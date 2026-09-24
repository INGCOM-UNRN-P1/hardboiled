"""Los widgets no deben pisar atributos internos de Textual.

Definir `self._running` en la App o `self._lines` en un OptionList reemplaza
estado interno de Textual: el primero impidió que se montaran widgets nuevos y
el segundo rompe el listado. Este test lo detecta antes de que llegue a la UI.
"""

from __future__ import annotations

import contextlib
import inspect
import re
from pathlib import Path

import pytest
from textual.app import App
from textual.scroll_view import ScrollView
from textual.widget import Widget
from textual.widgets import OptionList, Static, Tree

SRC = Path(__file__).parents[1] / "src" / "hardboiled" / "ui"
ASSIGNED = re.compile(r"self\.(_[A-Za-z]\w*)\s*(?::[^=]*)?=")
USED = re.compile(r"self\.(_[A-Za-z]\w*)")


def textual_internals(base: type) -> set[str]:
    names: set[str] = set()
    for cls in base.__mro__:
        if not cls.__module__.startswith("textual"):
            continue
        with contextlib.suppress(OSError, TypeError):  # clases sin fuente disponible
            names |= set(USED.findall(inspect.getsource(cls)))
        names |= {name for name in vars(cls) if name.startswith("_")}
    return names


BASES: dict[str, type] = {
    "tui.py": App,
    "widgets/code_view.py": ScrollView,
    "widgets/variables_view.py": Tree,
    "widgets/registers_view.py": Static,
    "widgets/memory_view.py": Static,
}


@pytest.mark.parametrize("path", sorted(p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py")))
def test_no_private_attribute_clashes(path: str) -> None:
    source = (SRC / path).read_text(encoding="utf-8")
    base = BASES.get(path)
    if base is None:
        base = OptionList if "OptionList" in source else Widget
    clashes = sorted(set(ASSIGNED.findall(source)) & textual_internals(base))
    assert not clashes, f"{path} pisa atributos internos de Textual: {clashes}"


BASE_STYLE = re.compile(r"= Text\([^)]*style=")


@pytest.mark.parametrize("path", sorted(p.relative_to(SRC).as_posix() for p in SRC.rglob("*.py")))
def test_no_base_styled_text_followed_by_appends(path: str) -> None:
    """`Text("x", style=s)` aplica `s` a todo lo que se agregue después con append.

    Para estilos por tramo hay que usar Text.assemble o Text() + append.
    """
    source = (SRC / path).read_text(encoding="utf-8")
    assert not BASE_STYLE.search(source), f"{path} usa Text(..., style=) como estilo base"
