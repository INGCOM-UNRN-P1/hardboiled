from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from hardboiled.config import BoardConfig, BoardInfo
from hardboiled.core.events import Event
from hardboiled.core.machine import Machine

FIXTURES = Path(__file__).parent / "fixtures"


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
