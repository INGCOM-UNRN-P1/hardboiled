"""Tabla de los 32 registros enteros (x0-x31) y el PC."""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from hardboiled.core.cpu import ABI_NAMES


class RegistersView(Static):
    DEFAULT_CSS = """
    RegistersView { height: auto; border: round $primary; padding: 0 1; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.border_title = "Registros"
        self._previous: dict[str, int] = {}
        self._current: dict[str, int] = {}

    def set_registers(self, registers: dict[str, int]) -> None:
        self._previous = self._current
        self._current = dict(registers)
        self.update(self._table())

    def _cell(self, index: int) -> Text:
        key = f"x{index}"
        value = self._current.get(key, 0)
        changed = self._previous and self._previous.get(key) != value
        text = Text(f"{key:>3} ", style="dim")
        text.append(f"{ABI_NAMES[index]:<5}", style="cyan")
        text.append(f"{value:08x}", style="bold yellow" if changed else "")
        return text

    def _table(self) -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column()
        table.add_column()
        pc = self._current.get("pc", 0)
        table.add_row(Text.assemble(("pc        ", "bold"), (f"{pc:08x}", "bold green")), "")
        for row in range(16):
            table.add_row(self._cell(row), self._cell(row + 16))
        return table
