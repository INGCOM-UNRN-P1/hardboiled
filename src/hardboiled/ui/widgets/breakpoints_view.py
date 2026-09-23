"""Lista de breakpoints y watchpoints; Supr (o Enter) quita el elegido."""

from __future__ import annotations

import os
from dataclasses import dataclass

from rich.text import Text
from textual.binding import Binding
from textual.message import Message
from textual.widgets import OptionList
from textual.widgets.option_list import Option

from hardboiled.core.events import EvtBreakpointsChanged


@dataclass(frozen=True)
class PointRef:
    kind: str  # "line", "address" o "watch"
    file: str | None = None
    line: int | None = None
    address: int | None = None
    expression: str | None = None


class BreakpointsView(OptionList):
    DEFAULT_CSS = """
    BreakpointsView { height: auto; max-height: 20; }
    """

    BINDINGS = [  # noqa: RUF012
        Binding("delete", "remove", "Quitar"),
        Binding("backspace", "remove", show=False),
    ]

    class RemoveRequested(Message):
        def __init__(self, point: PointRef) -> None:
            super().__init__()
            self.point = point

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.points: list[PointRef] = []

    def update_points(self, event: EvtBreakpointsChanged) -> None:
        self.points = [
            *(PointRef("line", file=f, line=n) for f, n in sorted(event.lines)),
            *(PointRef("address", address=a) for a in sorted(event.addresses)),
            *(PointRef("watch", expression=w.expression) for w in event.watches),
        ]
        prompts: list[Text] = []
        conditions = {(c.source_file, c.line): c for c in event.conditions}
        for f, n in sorted(event.lines):
            condition = conditions.get((f, n))
            marker = "◆ " if condition else "● "
            prompt = Text.assemble((marker, "bold red"), f"{os.path.basename(f)}:{n}")
            if condition is not None:
                prompt.append(f"  {condition.describe()}", style="italic")
            prompts.append(prompt)
        for a in sorted(event.addresses):
            prompts.append(Text.assemble(("● ", "bold red"), f"0x{a:08x}"))
        for w in event.watches:
            prompts.append(
                Text.assemble(
                    ("◉ ", "bold magenta"),
                    (w.expression, "bold"),
                    (f"  {w.type_name} @0x{w.address:08x}", "dim"),
                )
            )
        self.clear_options()
        if prompts:
            self.add_options([Option(p) for p in prompts])
        else:
            self.add_option(
                Option(Text("(sin breakpoints ni watchpoints)", style="dim"), disabled=True)
            )

    def action_remove(self) -> None:
        index = self.highlighted
        if index is not None and 0 <= index < len(self.points):
            self.post_message(self.RemoveRequested(self.points[index]))

    def on_option_list_option_selected(self, event: OptionList.OptionSelected) -> None:
        event.stop()
        self.action_remove()
