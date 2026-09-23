"""`hardboiled info`: segmentos, uso de memoria, símbolos y fuentes de un ELF."""

from __future__ import annotations

import argparse

from hardboiled.cli.common import CliError, Subparsers, board_from
from hardboiled.core.dwarf import LineTable
from hardboiled.core.elf import ElfImage, ElfLoadError


def register(sub: Subparsers) -> None:
    info = sub.add_parser("info", help="muestra segmentos, símbolos y fuentes de un ELF")
    info.add_argument("elf")
    info.add_argument("--board")
    info.set_defaults(func=cmd_info)


def cmd_info(args: argparse.Namespace) -> int:
    board = board_from(args.board)
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
