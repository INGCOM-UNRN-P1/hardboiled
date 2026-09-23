"""Aplicación Textual: la vista sólo envía comandos y dibuja eventos.

No conoce a la CPU: recibe dos colas y un hilo de trabajo ya construido. Los
eventos se drenan ~30 veces por segundo desde el hilo de la UI, y la salida de
la UART se agrupa para no redibujar un carácter por vez.
"""

from __future__ import annotations

import codecs
import os
import queue
import threading

from rich.text import Text
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Log, Static

from hardboiled.core.events import (
    CmdContinue,
    CmdPause,
    CmdReset,
    CmdShutdown,
    CmdStepInstruction,
    CmdStepInto,
    CmdStepOver,
    CmdToggleBreakpoint,
    CmdToggleSwitch,
    Command,
    Event,
    EvtBreakpointsChanged,
    EvtCpuRunning,
    EvtCpuSuspended,
    EvtHardwareUpdated,
    EvtMessage,
    EvtProgramExited,
    EvtProgramLoaded,
    EvtTrap,
    EvtUartOutput,
)
from hardboiled.ui.widgets.code_view import CodeView
from hardboiled.ui.widgets.hardware_view import HardwareView, SwitchBankView
from hardboiled.ui.widgets.memory_view import MemoryView
from hardboiled.ui.widgets.registers_view import RegistersView
from hardboiled.userconfig import UiPrefs

MAX_EVENTS_PER_FRAME = 5000


class HardboiledApp(App[None]):
    TITLE = "hardboiled"

    CSS = """
    #main { height: 1fr; }
    #left { width: 1fr; }
    #right { width: 52; }
    #code { height: 1fr; border: round $primary; }
    #code:focus { border: round $accent; }
    #uart { height: 9; border: round $primary; }
    #status { height: 1; padding: 0 1; background: $panel; }
    """

    BINDINGS = [  # noqa: RUF012 - convención de Textual
        Binding("f5", "continue", "Continue"),
        Binding("f6", "pause", "Pause"),
        Binding("f9", "toggle_breakpoint", "Breakpoint"),
        Binding("f10", "step_over", "Step Over"),
        Binding("f11", "step_into", "Step Into"),
        Binding("f7", "step_instruction", "Stepi"),
        Binding("c", "continue", show=False),
        Binding("p", "pause", show=False),
        Binding("b", "toggle_breakpoint", show=False),
        Binding("n", "step_over", show=False),
        Binding("s", "step_into", show=False),
        Binding("i", "step_instruction", show=False),
        Binding("r", "reset", "Reset"),
        Binding("q", "quit", "Salir"),
        *(Binding(str(pin), f"switch({pin})", show=False) for pin in range(8)),
    ]

    def __init__(
        self,
        cmd_queue: queue.Queue[Command],
        evt_queue: queue.Queue[Event],
        worker: threading.Thread | None = None,
        prefs: UiPrefs | None = None,
    ) -> None:
        super().__init__()
        self.prefs = prefs or UiPrefs()
        self.cmd_queue = cmd_queue
        self.evt_queue = evt_queue
        self.worker = worker
        self._breakpoints: frozenset[tuple[str, int]] = frozenset()
        self._uart_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield CodeView(id="code")
                yield Log(id="uart", highlight=False)
            with VerticalScroll(id="right"):
                yield HardwareView(id="hardware")
                yield RegistersView(id="registers")
                yield MemoryView(id="stack")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.theme = "textual-light" if self.prefs.theme == "light" else "textual-dark"
        self.query_one("#code").border_title = "Código"
        self.query_one("#uart").border_title = "Consola UART"
        self.query_one("#hardware").border_title = "Placa"
        self.query_one(CodeView).focus()
        self._set_status(Text("cargando…", style="dim"))
        self.set_interval(1 / 30, self._drain_events)
        if self.worker is not None and not self.worker.is_alive():
            self.worker.start()

    def on_unmount(self) -> None:
        self.cmd_queue.put(CmdShutdown())

    def send(self, command: Command) -> None:
        self.cmd_queue.put(command)

    # --------------------------------------------------------------- eventos

    def _drain_events(self) -> None:
        uart = bytearray()
        for _ in range(MAX_EVENTS_PER_FRAME):
            try:
                event = self.evt_queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(event, EvtUartOutput):
                uart.append(event.char_code)
                continue
            if uart:
                self._write_uart(bytes(uart))
                uart.clear()
            self.handle_event(event)
        if uart:
            self._write_uart(bytes(uart))

    def _write_uart(self, data: bytes) -> None:
        # La UART transmite bytes: se decodifican como UTF-8 aunque un carácter
        # multibyte quede repartido entre dos lotes.
        text = self._uart_decoder.decode(data)
        if text:
            self.query_one("#uart", Log).write(text)

    def handle_event(self, event: Event) -> None:
        match event:
            case EvtProgramLoaded():
                self.sub_title = f"{os.path.basename(event.elf_path)} · {event.board_name}"
                self.query_one(HardwareView).configure(event.peripherals)
                c_files = [f for f in event.source_files if f.endswith(".c")]
                if c_files:
                    self.query_one(CodeView).show_file(c_files[0])
                    self._refresh_breakpoints()
            case EvtCpuRunning():
                self._set_status(Text("▶ ejecutando…  (F6 pausa)", style="bold green"))
            case EvtCpuSuspended():
                self._on_suspended(event)
            case EvtHardwareUpdated():
                self.query_one(HardwareView).update_device(
                    event.device_name, event.register_offset, event.value
                )
            case EvtBreakpointsChanged():
                self._breakpoints = event.lines
                self._refresh_breakpoints()
            case EvtTrap():
                where = f" (dirección 0x{event.fault_address:08x})" if event.fault_address else ""
                self.notify(f"{event.reason}{where}", title="TRAP", severity="error", timeout=10)
            case EvtProgramExited():
                self.notify(f"main() devolvió {event.exit_code}", title="Programa terminado")
            case EvtMessage():
                self.notify(event.text, severity="warning")
            case EvtUartOutput():
                self._write_uart(bytes([event.char_code]))

    def _on_suspended(self, event: EvtCpuSuspended) -> None:
        code = self.query_one(CodeView)
        if event.source_file is not None:
            code.show_file(event.source_file)
            self._refresh_breakpoints()
            code.set_active_line(event.source_line)
        else:
            code.set_active_line(None)
        self.query_one(RegistersView).set_registers(event.registers)
        self.query_one(MemoryView).set_stack(
            event.stack, event.registers.get("x2", 0), event.registers.get("x8", 0)
        )
        status = Text()
        status.append("⏸ ", style="bold yellow")
        status.append(event.function or "??", style="bold")
        if event.source_file is not None:
            status.append(f"  {os.path.basename(event.source_file)}:{event.source_line}")
        status.append(f"  pc=0x{event.pc:08x}  ciclos={event.cycle_count:,}", style="dim")
        if event.reason:
            status.append(f"  · {event.reason}", style="italic")
        self._set_status(status)

    def _refresh_breakpoints(self) -> None:
        code = self.query_one(CodeView)
        code.set_breakpoints(frozenset(line for f, line in self._breakpoints if f == code.file))

    def _set_status(self, text: Text) -> None:
        self.query_one("#status", Static).update(text)

    # --------------------------------------------------------------- acciones

    def action_continue(self) -> None:
        self.send(CmdContinue())

    def action_pause(self) -> None:
        self.send(CmdPause())

    def action_step_over(self) -> None:
        self.send(CmdStepOver())

    def action_step_into(self) -> None:
        self.send(CmdStepInto())

    def action_step_instruction(self) -> None:
        self.send(CmdStepInstruction())

    def action_reset(self) -> None:
        self.query_one("#uart", Log).clear()
        self._uart_decoder.reset()
        self.send(CmdReset())

    def action_switch(self, pin: int) -> None:
        self.send(CmdToggleSwitch(pin))

    def action_toggle_breakpoint(self) -> None:
        code = self.query_one(CodeView)
        if code.file is not None:
            self.send(CmdToggleBreakpoint(code.cursor_line, code.file))

    def on_code_view_breakpoint_requested(self, message: CodeView.BreakpointRequested) -> None:
        self.send(CmdToggleBreakpoint(message.line, message.file))

    def on_switch_bank_view_toggled(self, message: SwitchBankView.Toggled) -> None:
        self.send(CmdToggleSwitch(message.pin_index))
