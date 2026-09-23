"""Carga de binarios ELF RV32: segmentos cargables y tabla de símbolos."""

from __future__ import annotations

import bisect
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from elftools.common.exceptions import ELFError
from elftools.elf.elffile import ELFFile
from elftools.elf.sections import SymbolTableSection

PF_X = 0x1
PF_W = 0x2
PF_R = 0x4
EF_RISCV_RVC = 0x1


class ElfLoadError(Exception):
    pass


@dataclass(frozen=True)
class Segment:
    vaddr: int
    paddr: int
    data: bytes
    memsz: int
    flags: int

    @property
    def executable(self) -> bool:
        return bool(self.flags & PF_X)

    @property
    def permissions(self) -> str:
        return "".join(
            char if self.flags & bit else "-"
            for char, bit in (("R", PF_R), ("W", PF_W), ("X", PF_X))
        )


@dataclass(frozen=True)
class Symbol:
    name: str
    address: int
    size: int
    kind: str  # "func" | "object" | "other"


class ElfImage:
    def __init__(
        self, path: Path, entry: int, segments: list[Segment], symbols: list[Symbol]
    ) -> None:
        self.path = path
        self.entry = entry
        self.segments = segments
        self.symbols = {sym.name: sym for sym in symbols}
        self._functions = sorted(
            (s for s in symbols if s.kind == "func" and s.size > 0), key=lambda s: s.address
        )
        self._function_starts = [s.address for s in self._functions]

    @classmethod
    def load(cls, path: str | Path) -> ElfImage:
        path = Path(path)
        try:
            with path.open("rb") as stream:
                elf = ELFFile(stream)
                if elf["e_machine"] != "EM_RISCV" or elf.elfclass != 32:
                    raise ElfLoadError(
                        f"{path.name} no es un ELF RISC-V de 32 bits "
                        f"(máquina {elf['e_machine']}, clase {elf.elfclass})"
                    )
                if elf["e_flags"] & EF_RISCV_RVC:
                    raise ElfLoadError(
                        f"{path.name} usa instrucciones comprimidas (extensión C); "
                        "compilá con -march=rv32i -mabi=ilp32"
                    )
                segments = [
                    Segment(
                        vaddr=seg["p_vaddr"],
                        paddr=seg["p_paddr"],
                        data=seg.data(),
                        memsz=seg["p_memsz"],
                        flags=seg["p_flags"],
                    )
                    for seg in elf.iter_segments()
                    if seg["p_type"] == "PT_LOAD"
                ]
                symbols: list[Symbol] = []
                symtab = elf.get_section_by_name(".symtab")
                if isinstance(symtab, SymbolTableSection):
                    for sym in symtab.iter_symbols():
                        if not sym.name:
                            continue
                        sym_type = sym["st_info"]["type"]
                        kind = {"STT_FUNC": "func", "STT_OBJECT": "object"}.get(sym_type, "other")
                        symbols.append(Symbol(sym.name, sym["st_value"], sym["st_size"], kind))
                entry = elf["e_entry"]
        except (OSError, ELFError) as exc:
            raise ElfLoadError(f"no se pudo leer {path}: {exc}") from exc
        if not segments:
            raise ElfLoadError(f"{path.name} no tiene segmentos PT_LOAD")
        return cls(path, entry, segments, symbols)

    def symbol_address(self, name: str) -> int | None:
        sym = self.symbols.get(name)
        return sym.address if sym is not None else None

    def function_at(self, address: int) -> str | None:
        idx = bisect.bisect_right(self._function_starts, address) - 1
        if idx < 0:
            return None
        func = self._functions[idx]
        return func.name if address < func.address + func.size else None

    def code_words(self) -> Iterator[tuple[int, int]]:
        """Palabras de 32 bits alineadas de los segmentos ejecutables (dirección de ejecución)."""
        for seg in self.segments:
            if not seg.executable:
                continue
            data = seg.data
            for offset in range(0, len(data) - 3, 4):
                yield seg.vaddr + offset, int.from_bytes(data[offset : offset + 4], "little")
