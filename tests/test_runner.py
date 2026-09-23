"""Hilo de trabajo, protocolo de colas, TUI y restricciones de arquitectura."""

from __future__ import annotations

import ast
import os
import queue
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from hardboiled.config import BoardConfig, BoardInfo
from hardboiled.core.events import (
    CmdContinue,
    CmdPause,
    CmdReset,
    CmdRunToLine,
    CmdShutdown,
    CmdStepOver,
    CmdToggleBreakpoint,
    CmdToggleSwitch,
    Command,
    Event,
    EvtBreakpointsChanged,
    EvtCpuRunning,
    EvtCpuSuspended,
    EvtHardwareUpdated,
    EvtMessage,
    EvtProgramExited,
    EvtProgramLoaded,
    EvtTrap,
)
from hardboiled.core.machine import Machine
from hardboiled.core.runner import RunnerThread
from tests.conftest import FIXTURES, line_of

SRC = Path(__file__).parents[1] / "src" / "hardboiled"
TIMEOUT = 10


class Harness:
    def __init__(self, name: str, max_instructions: int = 1_000_000) -> None:
        board = BoardConfig(board=BoardInfo(max_instructions=max_instructions))
        self.machine = Machine.from_elf(FIXTURES / f"{name}.elf", board)
        self.cmd: queue.Queue[Command] = queue.Queue()
        self.evt: queue.Queue[Event] = queue.Queue()
        self.runner = RunnerThread(self.machine, self.cmd, self.evt)
        self.seen: list[Event] = []

    def wait_for[T](self, kind: type[T]) -> T:
        while True:
            event = self.evt.get(timeout=TIMEOUT)
            self.seen.append(event)
            if isinstance(event, kind):
                return event


HarnessFactory = Callable[..., Harness]


@pytest.fixture
def harness() -> Iterator[HarnessFactory]:
    created: list[Harness] = []

    def start(name: str, max_instructions: int = 1_000_000) -> Harness:
        h = Harness(name, max_instructions)
        h.runner.start()
        created.append(h)
        return h

    yield start
    for h in created:
        h.cmd.put(CmdShutdown())
        h.runner.join(TIMEOUT)
        assert not h.runner.is_alive()


def test_runner_boot_and_step(harness: HarnessFactory) -> None:
    h = harness("basic")
    loaded = h.wait_for(EvtProgramLoaded)
    assert any(f.endswith("basic.c") for f in loaded.source_files)
    assert {p.name for p in loaded.peripherals} == {"leds", "switches", "uart0", "timer0"}
    first = h.wait_for(EvtCpuSuspended)
    assert first.source_line == line_of("basic.c", "main_first")
    assert first.function == "main"

    h.cmd.put(CmdStepOver())
    h.wait_for(EvtCpuRunning)
    step = h.wait_for(EvtCpuSuspended)
    assert step.source_line == line_of("basic.c", "main_store")
    assert step.cycle_count > first.cycle_count


def test_runner_breakpoints_continue_and_exit(harness: HarnessFactory) -> None:
    h = harness("basic")
    h.wait_for(EvtCpuSuspended)
    h.cmd.put(CmdToggleBreakpoint(line_of("basic.c", "square_body")))
    changed = h.wait_for(EvtBreakpointsChanged)
    assert {line for _, line in changed.lines} == {line_of("basic.c", "square_body")}

    h.cmd.put(CmdContinue())
    hit = h.wait_for(EvtCpuSuspended)
    assert hit.function == "square" and hit.reason == "breakpoint"

    h.cmd.put(CmdToggleBreakpoint(line_of("basic.c", "square_body")))
    h.wait_for(EvtBreakpointsChanged)
    h.cmd.put(CmdContinue())
    exited = h.wait_for(EvtProgramExited)
    assert exited.exit_code == 134

    h.cmd.put(CmdStepOver())  # programa terminado: se avisa, no se ejecuta
    assert "Reset" in h.wait_for(EvtMessage).text

    h.cmd.put(CmdReset())
    again = h.wait_for(EvtCpuSuspended)
    assert again.source_line == line_of("basic.c", "main_first")


def test_runner_pause_and_live_switches(harness: HarnessFactory) -> None:
    h = harness("traps", max_instructions=100_000_000)
    h.wait_for(EvtCpuSuspended)
    h.cmd.put(CmdToggleSwitch(2))  # 0b0100 = 4 -> bucle infinito
    update = h.wait_for(EvtHardwareUpdated)
    assert (update.device_name, update.value) == ("switches", 4)
    h.cmd.put(CmdContinue())
    h.wait_for(EvtCpuRunning)
    h.cmd.put(CmdToggleSwitch(0))  # se aplica en vivo mientras corre
    h.cmd.put(CmdPause())
    paused = h.wait_for(EvtCpuSuspended)
    assert paused.reason == "ejecución pausada"
    assert h.machine.switches() is not None
    assert any(isinstance(e, EvtHardwareUpdated) and e.value == 5 for e in h.seen), (
        "el switch no se actualizó durante la ejecución"
    )


def test_runner_reports_traps(harness: HarnessFactory) -> None:
    h = harness("traps")
    h.wait_for(EvtCpuSuspended)
    h.cmd.put(CmdToggleSwitch(0))  # 1 -> puntero nulo
    h.cmd.put(CmdContinue())
    trap = h.wait_for(EvtTrap)
    assert "puntero nulo" in trap.reason and trap.fault_address == 0
    suspended = h.wait_for(EvtCpuSuspended)
    assert suspended.function == "main"


# ------------------------------------------------------------------- TUI


async def test_tui_drives_runner() -> None:
    from textual.widgets import Log

    from hardboiled.ui.tui import HardboiledApp
    from hardboiled.ui.widgets.code_view import CodeView
    from hardboiled.ui.widgets.hardware_view import SwitchBankView

    h = Harness("mmio")
    app = HardboiledApp(h.cmd, h.evt, h.runner)
    async with app.run_test(size=(140, 45)) as pilot:
        code = app.query_one(CodeView)

        async def settle(predicate: Callable[[], bool]) -> None:
            for _ in range(200):
                await pilot.pause(0.02)
                if predicate():
                    return
            raise AssertionError("la TUI no alcanzó el estado esperado")

        await settle(lambda: code._active_line is not None)
        assert code.file is not None and os.path.basename(code.file) == "mmio.c"

        # Regresión: los botones de los switches deben montarse y responder al click.
        switches = app.query_one(SwitchBankView)
        await settle(lambda: all(child.is_mounted for child in switches.children))
        await pilot.click("#sw-2")
        await settle(lambda: switches.value == 0b0100)

        await pilot.press("f10")
        await settle(lambda: code._active_line == line_of("mmio.c", "leds_0f"))

        # Pila de llamadas: al elegir el marco de main se marca su línea.
        from hardboiled.ui.widgets.backtrace_view import BacktraceView

        backtrace = app.query_one(BacktraceView)
        await settle(lambda: len(backtrace.frames) >= 2)
        assert backtrace.frames[0].label == "main"
        crt0 = backtrace.frames[1]
        backtrace.post_message(BacktraceView.FrameChosen(crt0))
        await settle(lambda: code._frame_line == crt0.source_line)
        backtrace.post_message(BacktraceView.FrameChosen(backtrace.frames[0]))
        await settle(lambda: code._frame_line is None)

        await pilot.press("f5")
        uart = app.query_one("#uart", Log)
        await settle(lambda: "hola" in "".join(str(line) for line in uart.lines))
        await pilot.press("q")
    h.runner.join(TIMEOUT)
    assert not h.runner.is_alive()


# ------------------------------------------------------------ arquitectura


def _imports(path: Path) -> set[str]:
    tree = ast.parse(path.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module)
    return names


@pytest.mark.parametrize("package", ["core", "hardware"])
def test_core_never_imports_presentation(package: str) -> None:
    """RNF-03: el simulador y el hardware no dependen de textual ni de la UI."""
    for path in (SRC / package).rglob("*.py"):
        for module in _imports(path):
            assert not module.startswith(("textual", "hardboiled.ui")), f"{path} importa {module}"


def test_runner_run_to_line_without_code_does_not_start(harness: HarnessFactory) -> None:
    h = harness("basic")
    h.wait_for(EvtCpuSuspended)
    h.cmd.put(CmdRunToLine(10_000, "basic.c"))
    assert "no hay código" in h.wait_for(EvtMessage).text
    assert not any(isinstance(e, EvtCpuRunning) for e in h.seen[-1:])
    h.cmd.put(CmdRunToLine(line_of("basic.c", "main_fact")))
    h.wait_for(EvtCpuRunning)
    assert h.wait_for(EvtCpuSuspended).source_line == line_of("basic.c", "main_fact")
