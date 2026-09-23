"""Pistas breves para cada tipo de trampa o aviso, con la sección de la guía.

La guía completa viaja en el paquete (data/docs/trampas.md, y trampas.en.md en
inglés) y se lee con `hardboiled explain <tipo>`.
"""

from __future__ import annotations

import re

from hardboiled import i18n, resources
from hardboiled.i18n import N_, _

HINTS: dict[str, str] = {
    "null-pointer": N_("¿El puntero se inicializó? ¿Una función devolvió NULL y no se verificó?"),
    "flash-write": N_("¿Se modificó un literal de cadena o una variable const? Usá un char[]."),
    "unmapped": N_("¿Puntero sin inicializar, índice fuera de rango o aritmética de punteros?"),
    "bad-jump": N_(
        "¿Puntero a función corrupto, o un buffer overflow pisó el ra guardado en la pila?"
    ),
    "stack-overflow": N_("¿Recursión sin caso base? ¿Un arreglo local demasiado grande?"),
    "misaligned": N_(
        "¿Un int* que apunta dentro de un char[]? Copiá los bytes en lugar de convertir."
    ),
    "mmio": N_("Usá las macros de hardboiled.h en lugar de direcciones escritas a mano."),
    "wfi-deadlock": N_("Falta attach_irq(), interrupts_enable() o activar la IRQ del periférico."),
    "vector": N_("Compilá con `hardboiled build` para enlazar crt0.s y hardboiled.ld."),
    "isr-stack": N_("Una ISR escrita en ensamblador dejó sp distinto de como lo encontró."),
    "exception": N_("Instrucción desconocida: ¿salto a datos o compilado para otra arquitectura?"),
    "limit": N_("Si es un bucle infinito, la pausa muestra dónde; si no, F5 continúa."),
    "div0": N_("Verificá que el divisor no sea cero antes de dividir."),
    "uninit": N_("Inicializá la variable al declararla."),
}


def hint_for(kind: str | None) -> str | None:
    hint = HINTS.get(kind) if kind else None
    return _(hint) if hint else None


def explain(kind: str) -> str | None:
    """Sección de la guía para `kind` (sin el ancla HTML), o None si no existe."""
    docs = resources.package_dir() / "data" / "docs"
    guide = docs / f"trampas.{i18n.language()}.md"
    text = (guide if guide.is_file() else docs / "trampas.md").read_text(encoding="utf-8")
    match = re.search(rf'<a id="{re.escape(kind)}"></a>\n(.*?)(?=\n<a id=|\Z)', text, re.S)
    return match.group(1).strip() if match else None


def kinds() -> list[str]:
    return list(HINTS)
