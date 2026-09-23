"""Detección de compiladores y `hardboiled build`."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from hardboiled import toolchain
from hardboiled.cli import EXIT_USAGE, main
from hardboiled.core.cpu import StopReason
from hardboiled.core.machine import Machine
from hardboiled.toolchain import (
    BuildError,
    BuildOptions,
    Compiler,
    ToolchainError,
    compile_command,
    parse_march,
    select_compiler,
)
from tests.conftest import FIXTURES

HAS_ZIG = importlib.util.find_spec("ziglang") is not None
needs_zig = pytest.mark.skipif(not HAS_ZIG, reason="requiere el extra [zig]")

GCC = Compiler("gcc", ("riscv64-unknown-elf-gcc",), "gcc de prueba")
ZIG = Compiler("zig", ("python", "-m", "ziglang", "cc"), "zig de prueba")


def test_gcc_command_has_runtime_and_libgcc() -> None:
    command = compile_command(GCC, ["main.c"], "main.elf", BuildOptions(opt_level="1"))
    assert command[0] == "riscv64-unknown-elf-gcc"
    assert "-march=rv32i" in command and "-mabi=ilp32" in command
    assert "-O1" in command and "-g" in command
    assert any(flag.startswith("-T") and flag.endswith("hardboiled.ld") for flag in command)
    assert any(arg.endswith("crt0.s") for arg in command)
    assert command[-1] == "-lgcc"
    assert command.index("main.c") < command.index("-o")


def test_zig_command_maps_extensions_to_cpu() -> None:
    command = compile_command(ZIG, ["a.c"], "a.elf", BuildOptions(march="RV32IMC"))
    assert "-mcpu=generic_rv32+m+c" in command
    assert "-lgcc" not in command


def test_parse_march() -> None:
    assert parse_march("rv32ICM") == "rv32imc"
    with pytest.raises(ToolchainError):
        parse_march("rv64i")
    with pytest.raises(ToolchainError):
        parse_march("rv32imafd")


def test_no_compiler_gives_install_hint(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("HARDBOILED_CC", raising=False)
    monkeypatch.setattr(toolchain, "find_compilers", lambda: [])
    with pytest.raises(ToolchainError, match=r"hardboiled\[zig\]"):
        select_compiler()


def test_env_variable_selects_compiler(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARDBOILED_CC", "no-existe-cc")
    with pytest.raises(ToolchainError, match="no-existe-cc"):
        select_compiler()


@needs_zig
def test_build_and_run(tmp_path: Path) -> None:
    source = tmp_path / "prog.c"
    source.write_text(
        '#include "hardboiled.h"\nint main(void) { uart_puts("ok"); return 7 * 6; }\n'
    )
    result = toolchain.build([source], tmp_path / "prog.elf", compiler=select_compiler("zig"))
    assert result.output.is_file()
    machine = Machine.from_elf(result.output)
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.EXITED and stop.exit_code == 42
    # El fuente absoluto queda en la info de depuración.
    assert str(source) in machine.lines.user_files


@needs_zig
def test_build_error_reports_compiler_output(tmp_path: Path) -> None:
    source = tmp_path / "roto.c"
    source.write_text("int main(void) { return x; }\n")
    with pytest.raises(BuildError) as info:
        toolchain.build([source], compiler=select_compiler("zig"))
    assert "roto.c" in info.value.output


@needs_zig
def test_cli_build(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    output = tmp_path / "basic.elf"
    code = main(["build", str(FIXTURES / "basic.c"), "-o", str(output), "--cc", "zig"])
    assert code == 0 and output.is_file()
    assert "compilado" in capsys.readouterr().out
    assert main(["build", str(tmp_path / "falta.c"), "--cc", "zig"]) == EXIT_USAGE


@needs_zig
def test_run_compiles_sources_with_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path / "cache"))
    source = tmp_path / "hola.c"
    header = tmp_path / "valor.h"
    header.write_text("#define VALOR 5\n")
    source.write_text(
        '#include "hardboiled.h"\n#include "valor.h"\n'
        'int main(void) { uart_puts("hola"); return VALOR; }\n'
    )
    args = ["run", str(source), "--headless", "--cc", "zig"]
    assert main(args) == 5
    first = capsysbinary.readouterr()
    assert first.out == b"hola" and b"compilado con" in first.err

    assert main(args) == 5  # sin cambios: se reutiliza la caché
    assert b"compilado con" not in capsysbinary.readouterr().err

    header.write_text("#define VALOR 9\n")  # cambiar un encabezado invalida la caché
    assert main(args) == 9
    assert len(list((tmp_path / "cache" / "builds").iterdir())) == 2


def test_run_rejects_mixed_inputs(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "a.elf", "b.c", "--headless"]) == EXIT_USAGE
    assert "mezclar" in capsys.readouterr().err
    assert main(["run", "notas.txt", "--headless"]) == EXIT_USAGE
    assert "no reconocido" in capsys.readouterr().err
