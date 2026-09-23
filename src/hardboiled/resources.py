"""Ubicación de los recursos empaquetados (runtime, placa por defecto, ejemplos).

Todo lo que un alumno necesita para compilar viaja dentro del paquete, así
funciona igual desde el repositorio, desde `uv tool install` o desde `uvx`.
"""

from __future__ import annotations

from importlib.resources import files
from pathlib import Path


def package_dir() -> Path:
    return Path(str(files("hardboiled")))


def runtime_dir() -> Path:
    return package_dir() / "runtime"


def include_dir() -> Path:
    return runtime_dir() / "include"


def header_path() -> Path:
    return include_dir() / "hardboiled.h"


def linker_script() -> Path:
    return runtime_dir() / "hardboiled.ld"


def crt0_path() -> Path:
    return runtime_dir() / "crt0.s"


def default_board_path() -> Path:
    """Plantilla de la placa por defecto (la misma que `board.toml` del repositorio)."""
    return package_dir() / "data" / "board.toml"


def examples_dir() -> Path:
    return package_dir() / "examples"


def example_names() -> list[str]:
    return sorted(p.stem for p in examples_dir().glob("*.c"))


def example_path(name: str) -> Path:
    """Ruta del ejemplo `name` (con o sin `.c`)."""
    return examples_dir() / f"{name.removesuffix('.c')}.c"


def example_summary(name: str) -> str:
    """Descripción de una línea: el texto tras la raya en la primera línea del comentario."""
    for line in example_path(name).read_text(encoding="utf-8").splitlines():
        text = line.strip(" /*")
        if "—" in text:
            return text.split("—", 1)[1].strip()
    return ""
