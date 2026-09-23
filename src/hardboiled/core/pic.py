"""Controlador de interrupciones virtual (Virtual PIC).

Mantiene la máscara `irq_enable`, las solicitudes `irq_pending` y el
habilitador global. Se expone al firmware como un periférico MMIO más:

    +0x0 ENABLE   máscara de líneas habilitadas (lectura/escritura)
    +0x4 PENDING  solicitudes pendientes (escribir 1 limpia el bit)
    +0x8 GLOBAL   bit 0: interrupciones habilitadas globalmente

La inyección de contexto (guardar registros en la pila, saltar al vector y
restaurar al ejecutar `mret`) la realiza la CPU consultando este controlador.
"""

from __future__ import annotations

from hardboiled.hardware.bus import Peripheral, merge

IRQ_LINES = 8
LINES_MASK = (1 << IRQ_LINES) - 1

ENABLE = 0x0
PENDING = 0x4
GLOBAL = 0x8


class InterruptController(Peripheral):
    kind = "pic"
    size = 12

    def __init__(self, name: str = "pic", offset: int = 0xF00) -> None:
        super().__init__(name, offset, IRQ_LINES)
        self.reset()

    def reset(self) -> None:
        self.irq_enable = 0
        self.irq_pending = 0
        self.global_enable = False
        self.active_line: int | None = None
        # `ready` se consulta en cada instrucción: se precalcula en cada cambio.
        self.ready = False

    @property
    def in_isr(self) -> bool:
        return self.active_line is not None

    def _update(self) -> None:
        self.ready = (
            self.global_enable
            and self.active_line is None
            and bool(self.irq_pending & self.irq_enable)
        )

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
        active = self.irq_pending & self.irq_enable
        if not active:
            return None
        return (active & -active).bit_length() - 1

    def acknowledge(self, line: int) -> None:
        """La CPU entra a la ISR de `line`: se consume la solicitud."""
        self.irq_pending &= ~(1 << line)
        self.active_line = line
        self._update()

    def complete(self) -> None:
        """La ISR terminó (`mret`)."""
        self.active_line = None
        self._update()

    def read(self, reg: int) -> int:
        if reg == ENABLE:
            return self.irq_enable
        if reg == PENDING:
            return self.irq_pending
        if reg == GLOBAL:
            return int(self.global_enable)
        raise self.fault(reg, "registro inexistente")

    def write(self, reg: int, value: int, mask: int) -> None:
        if reg == ENABLE:
            self.irq_enable = merge(self.irq_enable, value, mask) & LINES_MASK
        elif reg == PENDING:
            self.irq_pending &= ~(value & mask)
        elif reg == GLOBAL:
            self.global_enable = bool(merge(int(self.global_enable), value, mask) & 1)
        else:
            raise self.fault(reg, "registro inexistente")
        self._update()
