"""Pruebas de firmware (Ola 21): hardboiled_test.h, contador de ciclos determinista y
controles con `until` en `hardboiled test`."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

from hardboiled import resources
from hardboiled.cli import main
from hardboiled.cli.common import CliError
from hardboiled.cli.test import parse_momento, steps_from_press
from hardboiled.core.pic import CYCLES_HI, CYCLES_LO, InterruptController
from hardboiled.hardware.bus import Clock, MmioFault

needs_zig = pytest.mark.skipif(importlib.util.find_spec("ziglang") is None, reason="requiere [zig]")

FIRMWARE_CON_LAZO = """\
#include "hardboiled.h"

static void on_button(void)
{
    buttons_clear(1u);
    led_toggle(3);
    uart_puts("presionado\\n");
}

int main(void)
{
    led_set(0);
    attach_irq(IRQ_BUTTONS, on_button);
    button_irq_enable(1u);
    interrupts_enable();
    for (;;) {
        wait_for_interrupt();
    }
}
"""

SUITE = """\
[[case]]
name = "una pulsación"
until_cycle = 200000
[[case.at]]
cycle = 50000
press = [0]
[[case.check]]
cycle = 40000
leds = 0b0000
[[case.check]]
cycle = 120000
leds = 0b1000
uart_contains = ["presionado"]

[[case]]
name = "control que falla"
until_cycle = 100000
[[case.check]]
cycle = 90000
leds = 0b1000
"""


def test_el_pic_expone_los_ciclos_de_solo_lectura() -> None:
    pic = InterruptController()
    pic.clock = Clock()
    pic.clock.cycles = (3 << 32) | 0x1234
    assert pic.read(CYCLES_LO) == 0x1234 and pic.read(CYCLES_HI) == 3
    with pytest.raises(MmioFault):
        pic.write(CYCLES_LO, 0, 0xFFFF_FFFF)


def test_parse_momento_y_press() -> None:
    assert parse_momento("20000") == (20000, None) and parse_momento("5ms") == (None, 5.0)
    (paso,) = steps_from_press(["1@3ms"])
    assert paso.press == [1] and paso.ms == 3.0
    with pytest.raises(CliError):
        steps_from_press(["a@100"])
    with pytest.raises(CliError):
        parse_momento("pronto")


def test_el_header_de_pruebas_esta_en_el_runtime() -> None:
    texto = (resources.include_dir() / "hardboiled_test.h").read_text(encoding="utf-8")
    assert "HB_ASSERT_PULLUP" in texto and "hb_test_fin" in texto and "hb_cycles()" in texto


@needs_zig
def test_hardboiled_test_h_con_el_ejemplo(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("HARDBOILED_CC", "zig")
    ejemplo = Path(__file__).parents[1] / "src" / "hardboiled" / "examples" / "pruebas.c"
    assert main(["test", str(ejemplo), "--press", "0@20000", "--expect-exit", "0", "--json"]) == 0
    capsys.readouterr()
    # Sin el botón, la prueba que lo espera falla y el programa sale con 1.
    assert main(["test", str(ejemplo), "--expect-exit", "0", "--json"]) == 1
    (caso,) = json.loads(capsys.readouterr().out)["cases"]
    assert (
        "FALLA pruebas.c:" in caso["uart"]
        and "se esperaba pulsaciones > 0u en 200000 ciclos" in caso["uart"]
    )
    assert "4 pruebas, 1 falla" in caso["uart"]


@needs_zig
def test_controles_y_until_son_deterministas(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("HARDBOILED_CC", "zig")
    (tmp_path / "firmware.c").write_text(FIRMWARE_CON_LAZO, encoding="utf-8")
    (tmp_path / "casos.toml").write_text(SUITE, encoding="utf-8")
    corridas = []
    for _ in range(2):
        assert (
            main(
                [
                    "test",
                    str(tmp_path / "firmware.c"),
                    "--suite",
                    str(tmp_path / "casos.toml"),
                    "--json",
                ]
            )
            == 1
        )
        corridas.append(json.loads(capsys.readouterr().out))
    assert corridas[0] == corridas[1]
    una, falla = corridas[0]["cases"]
    assert (
        una["passed"]
        and una["outcome"] == "until"
        and una["cycles"] == 200000
        and una["checks"] == 2
    )
    assert not falla["passed"] and falla["failures"] == [
        "a los 90,000 ciclos (90 ms) los LEDs estaban en 0b00000000, se esperaba 0b00001000"
    ]


@needs_zig
def test_hasta_sin_suite(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.setenv("HARDBOILED_CC", "zig")
    (tmp_path / "firmware.c").write_text(FIRMWARE_CON_LAZO, encoding="utf-8")
    assert (
        main(["test", str(tmp_path / "firmware.c"), "--press", "0@50ms", "--hasta", "200ms", "-q"])
        == 0
    )
    # Sin --hasta, el lazo infinito termina en un wfi sin nada que lo despierte: falla.
    assert main(["test", str(tmp_path / "firmware.c"), "-q"]) == 1


PLACA_GPIO = """\
[board]
name = "placa-gpio"

[[peripherals]]
name = "uart0"
type = "uart"
offset = "0x10"

[[peripherals]]
name = "gpio"
type = "gpio"
offset = "0x100"
width_bits = 8
irq_line = 4
"""

PRUEBA_PULL_UP = """\
#include "hardboiled.h"
#include "hardboiled_test.h"

static volatile uint32_t flancos;

static void on_gpio(void)
{
    GPIO_PENDING = 1u << 2;
    flancos++;
}

HB_TEST(pull_up_e_interrupcion)
{
    GPIO_DIR = GPIO_DIR & ~(1u << 2);
    gpio_pullup(1u << 2, 1);
    HB_ASSERT_PULLUP(GPIO_PULL, 2);
    HB_ASSERT_BITS_SET(GPIO_IN, 1u << 2);
    attach_irq(IRQ_GPIO, on_gpio);
    gpio_irq_enable(1u << 2, 1);
    interrupts_enable();
    HB_ASSERT_IRQ_ENABLED(IRQ_GPIO);
    HB_ESPERAR(flancos == 1u, 100000);
}

HB_TEST(falla_con_valores)
{
    HB_ASSERT_REG_EQ(GPIO_PULL, 0x80);
}

int main(void)
{
    HB_RUN(pull_up_e_interrupcion);
    HB_RUN(falla_con_valores);
    return hb_test_fin();
}
"""


@needs_zig
def test_hardboiled_test_h_con_una_placa_propia(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    """Con un board.toml propio el SDK va a la caché: hardboiled_test.h también tiene que estar."""
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "board.toml").write_text(PLACA_GPIO, encoding="utf-8")
    (tmp_path / "main.c").write_text(PRUEBA_PULL_UP, encoding="utf-8")
    (tmp_path / "guion.toml").write_text(
        "[[at]]\ncycle = 30000\ngpio_low = [2]\n", encoding="utf-8"
    )
    assert main(["run", "main.c", "--headless", "--cc", "zig", "--script", "guion.toml"]) == 1
    salida = capsysbinary.readouterr().out.decode()
    assert "[ ok  ] pull_up_e_interrupcion" in salida
    assert (
        "FALLA main.c:" in salida
        and "GPIO_PULL == 0x80 (obtenido 0x00000004, esperado 0x00000080)" in salida
    )
    assert "2 pruebas, 1 falla" in salida


async def test_los_botones_se_aprietan_con_alt_y_el_numero() -> None:
    """Antes los botones sólo se apretaban con el mouse; los switches ya tenían 0-7."""
    import queue

    from hardboiled.core.events import CmdPressButton, CmdToggleSwitch, Command, Event
    from hardboiled.ui.tui import HardboiledApp

    comandos: queue.Queue[Command] = queue.Queue()
    eventos: queue.Queue[Event] = queue.Queue()
    app = HardboiledApp(comandos, eventos)
    async with app.run_test() as pilot:
        await pilot.press("alt+2")
        await pilot.press("3")
        await pilot.pause()
    recibidos = []
    while not comandos.empty():
        recibidos.append(comandos.get())
    assert any(isinstance(c, CmdPressButton) and c.pin_index == 2 for c in recibidos)
    assert any(isinstance(c, CmdToggleSwitch) and c.pin_index == 3 for c in recibidos)


def test_los_botones_se_pueden_reasignar() -> None:
    from hardboiled.ui.tui import KEY_ACTIONS

    assert {f"button_{n}" for n in range(8)} <= KEY_ACTIONS
