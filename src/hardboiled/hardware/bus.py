"""Despachador central MMIO.

El bus no conoce a Unicorn ni a la interfaz: recibe accesos (offset relativo a
la base MMIO, tamaño en bytes) y los reparte entre los periféricos conectados.
Los periféricos exponen registros de 32 bits alineados; los accesos de 8 y 16
bits se traducen a una palabra más una máscara de carril (byte lanes).
"""

from __future__ import annotations

import copy
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any, ClassVar, Protocol

from hardboiled.core.events import Event
from hardboiled.i18n import _

WORD_MASK = 0xFFFF_FFFF

EventSink = Callable[[Event], None]


def _discard(_event: Event) -> None:
    pass


class Clock:
    """Contador de ciclos compartido entre la CPU y los periféricos."""

    def __init__(self) -> None:
        self.cycles = 0


class MmioFault(Exception):
    """Acceso MMIO inválido (registro inexistente, solo lectura, desalineado)."""


def merge(old: int, value: int, mask: int) -> int:
    """Combina `value` sobre `old` sólo en los bits de `mask`."""
    return (old & ~mask) | (value & mask)


class Peripheral(ABC):
    """Dispositivo mapeado en el bus. Sus registros son palabras de 32 bits."""

    kind: ClassVar[str]
    size: ClassVar[int]

    def __init__(self, name: str, offset: int, width_bits: int = 32) -> None:
        self.name = name
        self.offset = offset
        self.width_bits = width_bits
        self.clock = Clock()
        self.emit: EventSink = _discard

    @abstractmethod
    def read(self, reg: int) -> int:
        """Lee el registro alineado `reg` (offset relativo al periférico)."""

    @abstractmethod
    def write(self, reg: int, value: int, mask: int) -> None:
        """Escribe `value` en los bits `mask` del registro alineado `reg`."""

    def reset(self) -> None:  # noqa: B027 - la mayoría no necesita resetear nada extra
        """Vuelve al estado de encendido."""

    def next_deadline(self) -> int | None:
        """Próximo ciclo en que el periférico necesita ser atendido, si hay."""
        return None

    def service(self, cycle: int) -> None:  # noqa: B027
        """Atiende los eventos temporales vencidos hasta `cycle`."""

    def can_wake(self) -> bool:
        """¿Puede pedir una interrupción por un estímulo externo (teclado, botón)?"""
        return False

    def inspect(self) -> dict[str, int]:
        """Estado interno para mostrar en la interfaz (vacío si no hay nada útil)."""
        return {}

    # Atributos que no son estado del dispositivo sino su conexión con el resto.
    _TRANSIENT: ClassVar[frozenset[str]] = frozenset({"clock", "emit", "_raise_irq", "_lower_irq"})

    def snapshot(self) -> dict[str, Any]:
        """Estado del dispositivo (copia) para poder volver atrás en el tiempo."""
        return {
            key: copy.copy(value)
            for key, value in vars(self).items()
            if key not in self._TRANSIENT and not callable(value)
        }

    def restore(self, state: dict[str, Any]) -> None:
        for key, value in state.items():
            setattr(self, key, copy.copy(value))

    def fault(self, reg: int, message: str) -> MmioFault:
        """`message` viene marcado con N_() y se traduce acá."""
        return MmioFault(f"{self.name}+0x{reg:02x}: {_(message)}")


class TimedSource(Protocol):
    """Algo que actúa en ciclos dados sin estar mapeado en el bus (p. ej. un guion
    de estímulos). Participa de los vencimientos igual que un periférico."""

    def next_deadline(self) -> int | None: ...
    def service(self, cycle: int) -> None: ...
    def reset(self) -> None: ...
    def snapshot(self) -> dict[str, Any]: ...
    def restore(self, state: dict[str, Any]) -> None: ...


class MmioBus:
    def __init__(self, size: int, clock: Clock | None = None) -> None:
        self.size = size
        self.clock = clock if clock is not None else Clock()
        self._devices: list[Peripheral] = []
        self.sources: list[TimedSource] = []
        self._emit: EventSink = _discard

    @property
    def devices(self) -> tuple[Peripheral, ...]:
        return tuple(self._devices)

    def set_event_sink(self, sink: EventSink) -> None:
        self._emit = sink
        for device in self._devices:
            device.emit = sink

    def attach(self, device: Peripheral) -> None:
        start, end = device.offset, device.offset + device.size
        if start < 0 or end > self.size:
            raise ValueError(f"{device.name} queda fuera del espacio MMIO")
        for other in self._devices:
            if start < other.offset + other.size and other.offset < end:
                raise ValueError(f"{device.name} se superpone con {other.name}")
        device.clock = self.clock
        device.emit = self._emit
        self._devices.append(device)

    def device(self, name: str) -> Peripheral:
        for device in self._devices:
            if device.name == name:
                return device
        raise KeyError(name)

    def add_source(self, source: TimedSource) -> None:
        self.sources.append(source)

    def reset(self) -> None:
        for device in self._devices:
            device.reset()
        for source in self.sources:
            source.reset()

    def _decode(self, offset: int, size: int) -> tuple[Peripheral, int, int, int]:
        if size not in (1, 2, 4):
            raise MmioFault(
                _(
                    "tamaño de acceso no soportado ({size} bytes) en {offset}",
                    size=size,
                    offset=f"0x{offset:03x}",
                )
            )
        if offset % size:
            raise MmioFault(
                _(
                    "acceso desalineado de {size} bytes en {offset}",
                    size=size,
                    offset=f"0x{offset:03x}",
                )
            )
        for device in self._devices:
            if device.offset <= offset < device.offset + device.size:
                reg = offset - device.offset
                shift = (reg & 3) * 8
                lane = ((1 << (size * 8)) - 1) << shift
                return device, reg & ~3, shift, lane
        raise MmioFault(
            _("no hay ningún periférico en el offset MMIO {offset}", offset=f"0x{offset:03x}")
        )

    def read(self, offset: int, size: int) -> int:
        device, reg, shift, lane = self._decode(offset, size)
        return (device.read(reg) & lane) >> shift

    def write(self, offset: int, size: int, value: int) -> None:
        device, reg, shift, lane = self._decode(offset, size)
        device.write(reg, (value << shift) & lane, lane)

    def next_deadline(self) -> int | None:
        timed = (*self._devices, *self.sources)
        deadlines = [d for d in (item.next_deadline() for item in timed) if d is not None]
        return min(deadlines) if deadlines else None

    def can_wake(self) -> bool:
        return any(device.can_wake() for device in self._devices)

    def service(self, cycle: int) -> None:
        # Primero los estímulos externos: lo que inyectan lo ven los periféricos.
        for item in (*self.sources, *self._devices):
            deadline = item.next_deadline()
            if deadline is not None and deadline <= cycle:
                item.service(cycle)
