"""PIN y QR accesibles mientras la TUI ocupa la terminal."""

from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import VerticalScroll
from textual.screen import ModalScreen
from textual.widgets import Static

from hardboiled.i18n import _


class PairingScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    PairingScreen { align: center middle; }
    PairingScreen > VerticalScroll {
        width: 95%; height: 90%; padding: 1 2;
        border: thick $accent; background: $surface;
    }
    PairingScreen Static { width: auto; }
    """
    BINDINGS = [Binding("escape", "close", _("Cerrar"))]  # noqa: RUF012

    def __init__(self, banner: str) -> None:
        super().__init__()
        self.banner = banner

    def compose(self) -> ComposeResult:
        with VerticalScroll():
            yield Static(self.banner, markup=False)

    def action_close(self) -> None:
        self.dismiss()
