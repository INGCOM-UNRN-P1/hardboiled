"""CPU, trampas, mapeo DWARF y control de flujo del depurador."""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from hardboiled.core.cpu import StopReason
from hardboiled.core.debugger import DebuggerError
from hardboiled.core.dwarf import LineTable
from hardboiled.core.elf import ElfImage, ElfLoadError
from tests.conftest import MachineFactory, fixture_path, line_of

BASIC = "basic.c"


def test_rejects_non_riscv_elf() -> None:
    with pytest.raises(ElfLoadError, match="RISC-V"):
        ElfImage.load(sys.executable if Path(sys.executable).is_file() else "/bin/sh")


def test_loads_segments_and_initializes_data(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    assert machine.cpu.pc == machine.image.entry
    debugger.run_to_main()

    counter = machine.image.symbol_address("counter")
    results = machine.image.symbol_address("results")
    assert counter is not None and results is not None
    # crt0 copió .data desde Flash y puso .bss en cero.
    assert machine.cpu.read_memory(counter, 4) == (3).to_bytes(4, "little")
    assert machine.cpu.read_memory(results, 16) == bytes(16)


def test_run_to_main_skips_prologue(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    stop = machine.debugger.run_to_main()
    assert stop is not None and stop.reason is StopReason.BREAK
    location = machine.debugger.location()
    assert location is not None
    assert os.path.basename(location.file) == BASIC
    assert location.line == line_of(BASIC, "main_first")
    assert machine.debugger.function() == "main"


def test_registers_snapshot(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    machine.debugger.run_to_main()
    regs = machine.cpu.registers()
    assert set(regs) == {f"x{i}" for i in range(32)} | {"pc"}
    assert regs["x0"] == 0
    assert regs["pc"] == machine.cpu.pc
    sram = machine.board.memory
    assert sram.sram_base <= regs["x2"] < sram.sram_end  # sp dentro de la SRAM
    stack = machine.cpu.stack_words()
    assert regs["x2"] in [address for address, _ in stack]


def test_step_over_walks_main_without_entering_calls(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.run_to_main()
    visited = []
    for _ in range(3):
        stop = debugger.step_over()
        assert stop.reason is StopReason.BREAK
        location = debugger.location()
        assert location is not None
        visited.append(location.line)
        assert debugger.function() == "main"
    assert visited == [
        line_of(BASIC, "main_store"),
        line_of(BASIC, "main_fact"),
        line_of(BASIC, "main_fact") + 1,
    ]


def test_step_into_stops_at_first_instruction_of_callee(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.run_to_main()
    debugger.step_into()
    assert debugger.function() == "sum_squares"
    assert machine.cpu.pc == machine.image.symbol_address("sum_squares")
    debugger.step_into()
    location = debugger.location()
    assert location is not None and location.line == line_of(BASIC, "sum_first")


def test_step_over_recursive_call_stays_in_same_frame(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of(BASIC, "fact_recurse"), BASIC)
    stop = debugger.continue_()
    assert stop.reason is StopReason.BREAK
    sp_before = machine.cpu.sp
    debugger.toggle_line_breakpoint(line_of(BASIC, "fact_recurse"), BASIC)  # quitarlo
    debugger.step_over()
    # Tras ejecutar la llamada recursiva completa seguimos en el mismo marco.
    assert debugger.function() == "factorial"
    assert machine.cpu.sp == sp_before


def test_line_breakpoint_hits_every_iteration(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    assert debugger.toggle_line_breakpoint(line_of(BASIC, "square_body"), BASIC) is True
    for _ in range(3):
        stop = debugger.continue_()
        assert stop.reason is StopReason.BREAK
        assert debugger.function() == "square"
    stop = debugger.continue_()
    assert stop.reason is StopReason.EXITED
    assert stop.exit_code == 134


def test_breakpoint_on_blank_line_moves_to_next_code_line(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    blank = line_of(BASIC, "main_store") + 1  # línea en blanco dentro de main
    debugger.toggle_line_breakpoint(blank, BASIC)
    assert debugger.line_breakpoints == {
        (str(fixture_path(BASIC).resolve()), line_of(BASIC, "main_fact"))
    }


def test_breakpoint_without_code_raises(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    with pytest.raises(DebuggerError):
        machine.debugger.toggle_line_breakpoint(10_000, BASIC)
    with pytest.raises(DebuggerError):
        machine.debugger.toggle_line_breakpoint(1, "otro.c")


def test_address_breakpoint(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    factorial = machine.image.symbol_address("factorial")
    assert factorial is not None
    machine.debugger.toggle_address_breakpoint(factorial)
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.BREAK and stop.pc == factorial
    machine.debugger.toggle_address_breakpoint(factorial)
    assert machine.debugger.continue_().exit_code == 134


def test_program_exit_is_sticky_until_reset(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    first = machine.debugger.continue_()
    assert first.reason is StopReason.EXITED and first.exit_code == 134
    assert machine.debugger.step_into() == first
    machine.reset()
    assert machine.cpu.halted is None
    assert machine.cpu.instructions == 0
    assert machine.debugger.continue_().exit_code == 134


@pytest.mark.parametrize(
    ("selector", "expected"),
    [
        (1, "puntero nulo"),
        (2, "escritura en Flash"),
        (3, "stack overflow"),
        (5, "no hay ningún periférico"),
        (6, "sólo lectura"),
        (7, "no mapeada: 0x30000000"),
        (8, "deadlock"),
        (9, "SRAM (no es ejecutable)"),
    ],
)
def test_traps(make_machine: MachineFactory, selector: int, expected: str) -> None:
    machine, _ = make_machine("traps", switches=selector)
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.TRAP
    assert expected in stop.message
    # La ejecución queda abortada.
    assert machine.debugger.continue_() == stop


def test_stack_overflow_is_detected_before_leaving_sram(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("traps", switches=3)
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.TRAP
    assert machine.debugger.function(stop.pc) == "deep"
    assert stop.fault_address is not None and stop.fault_address < machine.board.memory.sram_base


def test_instruction_quota(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("traps", switches=4, max_instructions=20_000)
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.TRAP
    assert "límite de 20,000 instrucciones" in stop.message
    assert machine.cpu.instructions == 20_000


def test_pause_via_poll(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("traps", switches=4)
    calls = 0

    def poll() -> bool:
        nonlocal calls
        calls += 1
        return calls >= 5

    machine.cpu.poll = poll
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.PAUSED
    assert machine.cpu.halted is None  # se puede reanudar


def test_line_table_roundtrip() -> None:
    elf = fixture_path("basic.elf")
    lines = LineTable.from_elf(elf)
    image = ElfImage.load(elf)
    source = str(fixture_path(BASIC).resolve())
    assert source in lines.user_files
    # Las fuentes de compiler-rt (zig) no se consideran de usuario.
    assert all(f.endswith((".c", ".s")) for f in lines.user_files)

    line = line_of(BASIC, "square_body")
    resolved = lines.address_for_line(source, line)
    assert resolved is not None
    effective, address = resolved
    assert effective == line
    location = lines.lookup(address)
    assert location is not None and (location.file, location.line) == (source, line)
    assert image.function_at(address) == "square"
    assert lines.resolve_file(BASIC) == source


def test_step_instruction_executes_exactly_one(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    cpu = machine.cpu
    machine.debugger.run_to_main()
    for _ in range(5):
        before_pc, before_count = cpu.pc, cpu.instructions
        stop = machine.debugger.step_instruction()
        assert stop.reason is StopReason.BREAK
        assert cpu.instructions == before_count + 1
        assert cpu.pc != before_pc


def test_step_instruction_on_self_loop(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("traps", switches=4)  # for (;;) {} compila a `j .`
    debugger = machine.debugger
    debugger.run_to_main()
    for _ in range(40):
        debugger.step_instruction()
    loop_pc = machine.cpu.pc
    count = machine.cpu.instructions
    debugger.step_instruction()
    assert machine.cpu.pc == loop_pc and machine.cpu.instructions == count + 1
    # Un breakpoint sobre el propio salto vuelve a detener en cada vuelta.
    debugger.toggle_address_breakpoint(loop_pc)
    assert debugger.continue_().reason is StopReason.BREAK
    assert machine.cpu.instructions == count + 2


def test_run_to_line(make_machine: MachineFactory) -> None:
    machine, _ = make_machine("basic")
    debugger = machine.debugger
    debugger.run_to_main()
    stop = debugger.run_to_line(line_of(BASIC, "main_fact"), BASIC)
    assert stop.reason is StopReason.BREAK
    location = debugger.location()
    assert location is not None and location.line == line_of(BASIC, "main_fact")
    assert debugger.line_breakpoints == frozenset()  # no deja breakpoint
    # Un breakpoint en el camino detiene antes.
    debugger.toggle_line_breakpoint(line_of(BASIC, "fact_recurse"), BASIC)
    debugger.run_to_line(line_of(BASIC, "main_fact") + 1, BASIC)
    assert debugger.function() == "factorial"
    with pytest.raises(DebuggerError):
        debugger.run_to_line(10_000, BASIC)
