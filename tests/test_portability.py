"""Portabilidad a Windows: toda E/S de texto declara su codificación.

Sin `encoding=`, Python usa la del sistema: en Windows, cp1252. Leer un fuente
con "á" o "…", o escribir una plantilla, falla o corrompe el texto (pasó en CI).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
FILES = sorted(
    path for folder in ("src", "tests", "scripts") for path in (ROOT / folder).rglob("*.py")
)
TEXT_METHODS = {"read_text", "write_text"}


def _keywords(call: ast.Call) -> set[str | None]:
    return {keyword.arg for keyword in call.keywords}


def _binary_mode(call: ast.Call, position: int) -> bool:
    mode: ast.expr | None = call.args[position] if len(call.args) > position else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            mode = keyword.value
    return isinstance(mode, ast.Constant) and isinstance(mode.value, str) and "b" in mode.value


def implicit_encodings(path: Path) -> list[str]:
    problems = []
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if not isinstance(node, ast.Call):
            continue
        keywords = _keywords(node)
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
        if "encoding" in keywords or None in keywords:  # **kwargs: no se puede saber
            continue
        if name in TEXT_METHODS:
            problem = name
        elif name == "open" and isinstance(func, ast.Attribute):  # Path.open(modo)
            if isinstance(func.value, ast.Name) and func.value.id == "os":
                continue  # os.open: descriptor de bajo nivel, sin texto
            problem = "" if _binary_mode(node, 0) else "Path.open"
        elif name == "open":  # open(archivo, modo)
            problem = "" if _binary_mode(node, 1) else "open"
        elif name in ("run", "check_output", "Popen") and (
            "text" in keywords or "universal_newlines" in keywords
        ):
            problem = f"subprocess.{name}(text=True)"
        elif name == "TextIOWrapper":
            problem = name
        else:
            continue
        if problem:
            problems.append(f"{path.relative_to(ROOT)}:{node.lineno}: {problem} sin encoding")
    return problems


@pytest.mark.parametrize("path", FILES, ids=lambda p: str(p.relative_to(ROOT)))
def test_text_io_declares_encoding(path: Path) -> None:
    assert implicit_encodings(path) == []
