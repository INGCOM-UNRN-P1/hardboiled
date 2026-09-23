"""Programas con instrucciones comprimidas (rv32imc) en una placa rv32imc."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from hardboiled.config import BoardConfig
from hardboiled.core.cpu import StopReason
from hardboiled.core.machine import Machine
from hardboiled.toolchain import BuildOptions, build, select_compiler
from tests.conftest import FIXTURES, line_of

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("ziglang") is None, reason="requiere el extra [zig]"
)

BOARD = BoardConfig.model_validate({"board": {"isa": "rv32imc"}})


@pytest.fixture(scope="module")
def compressed(tmp_path_factory: pytest.TempPathFactory) -> Path:
    directory = tmp_path_factory.mktemp("rvc")
    for name in ("basic", "mmio"):
        shutil.copy(FIXTURES / f"{name}.c", directory / f"{name}.c")
        build(
            [f"{name}.c"],
            f"{name}.elf",
            BuildOptions(march="rv32imc", extra_flags=("-fdebug-compilation-dir=.",)),
            select_compiler("zig"),
            cwd=directory,
        )
    return directory


def test_binary_really_uses_compressed_instructions(compressed: Path) -> None:
    machine = Machine.from_elf(compressed / "basic.elf", BOARD)
    assert "c" in machine.image.extensions
    sizes = {size for _, size, _ in machine.image.instructions()}
    assert sizes == {2, 4}


def test_rejected_on_a_board_without_c(compressed: Path) -> None:
    from hardboiled.core.elf import ElfLoadError

    with pytest.raises(ElfLoadError, match="comprimidas"):
        Machine.from_elf(compressed / "basic.elf")


def test_stepping_and_calls(compressed: Path) -> None:
    machine = Machine.from_elf(compressed / "basic.elf", BOARD)
    debugger = machine.debugger
    debugger.run_to_main()
    assert debugger.location().line == line_of("basic.c", "main_first")  # type: ignore[union-attr]
    lines = []
    for _ in range(3):
        debugger.step_over()  # las llamadas (c.jalr o jal) se saltean completas
        assert debugger.function() == "main"
        lines.append(debugger.location().line)  # type: ignore[union-attr]
    assert lines == [
        line_of("basic.c", "main_store"),
        line_of("basic.c", "main_fact"),
        line_of("basic.c", "main_fact") + 1,
    ]
    # Recursión en una máquina nueva: la llamada a factorial ya quedó atrás.
    machine = Machine.from_elf(compressed / "basic.elf", BOARD)
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("basic.c", "fact_recurse"), "basic.c")
    debugger.continue_()
    debugger.continue_()
    depth = len(debugger.backtrace())
    debugger.toggle_line_breakpoint(line_of("basic.c", "fact_recurse"), "basic.c")
    stop = debugger.step_out()
    assert len(debugger.backtrace()) == depth - 1
    assert "devolvió" in stop.message
    assert debugger.continue_().exit_code == 134


def test_interrupts_with_compressed_runtime(compressed: Path) -> None:
    machine = Machine.from_elf(compressed / "mmio.elf", BOARD)
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("mmio.c", "isr_body"), "mmio.c")
    debugger.continue_()
    frames = debugger.backtrace()
    assert [f.irq_line for f in frames if f.irq_line is not None] == [0]
    debugger.toggle_line_breakpoint(line_of("mmio.c", "isr_body"), "mmio.c")
    stop = debugger.continue_()
    assert stop.reason is StopReason.EXITED and stop.exit_code == 3
