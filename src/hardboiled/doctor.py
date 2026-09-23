"""Diagnóstico del entorno: lo primero que conviene pedir en una consulta.

Cada verificación devuelve un `Check` con estado ok, aviso o error. Los avisos
no impiden usar hardboiled; los errores sí.
"""

from __future__ import annotations

import os
import shutil
import sys
import tempfile
from dataclasses import dataclass
from enum import Enum
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

from hardboiled import __version__, paths, resources
from hardboiled.userconfig import ConfigError, config_path, load_user_config

RECOMMENDED_SIZE = (120, 40)

PROBE_SOURCE = """\
#include "hardboiled.h"
int main(void) { uart_puts("ok"); led_set(0x5a); return 42; }
"""


class Status(Enum):
    OK = "ok"
    WARN = "aviso"
    ERROR = "error"


@dataclass(frozen=True)
class Check:
    name: str
    status: Status
    detail: str


def _pkg_version(name: str) -> str | None:
    try:
        return version(name)
    except PackageNotFoundError:
        return None


def check_python() -> Check:
    # requires-python >= 3.12 ya lo garantiza la instalación: sólo se informa.
    current = ".".join(str(part) for part in sys.version_info[:3])
    return Check("Python", Status.OK, f"{current} ({sys.executable})")


def check_packages() -> list[Check]:
    checks = [Check("hardboiled", Status.OK, f"{__version__} en {resources.package_dir()}")]
    for name in ("unicorn", "pyelftools", "textual", "pydantic"):
        found = _pkg_version(name)
        checks.append(
            Check(name, Status.OK, found)
            if found
            else Check(name, Status.ERROR, "no instalado (reinstalá hardboiled)")
        )
    return checks


def check_emulator() -> Check:
    """Ejecuta dos instrucciones RV32I para confirmar que Unicorn soporta RISC-V."""
    try:
        from unicorn import UC_ARCH_RISCV, UC_MODE_RISCV32, Uc, uc_arch_supported
        from unicorn.riscv_const import UC_RISCV_REG_A0

        if not uc_arch_supported(UC_ARCH_RISCV):
            return Check("emulador", Status.ERROR, "Unicorn se compiló sin soporte RISC-V")
        uc = Uc(UC_ARCH_RISCV, UC_MODE_RISCV32)
        uc.mem_map(0x10000, 0x1000)
        code = (0x02A00513).to_bytes(4, "little")  # addi a0, zero, 42
        uc.mem_write(0x10000, code)
        uc.emu_start(0x10000, 0x10004)
        result = uc.reg_read(UC_RISCV_REG_A0)
    except Exception as exc:  # cualquier falla de la biblioteca nativa
        return Check("emulador", Status.ERROR, f"Unicorn no funciona: {exc}")
    if result != 42:
        return Check("emulador", Status.ERROR, f"resultado inesperado ({result})")
    return Check("emulador", Status.OK, "Unicorn ejecuta RV32I")


def check_runtime() -> Check:
    missing = [
        str(path)
        for path in (resources.crt0_path(), resources.linker_script(), resources.header_path())
        if not path.is_file()
    ]
    if missing:
        return Check("runtime", Status.ERROR, "faltan " + ", ".join(missing))
    return Check("runtime", Status.OK, str(resources.runtime_dir()))


def check_config() -> Check:
    path = config_path()
    try:
        load_user_config()
    except ConfigError as exc:
        return Check("configuración", Status.ERROR, str(exc))
    state = "" if path.is_file() else " (no existe: valores por defecto)"
    return Check("configuración", Status.OK, f"{path}{state}")


def check_cache() -> Check:
    directory = paths.cache_dir()
    try:
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=directory):
            pass
    except OSError as exc:
        return Check("caché", Status.WARN, f"{directory} no es escribible: {exc}")
    return Check("caché", Status.OK, str(directory))


def check_compilers(preference: str | None) -> list[Check]:
    from hardboiled.toolchain import ToolchainError, find_compilers, select_compiler

    found = find_compilers()
    listed = ", ".join(c.description for c in found) or "ninguno"
    checks = [Check("compiladores", Status.OK if found else Status.ERROR, listed)]
    try:
        chosen = select_compiler(preference)
    except ToolchainError as exc:
        checks.append(Check("compilador elegido", Status.ERROR, str(exc).splitlines()[0]))
    else:
        checks.append(Check("compilador elegido", Status.OK, chosen.description))
    return checks


def check_build_and_run(preference: str | None) -> Check:
    """Compila y ejecuta un programa mínimo: prueba todo el circuito de punta a punta."""
    from hardboiled.core.cpu import StopReason
    from hardboiled.core.machine import Machine
    from hardboiled.toolchain import ToolchainError, build, select_compiler

    try:
        compiler = select_compiler(preference)
    except ToolchainError:
        return Check("compilar y ejecutar", Status.ERROR, "no hay compilador disponible")
    with tempfile.TemporaryDirectory() as tmp:
        source = Path(tmp) / "probe.c"
        source.write_text(PROBE_SOURCE)
        try:
            result = build([source], Path(tmp) / "probe.elf", compiler=compiler)
            machine = Machine.from_elf(result.output)
            stop = machine.debugger.continue_()
        except (ToolchainError, OSError) as exc:
            detail = getattr(exc, "output", "") or str(exc)
            return Check("compilar y ejecutar", Status.ERROR, detail.splitlines()[0])
    if stop.reason is not StopReason.EXITED or stop.exit_code != 42:
        return Check("compilar y ejecutar", Status.ERROR, f"resultado inesperado: {stop}")
    return Check("compilar y ejecutar", Status.OK, "programa de prueba compilado y ejecutado")


def check_terminal() -> list[Check]:
    checks: list[Check] = []
    if not sys.stdout.isatty():
        return [Check("terminal", Status.WARN, "la salida no es una terminal: la TUI no se verá")]
    columns, rows = shutil.get_terminal_size()
    min_cols, min_rows = RECOMMENDED_SIZE
    size_status = Status.OK if columns >= min_cols and rows >= min_rows else Status.WARN
    checks.append(
        Check(
            "tamaño",
            size_status,
            f"{columns}x{rows}"
            + ("" if size_status is Status.OK else f" (se recomienda {min_cols}x{min_rows})"),
        )
    )
    colorterm = os.environ.get("COLORTERM", "")
    term = os.environ.get("TERM", "")
    truecolor = colorterm in ("truecolor", "24bit")
    checks.append(
        Check(
            "colores",
            Status.OK if truecolor else Status.WARN,
            f"TERM={term or '?'} COLORTERM={colorterm or '?'}"
            + ("" if truecolor else " (sin color de 24 bits: los temas se ven aproximados)"),
        )
    )
    checks.append(
        Check(
            "teclas de función",
            Status.WARN,
            "algunas terminales capturan F10/F11 (menú, pantalla completa): usá n/s o "
            "reasignalas en [keys] de config.toml",
        )
    )
    return checks


def run_checks(preference: str | None = None, build: bool = True) -> list[Check]:
    checks = [check_python(), *check_packages(), check_emulator(), check_runtime()]
    checks += [check_config(), check_cache(), *check_compilers(preference)]
    if build:
        checks.append(check_build_and_run(preference))
    checks += check_terminal()
    return checks
