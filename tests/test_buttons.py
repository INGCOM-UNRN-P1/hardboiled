"""Botones pulsadores con interrupción."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from hardboiled import resources
from hardboiled.core.cpu import StopReason
from hardboiled.core.machine import Machine
from hardboiled.hardware.bus import Clock
from hardboiled.hardware.buttons import ButtonBank
from hardboiled.toolchain import build, select_compiler


def make_bank(hold: int = 100) -> tuple[ButtonBank, list[int], list[int]]:
    raised: list[int] = []
    lowered: list[int] = []
    bank = ButtonBank("b", 0x30, 4, 2, raised.append, lowered.append, hold_cycles=hold)
    bank.clock = Clock()
    return bank, raised, lowered


def test_press_latches_edge_and_releases_after_hold() -> None:
    bank, raised, lowered = make_bank()
    bank.write(0x4, 0b0010, 0xFFFFFFFF)  # IRQ del botón 1
    bank.press(1)
    assert bank.read(0x0) == 0b0010 and bank.read(0xC) == 0b0010
    assert raised == [2]
    assert bank.next_deadline() == 100
    bank.service(100)
    assert bank.read(0x0) == 0  # se soltó solo
    assert bank.read(0xC) == 0b0010  # el flanco sigue pendiente
    bank.write(0xC, 0b0010, 0xFFFFFFFF)  # limpiar
    assert lowered[-1] == 2 and bank.read(0xC) == 0


def test_falling_edge_and_disabled_buttons() -> None:
    bank, raised, lowered = make_bank()
    bank.write(0x8, 0b0001, 0xFFFFFFFF)  # botón 0: avisa al soltar
    bank.write(0x4, 0b0001, 0xFFFFFFFF)
    bank.press(0)
    assert bank.read(0xC) == 0 and raised == []
    bank.service(100)
    assert bank.read(0xC) == 0b0001 and raised == [2]
    bank.press(3)  # sin IRQ habilitada: queda pendiente
    assert bank.read(0xC) == 0b1001
    lowered.clear()
    bank.write(0xC, 0b0001, 0xFFFFFFFF)  # limpiar el 0: la línea baja aunque el 3 siga
    assert lowered == [2] and bank.read(0xC) == 0b1000
    with pytest.raises(ValueError):
        bank.press(4)


@pytest.mark.skipif(importlib.util.find_spec("ziglang") is None, reason="requiere [zig]")
def test_buttons_example_counts_presses(tmp_path: Path) -> None:
    elf = build(
        [resources.example_path("botones")], tmp_path / "b.elf", compiler=select_compiler("zig")
    ).output
    machine = Machine.from_elf(elf)
    debugger = machine.debugger
    debugger.run_to_main()
    bank = machine.buttons()
    uart = machine.uart()
    assert bank is not None and uart is not None
    machine.cpu.interactive = True
    presses = iter(range(5))

    def poll() -> bool:
        # Un "usuario" que aprieta un botón cada vez que la CPU consulta comandos.
        if bank.state == 0:
            pin = next(presses, None)
            if pin is not None:
                bank.press(pin % 4)
                machine.cpu.refresh_deadline()
        return False

    machine.cpu.poll = poll
    stop = debugger.continue_()
    assert stop.reason is StopReason.EXITED and stop.exit_code == 5
    assert bytes(uart.transmitted).count("pulsación".encode()) == 5
