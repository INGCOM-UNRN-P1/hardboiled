"""ADC multicanal con potenciómetros (qol.md #64)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

from hardboiled.config import BoardConfig
from hardboiled.core.cpu import StopReason
from hardboiled.core.machine import Machine
from hardboiled.hardware.adc import (
    CTRL,
    CTRL_IRQ,
    CTRL_START,
    DATA,
    INFO,
    POT_BASE,
    STATUS,
    STATUS_BUSY,
    STATUS_DONE,
    Adc,
)
from hardboiled.hardware.bus import Clock, MmioFault
from hardboiled.script import ScriptError, ScriptPlayer, load_script
from hardboiled.sdk import generate_header, runtime_for
from hardboiled.toolchain import BuildOptions, build, select_compiler

ALL = 0xFFFF_FFFF


def make_adc(**kwargs: int) -> tuple[Adc, list[int], list[int]]:
    raised: list[int] = []
    lowered: list[int] = []
    adc = Adc("adc0", 0x80, irq_line=4, raise_irq=raised.append, lower_irq=lowered.append, **kwargs)
    adc.clock = Clock()
    return adc, raised, lowered


def test_conversion_con_muestreo_y_retencion() -> None:
    adc, _, _ = make_adc(conversion_cycles=50)
    adc.set_millivolts(1, 1650)
    adc.write(CTRL, 1 | CTRL_START, ALL)
    assert adc.read(STATUS) == STATUS_BUSY and adc.next_deadline() == 50
    adc.set_millivolts(1, 0)  # girarlo durante la conversión no cambia lo muestreado
    adc.clock.cycles = 50
    adc.service(50)
    assert adc.read(STATUS) == STATUS_DONE and adc.read(DATA) == 512  # 1650 / 3300 de 1023
    assert adc.read(CTRL) == 1 and adc.conversions == 1
    adc.write(STATUS, STATUS_DONE, ALL)  # write-1-to-clear
    assert adc.read(STATUS) == 0 and adc.read(DATA) == 512


def test_resolucion_saturacion_e_info() -> None:
    adc, _, _ = make_adc(resolution_bits=12, channels=2, vref_mv=5000)
    assert adc.read(INFO) == 12 | 2 << 8 and adc.max_code == 4095
    assert adc.code_for(5000) == 4095 and adc.code_for(-10) == 0 and adc.code_for(9999) == 4095
    adc.nudge(0, 200)  # girar de más se queda en el tope
    assert adc.millivolts[0] == 5000
    adc.nudge(0, -30)
    assert adc.millivolts[0] == 3500
    with pytest.raises(ValueError):
        adc.set_millivolts(2, 100)
    with pytest.raises(MmioFault, match="canal"):
        adc.write(CTRL, 3 | CTRL_START, ALL)
    with pytest.raises(MmioFault):
        adc.write(DATA, 1, ALL)


def test_irq_al_terminar_y_reset() -> None:
    adc, raised, lowered = make_adc(conversion_cycles=10)
    adc.write(CTRL, 2 | CTRL_START | CTRL_IRQ, ALL)
    assert raised == []
    adc.clock.cycles = 10
    adc.service(10)
    assert raised == [4]
    adc.write(STATUS, STATUS_DONE, ALL)
    assert lowered[-1] == 4
    adc.set_millivolts(3, 3300)
    adc.reset()  # la posición de los potenciómetros es física
    assert adc.millivolts[3] == 3300 and adc.read(STATUS) == 0 and adc.read(DATA) == 0


def test_placa_sdk_y_guion(tmp_path: Path) -> None:
    board = BoardConfig.model_validate(
        {"peripherals": [{"name": "adc0", "type": "adc", "offset": "0x80", "resolution_bits": 12}]}
    )
    header = generate_header(board)
    for texto in ("ADC_CTRL", "ADC_DATA", "#define ADC_MAX 4095u", "adc_read", "ADC_CTRL_START"):
        assert texto in header
    with pytest.raises(ValidationError, match="son opciones del adc"):
        BoardConfig.model_validate(
            {"peripherals": [{"name": "t", "type": "timer", "offset": "0x20", "channels": 2}]}
        )
    guion = tmp_path / "entrada.toml"
    guion.write_text("[[at]]\ncycle = 10\nadc = [[0, 1650], [3, 100]]\n", encoding="utf-8")
    assert load_script(guion).at[0].describe() == "adc 0 = 1650 mV; adc 3 = 100 mV"
    sin_adc = Machine.from_elf(Path(__file__).parent / "fixtures" / "hwloop.elf")
    with pytest.raises(ScriptError, match="no tiene ADC"):
        ScriptPlayer(sin_adc, load_script(guion), None)


async def test_vista_de_los_potenciometros() -> None:
    from textual.app import App, ComposeResult
    from textual.widgets import Static

    from hardboiled.core.events import PeripheralInfo
    from hardboiled.ui.widgets.hardware_view import AdcView, HardwareView

    recibidos: list[AdcView.Turned] = []

    class AdcApp(App[None]):
        def compose(self) -> ComposeResult:
            yield HardwareView()

        def on_adc_view_turned(self, message: AdcView.Turned) -> None:
            recibidos.append(message)

    app = AdcApp()
    async with app.run_test(size=(120, 20)) as pilot:
        vista = app.query_one(HardwareView)
        vista.configure((PeripheralInfo("adc0", "adc", 0x80, 10, channels=2),))
        await pilot.pause()
        vista.update_device("adc0", POT_BASE + 4, 1650)
        await pilot.pause()
        barra = app.query_one("#adc-barra-1", Static)
        assert "1650 mV" in str(barra.render())
        await pilot.click("#adc-mas-1")
        await pilot.click("#adc-menos-0")
        await pilot.pause()
        assert [(m.device, m.channel, m.percent) for m in recibidos] == [
            ("adc0", 1, 5),
            ("adc0", 0, -5),
        ]


@pytest.mark.skipif(importlib.util.find_spec("ziglang") is None, reason="requiere [zig]")
def test_firmware_lee_por_sondeo_y_por_irq(tmp_path: Path) -> None:
    board = BoardConfig.model_validate(
        {
            "peripherals": [
                {"name": "uart0", "type": "uart", "offset": "0x10", "irq_line": 1},
                {"name": "adc0", "type": "adc", "offset": "0x80", "irq_line": 4},
            ]
        }
    )
    fuente = tmp_path / "pote.c"
    fuente.write_text(
        """#include "hardboiled.h"

static volatile int listo = 0;
static volatile uint32_t por_irq = 0;

static void al_convertir(void)
{
    por_irq = adc_value();  /* limpia DONE y retira la IRQ */
    listo = 1;
}

int main(void)
{
    for (volatile int i = 0; i < 5000; i++) {  /* el guion gira los potenciómetros */
    }
    uint32_t por_sondeo = adc_read(1);
    attach_irq(IRQ_ADC0, al_convertir);
    interrupts_enable();
    adc_start(0, 1);
    while (!listo) {
        wait_for_interrupt();
    }
    uart_puthex(por_sondeo);
    uart_putc(' ');
    uart_puthex(por_irq);
    return (int)adc_to_mv(por_irq) / 1000;
}
""",
        encoding="utf-8",
    )
    options = BuildOptions(runtime=runtime_for(board, tmp_path / "cache"))
    elf = build([fuente], tmp_path / "pote.elf", options, select_compiler("zig")).output
    machine = Machine.from_elf(elf, board)
    guion = tmp_path / "entrada.toml"
    guion.write_text("[[at]]\ncycle = 1000\nadc = [[1, 825], [0, 3300]]\n", encoding="utf-8")
    machine.bus.add_source(ScriptPlayer(machine, load_script(guion), None))
    machine.cpu.refresh_deadline()
    stop = machine.debugger.continue_()
    uart = machine.uart()
    # 825 mV de 3300 en 10 bits: 256 (0x100); 3300 mV: 1023 (0x3ff), que son 3300 mV -> sale con 3.
    assert uart is not None and bytes(uart.transmitted) == b"0x00000100 0x000003ff"
    assert stop.reason is StopReason.EXITED and stop.exit_code == 3
