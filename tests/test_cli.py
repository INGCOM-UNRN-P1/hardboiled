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
    board.write_text('[memory]\nflash_base = "0x10"\n')
    assert main(["validate", str(board)]) == EXIT_USAGE
    assert "configuración inválida" in capsys.readouterr().err


def test_missing_elf_is_a_clean_error(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", "no-existe.elf", "--headless"]) == EXIT_USAGE
    assert "no-existe.elf" in capsys.readouterr().err
