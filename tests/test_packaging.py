"""Recursos empaquetados: lo que necesita una instalación con `uv tool install`."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from hardboiled import resources

ROOT = Path(__file__).parents[1]

RUNTIME_FILES = ("runtime/crt0.s", "runtime/hardboiled.ld", "runtime/include/hardboiled.h")


def test_runtime_resources_exist() -> None:
    for path in (resources.crt0_path(), resources.linker_script(), resources.header_path()):
        assert path.is_file(), path
    assert resources.include_dir() == resources.header_path().parent


@pytest.mark.skipif(shutil.which("uv") is None, reason="requiere uv")
def test_wheel_contains_runtime(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(ROOT)],
        check=True,
        capture_output=True,
    )
    (wheel,) = tmp_path.glob("*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    for relative in RUNTIME_FILES:
        assert f"hardboiled/{relative}" in names
