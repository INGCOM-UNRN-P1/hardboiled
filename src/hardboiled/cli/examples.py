"""`hardboiled examples` y `hardboiled demo`: ejemplos que vienen con el paquete."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from hardboiled import resources
from hardboiled.cli.common import CliError, Subparsers
from hardboiled.cli.run import add_run_options, cmd_run


def register(sub: Subparsers) -> None:
    examples = sub.add_parser("examples", help="lista, muestra o copia los ejemplos incluidos")
    examples.set_defaults(func=cmd_list)
    actions = examples.add_subparsers(dest="examples_command")

    show = actions.add_parser("show", help="imprime el código de un ejemplo")
    show.add_argument("name")
    show.set_defaults(func=cmd_show)

    copy = actions.add_parser("copy", help="copia ejemplos al directorio actual (o a --dest)")
    copy.add_argument("names", nargs="*", help="ejemplos a copiar (todos si se omite)")
    copy.add_argument("--dest", default=".", help="directorio destino")
    copy.add_argument("--force", action="store_true", help="sobrescribir archivos existentes")
    copy.set_defaults(func=cmd_copy)

    demo = sub.add_parser("demo", help="compila y ejecuta un ejemplo (por defecto, la demo)")
    demo.add_argument("name", nargs="?", default="demo", help="nombre del ejemplo")
    add_run_options(demo)
    demo.set_defaults(func=cmd_demo)


def _example(name: str) -> Path:
    path = resources.example_path(name)
    if not path.is_file():
        available = ", ".join(resources.example_names())
        raise CliError(f"no existe el ejemplo {name!r}; disponibles: {available}")
    return path


def cmd_list(_args: argparse.Namespace) -> int:
    names = resources.example_names()
    width = max(len(name) for name in names)
    print("Ejemplos incluidos:")
    for name in names:
        print(f"  {name:<{width}}  {resources.example_summary(name)}")
    print("\nhardboiled demo NOMBRE        compila y ejecuta un ejemplo")
    print("hardboiled examples copy      copia los fuentes para modificarlos")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    print(_example(args.name).read_text(encoding="utf-8"), end="")
    return 0


def cmd_copy(args: argparse.Namespace) -> int:
    names = args.names or resources.example_names()
    sources = [_example(name) for name in names]
    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    existing = [dest / s.name for s in sources if (dest / s.name).exists()]
    if existing and not args.force:
        listed = ", ".join(str(p) for p in existing)
        raise CliError(f"ya existen {listed} (usá --force para sobrescribir)")
    for source in sources:
        shutil.copyfile(source, dest / source.name)
        print(f"copiado {dest / source.name}")
    return 0


def cmd_demo(args: argparse.Namespace) -> int:
    args.program = [str(_example(args.name))]
    args.no_save_breakpoints = True  # los ejemplos instalados pueden ser de sólo lectura
    return cmd_run(args)
