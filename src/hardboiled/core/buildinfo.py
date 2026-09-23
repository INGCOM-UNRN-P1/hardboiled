"""Cómo se compiló el programa: ¿tiene información de depuración? ¿está optimizado?

El paso a paso y la inspección de variables necesitan `-g` y funcionan mejor con
`-O0`. Si el binario no cumple eso conviene explicarlo al cargarlo, antes de que
el alumno se confunda porque "el depurador salta líneas".

Pistas de optimización (en las unidades de compilación del usuario):
- gcc anota los flags en DW_AT_producer ("GNU C17 13.2 -O2 -g");
- variables con listas de ubicación (sólo existen si el optimizador las mueve);
- funciones cuya base de marco es sp en lugar de s0 (sin frame pointer).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from elftools.elf.elffile import ELFFile

from hardboiled.core.dwarf import USER_SOURCE_SUFFIXES

OPT_FLAG = re.compile(r"(?:^|\s)-O([1-3sz]|fast)\b")
LOCATION_FORMS = ("DW_FORM_exprloc", "DW_FORM_block1", "DW_FORM_block")


@dataclass
class BuildReport:
    has_debug: bool
    optimized: bool = False
    reasons: list[str] = field(default_factory=list)
    producers: list[str] = field(default_factory=list)

    def warnings(self) -> list[str]:
        messages = []
        if not self.has_debug:
            messages.append(
                "el programa no tiene información de depuración de tu código (¿se compiló "
                "sin -g?): no se puede seguir línea por línea ni ver variables. "
                "`hardboiled build` ya agrega -g."
            )
        if self.optimized:
            messages.append(
                "el programa parece compilado con optimización ("
                + "; ".join(self.reasons)
                + "): el paso a paso puede saltar líneas o volver atrás y algunas variables "
                "figuran como no disponibles. Para depurar conviene -O0."
            )
        return messages


def _text(value: Any) -> str:
    return value.decode("utf-8", "replace") if isinstance(value, bytes) else str(value)


def _is_user_unit(top: Any, elf_path: Path) -> bool:
    name_attr = top.attributes.get("DW_AT_name")
    if name_attr is None:
        return False
    name = Path(_text(name_attr.value))
    if name.suffix not in USER_SOURCE_SUFFIXES or name.suffix in (".s", ".S"):
        return False  # el ensamblador de crt0 no dice nada del nivel de optimización
    comp_dir_attr = top.attributes.get("DW_AT_comp_dir")
    comp_dir = _text(comp_dir_attr.value) if comp_dir_attr else ""
    base = Path(comp_dir) if os.path.isabs(comp_dir) else elf_path.parent / comp_dir
    return (name if name.is_absolute() else base / name).is_file()


def analyze(path: str | Path) -> BuildReport:
    path = Path(path)
    with path.open("rb") as stream:
        elf = ELFFile(stream)
        if not elf.has_dwarf_info():
            return BuildReport(has_debug=False)
        dwarf = elf.get_dwarf_info()
        report = BuildReport(has_debug=False)
        location_lists = 0
        no_frame_pointer: list[str] = []
        for cu in dwarf.iter_CUs():
            top = cu.get_top_DIE()
            if not _is_user_unit(top, path):
                continue
            report.has_debug = True
            producer = top.attributes.get("DW_AT_producer")
            if producer is not None:
                text = _text(producer.value)
                report.producers.append(text)
                flag = OPT_FLAG.search(text)
                if flag:
                    report.reasons.append(f"el compilador registró -O{flag.group(1)}")
            for die in cu.iter_DIEs():
                if die.tag in ("DW_TAG_variable", "DW_TAG_formal_parameter"):
                    location = die.attributes.get("DW_AT_location")
                    if location is not None and location.form not in LOCATION_FORMS:
                        location_lists += 1
                elif die.tag == "DW_TAG_subprogram" and "DW_AT_low_pc" in die.attributes:
                    base = die.attributes.get("DW_AT_frame_base")
                    if base is not None and base.form == "DW_FORM_exprloc" and base.value == [0x72]:
                        name = die.attributes.get("DW_AT_name")
                        no_frame_pointer.append(_text(name.value) if name else "?")
        if location_lists:
            report.reasons.append(f"{location_lists} variables cambian de lugar durante la función")
        if no_frame_pointer:
            shown = ", ".join(no_frame_pointer[:3])
            report.reasons.append(f"funciones sin frame pointer ({shown})")
        report.optimized = bool(report.reasons)
        return report
