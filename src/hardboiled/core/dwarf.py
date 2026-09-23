"""Mapeo simbólico PC <-> (archivo.c, línea) a partir de `.debug_line` (DWARF v4/v5)."""

from __future__ import annotations

import bisect
import os
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from elftools.elf.elffile import ELFFile

USER_SOURCE_SUFFIXES = frozenset({".c", ".h", ".s", ".S", ".inc"})


@dataclass(frozen=True, order=True)
class SourceLocation:
    file: str
    line: int


@dataclass(frozen=True)
class _Range:
    start: int
    end: int
    file: str
    line: int
    is_stmt: bool


def _text(value: Any) -> str:
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return str(value)


class LineTable:
    """Tabla de líneas indexada por dirección.

    Sólo se consideran "de usuario" las ubicaciones cuyo archivo fuente es C o
    ensamblador y existe en disco: así los pasos no se detienen dentro de
    bibliotecas de runtime (compiler-rt, libgcc) sin fuente disponible.
    """

    def __init__(self, ranges: Iterable[_Range]) -> None:
        self._ranges = sorted(ranges, key=lambda r: r.start)
        self._starts = [r.start for r in self._ranges]
        files = sorted({r.file for r in self._ranges})
        self._available = {
            f for f in files if Path(f).suffix in USER_SOURCE_SUFFIXES and os.path.isfile(f)
        }
        self.files = tuple(files)
        self.user_files = tuple(f for f in files if f in self._available)
        self._cache: dict[int, SourceLocation | None] = {}

    @classmethod
    def empty(cls) -> LineTable:
        return cls([])

    @classmethod
    def from_elf(cls, path: str | Path) -> LineTable:
        path = Path(path)
        with path.open("rb") as stream:
            elf = ELFFile(stream)
            if not elf.has_dwarf_info():
                return cls.empty()
            dwarf = elf.get_dwarf_info()
            # El linker deja en dirección 0 (tombstone) las líneas de funciones
            # descartadas por --gc-sections: sólo valen las que caen en código cargado.
            code = [
                (seg["p_vaddr"], seg["p_vaddr"] + seg["p_memsz"])
                for seg in elf.iter_segments()
                if seg["p_type"] == "PT_LOAD" and seg["p_flags"] & 0x1
            ]
            ranges: list[_Range] = []
            for cu in dwarf.iter_CUs():
                program = dwarf.line_program_for_CU(cu)
                if program is None:
                    continue
                top = cu.get_top_DIE()
                comp_dir_attr = top.attributes.get("DW_AT_comp_dir")
                comp_dir = _text(comp_dir_attr.value) if comp_dir_attr else ""
                base = path.parent / comp_dir if not os.path.isabs(comp_dir) else Path(comp_dir)
                ranges.extend(
                    r
                    for r in _ranges_for_program(program, base)
                    if any(lo <= r.start and r.end <= hi for lo, hi in code)
                )
        return cls(ranges)

    def has_source(self, file: str) -> bool:
        return file in self._available

    def lookup(self, address: int) -> SourceLocation | None:
        """Ubicación de usuario (con fuente disponible) que contiene `address`."""
        try:
            return self._cache[address]
        except KeyError:
            pass
        location = None
        idx = bisect.bisect_right(self._starts, address) - 1
        # Puede haber rangos superpuestos de secuencias distintas: se busca hacia atrás
        # el más cercano que efectivamente contenga la dirección.
        while idx >= 0 and self._ranges[idx].start > address - 0x10000:
            rng = self._ranges[idx]
            if rng.start <= address < rng.end:
                if rng.file in self._available:
                    location = SourceLocation(rng.file, rng.line)
                break
            idx -= 1
        self._cache[address] = location
        return location

    def resolve_file(self, name: str) -> str | None:
        """Busca un archivo de la tabla por ruta completa o por nombre base."""
        normalized = os.path.normpath(os.path.abspath(name))
        if normalized in self.files:
            return normalized
        matches = [f for f in self.files if os.path.basename(f) == os.path.basename(name)]
        return matches[0] if len(matches) == 1 else None

    def address_for_line(self, file: str, line: int) -> tuple[int, int] | None:
        """Primera dirección de la línea `line` (o de la siguiente línea con código).

        Devuelve `(línea_efectiva, dirección)`.
        """
        candidates: dict[int, int] = {}
        for rng in self._ranges:
            if rng.file == file and rng.is_stmt and rng.line >= line:
                previous = candidates.get(rng.line)
                if previous is None or rng.start < previous:
                    candidates[rng.line] = rng.start
        if not candidates:
            return None
        effective = min(candidates)
        return effective, candidates[effective]

    def lines_with_code(self, file: str) -> frozenset[int]:
        return frozenset(r.line for r in self._ranges if r.file == file and r.is_stmt)


def _ranges_for_program(program: Any, base: Path) -> list[_Range]:
    header = program.header
    version = header["version"]
    include_dirs = [_text(d) for d in header["include_directory"]]
    file_entries = header["file_entry"]

    def file_path(index: int) -> str:
        # DWARF v5 indexa archivos y directorios desde 0; v2-v4, desde 1.
        entry_index = index if version >= 5 else index - 1
        if not 0 <= entry_index < len(file_entries):
            return f"<archivo {index}>"
        entry = file_entries[entry_index]
        name = _text(entry.name)
        dir_index = entry.dir_index
        if version >= 5:
            directory = include_dirs[dir_index] if dir_index < len(include_dirs) else ""
        else:
            directory = include_dirs[dir_index - 1] if 0 < dir_index <= len(include_dirs) else ""
        full = Path(directory) / name
        if not full.is_absolute():
            full = base / full
        return os.path.normpath(os.path.abspath(full))

    names: dict[int, str] = {}
    ranges: list[_Range] = []
    previous = None
    for entry in program.get_entries():
        state = entry.state
        if state is None:
            continue
        if previous is not None and state.address > previous.address and previous.line > 0:
            if previous.file not in names:
                names[previous.file] = file_path(previous.file)
            ranges.append(
                _Range(
                    previous.address,
                    state.address,
                    names[previous.file],
                    previous.line,
                    bool(previous.is_stmt),
                )
            )
        previous = None if state.end_sequence else _Row(state)
    return ranges


class _Row:
    """Copia de los campos relevantes de una fila (pyelftools reutiliza el estado)."""

    __slots__ = ("address", "file", "is_stmt", "line")

    def __init__(self, state: Any) -> None:
        self.address: int = state.address
        self.file: int = state.file
        self.line: int = state.line
        self.is_stmt: bool = state.is_stmt
