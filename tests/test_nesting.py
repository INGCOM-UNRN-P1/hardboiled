"""Prioridades y anidamiento de interrupciones."""

from __future__ import annotations

import importlib.util
import tomllib
from pathlib import Path

import pytest

from hardboiled.config import BoardConfig
from hardboiled.core.cpu import StopReason
from hardboiled.core.machine import Machine
from hardboiled.core.pic import InterruptController
from hardboiled.sdk import runtime_for
from hardboiled.toolchain import BuildOptions, build, select_compiler

needs_zig = pytest.mark.skipif(
    importlib.util.find_spec("ziglang") is None, reason="requiere el extra [zig]"
)


def enabled_pic(**kwargs: object) -> InterruptController:
    pic = InterruptController(**kwargs)  # type: ignore[arg-type]
    pic.write(0x0, 0xFF, 0xFF)
    pic.write(0x8, 1, 0xFF)
    return pic


def test_priorities_choose_the_most_urgent_line() -> None:
    pic = enabled_pic(priorities=[5, 4, 3, 2, 1, 0, 6, 7])
    pic.raise_irq(1)
    pic.raise_irq(4)
    assert pic.next_irq() == 4  # prioridad 1 contra 4


def test_without_nesting_the_active_isr_blocks_everything() -> None:
    pic = enabled_pic()
    pic.raise_irq(3)
    pic.acknowledge(3)
    pic.raise_irq(0)  # más urgente, pero sin anidamiento espera
    assert not pic.ready and pic.read(0xC) == 3
    pic.complete()
    assert pic.ready and pic.read(0xC) == 0xFFFFFFFF


def test_nesting_preempts_only_with_higher_priority() -> None:
    pic = enabled_pic(nesting=True)
    pic.raise_irq(3)
    pic.acknowledge(3)
    pic.raise_irq(5)  # menos urgente: espera
    assert not pic.ready
    pic.raise_irq(1)  # más urgente: interrumpe
    assert pic.ready and pic.next_irq() == 1
    pic.acknowledge(1)
    assert pic.depth == 2 and pic.active_line == 1
    pic.complete()
    assert pic.active_line == 3


def test_board_validates_priorities() -> None:
    with pytest.raises(ValueError, match="8 valores"):
        BoardConfig.model_validate({"pic": {"priorities": [0, 1]}})


BOARD = """\
[board]
name = "dos-timers"
max_instructions = 3_000_000

[pic]
priorities = [1, 0, 2, 3, 4, 5, 6, 7]  # el timer rápido (línea 1) es más urgente
nesting = {nesting}

[[peripherals]]
name = "uart0"
type = "uart"
offset = "0x10"

[[peripherals]]
name = "lento"
type = "timer"
offset = "0x20"
irq_line = 0

[[peripherals]]
name = "rapido"
type = "timer"
offset = "0x50"
irq_line = 1
"""

PROGRAM = """\
#include "hardboiled.h"

volatile int dentro, lentas, rapidas, anidadas;

static void on_lento(void)
{
    dentro = 1;
    for (volatile int i = 0; i < 400; i++) {
    }
    dentro = 0;
    lentas++;
}

static void on_rapido(void)
{
    rapidas++;
    if (dentro) {
        anidadas++; /* @anidada */
    }
}

int main(void)
{
    attach_irq(IRQ_LENTO, on_lento);
    attach_irq(IRQ_RAPIDO, on_rapido);
    timer_start(20000, 1);
    rapido_start(700, 1);
    interrupts_enable();
    while (lentas < 3) {
        wait_for_interrupt();
    }
    return anidadas;
}
"""


def build_program(tmp_path: Path, nesting: bool) -> Machine:
    board = BoardConfig.model_validate(tomllib.loads(BOARD.format(nesting=str(nesting).lower())))
    source = tmp_path / "anida.c"
    source.write_text(PROGRAM)
    options = BuildOptions(runtime=runtime_for(board, tmp_path / "cache"))
    elf = build([source], tmp_path / "anida.elf", options, select_compiler("zig")).output
    return Machine.from_elf(elf, board)


@needs_zig
@pytest.mark.parametrize("nesting", [False, True])
def test_firmware_nesting(tmp_path: Path, nesting: bool) -> None:
    machine = build_program(tmp_path, nesting)
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.EXITED
    if nesting:
        assert stop.exit_code is not None and stop.exit_code > 0
    else:
        assert stop.exit_code == 0


@needs_zig
def test_backtrace_through_nested_interrupts(tmp_path: Path) -> None:
    machine = build_program(tmp_path, nesting=True)
    debugger = machine.debugger
    line = next(n for n, text in enumerate(PROGRAM.splitlines(), start=1) if "@anidada" in text)
    debugger.toggle_line_breakpoint(line, "anida.c")
    stop = debugger.continue_()
    assert stop.reason is StopReason.BREAK
    assert machine.pic.depth == 2
    frames = debugger.backtrace()
    assert [f.irq_line for f in frames if f.irq_line is not None] == [1, 0]
    functions = [f.function for f in frames if f.function]
    assert functions.index("on_rapido") < functions.index("on_lento") < functions.index("main")
    # Step Out sale sólo de la ISR interna.
    debugger.toggle_line_breakpoint(line, "anida.c")
    debugger.step_out()
    assert machine.pic.depth == 1 and debugger.function() == "on_lento"
