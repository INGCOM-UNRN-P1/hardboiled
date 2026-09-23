"""Hardware virtual en lazo: timer, botones, UART, switches, LEDs y display a la vez.

El firmware `fixtures/hwloop.c` duerme con `wfi` y atiende tres IRQ; el banco de
pruebas `HardwareLoop` lo estimula por ciclo (lazo abierto) o reaccionando a lo
que muestran las salidas (lazo cerrado).
"""

from __future__ import annotations

import itertools
from collections.abc import Callable

from hardboiled.core.cpu import StopReason
from tests.hwloop import HardwareLoop

LoopFactory = Callable[..., HardwareLoop]
TICK = 20_000  # TICK_CYCLES del firmware


def test_open_loop_script_drives_every_peripheral(hardware_loop: LoopFactory) -> None:
    loop = hardware_loop()
    loop.at(3 * TICK, loop.set_switches(0b1010), "switches")
    loop.at(4 * TICK, loop.press(0), "botón 0")
    loop.at(5 * TICK, loop.press(3), "botón 3")
    # Un botón se suelta solo tras 20 000 ciclos: recién ahí puede volver a apretarse.
    loop.at(7 * TICK, loop.press(3), "botón 3 otra vez")
    loop.at(8 * TICK, loop.type("hola, placa!"), "texto")
    loop.at(10 * TICK, loop.type("q"), "salir")

    stop = loop.run()

    assert not loop.timed_out
    assert stop.reason is StopReason.EXITED and stop.exit_code == 3
    assert loop.output == "listo\nHOLA, PLACA!fin\n"
    assert loop.leds.value == 0b0011_1010  # 3 pulsaciones | switches
    assert loop.buttons.presses == 3
    assert [label for _, label in loop.log][-1] == "salir"
    assert loop.display_value is not None and loop.display_value >= 9


def test_display_counts_every_tick_without_skipping(hardware_loop: LoopFactory) -> None:
    loop = hardware_loop()
    loop.at(12 * TICK, loop.type("q"))
    loop.run()

    shown = [s.display.strip() for s in loop.trace]
    counts = [int(text) for text in shown if text.isdigit()]
    # Cada tick despierta al lazo antes del siguiente: el display pasa por todos.
    assert counts == list(range(counts[0], counts[-1] + 1))
    assert counts[-1] >= 11
    # Y a ritmo del timer: `wfi` adelanta el reloj justo hasta cada vencimiento.
    # (La última muestra es la del cierre, al recibir la 'q', no un tick.)
    changes = [s.cycle for s in loop.trace if s.display.strip().isdigit()][:-1]
    assert {b - a for a, b in itertools.pairwise(changes)} == {TICK}


def test_closed_loop_reacts_to_outputs(hardware_loop: LoopFactory) -> None:
    loop = hardware_loop()

    def shows(value: int) -> Callable[[HardwareLoop], bool]:
        return lambda board: board.display_value == value

    # Un "operador" que mira el display y los LEDs y responde a lo que ve.
    loop.when(shows(2), loop.press(1), "ve 2: aprieta")
    loop.when(lambda b: b.leds.value >> 4 == 1, loop.set_switches(0b0101), "ve 1 pulsación")
    loop.when(lambda b: b.leds.value & 0xF == 0b0101, loop.type("ok"), "ve los switches")
    loop.when(lambda b: b.output.endswith("OK"), loop.type("q"), "lee el eco")

    stop = loop.run()

    assert not loop.timed_out
    assert stop.reason is StopReason.EXITED and stop.exit_code == 1
    assert [label for _, label in loop.log] == [
        "ve 2: aprieta",
        "ve 1 pulsación",
        "ve los switches",
        "lee el eco",
    ]
    cycles = [cycle for cycle, _ in loop.log]
    assert cycles == sorted(cycles)
    assert loop.output == "listo\nOKfin\n"


def test_burst_of_input_is_buffered_between_wakeups(hardware_loop: LoopFactory) -> None:
    loop = hardware_loop()
    # Todo en el mismo ciclo: tres botones y un texto que casi llena el buffer (32).
    loop.at(2 * TICK, loop.press(0))
    loop.at(2 * TICK, loop.press(1))
    loop.at(2 * TICK, loop.press(2))
    loop.at(2 * TICK, loop.type("abcdefghijklmnoprstuvwxyz 0123q"))

    stop = loop.run()

    assert stop.reason is StopReason.EXITED and stop.exit_code == 3
    assert loop.output == "listo\nABCDEFGHIJKLMNOPRSTUVWXYZ 0123fin\n"


def test_loop_times_out_instead_of_hanging(hardware_loop: LoopFactory) -> None:
    loop = hardware_loop(max_instructions=100_000_000)
    loop.timeout = 0.3  # nunca llega la 'q'
    stop = loop.run()
    assert loop.timed_out and stop.reason is StopReason.PAUSED
