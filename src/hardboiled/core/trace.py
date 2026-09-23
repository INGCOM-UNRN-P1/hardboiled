"""Traza de ejecución: una fila por instrucción, para ejercicios de seguimiento.

Cada fila tiene el número de instrucción, el ciclo, el PC, la función, la línea
de C, la instrucción desensamblada y los registros que cambió. Las entradas a
una interrupción se anotan como evento en la primera instrucción de la ISR (el
contexto que guarda la CPU no se atribuye a ninguna instrucción).

Formatos: CSV (`.csv`) o una línea JSON por instrucción (`.jsonl`).
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, TYPE_CHECKING

from hardboiled.core.cpu import ABI_NAMES

if TYPE_CHECKING:
    from hardboiled.core.machine import Machine

FORMATS = (".csv", ".jsonl")
CSV_FIELDS = ("n", "cycle", "pc", "function", "file", "line", "instruction", "changes", "event")


class TraceError(Exception):
    pass


@dataclass
class _Row:
    n: int
    cycle: int
    pc: int
    registers: tuple[int, ...]
    event: str = ""
    changes: dict[str, int] = field(default_factory=dict)


class TraceWriter:
    """Tracer de la CPU (ver Cpu.tracer) que escribe a un archivo."""

    def __init__(self, machine: Machine, path: str | Path, limit: int = 1_000_000) -> None:
        path = Path(path)
        if path.suffix not in FORMATS:
            raise TraceError(f"formato de traza desconocido {path.suffix!r}: usá .csv o .jsonl")
        self.machine = machine
        self.path = path
        self.limit = limit
        self.rows = 0
        self.truncated = False
        self._jsonl = path.suffix == ".jsonl"
        try:
            self._file: IO[str] = path.open("w", encoding="utf-8", newline="")
        except OSError as exc:
            raise TraceError(f"no se pudo crear {path}: {exc}") from exc
        self._csv = csv.writer(self._file)
        if not self._jsonl:
            self._csv.writerow(CSV_FIELDS)
        self._pending: _Row | None = None
        self._event = ""
        self._where: dict[int, tuple[str, str, int | None, str]] = {}

    def attach(self) -> None:
        self.machine.cpu.tracer = self

    # --------------------------------------------------------- Tracer

    def step(self, pc: int) -> None:
        cpu = self.machine.cpu
        registers = cpu.register_values()
        self._finish(registers)
        if self.rows >= self.limit:
            self.truncated = True
            cpu.tracer = None  # el programa sigue sin traza (desde el próximo run, en modo rápido)
            return
        self._pending = _Row(cpu.instructions, cpu.clock.cycles, pc, registers, self._event)
        self._event = ""

    def event(self, text: str) -> None:
        self._finish(self.machine.cpu.register_values())
        self._event = text

    def close(self) -> None:
        if self.machine.cpu.tracer is self:
            self.machine.cpu.tracer = None
        if self._pending is not None:
            self._finish(self.machine.cpu.register_values())
        self._file.close()

    # --------------------------------------------------------- escritura

    def _finish(self, registers: tuple[int, ...]) -> None:
        row = self._pending
        if row is None:
            return
        self._pending = None
        row.changes = {
            ABI_NAMES[index]: after
            for index, (before, after) in enumerate(zip(row.registers, registers, strict=True))
            if before != after
        }
        self._write(row)

    def _describe(self, pc: int) -> tuple[str, str, int | None, str]:
        cached = self._where.get(pc)
        if cached is None:
            debugger = self.machine.debugger
            location = debugger.location(pc)
            instruction = debugger.instruction_at(pc)
            cached = (
                debugger.function(pc) or self.machine.image.describe(pc),
                location.file.rsplit("/", 1)[-1] if location else "",
                location.line if location else None,
                instruction.text if instruction is not None else "",
            )
            self._where[pc] = cached
        return cached

    def _write(self, row: _Row) -> None:
        function, file, line, instruction = self._describe(row.pc)
        self.rows += 1
        if self._jsonl:
            record = {
                "n": row.n,
                "cycle": row.cycle,
                "pc": f"0x{row.pc:08x}",
                "function": function,
                "file": file or None,
                "line": line,
                "instruction": instruction,
                "changes": {name: f"0x{value:08x}" for name, value in row.changes.items()},
            }
            if row.event:
                record["event"] = row.event
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            return
        changes = " ".join(f"{name}=0x{value:08x}" for name, value in row.changes.items())
        self._csv.writerow(
            (row.n, row.cycle, f"0x{row.pc:08x}", function, file, line or "", instruction,
             changes, row.event)
        )  # fmt: skip
