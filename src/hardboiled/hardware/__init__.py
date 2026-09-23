"""Periféricos simulados de la placa."""

from __future__ import annotations

from collections.abc import Callable

from hardboiled.hardware.bus import Clock, MmioBus, MmioFault, Peripheral
from hardboiled.hardware.buttons import ButtonBank
from hardboiled.hardware.gpio import LedBar, SwitchBank
from hardboiled.hardware.timer import Timer
from hardboiled.hardware.uart import Uart

__all__ = [
    "ButtonBank",
    "Clock",
    "LedBar",
    "MmioBus",
    "MmioFault",
    "Peripheral",
    "SwitchBank",
    "Timer",
    "Uart",
    "build_peripheral",
]


def build_peripheral(
    kind: str,
    name: str,
    offset: int,
    width_bits: int,
    irq_line: int | None,
    raise_irq: Callable[[int], None],
    lower_irq: Callable[[int], None] | None = None,
) -> Peripheral:
    if kind == "gpio_out":
        return LedBar(name, offset, width_bits)
    if kind == "gpio_in":
        return SwitchBank(name, offset, width_bits)
    if kind == "uart":
        return Uart(name, offset, irq_line=irq_line, raise_irq=raise_irq, lower_irq=lower_irq)
    if kind == "timer":
        return Timer(name, offset, irq_line, raise_irq)
    if kind == "gpio_irq":
        return ButtonBank(name, offset, width_bits, irq_line, raise_irq, lower_irq)
    raise ValueError(f"tipo de periférico desconocido: {kind}")
