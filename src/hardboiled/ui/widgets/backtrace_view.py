"""Pila de llamadas: un renglón por marco; al elegir uno se muestra su código."""

from __future__ import annotations

import os

from rich.text import Text
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from hardboiled.core.events import FrameInfo, collapse_frames
from hardboiled.i18n import _


class BacktraceView(OptionList):
    DEFAULT_CSS = """
    BacktraceView { height: auto; max-height: 12; border: round $primary; }
    """

    class FrameChosen(Message):
        def __init__(self, frame: FrameInfo) -> None:
            super().__init__()
            self.frame = frame

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.border_title = _("Llamadas")
        self.frames: tuple[FrameInfo, ...] = ()

    def set_frames(self, frames: tuple[FrameInfo, ...]) -> None:
        # Las recursiones profundas se agrupan: cada opción es el primer marco del grupo.
        groups = collapse_frames(frames)
        self.frames = tuple(frame for frame, _ in groups)
        self.clear_options()
        self.add_options([Option(self._prompt(frame, count)) for frame, count in groups])
        if frames:
            self.highlighted = 0

    @staticmethod
    def _prompt(frame: FrameInfo, count: int = 1) -> Text:
        if frame.irq_line is not None:
            return Text(f"── {frame.label} ──", style="bold magenta")
        span = f"#{frame.index}" if count == 1 else f"#{frame.index}-#{frame.index + count - 1}"
        text = Text.assemble((f"{span} ", "dim"))
        text.append(frame.label, style="bold")
        if frame.source_file is not None:
            text.append(f"  {os.path.basename(frame.source_file)}:{frame.source_line}")
        else:
            text.append(f"  0x{frame.pc:08x}", style="dim")
        if count > 1:
            text.append(" " + _(" x{count} (recursión)", count=count), style="bold magenta")
        return text

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if 0 <= event.option_index < len(self.frames):
            self.post_message(self.FrameChosen(self.frames[event.option_index]))
