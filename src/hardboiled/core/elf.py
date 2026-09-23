"""Carga de binarios ELF RV32: segmentos cargables y tabla de símbolos."""

from __future__ import annotations

import bisect
import re
import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

PF_X = 0x1
PF_W = 0x2
PF_R = 0x4
EF_RISCV_RVC = 0x1


class ElfLoadError(Exception):
    pass


@dataclass(frozen=True)
class Segment:
    vaddr: int
    paddr: int
    data: bytes
    memsz: int
    flags: int

    @property
    def executable(self) -> bool:
        return bool(self.flags & PF_X)

    @property
    def permissions(self) -> str:
        return "".join(
            char if self.flags & bit else "-"
            for char, bit in (("R", PF_R), ("W", PF_W), ("X", PF_X))
        )


@dataclass(frozen=True)
class Symbol:
    name: str
    address: int
    size: int
    kind: str  # "func" | "object" | "other"


STT_OBJECT = 1
STT_FUNC = 2
STT_SECTION = 3
STT_FILE = 4


def _read_symbols(elf: ELFFile) -> list[Symbol]:
    """Lee .symtab desempaquetando Elf32_Sym directamente.

    pyelftools crea un objeto por símbolo, y compiler-rt aporta miles: leer los
    registros de 16 bytes con struct es decenas de veces más rápido.
    """
    symtab = elf.get_section_by_name(".symtab")
    if not isinstance(symtab, SymbolTableSection):
        return []
    strtab = symtab.stringtable.data()
    symbols = []
    for name_offset, value, size, info, _other, _shndx in struct.iter_unpack(
        "<IIIBBH", symtab.data()
    ):
        sym_type = info & 0xF
        if name_offset == 0 or sym_type in (STT_SECTION, STT_FILE):
            continue
        end = strtab.index(b"\0", name_offset)
        name = strtab[name_offset:end].decode("utf-8", "replace")
        kind = "func" if sym_type == STT_FUNC else "object" if sym_type == STT_OBJECT else "other"
        symbols.append(Symbol(name, value, size, kind))
    return symbols


TAG_RISCV_ARCH = 5


def _uleb128(data: bytes, index: int) -> tuple[int, int]:
    value = shift = 0
    while True:
        byte = data[index]
        index += 1
        value |= (byte & 0x7F) << shift
        shift += 7
        if not byte & 0x80:
            return value, index


def _arch_attribute(elf: ELFFile) -> str | None:
    """Tag_RISCV_arch de .riscv.attributes (p. ej. "rv32i2p1_m2p0"), si está."""
    section = elf.get_section_by_name(".riscv.attributes")
    if section is None:
        return None
    data = section.data()
    if not data or data[0:1] != b"A":
        return None
    try:
        index = 1
        while index < len(data):
            length = int.from_bytes(data[index : index + 4], "little")
            end = index + length
            vendor_end = data.index(b"\0", index + 4)
            if data[index + 4 : vendor_end] != b"riscv":
                index = end
                continue
            cursor = vendor_end + 1
            while cursor < end:
                cursor += 1  # etiqueta del subsubsección (1 = archivo completo)
                size = int.from_bytes(data[cursor : cursor + 4], "little")
                block_end = cursor - 1 + size
                cursor += 4
                while cursor < block_end:
                    tag, cursor = _uleb128(data, cursor)
                    if tag % 2:  # etiquetas impares: cadena terminada en NUL
                        stop = data.index(b"\0", cursor)
                        text = data[cursor:stop].decode("ascii", "replace")
                        cursor = stop + 1
                        if tag == TAG_RISCV_ARCH:
                            return text
                    else:
                        _, cursor = _uleb128(data, cursor)
            index = end
    except (IndexError, ValueError):
        return None
    return None


def _extensions(arch: str | None) -> set[str]:
    """Extensiones de una letra de "rv32i2p1_m2p0_c2p0" -> {"m", "c"}."""
    if not arch:
        return set()
    found: set[str] = set()
    for part in arch.lower().split("_"):
        if part.startswith("rv32"):
            letters = re.sub(r"\d+p\d+", "", part[4:])  # quitar versiones como 2p1
            found.update(letter for letter in letters if letter not in "ie")
        elif part and part[0] in "mafdcvbq" and not part.startswith(("z", "x", "s")):
            found.add(part[0])
    return found


class ElfImage:
    def __init__(
        self, path: Path, entry: int, segments: list[Segment], symbols: list[Symbol]
    ) -> None:
        self.path = path
        self.entry = entry
        # Arquitectura declarada por el compilador (Tag_RISCV_arch) y extensiones
        # estándar de una letra además de la base I ("m", "c"…).
        self.arch: str | None = None
        self.extensions: frozenset[str] = frozenset()
        self.segments = segments
        self.symbols = {sym.name: sym for sym in symbols}
        self._functions = sorted(
            (s for s in symbols if s.kind == "func" and s.size > 0), key=lambda s: s.address
        )
        self._function_starts = [s.address for s in self._functions]
        self._objects = [s for s in symbols if s.kind == "object" and s.size > 0]
        code = [seg for seg in segments if seg.executable]
        self._labels = sorted(
            (
                s
                for s in symbols
                if s.kind in ("func", "other")
                and not s.name.startswith((".L", "$"))
                and any(seg.vaddr <= s.address < seg.vaddr + seg.memsz for seg in code)
            ),
            # A igual dirección, la función queda última y bisect_right la prefiere.
            key=lambda s: (s.address, s.kind == "func"),
        )
        self._label_starts = [s.address for s in self._labels]

    @classmethod
    def load(cls, path: str | Path) -> ElfImage:
        path = Path(path)
        try:
            with path.open("rb") as stream:
                elf = ELFFile(stream)
                if elf["e_machine"] != "EM_RISCV" or elf.elfclass != 32:
                    raise ElfLoadError(
                        f"{path.name} no es un ELF RISC-V de 32 bits "
                        f"(máquina {elf['e_machine']}, clase {elf.elfclass})"
                    )
                arch = _arch_attribute(elf)
                extensions = _extensions(arch)
                if elf["e_flags"] & EF_RISCV_RVC:
                    extensions.add("c")
                segments = [
                    Segment(
                        vaddr=seg["p_vaddr"],
                        paddr=seg["p_paddr"],
                        data=seg.data(),
                        memsz=seg["p_memsz"],
                        flags=seg["p_flags"],
                    )
                    for seg in elf.iter_segments()
                    if seg["p_type"] == "PT_LOAD"
                ]
                symbols = _read_symbols(elf)
                entry = elf["e_entry"]
        except (OSError, ELFError) as exc:
            raise ElfLoadError(f"no se pudo leer {path}: {exc}") from exc
        if not segments:
            raise ElfLoadError(f"{path.name} no tiene segmentos PT_LOAD")
        image = cls(path, entry, segments, symbols)
        image.arch = arch
        image.extensions = frozenset(extensions)
        return image

    def symbol_address(self, name: str) -> int | None:
        sym = self.symbols.get(name)
        return sym.address if sym is not None else None

    def function_at(self, address: int) -> str | None:
        idx = bisect.bisect_right(self._function_starts, address) - 1
        if idx < 0:
            return None
        func = self._functions[idx]
        return func.name if address < func.address + func.size else None

    def object_at(self, address: int) -> str | None:
        """Variable (símbolo de datos) que ocupa `address`."""
        for symbol in self._objects:
            if symbol.address <= address < symbol.address + max(symbol.size, 1):
                return symbol.name
        return None

    def nearest_symbol(self, address: int) -> tuple[str, int] | None:
        """Símbolo (incluidas etiquetas de ensamblador) más cercano por debajo: (nombre, offset)."""
        idx = bisect.bisect_right(self._label_starts, address) - 1
        if idx < 0:
            return None
        label = self._labels[idx]
        return label.name, address - label.address

    def describe(self, address: int) -> str:
        """`funcion+0x1c` para mostrar direcciones de código."""
        found = self.nearest_symbol(address)
        if found is None:
            return f"0x{address:08x}"
        name, offset = found
        return f"{name}+0x{offset:x}" if offset else name

    def code_words(self) -> Iterator[tuple[int, int]]:
        """Palabras de 32 bits alineadas de los segmentos ejecutables (dirección de ejecución)."""
        for seg in self.segments:
            if not seg.executable:
                continue
            data = seg.data
            for offset in range(0, len(data) - 3, 4):
                yield seg.vaddr + offset, int.from_bytes(data[offset : offset + 4], "little")
