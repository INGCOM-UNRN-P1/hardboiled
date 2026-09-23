"""Controlador de interrupciones virtual (Virtual PIC).

Mantiene la máscara `irq_enable`, las solicitudes `irq_pending` y el
habilitador global. Se expone al firmware como un periférico MMIO más:

    +0x0 ENABLE   máscara de líneas habilitadas (lectura/escritura)
    +0x4 PENDING  solicitudes pendientes (escribir 1 limpia el bit)
    +0x8 GLOBAL   bit 0: interrupciones habilitadas globalmente
    +0xC ACTIVE   línea que se está atendiendo (0xFFFFFFFF si ninguna)

Cada línea tiene una prioridad (menor número = más urgente; por defecto, el
número de línea). Sin anidamiento, mientras se atiende una IRQ las demás
esperan; con anidamiento, una IRQ de prioridad estrictamente mayor interrumpe
a la ISR en curso. Las ISR activas forman una pila.

La inyección de contexto (guardar registros en la pila, saltar al vector y
restaurar al ejecutar `mret`) la realiza la CPU consultando este controlador.
"""

from __future__ import annotations

from collections.abc import Sequence

from hardboiled.hardware.bus import Peripheral, merge
from hardboiled.i18n import N_

IRQ_LINES = 8
LINES_MASK = (1 << IRQ_LINES) - 1

ENABLE = 0x0
PENDING = 0x4
GLOBAL = 0x8
ACTIVE = 0xC
NO_ACTIVE = 0xFFFF_FFFF


class InterruptController(Peripheral):
    kind = "pic"
    size = 16

    def __init__(
        self,
        name: str = "pic",
        offset: int = 0xF00,
        priorities: Sequence[int] | None = None,
        nesting: bool = False,
    ) -> None:
        super().__init__(name, offset, IRQ_LINES)
        self.priorities = tuple(priorities) if priorities is not None else tuple(range(IRQ_LINES))
        if len(self.priorities) != IRQ_LINES:
            raise ValueError(f"se esperan {IRQ_LINES} prioridades")
        self.nesting = nesting
        self.reset()

    def reset(self) -> None:
        self.irq_enable = 0
        self.irq_pending = 0
        self.global_enable = False
        self.active: list[int] = []  # pila de líneas en atención (la última es la actual)
        # `ready` se consulta en cada instrucción: se precalcula en cada cambio.
        self.ready = False

    @property
    def in_isr(self) -> bool:
        return bool(self.active)

    @property
    def depth(self) -> int:
        """Cantidad de ISR anidadas en curso."""
        return len(self.active)

    @property
    def active_line(self) -> int | None:
        return self.active[-1] if self.active else None

    def _update(self) -> None:
        candidate = self.next_irq()
        if not self.global_enable or candidate is None:
            self.ready = False
        elif not self.active:
            self.ready = True
        else:
            current = self.priorities[self.active[-1]]
            self.ready = self.nesting and self.priorities[candidate] < current

    def raise_irq(self, line: int) -> None:
        if not 0 <= line < IRQ_LINES:
            raise ValueError(f"línea de IRQ inválida: {line}")
        self.irq_pending |= 1 << line
        self._update()

    def lower_irq(self, line: int) -> None:
        """Retira el pedido de una línea (periféricos que piden por nivel)."""
        if not 0 <= line < IRQ_LINES:
            raise ValueError(f"línea de IRQ inválida: {line}")
        self.irq_pending &= ~(1 << line)
        self._update()

    def wake_pending(self) -> bool:
        """¿Hay alguna IRQ habilitada pendiente? (condición de salida de `wfi`)."""
        return bool(self.irq_pending & self.irq_enable)

    def next_irq(self) -> int | None:
        """La línea pendiente y habilitada más urgente (a igual prioridad, la menor)."""
        active = self.irq_pending & self.irq_enable
        if not active:
            return None
        lines = [line for line in range(IRQ_LINES) if active >> line & 1]
        return min(lines, key=lambda line: (self.priorities[line], line))

    def acknowledge(self, line: int) -> None:
        """La CPU entra a la ISR de `line`: se consume la solicitud."""
        self.irq_pending &= ~(1 << line)
        self.active.append(line)
        self._update()

    def complete(self) -> None:
        """La ISR en curso terminó (`mret`)."""
        if self.active:
            self.active.pop()
        self._update()

    def read(self, reg: int) -> int:
        if reg == ENABLE:
            return self.irq_enable
        if reg == PENDING:
            return self.irq_pending
        if reg == GLOBAL:
            return int(self.global_enable)
        if reg == ACTIVE:
            return self.active[-1] if self.active else NO_ACTIVE
        raise self.fault(reg, N_("registro inexistente"))

    def write(self, reg: int, value: int, mask: int) -> None:
        if reg == ENABLE:
            self.irq_enable = merge(self.irq_enable, value, mask) & LINES_MASK
        elif reg == PENDING:
            self.irq_pending &= ~(value & mask)
        elif reg == GLOBAL:
            self.global_enable = bool(merge(int(self.global_enable), value, mask) & 1)
        elif reg == ACTIVE:
            raise self.fault(reg, N_("ACTIVE es de sólo lectura"))
        else:
            raise self.fault(reg, N_("registro inexistente"))
        self._update()
