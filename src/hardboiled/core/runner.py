"""Hilo de trabajo que ejecuta la CPU emulada y habla con la UI sólo por colas.

Mientras la CPU corre (Continue o un step largo) el hilo no puede bloquearse
en `cmd_queue.get()`, así que la CPU consulta periódicamente `_poll()`: ahí se
aplican en vivo los comandos que no requieren detener la CPU (switches,
breakpoints) y se atienden Pause/Shutdown. Los comandos de ejecución que
llegan mientras la CPU corre se descartan; Reset se posterga hasta que pare.
"""

from __future__ import annotations

import queue
import threading
from collections import deque
from collections.abc import Callable

from hardboiled.core.cpu import StopInfo, StopReason
from hardboiled.core.debugger import DebuggerError
from hardboiled.core.events import (
    CmdContinue,
    CmdPause,
    CmdReset,
    CmdRunToLine,
    CmdSelectFrame,
    CmdSetBreakpointCondition,
    CmdShutdown,
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
    EvtCpuRunning,
    EvtCpuSuspended,
    EvtFrameVariables,
    EvtHardwareUpdated,
    EvtMessage,
    EvtProgramExited,
    EvtProgramLoaded,
    EvtTrap,
    FrameInfo,
    WatchInfo,
)
from hardboiled.core.machine import Machine
from hardboiled.core.session import BreakpointStore
from hardboiled.core.unwind import Frame
from hardboiled.hardware import LedBar, SwitchBank


class RunnerThread(threading.Thread):
    def __init__(
        self,
        machine: Machine,
        cmd_queue: queue.Queue[Command],
        evt_queue: queue.Queue[Event],
        stop_at_main: bool = True,
        store: BreakpointStore | None = None,
    ) -> None:
        super().__init__(name="hardboiled-runner", daemon=True)
        self.machine = machine
        self.store = store
        self.cmd_queue = cmd_queue
        self.evt_queue = evt_queue
        self.stop_at_main = stop_at_main
        self._deferred: deque[Command] = deque()
        self._known_watches: set[str] = set()
        self._shutdown = False
        machine.set_event_sink(self._emit)
        machine.cpu.poll = self._poll

    def _emit(self, event: Event) -> None:
        self.evt_queue.put(event)

    # ------------------------------------------------------------------ bucle

    def run(self) -> None:
        self._announce()
        self._restore_breakpoints()
        self._boot()
        while not self._shutdown:
            command = self._deferred.popleft() if self._deferred else self.cmd_queue.get()
            self._dispatch(command)

    def _announce(self) -> None:
        machine = self.machine
        self._emit(
            EvtProgramLoaded(
                elf_path=str(machine.image.path),
                board_name=machine.board.board.name,
                entry_point=machine.image.entry,
                source_files=machine.lines.user_files,
                peripherals=machine.peripheral_info(),
            )
        )

    def _restore_breakpoints(self) -> None:
        if self.store is None:
            return
        failed = self.store.restore(self.machine.debugger)
        if failed:
            self._emit(
                EvtMessage("no se pudieron restaurar: " + ", ".join(failed) + " (código cambiado)")
            )
        if self.machine.debugger.line_breakpoints or self.machine.debugger.watchpoints:
            self._emit_breakpoints()

    def _boot(self) -> None:
        for dev in self.machine.peripherals:
            if isinstance(dev, LedBar | SwitchBank):
                self._emit(EvtHardwareUpdated(dev.name, 0, dev.value))
        if self.stop_at_main:
            self._emit(EvtCpuRunning())
            stop = self.machine.debugger.run_to_main()
            if stop is not None:
                self._report(stop, "inicio de main()")
                return
        self._suspended("reset")

    def _dispatch(self, command: Command) -> None:
        debugger = self.machine.debugger
        match command:
            case CmdShutdown():
                self._shutdown = True
            case CmdStepInto():
                self._execute(debugger.step_into)
            case CmdStepOver():
                self._execute(debugger.step_over)
            case CmdContinue():
                self._execute(debugger.continue_)
            case CmdStepInstruction():
                self._execute(debugger.step_instruction)
            case CmdStepOut():
                if len(debugger.backtrace()) < 2:
                    self._emit(EvtMessage("no hay una función llamadora a la que volver"))
                else:
                    self._execute(debugger.step_out)
            case CmdRunToLine(line_number=line, source_file=source):
                try:
                    address = debugger.resolve_line(line, source)[2]
                except DebuggerError as exc:
                    self._emit(EvtMessage(str(exc)))
                else:
                    self._execute(lambda: debugger.run_to(address))
            case CmdReset():
                self.machine.reset()
                self._emit(EvtMessage("placa reiniciada"))
                self._boot()
            case CmdPause():
                pass  # la CPU ya está detenida
            case CmdSelectFrame(index=index):
                frames = debugger.backtrace()
                if 0 <= index < len(frames):
                    frame = frames[index]
                    label = frame.function or self.machine.image.describe(frame.site)
                    locals_ = debugger.locals_of(frame) if frame.irq_line is None else ()
                    self._emit(EvtFrameVariables(index, label, locals_))
            case _:
                self._apply_live(command)

    def _apply_live(self, command: Command) -> None:
        debugger = self.machine.debugger
        try:
            match command:
                case CmdToggleBreakpoint(line_number=line, source_file=source):
                    debugger.toggle_line_breakpoint(line, source)
                case CmdToggleAddressBreakpoint(address=address):
                    debugger.toggle_address_breakpoint(address)
                case CmdToggleWatchpoint(expression=expression):
                    debugger.toggle_watchpoint(expression)
                case CmdSetBreakpointCondition(
                    line_number=line, source_file=source, condition=condition, hit_count=hits
                ):
                    debugger.set_condition(line, source, condition, hits)
                case CmdToggleSwitch(pin_index=pin):
                    switches = self.machine.switches()
                    if switches is None:
                        raise DebuggerError("la placa no tiene switches")
                    switches.toggle(pin)
                    return
                case _:
                    return
        except (DebuggerError, ValueError) as exc:
            self._emit(EvtMessage(str(exc)))
            return
        self._emit_breakpoints()

    def _emit_breakpoints(self) -> None:
        debugger = self.machine.debugger
        watches = tuple(
            WatchInfo(w.expression, w.address, w.ctype.size, w.ctype.name)
            for w in debugger.watchpoints
        )
        self._known_watches = {w.expression for w in watches}
        if self.store is not None:
            self.store.save(debugger)
        self._emit(
            EvtBreakpointsChanged(debugger.line_breakpoints, debugger.address_breakpoints, watches)
        )

    def _poll(self) -> bool:
        """Llamado desde el hook de la CPU: True pide pausar la ejecución."""
        pause = False
        while True:
            try:
                command = self.cmd_queue.get_nowait()
            except queue.Empty:
                return pause
            match command:
                case CmdPause():
                    pause = True
                case CmdShutdown():
                    self._shutdown = True
                    pause = True
                case CmdReset():
                    self._deferred.append(command)
                    pause = True
                case (
                    CmdStepInto()
                    | CmdStepOver()
                    | CmdContinue()
                    | CmdStepInstruction()
                    | CmdRunToLine()
                ):
                    pass  # ya está corriendo
                case _:
                    self._apply_live(command)

    # -------------------------------------------------------------- ejecución

    def _execute(self, operation: Callable[[], StopInfo]) -> None:
        cpu = self.machine.cpu
        if cpu.halted is not None:
            self._emit(EvtMessage(f"{cpu.halted.message}. Usá Reset para volver a empezar."))
            return
        self._emit(EvtCpuRunning())
        self._report(operation())
        debugger = self.machine.debugger
        current = {w.expression for w in debugger.watchpoints}
        # Watchpoints eliminados al salir de alcance o pasadas de breakpoints condicionales.
        if current != self._known_watches or debugger.conditions:
            self._emit_breakpoints()

    def _report(self, stop: StopInfo, reason: str | None = None) -> None:
        if stop.reason is StopReason.TRAP:
            self._emit(EvtTrap(stop.message, stop.fault_address))
        elif stop.reason is StopReason.EXITED:
            self._emit(EvtProgramExited(stop.exit_code if stop.exit_code is not None else 0))
        if reason is None:
            reason = stop.message or (
                "breakpoint" if self.machine.debugger.is_breakpoint() else "step"
            )
        self._suspended(reason)

    def _suspended(self, reason: str) -> None:
        self._emit(snapshot(self.machine, reason))


def snapshot(machine: Machine, reason: str = "") -> EvtCpuSuspended:
    cpu = machine.cpu
    pc = cpu.pc
    location = machine.debugger.location(pc)
    frames = machine.debugger.backtrace()
    return EvtCpuSuspended(
        pc=pc,
        source_file=location.file if location else None,
        source_line=location.line if location else None,
        registers=cpu.registers(),
        cycle_count=cpu.clock.cycles,
        reason=reason,
        function=machine.debugger.function(pc),
        stack=cpu.stack_words(),
        frames=frame_infos(machine, frames),
        locals=machine.debugger.locals_of(frames[0] if frames else None),
        global_vars=machine.debugger.global_variables(),
    )


def frame_infos(machine: Machine, frames: list[Frame]) -> tuple[FrameInfo, ...]:
    infos = []
    for frame in frames:
        if frame.irq_line is not None:
            label = f"interrupción IRQ {frame.irq_line}"
        else:
            label = frame.function or machine.image.describe(frame.site)
        location = frame.location
        infos.append(
            FrameInfo(
                frame.index,
                frame.pc,
                label,
                location.file if location else None,
                location.line if location else None,
                frame.irq_line,
            )
        )
    return tuple(infos)
