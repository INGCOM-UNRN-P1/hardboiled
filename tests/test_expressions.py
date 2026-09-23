"""Expresiones C evaluadas sobre el programa detenido."""

from __future__ import annotations

import pytest

from hardboiled.core.debugger import DebuggerError
from hardboiled.core.expressions import tokenize
from hardboiled.core.machine import Machine
from tests.conftest import MachineFactory, line_of


@pytest.fixture
def machine(make_machine: MachineFactory) -> Machine:
    machine, _ = make_machine("types")
    machine.debugger.toggle_line_breakpoint(line_of("types.c", "medir_loop"), "types.c")
    machine.debugger.continue_()
    return machine


@pytest.mark.parametrize(
    ("expression", "expected"),
    [
        ("escala", "2"),
        ("escala * 3 + 1", "7"),
        ("-7 / 2", "-3"),  # C trunca hacia cero
        ("-7 % 2", "-1"),
        ("matriz[1][2]", "6"),
        ("f->vertices[1].x", "4"),
        ("(*f).color", "VERDE (5)"),
        ("f->color == 5 && escala > 1", "1"),
        ("!bandera || corto < 0", "1"),
        ("'A' + 1", "66"),
        ("0x10 | 0b1", "17"),
        ("1 << 4 >> 2", "4"),
        ("triangulo.nombre[0]", "116 't'"),
        ("*saludo", "104 'h'"),
        ("&triangulo == f", "1"),
        ("$a0 == $x10", "1"),
    ],
)
def test_expressions(machine: Machine, expression: str, expected: str) -> None:
    assert machine.debugger.evaluate(expression) == expected


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("noexiste", "no hay ninguna variable"),
        ("escala +", "termina antes de tiempo"),
        ("f->nada", "no tiene un campo"),
        ("escala[0]", "no se puede indexar"),
        ("*escala", "sólo se puede desreferenciar"),
        ("1 / 0", "división por cero"),
        ("$zz", "registro desconocido"),
        ("triangulo + 1", "como número"),
        ("escala @ 2", "símbolo inesperado"),
    ],
)
def test_expression_errors(machine: Machine, expression: str, message: str) -> None:
    with pytest.raises(DebuggerError, match=message):
        machine.debugger.evaluate(expression)


def test_tokenize_operators() -> None:
    kinds = [text for _, text in tokenize("p->x<=3&&!b")]
    assert kinds == ["p", "->", "x", "<=", "3", "&&", "!", "b"]
