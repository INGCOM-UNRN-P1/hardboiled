"""`hardboiled validate`: valida un board.toml y muestra su mapa."""

from __future__ import annotations

import argparse

from hardboiled.cli.common import Subparsers, board_from


def register(sub: Subparsers) -> None:
    validate = sub.add_parser("validate", help="valida un board.toml")
    validate.add_argument("board", nargs="?", default="board.toml")
    validate.set_defaults(func=cmd_validate)


def cmd_validate(args: argparse.Namespace) -> int:
    board = board_from(args.board)
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
