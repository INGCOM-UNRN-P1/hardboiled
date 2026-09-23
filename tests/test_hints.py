"""Pistas y guía de trampas y avisos."""

from __future__ import annotations

import pytest

from hardboiled.cli import EXIT_USAGE, main
from hardboiled.core.hints import HINTS, explain
from tests.conftest import MachineFactory, fixture_path


def test_every_kind_has_a_guide_section() -> None:
    for kind in HINTS:
        section = explain(kind)
        assert section is not None and section.startswith("## "), kind


@pytest.mark.parametrize(
    ("selector", "kind"),
    [
        (1, "null-pointer"),
        (2, "flash-write"),
        (3, "stack-overflow"),
        (5, "mmio"),
        (7, "unmapped"),
        (8, "wfi-deadlock"),
        (9, "bad-jump"),
        (10, "misaligned"),
    ],
)
def test_traps_have_a_kind_with_hint(
    make_machine: MachineFactory, selector: int, kind: str
) -> None:
    machine, _ = make_machine("traps", switches=selector)
    stop = machine.debugger.continue_()
    assert stop.kind == kind and kind in HINTS


def test_explain_command(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["explain"]) == 0
    assert "null-pointer" in capsys.readouterr().out
    assert main(["explain", "stack-overflow"]) == 0
    assert "Recursión sin caso base" in capsys.readouterr().out
    assert main(["explain", "nada"]) == EXIT_USAGE


def test_headless_prints_hint(capsys: pytest.CaptureFixture[str]) -> None:
    main(["run", str(fixture_path("traps.elf")), "--headless", "--switches", "1"])
    assert "pista: ¿El puntero se inicializó?" in capsys.readouterr().err
