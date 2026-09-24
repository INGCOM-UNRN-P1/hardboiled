"""Recompila los fixtures ELF con `zig cc` a través de hardboiled.toolchain.

Uso: uv run python tests/fixtures/build.py [programa ...]
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from hardboiled import resources
from hardboiled.toolchain import BuildOptions, build, select_compiler

HERE = Path(__file__).resolve().parent
PROGRAMS = ("basic", "mmio", "traps", "types", "hwloop")

# Rutas DWARF relativas al directorio del ELF, también las del runtime
# (crt0.s, hardboiled.h), que se pasan con ruta absoluta: los fixtures
# funcionan desde cualquier clon del repositorio (p. ej. en CI).
RUNTIME = resources.runtime_dir().resolve()
OPTIONS = BuildOptions(
    extra_flags=(
        "-fdebug-compilation-dir=.",
        f"-ffile-prefix-map={RUNTIME}={os.path.relpath(RUNTIME, HERE)}",
    )
)


def main(names: list[str]) -> None:
    compiler = select_compiler("zig")
    for name in names or PROGRAMS:
        result = build([f"{name}.c"], f"{name}.elf", OPTIONS, compiler, cwd=HERE)
        if result.diagnostics:
            print(result.diagnostics)
        print(f"ok  {result.output.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
