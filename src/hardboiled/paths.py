"""Directorios por usuario: configuración y caché, según la plataforma.

Instalado como herramienta no hay un "repositorio" donde guardar cosas: se
siguen las convenciones de cada sistema (XDG en Linux, ~/Library en macOS,
%APPDATA%/%LOCALAPPDATA% en Windows). Las variables HARDBOILED_CONFIG_DIR y
HARDBOILED_CACHE_DIR tienen prioridad (útiles en tests y en aulas).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

APP = "hardboiled"


def _home() -> Path:
    return Path.home()


def config_dir() -> Path:
    if override := os.environ.get("HARDBOILED_CONFIG_DIR"):
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("APPDATA", _home() / "AppData" / "Roaming")) / APP
    if sys.platform == "darwin":
        return _home() / "Library" / "Application Support" / APP
    return Path(os.environ.get("XDG_CONFIG_HOME") or _home() / ".config") / APP


def cache_dir() -> Path:
    if override := os.environ.get("HARDBOILED_CACHE_DIR"):
        return Path(override)
    if sys.platform == "win32":
        return Path(os.environ.get("LOCALAPPDATA", _home() / "AppData" / "Local")) / APP / "cache"
    if sys.platform == "darwin":
        return _home() / "Library" / "Caches" / APP
    return Path(os.environ.get("XDG_CACHE_HOME") or _home() / ".cache") / APP
