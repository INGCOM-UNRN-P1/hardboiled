"""Búsqueda e ir a línea en la vista de código."""

from __future__ import annotations

from textual.app import App, ComposeResult

from hardboiled.ui.widgets.code_view import CodeView
from tests.conftest import FIXTURES, line_of


class CodeApp(App[None]):
    def compose(self) -> ComposeResult:
        yield CodeView(id="code")


async def test_find_wraps_and_goto() -> None:
    app = CodeApp()
    async with app.run_test(size=(100, 30)) as pilot:
        code = app.query_one(CodeView)
        code.show_file(str(FIXTURES / "basic.c"))
        await pilot.pause()
        source = (FIXTURES / "basic.c").read_text().splitlines()
        signature = source.index("int factorial(int n)") + 1
        first = code.find("FACTORIAL")  # sin distinguir mayúsculas
        assert first == signature
        second = code.find("factorial")
        assert second == line_of("basic.c", "fact_recurse")
        assert code.find("factorial", backwards=True) == first
        assert code.find("texto que no está") is None
        assert code.goto_line(3) and code.cursor_line == 3
        assert not code.goto_line(10_000)


def test_help_key_labels() -> None:
    from hardboiled.ui.widgets.help_screen import _key_label

    assert _key_label("shift+f11") == "Shift+F11"
    assert _key_label("ctrl+f9") == "Ctrl+F9"
    assert _key_label("slash") == "/"
    assert _key_label("n") == "n"


def test_normalize_keys() -> None:
    from hardboiled.ui.tui import normalize_keys

    assert normalize_keys("F8, n") == "f8,n"
    assert normalize_keys("/,?") == "slash,question_mark"
    assert normalize_keys("B") == "B"  # una letra conserva mayúsculas (Shift)


def test_format_hz() -> None:
    from hardboiled.ui.tui import format_hz

    assert format_hz(1_000_000) == "1 MHz"
    assert format_hz(250_000) == "250 kHz"
    assert format_hz(500) == "500 Hz"
    assert format_hz(None).startswith("sin límite")
