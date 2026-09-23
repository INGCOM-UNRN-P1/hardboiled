"""Temas y modo para daltonismo."""

from __future__ import annotations

from hardboiled.core.events import PeripheralInfo
from hardboiled.ui.palette import DARK, LIGHT, palette_for
from hardboiled.ui.tui import HardboiledApp
from hardboiled.ui.widgets.hardware_view import LedBarView
from hardboiled.userconfig import UiPrefs
from tests.conftest import Harness


def test_palette_selection() -> None:
    assert palette_for("dark", False) is DARK
    assert palette_for("light", False) is LIGHT
    colorblind = palette_for("dark", True)
    assert (colorblind.led_on, colorblind.led_off) == ("■", "□")  # forma, no sólo color
    assert "underline" in colorblind.changed
    assert "red" not in colorblind.breakpoint


async def test_light_and_colorblind_app() -> None:
    h = Harness("mmio")
    app = HardboiledApp(h.cmd, h.evt, h.runner, UiPrefs(theme="light", colorblind=True))
    async with app.run_test(size=(140, 45)) as pilot:
        for _ in range(100):
            await pilot.pause(0.02)
            if app._suspended is not None:
                break
        assert app.theme == "textual-light"
        led = app.query_one(LedBarView)
        led.set_value(0b1)
        assert "■" in led.render().plain and "□" in led.render().plain
        await pilot.press("q")


def test_led_view_defaults_to_dark_outside_app() -> None:
    view = LedBarView(PeripheralInfo("leds", "gpio_out", 0, 4))
    view.value = 0b0101
    assert view.render().plain.count("●") == 2
