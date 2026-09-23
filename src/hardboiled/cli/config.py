"""`hardboiled config`: preferencias del usuario."""

from __future__ import annotations

import argparse

from hardboiled.cli.common import CliError, Subparsers, user_config
from hardboiled.userconfig import TEMPLATE, config_path


def register(sub: Subparsers) -> None:
    parser = sub.add_parser("config", help="muestra o crea las preferencias del usuario")
    parser.set_defaults(func=cmd_show)
    actions = parser.add_subparsers(dest="config_command")
    path = actions.add_parser("path", help="imprime la ruta de config.toml")
    path.set_defaults(func=cmd_path)
    init = actions.add_parser("init", help="crea config.toml con todas las opciones comentadas")
    init.add_argument("--force", action="store_true", help="sobrescribir si ya existe")
    init.set_defaults(func=cmd_init)


def cmd_path(_args: argparse.Namespace) -> int:
    print(config_path())
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    path = config_path()
    if path.exists() and not args.force:
        raise CliError(f"{path} ya existe (usá --force para sobrescribirlo)")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(TEMPLATE, encoding="utf-8")
    print(f"creado {path}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    path = config_path()
    state = "" if path.is_file() else "  (no existe: se usan los valores por defecto)"
    print(f"archivo: {path}{state}\n")
    config = user_config(args)
    for section in ("build", "run", "ui"):
        print(f"[{section}]")
        for key, value in getattr(config, section).model_dump().items():
            print(f"{key} = {value!r}")
        print()
    print("[keys]")
    for action, keys in sorted(config.keys.items()):
        print(f"{action} = {keys!r}")
    return 0
