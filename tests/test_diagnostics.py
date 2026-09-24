"""Avisos: operaciones sospechosas que el programa hace y sigue ejecutando."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from hardboiled.cli import main
from hardboiled.config import BoardConfig
from hardboiled.core.cpu import StopReason
from hardboiled.core.events import CmdContinue, CmdToggleSwitch, EvtCpuSuspended, EvtWarning
from hardboiled.core.machine import Machine
from hardboiled.toolchain import BuildOptions, build, select_compiler
from tests.conftest import FIXTURES, HarnessFactory, MachineFactory, fixture_path, line_of

needs_zig = pytest.mark.skipif(
    importlib.util.find_spec("ziglang") is None, reason="requiere el extra [zig]"
)

DIV0 = 11  # caso de traps.c


def machine_with(**options: str) -> Machine:
    board = BoardConfig.model_validate({"board": options})
    machine = Machine.from_elf(FIXTURES / "traps.elf", board)
    machine.switches().set_value(DIV0)  # type: ignore[union-attr]
    return machine


def test_software_division_by_zero_warns_once_at_the_call() -> None:
    machine = machine_with()
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.EXITED  # un aviso no detiene
    (warning,) = machine.cpu.take_diagnostics()
    assert warning.kind == "div0" and "división por cero" in warning.message
    location = machine.debugger.location(warning.pc)
    assert location is not None and location.file.endswith("traps.c")
    assert machine.debugger.function(warning.pc) == "main"


def test_break_and_off_modes() -> None:
    machine = machine_with(div_by_zero="break")
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.BREAK and "división por cero" in stop.message
    machine = machine_with(div_by_zero="off")
    machine.debugger.continue_()
    assert machine.cpu.take_diagnostics() == []


@needs_zig
def test_m_extension_div_instruction(tmp_path: Path) -> None:
    source = tmp_path / "div.c"
    source.write_text(
        '#include "hardboiled.h"\n'
        "int main(void) { volatile int d = (int)switch_get(); return 7 / d; }\n",
        encoding="utf-8",
    )
    elf = build(
        [source], tmp_path / "div.elf", BuildOptions(march="rv32im"), select_compiler("zig")
    ).output
    machine = Machine.from_elf(elf, BoardConfig.model_validate({"board": {"isa": "rv32im"}}))
    stop = machine.debugger.continue_()
    assert stop.exit_code == -1  # así lo define RISC-V
    (warning,) = machine.cpu.take_diagnostics()
    assert "el cociente queda en -1" in warning.message
    instruction = machine.debugger.instruction_at(warning.pc)
    assert instruction is not None and instruction.mnemonic == "div"


def test_runner_emits_warning_event(harness: HarnessFactory) -> None:
    h = harness("traps")
    h.wait_for(EvtCpuSuspended)
    h.cmd.put(CmdToggleSwitch(0))
    h.cmd.put(CmdToggleSwitch(1))
    h.cmd.put(CmdToggleSwitch(3))  # 0b1011 = 11
    h.cmd.put(CmdContinue())
    warning = h.wait_for(EvtWarning)
    assert warning.kind == "div0" and warning.function == "main"
    assert warning.source_line == line_of("traps.c", "div0")


def test_headless_prints_warnings(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["run", str(fixture_path("traps.elf")), "--headless", "--switches", str(DIV0)])
    assert code == 0
    assert "aviso: división por cero" in capsys.readouterr().err


@needs_zig
def test_build_report_detects_optimization_and_missing_debug(tmp_path: Path) -> None:
    from hardboiled.core.buildinfo import analyze

    good = analyze(FIXTURES / "basic.elf")
    assert good.has_debug and not good.optimized and good.warnings() == []
    source = FIXTURES / "basic.c"
    zig = select_compiler("zig")
    optimized = build([source], tmp_path / "o2.elf", BuildOptions(opt_level="2"), zig).output
    report = analyze(optimized)
    assert report.optimized and "-O0" in report.warnings()[0]
    stripped = build([source], tmp_path / "g0.elf", BuildOptions(debug=False), zig).output
    report = analyze(stripped)
    assert not report.has_debug and "-g" in report.warnings()[0]


@needs_zig
def test_info_and_headless_mention_build_problems(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    elf = build(
        [FIXTURES / "basic.c"],
        tmp_path / "o2.elf",
        BuildOptions(opt_level="2"),
        select_compiler("zig"),
    ).output
    assert main(["info", str(elf)]) == 0
    assert "parece compilado con optimización" in capsys.readouterr().out
    main(["run", str(elf), "--headless"])
    assert "aviso: el programa parece compilado con optimización" in capsys.readouterr().err
    assert main(["info", str(FIXTURES / "basic.elf")]) == 0
    assert "apto para depurar" in capsys.readouterr().out


UNINIT = 12  # caso de traps.c


def uninit_machine(mode: str = "warn") -> Machine:
    board = BoardConfig.model_validate({"board": {"uninitialized": mode}})
    machine = Machine.from_elf(FIXTURES / "traps.elf", board)
    machine.switches().set_value(UNINIT)  # type: ignore[union-attr]
    return machine


def test_uninitialized_local_is_named() -> None:
    machine = uninit_machine()
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.EXITED
    (warning,) = machine.cpu.take_diagnostics()
    assert warning.kind == "uninit" and "`suma`" in warning.message
    location = machine.debugger.location(warning.pc)
    assert location is not None and location.line == line_of("traps.c", "uninit")


def test_uninitialized_break_and_off() -> None:
    machine = uninit_machine("break")
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.BREAK and "sin inicializar" in stop.message
    machine = uninit_machine("off")
    machine.debugger.continue_()
    assert machine.cpu.take_diagnostics() == []


def test_initialized_programs_do_not_warn(make_machine: MachineFactory) -> None:
    for name in ("basic", "mmio", "types"):
        machine, _ = make_machine(name)
        machine.debugger.continue_()
        assert machine.cpu.take_diagnostics() == [], name


def test_step_back_restores_shadow_memory() -> None:
    machine = uninit_machine("break")
    before = machine.snapshot()
    machine.debugger.continue_()
    machine.restore(before)
    machine.cpu.take_diagnostics()
    machine.cpu._warned.clear()  # volver a avisar en el mismo lugar
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.BREAK and "`suma`" in stop.message
