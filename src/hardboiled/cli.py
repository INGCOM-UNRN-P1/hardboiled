"""Línea de comandos: `hardboiled run | info | validate`."""

from __future__ import annotations

import argparse
import os
import queue
import sys
import tomllib
from pathlib import Path

from pydantic import ValidationError

from hardboiled import __version__
from hardboiled.config import BoardConfig, load_board
from hardboiled.core.cpu import StopReason
from hardboiled.core.dwarf import LineTable
from hardboiled.core.elf import ElfImage, ElfLoadError
from hardboiled.core.events import Command, Event, EvtUartOutput
from hardboiled.core.machine import Machine

EXIT_USAGE = 2
EXIT_TRAP = 3
EXIT_INTERRUPTED = 130


class CliError(Exception):
    pass


def _board_from(path: str | None) -> BoardConfig:
    """Usa la placa indicada, o `./board.toml` si existe, o la placa por defecto."""
    candidate = Path(path) if path else Path("board.toml")
    if path is None and not candidate.exists():
        return BoardConfig()
    try:
        return load_board(candidate)
    except FileNotFoundError as exc:
        raise CliError(f"no existe el archivo de placa {candidate}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CliError(f"{candidate}: TOML inválido: {exc}") from exc
    except ValidationError as exc:
        raise CliError(f"{candidate}: configuración inválida\n{_format_errors(exc)}") from exc


def _format_errors(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"]) or "(raíz)"
        lines.append(f"  - {where}: {error['msg']}")
    return "\n".join(lines)


def _load_machine(elf: str, board: BoardConfig) -> Machine:
    try:
        return Machine.from_elf(elf, board)
    except ElfLoadError as exc:
        raise CliError(str(exc)) from exc
    except FileNotFoundError as exc:
        raise CliError(f"no existe {elf}") from exc


# --------------------------------------------------------------------- run


def cmd_run(args: argparse.Namespace) -> int:
    board = _board_from(args.board)
    if args.max_instructions is not None:
        board = board.model_copy(
            update={
                "board": board.board.model_copy(update={"max_instructions": args.max_instructions})
            }
        )
    machine = _load_machine(args.elf, board)
    if args.switches is not None:
        switches = machine.switches()
        if switches is None:
            raise CliError("la placa no tiene switches")
        switches.set_value(args.switches)
    if args.headless:
        return _run_headless(machine)

    from hardboiled.core.runner import RunnerThread
    from hardboiled.ui.tui import HardboiledApp

    cmd_queue: queue.Queue[Command] = queue.Queue()
    evt_queue: queue.Queue[Event] = queue.Queue()
    runner = RunnerThread(machine, cmd_queue, evt_queue, stop_at_main=not args.no_stop_at_main)
    HardboiledApp(cmd_queue, evt_queue, runner).run()
    return 0


def _run_headless(machine: Machine) -> int:
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


# -------------------------------------------------------------------- info


def cmd_info(args: argparse.Namespace) -> int:
    board = _board_from(args.board)
    try:
        image = ElfImage.load(args.elf)
    except ElfLoadError as exc:
        raise CliError(str(exc)) from exc
    lines = LineTable.from_elf(args.elf)
    mem = board.memory

    print(f"Archivo:        {image.path}")
    print(f"Punto de entrada: 0x{image.entry:08x}")
    main = image.symbol_address("main")
    print(f"main():         {f'0x{main:08x}' if main is not None else 'no definido'}")
    vectors = image.symbol_address("__vector_table")
    print(f"Vectores IRQ:   {f'0x{vectors:08x}' if vectors is not None else 'no definidos'}")

    print("\nSegmentos cargables:")
    flash_used = sram_used = 0
    for seg in image.segments:
        in_flash = mem.flash_base <= seg.paddr < mem.flash_base + mem.flash_size
        runs_in_sram = mem.sram_base <= seg.vaddr < mem.sram_end
        region = "Flash -> SRAM" if in_flash and runs_in_sram else "Flash" if in_flash else "SRAM"
        print(
            f"  {seg.permissions} vaddr=0x{seg.vaddr:08x} paddr=0x{seg.paddr:08x} "
            f"archivo={len(seg.data):>6} B memoria={seg.memsz:>6} B ({region})"
        )
        if seg.data and in_flash:
            flash_used += len(seg.data)
        if runs_in_sram:
            sram_used += seg.memsz
    print(
        f"\nUso: Flash {flash_used} / {mem.flash_size} B, "
        f"SRAM estática {sram_used} / {mem.sram_size} B "
        f"(quedan {mem.sram_size - sram_used} B para heap y pila)"
    )

    functions = sorted(
        (s for s in image.symbols.values() if s.kind == "func" and s.size),
        key=lambda s: s.address,
    )
    print("\nFunciones:")
    for sym in functions:
        print(f"  0x{sym.address:08x} {sym.size:>5} B  {sym.name}")

    print("\nArchivos fuente con información de depuración:")
    if not lines.user_files:
        print("  (ninguno: ¿se compiló con -g?)")
    for file in lines.user_files:
        print(f"  {file}")
    return 0


# ---------------------------------------------------------------- validate


def cmd_validate(args: argparse.Namespace) -> int:
    board = _board_from(args.board)
    mem = board.memory
    print(f"{args.board}: placa '{board.board.name}' válida")
    print(f"  Flash 0x{mem.flash_base:08x} ({mem.flash_size_kb} KB)")
    print(f"  SRAM  0x{mem.sram_base:08x} ({mem.sram_size_kb} KB)")
    print(f"  MMIO  0x{mem.mmio_base:08x} ({mem.mmio_size_kb} KB)")
    for p in board.peripherals:
        irq = f" irq={p.irq_line}" if p.irq_line is not None else ""
        print(f"    +0x{p.offset:03x} {p.name:<10} {p.type:<9} {p.width_bits} bits{irq}")
    print(f"    +0x{board.pic.offset:03x} pic        (controlador de interrupciones)")
    return 0


# -------------------------------------------------------------------- main


def _int(text: str) -> int:
    return int(text.replace("_", ""), 0)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hardboiled",
        description="Emulador pedagógico RV32I bare-metal con depurador de código C.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="ejecuta un ELF en la TUI (o sin interfaz con --headless)")
    run.add_argument("elf", help="binario ELF riscv32 enlazado con el runtime de hardboiled")
    run.add_argument("--board", help="board.toml (por defecto ./board.toml si existe)")
    run.add_argument("--headless", action="store_true", help="ejecutar sin TUI hasta terminar")
    run.add_argument("--switches", type=_int, help="estado inicial de los switches (ej. 0b0101)")
    run.add_argument("--max-instructions", type=_int, help="cuota de instrucciones")
    run.add_argument(
        "--no-stop-at-main", action="store_true", help="no detenerse al inicio de main()"
    )
    run.set_defaults(func=cmd_run)

    info = sub.add_parser("info", help="muestra segmentos, símbolos y fuentes de un ELF")
    info.add_argument("elf")
    info.add_argument("--board")
    info.set_defaults(func=cmd_info)

    validate = sub.add_parser("validate", help="valida un board.toml")
    validate.add_argument("board", nargs="?", default="board.toml")
    validate.set_defaults(func=cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        code: int = args.func(args)
    except CliError as exc:
        print(f"hardboiled: error: {exc}", file=sys.stderr)
        return EXIT_USAGE
    except KeyboardInterrupt:
        print("\nhardboiled: ejecución interrumpida", file=sys.stderr)
        return EXIT_INTERRUPTED
    except BrokenPipeError:
        # La salida se cerró antes de tiempo (p. ej. `| head`): no es un error.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 0
    return code


if __name__ == "__main__":
    sys.exit(main())
