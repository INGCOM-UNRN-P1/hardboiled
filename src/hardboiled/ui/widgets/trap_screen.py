"""Pantalla post-mortem: qué falló, dónde y cómo se llegó hasta ahí."""

from __future__ import annotations

import os

from rich.text import Text
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import ModalScreen
from textual.widgets import Label, Static

from hardboiled.core.events import EvtTrap, FrameInfo, collapse_frames


class TrapScreen(ModalScreen[None]):
    DEFAULT_CSS = """
    TrapScreen { align: center middle; }
    TrapScreen > Vertical {
        width: 90; height: auto; max-height: 90%; padding: 1 2;
        border: thick $error; background: $surface;
    }
    TrapScreen #trap-title { text-style: bold; color: $error; }
    TrapScreen .section { margin-top: 1; text-style: bold; }
    TrapScreen #trap-help { margin-top: 1; color: $text-muted; }
    """

    BINDINGS = [  # noqa: RUF012
        Binding("escape", "dismiss_trap", "Cerrar"),
        Binding("enter", "dismiss_trap", show=False),
    ]

    def __init__(self, trap: EvtTrap, frames: tuple[FrameInfo, ...]) -> None:
        super().__init__()
        self.trap = trap
        self.frames = frames

    def compose(self) -> ComposeResult:
        trap = self.trap
        with Vertical():
            yield Label("✖ TRAMPA: la ejecución se abortó", id="trap-title")
            yield Static(Text(trap.reason, style="bold"))
            where = Text()
            where.append(f"{trap.function or '??'}()", style="bold")
            if trap.source_file is not None:
                where.append(f"  {os.path.basename(trap.source_file)}:{trap.source_line}")
            if trap.pc is not None:
                where.append(f"  pc=0x{trap.pc:08x}", style="dim")
            yield Label("Dónde", classes="section")
            yield Static(where)
            if trap.instruction:
                yield Label("Instrucción que falló", classes="section")
                yield Static(Text(trap.instruction, style="bold yellow"))
            if trap.fault_address is not None:
                yield Static(
                    Text(f"dirección involucrada: 0x{trap.fault_address:08x}", style="dim")
                )
            if self.frames:
                yield Label("Pila de llamadas", classes="section")
                yield Static(self._frames())
            yield Label(
                "Esc cierra este panel: variables, registros y memoria quedan como estaban "
                "al fallar. F8 vuelve al paso anterior; r reinicia la placa.",
                id="trap-help",
            )

    def _frames(self) -> Text:
        text = Text()
        for frame, count in collapse_frames(self.frames):
            if frame.irq_line is not None:
                text.append(f"  ── {frame.label} ──\n", style="magenta")
                continue
            span = f"#{frame.index}" if count == 1 else f"#{frame.index}-#{frame.index + count - 1}"
            text.append(f"  {span} ", style="dim")
            text.append(frame.label, style="bold")
            if frame.source_file is not None:
                text.append(f"  {os.path.basename(frame.source_file)}:{frame.source_line}")
            if count > 1:
                text.append(f"  x{count} (recursión)", style="bold magenta")
            text.append("\n")
        text.rstrip()
        return text

    def action_dismiss_trap(self) -> None:
        self.dismiss(None)
