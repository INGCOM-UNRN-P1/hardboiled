"""Instantáneas de la máquina y paso atrás."""

from __future__ import annotations

from hardboiled.core.cpu import StopReason
from hardboiled.core.events import (
    CmdContinue,
    CmdStepBack,
    CmdStepOver,
    CmdToggleSwitch,
    EvtCpuSuspended,
    EvtHardwareUpdated,
    EvtMessage,
)
from tests.conftest import HarnessFactory, MachineFactory, line_of


def test_snapshot_restores_registers_memory_and_peripherals(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("mmio")
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("mmio.c", "wait_loop"), "mmio.c")
    debugger.continue_()
    snap = machine.snapshot()
    registers = machine.cpu.registers()
    ticks = debugger.evaluate("ticks")
    leds = machine.bus.device("leds").snapshot()
    debugger.toggle_line_breakpoint(line_of("mmio.c", "wait_loop"), "mmio.c")
    assert debugger.continue_().reason is StopReason.EXITED

    machine.restore(snap)
    assert machine.cpu.halted is None
    assert machine.cpu.registers() == registers
    assert debugger.evaluate("ticks") == ticks
    assert machine.bus.device("leds").snapshot() == leds
    # Desde el pasado, la ejecución vuelve a llegar al mismo final.
    assert debugger.continue_().exit_code == 3


def test_step_back_after_trap(harness: HarnessFactory) -> None:
    h = harness("traps")
    before = h.wait_for(EvtCpuSuspended)
    h.cmd.put(CmdToggleSwitch(0))  # puntero nulo
    h.cmd.put(CmdContinue())
    trapped = h.wait_for(EvtCpuSuspended)
    assert "puntero nulo" in trapped.reason
    h.cmd.put(CmdStepBack())
    back = h.wait_for(EvtCpuSuspended)
    assert back.pc == before.pc and "paso atrás" in back.reason
    h.cmd.put(CmdStepBack())
    assert "no hay pasos" in h.wait_for(EvtMessage).text


def test_step_back_undoes_steps_and_leds(harness: HarnessFactory) -> None:
    h = harness("mmio")
    first = h.wait_for(EvtCpuSuspended)
    h.cmd.put(CmdStepOver())
    h.wait_for(EvtCpuSuspended)
    h.cmd.put(CmdStepOver())  # led_set(0x0F)
    h.wait_for(EvtCpuSuspended)
    h.cmd.put(CmdStepBack())
    h.cmd.put(CmdStepBack())
    back = h.wait_for(EvtCpuSuspended)
    while "paso atrás (0" not in back.reason:
        back = h.wait_for(EvtCpuSuspended)
    assert back.source_line == first.source_line
    leds = [
        e.value for e in h.seen if isinstance(e, EvtHardwareUpdated) and e.device_name == "leds"
    ]
    assert leds[-1] == 0  # los LEDs vuelven a como estaban
