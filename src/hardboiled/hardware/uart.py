"""UART virtual: sólo transmisión (el firmware escribe, la consola muestra)."""

from __future__ import annotations

from hardboiled.core.events import EvtUartOutput
from hardboiled.hardware.bus import Peripheral

TX_DATA = 0x0
STATUS = 0x4
STATUS_TX_READY = 1 << 0


class Uart(Peripheral):
    kind = "uart"
    size = 8

    def __init__(self, name: str, offset: int, width_bits: int = 8) -> None:
        super().__init__(name, offset, width_bits)
        self.transmitted = bytearray()

    def reset(self) -> None:
        self.transmitted.clear()

    def read(self, reg: int) -> int:
        if reg == TX_DATA:
            return 0
        if reg == STATUS:
            return STATUS_TX_READY
        raise self.fault(reg, "registro inexistente")

    def write(self, reg: int, value: int, mask: int) -> None:
        if reg == TX_DATA:
            char_code = value & mask & 0xFF
            self.transmitted.append(char_code)
            self.emit(EvtUartOutput(char_code))
        elif reg == STATUS:
            raise self.fault(reg, "STATUS es de sólo lectura")
        else:
            raise self.fault(reg, "registro inexistente")
