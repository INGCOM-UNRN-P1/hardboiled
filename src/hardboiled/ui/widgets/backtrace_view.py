"""Pila de llamadas: un renglón por marco; al elegir uno se muestra su código."""

from __future__ import annotations

import os

from rich.text import Text
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from hardboiled.core.events import FrameInfo


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
        self.border_title = "Llamadas"
        self.frames: tuple[FrameInfo, ...] = ()

    def set_frames(self, frames: tuple[FrameInfo, ...]) -> None:
        self.frames = frames
        self.clear_options()
        self.add_options([Option(self._prompt(frame)) for frame in frames])
        if frames:
            self.highlighted = 0

    @staticmethod
    def _prompt(frame: FrameInfo) -> Text:
        if frame.irq_line is not None:
            return Text(f"── {frame.label} ──", style="bold magenta")
        text = Text(f"#{frame.index} ", style="dim")
        text.append(frame.label, style="bold")
        if frame.source_file is not None:
            text.append(f"  {os.path.basename(frame.source_file)}:{frame.source_line}")
        else:
            text.append(f"  0x{frame.pc:08x}", style="dim")
        return text

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        if 0 <= event.option_index < len(self.frames):
            self.post_message(self.FrameChosen(self.frames[event.option_index]))
