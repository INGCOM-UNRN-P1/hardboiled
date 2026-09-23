"""Mensajes en inglés (i18n): catálogo completo, coherente y aplicado."""

from __future__ import annotations

import ast
import string
from pathlib import Path

import pytest

from hardboiled import i18n
from hardboiled.cli import EXIT_TRAP, main
from hardboiled.core.hints import HINTS, explain, hint_for
from hardboiled.core.machine import Machine
from hardboiled.locale.en import MESSAGES
from tests.conftest import fixture_path

SOURCES = Path(__file__).parents[1] / "src" / "hardboiled"


def marked_messages() -> dict[str, str]:
    """Textos marcados con _() o N_() en el código: texto -> archivo."""
    found: dict[str, str] = {}
    for path in sorted(SOURCES.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id in ("_", "N_")
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and isinstance(node.args[0].value, str)
            ):
                found.setdefault(node.args[0].value, str(path.relative_to(SOURCES)))
    return found


def fields(text: str) -> set[str]:
    return {name for _literal, name, _spec, _conv in string.Formatter().parse(text) if name}


def test_every_marked_message_is_translated() -> None:
    marked = marked_messages()
    missing = {text: where for text, where in marked.items() if text not in MESSAGES}
    assert not missing, f"sin traducción: {missing}"
    unused = set(MESSAGES) - set(marked)
    assert not unused, f"traducciones que ya no se usan: {unused}"


def test_translations_keep_their_placeholders() -> None:
    wrong = {key: value for key, value in MESSAGES.items() if fields(key) != fields(value)}
    assert not wrong


def test_marked_calls_are_literals() -> None:
    """`_(variable)` sólo se admite para textos marcados antes con N_()."""
    for path in sorted(SOURCES.rglob("*.py")):
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "N_"
            ):
                assert isinstance(node.args[0], ast.Constant), path


def test_underscore_is_never_rebound_where_it_translates() -> None:
    """`for _ in …` o `a, _ = …` en una función que usa _() la rompería."""
    for path in sorted(SOURCES.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"))
        imports_underscore = any(
            isinstance(node, ast.ImportFrom)
            and node.module == "hardboiled.i18n"
            and any(alias.name == "_" for alias in node.names)
            for node in ast.walk(tree)
        )
        if not imports_underscore:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
                continue
            for inner in ast.walk(node):
                targets: list[ast.expr] = []
                if isinstance(inner, ast.Assign):
                    targets = list(inner.targets)
                elif isinstance(inner, ast.For):
                    targets = [inner.target]
                for target in targets:
                    names = [n.id for n in ast.walk(target) if isinstance(n, ast.Name)]
                    assert "_" not in names, (
                        f"{path.name}:{getattr(inner, 'lineno', '?')} reasigna _"
                    )


def test_language_selection(monkeypatch: pytest.MonkeyPatch) -> None:
    assert i18n.normalize("en_US.UTF-8") == "en" and i18n.normalize("fr") is None
    assert i18n.set_language("fr") == "es"
    assert i18n.set_language("en") == "en"
    assert i18n._("programa terminado ({code})", code=3) == "program finished (3)"
    assert i18n._("texto sin traducción") == "texto sin traducción"
    monkeypatch.setenv("HARDBOILED_LANG", "es")
    assert i18n.configure("en") == "es"  # la variable de entorno manda


def test_traps_hints_and_guide_in_english() -> None:
    i18n.set_language("en")
    machine = Machine.from_elf(fixture_path("traps.elf"))
    machine.switches().set_value(1)  # type: ignore[union-attr]
    stop = machine.debugger.continue_()
    assert stop.message == "null pointer dereference: read at 0x00000000"
    assert hint_for("null-pointer") == MESSAGES[HINTS["null-pointer"]]
    for kind in HINTS:
        guide = explain(kind)
        assert guide is not None and guide.startswith("## ")
    assert explain("stack-overflow").startswith("## Stack overflow")  # type: ignore[union-attr]


def test_cli_follows_the_language(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HARDBOILED_LANG", "en")
    elf = str(fixture_path("traps.elf"))
    assert main(["run", elf, "--headless", "--switches", "3"]) == EXIT_TRAP
    err = capsys.readouterr().err
    assert "TRAP: stack overflow: sp = 0x" in err
    assert "hint: Recursion without a base case?" in err
    assert "call stack:" in err and "(recursion)" in err
    monkeypatch.delenv("HARDBOILED_LANG")
    assert main(["run", elf, "--headless", "--switches", "3"]) == EXIT_TRAP
    assert "pila de llamadas:" in capsys.readouterr().err


def test_language_from_user_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    (tmp_path / "config.toml").write_text('[ui]\nlanguage = "en"\n')
    monkeypatch.setenv("HARDBOILED_CONFIG_DIR", str(tmp_path))
    main(["run", str(fixture_path("traps.elf")), "--headless", "--switches", "11"])
    assert "division by zero: RISC-V raises no exception" in capsys.readouterr().err


async def test_trap_screen_in_english() -> None:
    from textual.app import App
    from textual.widgets import Label

    from hardboiled.core.events import EvtTrap
    from hardboiled.ui.widgets.trap_screen import TrapScreen

    i18n.set_language("en")
    app: App[None] = App()
    async with app.run_test() as pilot:
        await app.push_screen(TrapScreen(EvtTrap("boom", None, kind="null-pointer"), ()))
        await pilot.pause()
        labels = [str(label.render()) for label in app.screen.query(Label)]
        assert "✖ TRAP: execution aborted" in labels and "Where" in labels
