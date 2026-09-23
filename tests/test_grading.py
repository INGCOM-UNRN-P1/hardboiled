"""`hardboiled test`: casos con salida esperada."""

from __future__ import annotations

from pathlib import Path

import pytest

from hardboiled.cli import EXIT_USAGE, main
from tests.conftest import fixture_path

HWLOOP = str(fixture_path("hwloop.elf"))
MMIO = str(fixture_path("mmio.elf"))


def test_single_case_passes(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    expected = tmp_path / "esperado.txt"
    expected.write_text("hola\n0x00000005\n")
    code = main(["test", MMIO, "--switches", "5", "--expect-uart", str(expected),
                 "--expect-exit", "503"])  # el valor completo, no & 0xFF  # fmt: skip
    out = capsys.readouterr().out
    assert code == 0, out
    assert out.startswith("ok    mmio.elf (código 503,")
    assert out.rstrip().endswith("1/1 casos correctos")


def test_single_case_fails_with_diff(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    expected = tmp_path / "esperado.txt"
    expected.write_text("hola\n0x00000004\n")
    code = main(["test", MMIO, "--switches", "5", "--expect-uart", str(expected),
                 "--expect-exit", "0"])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 1
    assert "FALLA mmio.elf" in out
    assert "código de salida 503, se esperaba 0" in out
    assert "-0x00000004⏎" in out and "+0x00000005⏎" in out
    assert "0/1 casos correctos" in out


SUITE = """
[[case]]
name = "eco en mayúsculas"
script = "entrada.toml"
expect_uart_file = "esperado.txt"
expect_exit = 3

[[case]]
name = "sale enseguida"
uart_input = "q"
expect_uart = "listo\\nfin\\n"
expect_exit = 0

[[case]]
name = "se queda esperando"
max_instructions = 30_000
expect_trap = "*"

[[case]]
at = [{ cycle = 30_000, uart = "abq" }]
expect_uart_contains = ["AB", "fin"]

[[case]]
name = "mal"
uart_input = "q"
expect_exit = 1
"""

SCRIPT = """
[[at]]
cycle = 50_000
press = [0, 1, 2]
[[at]]
cycle = 90_000
uart = "hola q"
"""


def test_suite(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    (tmp_path / "casos.toml").write_text(SUITE)
    (tmp_path / "entrada.toml").write_text(SCRIPT)
    (tmp_path / "esperado.txt").write_text("listo\nHOLA fin\n")
    code = main(["test", HWLOOP, "--suite", str(tmp_path / "casos.toml")])
    out = capsys.readouterr().out
    assert code == 1
    lines = out.splitlines()
    assert lines[0].startswith("ok    eco en mayúsculas (código 3,")
    assert lines[1].startswith("ok    sale enseguida (código 0,")
    # sin límite de tiempo el lazo seguiría con el timer: se corta por cuota
    assert lines[2].startswith("FALLA se queda esperando (limit,")
    assert lines[4].startswith("ok    caso 4 (código 0,")
    assert lines[5].startswith("FALLA mal (código 0,")
    assert "4/5" not in out and "3/5 casos correctos" in out


def test_quiet_and_trap_expectations(capsys: pytest.CaptureFixture[str]) -> None:
    traps = str(fixture_path("traps.elf"))
    assert main(["test", traps, "--switches", "1", "--expect-trap", "null-pointer", "-q"]) == 0
    assert capsys.readouterr().out.strip() == "1/1 casos correctos"
    assert main(["test", traps, "--switches", "1", "--expect-trap", "stack-overflow"]) == 1
    assert "ocurrió null-pointer" in capsys.readouterr().out
    assert main(["test", traps, "--switches", "1"]) == 1
    assert "el programa no terminó: desreferencia de puntero nulo" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("suite", "error"),
    [
        ("", "case"),
        ("[[case]]\nexpect_exit = 1\nexpect_trap = 'x'\n", "a la vez"),
        ("[[case]]\nfoo = 1\n", "foo"),
        ("[[case]]\nscript = 'no-existe.toml'\n", "no se pudo leer"),
    ],
)
def test_invalid_suites(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], suite: str, error: str
) -> None:
    path = tmp_path / "casos.toml"
    path.write_text(suite)
    assert main(["test", HWLOOP, "--suite", str(path)]) == EXIT_USAGE
    assert error in capsys.readouterr().err


def test_suite_excludes_single_case_options(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "casos.toml"
    path.write_text("[[case]]\nexpect_exit = 0\n")
    assert main(["test", HWLOOP, "--suite", str(path), "--switches", "1"]) == EXIT_USAGE
    assert "en cada caso" in capsys.readouterr().err
