"""Periféricos: MMIO real, máscaras, barrido, IRQ y restauración del estado."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from hardboiled.config import BoardConfig
from hardboiled.hardware.bus import MmioBus
from hardboiled.hardware.external import ExternalPeripheral
from hardboiled.hardware.panel import LcdModel, PwmModel

ALL = 0xFFFFFFFF


def test_scan_irq_release_and_snapshot() -> None:
    raised: list[int] = []
    lowered: list[int] = []
    keypad = ExternalPeripheral(
        "keypad",
        0x50,
        irq_line=3,
        raise_irq=raised.append,
        lower_irq=lowered.append,
        model="keypad_4x4",
    )
    bus = MmioBus(4096)
    bus.attach(keypad)
    bus.write(0x58, 4, 1)
    bus.write(0x50, 4, 1)
    keypad.key(1, 1, True)
    assert bus.read(0x54, 4) == 0 and raised == []
    bus.write(0x50, 1, 2)
    assert bus.read(0x54, 4) == 2 and raised[-1] == 3
    snapshot = keypad.snapshot()
    keypad.key(1, 1, False)
    assert bus.read(0x54, 4) == 0 and lowered[-1] == 3
    keypad.restore(snapshot)
    assert bus.read(0x54, 4) == 2
    keypad.reset()
    assert bus.read(0x54, 4) == 0


def test_lcd_commands_cgram_shift_and_ddram_wrap() -> None:
    lcd = LcdModel()
    lcd.write(0, 0x0F)
    lcd.write(0, 0x06)
    for byte in b"Hola":
        lcd.write(4, byte)
    assert lcd.state()["cells"][0][:4] == list(b"Hola")
    assert lcd.state()["cursor"] and lcd.state()["blink"]
    lcd.write(0, 0xC0)
    lcd.write(4, ord("X"))
    assert lcd.state()["cells"][1][0] == ord("X")
    lcd.write(0, 0x40)
    for row in [0, 10, 10, 0, 17, 14, 0, 0]:
        lcd.write(4, row)
    assert lcd.state()["cgram"][4:6] == [17, 14]
    lcd.write(0, 0x80)
    lcd.write(4, 0)
    assert lcd.state()["cells"][0][0] == 0
    lcd.write(0, 0x18)
    assert lcd.state()["cells"][0][0] == ord("o")
    lcd.write(0, 0x02)
    assert lcd.state()["address"] == 0 and lcd.state()["shift"] == 0
    lcd.write(0, 0xA7)
    lcd.write(4, 65)
    assert lcd.address == 0x40
    lcd.write(0, 0x04)
    lcd.write(4, 66)
    assert lcd.address == 0x27
    lcd.write(0, 0x01)
    assert lcd.state()["cells"] == [[32] * 16] * 2
    lcd.write(0, 8)
    assert not lcd.state()["display"]


def test_lcd_byte_lanes_and_restore() -> None:
    dev = ExternalPeripheral("lcd", 0x60, model="lcd_hd44780")
    bus = MmioBus(4096)
    bus.attach(dev)
    bus.write(0x60, 1, 0x0C)
    bus.write(0x64, 1, ord("A"))
    snap = dev.snapshot()
    bus.write(0x65, 1, 255)
    assert dev.model is not None
    assert dev.model.state()["cells"][0][:2] == [65, 32]
    bus.write(0x60, 1, 1)
    dev.restore(snap)
    assert dev.model.state()["cells"][0][0] == 65
    assert bus.read(0x68, 1) == 1
    dev.reset()
    assert dev.model.state()["display"] is False


def test_pwm_mask_zero_and_saturation() -> None:
    pwm = ExternalPeripheral("rgb", 0x70, model="pwm_rgb")
    assert isinstance(pwm.model, PwmModel)
    pwm.write(4, 1000, ALL)
    assert pwm.model.state()["rgb"] == [0, 0, 0]
    pwm.write(0, 1000, ALL)
    pwm.write(8, 500, ALL)
    pwm.write(12, 2000, ALL)
    assert pwm.model.state()["duty"] == [1, 0.5, 1]
    pwm.write(4, 0, 0xFF)
    assert pwm.read(4) == 768
    assert pwm.model.state()["rgb"] == [196, 128, 255]
    assert pwm.snapshot()["write_log"] == []


@pytest.mark.parametrize(
    "extra",
    [
        {"type": "gpio_out", "external_model": "pwm_rgb"},
        {"type": "external", "external_model": "pwm_rgb", "external_size": 4},
        {"type": "external", "external_model": "no-existe"},
    ],
)
def test_reject_incompatible_configuration(extra: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        BoardConfig.model_validate({"peripherals": [{"name": "bad", "offset": "0x50", **extra}]})
