"""`hardboiled new`: proyecto listo para compilar y para el editor."""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
from pathlib import Path

import pytest

from hardboiled import resources
from hardboiled.cli import EXIT_USAGE, main


def test_new_project_files(tmp_path: Path) -> None:
    project = tmp_path / "mi proyecto"
    assert main(["new", str(project)]) == 0
    for name in ("main.c", "Makefile", ".gitignore", "compile_flags.txt", "board.toml"):
        assert (project / name).is_file(), name
    assert "mi_proyecto" in (project / "main.c").read_text()
    assert "TARGET  := mi_proyecto.elf" in (project / "Makefile").read_text()
    flags = (project / "compile_flags.txt").read_text()
    assert f"-I{resources.include_dir()}" in flags
    assert main(["new", str(project)]) == EXIT_USAGE  # no pisa sin --force


def test_new_from_example_and_editor_only(tmp_path: Path) -> None:
    assert main(["new", str(tmp_path), "--example", "interrupciones", "--no-board"]) == 0
    assert "on_tick" in (tmp_path / "main.c").read_text()
    assert not (tmp_path / "board.toml").exists()
    (tmp_path / "compile_flags.txt").write_text("viejo\n")
    assert main(["new", str(tmp_path), "--editor-only"]) == 0
    assert "--target=riscv32" in (tmp_path / "compile_flags.txt").read_text()


@pytest.mark.skipif(importlib.util.find_spec("ziglang") is None, reason="requiere [zig]")
def test_new_project_builds_and_runs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path / "cache"))
    assert main(["new", str(tmp_path / "p")]) == 0
    monkeypatch.chdir(tmp_path / "p")
    capsysbinary.readouterr()
    assert main(["run", "main.c", "--headless", "--cc", "zig"]) == 0
    assert capsysbinary.readouterr().out == b"Hola desde p!\n"


@pytest.mark.skipif(shutil.which("clangd") is None, reason="requiere clangd")
def test_compile_flags_satisfy_clangd(tmp_path: Path) -> None:
    assert main(["new", str(tmp_path)]) == 0
    check = subprocess.run(
        ["clangd", "--check=main.c"], cwd=tmp_path, capture_output=True, text=True
    )
    assert "All checks completed, 0 errors" in check.stderr
