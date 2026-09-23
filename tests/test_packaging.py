"""Recursos empaquetados: lo que necesita una instalación con `uv tool install`."""

from __future__ import annotations

import shutil
import subprocess
import zipfile
from pathlib import Path

import pytest

from hardboiled import resources

ROOT = Path(__file__).parents[1]

PACKAGED_FILES = (
    "runtime/crt0.s",
    "runtime/hardboiled.ld",
    "runtime/include/hardboiled.h",
    "data/board.toml",
    "examples/demo.c",
    "examples/hola.c",
    "data/project/main.c",
    "data/project/Makefile",
)


def test_runtime_resources_exist() -> None:
    for path in (resources.crt0_path(), resources.linker_script(), resources.header_path()):
        assert path.is_file(), path
    assert resources.include_dir() == resources.header_path().parent


@pytest.mark.skipif(shutil.which("uv") is None, reason="requiere uv")
def test_wheel_contains_resources(tmp_path: Path) -> None:
    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(tmp_path), str(ROOT)],
        check=True,
        capture_output=True,
    )
    (wheel,) = tmp_path.glob("*.whl")
    names = set(zipfile.ZipFile(wheel).namelist())
    for relative in PACKAGED_FILES:
        assert f"hardboiled/{relative}" in names


def test_packaged_board_matches_repository_board() -> None:
    packaged = resources.default_board_path()
    assert packaged.read_text() == (ROOT / "board.toml").read_text()
