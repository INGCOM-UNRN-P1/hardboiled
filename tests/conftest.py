from __future__ import annotations

import queue
import time
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from hardboiled.config import BoardConfig, BoardInfo
from hardboiled.core.events import CmdShutdown, Command, Event
from hardboiled.core.machine import Machine
from hardboiled.core.runner import RunnerThread

FIXTURES = Path(__file__).parent / "fixtures"
RUNNER_TIMEOUT = 10


def fixture_path(name: str) -> Path:
    return FIXTURES / name


def line_of(source: str, marker: str) -> int:
    """Número de línea del marcador `/* @marker */` en un fuente de fixtures."""
    for number, text in enumerate((FIXTURES / source).read_text().splitlines(), start=1):
        if f"@{marker} " in text or text.rstrip().endswith(f"@{marker}"):
            return number
    raise AssertionError(f"no se encontró @{marker} en {source}")


MachineFactory = Callable[..., tuple[Machine, list[Event]]]


@pytest.fixture
def make_machine() -> MachineFactory:
    def factory(
        name: str, *, switches: int | None = None, max_instructions: int = 1_000_000
    ) -> tuple[Machine, list[Event]]:
        board = BoardConfig(board=BoardInfo(max_instructions=max_instructions))
        machine = Machine.from_elf(FIXTURES / f"{name}.elf", board)
        events: list[Event] = []
        machine.set_event_sink(events.append)
        if switches is not None:
            bank = machine.switches()
            assert bank is not None
            bank.set_value(switches)
        return machine, events

    return factory


class Harness:
    def __init__(self, name: str, max_instructions: int = 1_000_000) -> None:
        board = BoardConfig(board=BoardInfo(max_instructions=max_instructions))
        self.machine = Machine.from_elf(FIXTURES / f"{name}.elf", board)
        self.cmd: queue.Queue[Command] = queue.Queue()
        self.evt: queue.Queue[Event] = queue.Queue()
        self.runner = RunnerThread(self.machine, self.cmd, self.evt)
        self.seen: list[Event] = []

    def wait_for[T](self, kind: type[T]) -> T:
        # Plazo total: los EvtCpuProgress periódicos no deben alargar la espera.
        deadline = time.monotonic() + RUNNER_TIMEOUT
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError(f"no llegó {kind.__name__} en {RUNNER_TIMEOUT} s")
            event = self.evt.get(timeout=remaining)
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
        h.runner.join(RUNNER_TIMEOUT)
        assert not h.runner.is_alive()
