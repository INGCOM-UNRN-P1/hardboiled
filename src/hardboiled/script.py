"""Guion de entrada: estímulos a los periféricos en ciclos dados.

Permite probar firmware interactivo de forma reproducible (sin TUI):

    # entrada.toml
    [[at]]
    cycle = 20_000
    switches = 0b0101        # valor de todos los switches

    [[at]]
    ms = 5                   # milisegundos: requiere clock_hz en [board]
    uart = "hola\\n"          # bytes que llegan por la UART

    [[at]]
    cycle = 90_000
    press = [0, 3]           # botones que se aprietan (se sueltan solos)

    [[at]]
    cycle = 120_000
    gpio_high = [2]          # pines del GPIO que se manejan desde afuera a 1…
    gpio_low = [5]           # …a 0
    gpio_float = [7]         # …o que se sueltan (leen el pull-up, si hay)

    [[at]]
    cycle = 150_000
    adc = [[0, 1650]]        # potenciómetros del ADC: [canal, milivoltios]

El guion se conecta al bus como una fuente con vencimientos: `wfi` adelanta el
reloj hasta el próximo estímulo, igual que hasta el próximo tick de un timer.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

if TYPE_CHECKING:
    from hardboiled.core.machine import Machine


class ScriptError(Exception):
    pass


class Step(BaseModel):
    model_config = ConfigDict(extra="forbid")

    cycle: int | None = Field(default=None, ge=0)
    ms: float | None = Field(default=None, ge=0)
    switches: int | None = Field(default=None, ge=0)
    uart: str | None = None
    press: list[int] = Field(default_factory=list)
    gpio_high: list[int] = Field(default_factory=list)
    gpio_low: list[int] = Field(default_factory=list)
    gpio_float: list[int] = Field(default_factory=list)
    adc: list[tuple[int, int]] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _single_press(cls, data: Any) -> Any:
        if isinstance(data, dict):
            for key in ("press", "gpio_high", "gpio_low", "gpio_float"):
                if isinstance(data.get(key), int):
                    data = {**data, key: [data[key]]}
        return data

    @property
    def gpio(self) -> list[tuple[int, int | None]]:
        """(pin, nivel) de cada pin del GPIO que cambia en este paso (None: se suelta)."""
        return (
            [(pin, 1) for pin in self.gpio_high]
            + [(pin, 0) for pin in self.gpio_low]
            + [(pin, None) for pin in self.gpio_float]
        )

    @model_validator(mode="after")
    def _check(self) -> Self:
        if (self.cycle is None) == (self.ms is None):
            raise ValueError("cada paso necesita `cycle` o `ms` (uno solo)")
        if (
            self.switches is None
            and self.uart is None
            and not (self.press or self.gpio or self.adc)
        ):
            raise ValueError(
                "el paso no hace nada: falta `switches`, `uart`, `press`, `gpio_*` o `adc`"
            )
        return self

    def describe(self) -> str:
        parts = []
        if self.switches is not None:
            parts.append(f"switches = 0b{self.switches:b}")
        if self.uart is not None:
            parts.append(f"uart {self.uart!r}")
        if self.press:
            parts.append("botón " + ", ".join(str(pin) for pin in self.press))
        for nombre, pins in (
            ("alto", self.gpio_high),
            ("bajo", self.gpio_low),
            ("suelto", self.gpio_float),
        ):
            if pins:
                parts.append(f"gpio {', '.join(str(pin) for pin in pins)} {nombre}")
        for channel, millivolts in self.adc:
            parts.append(f"adc {channel} = {millivolts} mV")
        return "; ".join(parts)


class InputScript(BaseModel):
    model_config = ConfigDict(extra="forbid")

    at: list[Step] = Field(default_factory=list)


def load_script(path: str | Path) -> InputScript:
    path = Path(path)
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
        return InputScript.model_validate(data)
    except OSError as exc:
        raise ScriptError(f"no se pudo leer el guion {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ScriptError(f"{path}: TOML inválido: {exc}") from exc
    except ValidationError as exc:
        details = "\n".join(
            f"  - {'.'.join(str(p) for p in error['loc']) or '(raíz)'}: {error['msg']}"
            for error in exc.errors()
        )
        raise ScriptError(f"{path}: guion inválido\n{details}") from exc


@dataclass(frozen=True)
class Applied:
    cycle: int
    description: str


class ScriptPlayer:
    """Fuente temporal del bus que aplica los pasos del guion a su ciclo."""

    def __init__(self, machine: Machine, script: InputScript, clock_hz: int | None) -> None:
        self._switches = machine.switches()
        self._uart = machine.uart()
        self._buttons = machine.buttons()
        self._gpio = machine.gpio()
        self._adc = machine.adc()
        steps = []
        for number, step in enumerate(script.at, start=1):
            if step.cycle is not None:
                cycle = step.cycle
            else:
                if not clock_hz:
                    raise ScriptError(
                        f"paso {number}: `ms` necesita clock_hz en [board]; usá `cycle`"
                    )
                cycle = round((step.ms or 0) * clock_hz / 1000)
            self._check(number, step)
            steps.append((cycle, step))
        steps.sort(key=lambda item: item[0])  # estable: a igual ciclo, orden del archivo
        self.steps = steps
        self.applied: list[Applied] = []
        self._next = 0

    def _check(self, number: int, step: Step) -> None:
        if step.switches is not None and self._switches is None:
            raise ScriptError(f"paso {number}: la placa no tiene switches")
        if step.uart is not None and self._uart is None:
            raise ScriptError(f"paso {number}: la placa no tiene UART")
        if step.press:
            if self._buttons is None:
                raise ScriptError(f"paso {number}: la placa no tiene botones")
            bad = [pin for pin in step.press if not 0 <= pin < self._buttons.width_bits]
            if bad:
                raise ScriptError(f"paso {number}: no existe el botón {bad[0]}")
        if step.gpio:
            if self._gpio is None:
                raise ScriptError(f"paso {number}: la placa no tiene GPIO bidireccional")
            bad = [pin for pin, _ in step.gpio if not 0 <= pin < self._gpio.width_bits]
            if bad:
                raise ScriptError(f"paso {number}: no existe el pin {bad[0]} del GPIO")
        if step.adc:
            if self._adc is None:
                raise ScriptError(f"paso {number}: la placa no tiene ADC")
            bad = [ch for ch, _ in step.adc if not 0 <= ch < self._adc.channels]
            if bad:
                raise ScriptError(f"paso {number}: no existe el canal {bad[0]} del ADC")

    @property
    def pending(self) -> int:
        return len(self.steps) - self._next

    def next_deadline(self) -> int | None:
        return self.steps[self._next][0] if self._next < len(self.steps) else None

    def service(self, cycle: int) -> None:
        while self._next < len(self.steps) and self.steps[self._next][0] <= cycle:
            _, step = self.steps[self._next]
            self._next += 1
            if step.switches is not None and self._switches is not None:
                self._switches.set_value(step.switches)
            if step.uart is not None and self._uart is not None:
                self._uart.receive(step.uart.encode())
            if self._buttons is not None:
                for pin in step.press:
                    self._buttons.press(pin)
            if self._gpio is not None:
                for pin, level in step.gpio:
                    self._gpio.drive(pin, level)
            if self._adc is not None:
                for channel, millivolts in step.adc:
                    self._adc.set_millivolts(channel, millivolts)
            self.applied.append(Applied(cycle, step.describe()))

    def reset(self) -> None:
        self._next = 0
        self.applied = []

    def snapshot(self) -> dict[str, Any]:
        return {"next": self._next, "applied": list(self.applied)}

    def restore(self, state: dict[str, Any]) -> None:
        self._next = state["next"]
        self.applied = list(state["applied"])


def attach_script(machine: Machine, path: str | Path, clock_hz: int | None) -> ScriptPlayer:
    player = ScriptPlayer(machine, load_script(path), clock_hz)
    machine.bus.add_source(player)
    machine.cpu.refresh_deadline()
    return player
