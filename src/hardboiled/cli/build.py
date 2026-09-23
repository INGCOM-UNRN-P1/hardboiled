"""`hardboiled build`: compila programas C con el runtime y los flags de la placa."""

from __future__ import annotations

import argparse
import os
import shlex
import sys
from pathlib import Path

from hardboiled.cli.common import CliError, Subparsers, user_config
from hardboiled.toolchain import BuildError, BuildOptions, ToolchainError, build, select_compiler


def add_build_options(parser: argparse.ArgumentParser) -> None:
    """Opciones de compilación compartidas por `build` y por `run archivo.c`."""
    group = parser.add_argument_group("compilación")
    group.add_argument("-O", dest="opt_level", help="nivel de optimización (0)")
    group.add_argument("--march", help="rv32i, rv32im, rv32ic o rv32imc")
    group.add_argument("--cc", help="compilador: auto, gcc, zig o una ruta (HARDBOILED_CC)")
    group.add_argument("-D", dest="defines", action="append", default=[], help="macro")
    group.add_argument("-I", dest="include_dirs", action="append", default=[], help="includes")
    group.add_argument("--cflags", default="", help='flags extra, p. ej. --cflags="-std=c99"')


def options_from(args: argparse.Namespace) -> BuildOptions:
    prefs = user_config(args).build
    return BuildOptions(
        opt_level=args.opt_level or prefs.opt_level,
        march=args.march or prefs.march,
        defines=tuple(args.defines),
        include_dirs=tuple(Path(d) for d in args.include_dirs),
        extra_flags=tuple(shlex.split(args.cflags)),
    )


def compiler_preference(args: argparse.Namespace) -> str | None:
    """--cc, luego HARDBOILED_CC, luego la preferencia del usuario (o auto)."""
    return args.cc or os.environ.get("HARDBOILED_CC") or user_config(args).build.compiler


def register(sub: Subparsers) -> None:
    parser = sub.add_parser("build", help="compila fuentes C a un ELF para la placa")
    parser.add_argument("sources", nargs="+", help="archivos .c (y .s) del programa")
    parser.add_argument("-o", "--output", help="ELF de salida (por defecto, el del 1.er fuente)")
    parser.add_argument("-v", "--verbose", action="store_true", help="mostrar el comando")
    add_build_options(parser)
    parser.set_defaults(func=cmd_build)


def compile_sources(
    sources: list[str], output: Path | None, args: argparse.Namespace, verbose: bool
) -> Path:
    try:
        compiler = select_compiler(compiler_preference(args))
        result = build(sources, output, options_from(args), compiler)
    except BuildError as exc:
        if verbose:
            print(shlex.join(exc.command), file=sys.stderr)
        raise CliError(f"{exc}\n{exc.output}") from exc
    except ToolchainError as exc:
        raise CliError(str(exc)) from exc
    if verbose:
        print(shlex.join(result.command), file=sys.stderr)
    if result.diagnostics:
        print(result.diagnostics, file=sys.stderr)
    return result.output


def cmd_build(args: argparse.Namespace) -> int:
    output = Path(args.output) if args.output else None
    elf = compile_sources(args.sources, output, args, args.verbose)
    print(f"compilado {elf}")
    return 0
