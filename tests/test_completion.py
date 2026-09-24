"""Scripts de autocompletado generados desde el parser."""

from __future__ import annotations

import shutil
import subprocess
import sys

import pytest

from hardboiled.cli.completion import bash_script, build_spec, fish_script, zsh_script


def test_spec_covers_subcommands_and_nested_actions() -> None:
    spec = build_spec()
    assert {"run", "build", "demo", "doctor", "completion"} <= set(spec.children)
    assert set(spec.children["board"].children) == {"init", "show"}
    assert "--headless" in spec.children["run"].options


def test_fish_and_zsh_scripts_mention_commands() -> None:
    fish = fish_script(build_spec())
    assert "complete -c hardboiled" in fish and "-a doctor" in fish
    assert zsh_script(build_spec()).startswith("# Autocompletado de hardboiled para zsh")


# En Windows, el primer bash del PATH suele ser el lanzador de WSL (sin distribución
# en CI), y el autocompletado de bash no se usa en Windows nativo.
@pytest.mark.skipif(
    shutil.which("bash") is None or sys.platform == "win32", reason="requiere bash (Unix)"
)
@pytest.mark.parametrize(
    ("words", "expected"),
    [
        (["hardboiled", "exa"], "examples"),
        (["hardboiled", "ex"], "examples explain"),
        (["hardboiled", "board", ""], "init show"),
        (["hardboiled", "demo", "inter"], "interrupciones"),
        (["hardboiled", "run", "--headl"], "--headless"),
    ],
)
def test_bash_completion(words: list[str], expected: str) -> None:
    script = bash_script(build_spec())
    quoted = " ".join(f"'{w}'" for w in words)
    probe = (
        f"{script}\nCOMP_WORDS=({quoted}); COMP_CWORD={len(words) - 1}; "
        '_hardboiled; echo "${COMPREPLY[*]}"'
    )
    result = subprocess.run(
        ["bash", "-c", probe],
        capture_output=True,
        text=True,
        check=True,
        encoding="utf-8",
        errors="replace",
    )
    assert result.stdout.strip() == expected


def test_bash_script_parses_on_bash_3_2() -> None:
    """macOS trae bash 3.2: extglob en [[ ]] sólo si ya estaba activo al leer la función."""
    script = bash_script(build_spec())
    assert "== @(" not in script
    assert script.index("shopt -s extglob") < script.index("_hardboiled() {")
