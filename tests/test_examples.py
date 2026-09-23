"""Los ejemplos empaquetados compilan, corren y se pueden listar y copiar."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from hardboiled import resources
from hardboiled.cli import EXIT_TRAP, EXIT_USAGE, main

needs_zig = pytest.mark.skipif(
    importlib.util.find_spec("ziglang") is None, reason="requiere el extra [zig]"
)


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("HARDBOILED_CC", "zig")


def test_every_example_has_a_summary() -> None:
    names = resources.example_names()
    assert {"demo", "hola", "leds", "switches", "interrupciones", "errores"} <= set(names)
    for name in names:
        assert resources.example_summary(name), name


def test_list_show_and_copy(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["examples"]) == 0
    assert "interrupciones" in capsys.readouterr().out
    assert main(["examples", "show", "hola"]) == 0
    assert "uart_puts" in capsys.readouterr().out
    assert main(["examples", "copy", "hola", "leds.c", "--dest", str(tmp_path)]) == 0
    assert (tmp_path / "hola.c").is_file() and (tmp_path / "leds.c").is_file()
    assert main(["examples", "copy", "hola", "--dest", str(tmp_path)]) == EXIT_USAGE
    assert main(["examples", "show", "nada"]) == EXIT_USAGE
    assert "disponibles" in capsys.readouterr().err


@needs_zig
@pytest.mark.parametrize(
    ("name", "extra", "code", "output"),
    [
        ("hola", [], 0, b"Hola, hardboiled!\n"),
        ("leds", [], 15, b""),
        ("switches", ["--switches", "15"], 0, b"todos encendidos\n"),
        ("interrupciones", [], 10, b"10 interrupciones atendidas\n"),
        ("errores", [], 0, b"Eleg"),
        ("errores", ["--switches", "1"], EXIT_TRAP, b""),
        ("demo", ["--max-instructions", "20000"], EXIT_TRAP, b"hardboiled demo"),
    ],
)
def test_examples_run(
    name: str,
    extra: list[str],
    code: int,
    output: bytes,
    capsysbinary: pytest.CaptureFixture[bytes],
) -> None:
    assert main(["demo", name, "--headless", *extra]) == code
    assert capsysbinary.readouterr().out.startswith(output)
