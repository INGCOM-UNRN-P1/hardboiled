"""Visor de memoria: volcado hexadecimal navegable de Flash y SRAM.

Se escribe una dirección, un símbolo o una expresión (`&results`, `triangulo`,
`0x20000000`, `p`). Los bytes que cambiaron desde la detención anterior se
resaltan; PgUp/PgDn recorren la memoria de a 256 bytes.
"""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.message import Message
from textual.widgets import Input, Static

from hardboiled.core.events import EvtMemoryDump
from hardboiled.ui.palette import current_palette

PAGE = 256
ROW = 8  # bytes por fila: entra en el ancho del panel lateral


class MemoryInspector(Vertical):
    DEFAULT_CSS = """
    MemoryInspector { height: auto; }
    MemoryInspector Input { margin-bottom: 1; }
    """

    BINDINGS = [  # noqa: RUF012
        Binding("pageup", "page(-1)", "Anterior", show=False),
        Binding("pagedown", "page(1)", "Siguiente", show=False),
    ]

    class DumpRequested(Message):
        def __init__(self, where: str) -> None:
            super().__init__()
            self.where = where

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.where: str | None = None
        self.address: int | None = None
        self._previous: dict[int, int] = {}
        self._current: dict[int, int] = {}

    def compose(self) -> ComposeResult:
        yield Input(placeholder="dirección, símbolo o expresión (&results, 0x20000000…)")
        yield Static(Text("Escribí una dirección y Enter.", style="dim"), id="dump")

    def on_input_submitted(self, event: Input.Submitted) -> None:
        event.stop()
        if event.value.strip():
            self.where = event.value.strip()
            self._previous = {}
            self.post_message(self.DumpRequested(self.where))

    def refresh_request(self) -> None:
        """Nueva detención: volver a pedir el mismo rango para ver qué cambió."""
        if self.where is not None:
            self.post_message(self.DumpRequested(self.where))

    def action_page(self, direction: int) -> None:
        if self.address is None:
            return
        self.where = f"0x{max(self.address + direction * PAGE, 0):x}"
        self.post_message(self.DumpRequested(self.where))

    def show(self, dump: EvtMemoryDump) -> None:
        output = self.query_one("#dump", Static)
        if dump.error is not None:
            output.update(Text(dump.error, style="bold red"))
            return
        if dump.address != self.address:
            self._previous = {}
        else:
            self._previous = self._current
        self.address = dump.address
        self._current = {dump.address + i: b for i, b in enumerate(dump.data)}
        labels = dict(dump.labels)
        table = Table.grid(padding=(0, 1))
        table.add_column(style="dim")
        table.add_column()
        table.add_column()
        for row in range(0, len(dump.data), ROW):
            base = dump.address + row
            hex_part = Text()
            ascii_part = Text()
            for offset in range(ROW):
                address = base + offset
                if row + offset >= len(dump.data):
                    break
                value = dump.data[row + offset]
                changed = address in self._previous and self._previous[address] != value
                style = current_palette(self).changed if changed else ("dim" if value == 0 else "")
                hex_part.append(f"{value:02x}", style=style)
                hex_part.append(" " if offset != 3 else "  ")
                ascii_part.append(chr(value) if 32 <= value < 127 else "·", style=style)
            names = [name for addr, name in labels.items() if base <= addr < base + ROW]
            label = Text(f"{base:08x}")
            if names:
                label.append(f" {', '.join(names)[:12]}", style="cyan")
            table.add_row(label, hex_part, ascii_part)
        output.update(table)
