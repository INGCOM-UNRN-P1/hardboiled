"""Inspección de variables con la información DWARF (`.debug_info`).

Se leen los DIEs de las unidades de compilación del usuario (las de fuentes C
disponibles) para conocer:

- variables globales y `static` (DW_OP_addr),
- parámetros y locales de cada función, con los bloques léxicos que limitan su
  alcance (el `int i` de un `for`),
- los tipos: base, punteros, arreglos, estructuras, uniones, enumeraciones,
  typedefs y calificadores.

Las ubicaciones soportadas son las que genera `-O0`: DW_OP_addr, DW_OP_fbreg,
DW_OP_bregN, DW_OP_regN y DW_OP_plus_uconst. Otras (listas de ubicaciones de
código optimizado) se muestran como "no disponible".
"""

from __future__ import annotations

import os
import struct
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from elftools.dwarf.dwarf_expr import DWARFExprParser
from elftools.elf.elffile import ELFFile

from hardboiled.core.dwarf import USER_SOURCE_SUFFIXES
from hardboiled.core.events import VariableInfo

MAX_ARRAY_ITEMS = 64
MAX_DEPTH = 4
MAX_STRING = 48

MemoryReader = Callable[[int, int], bytes | None]

DW_ATE_BOOLEAN = 0x02
DW_ATE_FLOAT = 0x04
DW_ATE_SIGNED = 0x05
DW_ATE_SIGNED_CHAR = 0x06
DW_ATE_UNSIGNED = 0x07
DW_ATE_UNSIGNED_CHAR = 0x08

QUALIFIERS = {
    "DW_TAG_const_type": "const",
    "DW_TAG_volatile_type": "volatile",
    "DW_TAG_restrict_type": "restrict",
}


# ------------------------------------------------------------------ tipos


@dataclass
class CType:
    """Tipo C reducido a lo necesario para leer y mostrar valores."""

    kind: str  # base, pointer, array, struct, union, enum, function, void
    name: str
    size: int
    encoding: int = 0
    target: CType | None = None  # apuntado / elemento
    count: int | None = None  # elementos de un arreglo
    members: list[tuple[str, int, CType, int | None, int]] = field(default_factory=list)
    # (nombre, offset en bytes, tipo, bits, offset de bits)
    enumerators: dict[int, str] = field(default_factory=dict)


VOID = CType("void", "void", 0)


def _name(die: Any) -> str | None:
    attr = die.attributes.get("DW_AT_name")
    if attr is None:
        return None
    value = attr.value
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _int_attr(die: Any, name: str) -> int | None:
    attr = die.attributes.get(name)
    return attr.value if attr is not None and isinstance(attr.value, int) else None


class TypeCache:
    def __init__(self) -> None:
        self._types: dict[int, CType] = {}

    def resolve(self, die: Any) -> CType:
        if "DW_AT_type" not in die.attributes:
            return VOID
        return self.of(die.get_DIE_from_attribute("DW_AT_type"))

    def of(self, die: Any) -> CType:
        cached = self._types.get(die.offset)
        if cached is not None:
            return cached
        tag = die.tag
        if tag == "DW_TAG_base_type":
            ctype = CType(
                "base",
                _name(die) or "?",
                _int_attr(die, "DW_AT_byte_size") or 0,
                _int_attr(die, "DW_AT_encoding") or 0,
            )
        elif tag == "DW_TAG_pointer_type":
            # Se registra antes de resolver el apuntado: listas enlazadas.
            ctype = CType("pointer", "*", 4)
            self._types[die.offset] = ctype
            ctype.target = self.resolve(die)
            if ctype.target.kind == "function":
                returns, _, params = ctype.target.name.partition(" (")
                ctype.name = f"{returns} (*)({params}"
            else:
                ctype.name = f"{ctype.target.name} *"
            return ctype
        elif tag in QUALIFIERS:
            inner = self.resolve(die)
            ctype = CType(**{**inner.__dict__, "name": f"{QUALIFIERS[tag]} {inner.name}"})
        elif tag == "DW_TAG_typedef":
            inner = self.resolve(die)
            ctype = CType(**{**inner.__dict__, "name": _name(die) or inner.name})
        elif tag == "DW_TAG_array_type":
            element = self.resolve(die)
            counts = []
            for child in die.iter_children():
                if child.tag != "DW_TAG_subrange_type":
                    continue
                count = _int_attr(child, "DW_AT_count")
                if count is None:
                    upper = _int_attr(child, "DW_AT_upper_bound")
                    count = upper + 1 if upper is not None else 0
                counts.append(count)
            counts = counts or [0]
            ctype = element
            # int m[2][3]: arreglo de 2 arreglos de 3 enteros (se arma de adentro hacia afuera).
            for depth in range(len(counts) - 1, -1, -1):
                dims = "".join(f"[{c}]" for c in counts[depth:])
                ctype = CType(
                    "array",
                    f"{element.name} {dims}",
                    ctype.size * counts[depth],
                    target=ctype,
                    count=counts[depth],
                )
        elif tag in ("DW_TAG_structure_type", "DW_TAG_union_type"):
            keyword = "struct" if tag == "DW_TAG_structure_type" else "union"
            ctype = CType(
                keyword,
                f"{keyword} {_name(die) or '(anónima)'}",
                _int_attr(die, "DW_AT_byte_size") or 0,
            )
            self._types[die.offset] = ctype
            for member in die.iter_children():
                if member.tag != "DW_TAG_member":
                    continue
                offset = _int_attr(member, "DW_AT_data_member_location") or 0
                bits = _int_attr(member, "DW_AT_bit_size")
                bit_offset = 0
                if bits is not None:
                    offset, bit_offset = _bitfield_position(member, offset, bits)
                ctype.members.append(
                    (_name(member) or "?", offset, self.resolve(member), bits, bit_offset)
                )
            return ctype
        elif tag == "DW_TAG_enumeration_type":
            ctype = CType(
                "enum",
                f"enum {_name(die) or '(anónima)'}",
                _int_attr(die, "DW_AT_byte_size") or 4,
                DW_ATE_SIGNED,
            )
            for child in die.iter_children():
                if child.tag == "DW_TAG_enumerator":
                    value = _int_attr(child, "DW_AT_const_value")
                    if value is not None:
                        ctype.enumerators[value] = _name(child) or "?"
        elif tag == "DW_TAG_subroutine_type":
            param_names = [
                self.resolve(child).name
                for child in die.iter_children()
                if child.tag == "DW_TAG_formal_parameter"
            ]
            signature = ", ".join(param_names) or "void"
            ctype = CType("function", f"{self.resolve(die).name} ({signature})", 4)
        else:
            ctype = CType("void", _name(die) or "?", 0)
        self._types[die.offset] = ctype
        return ctype


def _bitfield_position(member: Any, offset: int, bits: int) -> tuple[int, int]:
    """(offset de la palabra de 32 bits, bit menos significativo dentro de ella)."""
    absolute = _int_attr(member, "DW_AT_data_bit_offset")
    if absolute is None:
        # DWARF 2/3: DW_AT_bit_offset cuenta desde el bit más significativo de la unidad.
        legacy = _int_attr(member, "DW_AT_bit_offset") or 0
        unit = (_int_attr(member, "DW_AT_byte_size") or 4) * 8
        absolute = offset * 8 + unit - legacy - bits
    return (absolute // 32) * 4, absolute % 32


# --------------------------------------------------------------- variables


@dataclass
class VariableDecl:
    name: str
    ctype: CType
    location: list[Any] | None  # operaciones DWARF ya parseadas
    is_param: bool = False


@dataclass
class Scope:
    low: int
    high: int
    variables: list[VariableDecl] = field(default_factory=list)
    children: list[Scope] = field(default_factory=list)


@dataclass
class FunctionInfo:
    name: str
    scope: Scope
    frame_base: list[Any] | None


@dataclass(frozen=True)
class Storage:
    """Dónde vive un valor: en memoria o en un registro."""

    address: int | None
    register: int | None = None


@dataclass(frozen=True)
class FrameContext:
    """Lo necesario para evaluar ubicaciones en un marco de la pila."""

    pc: int
    cfa: int | None
    regs: dict[int, int]


class VariableTable:
    def __init__(self, functions: list[FunctionInfo], globals_: list[VariableDecl]) -> None:
        self.functions = sorted(functions, key=lambda f: f.scope.low)
        self.globals = sorted(globals_, key=lambda v: v.name)

    @classmethod
    def empty(cls) -> VariableTable:
        return cls([], [])

    @classmethod
    def from_elf(cls, path: str | Path) -> VariableTable:
        path = Path(path)
        functions: list[FunctionInfo] = []
        globals_: list[VariableDecl] = []
        with path.open("rb") as stream:
            elf = ELFFile(stream)
            if not elf.has_dwarf_info():
                return cls.empty()
            dwarf = elf.get_dwarf_info()
            for cu in dwarf.iter_CUs():
                top = cu.get_top_DIE()
                if not _is_user_cu(top, path):
                    continue
                parser = DWARFExprParser(cu.structs)
                types = TypeCache()
                for die in top.iter_children():
                    if die.tag == "DW_TAG_variable":
                        decl = _variable(die, parser, types)
                        if decl is not None and _has_real_address(decl):
                            globals_.append(decl)
                    elif die.tag == "DW_TAG_subprogram":
                        info = _function(die, parser, types)
                        if info is not None:
                            functions.append(info)
        return cls(functions, globals_)

    def function_at(self, pc: int) -> FunctionInfo | None:
        for function in self.functions:
            if function.scope.low <= pc < function.scope.high:
                return function
        return None

    def locals_at(self, pc: int) -> list[VariableDecl]:
        """Parámetros y locales visibles en `pc` (los bloques internos, al final)."""
        function = self.function_at(pc)
        if function is None:
            return []
        found: list[VariableDecl] = []
        scope: Scope | None = function.scope
        while scope is not None:
            found.extend(scope.variables)
            scope = next((c for c in scope.children if c.low <= pc < c.high), None)
        # Si una variable interna oculta a otra externa con el mismo nombre, gana la interna.
        unique: dict[str, VariableDecl] = {}
        for decl in found:
            unique.pop(decl.name, None)
            unique[decl.name] = decl
        return list(unique.values())

    def find(self, name: str, pc: int | None) -> VariableDecl | None:
        """Busca un nombre como lo haría C: primero locales, después globales."""
        if pc is not None:
            for decl in reversed(self.locals_at(pc)):
                if decl.name == name:
                    return decl
        return next((g for g in self.globals if g.name == name), None)

    def storage(self, decl: VariableDecl, frame: FrameContext | None) -> Storage | None:
        if decl.location is None:
            return None
        function = self.function_at(frame.pc) if frame is not None else None
        return _evaluate(decl.location, frame, function)


def _has_real_address(decl: VariableDecl) -> bool:
    """Descarta globales eliminadas por --gc-sections (quedan en la dirección 0)."""
    if not decl.location:
        return False
    first = decl.location[0]
    return not (first.op_name == "DW_OP_addr" and first.args[0] == 0)


def _is_user_cu(top: Any, elf_path: Path) -> bool:
    name = _name(top)
    if not name or Path(name).suffix not in USER_SOURCE_SUFFIXES:
        return False
    comp_dir_attr = top.attributes.get("DW_AT_comp_dir")
    comp_dir = comp_dir_attr.value.decode() if comp_dir_attr is not None else ""
    base = Path(comp_dir) if os.path.isabs(comp_dir) else elf_path.parent / comp_dir
    return (base / name).is_file()


def _location(die: Any, parser: DWARFExprParser, attribute: str) -> list[Any] | None:
    attr = die.attributes.get(attribute)
    if attr is None or attr.form not in ("DW_FORM_exprloc", "DW_FORM_block1", "DW_FORM_block"):
        return None
    return list(parser.parse_expr(attr.value))


def _variable(
    die: Any, parser: DWARFExprParser, types: TypeCache, is_param: bool = False
) -> VariableDecl | None:
    name = _name(die)
    if name is None:
        return None
    return VariableDecl(
        name, types.resolve(die), _location(die, parser, "DW_AT_location"), is_param
    )


def _pc_range(die: Any) -> tuple[int, int] | None:
    low = _int_attr(die, "DW_AT_low_pc")
    high_attr = die.attributes.get("DW_AT_high_pc")
    if low is None or high_attr is None:
        return None
    high = high_attr.value if high_attr.form == "DW_FORM_addr" else low + high_attr.value
    return low, high


def _scope(die: Any, parser: DWARFExprParser, types: TypeCache, low: int, high: int) -> Scope:
    scope = Scope(low, high)
    for child in die.iter_children():
        if child.tag in ("DW_TAG_formal_parameter", "DW_TAG_variable"):
            decl = _variable(child, parser, types, child.tag == "DW_TAG_formal_parameter")
            if decl is not None:
                scope.variables.append(decl)
        elif child.tag == "DW_TAG_lexical_block":
            bounds = _pc_range(child) or (low, high)
            scope.children.append(_scope(child, parser, types, *bounds))
    return scope


def _function(die: Any, parser: DWARFExprParser, types: TypeCache) -> FunctionInfo | None:
    bounds = _pc_range(die)
    name = _name(die)
    if bounds is None or name is None or bounds[0] == 0:
        return None
    return FunctionInfo(
        name, _scope(die, parser, types, *bounds), _location(die, parser, "DW_AT_frame_base")
    )


def _reg_number(op_name: str, prefix: str) -> int:
    return int(op_name.removeprefix(prefix))


def _frame_base(function: FunctionInfo | None, frame: FrameContext) -> int | None:
    if function is None or not function.frame_base:
        return None
    op = function.frame_base[0]
    if op.op_name == "DW_OP_call_frame_cfa":
        return frame.cfa
    if op.op_name.startswith("DW_OP_reg"):
        register = _reg_number(op.op_name, "DW_OP_reg")
        # A -O0 s0 termina siendo el CFA: usar el CFA vale también durante el prólogo,
        # cuando s0 todavía es el del llamador.
        if register == 8 and frame.cfa is not None:
            return frame.cfa
        return frame.regs.get(register)
    if op.op_name.startswith("DW_OP_breg"):
        base = frame.regs.get(_reg_number(op.op_name, "DW_OP_breg"))
        return None if base is None else base + op.args[0]
    return None


def _evaluate(
    ops: list[Any], frame: FrameContext | None, function: FunctionInfo | None
) -> Storage | None:
    stack: list[int] = []
    for op in ops:
        name = op.op_name
        if name == "DW_OP_addr":
            stack.append(op.args[0])
        elif name == "DW_OP_fbreg":
            base = _frame_base(function, frame) if frame is not None else None
            if base is None:
                return None
            stack.append(base + op.args[0])
        elif name.startswith("DW_OP_breg") and frame is not None:
            base = frame.regs.get(_reg_number(name, "DW_OP_breg"))
            if base is None:
                return None
            stack.append(base + op.args[0])
        elif name.startswith("DW_OP_reg") and frame is not None and len(ops) == 1:
            register = _reg_number(name, "DW_OP_reg")
            return Storage(None, register) if register in frame.regs else None
        elif name == "DW_OP_plus_uconst" and stack:
            stack.append(stack.pop() + op.args[0])
        else:
            return None
    return Storage(stack[-1] & 0xFFFF_FFFF) if stack else None


# ---------------------------------------------------------------- valores


class Formatter:
    """Convierte bytes de la memoria emulada en `VariableInfo` legibles."""

    def __init__(self, read: MemoryReader, describe: Callable[[int], str | None]) -> None:
        self.read = read
        self.describe = describe

    def variable(
        self,
        name: str,
        ctype: CType,
        storage: Storage | None,
        regs: dict[int, int],
        path: str = "",
    ) -> VariableInfo:
        path = f"{path}.{name}" if path and not name.startswith("[") else f"{path}{name}"
        if storage is None:
            return VariableInfo(name, ctype.name, "<no disponible>", None, path=path)
        if storage.register is not None:
            raw = regs[storage.register].to_bytes(4, "little")[: max(ctype.size, 1)]
            return self._value(name, ctype, raw, None, path, 0)
        return self._at(name, ctype, storage.address or 0, path, 0)

    def _at(self, name: str, ctype: CType, address: int, path: str, depth: int) -> VariableInfo:
        if ctype.kind in ("struct", "union", "array") or ctype.size == 0:
            return self._value(name, ctype, None, address, path, depth)
        raw = self.read(address, ctype.size)
        if raw is None:
            return VariableInfo(
                name, ctype.name, f"<sin acceso a 0x{address:08x}>", address, path=path
            )
        return self._value(name, ctype, raw, address, path, depth)

    def _value(
        self,
        name: str,
        ctype: CType,
        raw: bytes | None,
        address: int | None,
        path: str,
        depth: int,
    ) -> VariableInfo:
        kind = ctype.kind
        if kind == "array" and address is not None and ctype.target is not None:
            return self._array(name, ctype, address, path, depth)
        if kind in ("struct", "union") and address is not None:
            return self._struct(name, ctype, address, path, depth)
        if raw is None:
            return VariableInfo(name, ctype.name, "?", address, path=path)
        children: tuple[VariableInfo, ...] = ()
        if kind == "pointer" and depth < MAX_DEPTH:
            children = self._dereference(name, ctype, int.from_bytes(raw, "little"), path, depth)
        return VariableInfo(name, ctype.name, self.scalar(ctype, raw), address, children, path)

    def _dereference(
        self, name: str, ctype: CType, pointer: int, path: str, depth: int
    ) -> tuple[VariableInfo, ...]:
        """Lo apuntado como hijo expandible (`*p`), si es legible y tiene sentido mostrarlo."""
        target = ctype.target
        if target is None or target.kind in ("void", "function") or target.size == 0:
            return ()
        if pointer == 0 or self.read(pointer, target.size) is None:
            return ()
        return (self._at(f"*{name}", target, pointer, f"*({path})", depth + 1),)

    def scalar(self, ctype: CType, raw: bytes) -> str:
        unsigned = int.from_bytes(raw, "little")
        bits = len(raw) * 8
        signed = unsigned - (1 << bits) if bits and unsigned >> (bits - 1) else unsigned
        if ctype.kind == "pointer":
            return self._pointer(ctype, unsigned)
        if ctype.kind == "function":
            return self.describe(unsigned) or f"0x{unsigned:08x}"
        if ctype.kind == "enum":
            label = ctype.enumerators.get(signed)
            return f"{label} ({signed})" if label else str(signed)
        encoding = ctype.encoding
        if encoding == DW_ATE_BOOLEAN:
            return "true" if unsigned else "false"
        if encoding == DW_ATE_FLOAT and len(raw) in (4, 8):
            value = struct.unpack("<f" if len(raw) == 4 else "<d", raw)[0]
            return f"{value:g}"
        if encoding in (DW_ATE_SIGNED_CHAR, DW_ATE_UNSIGNED_CHAR) or (
            len(raw) == 1 and "char" in ctype.name
        ):
            number = signed if encoding == DW_ATE_SIGNED_CHAR else unsigned
            return f"{number} {_char_literal(unsigned)}"
        if encoding == DW_ATE_UNSIGNED:
            return str(unsigned) if unsigned < 0x10000 else f"{unsigned} (0x{unsigned:x})"
        return str(signed)

    def _pointer(self, ctype: CType, value: int) -> str:
        if value == 0:
            return "NULL"
        text = f"0x{value:08x}"
        target = ctype.target
        if target is not None and target.size == 1 and "char" in target.name:
            data = self.read(value, MAX_STRING) or b""
            end = data.find(b"\0")
            if data:
                fragment = data if end < 0 else data[:end]
                suffix = "…" if end < 0 else ""
                return f'{text} "{fragment.decode("utf-8", "replace")}{suffix}"'
        described = self.describe(value)
        return f"{text} → {described}" if described else text

    def _array(self, name: str, ctype: CType, address: int, path: str, depth: int) -> VariableInfo:
        element = ctype.target
        assert element is not None
        count = ctype.count or 0
        if element.size == 1 and "char" in element.name and count:
            data = self.read(address, count) or b""
            end = data.find(b"\0")
            text = data if end < 0 else data[:end]
            summary = f'"{text.decode("utf-8", "replace")}"'
        else:
            summary = ""
        children: list[VariableInfo] = []
        if depth < MAX_DEPTH:
            for index in range(min(count, MAX_ARRAY_ITEMS)):
                children.append(
                    self._at(
                        f"[{index}]",
                        element,
                        address + index * element.size,
                        f"{path}[{index}]",
                        depth + 1,
                    )
                )
        if not summary:
            shown = ", ".join(child.value for child in children[:8])
            more = ", …" if count > 8 else ""
            summary = f"{{{shown}{more}}}"
        return VariableInfo(name, ctype.name, summary, address, tuple(children), path)

    def _struct(self, name: str, ctype: CType, address: int, path: str, depth: int) -> VariableInfo:
        children: list[VariableInfo] = []
        if depth < MAX_DEPTH:
            for member, offset, mtype, bits, bit_offset in ctype.members:
                child_path = f"{path}.{member}"
                if bits is not None:
                    raw = self.read(address + offset, 4)
                    value = "?"
                    if raw is not None:
                        field_value = (int.from_bytes(raw, "little") >> bit_offset) & (
                            (1 << bits) - 1
                        )
                        value = str(field_value)
                    children.append(
                        VariableInfo(member, f"{mtype.name} : {bits}", value, None, (), child_path)
                    )
                else:
                    children.append(
                        self._at(member, mtype, address + offset, child_path, depth + 1)
                    )
        shown = ", ".join(f"{child.name} = {child.value}" for child in children[:4])
        more = ", …" if len(children) > 4 else ""
        return VariableInfo(name, ctype.name, f"{{{shown}{more}}}", address, tuple(children), path)


def _char_literal(code: int) -> str:
    escapes = {0: "\\0", 9: "\\t", 10: "\\n", 13: "\\r", 39: "\\'", 92: "\\\\"}
    if code in escapes:
        return f"'{escapes[code]}'"
    if 32 <= code < 127:
        return f"'{chr(code)}'"
    return f"'\\x{code:02x}'"
