"""`hardboiled runtime`: rutas del runtime para Makefiles propios o gcc a mano."""

from __future__ import annotations

import argparse

from hardboiled import resources
from hardboiled.cli.common import Subparsers


def register(sub: Subparsers) -> None:
    parser = sub.add_parser(
        "runtime",
        help="imprime las rutas del runtime (include, linker script, crt0)",
        description="Sin opciones imprime las tres rutas; con una opción, sólo esa "
        "(para usar como $(hardboiled runtime --include) en un Makefile).",
    )
    which = parser.add_mutually_exclusive_group()
    which.add_argument("--include", action="store_true", help="directorio de hardboiled.h")
    which.add_argument("--linker-script", action="store_true", help="hardboiled.ld")
    which.add_argument("--crt0", action="store_true", help="crt0.s")
    which.add_argument("--dir", action="store_true", help="directorio del runtime")
    parser.set_defaults(func=cmd_runtime)


def cmd_runtime(args: argparse.Namespace) -> int:
    if args.include:
        print(resources.include_dir())
    elif args.linker_script:
        print(resources.linker_script())
    elif args.crt0:
        print(resources.crt0_path())
    elif args.dir:
        print(resources.runtime_dir())
    else:
        print(f"include        {resources.include_dir()}")
        print(f"linker-script  {resources.linker_script()}")
        print(f"crt0           {resources.crt0_path()}")
    return 0
