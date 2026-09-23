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
from textual.widgets import Footer, Header, Log, Static, TabbedContent, TabPane

from hardboiled.core.events import (
    CmdContinue,
    CmdPause,
    CmdReadMemory,
    CmdReset,
    CmdRunToLine,
    CmdSelectFrame,
    CmdSetBreakpointCondition,
    CmdShutdown,
    CmdStepBack,
    CmdStepInstruction,
    CmdStepInto,
    CmdStepOut,
    CmdStepOver,
    CmdToggleAddressBreakpoint,
    CmdToggleBreakpoint,
    CmdToggleSwitch,
    CmdToggleWatchpoint,
    Command,
    Event,
    EvtBreakpointsChanged,
    EvtCpuProgress,
    EvtCpuRunning,
    EvtCpuSuspended,
    EvtFrameVariables,
    EvtHardwareUpdated,
    EvtMemoryDump,
    EvtMessage,
    EvtProgramExited,
    EvtProgramLoaded,
    EvtTrap,
    EvtUartOutput,
)
from hardboiled.ui.widgets.backtrace_view import BacktraceView
from hardboiled.ui.widgets.breakpoints_view import BreakpointsView
from hardboiled.ui.widgets.code_view import CodeView
from hardboiled.ui.widgets.disasm_view import DisassemblyView
from hardboiled.ui.widgets.hardware_view import HardwareView, SwitchBankView
from hardboiled.ui.widgets.memory_inspector import MemoryInspector
from hardboiled.ui.widgets.memory_view import MemoryView
from hardboiled.ui.widgets.prompt import Prompt
from hardboiled.ui.widgets.registers_view import RegistersView
from hardboiled.ui.widgets.trap_screen import TrapScreen
from hardboiled.ui.widgets.variables_view import VariablesView
from hardboiled.userconfig import UiPrefs

MAX_EVENTS_PER_FRAME = 5000


def parse_condition(text: str) -> tuple[str | None, int | None]:
    """`"i == 3 #5"` -> ("i == 3", 5). La cantidad de pasadas va al final con #."""
    text = text.strip()
    hits = None
    if "#" in text:
        text, _, count = text.rpartition("#")
        text = text.strip()
        if not count.strip().isdigit() or int(count) < 1:
            raise ValueError(f"cantidad de pasadas inválida: #{count.strip()}")
        hits = int(count)
    return (text or None), hits


class HardboiledApp(App[None]):
    TITLE = "hardboiled"

    CSS = """
    #main { height: 1fr; }
    #left { width: 1fr; }
    #right { width: 60; }
    #inspect { height: auto; }
    #code { height: 1fr; border: round $primary; }
    #code:focus { border: round $accent; }
    #uart { height: 9; border: round $primary; }
    #disasm { display: none; }
    #disasm.visible { display: block; }
    #status { height: 1; padding: 0 1; background: $panel; }
    """

    BINDINGS = [  # noqa: RUF012 - convención de Textual
        Binding("f5", "continue", "Continue"),
        Binding("f6", "pause", "Pause"),
        Binding("f9", "toggle_breakpoint", "Breakpoint"),
        Binding("f10", "step_over", "Step Over"),
        Binding("f11", "step_into", "Step Into"),
        Binding("shift+f11", "step_out", "Step Out"),
        Binding("f7", "step_instruction", "Stepi"),
        Binding("f8", "step_back", "Atrás"),
        Binding("f4", "run_to_cursor", "Hasta cursor"),
        Binding("c", "continue", show=False),
        Binding("p", "pause", show=False),
        Binding("b", "toggle_breakpoint", show=False),
        Binding("n", "step_over", show=False),
        Binding("s", "step_into", show=False),
        Binding("i", "step_instruction", show=False),
        Binding("o", "step_out", show=False),
        Binding("u", "step_back", show=False),
        Binding("g", "run_to_cursor", show=False),
        Binding("w", "watch", "Watch"),
        Binding("d", "toggle_disassembly", "ASM"),
        Binding("x", "register_format", show=False),
        Binding("B", "conditional_breakpoint", show=False),
        Binding("ctrl+f9", "conditional_breakpoint", show=False),
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
        self._suspended: EvtCpuSuspended | None = None
        self._pending_trap: EvtTrap | None = None
        self._conditional: frozenset[tuple[str | None, int]] = frozenset()
        self._uart_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield CodeView(id="code")
                yield DisassemblyView(id="disasm")
                yield Log(id="uart", highlight=False)
            with VerticalScroll(id="right"):
                yield HardwareView(id="hardware")
                yield BacktraceView(id="backtrace")
                with TabbedContent(id="inspect"):
                    with TabPane("Variables", id="tab-variables"):
                        yield VariablesView(id="variables")
                    with TabPane("Registros", id="tab-registers"):
                        yield RegistersView(id="registers")
                    with TabPane("Pila", id="tab-stack"):
                        yield MemoryView(id="stack")
                    with TabPane("Puntos", id="tab-points"):
                        yield BreakpointsView(id="points")
                    with TabPane("Memoria", id="tab-memory"):
                        yield MemoryInspector(id="memory")
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
            case EvtCpuProgress():
                status = Text()
                status.append("▶ ejecutando ", style="bold green")
                status.append(event.function or "??", style="bold")
                status.append(
                    f"  pc=0x{event.pc:08x}  ciclos={event.cycle_count:,}"
                    f"  {event.instructions_per_second / 1e6:.2f} M instr/s",
                    style="dim",
                )
                status.append("  (F6 pausa)", style="green")
                self._set_status(status)
            case EvtCpuSuspended():
                self._on_suspended(event)
            case EvtMemoryDump():
                self.query_one(MemoryInspector).show(event)
            case EvtFrameVariables():
                self.query_one(VariablesView).set_frame_locals(event.locals, event.label)
            case EvtHardwareUpdated():
                self.query_one(HardwareView).update_device(
                    event.device_name, event.register_offset, event.value
                )
            case EvtBreakpointsChanged():
                self._breakpoints = event.lines
                self._conditional = frozenset(
                    (c.source_file, c.line) for c in event.conditions if c.line is not None
                )
                self._refresh_breakpoints()
                self.query_one(BreakpointsView).update_points(event)
                self.query_one(DisassemblyView).set_breakpoints(event.addresses)
            case EvtTrap():
                # Se muestra al llegar la suspensión, que trae la pila de llamadas.
                self._pending_trap = event
            case EvtProgramExited():
                self.notify(f"main() devolvió {event.exit_code}", title="Programa terminado")
            case EvtMessage():
                self.notify(event.text, severity="warning")
            case EvtUartOutput():
                self._write_uart(bytes([event.char_code]))

    def _on_suspended(self, event: EvtCpuSuspended) -> None:
        self._suspended = event
        self._show_location(event.source_file, event.source_line)
        trap, self._pending_trap = self._pending_trap, None
        code = self.query_one(CodeView)
        code.set_trap_line(trap.source_line if trap is not None else None)
        if trap is not None:
            self.push_screen(TrapScreen(trap, event.frames))
        self.query_one(BacktraceView).set_frames(event.frames)
        self.query_one(DisassemblyView).show(event.disassembly, event.pc)
        self.query_one(MemoryInspector).refresh_request()
        function = event.frames[0].label if event.frames else event.function
        self.query_one(VariablesView).set_variables(event.locals, event.global_vars, function)
        self.query_one(RegistersView).set_registers(event.registers, event.register_symbols)
        self.query_one(MemoryView).set_stack(
            event.stack_slots, event.registers.get("x2", 0), event.registers.get("x8", 0)
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

    def _show_location(self, source_file: str | None, line: int | None) -> None:
        """Muestra la línea en ejecución (marco 0)."""
        code = self.query_one(CodeView)
        if source_file is not None:
            code.show_file(source_file)
            self._refresh_breakpoints()
            code.set_frame_line(None)
            code.set_active_line(line)
        else:
            code.set_active_line(None)

    def on_backtrace_view_frame_chosen(self, message: BacktraceView.FrameChosen) -> None:
        frame = message.frame
        if frame.irq_line is None:
            self.send(CmdSelectFrame(frame.index))
        if frame.index == 0 and self._suspended is not None:
            self._show_location(self._suspended.source_file, self._suspended.source_line)
            return
        if frame.source_file is None:
            self.notify(f"{frame.label}: sin código fuente", severity="warning")
            return
        code = self.query_one(CodeView)
        code.show_file(frame.source_file)
        self._refresh_breakpoints()
        if self._suspended is not None and self._suspended.source_file == frame.source_file:
            code.set_active_line(self._suspended.source_line)
        code.set_frame_line(frame.source_line)

    def _refresh_breakpoints(self) -> None:
        code = self.query_one(CodeView)
        code.set_breakpoints(
            frozenset(line for f, line in self._breakpoints if f == code.file),
            frozenset(line for f, line in self._conditional if f == code.file),
        )

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

    def action_step_back(self) -> None:
        self.send(CmdStepBack())

    def action_step_out(self) -> None:
        self.send(CmdStepOut())

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

    def action_run_to_cursor(self) -> None:
        code = self.query_one(CodeView)
        if code.file is not None:
            self.send(CmdRunToLine(code.cursor_line, code.file))

    def action_conditional_breakpoint(self) -> None:
        code = self.query_one(CodeView)
        if code.file is None:
            return
        file, line = code.file, code.cursor_line

        def submit(text: str | None) -> None:
            if text is None:
                return
            try:
                condition, hits = parse_condition(text)
            except ValueError as exc:
                self.notify(str(exc), severity="error")
                return
            self.send(CmdSetBreakpointCondition(line, file, condition, hits))

        self.push_screen(
            Prompt(
                f"Breakpoint condicional en la línea {line}:",
                "i == 3     #5     n > 2 #2",
                help="Una expresión C detiene sólo si es verdadera; #N detiene desde la "
                "pasada N. Vacío: breakpoint común.",
            ),
            submit,
        )

    def on_memory_inspector_dump_requested(self, message: MemoryInspector.DumpRequested) -> None:
        self.send(CmdReadMemory(message.where))

    def action_register_format(self) -> None:
        mode = self.query_one(RegistersView).cycle_format()
        self.notify(f"registros en formato: {mode}", timeout=2)

    def action_toggle_disassembly(self) -> None:
        self.query_one(DisassemblyView).toggle_class("visible")

    def on_disassembly_view_address_breakpoint_requested(
        self, message: DisassemblyView.AddressBreakpointRequested
    ) -> None:
        self.send(CmdToggleAddressBreakpoint(message.address))

    def action_watch(self) -> None:
        def submit(expression: str | None) -> None:
            if expression:
                self.send(CmdToggleWatchpoint(expression))

        self.push_screen(
            Prompt(
                "Vigilar una expresión (detiene cuando cambia):",
                "results[1], total, f->color, *p…",
                help="La misma expresión otra vez quita el watchpoint. "
                "Los de variables locales se eliminan al terminar su función.",
            ),
            submit,
        )

    def on_breakpoints_view_remove_requested(
        self, message: BreakpointsView.RemoveRequested
    ) -> None:
        point = message.point
        if point.kind == "line" and point.line is not None:
            self.send(CmdToggleBreakpoint(point.line, point.file))
        elif point.kind == "address" and point.address is not None:
            self.send(CmdToggleAddressBreakpoint(point.address))
        elif point.kind == "watch" and point.expression is not None:
            self.send(CmdToggleWatchpoint(point.expression))

    def on_code_view_breakpoint_requested(self, message: CodeView.BreakpointRequested) -> None:
        self.send(CmdToggleBreakpoint(message.line, message.file))

    def on_switch_bank_view_toggled(self, message: SwitchBankView.Toggled) -> None:
        self.send(CmdToggleSwitch(message.pin_index))
