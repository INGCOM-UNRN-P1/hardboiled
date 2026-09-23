"""Perfil de ejecución: cuántas instrucciones se ejecutaron por línea y por función.

Sirve para ver el costo de un bucle o de una recursión, y dónde gasta el tiempo
un programa (por ejemplo, en `__mulsi3` si la placa no tiene la extensión M).
Los contadores los lleva la CPU desde el último Reset.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from hardboiled.core.machine import Machine


@dataclass(frozen=True)
class LineCost:
    file: str
    line: int
    count: int


@dataclass(frozen=True)
class FunctionCost:
    name: str
    count: int


@dataclass(frozen=True)
class Profile:
    total: int
    lines: tuple[LineCost, ...]  # de la más ejecutada a la menos
    functions: tuple[FunctionCost, ...]

    def line_counts(self, file: str) -> dict[int, int]:
        return {cost.line: cost.count for cost in self.lines if cost.file == file}

    def as_dict(self, limit: int | None = None) -> dict[str, Any]:
        return {
            "total": self.total,
            "functions": [{"name": f.name, "count": f.count} for f in self.functions[:limit]],
            "lines": [
                {"file": c.file, "line": c.line, "count": c.count} for c in self.lines[:limit]
            ],
        }


def build_profile(machine: Machine) -> Profile:
    counts = machine.cpu.execution_counts()
    debugger = machine.debugger
    image = machine.image
    lines: dict[tuple[str, int], int] = {}
    functions: dict[str, int] = {}
    for pc, count in counts.items():
        location = debugger.location(pc)
        if location is not None:
            key = (location.file, location.line)
            lines[key] = lines.get(key, 0) + count
        nearest = image.nearest_symbol(pc)  # código de ensamblador (crt0): su etiqueta
        name = (
            debugger.function(pc)
            or image.function_at(pc)
            or (nearest[0] if nearest else "(sin símbolo)")
        )
        functions[name] = functions.get(name, 0) + count
    return Profile(
        total=sum(counts.values()),
        lines=tuple(
            sorted(
                (LineCost(file, line, count) for (file, line), count in lines.items()),
                key=lambda cost: (-cost.count, cost.file, cost.line),
            )
        ),
        functions=tuple(
            sorted(
                (FunctionCost(name, count) for name, count in functions.items()),
                key=lambda cost: (-cost.count, cost.name),
            )
        ),
    )


def format_profile(profile: Profile, top: int = 10) -> str:
    """Resumen para la terminal: funciones y líneas más ejecutadas, con su código."""
    if not profile.total:
        return "perfil: no se ejecutó ninguna instrucción"
    out = [f"Perfil: {profile.total:,} instrucciones ejecutadas", "  funciones:"]
    for fn in profile.functions[:top]:
        out.append(f"    {100 * fn.count / profile.total:5.1f}% {fn.count:>12,}  {fn.name}")
    out.append("  líneas más ejecutadas:")
    sources: dict[str, list[str]] = {}
    shown = profile.lines[:top]
    width = max((len(f"{c.file.rsplit('/', 1)[-1]}:{c.line}") for c in shown), default=0)
    for cost in shown:
        if cost.file not in sources:
            try:
                with open(cost.file, encoding="utf-8", errors="replace") as stream:
                    sources[cost.file] = stream.read().splitlines()
            except OSError:
                sources[cost.file] = []
        text = sources[cost.file]
        code = text[cost.line - 1].strip() if 0 < cost.line <= len(text) else ""
        where = f"{cost.file.rsplit('/', 1)[-1]}:{cost.line}"
        share = 100 * cost.count / profile.total
        out.append(f"    {share:5.1f}% {cost.count:>12,}  {where:<{width}} │ {code}")
    return "\n".join(out)
