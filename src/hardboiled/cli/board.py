"""`hardboiled board`: plantillas de placa."""

from __future__ import annotations

import argparse
import shutil
from pathlib import Path

from hardboiled.cli.common import CliError, Subparsers
from hardboiled.resources import default_board_path


def register(sub: Subparsers) -> None:
    board = sub.add_parser("board", help="crea o muestra placas (board.toml)")
    actions = board.add_subparsers(dest="board_command", required=True)

    init = actions.add_parser("init", help="copia la placa por defecto para editarla")
    init.add_argument("path", nargs="?", default="board.toml", help="destino (./board.toml)")
    init.add_argument("--force", action="store_true", help="sobrescribir si ya existe")
    init.set_defaults(func=cmd_init)

    show = actions.add_parser("show", help="imprime la placa por defecto")
    show.set_defaults(func=cmd_show)


def cmd_init(args: argparse.Namespace) -> int:
    target = Path(args.path)
    if target.exists() and not args.force:
        raise CliError(f"{target} ya existe (usá --force para sobrescribirlo)")
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(default_board_path(), target)
    print(f"placa por defecto copiada en {target}")
    print(f"validala después de editarla con: hardboiled validate {target}")
    return 0


def cmd_show(_args: argparse.Namespace) -> int:
    print(default_board_path().read_text(encoding="utf-8"), end="")
    return 0
