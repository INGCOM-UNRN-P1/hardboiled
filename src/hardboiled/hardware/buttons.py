"""Botones pulsadores que piden una interrupción al presionarse (o al soltarse).

Registros:
    +0x0 STATE    sólo lectura: un bit por botón presionado
    +0x4 IRQ_EN   máscara de botones que piden la IRQ
    +0x8 EDGE     por botón: 0 = avisa al presionar, 1 = al soltar
    +0xC PENDING  flancos detectados; escribir 1 limpia (y retira la IRQ)

La IRQ queda pedida mientras haya algún flanco pendiente de un botón habilitado.
Desde la interfaz, un botón se presiona y se suelta solo `hold_cycles` después. Con
`bounce_cycles`, al presionarse y al soltarse el contacto rebota (ver rebote.py).
"""

from __future__ import annotations

from collections.abc import Callable

from hardboiled.core.events import EvtHardwareUpdated
from hardboiled.hardware import rebote
from hardboiled.hardware.bus import Peripheral, merge
from hardboiled.i18n import N_, _

STATE = 0x0
IRQ_EN = 0x4
EDGE = 0x8
PENDING = 0xC
DEFAULT_HOLD_CYCLES = 20_000


class ButtonBank(Peripheral):
    kind = "gpio_irq"
    size = 16

    def __init__(
        self,
        name: str,
        offset: int,
        width_bits: int = 4,
        irq_line: int | None = None,
        raise_irq: Callable[[int], None] | None = None,
        lower_irq: Callable[[int], None] | None = None,
        hold_cycles: int = DEFAULT_HOLD_CYCLES,
        bounce_cycles: int = 0,
    ) -> None:
        super().__init__(name, offset, width_bits)
        self.irq_line = irq_line
        self._raise_irq = raise_irq
        self._lower_irq = lower_irq
        self.hold_cycles = hold_cycles
        self.bounce_cycles = bounce_cycles
        self._mask = (1 << width_bits) - 1
        self.reset()

    def reset(self) -> None:
        self.state = 0
        self.irq_enable = 0
        self.edge = 0
        self.pending = 0
        self.presses = 0
        self._releases: dict[int, int] = {}  # pin -> ciclo en que se suelta
        self._rebotes: rebote.Pendientes = []

    # --------------------------------------------------------------- estímulos

    def press(self, pin: int) -> None:
        """Presiona un botón; se suelta solo después de `hold_cycles`."""
        if not 0 <= pin < self.width_bits:
            raise ValueError(_("{device} no tiene el botón {pin}", device=self.name, pin=pin))
        ahora = self.clock.cycles
        self._contacto(pin, True, ahora)
        # Se suelta recién cuando terminó de rebotar al apretarse.
        self._releases[pin] = ahora + max(self.hold_cycles, self.bounce_cycles + 1)
        self.presses += 1

    def _contacto(self, pin: int, pressed: bool, ahora: int) -> None:
        if self.bounce_cycles:
            self._rebotes = rebote.programar(
                self._rebotes, ahora, pin, int(pressed), self.bounce_cycles
            )
        self._set(pin, pressed)

    def _set(self, pin: int, pressed: bool) -> None:
        bit = 1 << pin
        before = self.state
        self.state = (self.state | bit) if pressed else (self.state & ~bit)
        if before == self.state:
            return
        falling_edge = bool(self.edge & bit)
        if pressed != falling_edge:  # presionar con EDGE=0 o soltar con EDGE=1
            self.pending |= bit
        self._update_irq()
        self.emit(EvtHardwareUpdated(self.name, STATE, self.state))

    def _update_irq(self) -> None:
        if self.irq_line is None:
            return
        if self.pending & self.irq_enable:
            if self._raise_irq is not None:
                self._raise_irq(self.irq_line)
        elif self._lower_irq is not None:
            self._lower_irq(self.irq_line)

    def inspect(self) -> dict[str, int]:
        return {"pending": self.pending, "irq_enable": self.irq_enable, "presses": self.presses}

    def can_wake(self) -> bool:
        return bool(self.irq_enable) and self.irq_line is not None

    # ---------------------------------------------------------------- tiempo

    def next_deadline(self) -> int | None:
        candidatos = list(self._releases.values())
        if self._rebotes:
            candidatos.append(self._rebotes[0][0])
        return min(candidatos) if candidatos else None

    def service(self, cycle: int) -> None:
        # Rebotes y sueltas en orden de ciclo: soltar un botón también rebota.
        while True:
            proximo_rebote = rebote.proximo(self._rebotes)
            suelta = min(self._releases.items(), key=lambda item: (item[1], item[0]), default=None)
            momentos = [m for m in (proximo_rebote, suelta[1] if suelta else None) if m is not None]
            if not momentos or min(momentos) > cycle:
                return
            if proximo_rebote is not None and proximo_rebote == min(momentos):
                (_ciclo, pin, nivel), self._rebotes = self._rebotes[0], self._rebotes[1:]
                self._set(pin, bool(nivel))
            elif suelta is not None:
                del self._releases[suelta[0]]
                self._contacto(suelta[0], False, suelta[1])

    # ------------------------------------------------------------- registros

    def read(self, reg: int) -> int:
        if reg == STATE:
            return self.state
        if reg == IRQ_EN:
            return self.irq_enable
        if reg == EDGE:
            return self.edge
        if reg == PENDING:
            return self.pending
        raise self.fault(reg, N_("registro inexistente"))

    def write(self, reg: int, value: int, mask: int) -> None:
        if reg == STATE:
            raise self.fault(reg, N_("STATE es de sólo lectura"))
        if reg == IRQ_EN:
            self.irq_enable = merge(self.irq_enable, value, mask) & self._mask
        elif reg == EDGE:
            self.edge = merge(self.edge, value, mask) & self._mask
        elif reg == PENDING:
            self.pending &= ~(value & mask)  # write-1-to-clear
        else:
            raise self.fault(reg, N_("registro inexistente"))
        self._update_irq()
