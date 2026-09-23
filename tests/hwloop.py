"""Banco de pruebas de hardware en lazo.

`HardwareLoop` hace de "entorno" de la placa mientras el firmware corre: aplica
estímulos en ciclos dados (lazo abierto) o en reacción a lo que muestran las
salidas (lazo cerrado), y registra cómo evolucionan LEDs y display.

Se engancha al `poll` de la CPU, que se consulta cada 1024 instrucciones y
después de cada `wfi`: la resolución temporal de los estímulos es esa.
"""

from __future__ import annotations

import heapq
import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Self

from hardboiled.core.cpu import StopInfo
from hardboiled.core.machine import Machine
from hardboiled.hardware import LedBar
from hardboiled.hardware.sevenseg import SevenSegment

# Mismo alfabeto que seg_pattern() del SDK.
SEG_FONT = (0x3F, 0x06, 0x5B, 0x4F, 0x66, 0x6D, 0x7D, 0x07,
            0x7F, 0x6F, 0x77, 0x7C, 0x39, 0x5E, 0x79, 0x71)  # fmt: skip
SEG_CHARS = {pattern: "0123456789ABCDEF"[i] for i, pattern in enumerate(SEG_FONT)} | {0: " "}

Action = Callable[["HardwareLoop"], None]
Predicate = Callable[["HardwareLoop"], bool]


@dataclass(frozen=True)
class Sample:
    """Estado visible de la placa en un ciclo (sólo se guarda cuando cambia)."""

    cycle: int
    leds: int
    display: str


class HardwareLoop:
    def __init__(self, machine: Machine, timeout: float = 10.0) -> None:
        self.machine = machine
        self.cpu = machine.cpu
        self.timeout = timeout
        buttons, uart, switches = machine.buttons(), machine.uart(), machine.switches()
        assert buttons is not None and uart is not None and switches is not None
        self.buttons, self.uart, self.switches = buttons, uart, switches
        self.leds = next(p for p in machine.peripherals if isinstance(p, LedBar))
        self.seg = next(p for p in machine.peripherals if isinstance(p, SevenSegment))
        self.trace: list[Sample] = []
        self.log: list[tuple[int, str]] = []  # (ciclo, estímulo aplicado)
        self._scheduled: list[tuple[int, int, str, Action]] = []
        self._reactions: list[tuple[Predicate, str, Action]] = []
        self._order = itertools.count()
        self._deadline = 0.0
        self.timed_out = False

    # ------------------------------------------------------------ salidas

    @property
    def cycle(self) -> int:
        return self.cpu.clock.cycles

    @property
    def display(self) -> str:
        """Texto del display, con el dígito 0 a la derecha ('?' si no es una cifra)."""
        return "".join(SEG_CHARS.get(s & 0x7F, "?") for s in reversed(self.seg.segments()))

    @property
    def display_value(self) -> int | None:
        text = self.display.strip()
        return int(text) if text.isdigit() else None

    @property
    def output(self) -> str:
        return self.uart.transmitted.decode("utf-8", "replace")

    # ---------------------------------------------------------- estímulos

    def press(self, pin: int) -> Action:
        return lambda loop: loop.buttons.press(pin)

    def type(self, text: str) -> Action:
        return lambda loop: loop.uart.receive(text.encode())

    def set_switches(self, value: int) -> Action:
        return lambda loop: loop.switches.set_value(value)

    def at(self, cycle: int, action: Action, label: str = "") -> Self:
        """Lazo abierto: aplica `action` apenas el reloj llegue a `cycle`."""
        heapq.heappush(self._scheduled, (cycle, next(self._order), label, action))
        return self

    def when(self, predicate: Predicate, action: Action, label: str = "") -> Self:
        """Lazo cerrado: aplica `action` una vez, la primera vez que `predicate` se cumple."""
        self._reactions.append((predicate, label, action))
        return self

    # ---------------------------------------------------------- ejecución

    def run(self) -> StopInfo:
        """Corre desde el comienzo hasta que el programa termina o se detiene."""
        self.cpu.interactive = True  # `wfi` espera estímulos en vez de dar deadlock
        self.cpu.poll = self._poll
        self._deadline = time.monotonic() + self.timeout
        self._sample()
        stop = self.machine.debugger.continue_()
        self._sample()
        return stop

    def _poll(self) -> bool:
        fired = False
        while self._scheduled and self._scheduled[0][0] <= self.cycle:
            _, _, label, action = heapq.heappop(self._scheduled)
            fired |= self._apply(label, action)
        for reaction in list(self._reactions):
            predicate, label, action = reaction
            if predicate(self):
                self._reactions.remove(reaction)
                fired |= self._apply(label, action)
        if fired:
            self.cpu.refresh_deadline()
        self._sample()
        if time.monotonic() > self._deadline:
            self.timed_out = True
            return True  # pausar: el test falla en vez de colgarse
        return False

    def _apply(self, label: str, action: Action) -> bool:
        action(self)
        self.log.append((self.cycle, label))
        return True

    def _sample(self) -> None:
        sample = Sample(self.cycle, self.leds.value, self.display)
        last = self.trace[-1] if self.trace else None
        if last is None or (last.leds, last.display) != (sample.leds, sample.display):
            self.trace.append(sample)
