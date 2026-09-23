"""Compilación de programas C para la placa: detecta la toolchain y agrega el runtime.

Se prefiere una toolchain GNU para RISC-V si está en el PATH; si no, se usa el
clang que trae el paquete `ziglang` (extra `hardboiled[zig]`), que corre dentro
del mismo entorno que hardboiled.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

from hardboiled import resources

CompilerKind = Literal["gcc", "zig"]

GCC_NAMES = (
    "riscv64-unknown-elf-gcc",
    "riscv32-unknown-elf-gcc",
    "riscv-none-elf-gcc",
    "riscv64-elf-gcc",
    "riscv32-elf-gcc",
)

# Extensiones que la placa sabe ejecutar, en el orden canónico de -march.
SUPPORTED_EXTENSIONS = "mc"

INSTALL_HINT = (
    "no se encontró un compilador para RISC-V. Opciones:\n"
    '  - instalar hardboiled con el extra zig:  uv tool install "hardboiled[zig]"\n'
    "  - o instalar una toolchain GNU (riscv64-unknown-elf-gcc) y dejarla en el PATH\n"
    "  - o indicar el compilador con --cc RUTA o la variable HARDBOILED_CC"
)


class ToolchainError(Exception):
    pass


class BuildError(ToolchainError):
    def __init__(self, message: str, output: str, command: Sequence[str]) -> None:
        super().__init__(message)
        self.output = output
        self.command = list(command)


@dataclass(frozen=True)
class Compiler:
    kind: CompilerKind
    command: tuple[str, ...]
    description: str


@dataclass(frozen=True)
class RuntimeFiles:
    include_dir: Path
    linker_script: Path
    crt0: Path

    @classmethod
    def packaged(cls) -> RuntimeFiles:
        return cls(resources.include_dir(), resources.linker_script(), resources.crt0_path())


@dataclass(frozen=True)
class BuildOptions:
    opt_level: str = "0"
    march: str = "rv32i"
    debug: bool = True
    warnings: bool = True
    defines: tuple[str, ...] = ()
    include_dirs: tuple[Path, ...] = ()
    extra_flags: tuple[str, ...] = ()
    runtime: RuntimeFiles = field(default_factory=RuntimeFiles.packaged)


@dataclass(frozen=True)
class BuildResult:
    output: Path
    command: tuple[str, ...]
    diagnostics: str


# ------------------------------------------------------------ detección


def _zig_compiler() -> Compiler | None:
    if importlib.util.find_spec("ziglang") is None:
        return None
    return Compiler("zig", (sys.executable, "-m", "ziglang", "cc"), "zig cc (paquete ziglang)")


def _gcc_compiler(executable: str) -> Compiler:
    return Compiler("gcc", (executable,), f"{Path(executable).name} ({executable})")


def find_compilers() -> list[Compiler]:
    """Compiladores disponibles, en orden de preferencia."""
    found = [_gcc_compiler(path) for name in GCC_NAMES if (path := shutil.which(name))]
    zig = _zig_compiler()
    if zig is not None:
        found.append(zig)
    return found


def _kind_of(executable: str) -> CompilerKind:
    return "zig" if "zig" in Path(executable).name else "gcc"


def select_compiler(preference: str | None = None) -> Compiler:
    """`auto` (o None), `gcc`, `zig` o la ruta/nombre de un ejecutable.

    Sin preferencia explícita se respeta la variable de entorno HARDBOILED_CC.
    """
    choice = preference or os.environ.get("HARDBOILED_CC") or "auto"
    if choice == "auto":
        compilers = find_compilers()
        if not compilers:
            raise ToolchainError(INSTALL_HINT)
        return compilers[0]
    if choice == "zig":
        zig = _zig_compiler()
        if zig is None:
            raise ToolchainError(
                'zig no está disponible: instalá el extra con uv tool install "hardboiled[zig]"'
            )
        return zig
    if choice == "gcc":
        for name in GCC_NAMES:
            if path := shutil.which(name):
                return _gcc_compiler(path)
        raise ToolchainError(f"no hay ningún {' / '.join(GCC_NAMES)} en el PATH")
    path = shutil.which(choice)
    if path is None:
        raise ToolchainError(f"no se encontró el compilador {choice!r}")
    kind = _kind_of(path)
    command = (path, "cc") if kind == "zig" and Path(path).name.startswith("zig") else (path,)
    return Compiler(kind, command, f"{Path(path).name} ({path})")


# ------------------------------------------------------------- comandos


def parse_march(march: str) -> str:
    """Valida y normaliza -march: rv32i más extensiones m y/o c (p. ej. rv32imc)."""
    normalized = march.lower().strip()
    if not normalized.startswith("rv32i"):
        raise ToolchainError(f"arquitectura no soportada: {march} (se espera rv32i[m][c])")
    extensions = normalized.removeprefix("rv32i")
    unknown = sorted(set(extensions) - set(SUPPORTED_EXTENSIONS))
    if unknown or len(set(extensions)) != len(extensions):
        raise ToolchainError(
            f"extensiones no soportadas en {march}: "
            "la placa ejecuta rv32i, rv32im, rv32ic y rv32imc"
        )
    ordered = "".join(ext for ext in SUPPORTED_EXTENSIONS if ext in extensions)
    return f"rv32i{ordered}"


def compile_command(
    compiler: Compiler,
    sources: Sequence[Path | str],
    output: Path | str,
    options: BuildOptions | None = None,
) -> list[str]:
    options = options or BuildOptions()
    march = parse_march(options.march)
    runtime = options.runtime
    command = list(compiler.command)
    if compiler.kind == "zig":
        cpu = "generic_rv32" + "".join(f"+{ext}" for ext in march.removeprefix("rv32i"))
        command += [
            "-target",
            "riscv32-freestanding-none",
            f"-mcpu={cpu}",
            "-fno-sanitize=undefined",
        ]
    else:
        command += [f"-march={march}", "-mabi=ilp32", "-nostdlib", "-nostartfiles"]
    command += [
        f"-O{options.opt_level}",
        "-ffreestanding",
        "-fno-unwind-tables",
        "-fno-asynchronous-unwind-tables",
        "-ffunction-sections",
        "-fdata-sections",
        "-Wl,--gc-sections",
    ]
    # Explícito en ambos sentidos: zig cc genera información de depuración por defecto.
    command.append("-g" if options.debug else "-g0")
    if options.warnings:
        command += ["-Wall", "-Wextra"]
    command += [f"-D{define}" for define in options.defines]
    command += [f"-I{directory}" for directory in options.include_dirs]
    command += [f"-I{runtime.include_dir}", f"-T{runtime.linker_script}"]
    command += list(options.extra_flags)
    command += [str(runtime.crt0), *(str(source) for source in sources)]
    command += ["-o", str(output)]
    if compiler.kind == "gcc":
        command.append("-lgcc")  # multiplicación/división por software en RV32I
    return command


def default_output(sources: Sequence[Path | str]) -> Path:
    first = Path(sources[0])
    return first.with_suffix(".elf")


def build(
    sources: Sequence[Path | str],
    output: Path | str | None = None,
    options: BuildOptions | None = None,
    compiler: Compiler | None = None,
    cwd: Path | None = None,
) -> BuildResult:
    if not sources:
        raise ToolchainError("no se indicó ningún archivo fuente")
    base = cwd or Path.cwd()
    for source in sources:
        if not (base / source).is_file():
            raise ToolchainError(f"no existe el archivo fuente {source}")
    compiler = compiler or select_compiler()
    target = Path(output) if output is not None else default_output(sources)
    command = compile_command(compiler, sources, target, options)
    try:
        completed = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False)
    except OSError as exc:
        raise ToolchainError(f"no se pudo ejecutar {command[0]}: {exc}") from exc
    diagnostics = (completed.stdout + completed.stderr).strip()
    if completed.returncode != 0:
        raise BuildError(f"la compilación falló ({compiler.description})", diagnostics, command)
    return BuildResult(base / target, tuple(command), diagnostics)
