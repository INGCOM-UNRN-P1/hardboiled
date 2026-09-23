"""Tabla de los 32 registros enteros (x0-x31) y el PC, en varios formatos.

`x` cambia el formato: hexadecimal, decimal con signo, sin signo, ASCII
(los 4 bytes como caracteres, little endian) y símbolo (qué hay en esa
dirección: `main+0x2c`, `results[1]`…). Los registros que cambiaron desde la
detención anterior se resaltan.
"""

from __future__ import annotations

from rich.table import Table
from rich.text import Text
from textual.widgets import Static

from hardboiled.core.cpu import ABI_NAMES

FORMATS = ("hex", "con signo", "sin signo", "ascii", "símbolo")


def format_value(value: int, mode: str, symbol: str | None = None, width: int = 11) -> str:
    if mode == "con signo":
        text = str(value - (1 << 32) if value & 0x8000_0000 else value)
    elif mode == "sin signo":
        text = str(value)
    elif mode == "ascii":
        chars = value.to_bytes(4, "little")
        text = "'" + "".join(chr(c) if 32 <= c < 127 else "·" for c in chars) + "'"
    elif mode == "símbolo" and symbol:
        text = symbol[:width]
    else:
        text = f"{value:08x}"
    return f"{text:>{width}}" if mode in ("con signo", "sin signo") else f"{text:<{width}}"


class RegistersView(Static):
    DEFAULT_CSS = """
    RegistersView { height: auto; border: round $primary; padding: 0 1; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self._previous: dict[str, int] = {}
        self._current: dict[str, int] = {}
        self._symbols: dict[str, str] = {}
        self.mode = FORMATS[0]
        self._update_title()

    def _update_title(self) -> None:
        self.border_title = f"Registros ({self.mode}; x cambia)"

    def set_registers(
        self, registers: dict[str, int], symbols: dict[str, str] | None = None
    ) -> None:
        self._previous = self._current
        self._current = dict(registers)
        self._symbols = dict(symbols or {})
        self.update(self._table())

    def cycle_format(self) -> str:
        self.mode = FORMATS[(FORMATS.index(self.mode) + 1) % len(FORMATS)]
        self._update_title()
        self.update(self._table())
        return self.mode

    def _cell(self, index: int) -> Text:
        key = f"x{index}"
        value = self._current.get(key, 0)
        changed = self._previous and self._previous.get(key) != value
        text = Text.assemble((f"{key:>3} ", "dim"))
        text.append(f"{ABI_NAMES[index]:<5}", style="cyan")
        shown = format_value(value, self.mode, self._symbols.get(key))
        text.append(shown, style="bold yellow" if changed else "")
        return text

    def _table(self) -> Table:
        table = Table.grid(padding=(0, 2))
        table.add_column()
        table.add_column()
        pc = self._current.get("pc", 0)
        pc_text = Text.assemble(("pc        ", "bold"), (f"{pc:08x}", "bold green"))
        if self._symbols.get("pc"):
            pc_text.append(f"  {self._symbols['pc']}", style="green")
        table.add_row(pc_text, "")
        for row in range(16):
            table.add_row(self._cell(row), self._cell(row + 16))
        return table
