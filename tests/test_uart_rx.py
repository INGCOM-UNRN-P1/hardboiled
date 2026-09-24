"""Recepción por la UART: registros, IRQ, entrada en la TUI y por stdin."""

from __future__ import annotations

import importlib.util
import io
import queue
import time
from pathlib import Path

import pytest

from hardboiled import resources
from hardboiled.cli import main
from hardboiled.core.events import (
    CmdContinue,
    CmdShutdown,
    CmdUartInput,
    Command,
    Event,
    EvtCpuRunning,
    EvtCpuSuspended,
    EvtProgramExited,
    EvtUartOutput,
)
from hardboiled.core.machine import Machine
from hardboiled.core.runner import RunnerThread
from hardboiled.hardware.uart import Uart
from hardboiled.toolchain import build, select_compiler

needs_zig = pytest.mark.skipif(
    importlib.util.find_spec("ziglang") is None, reason="requiere el extra [zig]"
)


def test_uart_receive_registers_and_level_irq() -> None:
    raised: list[int] = []
    lowered: list[int] = []
    uart = Uart("uart0", 0x10, irq_line=1, raise_irq=raised.append, lower_irq=lowered.append)
    assert uart.read(0x4) == 0b01  # listo para transmitir, sin datos
    uart.receive(b"ab")
    assert uart.read(0x4) == 0b11
    assert raised == []  # la IRQ no está habilitada
    uart.write(0xC, 1, 0xFFFFFFFF)
    assert raised == [1] and uart.can_wake()
    assert uart.read(0x8) == ord("a")
    assert raised == [1, 1]  # por nivel: queda un byte, sigue pedida
    assert uart.read(0x8) == ord("b")
    assert uart.read(0x8) == 0 and uart.read(0x4) == 0b01
    assert lowered  # buffer vacío: la línea se baja
    uart.receive(b"x")
    lowered.clear()
    uart.write(0xC, 0, 0xFFFFFFFF)  # deshabilitar la IRQ también la baja
    assert lowered == [1]


@needs_zig
def test_echo_example_from_stdin(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("HARDBOILED_CC", "zig")
    fake_stdin = io.TextIOWrapper(io.BytesIO(b"hola\nMundo 1\nfin\n"), encoding="utf-8")
    monkeypatch.setattr("sys.stdin", fake_stdin)
    assert main(["demo", "eco", "--headless", "--uart-input", "-"]) == 0
    out = capsysbinary.readouterr().out.decode()
    assert "HOLA\nMUNDO 1\nchau\n" in out


@needs_zig
def test_echo_waits_for_input_in_interactive_mode(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Con la TUI, wfi espera lo que escriba el usuario en vez de dar deadlock."""

    elf = build(
        [resources.example_path("eco")], tmp_path / "eco.elf", compiler=select_compiler("zig")
    ).output
    machine = Machine.from_elf(elf)
    cmd: queue.Queue[Command] = queue.Queue()
    evt: queue.Queue[Event] = queue.Queue()
    runner = RunnerThread(machine, cmd, evt)
    runner.start()
    seen = []

    deadline = time.monotonic() + 20

    def wait_for(kind: type) -> object:
        while True:
            event = evt.get(timeout=max(deadline - time.monotonic(), 0.01))
            seen.append(event)
            if isinstance(event, kind):
                return event

    wait_for(EvtCpuSuspended)
    cmd.put(CmdContinue())
    wait_for(EvtCpuRunning)
    cmd.put(CmdUartInput(b"abc\n"))
    cmd.put(CmdUartInput(b"fin\n"))
    wait_for(EvtProgramExited)
    output = bytes(e.char_code for e in seen if isinstance(e, EvtUartOutput))
    assert b"ABC\n" in output and output.endswith(b"chau\n")
    cmd.put(CmdShutdown())
    runner.join(10)


@needs_zig
def test_uart_input_from_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path))
    monkeypatch.setenv("HARDBOILED_CC", "zig")
    entrada = tmp_path / "entrada.txt"
    entrada.write_bytes(b"abc\nfin\n")
    assert main(["demo", "eco", "--headless", "--uart-input", str(entrada)]) == 0
    assert b"ABC\n" in capsysbinary.readouterr().out


async def test_tui_uart_input_field() -> None:
    from textual.widgets import Input

    from hardboiled.ui.tui import HardboiledApp
    from tests.conftest import Harness

    h = Harness("mmio")
    app = HardboiledApp(h.cmd, h.evt, h.runner)
    async with app.run_test(size=(140, 45)) as pilot:
        for _ in range(100):
            await pilot.pause(0.02)
            if app._suspended is not None:
                break
        field = app.query_one("#uart-input", Input)
        field.focus()
        await pilot.press("h", "o", "l", "a", "enter")
        uart = h.machine.uart()
        assert uart is not None
        for _ in range(100):
            await pilot.pause(0.02)
            if uart.received:
                break
        assert bytes(uart.received) == b"hola\n"
        assert field.value == ""
        await pilot.press("escape")
        assert app.focused is not None and app.focused.id == "code"
        await pilot.press("q")
