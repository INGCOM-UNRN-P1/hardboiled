"""Temporizador con divisor de ciclos que genera IRQs periódicas."""

from __future__ import annotations

from collections.abc import Callable

from hardboiled.core.events import EvtHardwareUpdated
from hardboiled.hardware.bus import Peripheral, merge

CTRL = 0x0
RELOAD = 0x4
COUNT = 0x8
STATUS = 0xC

CTRL_ENABLE = 1 << 0
CTRL_IRQ = 1 << 1
STATUS_EXPIRED = 1 << 0


class Timer(Peripheral):
    """Cuenta ciclos de CPU; cada `RELOAD` ciclos vence, marca STATUS y pide su IRQ."""

    kind = "timer"
    size = 16

    def __init__(
        self,
        name: str,
        offset: int,
        irq_line: int | None = None,
        raise_irq: Callable[[int], None] | None = None,
    ) -> None:
        super().__init__(name, offset, 32)
        self.irq_line = irq_line
        self._raise_irq = raise_irq
        self.reset()

    def reset(self) -> None:
        self.ctrl = 0
        self.reload = 0
        self.status = 0
        self.expirations = 0
        self._next_fire: int | None = None

    @property
    def enabled(self) -> bool:
        return bool(self.ctrl & CTRL_ENABLE) and self.reload > 0

    def _rearm(self) -> None:
        self._next_fire = self.clock.cycles + self.reload if self.enabled else None

    def read(self, reg: int) -> int:
        if reg == CTRL:
            return self.ctrl
        if reg == RELOAD:
            return self.reload
        if reg == COUNT:
            if self._next_fire is None:
                return 0
            return max(0, self._next_fire - self.clock.cycles)
        if reg == STATUS:
            return self.status
        raise self.fault(reg, "registro inexistente")

    def write(self, reg: int, value: int, mask: int) -> None:
        if reg == CTRL:
            was_enabled = self.enabled
            self.ctrl = merge(self.ctrl, value, mask) & (CTRL_ENABLE | CTRL_IRQ)
            if self.enabled != was_enabled:
                self._rearm()
        elif reg == RELOAD:
            self.reload = merge(self.reload, value, mask)
            self._rearm()
        elif reg == STATUS:
            self.status &= ~(value & mask)  # write-1-to-clear
            return
        elif reg == COUNT:
            raise self.fault(reg, "COUNT es de sólo lectura")
        else:
            raise self.fault(reg, "registro inexistente")
        self.emit(EvtHardwareUpdated(self.name, reg, self.ctrl if reg == CTRL else self.reload))

    def inspect(self) -> dict[str, int]:
        return {
            "ctrl": self.ctrl,
            "reload": self.reload,
            "count": self.read(COUNT),
            "expirations": self.expirations,
            "status": self.status,
        }

    def next_deadline(self) -> int | None:
        return self._next_fire

    def service(self, cycle: int) -> None:
        if self._next_fire is None or cycle < self._next_fire:
            return
        periods = (cycle - self._next_fire) // self.reload + 1
        self._next_fire += periods * self.reload
        self.expirations += periods
        self.status |= STATUS_EXPIRED
        if self.ctrl & CTRL_IRQ and self.irq_line is not None and self._raise_irq is not None:
            self._raise_irq(self.irq_line)
