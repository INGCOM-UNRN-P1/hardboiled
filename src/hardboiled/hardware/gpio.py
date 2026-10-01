"""Módulos GPIO: barra de LEDs (salida) y banco de DIP switches (entrada)."""

from __future__ import annotations

from hardboiled.core.events import EvtHardwareUpdated
from hardboiled.hardware import rebote
from hardboiled.hardware.bus import Peripheral, merge
from hardboiled.i18n import N_, _


class LedBar(Peripheral):
    """Registro de salida: cada bit enciende un LED. Admite accesos de 8/16/32 bits."""

    kind = "gpio_out"
    size = 4

    def __init__(self, name: str, offset: int, width_bits: int = 8) -> None:
        super().__init__(name, offset, width_bits)
        self._mask = (1 << width_bits) - 1
        self.value = 0

    def reset(self) -> None:
        self.value = 0

    def read(self, reg: int) -> int:
        if reg != 0:
            raise self.fault(reg, N_("registro inexistente"))
        return self.value

    def write(self, reg: int, value: int, mask: int) -> None:
        if reg != 0:
            raise self.fault(reg, N_("registro inexistente"))
        new_value = merge(self.value, value, mask) & self._mask
        if new_value != self.value:
            self.value = new_value
            self.emit(EvtHardwareUpdated(self.name, 0, new_value))


class SwitchBank(Peripheral):
    """Registro de sólo lectura con el estado de los interruptores de la UI."""

    kind = "gpio_in"
    size = 4

    def __init__(self, name: str, offset: int, width_bits: int = 4, bounce_cycles: int = 0) -> None:
        super().__init__(name, offset, width_bits)
        self.value = 0
        self.bounce_cycles = bounce_cycles
        self._rebotes: rebote.Pendientes = []

    # El estado de los switches es "físico": sobrevive a un reset de la placa. Un rebote a mitad de
    # camino termina en su nivel final (el reloj vuelve a 0).

    def reset(self) -> None:
        for pin, nivel in rebote.finales(self._rebotes).items():
            self._poner(pin, nivel)
        self._rebotes = []

    def read(self, reg: int) -> int:
        if reg != 0:
            raise self.fault(reg, N_("registro inexistente"))
        return self.value

    def write(self, reg: int, value: int, mask: int) -> None:
        raise self.fault(reg, N_("los switches son de sólo lectura"))

    def toggle(self, pin_index: int) -> None:
        if not 0 <= pin_index < self.width_bits:
            raise ValueError(_("{device} no tiene el pin {pin}", device=self.name, pin=pin_index))
        self.set_value(self.value ^ (1 << pin_index))

    def set_value(self, value: int) -> None:
        value &= (1 << self.width_bits) - 1
        if self.bounce_cycles:
            cambiados = value ^ self.value
            for pin in range(self.width_bits):
                if cambiados >> pin & 1:
                    self._rebotes = rebote.programar(
                        self._rebotes, self.clock.cycles, pin, value >> pin & 1, self.bounce_cycles
                    )
        self._aplicar(value)

    def _aplicar(self, value: int) -> None:
        self.value = value
        self.emit(EvtHardwareUpdated(self.name, 0, self.value))

    def _poner(self, pin: int, nivel: int) -> None:
        self._aplicar((self.value & ~(1 << pin)) | (nivel << pin))

    def next_deadline(self) -> int | None:
        return rebote.proximo(self._rebotes)

    def service(self, cycle: int) -> None:
        hechos, self._rebotes = rebote.vencidos(self._rebotes, cycle)
        for _ciclo, pin, nivel in hechos:
            self._poner(pin, nivel)
