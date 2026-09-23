"""Formatos de los registros en la TUI y registros con símbolo."""

from __future__ import annotations

from hardboiled.core.runner import snapshot
from hardboiled.ui.widgets.registers_view import format_value
from tests.conftest import MachineFactory, line_of


def test_formats() -> None:
    assert format_value(0xFFFFFFFE, "hex").strip() == "fffffffe"
    assert format_value(0xFFFFFFFE, "con signo").strip() == "-2"
    assert format_value(0xFFFFFFFE, "sin signo").strip() == "4294967294"
    assert format_value(0x616C6F68, "ascii").strip() == "'hola'"
    assert format_value(0x10, "ascii").strip() == "'····'"
    assert format_value(0x10158, "símbolo", "main+0x2c").strip() == "main+0x2c"
    assert format_value(0x10158, "símbolo", None).strip() == "00010158"


def test_register_symbols_name_code_and_globals(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    machine.debugger.toggle_line_breakpoint(line_of("basic.c", "square_body"), "basic.c")
    machine.debugger.continue_()
    event = snapshot(machine)
    assert event.register_symbols["pc"].startswith("square")
    assert event.register_symbols["x1"].startswith("sum_squares+")  # ra
    assert "x2" not in event.register_symbols  # sp apunta a la pila, sin nombre
