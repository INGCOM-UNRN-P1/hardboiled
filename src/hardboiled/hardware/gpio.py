"""Módulos GPIO: barra de LEDs (salida) y banco de DIP switches (entrada)."""

from __future__ import annotations

from hardboiled.core.events import EvtHardwareUpdated
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

    def __init__(self, name: str, offset: int, width_bits: int = 4) -> None:
        super().__init__(name, offset, width_bits)
        self.value = 0

    # El estado de los switches es "físico": sobrevive a un reset de la placa.

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
        self.value = value & ((1 << self.width_bits) - 1)
        self.emit(EvtHardwareUpdated(self.name, 0, self.value))
