"""Breakpoints y watchpoints que sobreviven entre sesiones.

Se guardan en `.hardboiled/<programa>.breakpoints.json` junto al programa, con
rutas relativas a ese directorio: el proyecto se puede mover o compartir y los
breakpoints siguen en su lugar (se ubican por archivo:línea, no por dirección,
así que también sobreviven a una recompilación).
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from hardboiled.core.debugger import Debugger, DebuggerError

STORE_DIR = ".hardboiled"
VERSION = 1


@dataclass(frozen=True)
class SavedPoint:
    kind: str  # "line", "address" o "watch"
    file: str | None = None
    line: int | None = None
    address: int | None = None
    expression: str | None = None
    condition: str | None = None
    hit_count: int | None = None


class BreakpointStore:
    def __init__(self, path: Path) -> None:
        self.path = path

    @classmethod
    def for_program(cls, program: Path) -> BreakpointStore:
        directory = program.resolve().parent
        return cls(directory / STORE_DIR / f"{program.stem}.breakpoints.json")

    @property
    def base(self) -> Path:
        return self.path.parent.parent

    # ------------------------------------------------------------- lectura

    def load(self) -> list[SavedPoint]:
        if not self.path.is_file():
            return []
        try:
            data: dict[str, Any] = json.loads(self.path.read_text(encoding="utf-8"))
            points = [SavedPoint(**entry) for entry in data.get("points", [])]
        except (OSError, ValueError, TypeError):
            return []  # un archivo dañado no debe impedir depurar
        return [self._absolute(point) for point in points]

    def _absolute(self, point: SavedPoint) -> SavedPoint:
        if point.file is None or os.path.isabs(point.file):
            return point
        return SavedPoint(**{**asdict(point), "file": str((self.base / point.file).resolve())})

    def restore(self, debugger: Debugger) -> list[str]:
        """Aplica lo guardado; devuelve descripciones de lo que ya no se pudo ubicar."""
        failed = []
        for point in self.load():
            try:
                if point.kind == "line" and point.line is not None:
                    if point.condition or point.hit_count:
                        debugger.set_condition(
                            point.line, point.file, point.condition, point.hit_count
                        )
                    else:
                        _, line, _ = debugger.resolve_line(point.line, point.file)
                        if (point.file, line) not in debugger.line_breakpoints:
                            debugger.toggle_line_breakpoint(point.line, point.file)
                elif point.kind == "address" and point.address is not None:
                    if point.address not in debugger.address_breakpoints:
                        debugger.toggle_address_breakpoint(point.address)
                elif point.kind == "watch" and point.expression:
                    debugger.add_watchpoint(point.expression)
            except DebuggerError:
                where = point.expression or f"{Path(point.file or '?').name}:{point.line}"
                failed.append(where)
        return failed

    # ----------------------------------------------------------- escritura

    def _relative(self, file: str) -> str:
        try:
            return os.path.relpath(file, self.base)
        except ValueError:  # otra unidad en Windows
            return file

    def save(self, debugger: Debugger) -> None:
        conditions = debugger.conditions
        points: list[SavedPoint] = []
        for (file, line), address in sorted(debugger.line_breakpoint_addresses.items()):
            condition = conditions.get(address)
            points.append(
                SavedPoint(
                    "line",
                    file=self._relative(file),
                    line=line,
                    condition=condition.expression if condition else None,
                    hit_count=condition.hit_target if condition else None,
                )
            )
        points += [SavedPoint("address", address=a) for a in sorted(debugger.address_breakpoints)]
        # Los watchpoints de locales dependen de un marco concreto: no se guardan.
        points += [
            SavedPoint("watch", expression=w.expression)
            for w in debugger.watchpoints
            if w.scope_cfa is None
        ]
        if not points and not self.path.exists():
            return
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            payload = {"version": VERSION, "points": [asdict(p) for p in points]}
            self.path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        except OSError:
            pass  # directorio de sólo lectura (p. ej. un ejemplo instalado): se ignora
