"""Expresiones C sobre el estado del programa: `results[1]`, `f->color`, `i == 3`.

Un parser descendente recursivo para el subconjunto de C que tiene sentido en
un depurador:

- primarias: identificadores (locales, parámetros o globales), números
  (decimales, 0x…, 0b…), caracteres ('a'), registros ($a0, $sp, $pc, $x5) y
  paréntesis;
- postfijas: `a[i]`, `s.campo`, `p->campo`;
- unarias: `-`, `!`, `~`, `*p`, `&x`;
- binarias con la precedencia de C: `* / %`, `+ -`, `<< >>`, `< <= > >=`,
  `== !=`, `&`, `^`, `|`, `&&`, `||`.

El resultado conserva la dirección y el tipo cuando la expresión designa un
objeto en memoria (un *lvalue*), que es lo que necesita un watchpoint.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass

from hardboiled.core.cpu import ABI_NAMES
from hardboiled.core.variables import CType, FrameContext, VariableTable
from hardboiled.i18n import _

INT = CType("base", "int", 4, 0x05)


class ExpressionError(Exception):
    pass


@dataclass(frozen=True)
class Value:
    ctype: CType
    address: int | None = None  # dirección si es un objeto en memoria
    constant: int | None = None  # valor si es un resultado calculado

    @property
    def is_lvalue(self) -> bool:
        return self.address is not None


TOKEN = re.compile(
    r"\s*(?:(?P<number>0[xX][0-9a-fA-F]+|0[bB][01]+|\d+)"
    r"|(?P<char>'(?:\\.|[^'\\])')"
    r"|(?P<register>\$[a-zA-Z0-9]+)"
    r"|(?P<name>[A-Za-z_]\w*)"
    r"|(?P<op>->|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%<>!~&|^()\[\].]))"
)

BINARY_LEVELS: list[tuple[str, ...]] = [
    ("||",),
    ("&&",),
    ("|",),
    ("^",),
    ("&",),
    ("==", "!="),
    ("<", "<=", ">", ">="),
    ("<<", ">>"),
    ("+", "-"),
    ("*", "/", "%"),
]

ESCAPES = {"n": 10, "t": 9, "r": 13, "0": 0, "\\": 92, "'": 39}

REGISTER_ALIASES = {name: index for index, name in enumerate(ABI_NAMES)} | {"fp": 8}


def tokenize(text: str) -> list[tuple[str, str]]:
    tokens: list[tuple[str, str]] = []
    position = 0
    text = text.rstrip()
    while position < len(text):
        match = TOKEN.match(text, position)
        if match is None or match.end() == position:
            raise ExpressionError(
                _(
                    "símbolo inesperado en la posición {position}: {text}",
                    position=position + 1,
                    text=repr(text),
                )
            )
        kind = match.lastgroup
        assert kind is not None
        tokens.append((kind, match.group(kind)))
        position = match.end()
    return tokens


class Evaluator:
    """Evalúa expresiones en el contexto de un marco (o sólo con globales)."""

    def __init__(
        self,
        variables: VariableTable,
        read: Callable[[int, int], bytes | None],
        frame: FrameContext | None,
        pc: int | None = None,
    ) -> None:
        self.variables = variables
        self.read = read
        self.frame = frame
        self.pc = pc
        # Si la expresión usó alguna variable local (su valor depende del marco).
        self.used_locals = False

    # --------------------------------------------------------------- entrada

    def evaluate(self, text: str) -> Value:
        self._tokens = tokenize(text)
        self._index = 0
        if not self._tokens:
            raise ExpressionError(_("la expresión está vacía"))
        value = self._binary(0)
        if self._index != len(self._tokens):
            raise ExpressionError(
                _(
                    "sobra texto después de la posición {position}: {text}",
                    position=self._index,
                    text=repr(text),
                )
            )
        return value

    def integer(self, text: str) -> int:
        return self.load(self.evaluate(text))

    # ------------------------------------------------------------- valores

    def load(self, value: Value) -> int:
        if value.constant is not None:
            return value.constant
        ctype = value.ctype
        if ctype.kind == "array":  # un arreglo "decae" a puntero a su primer elemento
            return value.address or 0
        if ctype.kind in ("struct", "union"):
            raise ExpressionError(_("no se puede usar un {type} como número", type=ctype.name))
        size = min(max(ctype.size, 1), 8)
        raw = self.read(value.address or 0, size)
        if raw is None:
            raise ExpressionError(
                _("no se puede leer la memoria en {address}", address=f"0x{value.address or 0:08x}")
            )
        number = int.from_bytes(raw, "little")
        signed = ctype.kind == "enum" or ctype.encoding in (0x05, 0x06)
        if signed and number >> (size * 8 - 1):
            number -= 1 << (size * 8)
        return number

    # -------------------------------------------------------------- parser

    def _peek(self) -> tuple[str, str] | None:
        return self._tokens[self._index] if self._index < len(self._tokens) else None

    def _accept(self, *ops: str) -> str | None:
        token = self._peek()
        if token is not None and token[0] == "op" and token[1] in ops:
            self._index += 1
            return token[1]
        return None

    def _expect(self, op: str) -> None:
        if self._accept(op) is None:
            raise ExpressionError(_("se esperaba '{token}'", token=op))

    def _binary(self, level: int) -> Value:
        if level == len(BINARY_LEVELS):
            return self._unary()
        left = self._binary(level + 1)
        while (op := self._accept(*BINARY_LEVELS[level])) is not None:
            right = self._binary(level + 1)
            left = Value(INT, constant=self._apply(op, self.load(left), self.load(right)))
        return left

    @staticmethod
    def _apply(op: str, a: int, b: int) -> int:
        if op in ("/", "%") and b == 0:
            raise ExpressionError(_("división por cero en la expresión"))
        results: dict[str, Callable[[], int]] = {
            "||": lambda: int(bool(a) or bool(b)),
            "&&": lambda: int(bool(a) and bool(b)),
            "|": lambda: a | b,
            "^": lambda: a ^ b,
            "&": lambda: a & b,
            "==": lambda: int(a == b),
            "!=": lambda: int(a != b),
            "<": lambda: int(a < b),
            "<=": lambda: int(a <= b),
            ">": lambda: int(a > b),
            ">=": lambda: int(a >= b),
            "<<": lambda: a << b,
            ">>": lambda: a >> b,
            "+": lambda: a + b,
            "-": lambda: a - b,
            "*": lambda: a * b,
            "/": lambda: int(a / b),  # C trunca hacia cero
            "%": lambda: a - int(a / b) * b,
        }
        return results[op]()

    def _unary(self) -> Value:
        op = self._accept("-", "!", "~", "*", "&", "+")
        if op is None:
            return self._postfix()
        operand = self._unary()
        if op == "*":
            return self._deref(operand)
        if op == "&":
            if operand.address is None:
                raise ExpressionError(_("& necesita una variable en memoria"))
            return Value(INT, constant=operand.address)
        number = self.load(operand)
        result = {"-": -number, "!": int(not number), "~": ~number, "+": number}[op]
        return Value(INT, constant=result)

    def _deref(self, pointer: Value) -> Value:
        target = pointer.ctype.target
        if pointer.ctype.kind not in ("pointer", "array") or target is None:
            raise ExpressionError(_("sólo se puede desreferenciar un puntero"))
        if target.kind in ("void", "function"):
            raise ExpressionError(
                _("no se puede desreferenciar un {type}", type=pointer.ctype.name)
            )
        return Value(target, address=self.load(pointer) & 0xFFFF_FFFF)

    def _postfix(self) -> Value:
        value = self._primary()
        while True:
            if self._accept("["):
                index = self.load(self._binary(0))
                self._expect("]")
                element = value.ctype.target
                if value.ctype.kind not in ("array", "pointer") or element is None:
                    raise ExpressionError(_("{type} no se puede indexar", type=value.ctype.name))
                base = value.address if value.ctype.kind == "array" else self.load(value)
                value = Value(element, address=((base or 0) + index * element.size) & 0xFFFF_FFFF)
            elif (op := self._accept(".", "->")) is not None:
                token = self._peek()
                if token is None or token[0] != "name":
                    raise ExpressionError(
                        _("se esperaba un nombre de campo después de '{token}'", token=op)
                    )
                self._index += 1
                if op == "->":
                    value = self._deref(value)
                value = self._member(value, token[1])
            else:
                return value

    @staticmethod
    def _member(value: Value, name: str) -> Value:
        ctype = value.ctype
        if ctype.kind not in ("struct", "union"):
            raise ExpressionError(_("{type} no tiene campos", type=ctype.name))
        for member, offset, mtype, bits, _bit_offset in ctype.members:
            if member == name:
                if bits is not None:
                    raise ExpressionError(
                        _("{name} es un campo de bits: no tiene dirección", name=name)
                    )
                return Value(mtype, address=(value.address or 0) + offset)
        raise ExpressionError(
            _("{type} no tiene un campo {name}", type=ctype.name, name=repr(name))
        )

    def _primary(self) -> Value:
        token = self._peek()
        if token is None:
            raise ExpressionError(_("la expresión termina antes de tiempo"))
        kind, text = token
        self._index += 1
        if kind == "number":
            return Value(INT, constant=int(text, 0))
        if kind == "char":
            body = text[1:-1]
            code = ESCAPES.get(body[1], ord(body[1])) if body.startswith("\\") else ord(body)
            return Value(INT, constant=code)
        if kind == "register":
            return Value(INT, constant=self._register(text[1:]))
        if kind == "name":
            return self._variable(text)
        if text == "(":
            value = self._binary(0)
            self._expect(")")
            return value
        raise ExpressionError(_("no se esperaba '{token}'", token=text))

    def _register(self, name: str) -> int:
        if self.frame is None:
            raise ExpressionError(
                _("los registros sólo están disponibles con el programa detenido")
            )
        if name == "pc":
            return self.frame.pc
        if name.startswith("x") and name[1:].isdigit() and int(name[1:]) < 32:
            index = int(name[1:])
        elif name in REGISTER_ALIASES:
            index = REGISTER_ALIASES[name]
        else:
            raise ExpressionError(_("registro desconocido: ${name}", name=name))
        value = self.frame.regs.get(index)
        if value is None:
            raise ExpressionError(_("${name} no se conoce en este marco", name=name))
        return value

    def _variable(self, name: str) -> Value:
        pc = self.frame.pc if self.frame is not None else self.pc
        decl = self.variables.find(name, pc)
        if decl is None:
            raise ExpressionError(_("no hay ninguna variable {name} visible aquí", name=repr(name)))
        if pc is not None and any(local is decl for local in self.variables.locals_at(pc)):
            self.used_locals = True
        storage = self.variables.storage(decl, self.frame)
        if storage is None:
            raise ExpressionError(_("la ubicación de {name} no está disponible", name=repr(name)))
        if storage.register is not None:
            assert self.frame is not None
            return Value(decl.ctype, constant=self.frame.regs[storage.register])
        return Value(decl.ctype, address=storage.address)
