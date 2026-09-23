"""Recompila los fixtures ELF con `zig cc` (paquete PyPI `ziglang`, sin toolchain del sistema).

Uso: uv run python tests/fixtures/build.py
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
RUNTIME = HERE.parents[1] / "runtime"
PROGRAMS = ("basic", "mmio", "traps", "demo")

CFLAGS = [
    "-target", "riscv32-freestanding-none",
    "-mcpu=generic_rv32",  # RV32I puro, sin extensiones M/A/C
    "-g", "-O0",
    "-fno-sanitize=undefined",
    "-fno-unwind-tables", "-fno-asynchronous-unwind-tables",
    "-ffunction-sections", "-fdata-sections",
    "-fdebug-compilation-dir=.",
    "-Wl,--gc-sections",
    "-Wall", "-Wextra",
]  # fmt: skip


def build(name: str) -> None:
    command = [
        sys.executable, "-m", "ziglang", "cc", *CFLAGS,
        f"-I{RUNTIME / 'include'}",
        f"-T{RUNTIME / 'hardboiled.ld'}",
        str(RUNTIME / "crt0.s"), f"{name}.c",
        "-o", f"{name}.elf",
    ]  # fmt: skip
    subprocess.run(command, cwd=HERE, check=True)
    print(f"ok  {name}.elf")


if __name__ == "__main__":
    for program in sys.argv[1:] or PROGRAMS:
        build(program)
