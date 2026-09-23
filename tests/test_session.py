"""Breakpoints persistentes entre sesiones."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from hardboiled.core.machine import Machine
from hardboiled.core.session import BreakpointStore
from tests.conftest import FIXTURES, line_of


def copy_program(tmp_path: Path) -> Path:
    for name in ("basic.c", "basic.elf"):
        shutil.copy(FIXTURES / name, tmp_path / name)
    return tmp_path / "basic.elf"


def test_save_and_restore(tmp_path: Path) -> None:
    elf = copy_program(tmp_path)
    store = BreakpointStore.for_program(elf)
    machine = Machine.from_elf(elf)
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("basic.c", "square_body"), "basic.c")
    debugger.set_condition(line_of("basic.c", "sum_call"), "basic.c", "i == 2", 1)
    debugger.toggle_address_breakpoint(0x10000)
    debugger.run_to_main()
    debugger.add_watchpoint("results[1]")
    store.save(debugger)

    data = json.loads(store.path.read_text())
    assert store.path == tmp_path / ".hardboiled" / "basic.breakpoints.json"
    assert {p["file"] for p in data["points"] if p["kind"] == "line"} == {"basic.c"}

    fresh = Machine.from_elf(elf).debugger
    assert store.restore(fresh) == []
    assert fresh.line_breakpoints == debugger.line_breakpoints
    assert fresh.address_breakpoints == {0x10000}
    assert [c.expression for c in fresh.conditions.values()] == ["i == 2"]
    assert [w.expression for w in fresh.watchpoints] == ["results[1]"]


def test_restore_reports_points_that_no_longer_exist(tmp_path: Path) -> None:
    elf = copy_program(tmp_path)
    store = BreakpointStore.for_program(elf)
    store.path.parent.mkdir()
    store.path.write_text(
        json.dumps(
            {
                "version": 1,
                "points": [
                    {"kind": "line", "file": "basic.c", "line": 10_000},
                    {"kind": "watch", "expression": "variable_borrada"},
                ],
            }
        )
    )
    failed = store.restore(Machine.from_elf(elf).debugger)
    assert failed == ["basic.c:10000", "variable_borrada"]


def test_damaged_file_is_ignored(tmp_path: Path) -> None:
    elf = copy_program(tmp_path)
    store = BreakpointStore.for_program(elf)
    store.path.parent.mkdir()
    store.path.write_text("{no es json")
    assert store.load() == []


def test_local_watchpoints_are_not_saved(tmp_path: Path) -> None:
    elf = copy_program(tmp_path)
    machine = Machine.from_elf(elf)
    debugger = machine.debugger
    debugger.toggle_line_breakpoint(line_of("basic.c", "sum_first"), "basic.c")
    debugger.continue_()
    debugger.add_watchpoint("total")
    store = BreakpointStore.for_program(elf)
    store.save(debugger)
    kinds = [p["kind"] for p in json.loads(store.path.read_text())["points"]]
    assert kinds == ["line"]
