"""GPIO bidireccional con pull-ups, IRQ por pin y cortocircuitos (qol.md #69)."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

from hardboiled.config import BoardConfig
from hardboiled.core.cpu import StopReason
from hardboiled.core.events import Event, EvtMessage
from hardboiled.core.machine import Machine
from hardboiled.hardware.bus import Clock, MmioFault
from hardboiled.hardware.gpio_port import DIR, EDGE, IN, IRQ_EN, OUT, PENDING, PULL, SHORT, GpioPort
from hardboiled.script import ScriptError, ScriptPlayer, load_script
from hardboiled.sdk import generate_header, runtime_for
from hardboiled.toolchain import BuildOptions, build, select_compiler

ALL = 0xFFFF_FFFF


def make_port() -> tuple[GpioPort, list[int], list[int], list[Event]]:
    raised: list[int] = []
    lowered: list[int] = []
    events: list[Event] = []
    port = GpioPort("gpio", 0x60, 8, 3, raised.append, lowered.append)
    port.clock = Clock()
    port.emit = events.append
    return port, raised, lowered, events


def test_salidas_entradas_pull_up_y_pines_sueltos() -> None:
    port, _, _, _ = make_port()
    assert port.read(IN) == 0  # todo entrada y suelto, sin pull-up
    port.write(PULL, 0b0000_0011, ALL)
    assert port.read(IN) == 0b0000_0011  # sueltas con pull-up leen 1
    port.drive(0, 0)  # un botón a masa apretado
    assert port.read(IN) == 0b0000_0010
    port.write(DIR, 0b1000_0000, ALL)
    port.write(OUT, 0b1000_0000, ALL)
    assert port.read(IN) == 0b1000_0010  # las salidas también se leen en IN
    port.drive(0, None)
    assert port.read(IN) == 0b1000_0011


def test_irq_por_flanco_de_cada_pin() -> None:
    port, raised, lowered, _ = make_port()
    port.write(IRQ_EN, 0b0011, ALL)
    port.write(EDGE, 0b0010, ALL)  # pin 0 en subida, pin 1 en bajada
    port.drive(0, 1)
    assert port.read(PENDING) == 0b0001 and raised == [3]
    port.drive(1, 1)  # subida en un pin que avisa en bajada: nada
    assert port.read(PENDING) == 0b0001
    port.drive(1, 0)
    assert port.read(PENDING) == 0b0011
    port.write(PENDING, 0b0011, ALL)  # write-1-to-clear
    assert port.read(PENDING) == 0 and lowered[-1] == 3
    port.drive(5, 1)  # sin IRQ habilitada queda pendiente, sin pedir la línea
    assert port.read(PENDING) == 0b10_0000 and lowered[-1] == 3


def test_cortocircuito_entre_una_salida_y_un_nivel_de_afuera() -> None:
    port, _, _, events = make_port()
    port.drive(2, 0)
    port.write(DIR, 0b0100, ALL)
    port.write(OUT, 0b0100, ALL)  # el programa saca 1 donde afuera hay 0
    assert port.read(SHORT) == 0b0100
    avisos = [e for e in events if isinstance(e, EvtMessage)]
    assert len(avisos) == 1 and "cortocircuito en el pin 2" in avisos[0].text
    port.write(OUT, 0b0000_0100, ALL)  # sigue igual: no se repite el aviso
    assert len([e for e in events if isinstance(e, EvtMessage)]) == 1
    port.write(OUT, 0, ALL)  # ahora coinciden
    assert port.read(SHORT) == 0


def test_estimulos_reset_y_errores() -> None:
    port, _, _, _ = make_port()
    port.cycle_drive(4)
    assert port.external == {4: 1}
    port.cycle_drive(4)
    assert port.external == {4: 0}
    port.cycle_drive(4)
    assert port.external == {}
    port.drive(6, 1)
    port.write(DIR, 0b1, ALL)
    port.reset()  # lo de afuera es físico: sobrevive al reset
    assert port.read(DIR) == 0 and port.read(IN) == 0b0100_0000
    snapshot = port.snapshot()
    port.drive(6, None)
    port.restore(snapshot)
    assert port.read(IN) == 0b0100_0000
    with pytest.raises(MmioFault):
        port.write(IN, 1, ALL)
    with pytest.raises(MmioFault):
        port.read(0x20)
    with pytest.raises(ValueError):
        port.drive(8, 1)


def test_placa_sdk_y_guion(tmp_path: Path) -> None:
    board = BoardConfig.model_validate(
        {"peripherals": [{"name": "puerto", "type": "gpio", "offset": "0x60", "irq_line": 3}]}
    )
    header = generate_header(board)
    for macro in (
        "GPIO_DIR",
        "GPIO_IN",
        "GPIO_PULL",
        "GPIO_SHORT",
        "gpio_irq_enable",
        "IRQ_PUERTO 3",
    ):
        assert macro in header
    # Un GPIO necesita sus 32 bytes: no puede pisar a otro periférico.
    with pytest.raises(ValidationError, match="se superponen"):
        BoardConfig.model_validate(
            {
                "peripherals": [
                    {"name": "puerto", "type": "gpio", "offset": "0x60"},
                    {"name": "leds", "type": "gpio_out", "offset": "0x70"},
                ]
            }
        )
    guion = tmp_path / "entrada.toml"
    guion.write_text(
        "[[at]]\ncycle = 10\ngpio_high = [1, 2]\ngpio_low = 3\n\n"
        "[[at]]\ncycle = 20\ngpio_float = [1]\n",
        encoding="utf-8",
    )
    script = load_script(guion)
    assert script.at[0].describe() == "gpio 1, 2 alto; gpio 3 bajo"
    assert script.at[0].gpio == [(1, 1), (2, 1), (3, 0)]


@pytest.mark.skipif(importlib.util.find_spec("ziglang") is None, reason="requiere [zig]")
def test_firmware_con_pull_up_e_irq_por_flanco(tmp_path: Path) -> None:
    board = BoardConfig.model_validate(
        {
            "peripherals": [
                {"name": "uart0", "type": "uart", "offset": "0x10", "irq_line": 1},
                {"name": "puerto", "type": "gpio", "offset": "0x60", "irq_line": 3},
            ]
        }
    )
    fuente = tmp_path / "gpio.c"
    fuente.write_text(
        """#include "hardboiled.h"

static volatile int flancos = 0;

static void al_bajar(void)
{
    flancos++;
    gpio_clear(1u << 0);
}

int main(void)
{
    gpio_pullup(1u << 0, 1);      /* botón a masa en el pin 0 */
    gpio_output(1u << 7);         /* LED en el pin 7 */
    gpio_irq_enable(1u << 0, 1);  /* avisar al apretar (flanco de bajada) */
    attach_irq(IRQ_PUERTO, al_bajar);
    interrupts_enable();
    while (flancos < 2) {
        wait_for_interrupt();
    }
    gpio_write(7, 1);
    uart_putc((char)('0' + flancos));
    return gpio_read(0) * 10 + gpio_read(7);
}
""",
        encoding="utf-8",
    )
    options = BuildOptions(runtime=runtime_for(board, tmp_path / "cache"))
    elf = build([fuente], tmp_path / "gpio.elf", options, select_compiler("zig")).output
    machine = Machine.from_elf(elf, board)
    port = machine.gpio()
    assert port is not None and port.read(IN) == 0
    guion = tmp_path / "entrada.toml"
    guion.write_text(
        "[[at]]\ncycle = 5000\ngpio_low = 0\n\n[[at]]\ncycle = 6000\ngpio_float = 0\n\n"
        "[[at]]\ncycle = 9000\ngpio_low = 0\n",
        encoding="utf-8",
    )
    player = ScriptPlayer(machine, load_script(guion), None)
    machine.bus.add_source(player)
    machine.cpu.refresh_deadline()
    stop = machine.debugger.continue_()
    uart = machine.uart()
    assert uart is not None and bytes(uart.transmitted) == b"2"
    # Al final el pin 0 sigue a masa (0) y el LED del pin 7 quedó encendido (1).
    assert stop.reason is StopReason.EXITED and stop.exit_code == 1


def test_guion_sin_gpio_en_la_placa(tmp_path: Path) -> None:
    guion = tmp_path / "entrada.toml"
    guion.write_text("[[at]]\ncycle = 10\ngpio_high = 1\n", encoding="utf-8")
    machine = Machine.from_elf(Path(__file__).parent / "fixtures" / "hwloop.elf")
    with pytest.raises(ScriptError, match="no tiene GPIO"):
        ScriptPlayer(machine, load_script(guion), None)


async def test_vista_del_puerto_en_la_tui() -> None:
    from textual.app import App, ComposeResult
    from textual.widgets import Button

    from hardboiled.core.events import PeripheralInfo
    from hardboiled.ui.widgets.hardware_view import GpioPortView, HardwareView

    recibidos: list[GpioPortView.Driven] = []

    class GpioApp(App[None]):
        def compose(self) -> ComposeResult:
            yield HardwareView()

        def on_gpio_port_view_driven(self, message: GpioPortView.Driven) -> None:
            recibidos.append(message)

    app = GpioApp()
    async with app.run_test(size=(120, 20)) as pilot:
        vista = app.query_one(HardwareView)
        vista.configure((PeripheralInfo("puerto", "gpio", 0x60, 4),))
        await pilot.pause()
        estado = {"dir": 0b0001, "level": 0b0011, "short": 0b0001, "driven": 0b0010}
        vista.update_states((("puerto", tuple(estado.items())),))
        await pilot.pause()
        pin0 = app.query_one("#gpio-0", Button)
        pin1 = app.query_one("#gpio-1", Button)
        assert str(pin0.label) == "0→1" and pin0.has_class("short") and pin0.has_class("high")
        assert str(pin1.label) == "1←1" and pin1.has_class("driven")
        vista.update_device("puerto", IN, 0b0001)
        await pilot.pause()
        assert str(pin1.label) == "1←0" and not pin1.has_class("high")
        await pilot.click("#gpio-1")
        await pilot.pause()
        assert [(m.device, m.pin_index) for m in recibidos] == [("puerto", 1)]
