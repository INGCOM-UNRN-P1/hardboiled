"""Diálogo modal de una línea (expresiones, condiciones, búsquedas, direcciones)."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Input, Label

from hardboiled.i18n import _


class Prompt(ModalScreen[str | None]):
    """Pide un texto: Enter lo confirma, Escape cancela (devuelve None)."""

    DEFAULT_CSS = """
    Prompt { align: center middle; }
    Prompt > Vertical {
        width: 70; height: auto; padding: 1 2;
        border: thick $accent; background: $surface;
    }
    Prompt Label.help { color: $text-muted; margin-top: 1; }
    """

    BINDINGS = [Binding("escape", "cancel", _("Cancelar"))]  # noqa: RUF012

    def __init__(self, title: str, placeholder: str = "", value: str = "", help: str = "") -> None:
        super().__init__()
        self._title = title
        self._placeholder = placeholder
        self._value = value
        self._help = help

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(self._title)
            yield Input(value=self._value, placeholder=self._placeholder, id="prompt-input")
            if self._help:
                yield Label(self._help, classes="help")

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self.dismiss(None)
