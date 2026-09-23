"""Volcado de la pila alrededor de sp."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.widgets import Static


class MemoryView(Static):
    DEFAULT_CSS = """
    MemoryView { height: auto; border: round $primary; padding: 0 1; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.border_title = "Pila"

    def set_stack(self, stack: tuple[tuple[int, int], ...], sp: int, fp: int) -> None:
        table = Table.grid(padding=(0, 2))
        table.add_column(style="dim")
        table.add_column()
        table.add_column()
        # Direcciones altas arriba: la pila crece hacia abajo.
        for address, value in reversed(stack):
            marks = []
            if address == sp:
                marks.append("◀ sp")
            if address == fp:
                marks.append("◀ s0/fp")
            style = "bold yellow" if address == sp else "dim" if address < sp else ""
            table.add_row(f"{address:08x}", Text(f"{value:08x}", style=style), " ".join(marks))
        if not stack:
            table.add_row("(sp fuera de la SRAM)", "", "")
        self.update(table)
