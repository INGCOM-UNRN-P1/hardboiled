"""Modo rápido de la CPU (hooks por bloque): mismos resultados que paso a paso.

Continue, Run to y Step Out corren con hooks de bloque y hooks puntuales; para
comparar, `slow()` fuerza el hook por instrucción con una condición que nunca
se cumple.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from hardboiled.config import BoardConfig, BoardInfo
from hardboiled.core.cpu import StopInfo, StopReason
from hardboiled.core.machine import Machine
from tests.conftest import FIXTURES, line_of


@dataclass(frozen=True)
class Outcome:
    stop: StopInfo
    instructions: int
    cycles: int
    uart: bytes
    diagnostics: tuple[tuple[str, int], ...]


def machine_for(name: str, switches: int = 0, **board: object) -> Machine:
    info = BoardInfo.model_validate({"max_instructions": 2_000_000, **board})
    machine = Machine.from_elf(FIXTURES / f"{name}.elf", BoardConfig(board=info))
    bank = machine.switches()
    assert bank is not None
    bank.set_value(switches)
    return machine


def outcome(machine: Machine, stop: StopInfo) -> Outcome:
    uart = machine.uart()
    assert uart is not None
    cpu = machine.cpu
    return Outcome(
        stop,
        cpu.instructions,
        cpu.clock.cycles,
        bytes(uart.transmitted),
        tuple((d.kind, d.pc) for d in cpu.diagnostics),
    )


def fast(machine: Machine) -> Outcome:
    stop = machine.debugger.continue_()
    assert not machine.cpu._stepping
    return outcome(machine, stop)


def slow(machine: Machine) -> Outcome:
    stop = machine.debugger._run(lambda pc: False)  # sin direcciones: por instrucción
    assert machine.cpu._stepping
    return outcome(machine, stop)


@pytest.mark.parametrize(("name", "switches"), [("basic", 0), ("mmio", 5), ("types", 0)])
def test_programs_end_identically(name: str, switches: int) -> None:
    assert fast(machine_for(name, switches)) == slow(machine_for(name, switches))


@pytest.mark.parametrize("case", range(1, 13))
def test_every_trap_is_detected_at_the_same_place(case: int) -> None:
    quick, careful = fast(machine_for("traps", case)), slow(machine_for("traps", case))
    assert quick.stop.reason == careful.stop.reason
    assert quick.stop.kind == careful.stop.kind
    assert quick.stop.pc == careful.stop.pc
    assert quick.stop.fault_address == careful.stop.fault_address
    assert quick.diagnostics == careful.diagnostics
    assert quick.uart == careful.uart


def test_breakpoints_stop_at_the_same_instruction() -> None:
    quick, careful = machine_for("mmio", 1), machine_for("mmio", 1)
    for machine in (quick, careful):
        machine.debugger.toggle_line_breakpoint(line_of("mmio.c", "isr_body"), "mmio.c")
    hits = []
    for _ in range(3):
        a, b = fast(quick), slow(careful)
        assert a.stop.reason is StopReason.BREAK
        assert (a.stop.pc, a.instructions, a.uart) == (b.stop.pc, b.instructions, b.uart)
        hits.append(a.instructions)
    assert len(set(hits)) == 3


def test_run_to_and_step_out_use_fast_mode() -> None:
    machine = machine_for("basic")
    debugger = machine.debugger
    main = machine.image.symbol_address("main")
    assert main is not None
    debugger.run_to(main)
    assert not machine.cpu._stepping
    debugger.step_into()
    while debugger.location() is not None and debugger.backtrace()[0].function == "main":
        debugger.step_into()
    assert machine.cpu._stepping  # los pasos de línea van instrucción por instrucción
    stop = debugger.step_out()
    assert stop.reason is StopReason.BREAK and "devolvió" in stop.message
    assert not machine.cpu._stepping


def test_quota_and_uninitialized_reads_in_fast_mode() -> None:
    machine = machine_for("traps", 4, max_instructions=50_000)
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.LIMIT
    assert 50_000 <= machine.cpu.instructions < 50_100  # se controla por bloque
    machine = machine_for("traps", 12, uninitialized="break")
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.BREAK and "sin inicializar" in stop.message
    assert machine.debugger.location().line == line_of("traps.c", "uninit")  # type: ignore[union-attr]
