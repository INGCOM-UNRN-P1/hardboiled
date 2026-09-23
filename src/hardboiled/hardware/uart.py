"""UART virtual: transmisión a la consola y recepción desde el teclado.

Registros:
    +0x0 TX_DATA  escritura: byte a transmitir
    +0x4 STATUS   bit 0: listo para transmitir; bit 1: hay un byte recibido
    +0x8 RX_DATA  lectura: siguiente byte recibido (0 si no hay)
    +0xC CTRL     bit 0: pedir la IRQ mientras haya bytes recibidos
"""

from __future__ import annotations

from collections import deque
from collections.abc import Callable

from hardboiled.core.events import EvtUartOutput
from hardboiled.hardware.bus import Peripheral, merge

TX_DATA = 0x0
STATUS = 0x4
RX_DATA = 0x8
CTRL = 0xC
STATUS_TX_READY = 1 << 0
STATUS_RX_AVAILABLE = 1 << 1
CTRL_RX_IRQ = 1 << 0
RX_CAPACITY = 1024  # bytes que la UART retiene sin leer (lo que exceda se pierde)


class Uart(Peripheral):
    kind = "uart"
    size = 16

    def __init__(
        self,
        name: str,
        offset: int,
        width_bits: int = 8,
        irq_line: int | None = None,
        raise_irq: Callable[[int], None] | None = None,
        lower_irq: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(name, offset, width_bits)
        self.irq_line = irq_line
        self._raise_irq = raise_irq
        self._lower_irq = lower_irq
        self.transmitted = bytearray()
        self.received: deque[int] = deque()
        self.ctrl = 0
        self.overrun = 0

    def reset(self) -> None:
        self.transmitted.clear()
        self.received.clear()
        self.ctrl = 0
        self.overrun = 0

    # ------------------------------------------------------------- recepción

    def receive(self, data: bytes) -> None:
        """Bytes que llegan desde fuera (teclado de la TUI, stdin, un guion)."""
        for byte in data:
            if len(self.received) >= RX_CAPACITY:
                self.overrun += 1
                continue
            self.received.append(byte)
        self._request_irq()

    def _request_irq(self) -> None:
        # Por nivel: la línea está pedida mientras haya datos y la IRQ esté habilitada,
        # y deja de estarlo en cuanto se vacía el buffer o se deshabilita.
        if self.irq_line is None:
            return
        if self.received and self.ctrl & CTRL_RX_IRQ:
            if self._raise_irq is not None:
                self._raise_irq(self.irq_line)
        elif self._lower_irq is not None:
            self._lower_irq(self.irq_line)

    def can_wake(self) -> bool:
        """¿Puede despertar a la CPU con datos que todavía no llegaron?"""
        return bool(self.ctrl & CTRL_RX_IRQ) and self.irq_line is not None

    # ------------------------------------------------------------ registros

    def read(self, reg: int) -> int:
        if reg == TX_DATA:
            return 0
        if reg == STATUS:
            return STATUS_TX_READY | (STATUS_RX_AVAILABLE if self.received else 0)
        if reg == RX_DATA:
            value = self.received.popleft() if self.received else 0
            self._request_irq()
            return value
        if reg == CTRL:
            return self.ctrl
        raise self.fault(reg, "registro inexistente")

    def write(self, reg: int, value: int, mask: int) -> None:
        if reg == TX_DATA:
            char_code = value & mask & 0xFF
            self.transmitted.append(char_code)
            self.emit(EvtUartOutput(char_code))
        elif reg == CTRL:
            self.ctrl = merge(self.ctrl, value, mask) & CTRL_RX_IRQ
            self._request_irq()
        elif reg in (STATUS, RX_DATA):
            raise self.fault(reg, "registro de sólo lectura")
        else:
            raise self.fault(reg, "registro inexistente")
