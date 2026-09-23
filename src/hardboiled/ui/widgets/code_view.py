"""Vista de código fuente con línea activa, cursor y marcadores de breakpoint."""

from __future__ import annotations

from pathlib import Path

from rich.segment import Segment
from rich.style import Style
from rich.syntax import Syntax
from rich.text import Text
from textual import events
from textual.binding import Binding
from textual.geometry import Size
from textual.message import Message
from textual.scroll_view import ScrollView
from textual.strip import Strip

GUTTER_WIDTH = 10  # "●▶ 1234 │ "

_ACTIVE_BG = Style(bgcolor="#2d3f5f")
_CURSOR_BG = Style(bgcolor="#262626")
_FRAME_BG = Style(bgcolor="#3b2f4a")


class CodeView(ScrollView, can_focus=True):
    """Muestra un archivo fuente. Click en el margen (o F9) alterna un breakpoint."""

    DEFAULT_CSS = """
    CodeView {
        background: $surface;
    }
    """

    BINDINGS = [  # noqa: RUF012 - convención de Textual
        Binding("up", "cursor(-1)", "Arriba", show=False),
        Binding("down", "cursor(1)", "Abajo", show=False),
        Binding("pageup", "cursor(-20)", show=False),
        Binding("pagedown", "cursor(20)", show=False),
    ]

    class BreakpointRequested(Message):
        def __init__(self, file: str, line: int) -> None:
            super().__init__()
            self.file = file
            self.line = line

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.file: str | None = None
        self._lines: list[Text] = []
        self._active_line: int | None = None
        self._frame_line: int | None = None  # línea del marco elegido en la pila de llamadas
        self._cursor_line = 1
        self._breakpoints: frozenset[int] = frozenset()

    @property
    def cursor_line(self) -> int:
        return self._cursor_line

    # ------------------------------------------------------------- contenido

    def show_file(self, path: str | None) -> None:
        if path == self.file:
            return
        self.file = path
        self._active_line = None
        self._frame_line = None
        self._cursor_line = 1
        if path is None:
            self._lines = [Text("(sin código fuente para la ubicación actual)", style="dim")]
        else:
            try:
                code = Path(path).read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                self._lines = [Text(f"no se pudo abrir {path}: {exc}", style="red")]
            else:
                lexer = Syntax.guess_lexer(path, code)
                highlighted = Syntax(code, lexer, theme="monokai").highlight(code)
                highlighted.rstrip()
                self._lines = list(highlighted.split("\n", allow_blank=True))
        longest = max((line.cell_len for line in self._lines), default=0)
        self.virtual_size = Size(GUTTER_WIDTH + longest + 1, len(self._lines))
        self.scroll_to(0, 0, animate=False)
        self.refresh()

    def set_active_line(self, line: int | None) -> None:
        self._active_line = line
        if line is not None:
            self._cursor_line = line
            self._ensure_visible(line)
        self.refresh()

    def set_frame_line(self, line: int | None) -> None:
        """Marca la línea de un marco llamador (distinta de la línea en ejecución)."""
        self._frame_line = line
        if line is not None:
            self._cursor_line = line
            self._ensure_visible(line)
        self.refresh()

    def set_breakpoints(self, lines: frozenset[int]) -> None:
        self._breakpoints = lines
        self.refresh()

    def _ensure_visible(self, line: int) -> None:
        top = int(self.scroll_offset.y)
        height = max(1, self.size.height)
        index = line - 1
        if index < top or index >= top + height:
            self.scroll_to(y=max(0, index - height // 3), animate=False)

    # ---------------------------------------------------------------- render

    def render_line(self, y: int) -> Strip:
        scroll_x, scroll_y = self.scroll_offset
        index = scroll_y + y
        width = self.size.width
        if index >= len(self._lines):
            return Strip.blank(width)
        number = index + 1
        active = number == self._active_line
        in_frame = number == self._frame_line and not active
        if active:
            background: Style | None = _ACTIVE_BG
        elif in_frame:
            background = _FRAME_BG
        elif number == self._cursor_line:
            background = _CURSOR_BG
        else:
            background = None

        gutter = Text(no_wrap=True)
        gutter.append("●" if number in self._breakpoints else " ", style="bold red")
        gutter.append("▶" if active else "▷" if in_frame else " ", style="bold yellow")
        gutter.append(f"{number:>5} ", style="bold" if active else "dim")
        gutter.append("│ ", style="dim")

        code = self._lines[index].copy()
        code.no_wrap = True
        if background is not None:
            gutter.stylize(background)
            code.stylize(background)

        console = self.app.console
        gutter_strip = Strip(gutter.render(console), GUTTER_WIDTH)
        code_width = max(0, width - GUTTER_WIDTH)
        segments: list[Segment] = list(code.render(console))
        code_strip = (
            Strip(segments)
            .crop(scroll_x, scroll_x + code_width)
            .extend_cell_length(code_width, background)
        )
        return Strip.join([gutter_strip, code_strip])

    # ---------------------------------------------------------------- input

    def action_cursor(self, delta: int) -> None:
        if not self._lines:
            return
        self._cursor_line = min(max(1, self._cursor_line + delta), len(self._lines))
        self._ensure_visible(self._cursor_line)
        self.refresh()

    def on_click(self, event: events.Click) -> None:
        offset = event.get_content_offset(self)
        if offset is None or self.file is None:
            return
        line = int(self.scroll_offset.y) + offset.y + 1
        if not 1 <= line <= len(self._lines):
            return
        self._cursor_line = line
        self.refresh()
        if offset.x < GUTTER_WIDTH:
            self.post_message(self.BreakpointRequested(self.file, line))
