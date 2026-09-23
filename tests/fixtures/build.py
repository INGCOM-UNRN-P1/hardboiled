"""Recompila los fixtures ELF con `zig cc` a través de hardboiled.toolchain.

Uso: uv run python tests/fixtures/build.py [programa ...]
"""

from __future__ import annotations

import sys
from pathlib import Path

from hardboiled.toolchain import BuildOptions, build, select_compiler

HERE = Path(__file__).resolve().parent
PROGRAMS = ("basic", "mmio", "traps", "types")

# Rutas DWARF relativas al directorio del ELF: los fixtures funcionan desde
# cualquier clon del repositorio.
OPTIONS = BuildOptions(extra_flags=("-fdebug-compilation-dir=.",))


def main(names: list[str]) -> None:
    compiler = select_compiler("zig")
    for name in names or PROGRAMS:
        result = build([f"{name}.c"], f"{name}.elf", OPTIONS, compiler, cwd=HERE)
        if result.diagnostics:
            print(result.diagnostics)
        print(f"ok  {result.output.name}")


if __name__ == "__main__":
    main(sys.argv[1:])
