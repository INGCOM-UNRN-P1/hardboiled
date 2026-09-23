"""Breakpoints condicionales y por cantidad de pasadas."""

from __future__ import annotations

import pytest

from hardboiled.core.cpu import StopReason
from hardboiled.core.debugger import DebuggerError
from hardboiled.ui.tui import parse_condition
from tests.conftest import MachineFactory, line_of


def test_condition_on_loop_variable(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.set_condition(line_of("basic.c", "sum_call"), "basic.c", "i == 3")
    stop = debugger.continue_()
    assert stop.reason is StopReason.BREAK
    assert debugger.evaluate("i") == "3"
    assert "i == 3 es verdadera" in stop.message
    assert debugger.continue_().exit_code == 134  # no vuelve a cumplirse


def test_hit_count(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.set_condition(line_of("basic.c", "square_body"), "basic.c", hit_target=2)
    stop = debugger.continue_()
    assert debugger.evaluate("x") == "2"  # la primera pasada (x = 1) no detuvo
    assert "pasada 2" in stop.message
    debugger.continue_()
    assert debugger.evaluate("x") == "3"  # desde la pasada N detiene siempre


def test_condition_and_hit_count_combined(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.set_condition(line_of("basic.c", "fact_recurse"), "basic.c", "n <= 3", 2)
    debugger.continue_()
    assert debugger.evaluate("n") == "2"  # n=3 fue la primera pasada verdadera


def test_invalid_condition(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    with pytest.raises(DebuggerError, match="condición inválida"):
        debugger.set_condition(line_of("basic.c", "sum_call"), "basic.c", "i @@ 3")
    # Una condición que falla al evaluarse detiene y lo informa.
    debugger.set_condition(line_of("basic.c", "sum_call"), "basic.c", "no_existe > 0")
    stop = debugger.continue_()
    assert "no se pudo evaluar la condición" in stop.message


def test_removing_condition_keeps_breakpoint(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    line = line_of("basic.c", "sum_call")
    debugger.set_condition(line, "basic.c", "i == 3")
    debugger.set_condition(line, "basic.c", None)
    assert debugger.conditions == {}
    debugger.continue_()
    assert debugger.evaluate("i") == "1"


def test_parse_condition() -> None:
    assert parse_condition("i == 3 #5") == ("i == 3", 5)
    assert parse_condition("#2") == (None, 2)
    assert parse_condition("  ") == (None, None)
    with pytest.raises(ValueError):
        parse_condition("i > 0 #cero")
