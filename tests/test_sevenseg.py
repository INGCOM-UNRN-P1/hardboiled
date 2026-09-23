"""Display de 7 segmentos."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from hardboiled import resources
from hardboiled.core.cpu import StopReason
from hardboiled.core.machine import Machine
from hardboiled.hardware.sevenseg import SevenSegment
from hardboiled.toolchain import build, select_compiler
from hardboiled.ui.widgets.hardware_view import render_digits


def test_register_bytes_and_unused_digits() -> None:
    display = SevenSegment("d", 0x40, digits=6)
    display.write(0x0, 0x3F, 0xFF)  # byte 0: dígito 0
    display.write(0x0, 0x06 << 8, 0xFF00)  # byte 1: dígito 1
    display.write(0x4, 0xFFFFFFFF, 0xFFFFFFFF)  # sólo existen los dígitos 4 y 5
    assert display.segments() == [0x3F, 0x06, 0, 0, 0xFF, 0xFF]
    assert display.read(0x4) == 0xFFFF


def test_render_digits_draws_segments_and_point() -> None:
    rows = render_digits([0x3F, 0x06 | 0x80])  # "1." a la izquierda, "0" a la derecha
    assert rows == ["     _  ", "  | | | ", "  |.|_| "]


@pytest.mark.skipif(importlib.util.find_spec("ziglang") is None, reason="requiere [zig]")
def test_display_example(tmp_path: Path) -> None:
    elf = build(
        [resources.example_path("display")], tmp_path / "d.elf", compiler=select_compiler("zig")
    ).output
    machine = Machine.from_elf(elf)
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.EXITED and stop.exit_code == 20
    display = next(d for d in machine.peripherals if isinstance(d, SevenSegment))
    # BEEF con el punto en la F: E=0x79, E, B=0x7C, F=0x71|0x80.
    assert display.segments() == [0x71 | 0x80, 0x79, 0x79, 0x7C]
