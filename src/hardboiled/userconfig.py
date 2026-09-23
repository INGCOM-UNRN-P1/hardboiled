"""Preferencias del usuario en `config.toml` (fuera de cualquier proyecto).

Ubicación: `hardboiled config path` (XDG en Linux, ~/Library en macOS,
%APPDATA% en Windows, o HARDBOILED_CONFIG_DIR). Todas las claves son
opcionales; lo que se indica en la línea de comandos tiene prioridad.
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from hardboiled import paths

CONFIG_FILE = "config.toml"

TEMPLATE = """\
# Preferencias de hardboiled. Todas las claves son opcionales.

[build]
# compiler = "auto"        # auto, gcc, zig o una ruta (como --cc)
# opt_level = "0"          # como -O
# march = "rv32i"          # rv32i, rv32im, rv32ic, rv32imc

[run]
# clock_hz = 1_000_000     # reemplaza el clock_hz de la placa en la TUI
# stop_at_main = true
# save_breakpoints = true  # recordar breakpoints en .hardboiled/ junto al programa
# history = 200            # pasos que se pueden deshacer con F8 (0 lo desactiva)

[ui]
# theme = "dark"           # dark o light (proyector del aula)
# colorblind = false       # LEDs y estados distinguibles por forma, no sólo por color

[keys]
# Reasignar atajos: acción = "tecla[,otra]" (reemplaza todas las teclas de esa
# acción). Útil si la terminal captura F10/F11. Acciones: continue, pause,
# toggle_breakpoint, conditional_breakpoint, step_over, step_into, step_out,
# step_instruction, step_back, run_to_cursor, watch, toggle_disassembly,
# register_format, open_file, search, search_next, search_previous, goto_line,
# help, reset, quit, switch_0 … switch_7. La lista vigente está en la ayuda (?).
# step_over = "f8,n"
# step_into = "f2,s"
"""


class ConfigError(Exception):
    pass


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BuildPrefs(_Model):
    compiler: str | None = None
    opt_level: str = "0"
    march: str = "rv32i"


class RunPrefs(_Model):
    clock_hz: int | None = Field(default=None, gt=0)
    stop_at_main: bool = True
    save_breakpoints: bool = True
    history: int = Field(default=200, ge=0, le=10_000)


class UiPrefs(_Model):
    theme: Literal["dark", "light"] = "dark"
    colorblind: bool = False


class UserConfig(_Model):
    build: BuildPrefs = BuildPrefs()
    run: RunPrefs = RunPrefs()
    ui: UiPrefs = UiPrefs()
    keys: dict[str, str] = Field(default_factory=dict)


def config_path() -> Path:
    return paths.config_dir() / CONFIG_FILE


def load_user_config(path: Path | None = None) -> UserConfig:
    path = path or config_path()
    if not path.is_file():
        return UserConfig()
    try:
        with path.open("rb") as stream:
            return UserConfig.model_validate(tomllib.load(stream))
    except tomllib.TOMLDecodeError as exc:
        raise ConfigError(f"{path}: TOML inválido: {exc}") from exc
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(p) for p in err['loc'])}: {err['msg']}" for err in exc.errors()
        )
        raise ConfigError(f"{path}: configuración inválida: {details}") from exc
