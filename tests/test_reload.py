"""Recarga automática del programa en la TUI al recompilar (QoL #37)."""

from __future__ import annotations

import importlib.util
import os
import queue
import shutil
import time
from collections.abc import Iterator
from pathlib import Path

import pytest

from hardboiled.core.events import (
    CmdContinue,
    CmdShutdown,
    CmdToggleBreakpoint,
    Command,
    Event,
    EvtBreakpointsChanged,
    EvtCpuSuspended,
    EvtMessage,
    EvtProgramExited,
)
from hardboiled.core.machine import Machine
from hardboiled.core.runner import RunnerThread
from hardboiled.toolchain import build, select_compiler
from hardboiled.watch import ProgramWatcher, WatchError
from tests.conftest import FIXTURES, line_of

needs_zig = pytest.mark.skipif(
    importlib.util.find_spec("ziglang") is None, reason="requiere el extra [zig]"
)


class Session:
    def __init__(self, elf: Path, watcher: ProgramWatcher) -> None:
        self.cmd: queue.Queue[Command] = queue.Queue()
        self.evt: queue.Queue[Event] = queue.Queue()
        self.runner = RunnerThread(
            Machine.from_elf(elf), self.cmd, self.evt, stop_at_main=True, watcher=watcher
        )
        self.runner.start()

    def wait(self, predicate: type[Event] | str, timeout: float = 15) -> Event:
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            try:
                event = self.evt.get(timeout=0.1)
            except queue.Empty:
                continue
            if isinstance(predicate, str):
                if isinstance(event, EvtMessage) and predicate in event.text:
                    return event
            elif isinstance(event, predicate):
                return event
        raise TimeoutError(f"no llegó {predicate}")


@pytest.fixture
def session() -> Iterator[list[Session]]:
    created: list[Session] = []
    yield created
    for s in created:
        s.cmd.put(CmdShutdown())
        s.runner.join(10)


def bump(path: Path) -> None:
    """Asegura que la fecha de modificación cambie aunque el sistema de archivos sea grueso."""
    stamp = time.time() + 2
    os.utime(path, (stamp, stamp))


def test_watcher_waits_until_the_file_settles(tmp_path: Path) -> None:
    elf = tmp_path / "p.elf"
    elf.write_bytes(b"uno")
    watcher = ProgramWatcher.for_elf(elf)
    assert not watcher.changed()
    elf.write_bytes(b"dos, mas largo")
    assert not watcher.changed()  # recién escrito: todavía podría estar cambiando
    assert watcher.changed()
    assert not watcher.changed()  # ya recargado
    assert watcher.rebuild() == elf.resolve()


def test_recompiled_elf_is_reloaded_keeping_breakpoints(
    tmp_path: Path, session: list[Session]
) -> None:
    elf = tmp_path / "basic.elf"
    shutil.copy(FIXTURES / "basic.elf", elf)
    shutil.copy(FIXTURES / "basic.c", tmp_path)  # rutas DWARF relativas al ELF
    source = str((tmp_path / "basic.c").resolve())
    s = Session(elf, ProgramWatcher.for_elf(elf))
    session.append(s)
    s.wait(EvtCpuSuspended)
    line = line_of("basic.c", "square_body")
    s.cmd.put(CmdToggleBreakpoint(line, source))
    s.wait(EvtBreakpointsChanged)
    shutil.copy(FIXTURES / "basic.elf", elf)  # "recompilado"
    bump(elf)
    changed = s.wait(EvtBreakpointsChanged)  # los del programa nuevo
    assert isinstance(changed, EvtBreakpointsChanged)
    s.wait("programa recargado (1 puntos conservados)")
    assert (source, line) in changed.lines
    s.wait(EvtCpuSuspended)  # detenido otra vez al inicio de main()
    s.cmd.put(CmdContinue())
    stop = s.wait(EvtCpuSuspended)
    assert isinstance(stop, EvtCpuSuspended) and stop.source_line == line


@needs_zig
def test_changed_sources_are_rebuilt(tmp_path: Path, session: list[Session]) -> None:
    source = tmp_path / "basic.c"
    shutil.copy(FIXTURES / "basic.c", source)
    compiler = select_compiler("zig")

    def rebuild() -> Path:
        result = build([source], tmp_path / "basic.elf", compiler=compiler)
        if result.diagnostics and "error" in result.diagnostics:
            raise WatchError(result.diagnostics)
        return result.output

    def rebuild_or_fail() -> Path:
        try:
            return rebuild()
        except Exception as exc:  # BuildError: como hace la CLI
            raise WatchError(str(exc)) from exc

    elf = rebuild()
    s = Session(elf, ProgramWatcher.for_sources([source], [], rebuild_or_fail))
    session.append(s)
    s.wait(EvtCpuSuspended)

    # Un error de compilación se informa y se sigue con el programa anterior.
    text = source.read_text(encoding="utf-8")
    source.write_text(text.replace("return x * x;", "return x * ;"), encoding="utf-8")
    bump(source)
    s.wait("no se recargó")

    # Corregido y con otro valor: el programa nuevo devuelve otra cosa.
    source.write_text(text.replace("int counter = 3;", "int counter = 4;"), encoding="utf-8")
    bump(source)
    s.wait("recompilando")
    s.wait("programa recargado")
    s.wait(EvtCpuSuspended)
    s.cmd.put(CmdContinue())
    exited = s.wait(EvtProgramExited)
    assert isinstance(exited, EvtProgramExited)
    assert exited.exit_code == 1 + 4 + 9 + 16 + 120


async def test_tui_survives_a_reload() -> None:
    from hardboiled.core.events import CmdReload
    from hardboiled.ui.tui import HardboiledApp
    from hardboiled.ui.widgets.hardware_view import HardwareView
    from tests.conftest import Harness

    h = Harness("mmio")
    app = HardboiledApp(h.cmd, h.evt, h.runner)
    async with app.run_test(size=(140, 45)) as pilot:
        for _ in range(100):
            await pilot.pause(0.02)
            if app._suspended is not None:
                break
        rows = len(app.query_one(HardwareView).children)
        first = app._suspended
        app._suspended = None
        h.cmd.put(CmdReload(str(FIXTURES / "mmio.elf")))
        for _ in range(100):
            await pilot.pause(0.02)
            if app._suspended is not None:
                break
        assert app._suspended is not None and first is not None
        assert app._suspended.pc == first.pc
        assert len(app.query_one(HardwareView).children) == rows  # sin duplicar la placa
        await pilot.press("q")
