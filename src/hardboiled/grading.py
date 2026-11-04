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

Para firmware que no termina (un lazo infinito atendiendo interrupciones), el caso
corre hasta un ciclo y se juzga ahí, con puntos de control en el camino:

    [[case]]
    name = "el botón enciende el LED"
    until_ms = 50                 # o until_cycle: no es una falla que no termine
    [[case.at]]
    ms = 10
    press = [0]
    [[case.check]]                # oráculos en un momento dado (deterministas)
    ms = 5
    leds = 0b0000
    [[case.check]]
    ms = 20
    leds = 0b1000
    gpio_high = [3]
    uart_contains = ["presionado"]
"""

from __future__ import annotations

import difflib
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Self

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from hardboiled.core.cpu import StopInfo, StopReason
from hardboiled.core.machine import Machine
from hardboiled.hardware import LedBar, SevenSegment
from hardboiled.script import InputScript, ScriptError, ScriptPlayer, Step, load_script


class SuiteError(Exception):
    pass


class Check(BaseModel):
    """Lo que se espera ver en un ciclo (o un momento) dado de la ejecución."""

    model_config = ConfigDict(extra="forbid")

    cycle: int | None = Field(default=None, ge=0)
    ms: float | None = Field(default=None, ge=0)
    leds: int | None = Field(default=None, ge=0)
    display: str | None = None
    gpio_high: list[int] = Field(default_factory=list)
    gpio_low: list[int] = Field(default_factory=list)
    uart_contains: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> Self:
        if (self.cycle is None) == (self.ms is None):
            raise ValueError("cada control necesita `cycle` o `ms` (uno solo)")
        if (
            self.leds is None
            and self.display is None
            and not self.gpio_high
            and not self.gpio_low
            and not self.uart_contains
        ):
            raise ValueError(
                "el control no verifica nada: falta `leds`, `display`, `gpio_*` o `uart_contains`"
            )
        return self


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
    check: list[Check] = Field(default_factory=list)  # oráculos en ciclos dados
    until_cycle: int | None = Field(default=None, gt=0)  # correr hasta acá y juzgar
    until_ms: float | None = Field(default=None, gt=0)

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
        if self.until_cycle is not None and self.until_ms is not None:
            raise ValueError("until_cycle y until_ms se excluyen")
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


class _Recorder:
    """Fuente del bus que toma el estado de los periféricos en el ciclo de cada control y,
    con `until`, pide detener la ejecución al llegar a ese ciclo."""

    def __init__(
        self, machine: Machine, checks: list[tuple[int, Check]], until: int | None
    ) -> None:
        self.machine = machine
        self.pending = sorted(checks, key=lambda item: item[0])
        self.until = until
        self.reached = False
        self.seen: list[tuple[int, Check, dict[str, Any]]] = []

    def next_deadline(self) -> int | None:
        candidates = [self.pending[0][0]] if self.pending else []
        if self.until is not None and not self.reached:
            candidates.append(self.until)
        return min(candidates) if candidates else None

    def service(self, cycle: int) -> None:
        while self.pending and self.pending[0][0] <= cycle:
            at, check = self.pending.pop(0)
            self.seen.append((at, check, self._state()))
        if self.until is not None and cycle >= self.until:
            self.reached = True

    def _state(self) -> dict[str, Any]:
        machine = self.machine
        leds = next((p for p in machine.peripherals if isinstance(p, LedBar)), None)
        display = next((p for p in machine.peripherals if isinstance(p, SevenSegment)), None)
        gpio = machine.gpio()
        uart = machine.uart()
        return {
            "leds": leds.value if leds is not None else None,
            "display": display.text() if display is not None else None,
            "gpio": gpio.level if gpio is not None else None,
            "uart": bytes(uart.transmitted).decode("utf-8", "replace") if uart is not None else "",
        }

    def reset(self) -> None:  # una sola corrida por caso: no se rebobina
        pass

    def snapshot(self) -> dict[str, Any]:
        return {}

    def restore(self, state: dict[str, Any]) -> None:
        pass


def _a_ciclo(cycle: int | None, ms: float | None, clock_hz: int | None, que: str) -> int:
    if cycle is not None:
        return cycle
    if not clock_hz:
        raise SuiteError(f"{que}: `ms` necesita clock_hz en [board]; usá `cycle`")
    return round((ms or 0) * clock_hz / 1000)


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
    checks: int = 0  # controles evaluados


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
        recorder = None
        poll = cpu.poll
        if case.check or case.until_cycle is not None or case.until_ms is not None:
            checks = [
                (_a_ciclo(c.cycle, c.ms, self.clock_hz, f"{case.name}: control {n}"), c)
                for n, c in enumerate(case.check, start=1)
            ]
            until = None
            if case.until_cycle is not None or case.until_ms is not None:
                until = _a_ciclo(case.until_cycle, case.until_ms, self.clock_hz, case.name)
            self._check_hardware(case, checks)
            recorder = _Recorder(machine, checks, until)
            machine.bus.add_source(recorder)
            if until is not None:
                cpu.poll = lambda: recorder.reached
        cpu.refresh_deadline()
        try:
            stop = machine.debugger.continue_()
        finally:
            cpu.poll = poll
        return self._judge(case, stop, recorder)

    def _check_hardware(self, case: Case, checks: list[tuple[int, Check]]) -> None:
        machine = self.machine
        gpio = machine.gpio()
        for _, check in checks:
            if check.leds is not None and not any(
                isinstance(p, LedBar) for p in machine.peripherals
            ):
                raise SuiteError(f"{case.name}: la placa no tiene LEDs")
            if check.display is not None and not any(
                isinstance(p, SevenSegment) for p in machine.peripherals
            ):
                raise SuiteError(f"{case.name}: la placa no tiene display")
            pins = check.gpio_high + check.gpio_low
            if pins and gpio is None:
                raise SuiteError(f"{case.name}: la placa no tiene GPIO bidireccional")
            if gpio is not None and any(not 0 <= pin < gpio.width_bits for pin in pins):
                raise SuiteError(f"{case.name}: un control usa un pin que el GPIO no tiene")

    def _momento(self, cycle: int) -> str:
        if self.clock_hz:
            return f"a los {cycle:,} ciclos ({cycle * 1000 / self.clock_hz:g} ms)"
        return f"a los {cycle:,} ciclos"

    def _judge_checks(self, recorder: _Recorder, failures: list[str]) -> None:
        for cycle, check, estado in recorder.seen:
            cuando = self._momento(cycle)
            if check.leds is not None and estado["leds"] != check.leds:
                failures.append(
                    f"{cuando} los LEDs estaban en 0b{estado['leds']:08b}, "
                    f"se esperaba 0b{check.leds:08b}"
                )
            if (
                check.display is not None
                and (estado["display"] or "").strip() != check.display.strip()
            ):
                failures.append(
                    f"{cuando} el display mostraba {(estado['display'] or '').strip()!r}, "
                    f"se esperaba {check.display.strip()!r}"
                )
            for pin in check.gpio_high:
                if not (estado["gpio"] >> pin) & 1:
                    failures.append(f"{cuando} el pin {pin} del GPIO estaba en 0, se esperaba 1")
            for pin in check.gpio_low:
                if (estado["gpio"] >> pin) & 1:
                    failures.append(f"{cuando} el pin {pin} del GPIO estaba en 1, se esperaba 0")
            for fragment in check.uart_contains:
                if fragment not in estado["uart"]:
                    failures.append(f"{cuando} la UART todavía no había mostrado {fragment!r}")
        for cycle, _ in recorder.pending:
            failures.append(
                "el programa terminó antes del control de "
                f"{self._momento(cycle).removeprefix('a los ')}"
            )

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

    def _judge(self, case: Case, stop: StopInfo, recorder: _Recorder | None = None) -> CaseResult:
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
        llego = recorder is not None and recorder.reached and stop.reason is StopReason.PAUSED
        if llego:
            result.outcome = "until"  # corrió hasta el ciclo pedido: no es una falla
        if recorder is not None:
            result.checks = len(recorder.seen)
            self._judge_checks(recorder, failures)
        if llego:
            if case.expect_trap is not None:
                failures.append(
                    f"se esperaba la trampa {case.expect_trap} y el programa siguió corriendo"
                )
            if case.expect_exit is not None:
                failures.append(
                    f"se esperaba el código de salida {case.expect_exit} "
                    "y el programa siguió corriendo"
                )
        elif case.expect_trap is not None:
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
