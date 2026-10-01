"""Convertidor analógico-digital multicanal con potenciómetros (qol.md #64).

Registros:
    +0x0 CTRL    bits 0-2: canal; bit 8: START (escribir 1 inicia la conversión);
                 bit 9: pedir la IRQ al terminar
    +0x4 STATUS  bit 0: BUSY (convirtiendo); bit 1: DONE (escribir 1 limpia y retira la IRQ)
    +0x8 DATA    sólo lectura: resultado de la última conversión (0 .. 2^bits - 1)
    +0xC INFO    sólo lectura: bits 0-7 = resolución en bits; bits 8-15 = cantidad de canales

Se elige un canal, se pide la conversión, se espera DONE (por sondeo o por IRQ) y se lee
DATA. La tensión del canal se toma al iniciar (muestreo y retención) y el resultado está
`conversion_cycles` después. Cada canal tiene un potenciómetro entre 0 y `vref_mv` milivoltios
que se gira desde la TUI o el guion de entrada; su posición es física: sobrevive al reset. Es
la base de los sensores analógicos (temperatura, luz) de la sección J.
"""

from __future__ import annotations

from collections.abc import Callable

from hardboiled.core.events import EvtHardwareUpdated
from hardboiled.hardware.bus import Peripheral, merge
from hardboiled.i18n import N_, _

CTRL = 0x0
STATUS = 0x4
DATA = 0x8
INFO = 0xC

CTRL_CHANNEL = 0x7
CTRL_START = 1 << 8
CTRL_IRQ = 1 << 9
STATUS_BUSY = 1 << 0
STATUS_DONE = 1 << 1

# Desplazamiento (fuera de los registros) con que se avisa a la interfaz la tensión de cada canal:
# EvtHardwareUpdated(nombre, POT_BASE + 4 * canal, milivoltios).
POT_BASE = 0x100


class Adc(Peripheral):
    kind = "adc"
    size = 16

    def __init__(
        self,
        name: str,
        offset: int,
        channels: int = 4,
        resolution_bits: int = 10,
        conversion_cycles: int = 100,
        vref_mv: int = 3300,
        irq_line: int | None = None,
        raise_irq: Callable[[int], None] | None = None,
        lower_irq: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(name, offset, resolution_bits)
        self.channels = channels
        self.conversion_cycles = conversion_cycles
        self.vref_mv = vref_mv
        self.irq_line = irq_line
        self._raise_irq = raise_irq
        self._lower_irq = lower_irq
        # Los potenciómetros arrancan a mitad de recorrido.
        self.millivolts = [vref_mv // 2] * channels
        self.reset()

    def reset(self) -> None:
        self.channel = 0
        self.irq_enable = False
        self.busy = False
        self.done = False
        self.data = 0
        self.conversions = 0
        self._sample = 0
        self._finish: int | None = None

    @property
    def max_code(self) -> int:
        return (1 << self.width_bits) - 1

    def code_for(self, millivolts: int) -> int:
        """Resultado de convertir `millivolts` (se satura en 0 y en vref)."""
        clamped = min(max(millivolts, 0), self.vref_mv)
        return round(clamped * self.max_code / self.vref_mv)

    # ------------------------------------------------------------ estímulos

    def _check_channel(self, channel: int) -> None:
        if not 0 <= channel < self.channels:
            raise ValueError(
                _("{device} no tiene el canal {channel}", device=self.name, channel=channel)
            )

    def set_millivolts(self, channel: int, millivolts: int) -> None:
        """Gira el potenciómetro del canal hasta `millivolts` (entre 0 y vref)."""
        self._check_channel(channel)
        self.millivolts[channel] = min(max(int(millivolts), 0), self.vref_mv)
        self.emit(EvtHardwareUpdated(self.name, POT_BASE + 4 * channel, self.millivolts[channel]))

    def nudge(self, channel: int, percent: int) -> None:
        """Gira el potenciómetro `percent` por ciento del recorrido (negativo: hacia 0)."""
        self._check_channel(channel)
        self.set_millivolts(channel, self.millivolts[channel] + percent * self.vref_mv // 100)

    def inspect(self) -> dict[str, int]:
        state = {
            "channel": self.channel,
            "busy": int(self.busy),
            "done": int(self.done),
            "data": self.data,
            "conversions": self.conversions,
        }
        state.update({f"mv{channel}": mv for channel, mv in enumerate(self.millivolts)})
        state["vref"] = self.vref_mv
        return state

    def can_wake(self) -> bool:
        return self.irq_enable and self.irq_line is not None

    # ---------------------------------------------------------------- tiempo

    def next_deadline(self) -> int | None:
        return self._finish

    def service(self, cycle: int) -> None:
        if self._finish is not None and self._finish <= cycle:
            self._finish = None
            self.busy = False
            self.done = True
            self.data = self._sample
            self.conversions += 1
            self.emit(EvtHardwareUpdated(self.name, DATA, self.data))
            self._update_irq()

    def _update_irq(self) -> None:
        if self.irq_line is None:
            return
        if self.done and self.irq_enable:
            if self._raise_irq is not None:
                self._raise_irq(self.irq_line)
        elif self._lower_irq is not None:
            self._lower_irq(self.irq_line)

    # ------------------------------------------------------------- registros

    def read(self, reg: int) -> int:
        if reg == CTRL:
            return self.channel | (CTRL_IRQ if self.irq_enable else 0)
        if reg == STATUS:
            return (STATUS_BUSY if self.busy else 0) | (STATUS_DONE if self.done else 0)
        if reg == DATA:
            return self.data
        if reg == INFO:
            return self.width_bits | self.channels << 8
        raise self.fault(reg, N_("registro inexistente"))

    def write(self, reg: int, value: int, mask: int) -> None:
        if reg == CTRL:
            # Un acceso de 8 bits conserva el resto (START se lee siempre en 0: es una orden).
            value = merge(self.read(CTRL), value, mask)
            channel = value & CTRL_CHANNEL
            if channel >= self.channels:
                raise self.fault(reg, N_("el ADC no tiene ese canal"))
            self.channel = channel
            self.irq_enable = bool(value & CTRL_IRQ)
            if value & CTRL_START:
                # Muestreo y retención: se toma la tensión de ahora; el resultado, más tarde.
                self._sample = self.code_for(self.millivolts[channel])
                self.busy = True
                self.done = False
                self._finish = self.clock.cycles + self.conversion_cycles
        elif reg == STATUS:
            if value & mask & STATUS_DONE:
                self.done = False  # write-1-to-clear
        elif reg in (DATA, INFO):
            raise self.fault(reg, N_("DATA e INFO son de sólo lectura"))
        else:
            raise self.fault(reg, N_("registro inexistente"))
        self._update_irq()
