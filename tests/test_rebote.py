"""Rebote de contactos configurable (qol.md #74): «apreté una vez y contó tres»."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
from pydantic import ValidationError

from hardboiled.config import BoardConfig
from hardboiled.core.events import Event, EvtHardwareUpdated
from hardboiled.core.machine import Machine
from hardboiled.hardware import rebote
from hardboiled.hardware.bus import Clock
from hardboiled.hardware.buttons import ButtonBank
from hardboiled.hardware.gpio import SwitchBank
from hardboiled.hardware.gpio_port import IN, IRQ_EN, PENDING, PULL, GpioPort
from hardboiled.script import ScriptPlayer, load_script
from hardboiled.sdk import runtime_for
from hardboiled.toolchain import BuildOptions, build, select_compiler

ALL = 0xFFFF_FFFF


def avanzar(device: ButtonBank | SwitchBank | GpioPort, hasta: int) -> None:
    """Atiende al periférico en cada vencimiento, como hace la CPU, hasta el ciclo `hasta`."""
    while (deadline := device.next_deadline()) is not None and deadline <= hasta:
        device.clock.cycles = deadline
        device.service(deadline)
    device.clock.cycles = hasta


def test_patron_del_rebote() -> None:
    pendientes = rebote.programar([], 100, 2, 1, 1000)
    assert pendientes == [(250, 2, 0), (450, 2, 1), (700, 2, 0), (1100, 2, 1)]
    hechos, resto = rebote.vencidos(pendientes, 450)
    assert [n for _c, _p, n in hechos] == [0, 1] and len(resto) == 2
    assert rebote.finales(resto) == {2: 1}
    # Un cambio nuevo del mismo pin reemplaza al rebote en curso; los de otro pin siguen.
    otro = rebote.programar(pendientes, 0, 3, 0, 10)
    assert rebote.programar(otro, 200, 2, 0, 1000)[-1] == (1200, 2, 0)
    assert {p for _c, p, _n in rebote.programar(otro, 200, 2, 0, 1000)} == {2, 3}


def test_un_boton_con_rebote_genera_tres_flancos_al_apretar_y_al_soltar() -> None:
    eventos: list[Event] = []
    bank = ButtonBank(
        "b", 0x30, 4, 2, lambda _: None, lambda _: None, hold_cycles=5000, bounce_cycles=1000
    )
    bank.clock = Clock()
    bank.emit = eventos.append
    bank.press(1)
    avanzar(bank, 10_000)
    niveles = [e.value >> 1 & 1 for e in eventos if isinstance(e, EvtHardwareUpdated)]
    assert niveles == [1, 0, 1, 0, 1, 0, 1, 0, 1, 0]
    assert bank.presses == 1 and bank.read(0x0) == 0
    # Sin rebote, el mismo botón cambia una vez al apretar y otra al soltar.
    eventos.clear()
    limpio = ButtonBank("b", 0x30, 4, hold_cycles=5000)
    limpio.clock = Clock()
    limpio.emit = eventos.append
    limpio.press(1)
    avanzar(limpio, 10_000)
    assert [e.value for e in eventos if isinstance(e, EvtHardwareUpdated)] == [0b10, 0]


def test_switches_con_rebote_y_reset_a_mitad_de_camino() -> None:
    switches = SwitchBank("sw", 0x04, 4, bounce_cycles=100)
    switches.clock = Clock()
    switches.toggle(2)
    assert switches.value == 0b100  # el primer contacto ya es el nivel nuevo
    avanzar(switches, 20)
    assert switches.value == 0  # rebotó
    switches.reset()  # el reloj vuelve a 0: queda en el nivel final, sin pendientes
    assert switches.value == 0b100 and switches.next_deadline() is None


def test_gpio_con_rebote_cuenta_cada_flanco() -> None:
    port = GpioPort("gpio", 0x60, 8, bounce_cycles=400)
    port.clock = Clock()
    port.write(PULL, 0b1, ALL)
    port.write(IRQ_EN, 0b1, ALL)
    port.write(0x14, 0b1, ALL)  # EDGE: flanco de bajada
    flancos = 0
    port.drive(0, 0)  # un botón a masa: primer contacto
    while True:
        if port.read(PENDING):
            flancos += 1
            port.write(PENDING, 0b1, ALL)  # la ISR limpia y espera el próximo
        deadline = port.next_deadline()
        if deadline is None:
            break
        port.clock.cycles = deadline
        port.service(deadline)
    assert flancos == 3 and port.read(IN) & 1 == 0
    port.drive(0, None)  # soltarlo no rebota (queda flotando: el pull-up lo lleva a 1)
    assert port.next_deadline() is None and port.read(IN) & 1 == 1


def test_solo_rebotan_las_entradas() -> None:
    with pytest.raises(ValidationError, match="sólo rebotan las entradas"):
        BoardConfig.model_validate(
            {"peripherals": [{"name": "t", "type": "timer", "offset": "0x20", "bounce_cycles": 10}]}
        )
    board = BoardConfig.model_validate(
        {"peripherals": [{"name": "b", "type": "gpio_irq", "offset": "0x30", "bounce_cycles": 500}]}
    )
    assert board.peripherals[0].bounce_cycles == 500


@pytest.mark.skipif(importlib.util.find_spec("ziglang") is None, reason="requiere [zig]")
def test_firmware_sin_antirrebote_cuenta_tres(tmp_path: Path) -> None:
    board = BoardConfig.model_validate(
        {
            "peripherals": [
                {"name": "uart0", "type": "uart", "offset": "0x10", "irq_line": 1},
                {
                    "name": "puerto",
                    "type": "gpio",
                    "offset": "0x60",
                    "irq_line": 3,
                    "bounce_cycles": 3000,
                },
            ]
        }
    )
    fuente = tmp_path / "contador.c"
    fuente.write_text(
        """#include "hardboiled.h"

static volatile int pulsaciones = 0;

static void al_apretar(void)
{
    pulsaciones++;  /* sin antirrebote: cada flanco cuenta */
    gpio_clear(1u << 0);
}

int main(void)
{
    gpio_pullup(1u << 0, 1);
    gpio_irq_enable(1u << 0, 1);
    attach_irq(IRQ_PUERTO, al_apretar);
    interrupts_enable();
    for (volatile int i = 0; i < 20000; i++) {
    }
    uart_putc((char)('0' + pulsaciones));
    return 0;
}
""",
        encoding="utf-8",
    )
    options = BuildOptions(runtime=runtime_for(board, tmp_path / "cache"))
    elf = build([fuente], tmp_path / "contador.elf", options, select_compiler("zig")).output
    machine = Machine.from_elf(elf, board)
    guion = tmp_path / "entrada.toml"
    guion.write_text("[[at]]\ncycle = 2000\ngpio_low = 0\n", encoding="utf-8")
    machine.bus.add_source(ScriptPlayer(machine, load_script(guion), None))
    machine.cpu.refresh_deadline()
    machine.debugger.continue_()
    uart = machine.uart()
    assert uart is not None and bytes(uart.transmitted) == b"3"  # una sola pulsación
