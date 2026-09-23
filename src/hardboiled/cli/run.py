"""`hardboiled run`: TUI o ejecución sin interfaz."""

from __future__ import annotations

import argparse
import queue
import sys
from pathlib import Path

from hardboiled.buildcache import SOURCE_SUFFIXES, build_cached
from hardboiled.cli.build import add_build_options, compiler_preference, options_from
from hardboiled.cli.common import (
    EXIT_TRAP,
    CliError,
    Subparsers,
    board_from,
    load_machine,
    parse_int,
    user_config,
)
from hardboiled.core.cpu import StopReason
from hardboiled.core.events import Command, Event, EvtUartOutput
from hardboiled.core.machine import Machine
from hardboiled.toolchain import BuildError, ToolchainError, select_compiler


def register(sub: Subparsers) -> None:
    run = sub.add_parser("run", help="ejecuta un ELF en la TUI (o sin interfaz con --headless)")
    run.add_argument(
        "program",
        nargs="+",
        help="un ELF, o fuentes .c/.s que se compilan (con caché) antes de ejecutar",
    )
    add_run_options(run)
    run.set_defaults(func=cmd_run)


def add_run_options(parser: argparse.ArgumentParser) -> None:
    """Opciones de ejecución compartidas por `run` y `demo`."""
    parser.add_argument("--board", help="board.toml (por defecto ./board.toml si existe)")
    parser.add_argument("--headless", action="store_true", help="ejecutar sin TUI hasta terminar")
    parser.add_argument(
        "--switches", type=parse_int, help="estado inicial de los switches (0b0101)"
    )
    parser.add_argument("--max-instructions", type=parse_int, help="cuota de instrucciones")
    parser.add_argument(
        "--no-stop-at-main", action="store_true", help="no detenerse al inicio de main()"
    )
    parser.add_argument(
        "--realtime",
        action="store_true",
        help="con --headless, respetar clock_hz de la placa (por defecto corre sin pausas)",
    )
    add_build_options(parser)


def resolve_program(args: argparse.Namespace) -> Path:
    """Devuelve el ELF a ejecutar, compilando los fuentes si hace falta."""
    programs = [Path(p) for p in args.program]
    suffixes = {p.suffix.lower() for p in programs}
    if suffixes == {".elf"}:
        if len(programs) > 1:
            raise CliError("se puede ejecutar un único ELF por vez")
        return programs[0]
    if ".elf" in suffixes:
        raise CliError("no se pueden mezclar un ELF y archivos fuente")
    unknown = sorted(suffixes - set(SOURCE_SUFFIXES))
    if unknown:
        raise CliError(f"tipo de archivo no reconocido: {', '.join(unknown)} (se espera .elf o .c)")
    for program in programs:
        if not program.is_file():
            raise CliError(f"no existe {program}")
    try:
        compiler = select_compiler(compiler_preference(args))
        result = build_cached(programs, options_from(args), compiler)
    except BuildError as exc:
        raise CliError(f"{exc}\n{exc.output}") from exc
    except ToolchainError as exc:
        raise CliError(str(exc)) from exc
    if result.diagnostics:
        print(result.diagnostics, file=sys.stderr)
    if not result.reused:
        print(f"compilado con {compiler.description}", file=sys.stderr)
    return result.elf


def cmd_run(args: argparse.Namespace) -> int:
    board = board_from(args.board)
    if args.max_instructions is not None:
        board = board.model_copy(
            update={
                "board": board.board.model_copy(update={"max_instructions": args.max_instructions})
            }
        )
    prefs = user_config(args).run
    if prefs.clock_hz is not None and not args.headless:
        board = board.model_copy(
            update={"board": board.board.model_copy(update={"clock_hz": prefs.clock_hz})}
        )
    if args.headless and not args.realtime and board.board.clock_hz is not None:
        # Sin interfaz nadie mira los LEDs: acompasar al reloj real sólo haría esperar.
        board = board.model_copy(
            update={"board": board.board.model_copy(update={"clock_hz": None})}
        )
    machine = load_machine(resolve_program(args), board)
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
    stop_at_main = prefs.stop_at_main and not args.no_stop_at_main
    runner = RunnerThread(machine, cmd_queue, evt_queue, stop_at_main=stop_at_main)
    HardboiledApp(cmd_queue, evt_queue, runner, user_config(args).ui).run()
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
