"""Lista de archivos fuente del programa para abrir cualquiera en el código."""

from __future__ import annotations

import os

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, OptionList
from textual.widgets.option_list import Option

from hardboiled.i18n import _


class FilePicker(ModalScreen[str | None]):
    DEFAULT_CSS = """
    FilePicker { align: center middle; }
    FilePicker > Vertical {
        width: 90; height: auto; max-height: 80%; padding: 1 2;
        border: thick $accent; background: $surface;
    }
    FilePicker OptionList { height: auto; max-height: 30; margin-top: 1; }
    """

    BINDINGS = [Binding("escape", "cancel", _("Cancelar"))]  # noqa: RUF012

    def __init__(self, files: tuple[str, ...], current: str | None) -> None:
        super().__init__()
        # Los .c primero, después encabezados y ensamblador.
        self.files = sorted(files, key=lambda f: (not f.endswith(".c"), os.path.basename(f)))
        self.current = current

    def compose(self) -> ComposeResult:
        with Vertical():
            yield Label(_("Abrir archivo fuente (Enter abre, Esc cancela):"))
            options = []
            for path in self.files:
                prompt = Text.assemble(
                    (os.path.basename(path), "bold" if path == self.current else ""),
                    (f"  {os.path.dirname(path)}", "dim"),
                )
                options.append(Option(prompt))
            yield OptionList(*options)

    def on_mount(self) -> None:
        option_list = self.query_one(OptionList)
        option_list.focus()
        if self.current in self.files:
            option_list.highlighted = self.files.index(self.current)

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        self.dismiss(self.files[event.option_index])

    def action_cancel(self) -> None:
        self.dismiss(None)
