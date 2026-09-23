"""Watchpoints: detenerse cuando cambia una variable."""

from __future__ import annotations

import pytest

from hardboiled.core.cpu import StopReason
from hardboiled.core.debugger import DebuggerError
from tests.conftest import MachineFactory, line_of


def test_global_watchpoint_reports_old_and_new_value(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.run_to_main()
    debugger.add_watchpoint("results[1]")
    stop = debugger.continue_()
    assert stop.reason is StopReason.BREAK
    assert stop.message.startswith("watchpoint results[1]: 0 → 120")
    assert "basic.c:" in stop.message
    # Se detiene después de la escritura: la línea que escribió es la anterior.
    assert debugger.evaluate("results[1]") == "120"
    assert debugger.continue_().exit_code == 134


def test_writes_that_do_not_change_the_value_are_ignored(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("mmio")
    debugger = machine.debugger
    debugger.run_to_main()
    debugger.add_watchpoint("ticks")
    stops = []
    for _ in range(3):
        stop = debugger.continue_()
        stops.append(stop.message)
        assert "watchpoint ticks" in stop.message
    assert [m.split(":")[1].split("(")[0].strip() for m in stops] == ["0 → 1", "1 → 2", "2 → 3"]


def test_local_watchpoint_is_removed_when_function_returns(
    make_machine: MachineFactory,
) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("basic.c", "sum_first"), "basic.c")
    debugger.continue_()
    debugger.toggle_line_breakpoint(line_of("basic.c", "sum_first"), "basic.c")
    debugger.add_watchpoint("total")
    messages = []
    for _ in range(10):
        stop = debugger.continue_()
        messages.append(stop.message)
        if not debugger.watchpoints or stop.reason is not StopReason.BREAK:
            break
    assert any("watchpoint total: 0 → 1" in m for m in messages)
    assert "eliminado al salir de su función: total" in messages[-1]
    assert debugger.watchpoints == ()


def test_toggle_and_errors(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.run_to_main()
    assert debugger.toggle_watchpoint("counter") is True
    assert debugger.toggle_watchpoint("counter") is False
    with pytest.raises(DebuggerError, match="no es una variable en memoria"):
        debugger.add_watchpoint("counter + 1")
    with pytest.raises(DebuggerError, match="no hay ninguna variable"):
        debugger.add_watchpoint("nada")


def test_watchpoints_survive_reset(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.run_to_main()
    debugger.add_watchpoint("results[0]")
    machine.reset()
    debugger.run_to_main()
    stop = debugger.continue_()
    assert "watchpoint results[0]: 0 → 14" in stop.message
