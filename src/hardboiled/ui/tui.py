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
from textual import events
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.widgets import Footer, Header, Input, Log, Static, TabbedContent, TabPane

from hardboiled.core.events import (
    CmdContinue,
    CmdPause,
    CmdPressButton,
    CmdProfile,
    CmdReadMemory,
    CmdReset,
    CmdRunToLine,
    CmdSelectFrame,
    CmdSetBreakpointCondition,
    CmdSetClock,
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
    CmdUartInput,
    Command,
    Event,
    EvtBreakpointsChanged,
    EvtClockChanged,
    EvtCpuProgress,
    EvtCpuRunning,
    EvtCpuSuspended,
    EvtFrameVariables,
    EvtHardwareUpdated,
    EvtMemoryDump,
    EvtMessage,
    EvtProfile,
    EvtProgramExited,
    EvtProgramLoaded,
    EvtTrap,
    EvtUartOutput,
    EvtWarning,
)
from hardboiled.i18n import N_, _
from hardboiled.ui.palette import palette_for
from hardboiled.ui.widgets.backtrace_view import BacktraceView
from hardboiled.ui.widgets.breakpoints_view import BreakpointsView
from hardboiled.ui.widgets.code_view import CodeView
from hardboiled.ui.widgets.disasm_view import DisassemblyView
from hardboiled.ui.widgets.file_picker import FilePicker
from hardboiled.ui.widgets.hardware_view import ButtonBankView, HardwareView, SwitchBankView
from hardboiled.ui.widgets.help_screen import HelpScreen
from hardboiled.ui.widgets.memory_inspector import MemoryInspector
from hardboiled.ui.widgets.memory_view import MemoryView
from hardboiled.ui.widgets.prompt import Prompt
from hardboiled.ui.widgets.registers_view import RegistersView
from hardboiled.ui.widgets.trap_screen import TrapScreen
from hardboiled.ui.widgets.variables_view import VariablesView
from hardboiled.userconfig import UiPrefs

MAX_EVENTS_PER_FRAME = 5000


# (acción, teclas por defecto, descripción en el pie o "" para no mostrarla).
DEFAULT_KEYS: tuple[tuple[str, str, str], ...] = (
    ("continue", "f5,c", N_("Continue")),
    ("pause", "f6,p", N_("Pause")),
    ("toggle_breakpoint", "f9,b", N_("Breakpoint")),
    ("step_over", "f10,n", N_("Step Over")),
    ("step_into", "f11,s", N_("Step Into")),
    ("step_out", "shift+f11,o", N_("Step Out")),
    ("step_instruction", "f7,i", N_("Stepi")),
    ("step_back", "f8,u", N_("Atrás")),
    ("run_to_cursor", "f4,g", N_("Hasta cursor")),
    ("watch", "w", N_("Watch")),
    ("toggle_disassembly", "d", N_("ASM")),
    ("toggle_profile", "h", N_("Perfil")),
    ("open_file", "f", N_("Archivos")),
    ("search", "slash", N_("Buscar")),
    ("search_next", "f3", ""),
    ("search_previous", "shift+f3", ""),
    ("goto_line", "colon", ""),
    ("register_format", "x", ""),
    ("conditional_breakpoint", "B,ctrl+f9", ""),
    ("clock_faster", "plus", ""),
    ("clock_slower", "minus", ""),
    ("clock_unlimited", "equals_sign", ""),
    ("help", "question_mark", N_("Ayuda")),
    ("reset", "r", N_("Reset")),
    ("quit", "q", N_("Salir")),
)
KEY_ACTIONS = frozenset(action for action, _, _ in DEFAULT_KEYS) | {
    f"switch_{pin}" for pin in range(8)
}

# Nombres amigables para config.toml ("/" en lugar de "slash").
KEY_ALIASES = {"/": "slash", ":": "colon", "?": "question_mark"}


def normalize_keys(keys: str) -> str:
    return ",".join(
        KEY_ALIASES.get(k.strip(), k.strip().lower() if len(k.strip()) > 1 else k.strip())
        for k in keys.split(",")
        if k.strip()
    )


MIN_CLOCK_HZ = 1_000
MAX_CLOCK_HZ = 100_000_000
DEFAULT_CLOCK_HZ = 1_000_000


def format_hz(hz: int | None) -> str:
    if hz is None:
        return _("sin límite (+/- para fijarlo, = alterna)")
    for unit, scale in (("MHz", 1_000_000), ("kHz", 1_000)):
        if hz >= scale:
            return f"{hz / scale:g} {unit}"
    return f"{hz} Hz"


def parse_condition(text: str) -> tuple[str | None, int | None]:
    """`"i == 3 #5"` -> ("i == 3", 5). La cantidad de pasadas va al final con #."""
    text = text.strip()
    hits = None
    if "#" in text:
        text, _sep, count = text.rpartition("#")
        text = text.strip()
        if not count.strip().isdigit() or int(count) < 1:
            raise ValueError(_("cantidad de pasadas inválida: #{count}", count=count.strip()))
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
    #uart-input { height: 3; }
    #disasm { display: none; }
    #disasm.visible { display: block; }
    #status { height: 1; padding: 0 1; background: $panel; }
    """

    BINDINGS = [  # noqa: RUF012 - convención de Textual
        # El id de cada binding es el nombre que se usa en [keys] de config.toml.
        *(
            Binding(keys, action, _(description), show=bool(description), id=action)
            for action, keys, description in DEFAULT_KEYS
        ),
        *(Binding(str(pin), f"switch({pin})", show=False, id=f"switch_{pin}") for pin in range(8)),
    ]

    def __init__(
        self,
        cmd_queue: queue.Queue[Command],
        evt_queue: queue.Queue[Event],
        worker: threading.Thread | None = None,
        prefs: UiPrefs | None = None,
        keymap: dict[str, str] | None = None,
    ) -> None:
        super().__init__()
        self.prefs = prefs or UiPrefs()
        self.palette = palette_for(self.prefs.theme, self.prefs.colorblind)
        self.user_keymap = dict(keymap or {})
        self.cmd_queue = cmd_queue
        self.evt_queue = evt_queue
        self.worker = worker
        self._breakpoints: frozenset[tuple[str, int]] = frozenset()
        self._suspended: EvtCpuSuspended | None = None
        self._pending_trap: EvtTrap | None = None
        self._source_files: tuple[str, ...] = ()
        self._last_search = ""
        self._program: EvtProgramLoaded | None = None
        self._clock_hz: int | None = None
        self._last_clock_hz = DEFAULT_CLOCK_HZ
        self._conditional: frozenset[tuple[str | None, int]] = frozenset()
        self._profiling = False  # mapa de calor en la vista de código
        self._profile_note = True  # el primer perfil se resume en una notificación
        self._uart_decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")

    def compose(self) -> ComposeResult:
        yield Header()
        with Horizontal(id="main"):
            with Vertical(id="left"):
                yield CodeView(id="code")
                yield DisassemblyView(id="disasm")
                yield Log(id="uart", highlight=False)
                yield Input(
                    placeholder=_("escribí y Enter para enviar por la UART (Esc vuelve al código)"),
                    id="uart-input",
                )
            with VerticalScroll(id="right"):
                yield HardwareView(id="hardware")
                yield BacktraceView(id="backtrace")
                with TabbedContent(id="inspect"):
                    with TabPane(_("Variables"), id="tab-variables"):
                        yield VariablesView(id="variables")
                    with TabPane(_("Registros"), id="tab-registers"):
                        yield RegistersView(id="registers")
                    with TabPane(_("Pila"), id="tab-stack"):
                        yield MemoryView(id="stack")
                    with TabPane(_("Puntos"), id="tab-points"):
                        yield BreakpointsView(id="points")
                    with TabPane(_("Memoria"), id="tab-memory"):
                        yield MemoryInspector(id="memory")
        yield Static(id="status")
        yield Footer()

    def on_mount(self) -> None:
        self.theme = "textual-light" if self.prefs.theme == "light" else "textual-dark"
        self._apply_keymap()
        self.query_one("#code").border_title = _("Código")
        self.query_one("#uart").border_title = _("Consola UART")
        self.query_one("#hardware").border_title = _("Placa")
        self.query_one(CodeView).focus()
        self._set_status(Text(_("cargando…"), style="dim"))
        self.set_interval(1 / 30, self._drain_events)
        if self.worker is not None and not self.worker.is_alive():
            self.worker.start()

    def on_unmount(self) -> None:
        self.cmd_queue.put(CmdShutdown())

    def _apply_keymap(self) -> None:
        """Aplica [keys] de config.toml; las acciones desconocidas se informan."""
        if not self.user_keymap:
            return
        unknown = sorted(set(self.user_keymap) - KEY_ACTIONS)
        valid = {
            action: normalize_keys(keys)
            for action, keys in self.user_keymap.items()
            if action in KEY_ACTIONS and normalize_keys(keys)
        }
        self.set_keymap(valid)
        if unknown:
            self.notify(
                _(
                    "acciones desconocidas en [keys]: {actions} (ver ? para la lista)",
                    actions=", ".join(unknown),
                ),
                severity="warning",
            )

    def send(self, command: Command) -> None:
        self.cmd_queue.put(command)

    # --------------------------------------------------------------- eventos

    def _drain_events(self) -> None:
        uart = bytearray()
        for _event in range(MAX_EVENTS_PER_FRAME):
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
                self._program = event
                self._source_files = event.source_files
                self.sub_title = f"{os.path.basename(event.elf_path)} · {event.board_name}"
                self.query_one(HardwareView).configure(event.peripherals)
                c_files = [f for f in event.source_files if f.endswith(".c")]
                if c_files:
                    self.query_one(CodeView).show_file(c_files[0])
                    self._refresh_breakpoints()
            case EvtCpuRunning():
                self._set_status(Text(_("▶ ejecutando…  (F6 pausa)"), style="bold green"))
            case EvtCpuProgress():
                if self._profiling:
                    self.send(CmdProfile())  # mapa de calor en vivo (cada ~0,2 s)
                status = Text()
                status.append(_("▶ ejecutando "), style="bold green")
                status.append(event.function or "??", style="bold")
                status.append(
                    f"  pc=0x{event.pc:08x}  "
                    + _("ciclos={cycles}", cycles=f"{event.cycle_count:,}")
                    + f"  {event.instructions_per_second / 1e6:.2f} M instr/s",
                    style="dim",
                )
                status.append(_("  (F6 pausa)"), style="green")
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
                self.notify(
                    _("main() devolvió {code}", code=event.exit_code),
                    title=_("Programa terminado"),
                )
            case EvtWarning():
                where = (
                    f"{os.path.basename(event.source_file)}:{event.source_line}"
                    if event.source_file
                    else f"0x{event.pc:08x}"
                )
                hint = f"\n{event.hint}" if event.hint else ""
                self.notify(
                    f"{event.text}\n{where}{hint}\n(hardboiled explain {event.kind})",
                    title=_("Aviso"),
                    severity="warning",
                    timeout=10,
                )
            case EvtClockChanged():
                if event.hz is not None:
                    self._last_clock_hz = event.hz
                self._clock_hz = event.hz
                self._update_clock_title()
            case EvtProfile():
                self._show_profile(event)
            case EvtMessage():
                self.notify(event.text, severity="warning")
            case EvtUartOutput():
                self._write_uart(bytes([event.char_code]))

    def _on_suspended(self, event: EvtCpuSuspended) -> None:
        self._suspended = event
        if self._profiling:
            self.send(CmdProfile())
        self._show_location(event.source_file, event.source_line)
        trap, self._pending_trap = self._pending_trap, None
        code = self.query_one(CodeView)
        code.set_trap_line(trap.source_line if trap is not None else None)
        if trap is not None:
            self.push_screen(TrapScreen(trap, event.frames))
        self.query_one(BacktraceView).set_frames(event.frames)
        self.query_one(HardwareView).update_states(event.devices)
        uart_state = next(
            (dict(items) for name, items in event.devices if "rx_pending" in dict(items)), {}
        )
        pending = uart_state.get("rx_pending", 0)
        self.query_one("#uart").border_title = (
            _("Consola UART ({count} bytes recibidos sin leer)", count=pending)
            if pending
            else _("Consola UART")
        )
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
        status.append(
            f"  pc=0x{event.pc:08x}  " + _("ciclos={cycles}", cycles=f"{event.cycle_count:,}"),
            style="dim",
        )
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
            self.notify(_("{frame}: sin código fuente", frame=frame.label), severity="warning")
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

    def _update_clock_title(self) -> None:
        self.query_one("#hardware").border_title = _(
            "Placa · reloj {clock}", clock=format_hz(self._clock_hz)
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
                _("Breakpoint condicional en la línea {line}:", line=line),
                "i == 3     #5     n > 2 #2",
                help=_(
                    "Una expresión C detiene sólo si es verdadera; #N detiene desde la "
                    "pasada N. Vacío: breakpoint común."
                ),
            ),
            submit,
        )

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id != "uart-input":
            return
        event.stop()
        self.send(CmdUartInput(event.value.encode("utf-8") + b"\n"))
        event.input.value = ""

    def on_key(self, event: events.Key) -> None:
        if event.key == "escape" and self.focused is not None and self.focused.id == "uart-input":
            self.query_one(CodeView).focus()

    def on_memory_inspector_dump_requested(self, message: MemoryInspector.DumpRequested) -> None:
        self.send(CmdReadMemory(message.where))

    def current_keys(self) -> dict[str, list[str]]:
        """Teclas vigentes por acción (incluidas las reasignadas por el usuario)."""
        keys: dict[str, list[str]] = {}
        for key, active in self.active_bindings.items():
            action = active.binding.action
            if active.node is self:
                keys.setdefault(action, []).append(key)
        return keys

    def action_help(self) -> None:
        self.push_screen(HelpScreen(self.current_keys(), self._program))

    def action_search(self) -> None:
        def submit(text: str | None) -> None:
            code = self.query_one(CodeView)
            if not text:
                code.clear_search()
                return
            self._last_search = text
            if code.find(text) is None:
                self.notify(_("no se encontró {text}", text=repr(text)), severity="warning")

        self.push_screen(
            Prompt(
                _("Buscar en el código:"),
                value=self._last_search,
                help=_("F3 siguiente, Shift+F3 anterior; vacío quita el resaltado."),
            ),
            submit,
        )

    def _search_again(self, backwards: bool) -> None:
        if not self._last_search:
            self.action_search()
            return
        if self.query_one(CodeView).find(self._last_search, backwards) is None:
            self.notify(
                _("no se encontró {text}", text=repr(self._last_search)), severity="warning"
            )

    def action_search_next(self) -> None:
        self._search_again(backwards=False)

    def action_search_previous(self) -> None:
        self._search_again(backwards=True)

    def action_goto_line(self) -> None:
        def submit(text: str | None) -> None:
            if text is None or not text.strip():
                return
            if not text.strip().isdigit() or not self.query_one(CodeView).goto_line(int(text)):
                self.notify(_("línea inválida: {text}", text=text), severity="warning")

        self.push_screen(Prompt(_("Ir a la línea:"), _("número")), submit)

    def _change_clock(self, hz: int | None) -> None:
        self.send(CmdSetClock(hz))

    def action_clock_faster(self) -> None:
        if self._clock_hz is not None:
            self._change_clock(min(self._clock_hz * 2, MAX_CLOCK_HZ))

    def action_clock_slower(self) -> None:
        current = self._clock_hz or self._last_clock_hz
        self._change_clock(max(current // 2, MIN_CLOCK_HZ))

    def action_clock_unlimited(self) -> None:
        if self._clock_hz is None:
            self._change_clock(self._last_clock_hz)
        else:
            self._change_clock(None)

    def action_open_file(self) -> None:
        if not self._source_files:
            self.notify(_("el programa no tiene archivos fuente con información de depuración"))
            return
        code = self.query_one(CodeView)

        def opened(path: str | None) -> None:
            if path is None:
                return
            code.show_file(path)
            self._refresh_breakpoints()
            suspended = self._suspended
            if suspended is not None and suspended.source_file == path:
                code.set_active_line(suspended.source_line)
            code.focus()

        self.push_screen(FilePicker(self._source_files, code.file), opened)

    def action_register_format(self) -> None:
        mode = self.query_one(RegistersView).cycle_format()
        self.notify(_("registros en formato: {mode}", mode=_(mode)), timeout=2)

    def action_toggle_disassembly(self) -> None:
        self.query_one(DisassemblyView).toggle_class("visible")

    def action_toggle_profile(self) -> None:
        self._profiling = not self._profiling
        if self._profiling:
            self._profile_note = True
            self.send(CmdProfile())
        else:
            self.query_one(CodeView).set_profile(None)
            self.notify(_("mapa de calor oculto"), timeout=2)

    def _show_profile(self, event: EvtProfile) -> None:
        if not self._profiling:
            return
        self.query_one(CodeView).set_profile(
            {(file, line): count for file, line, count in event.lines}
        )
        if self._profile_note:
            self._profile_note = False
            top = ", ".join(
                f"{name} {100 * count / event.total:.0f}%"
                for name, count in event.functions[:4]
                if event.total
            )
            self.notify(
                _("{count} instrucciones desde el reset", count=f"{event.total:,}")
                + (f"\n{top}" if top else ""),
                title=_("Perfil (h lo oculta)"),
                timeout=6,
            )

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
                _("Vigilar una expresión (detiene cuando cambia):"),
                "results[1], total, f->color, *p…",
                help=_(
                    "La misma expresión otra vez quita el watchpoint. "
                    "Los de variables locales se eliminan al terminar su función."
                ),
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

    def on_button_bank_view_pressed(self, message: ButtonBankView.Pressed) -> None:
        self.send(CmdPressButton(message.pin_index))

    def on_switch_bank_view_toggled(self, message: SwitchBankView.Toggled) -> None:
        self.send(CmdToggleSwitch(message.pin_index))
