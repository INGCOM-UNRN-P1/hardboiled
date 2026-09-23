"""Prueba de humo de la instalación como herramienta, tal como la hace un alumno.

Construye el wheel, lo instala con `uv tool install "<wheel>[zig]"` en
directorios temporales (sin tocar las herramientas del usuario) y ejecuta el
comando instalado fuera del repositorio: doctor, un ejemplo y un proyecto nuevo.

Uso: uv run python scripts/smoke_install.py
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def run(command: list[str], env: dict[str, str], cwd: Path) -> str:
    print(f"$ {' '.join(command)}", flush=True)
    result = subprocess.run(command, env=env, cwd=cwd, capture_output=True, text=True)
    output = result.stdout + result.stderr
    print(output, end="" if output.endswith("\n") or not output else "\n")
    if result.returncode != 0:
        raise SystemExit(f"falló (código {result.returncode}): {' '.join(command)}")
    return result.stdout


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="hardboiled-smoke-") as tmp:
        base = Path(tmp)
        env = dict(os.environ)
        env.update(
            UV_TOOL_DIR=str(base / "tools"),
            UV_TOOL_BIN_DIR=str(base / "bin"),
            HARDBOILED_CONFIG_DIR=str(base / "config"),
            HARDBOILED_CACHE_DIR=str(base / "cache"),
        )
        env.pop("VIRTUAL_ENV", None)
        env.pop("HARDBOILED_CC", None)
        dist = base / "dist"
        run(["uv", "build", "--wheel", "--out-dir", str(dist), str(ROOT)], env, ROOT)
        (wheel,) = dist.glob("*.whl")
        run(["uv", "tool", "install", f"{wheel}[zig]"], env, base)

        exe = base / "bin" / ("hardboiled.exe" if sys.platform == "win32" else "hardboiled")
        work = base / "work"
        work.mkdir()
        run([str(exe), "--version"], env, work)
        run([str(exe), "doctor"], env, work)
        output = run([str(exe), "demo", "hola", "--headless"], env, work)
        assert output == "Hola, hardboiled!\n", repr(output)
        run([str(exe), "new", "tp"], env, work)
        output = run([str(exe), "run", "main.c", "--headless"], env, work / "tp")
        assert output == "Hola desde tp!\n", repr(output)
    print("instalación verificada")


if __name__ == "__main__":
    main()
