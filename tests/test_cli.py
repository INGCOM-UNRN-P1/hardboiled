"""Subcomandos run --headless, info y validate."""

from __future__ import annotations

from pathlib import Path

import pytest

from hardboiled.cli import EXIT_TRAP, EXIT_USAGE, main
from tests.conftest import fixture_path

ROOT = Path(__file__).parents[1]


def test_run_headless_prints_uart_and_returns_exit_code(
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    code = main(["run", str(fixture_path("mmio.elf")), "--headless", "--switches", "0b0101"])
    assert code == (3 + 500) & 0xFF
    assert capsysbinary.readouterr().out == b"hola\n0x00000005\n"


def test_run_headless_reports_trap_with_source_location(
    capsys: pytest.CaptureFixture[str],
) -> None:
    code = main(["run", str(fixture_path("traps.elf")), "--headless", "--switches", "1"])
    assert code == EXIT_TRAP
    err = capsys.readouterr().err
    assert "puntero nulo" in err
    assert "traps.c:" in err and "main()" in err
    assert "instrucción: lw " in err


def test_run_headless_honours_instruction_quota(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(
        [
            "run",
            str(fixture_path("traps.elf")),
            "--headless",
            "--switches",
            "4",
            "--max-instructions",
            "5000",
        ]
    )
    assert code == EXIT_TRAP
    assert "5,000 instrucciones" in capsys.readouterr().err


def test_info_lists_functions_and_sources(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["info", str(fixture_path("basic.elf"))]) == 0
    out = capsys.readouterr().out
    assert "factorial" in out and "main" in out
    assert "basic.c" in out
    assert "Flash -> SRAM" in out  # .data se carga en Flash y se copia a SRAM


def test_validate_default_board(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["validate", str(ROOT / "board.toml")]) == 0
    assert "lab-rv32-basics" in capsys.readouterr().out


def test_validate_reports_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    board = tmp_path / "board.toml"
    board.write_text('[memory]\nflash_base = "0x10"\n', encoding="utf-8")
    assert main(["validate", str(board)]) == EXIT_USAGE
    assert "configuración inválida" in capsys.readouterr().err


def test_missing_elf_is_a_clean_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "no-existe.elf", "--headless"]) == EXIT_USAGE
    assert "no-existe.elf" in capsys.readouterr().err


def test_validate_without_board_uses_packaged_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)  # sin ./board.toml
    assert main(["validate"]) == 0
    out = capsys.readouterr().out
    assert "data/board.toml" in out.replace("\\", "/")
    assert "lab-rv32-basics" in out


def test_board_init_copies_template(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    assert main(["board", "init"]) == 0
    assert (tmp_path / "board.toml").read_text(encoding="utf-8") == (ROOT / "board.toml").read_text(
        encoding="utf-8"
    )
    assert main(["board", "init"]) == EXIT_USAGE  # no pisa sin --force
    assert "--force" in capsys.readouterr().err
    assert main(["board", "init", "--force"]) == 0
    assert main(["validate"]) == 0


def test_runtime_paths(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["runtime", "--include"]) == 0
    include = Path(capsys.readouterr().out.strip())
    assert (include / "hardboiled.h").is_file()
    assert main(["runtime", "--linker-script"]) == 0
    assert capsys.readouterr().out.strip().endswith("hardboiled.ld")
    assert main(["runtime"]) == 0
    out = capsys.readouterr().out
    assert "include" in out and "crt0" in out


def test_headless_trap_prints_call_stack(capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["run", str(fixture_path("traps.elf")), "--headless", "--switches", "3"])
    assert code == EXIT_TRAP
    err = capsys.readouterr().err
    assert "stack overflow" in err
    assert "pila de llamadas:" in err
    assert "deep" in err and "(recursión)" in err
    assert err.count("deep") < 5  # los marcos repetidos se agrupan


def test_deep_recursion_reports_real_depth(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", str(fixture_path("traps.elf")), "--headless", "--switches", "3"]) == 3
    err = capsys.readouterr().err
    # 64 KB de pila / 80 bytes por marco de deep(): cientos de niveles, no 63.
    depth = int(err.split(" x", 1)[1].split(" ")[0])
    assert depth > 500


def test_output_survives_a_non_utf8_console(monkeypatch: pytest.MonkeyPatch) -> None:
    """Windows fuera de una consola: stdout en cp1252, sin ✔ ni ⏎ (falló en CI)."""
    import io
    import sys

    raw = io.BytesIO()
    stdout = io.TextIOWrapper(raw, encoding="cp1252")
    monkeypatch.setattr(sys, "stdout", stdout)
    assert main(["doctor", "--no-build"]) in (0, 1)
    stdout.flush()
    assert "✔" in raw.getvalue().decode("utf-8")
