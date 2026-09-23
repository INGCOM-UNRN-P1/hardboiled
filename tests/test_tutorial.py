"""Tutorial guiado: cada lección compila, su punto de partida no pasa y la
solución de referencia (tests/tutorial/) pasa todos los casos."""

from __future__ import annotations

import importlib.util
import shutil
from pathlib import Path

import pytest

from hardboiled.cli import EXIT_USAGE, main
from hardboiled.tutorial import find_lesson, lessons

SOLUTIONS = Path(__file__).parent / "tutorial"
needs_zig = pytest.mark.skipif(
    importlib.util.find_spec("ziglang") is None, reason="requiere el extra [zig]"
)


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("HARDBOILED_CC", "zig")
    monkeypatch.chdir(tmp_path)


def test_every_lesson_is_complete() -> None:
    found = lessons()
    assert [lesson.number for lesson in found] == list(range(1, len(found) + 1))
    for lesson in found:
        assert lesson.title and "TODO" not in lesson.title
        assert (lesson.path / "main.c").is_file() and lesson.suite.is_file()
        assert "## Consigna" in lesson.text
        assert f"hardboiled tutorial check {lesson.number}" in lesson.text
        assert (SOLUTIONS / f"{lesson.path.name}.c").is_file()
    assert find_lesson("03").slug == "uart" and find_lesson("uart").number == 3


def test_list_show_and_start(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tutorial"]) == 0
    assert "1. Encender LEDs  (leds)" in capsys.readouterr().out
    assert main(["tutorial", "show", "leds"]) == 0
    assert capsys.readouterr().out.startswith("# Lección 1 — Encender LEDs")
    assert main(["tutorial", "start", "1"]) == 0
    assert {p.name for p in Path("leccion-01-leds").iterdir()} == {
        "leccion.md", "main.c", "casos.toml",
    }  # fmt: skip
    capsys.readouterr()
    assert main(["tutorial", "start", "1"]) == EXIT_USAGE  # no pisa el trabajo
    assert "--force" in capsys.readouterr().err
    assert main(["tutorial", "show", "99"]) == EXIT_USAGE
    assert "disponibles: 1 (leds)" in capsys.readouterr().err


def test_check_without_sources(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["tutorial", "check", "1"]) == EXIT_USAGE
    assert "tutorial start 1" in capsys.readouterr().err


@needs_zig
@pytest.mark.parametrize("lesson", lessons(), ids=lambda lesson: lesson.path.name)
def test_starter_fails_and_solution_passes(
    lesson: object, capsys: pytest.CaptureFixture[str]
) -> None:
    from hardboiled.tutorial import Lesson

    assert isinstance(lesson, Lesson)
    assert main(["tutorial", "start", str(lesson.number)]) == 0
    capsys.readouterr()
    assert main(["tutorial", "check", str(lesson.number)]) == 1, "el punto de partida ya pasa"
    capsys.readouterr()
    shutil.copyfile(SOLUTIONS / f"{lesson.path.name}.c", Path(lesson.default_dir) / "main.c")
    code = main(["tutorial", "check", str(lesson.number)])
    out = capsys.readouterr().out
    assert code == 0, out
    assert "¡Muy bien!" in out
