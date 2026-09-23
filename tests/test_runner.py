"""Hilo de trabajo, protocolo de colas, TUI y restricciones de arquitectura."""

from __future__ import annotations

import ast
import os
from collections.abc import Callable
from pathlib import Path

import pytest

from hardboiled.core.events import (
    CmdContinue,
    CmdPause,
    CmdReadMemory,
    CmdReset,
    CmdRunToLine,
    CmdSelectFrame,
    CmdStepOver,
    CmdToggleBreakpoint,
    CmdToggleSwitch,
    CmdToggleWatchpoint,
    EvtBreakpointsChanged,
    EvtCpuProgress,
    EvtCpuRunning,
    EvtCpuSuspended,
    EvtFrameVariables,
    EvtHardwareUpdated,
    EvtMemoryDump,
    EvtMessage,
    EvtProgramExited,
    EvtProgramLoaded,
    EvtTrap,
)
from hardboiled.ui.tui import HardboiledApp
from tests.conftest import Harness, HarnessFactory, line_of

SRC = Path(__file__).parents[1] / "src" / "hardboiled"
TIMEOUT = 10


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
    progress = h.wait_for(EvtCpuProgress)  # el bucle infinito informa su avance
    assert progress.function == "main" and progress.instructions_per_second > 0
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
    assert trap.instruction is not None and trap.instruction.startswith("lw ")
    assert trap.function == "main" and trap.source_line is not None
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

        # Variables: la global `ticks` aparece en el árbol.
        from hardboiled.ui.widgets.variables_view import VariablesView

        variables = app.query_one(VariablesView)
        await settle(lambda: any(v.name == "ticks" for v in variables._globals))

        # Desensamblado mixto: `d` lo muestra, con la instrucción del PC marcada.
        from hardboiled.ui.widgets.disasm_view import DisassemblyView

        disasm = app.query_one(DisassemblyView)
        assert not disasm.display
        await pilot.press("d")
        await settle(lambda: disasm.display and disasm.option_count > 0)
        pc = app._suspended.pc if app._suspended else -1
        assert any(row is not None and row.address == pc for row in disasm._rows)

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


def test_runner_frame_variables(harness: HarnessFactory) -> None:
    h = harness("basic")
    h.wait_for(EvtCpuSuspended)
    h.cmd.put(CmdToggleBreakpoint(line_of("basic.c", "square_body")))
    h.cmd.put(CmdContinue())
    hit = h.wait_for(EvtCpuSuspended)
    while hit.function != "square":
        hit = h.wait_for(EvtCpuSuspended)
    assert [v.name for v in hit.locals] == ["x"]
    assert {v.name for v in hit.global_vars} == {"counter", "results"}
    h.cmd.put(CmdSelectFrame(1))
    frame = h.wait_for(EvtFrameVariables)
    assert frame.label == "sum_squares"
    assert [v.name for v in frame.locals] == ["n", "total", "i"]


def test_runner_watchpoints(harness: HarnessFactory) -> None:
    h = harness("basic")
    h.wait_for(EvtCpuSuspended)
    h.cmd.put(CmdToggleWatchpoint("results[0]"))
    changed = h.wait_for(EvtBreakpointsChanged)
    assert [w.expression for w in changed.watches] == ["results[0]"]
    h.cmd.put(CmdContinue())
    hit = h.wait_for(EvtCpuSuspended)
    while "watchpoint" not in hit.reason:
        hit = h.wait_for(EvtCpuSuspended)
    assert "0 → 14" in hit.reason
    h.cmd.put(CmdToggleWatchpoint("nada"))
    assert "nada" in h.wait_for(EvtMessage).text


async def test_tui_shows_trap_post_mortem() -> None:
    from hardboiled.ui.widgets.code_view import CodeView
    from hardboiled.ui.widgets.trap_screen import TrapScreen

    h = Harness("traps")
    h.machine.switches().set_value(1)  # type: ignore[union-attr]
    app = HardboiledApp(h.cmd, h.evt, h.runner)
    async with app.run_test(size=(140, 45)) as pilot:
        for _ in range(100):
            await pilot.pause(0.02)
            if app._suspended is not None:
                break
        await pilot.press("f5")
        for _ in range(200):
            await pilot.pause(0.02)
            if isinstance(app.screen, TrapScreen):
                break
        assert isinstance(app.screen, TrapScreen)
        assert "puntero nulo" in app.screen.trap.reason
        code = app.query_one(CodeView)
        assert code._trap_line == app.screen.trap.source_line
        await pilot.press("escape")
        await pilot.pause(0.1)
        assert not isinstance(app.screen, TrapScreen)
        await pilot.press("q")


def test_runner_memory_dump(harness: HarnessFactory) -> None:
    h = harness("basic")
    h.wait_for(EvtCpuSuspended)
    h.cmd.put(CmdReadMemory("counter"))
    dump = h.wait_for(EvtMemoryDump)
    assert dump.error is None and dump.address == 0x20000000
    assert dump.data[:4] == (3).to_bytes(4, "little")
    assert (0x20000000, "counter") in dump.labels
    h.cmd.put(CmdReadMemory("0x40000000"))
    assert "MMIO" in (h.wait_for(EvtMemoryDump).error or "")
    h.cmd.put(CmdReadMemory("no_existe"))
    assert "no_existe" in (h.wait_for(EvtMemoryDump).error or "")
    h.cmd.put(CmdReadMemory("main"))  # símbolo de código: la Flash también se puede ver
    assert h.wait_for(EvtMemoryDump).address >= 0x10000
