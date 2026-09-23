"""Casos de prueba con salida esperada, para corregir trabajos prácticos.

Un caso fija las entradas (switches, bytes por la UART, un guion de estímulos)
y lo que se espera (salida de la UART, código de salida o una trampa). Una
suite es un TOML con varios casos:

    # casos.toml
    [[case]]
    name = "suma chica"
    switches = 0b0011
    uart_input = "2 3\\n"
    expect_uart = "5\\n"
    expect_exit = 0

    [[case]]
    name = "sin datos"
    expect_trap = "wfi-deadlock"

El programa se carga una vez y cada caso arranca de un Reset.
"""

from __future__ import annotations

import difflib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from hardboiled.core.cpu import StopInfo, StopReason
from hardboiled.core.machine import Machine
from hardboiled.hardware import LedBar, SevenSegment
from hardboiled.script import InputScript, ScriptError, ScriptPlayer, Step, load_script


class SuiteError(Exception):
    pass


class Case(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = ""
    switches: int | None = Field(default=None, ge=0)
    uart_input: str | None = None
    uart_input_file: Path | None = None
    script: Path | None = None
    at: list[Step] = Field(default_factory=list)  # guion en línea
    max_instructions: int | None = Field(default=None, gt=0)
    expect_uart: str | None = None
    expect_uart_file: Path | None = None
    expect_uart_contains: list[str] = Field(default_factory=list)
    expect_exit: int | None = None
    expect_trap: str | None = None
    expect_leds: int | None = Field(default=None, ge=0)  # valor final de los LEDs
    expect_display: str | None = None  # lo que muestra el display (sin blancos a los lados)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if self.uart_input is not None and self.uart_input_file is not None:
            raise ValueError("uart_input y uart_input_file se excluyen")
        if self.expect_uart is not None and self.expect_uart_file is not None:
            raise ValueError("expect_uart y expect_uart_file se excluyen")
        if self.script is not None and self.at:
            raise ValueError("script y [[case.at]] se excluyen")
        if self.expect_trap is not None and self.expect_exit is not None:
            raise ValueError("un caso no puede esperar a la vez una trampa y un código de salida")
        return self

    def resolved(self, base: Path) -> Case:
        """Con las rutas relativas a `base` (el directorio de la suite)."""

        def fix(path: Path | None) -> Path | None:
            return None if path is None or path.is_absolute() else base / path

        return self.model_copy(
            update={
                "uart_input_file": fix(self.uart_input_file) or self.uart_input_file,
                "script": fix(self.script) or self.script,
                "expect_uart_file": fix(self.expect_uart_file) or self.expect_uart_file,
            }
        )


class Suite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case: list[Case] = Field(min_length=1)


def load_suite(path: str | Path) -> list[Case]:
    path = Path(path)
    try:
        suite = Suite.model_validate(tomllib.loads(path.read_text(encoding="utf-8")))
    except OSError as exc:
        raise SuiteError(f"no se pudo leer {path}: {exc}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise SuiteError(f"{path}: TOML inválido: {exc}") from exc
    except ValidationError as exc:
        details = "\n".join(
            f"  - {'.'.join(str(p) for p in error['loc']) or '(raíz)'}: {error['msg']}"
            for error in exc.errors()
        )
        raise SuiteError(f"{path}: suite inválida\n{details}") from exc
    cases = []
    for number, case in enumerate(suite.case, start=1):
        named = case if case.name else case.model_copy(update={"name": f"caso {number}"})
        cases.append(named.resolved(path.parent))
    return cases


@dataclass
class CaseResult:
    name: str
    passed: bool
    failures: list[str] = field(default_factory=list)
    outcome: str = ""  # "exited", "trap", "limit", "paused"
    exit_code: int | None = None
    trap: str | None = None
    message: str = ""
    uart: str = ""
    leds: int | None = None
    display: str | None = None
    instructions: int = 0
    cycles: int = 0


def _read(path: Path, what: str) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        raise SuiteError(f"no se pudo leer {what} {path}: {exc}") from exc


def uart_diff(expected: str, actual: str) -> str:
    """Diferencias línea por línea, mostrando los finales de línea."""
    lines = difflib.unified_diff(
        expected.splitlines(keepends=True),
        actual.splitlines(keepends=True),
        "esperado",
        "obtenido",
        lineterm="",
    )
    return "\n".join(line.rstrip("\n") + ("⏎" if line.endswith("\n") else "") for line in lines)


class Grader:
    def __init__(self, machine: Machine, clock_hz: int | None) -> None:
        self.machine = machine
        self.clock_hz = clock_hz  # nominal, para los `ms` de los guiones
        self._quota = machine.cpu.quota_step
        machine.cpu.set_clock(None)  # sin interfaz: correr sin pausas

    def run(self, case: Case) -> CaseResult:
        machine = self.machine
        cpu = machine.cpu
        machine.bus.sources.clear()
        cpu.quota_step = case.max_instructions or self._quota
        machine.reset()
        bank = machine.switches()
        if case.switches is not None and bank is None:
            raise SuiteError(f"{case.name}: la placa no tiene switches")
        if bank is not None:
            # Reset no mueve las entradas físicas: cada caso arranca con las suyas (o en 0).
            bank.set_value(case.switches or 0)
        data = case.uart_input
        if case.uart_input_file is not None:
            data = _read(case.uart_input_file, "la entrada")
        if data is not None:
            uart = machine.uart()
            if uart is None:
                raise SuiteError(f"{case.name}: la placa no tiene UART")
            uart.receive(data.encode())
        try:
            script = (
                load_script(case.script) if case.script is not None else InputScript(at=case.at)
            )
            if script.at:
                machine.bus.add_source(ScriptPlayer(machine, script, self.clock_hz))
        except ScriptError as exc:
            raise SuiteError(f"{case.name}: {exc}") from exc
        cpu.refresh_deadline()
        stop = machine.debugger.continue_()
        return self._judge(case, stop)

    def _where(self, stop: StopInfo) -> str:
        """` (en suma(), main.c:44)` para ubicar una trampa o una detención."""
        if stop.reason is StopReason.EXITED:
            return ""
        debugger = self.machine.debugger
        location = debugger.location(stop.pc)
        function = debugger.function(stop.pc)
        parts = [f"en {function}()" if function else ""]
        if location is not None:
            parts.append(f"{Path(location.file).name}:{location.line}")
        shown = ", ".join(part for part in parts if part)
        return f" ({shown})" if shown else ""

    def _judge(self, case: Case, stop: StopInfo) -> CaseResult:
        uart = self.machine.uart()
        output = bytes(uart.transmitted).decode("utf-8", "replace") if uart is not None else ""
        cpu = self.machine.cpu
        peripherals = self.machine.peripherals
        leds = next((p for p in peripherals if isinstance(p, LedBar)), None)
        display = next((p for p in peripherals if isinstance(p, SevenSegment)), None)
        result = CaseResult(
            case.name,
            passed=False,
            outcome=stop.reason.value,
            exit_code=stop.exit_code,
            trap=stop.kind if stop.reason is StopReason.TRAP else None,
            message=stop.message,
            uart=output,
            leds=leds.value if leds is not None else None,
            display=display.text() if display is not None else None,
            instructions=cpu.instructions,
            cycles=cpu.clock.cycles,
        )
        failures = result.failures
        what = stop.message + self._where(stop)
        if case.expect_trap is not None:
            if result.trap is None:
                failures.append(f"se esperaba la trampa {case.expect_trap}: {what}")
            elif case.expect_trap not in (result.trap, "*"):
                failures.append(
                    f"se esperaba la trampa {case.expect_trap} y ocurrió {result.trap}: {what}"
                )
        elif stop.reason is not StopReason.EXITED:
            failures.append(f"el programa no terminó: {what}")
        elif case.expect_exit is not None and stop.exit_code != case.expect_exit:
            failures.append(f"código de salida {stop.exit_code}, se esperaba {case.expect_exit}")
        expected = case.expect_uart
        if case.expect_uart_file is not None:
            expected = _read(case.expect_uart_file, "la salida esperada")
        if expected is not None and output != expected:
            failures.append("la salida por la UART no coincide:\n" + uart_diff(expected, output))
        for fragment in case.expect_uart_contains:
            if fragment not in output:
                failures.append(f"la salida por la UART no contiene {fragment!r}")
        if case.expect_leds is not None:
            if result.leds is None:
                failures.append("la placa no tiene LEDs")
            elif result.leds != case.expect_leds:
                failures.append(
                    f"los LEDs quedaron en 0b{result.leds:08b}, "
                    f"se esperaba 0b{case.expect_leds:08b}"
                )
        if case.expect_display is not None:
            shown = (result.display or "").strip()
            if result.display is None:
                failures.append("la placa no tiene display")
            elif shown != case.expect_display.strip():
                failures.append(
                    f"el display muestra {shown!r}, se esperaba {case.expect_display.strip()!r}"
                )
        result.passed = not failures
        return result
