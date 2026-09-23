"""Preferencias del usuario (config.toml) y `hardboiled config`."""

from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from hardboiled.cli import EXIT_USAGE, main
from hardboiled.userconfig import TEMPLATE, UserConfig, config_path, load_user_config


@pytest.fixture(autouse=True)
def config_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setenv("HARDBOILED_CONFIG_DIR", str(tmp_path / "conf"))
    return tmp_path / "conf"


def test_missing_file_gives_defaults() -> None:
    assert load_user_config() == UserConfig()


def test_template_is_valid_and_all_commented(config_dir: Path) -> None:
    config_dir.mkdir()
    config_path().write_text(TEMPLATE)
    assert load_user_config() == UserConfig()


def test_values_are_loaded(config_dir: Path) -> None:
    config_dir.mkdir()
    config_path().write_text(
        '[build]\ncompiler = "zig"\nopt_level = "1"\n[ui]\ntheme = "light"\n'
        '[keys]\nstep_over = "f8"\n'
    )
    config = load_user_config()
    assert config.build.compiler == "zig" and config.build.opt_level == "1"
    assert config.ui.theme == "light"
    assert config.keys == {"step_over": "f8"}


def test_invalid_config_is_a_clean_cli_error(
    config_dir: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    config_dir.mkdir()
    config_path().write_text('[ui]\ntheme = "violeta"\n')
    assert main(["runtime"]) == EXIT_USAGE
    assert "ui.theme" in capsys.readouterr().err


def test_config_commands(config_dir: Path, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["config", "path"]) == 0
    assert capsys.readouterr().out.strip() == str(config_dir / "config.toml")
    assert main(["config", "init"]) == 0
    assert config_path().read_text() == TEMPLATE
    assert main(["config", "init"]) == EXIT_USAGE
    assert main(["config"]) == 0
    assert "theme = 'dark'" in capsys.readouterr().out


def test_build_preferences_apply(config_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from hardboiled.cli import build as build_cli

    config_dir.mkdir()
    config_path().write_text('[build]\ncompiler = "zig"\nmarch = "rv32im"\n')
    monkeypatch.delenv("HARDBOILED_CC", raising=False)
    args = argparse.Namespace(
        cc=None,
        opt_level=None,
        march=None,
        defines=[],
        include_dirs=[],
        cflags="",
        user_config=load_user_config(),
    )
    assert build_cli.compiler_preference(args) == "zig"
    assert build_cli.options_from(args).march == "rv32im"
    args.cc = "gcc"
    args.march = "rv32i"
    assert build_cli.compiler_preference(args) == "gcc"  # la línea de comandos gana
    assert build_cli.options_from(args).march == "rv32i"
