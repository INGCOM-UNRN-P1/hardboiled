"""Línea de comandos de hardboiled: un módulo por subcomando."""

from __future__ import annotations

import argparse
import os
import sys

from hardboiled import __version__, i18n
from hardboiled.cli import (
    board,
    build,
    completion,
    config,
    doctor,
    examples,
    explain,
    info,
    new,
    run,
    runtime,
    sdk,
    test,
    tutorial,
    validate,
)
from hardboiled.cli.common import EXIT_INTERRUPTED, EXIT_TRAP, EXIT_USAGE, CliError
from hardboiled.userconfig import ConfigError, load_user_config

__all__ = ["EXIT_INTERRUPTED", "EXIT_TRAP", "EXIT_USAGE", "build_parser", "main"]

SUBCOMMANDS = (
    new,
    build,
    run,
    test,
    tutorial,
    examples,
    info,
    validate,
    board,
    runtime,
    sdk,
    config,
    doctor,
    explain,
    completion,
)


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


def utf8_output() -> None:
    """Salida en UTF-8 aunque el sistema diga otra cosa.

    En Windows, fuera de una consola (redirigida a un archivo o a un pipe, como
    en CI), Python usa la página de códigos del sistema (cp1252), que no tiene
    `✔`, `⏎` ni los caracteres de caja: imprimirlos abortaba con
    UnicodeEncodeError. La consola de Windows ya usa UTF-8 y no se toca.
    """
    for stream in (sys.stdout, sys.stderr):
        encoding = (getattr(stream, "encoding", None) or "").lower().replace("-", "")
        reconfigure = getattr(stream, "reconfigure", None)
        if encoding != "utf8" and reconfigure is not None:
            reconfigure(encoding="utf-8", errors="replace")


def main(argv: list[str] | None = None) -> int:
    utf8_output()
    args = build_parser().parse_args(argv)
    try:
        try:
            args.user_config = load_user_config()
            i18n.configure(args.user_config.ui.language)
        except ConfigError as exc:
            raise CliError(f"{exc}\n(corregilo o revisalo con `hardboiled config`)") from exc
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
