"""Pistas breves para cada tipo de trampa o aviso, con la sección de la guía.

La guía completa viaja en el paquete (data/docs/trampas.md) y se lee con
`hardboiled explain <tipo>`.
"""

from __future__ import annotations

import re

from hardboiled import resources

HINTS: dict[str, str] = {
    "null-pointer": "¿El puntero se inicializó? ¿Una función devolvió NULL y no se verificó?",
    "flash-write": "¿Se modificó un literal de cadena o una variable const? Usá un char[].",
    "unmapped": "¿Puntero sin inicializar, índice fuera de rango o aritmética de punteros?",
    "bad-jump": "¿Puntero a función corrupto, o un buffer overflow pisó el ra guardado en la pila?",
    "stack-overflow": "¿Recursión sin caso base? ¿Un arreglo local demasiado grande?",
    "misaligned": "¿Un int* que apunta dentro de un char[]? Copiá los bytes en lugar de convertir.",
    "mmio": "Usá las macros de hardboiled.h en lugar de direcciones escritas a mano.",
    "wfi-deadlock": "Falta attach_irq(), interrupts_enable() o activar la IRQ del periférico.",
    "vector": "Compilá con `hardboiled build` para enlazar crt0.s y hardboiled.ld.",
    "isr-stack": "Una ISR escrita en ensamblador dejó sp distinto de como lo encontró.",
    "exception": "Instrucción desconocida: ¿salto a datos o compilado para otra arquitectura?",
    "limit": "Si es un bucle infinito, la pausa muestra dónde; si no, F5 continúa.",
    "div0": "Verificá que el divisor no sea cero antes de dividir.",
    "uninit": "Inicializá la variable al declararla.",
}


def hint_for(kind: str | None) -> str | None:
    return HINTS.get(kind) if kind else None


def explain(kind: str) -> str | None:
    """Sección de la guía para `kind` (sin el ancla HTML), o None si no existe."""
    text = (resources.package_dir() / "data" / "docs" / "trampas.md").read_text(encoding="utf-8")
    match = re.search(rf'<a id="{re.escape(kind)}"></a>\n(.*?)(?=\n<a id=|\Z)', text, re.S)
    return match.group(1).strip() if match else None


def kinds() -> list[str]:
    return list(HINTS)
