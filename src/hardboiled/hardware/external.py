"""Periférico externo conectado vía streaming / socket o guion determinista."""

from __future__ import annotations

from typing import Any, ClassVar

from hardboiled.hardware.bus import Peripheral, merge
from hardboiled.i18n import N_


class ExternalPeripheral(Peripheral):
    """Periférico mapeado en MMIO cuyos registros se delegan a un proceso externo o guion."""

    kind: ClassVar[str] = "external"

    def __init__(
        self,
        name: str,
        offset: int,
        size: int = 16,
        irq_line: int | None = None,
        raise_irq: Any = None,
        lower_irq: Any = None,
    ) -> None:
        super().__init__(name, offset)
        self.size = size
        self.irq_line = irq_line
        self._raise_irq = raise_irq
        self._lower_irq = lower_irq
        # Registros sombra de 32 bits indexados por offset relativo en bytes (0, 4, 8, ...)
        self._registers: dict[int, int] = {reg: 0 for reg in range(0, size, 4)}
        self._write_log: list[tuple[int, int, int, int]] = []  # (cycle, reg, val, mask)

    def read(self, reg: int) -> int:
        """Lectura no bloqueante: retorna el valor actual del registro sombra."""
        if reg not in self._registers:
            raise self.fault(reg, N_("registro fuera del rango del periférico externo"))
        return self._registers[reg]

    def write(self, reg: int, value: int, mask: int) -> None:
        """Escritura: actualiza registro sombra y almacena el evento en el log de escrituras."""
        if reg not in self._registers:
            raise self.fault(reg, N_("registro fuera del rango del periférico externo"))
        self._registers[reg] = merge(self._registers[reg], value, mask)
        self._write_log.append((self.clock.cycles, reg, value, mask))

    def update_shadow(self, reg: int, value: int) -> None:
        """Actualiza el registro sombra desde el proceso externo o test fixture."""
        if reg not in self._registers:
            raise self.fault(reg, N_("registro fuera del rango del periférico externo"))
        self._registers[reg] = value & 0xFFFF_FFFF

    def trigger_irq(self, assert_level: bool = True) -> None:
        """Dispara o baja la línea de interrupción asociada si está configurada."""
        if self.irq_line is None:
            return
        if assert_level and self._raise_irq:
            self._raise_irq(self.irq_line)
        elif not assert_level and self._lower_irq:
            self._lower_irq(self.irq_line)

    def can_wake(self) -> bool:
        return self.irq_line is not None

    def reset(self) -> None:
        for reg in self._registers:
            self._registers[reg] = 0
        self._write_log.clear()
        if self.irq_line is not None and self._lower_irq:
            self._lower_irq(self.irq_line)

    def inspect(self) -> dict[str, int]:
        return {f"reg_0x{reg:02x}": val for reg, val in self._registers.items()}

    def snapshot(self) -> dict[str, Any]:
        return {
            "registers": dict(self._registers),
            "write_log": list(self._write_log),
        }

    def restore(self, state: dict[str, Any]) -> None:
        self._registers = dict(state["registers"])
        self._write_log = list(state["write_log"])
