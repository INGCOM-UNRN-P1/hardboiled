"""Línea de comandos de hardboiled: un módulo por subcomando."""

from __future__ import annotations

import argparse
import os
import sys

from hardboiled import __version__
from hardboiled.cli import board, build, examples, info, run, validate
from hardboiled.cli.common import EXIT_INTERRUPTED, EXIT_TRAP, EXIT_USAGE, CliError

__all__ = ["EXIT_INTERRUPTED", "EXIT_TRAP", "EXIT_USAGE", "build_parser", "main"]

SUBCOMMANDS = (build, run, examples, info, validate, board)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="hardboiled",
        description="Emulador pedagógico RV32I bare-metal con depurador de código C.",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)
    for module in SUBCOMMANDS:
        module.register(sub)
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
