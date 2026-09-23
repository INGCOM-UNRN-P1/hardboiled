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
