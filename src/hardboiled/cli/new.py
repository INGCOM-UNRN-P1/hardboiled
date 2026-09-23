"""`hardboiled new`: crea un proyecto listo para compilar, ejecutar y editar."""

from __future__ import annotations

import argparse
import re
import shutil
from pathlib import Path

from hardboiled import resources
from hardboiled.cli.common import CliError, Subparsers

EDITOR_FILE = "compile_flags.txt"


def register(sub: Subparsers) -> None:
    parser = sub.add_parser("new", help="crea un proyecto nuevo (main.c, Makefile, placa, editor)")
    parser.add_argument("path", help="directorio del proyecto (se crea si no existe)")
    parser.add_argument(
        "--example", help="partir de un ejemplo incluido en lugar de la plantilla vacía"
    )
    parser.add_argument("--no-board", action="store_true", help="no copiar board.toml")
    parser.add_argument(
        "--editor-only",
        action="store_true",
        help=f"sólo (re)generar {EDITOR_FILE}, p. ej. tras reinstalar hardboiled",
    )
    parser.add_argument("--force", action="store_true", help="sobrescribir archivos existentes")
    parser.set_defaults(func=cmd_new)


def editor_flags(march: str = "rv32i") -> str:
    """Flags para clangd: target, ABI y la ruta del hardboiled.h instalado."""
    return "\n".join(
        [
            "--target=riscv32-unknown-elf",
            f"-march={march}",
            "-mabi=ilp32",
            "-ffreestanding",
            "-nostdlib",
            "-std=c11",
            "-Wall",
            "-Wextra",
            f"-I{resources.include_dir()}",
            "",
        ]
    )


def _project_name(path: Path) -> str:
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", path.resolve().name).strip("_")
    return name or "programa"


def _write(target: Path, content: str, force: bool) -> None:
    if target.exists() and not force:
        raise CliError(f"{target} ya existe (usá --force para sobrescribir)")
    target.write_text(content, encoding="utf-8")
    print(f"  creado {target}")


def cmd_new(args: argparse.Namespace) -> int:
    root = Path(args.path)
    root.mkdir(parents=True, exist_ok=True)
    if args.editor_only:
        _write(root / EDITOR_FILE, editor_flags(), force=True)
        return 0
    name = _project_name(root)
    template = resources.package_dir() / "data" / "project"

    files: dict[str, str] = {}
    if args.example:
        example = resources.example_path(args.example)
        if not example.is_file():
            raise CliError(f"no existe el ejemplo {args.example!r}")
        files["main.c"] = example.read_text(encoding="utf-8")
    else:
        files["main.c"] = (template / "main.c").read_text(encoding="utf-8").replace("{name}", name)
    files["Makefile"] = (template / "Makefile").read_text(encoding="utf-8").replace("{name}", name)
    files[".gitignore"] = (template / "gitignore").read_text(encoding="utf-8")
    files[EDITOR_FILE] = editor_flags()

    conflicts = [root / f for f in files if (root / f).exists()]
    if not args.no_board and (root / "board.toml").exists():
        conflicts.append(root / "board.toml")
    if conflicts and not args.force:
        listed = ", ".join(str(p) for p in conflicts)
        raise CliError(f"ya existen {listed} (usá --force para sobrescribir)")

    print(f"proyecto {name} en {root}:")
    for filename, content in files.items():
        _write(root / filename, content, force=True)
    if not args.no_board:
        shutil.copyfile(resources.default_board_path(), root / "board.toml")
        print(f"  creado {root / 'board.toml'}")
    print(f"\nsiguiente paso:  cd {root} && hardboiled run main.c")
    return 0
