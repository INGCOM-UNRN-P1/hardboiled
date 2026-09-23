"""`hardboiled gen-header`: SDK y linker script a partir de un board.toml."""

from __future__ import annotations

import argparse
from pathlib import Path

from hardboiled.cli.common import Subparsers, board_path, load_board_file
from hardboiled.sdk import generate_header, generate_linker_script


def register(sub: Subparsers) -> None:
    parser = sub.add_parser(
        "gen-header",
        help="genera hardboiled.h (o el linker script) para una placa",
        description="Genera el SDK para los offsets de board.toml. `build` y `run` lo hacen "
        "solos cuando el proyecto tiene un board.toml propio.",
    )
    parser.add_argument("board", nargs="?", help="board.toml (por defecto ./board.toml)")
    parser.add_argument(
        "-o", "--output", help="archivo de salida (por defecto, la salida estándar)"
    )
    parser.add_argument(
        "--linker-script", action="store_true", help="generar hardboiled.ld en lugar del header"
    )
    parser.set_defaults(func=cmd_gen_header)


def cmd_gen_header(args: argparse.Namespace) -> int:
    board = load_board_file(board_path(args.board))
    text = generate_linker_script(board) if args.linker_script else generate_header(board)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"generado {args.output}")
    else:
        print(text, end="")
    return 0
