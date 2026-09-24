"""Salida --json de info, run --headless, test y doctor."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from hardboiled.cli import EXIT_TRAP, EXIT_USAGE, main
from tests.conftest import fixture_path


def run_json(capsys: pytest.CaptureFixture[str], argv: list[str]) -> tuple[int, Any]:
    code = main(argv)
    return code, json.loads(capsys.readouterr().out)


def test_info_json(capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(capsys, ["info", str(fixture_path("basic.elf")), "--json"])
    assert code == 0
    assert data["entry"] == 0x10000 and data["main"] is not None
    assert {"name", "address", "size"} <= set(data["functions"][0])
    assert "square" in {f["name"] for f in data["functions"]}
    assert any(Path(source).parts[-2:] == ("fixtures", "basic.c") for source in data["sources"])
    assert data["build"]["has_debug"] and not data["build"]["optimized"]
    assert data["usage"]["flash_used"] > 0


def test_run_headless_json_exit(capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(
        capsys,
        ["run", str(fixture_path("mmio.elf")), "--headless", "--json", "--switches", "5"],
    )
    assert code == 503 & 0xFF
    assert data["outcome"] == "exited" and data["exit_code"] == 503
    assert data["uart"] == "hola\n0x00000005\n"
    assert data["trap"] is None and data["instructions"] > 0


def test_run_headless_json_trap(capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(
        capsys, ["run", str(fixture_path("traps.elf")), "--headless", "--json", "--switches", "3"]
    )
    assert code == EXIT_TRAP
    trap = data["trap"]
    assert data["outcome"] == "trap" and trap["kind"] == "stack-overflow"
    assert trap["source_file"].endswith("traps.c") and trap["hint"]
    assert len(trap["backtrace"]) > 3  # recursión
    code, data = run_json(
        capsys, ["run", str(fixture_path("traps.elf")), "--headless", "--json", "--switches", "11"]
    )
    assert [w["kind"] for w in data["warnings"]] == ["div0"]


def test_json_requires_headless(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", str(fixture_path("basic.elf")), "--json"]) == EXIT_USAGE
    assert "--headless" in capsys.readouterr().err


def test_test_json(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(
        capsys,
        ["test", str(fixture_path("traps.elf")), "--switches", "1", "--expect-exit", "0", "--json"],
    )
    assert code == 1
    assert data["passed"] == 0 and data["total"] == 1
    case = data["cases"][0]
    assert case["outcome"] == "trap" and case["trap"] == "null-pointer"
    assert case["failures"][0].startswith("el programa no terminó")


def test_doctor_json(capsys: pytest.CaptureFixture[str]) -> None:
    code, data = run_json(capsys, ["doctor", "--no-build", "--json"])
    assert code in (0, 1)
    names = {check["name"] for check in data["checks"]}
    assert {"Python", "hardboiled", "emulador"} <= names
    assert {check["status"] for check in data["checks"]} <= {"ok", "warn", "error"}
    assert data["errors"] == sum(c["status"] == "error" for c in data["checks"])
