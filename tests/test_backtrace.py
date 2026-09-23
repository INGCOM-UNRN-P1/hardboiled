"""Pila de llamadas: CFI, frame pointer e interrupciones."""

from __future__ import annotations

import os

import pytest

from hardboiled.core.unwind import CallFrameTable, Frame, Unwinder
from tests.conftest import MachineFactory, line_of


def summary(frames: list[Frame]) -> list[tuple[str | None, int | None]]:
    return [
        (f.function if f.irq_line is None else f"IRQ{f.irq_line}", f.location.line)
        if f.location
        else (f.function if f.irq_line is None else f"IRQ{f.irq_line}", None)
        for f in frames
    ]


def test_backtrace_inside_nested_calls(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("basic.c", "square_body"), "basic.c")
    debugger.continue_()
    frames = debugger.backtrace()
    assert summary(frames)[:3] == [
        ("square", line_of("basic.c", "square_body")),
        ("sum_squares", line_of("basic.c", "sum_call")),
        ("main", line_of("basic.c", "main_first")),
    ]
    # El último marco es crt0, que llamó a main().
    assert frames[-1].location is not None
    assert os.path.basename(frames[-1].location.file) == "crt0.s"


def test_backtrace_at_function_entry_uses_cfi(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    square = machine.image.symbol_address("square")
    assert square is not None
    machine.debugger.toggle_address_breakpoint(square)
    machine.debugger.continue_()  # prólogo sin ejecutar: ra todavía en el registro
    functions = [f.function for f in machine.debugger.backtrace()]
    assert functions[:3] == ["square", "sum_squares", "main"]


def test_backtrace_recursion(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("basic.c", "fact_recurse"), "basic.c")
    for _ in range(4):
        debugger.continue_()
    frames = debugger.backtrace()
    assert [f.function for f in frames[:5]] == ["factorial"] * 4 + ["main"]
    cfas = [f.cfa for f in frames[:5] if f.cfa is not None]
    assert len(cfas) == 5 and cfas == sorted(cfas)  # cada llamador está más arriba


def test_backtrace_crosses_interrupt(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("mmio")
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("mmio.c", "isr_body"), "mmio.c")
    debugger.continue_()
    frames = debugger.backtrace()
    assert frames[0].function == "on_timer"
    assert frames[1].irq_line == 0
    interrupted = [f.function for f in frames[2:]]
    assert "main" in interrupted


@pytest.mark.parametrize("breakpoint", ["square_body", "fact_recurse"])
def test_frame_pointer_fallback_matches_cfi(make_machine: MachineFactory, breakpoint: str) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("basic.c", breakpoint), "basic.c")
    debugger.continue_()
    with_cfi = summary(debugger.backtrace())
    without = Unwinder(machine.image, machine.lines, CallFrameTable.empty()).unwind(machine.cpu)
    # Sin CFI se reconstruye igual (salvo el marco de crt0, que no usa s0).
    assert summary(without)[: len(with_cfi) - 1] == with_cfi[:-1]


def test_step_out_returns_to_caller_with_value(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("basic.c", "square_body"), "basic.c")
    debugger.continue_()
    debugger.toggle_line_breakpoint(line_of("basic.c", "square_body"), "basic.c")
    stop = debugger.step_out()
    assert debugger.function() == "sum_squares"
    assert "square devolvió a0 = 1" in stop.message


def test_step_out_of_recursion_leaves_one_level(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("basic.c", "fact_recurse"), "basic.c")
    for _ in range(3):
        debugger.continue_()
    depth = len(debugger.backtrace())
    debugger.toggle_line_breakpoint(line_of("basic.c", "fact_recurse"), "basic.c")
    stop = debugger.step_out()
    assert len(debugger.backtrace()) == depth - 1
    assert debugger.function() == "factorial"
    assert "devolvió a0 = 6" in stop.message  # factorial(3) volviendo a factorial(4)


def test_step_out_of_interrupt(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("mmio")
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("mmio.c", "isr_body"), "mmio.c")
    debugger.continue_()
    debugger.toggle_line_breakpoint(line_of("mmio.c", "isr_body"), "mmio.c")
    stop = debugger.step_out()
    assert not machine.pic.in_isr
    assert "fin de la interrupción" in stop.message


def test_step_out_without_caller(make_machine: MachineFactory) -> None:
    from hardboiled.core.debugger import DebuggerError

    machine, _ = make_machine("basic")  # en _start, sin llamador
    with pytest.raises(DebuggerError):
        machine.debugger.step_out()
