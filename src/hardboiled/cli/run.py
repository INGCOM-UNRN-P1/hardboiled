"""`hardboiled run`: TUI o ejecución sin interfaz."""

from __future__ import annotations

import argparse
import queue
import sys

from hardboiled.cli.common import (
    EXIT_TRAP,
    CliError,
    Subparsers,
    board_from,
    load_machine,
    parse_int,
)
from hardboiled.core.cpu import StopReason
from hardboiled.core.events import Command, Event, EvtUartOutput
from hardboiled.core.machine import Machine


def register(sub: Subparsers) -> None:
    run = sub.add_parser("run", help="ejecuta un ELF en la TUI (o sin interfaz con --headless)")
    run.add_argument("elf", help="binario ELF riscv32 enlazado con el runtime de hardboiled")
    run.add_argument("--board", help="board.toml (por defecto ./board.toml si existe)")
    run.add_argument("--headless", action="store_true", help="ejecutar sin TUI hasta terminar")
    run.add_argument("--switches", type=parse_int, help="estado inicial de los switches (0b0101)")
    run.add_argument("--max-instructions", type=parse_int, help="cuota de instrucciones")
    run.add_argument(
        "--no-stop-at-main", action="store_true", help="no detenerse al inicio de main()"
    )
    run.set_defaults(func=cmd_run)


def cmd_run(args: argparse.Namespace) -> int:
    board = board_from(args.board)
    if args.max_instructions is not None:
        board = board.model_copy(
            update={
                "board": board.board.model_copy(update={"max_instructions": args.max_instructions})
            }
        )
    machine = load_machine(args.elf, board)
    if args.switches is not None:
        switches = machine.switches()
        if switches is None:
            raise CliError("la placa no tiene switches")
        switches.set_value(args.switches)
    if args.headless:
        return run_headless(machine)

    from hardboiled.core.runner import RunnerThread
    from hardboiled.ui.tui import HardboiledApp

    cmd_queue: queue.Queue[Command] = queue.Queue()
    evt_queue: queue.Queue[Event] = queue.Queue()
    runner = RunnerThread(machine, cmd_queue, evt_queue, stop_at_main=not args.no_stop_at_main)
    HardboiledApp(cmd_queue, evt_queue, runner).run()
    return 0


def run_headless(machine: Machine) -> int:
    """Ejecuta sin TUI hasta terminar: la UART va a stdout, las trampas a stderr."""
    out = sys.stdout.buffer  # la UART transmite bytes: se reenvían sin reinterpretarlos

    def sink(event: Event) -> None:
        if isinstance(event, EvtUartOutput):
            out.write(bytes([event.char_code]))
            out.flush()

    machine.set_event_sink(sink)
    stop = machine.debugger.continue_()
    if stop.reason is StopReason.EXITED:
        return (stop.exit_code or 0) & 0xFF
    location = machine.debugger.location(stop.pc)
    where = f"{location.file}:{location.line}" if location else "sin información de línea"
    function = machine.debugger.function(stop.pc) or "??"
    print(
        f"\nTRAP: {stop.message}\n  en {function}() pc=0x{stop.pc:08x} ({where})",
        file=sys.stderr,
    )
    return EXIT_TRAP
