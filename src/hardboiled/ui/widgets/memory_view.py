"""Pila rotulada por marcos: qué función ocupa cada palabra y qué guardó ahí."""

from __future__ import annotations

from rich.text import Text
from textual.widgets import Static

from hardboiled.core.events import StackSlot


class MemoryView(Static):
    DEFAULT_CSS = """
    MemoryView { height: auto; border: round $primary; padding: 0 1; }
    """

    def __init__(self, *, id: str | None = None) -> None:
        super().__init__(id=id)
        self.border_title = "Pila (direcciones altas arriba)"

    def set_stack(self, slots: tuple[StackSlot, ...], sp: int, fp: int) -> None:
        text = Text(no_wrap=True, overflow="ellipsis")
        current_frame: object = object()
        # Direcciones altas arriba: la pila crece hacia abajo.
        for slot in reversed(slots):
            if slot.frame_index != current_frame:
                current_frame = slot.frame_index
                if slot.frame_index is None:
                    text.append("── libre (debajo de sp) ──\n", style="dim italic")
                else:
                    style = "bold magenta" if "IRQ" in (slot.frame_label or "") else "bold"
                    text.append(f"── #{slot.frame_index} {slot.frame_label} ──\n", style=style)
            text.append(f"{slot.address:08x}  ", style="dim")
            value_style = (
                "bold yellow" if slot.address == sp else ("dim" if slot.frame_index is None else "")
            )
            text.append(f"{slot.value:08x}", style=value_style)
            if slot.note:
                text.append(f"  {slot.note}", style="cyan")
            marks = [m for a, m in ((sp, "◀ sp"), (fp, "◀ s0/fp")) if slot.address == a]
            if marks:
                text.append("  " + " ".join(marks), style="bold yellow")
            text.append("\n")
        if not slots:
            text.append("(sp fuera de la SRAM)", style="dim")
        text.rstrip()
        self.update(text)
