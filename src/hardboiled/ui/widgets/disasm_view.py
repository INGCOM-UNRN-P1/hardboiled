"""Desensamblado mixto: cada línea de C seguida de sus instrucciones RV32I.

La instrucción actual se marca con ▶; los breakpoints por dirección con ●.
Click (o Enter) sobre una instrucción pone o quita un breakpoint en esa dirección.
"""

from __future__ import annotations

from pathlib import Path

from rich.text import Text
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from hardboiled.core.events import DisasmLine


class DisassemblyView(OptionList):
    DEFAULT_CSS = """
    DisassemblyView { height: 1fr; border: round $primary; }
    """

    class AddressBreakpointRequested(Message):
        def __init__(self, address: int) -> None:
            super().__init__()
            self.address = address

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.border_title = "Desensamblado"
        self._rows: list[DisasmLine | None] = []
        self._sources: dict[str, list[str]] = {}
        self._instructions: tuple[DisasmLine, ...] = ()
        self._pc = 0
        self._breakpoints: frozenset[int] = frozenset()

    def _source_text(self, file: str, line: int) -> str:
        if file not in self._sources:
            try:
                self._sources[file] = Path(file).read_text(errors="replace").splitlines()
            except OSError:
                self._sources[file] = []
        lines = self._sources[file]
        return lines[line - 1].strip() if 0 < line <= len(lines) else ""

    def show(self, lines: tuple[DisasmLine, ...], pc: int) -> None:
        self._instructions, self._pc = lines, pc
        self._render_rows()

    def set_breakpoints(self, addresses: frozenset[int]) -> None:
        self._breakpoints = addresses
        self._render_rows()

    def _render_rows(self) -> None:
        options: list[Option] = []
        self._rows = []
        current_index = None
        previous: tuple[str | None, int | None] = (None, None)
        for line in self._instructions:
            key = (line.source_file, line.source_line)
            if key != previous and line.source_file and line.source_line:
                header = Text.assemble((f"{line.source_line:>5} │ ", "dim"))
                header.append(self._source_text(line.source_file, line.source_line), style="italic")
                options.append(Option(header, disabled=True))
                self._rows.append(None)
            previous = key
            is_pc = line.address == self._pc
            marker = "●" if line.address in self._breakpoints else " "
            text = Text.assemble((marker, "bold red"))
            text.append("▶ " if is_pc else "  ", style="bold yellow")
            text.append(f"{line.address:08x}  ", style="dim")
            text.append(f"{line.raw:<9}", style="dim")
            text.append(line.text, style="bold" if is_pc else "")
            if is_pc:
                text.stylize("on #2d3f5f")
                current_index = len(options)
            options.append(Option(text))
            self._rows.append(line)
        self.clear_options()
        self.add_options(options)
        if current_index is not None:
            self.highlighted = current_index
            self.scroll_to_highlight()

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        row = self._rows[event.option_index] if event.option_index < len(self._rows) else None
        if row is not None:
            self.post_message(self.AddressBreakpointRequested(row.address))
