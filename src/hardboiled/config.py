"""Esquema declarativo de la placa virtual (`board.toml`) validado con pydantic."""

from __future__ import annotations

import tomllib
from itertools import pairwise
from pathlib import Path
from typing import Annotated, Literal, Self

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, model_validator

from hardboiled.core.pic import IRQ_LINES, InterruptController
from hardboiled.hardware.buttons import ButtonBank
from hardboiled.hardware.gpio import LedBar, SwitchBank
from hardboiled.hardware.timer import Timer
from hardboiled.hardware.uart import Uart

PAGE = 0x1000
NULL_GUARD_END = 0x1_0000

PeripheralType = Literal["gpio_out", "gpio_in", "gpio_irq", "uart", "timer"]

# Tipos de periférico que pueden pedir una interrupción.
IRQ_CAPABLE = frozenset({"timer", "uart", "gpio_irq"})

PERIPHERAL_SIZES: dict[str, int] = {
    "gpio_out": LedBar.size,
    "gpio_in": SwitchBank.size,
    "gpio_irq": ButtonBank.size,
    "uart": Uart.size,
    "timer": Timer.size,
}


def _parse_int(value: object) -> object:
    """Acepta enteros o cadenas en cualquier base de Python ("0x4000_0000")."""
    if isinstance(value, str):
        try:
            return int(value.replace("_", ""), 0)
        except ValueError as exc:
            raise ValueError(f"entero inválido: {value!r}") from exc
    return value


HexInt = Annotated[int, BeforeValidator(_parse_int), Field(ge=0, le=0xFFFF_FFFF)]


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class BoardInfo(_Model):
    name: str = "hardboiled-default"
    arch: Literal["riscv32"] = "riscv32"
    max_instructions: int = Field(default=1_000_000, gt=0)
    # Frecuencia nominal: si se indica, la emulación se acompasa al reloj real
    # (útil para ver parpadear LEDs). Sin valor, corre tan rápido como puede.
    clock_hz: int | None = Field(default=None, gt=0)


class MemoryConfig(_Model):
    flash_base: HexInt = 0x0001_0000
    flash_size_kb: int = Field(default=64, gt=0)
    sram_base: HexInt = 0x2000_0000
    sram_size_kb: int = Field(default=64, gt=0)
    mmio_base: HexInt = 0x4000_0000
    mmio_size_kb: int = Field(default=4, gt=0)

    @property
    def flash_size(self) -> int:
        return self.flash_size_kb * 1024

    @property
    def sram_size(self) -> int:
        return self.sram_size_kb * 1024

    @property
    def sram_end(self) -> int:
        return self.sram_base + self.sram_size

    @property
    def mmio_size(self) -> int:
        return self.mmio_size_kb * 1024

    def regions(self) -> dict[str, tuple[int, int]]:
        return {
            "flash": (self.flash_base, self.flash_size),
            "sram": (self.sram_base, self.sram_size),
            "mmio": (self.mmio_base, self.mmio_size),
        }

    @model_validator(mode="after")
    def _check_layout(self) -> Self:
        regions = sorted(self.regions().items(), key=lambda item: item[1][0])
        for name, (base, size) in regions:
            if base % PAGE or size % PAGE:
                raise ValueError(f"la región {name} debe estar alineada a 4 KB")
            if base < NULL_GUARD_END:
                raise ValueError(
                    f"la región {name} invade la zona de trampa de punteros nulos "
                    f"(0x0 - 0x{NULL_GUARD_END - 1:x})"
                )
            if base + size > 1 << 32:
                raise ValueError(f"la región {name} excede el espacio de 32 bits")
        for (name_a, (base_a, size_a)), (name_b, (base_b, _)) in pairwise(regions):
            if base_a + size_a > base_b:
                raise ValueError(f"las regiones {name_a} y {name_b} se superponen")
        return self


class PeripheralConfig(_Model):
    name: str = Field(min_length=1)
    type: PeripheralType
    offset: HexInt
    width_bits: int = Field(default=32, ge=1, le=32)
    irq_line: int | None = Field(default=None, ge=0, lt=IRQ_LINES)

    @property
    def size(self) -> int:
        return PERIPHERAL_SIZES[self.type]

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.offset % 4:
            raise ValueError(f"{self.name}: el offset debe estar alineado a 4 bytes")
        if self.irq_line is not None and self.type not in IRQ_CAPABLE:
            capable = ", ".join(sorted(IRQ_CAPABLE))
            raise ValueError(f"{self.name}: sólo generan interrupciones: {capable}")
        return self


class PicConfig(_Model):
    offset: HexInt = 0xF00


def _default_peripherals() -> tuple[PeripheralConfig, ...]:
    return (
        PeripheralConfig(name="leds", type="gpio_out", offset=0x00, width_bits=8),
        PeripheralConfig(name="switches", type="gpio_in", offset=0x04, width_bits=4),
        PeripheralConfig(name="uart0", type="uart", offset=0x10, irq_line=1),
        PeripheralConfig(name="timer0", type="timer", offset=0x20, irq_line=0),
        PeripheralConfig(name="buttons", type="gpio_irq", offset=0x30, width_bits=4, irq_line=2),
    )


class BoardConfig(_Model):
    board: BoardInfo = BoardInfo()
    memory: MemoryConfig = MemoryConfig()
    pic: PicConfig = PicConfig()
    peripherals: tuple[PeripheralConfig, ...] = Field(default_factory=_default_peripherals)

    @model_validator(mode="after")
    def _check_peripherals(self) -> Self:
        spans = [(p.name, p.offset, p.size) for p in self.peripherals]
        spans.append(("pic", self.pic.offset, InterruptController.size))
        names = [name for name, _, _ in spans]
        duplicated = {n for n in names if names.count(n) > 1}
        if duplicated:
            raise ValueError(f"nombres de periférico repetidos: {', '.join(sorted(duplicated))}")
        spans.sort(key=lambda span: span[1])
        for name, offset, size in spans:
            if offset + size > self.memory.mmio_size:
                raise ValueError(f"{name} queda fuera del espacio MMIO")
        for (name_a, off_a, size_a), (name_b, off_b, _) in pairwise(spans):
            if off_a + size_a > off_b:
                raise ValueError(f"los periféricos {name_a} y {name_b} se superponen")
        lines = [p.irq_line for p in self.peripherals if p.irq_line is not None]
        if len(lines) != len(set(lines)):
            raise ValueError("dos periféricos comparten la misma línea de IRQ")
        return self


def load_board(path: str | Path) -> BoardConfig:
    """Lee y valida un `board.toml`. Lanza `pydantic.ValidationError` o `TOMLDecodeError`."""
    with Path(path).open("rb") as stream:
        data = tomllib.load(stream)
    return BoardConfig.model_validate(data)
