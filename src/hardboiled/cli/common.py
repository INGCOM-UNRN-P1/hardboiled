"""Utilidades compartidas por los subcomandos de la CLI."""

from __future__ import annotations

import argparse
import tomllib
from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError

from hardboiled.config import BoardConfig, load_board
from hardboiled.core.elf import ElfLoadError
from hardboiled.core.machine import Machine

EXIT_USAGE = 2
EXIT_TRAP = 3
EXIT_INTERRUPTED = 130

type Subparsers = argparse._SubParsersAction[argparse.ArgumentParser]
Handler = Callable[[argparse.Namespace], int]


class CliError(Exception):
    pass


def parse_int(text: str) -> int:
    return int(text.replace("_", ""), 0)


def load_board_file(path: Path) -> BoardConfig:
    try:
        return load_board(path)
    except FileNotFoundError as exc:
        raise CliError(f"no existe el archivo de placa {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CliError(f"{path}: TOML inválido: {exc}") from exc
    except ValidationError as exc:
        raise CliError(f"{path}: configuración inválida\n{format_errors(exc)}") from exc


def board_from(path: str | None) -> BoardConfig:
    """Usa la placa indicada, o `./board.toml` si existe, o la placa por defecto."""
    if path is None:
        candidate = Path("board.toml")
        return load_board_file(candidate) if candidate.exists() else BoardConfig()
    return load_board_file(Path(path))


def format_errors(exc: ValidationError) -> str:
    lines = []
    for error in exc.errors():
        where = ".".join(str(part) for part in error["loc"]) or "(raíz)"
        lines.append(f"  - {where}: {error['msg']}")
    return "\n".join(lines)


def load_machine(elf: str | Path, board: BoardConfig) -> Machine:
    try:
        return Machine.from_elf(elf, board)
    except ElfLoadError as exc:
        raise CliError(str(exc)) from exc
    except FileNotFoundError as exc:
        raise CliError(f"no existe {elf}") from exc
