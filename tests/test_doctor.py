"""`hardboiled doctor`."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from hardboiled import doctor
from hardboiled.cli import main
from hardboiled.doctor import Status


@pytest.fixture(autouse=True)
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARDBOILED_CONFIG_DIR", str(tmp_path / "conf"))
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path / "cache"))


def test_core_checks_pass() -> None:
    assert doctor.check_python().status is Status.OK
    assert doctor.check_emulator().status is Status.OK
    assert doctor.check_runtime().status is Status.OK
    assert doctor.check_config().status is Status.OK
    assert doctor.check_cache().status is Status.OK


def test_invalid_config_is_reported(tmp_path: Path) -> None:
    (tmp_path / "conf").mkdir()
    (tmp_path / "conf" / "config.toml").write_text("[ui]\ntheme = 3\n")
    assert doctor.check_config().status is Status.ERROR


def test_missing_compiler_is_an_error(monkeypatch: pytest.MonkeyPatch) -> None:
    from hardboiled import toolchain

    monkeypatch.delenv("HARDBOILED_CC", raising=False)
    monkeypatch.setattr(toolchain, "find_compilers", lambda: [])
    statuses = {check.name: check.status for check in doctor.check_compilers(None)}
    assert statuses == {"compiladores": Status.ERROR, "compilador elegido": Status.ERROR}


@pytest.mark.skipif(importlib.util.find_spec("ziglang") is None, reason="requiere [zig]")
def test_doctor_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["doctor", "--cc", "zig"]) == 0
    out = capsys.readouterr().out
    assert "✔ compilar y ejecutar" in out
    assert "0 error(es)" in out
