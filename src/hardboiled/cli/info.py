"""`hardboiled info`: segmentos, uso de memoria, símbolos y fuentes de un ELF."""

from __future__ import annotations

import argparse
from typing import Any

from hardboiled.cli.common import CliError, Subparsers, board_from, print_json
from hardboiled.config import BoardConfig
from hardboiled.core.buildinfo import analyze
from hardboiled.core.dwarf import LineTable
from hardboiled.core.elf import ElfImage, ElfLoadError


def register(sub: Subparsers) -> None:
    info = sub.add_parser("info", help="muestra segmentos, símbolos y fuentes de un ELF")
    info.add_argument("elf")
    info.add_argument("--board")
    info.add_argument("--json", action="store_true", help="la misma información en JSON")
    info.set_defaults(func=cmd_info)


def collect(path: str, board: BoardConfig) -> dict[str, Any]:
    """Toda la información del ELF, lista para mostrar o serializar."""
    try:
        image = ElfImage.load(path)
    except ElfLoadError as exc:
        raise CliError(str(exc)) from exc
    lines = LineTable.from_elf(path)
    mem = board.memory
    segments = []
    flash_used = sram_used = 0
    for seg in image.segments:
        in_flash = mem.flash_base <= seg.paddr < mem.flash_base + mem.flash_size
        runs_in_sram = mem.sram_base <= seg.vaddr < mem.sram_end
        region = "Flash -> SRAM" if in_flash and runs_in_sram else "Flash" if in_flash else "SRAM"
        segments.append(
            {
                "permissions": seg.permissions,
                "vaddr": seg.vaddr,
                "paddr": seg.paddr,
                "file_size": len(seg.data),
                "mem_size": seg.memsz,
                "region": region,
            }
        )
        if seg.data and in_flash:
            flash_used += len(seg.data)
        if runs_in_sram:
            sram_used += seg.memsz
    functions = sorted(
        (s for s in image.symbols.values() if s.kind == "func" and s.size),
        key=lambda s: s.address,
    )
    report = analyze(path)
    return {
        "path": str(image.path),
        "entry": image.entry,
        "main": image.symbol_address("main"),
        "vector_table": image.symbol_address("__vector_table"),
        "arch": image.arch,
        "segments": segments,
        "usage": {
            "flash_used": flash_used,
            "flash_size": mem.flash_size,
            "sram_static": sram_used,
            "sram_size": mem.sram_size,
        },
        "functions": [{"name": s.name, "address": s.address, "size": s.size} for s in functions],
        "build": {
            "producers": sorted(set(report.producers)),
            "has_debug": report.has_debug,
            "optimized": report.optimized,
            "warnings": report.warnings(),
        },
        "sources": list(lines.user_files),
    }


def _hex(value: int | None, missing: str) -> str:
    return f"0x{value:08x}" if value is not None else missing


def cmd_info(args: argparse.Namespace) -> int:
    data = collect(args.elf, board_from(args.board))
    if args.json:
        print_json(data)
        return 0
    print(f"Archivo:        {data['path']}")
    print(f"Punto de entrada: 0x{data['entry']:08x}")
    print(f"main():         {_hex(data['main'], 'no definido')}")
    print(f"Vectores IRQ:   {_hex(data['vector_table'], 'no definidos')}")

    print("\nSegmentos cargables:")
    for seg in data["segments"]:
        print(
            f"  {seg['permissions']} vaddr=0x{seg['vaddr']:08x} paddr=0x{seg['paddr']:08x} "
            f"archivo={seg['file_size']:>6} B memoria={seg['mem_size']:>6} B ({seg['region']})"
        )
    usage = data["usage"]
    print(
        f"\nUso: Flash {usage['flash_used']} / {usage['flash_size']} B, "
        f"SRAM estática {usage['sram_static']} / {usage['sram_size']} B "
        f"(quedan {usage['sram_size'] - usage['sram_static']} B para heap y pila)"
    )

    print("\nFunciones:")
    for sym in data["functions"]:
        print(f"  0x{sym['address']:08x} {sym['size']:>5} B  {sym['name']}")

    build = data["build"]
    print("\nCompilación:")
    for producer in build["producers"]:
        print(f"  compilador: {producer}")
    if build["has_debug"] and not build["optimized"]:
        print("  apto para depurar: con información de depuración y sin optimización")
    for message in build["warnings"]:
        print(f"  aviso: {message}")

    print("\nArchivos fuente con información de depuración:")
    if not data["sources"]:
        print("  (ninguno: ¿se compiló con -g?)")
    for file in data["sources"]:
        print(f"  {file}")
    return 0
