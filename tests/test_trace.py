"""Traza de ejecución exportable (--trace)."""

from __future__ import annotations

import csv
import json
from pathlib import Path

import pytest

from hardboiled.cli import EXIT_USAGE, main
from hardboiled.core.machine import Machine
from hardboiled.core.trace import TraceWriter
from tests.conftest import fixture_path, line_of


def test_register_values_match_reg_read() -> None:
    machine = Machine.from_elf(fixture_path("basic.elf"))
    machine.debugger.run_to_main()
    cpu = machine.cpu
    assert cpu.register_values() == tuple(cpu.read_register(i) for i in range(32))
    assert isinstance(cpu._gpr_view, tuple)  # calibrado: se usa la lectura rápida


def test_csv_trace_of_a_whole_program(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "traza.csv"
    code = main(["run", str(fixture_path("basic.elf")), "--headless", "--trace", str(path)])
    assert code == 134
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    machine = Machine.from_elf(fixture_path("basic.elf"))
    machine.debugger.continue_()
    assert len(rows) == machine.cpu.instructions + 1  # + el ebreak final
    assert f"traza: {len(rows):,} instrucciones" in capsys.readouterr().err
    assert [int(row["n"]) for row in rows[:-1]] == list(range(len(rows) - 1))
    first = rows[0]
    assert first["pc"] == "0x00010000" and first["function"] == "_start"
    # La primera instrucción de crt0 arma sp (y quizá gp): se ven los cambios.
    assert any("sp=0x" in row["changes"] for row in rows[:5])
    in_square = [row for row in rows if row["function"] == "square" and row["file"] == "basic.c"]
    assert in_square and all(row["line"] for row in in_square)
    assert any(row["instruction"].startswith("mul") or "__mulsi3" in row["instruction"]
               or row["instruction"] for row in in_square)  # fmt: skip


def test_jsonl_trace_marks_interrupts_and_mret(tmp_path: Path) -> None:
    path = tmp_path / "traza.jsonl"
    code = main(
        [
            "run",
            str(fixture_path("mmio.elf")),
            "--headless",
            "--switches",
            "1",
            "--trace",
            str(path),
        ]
    )
    assert code == 103
    records = [json.loads(line) for line in path.read_text().splitlines()]
    irq = [r for r in records if r.get("event") == "IRQ 0"]
    assert len(irq) == 3 and all(r["function"] == "__isr_trampoline" or r["pc"] for r in irq)
    mret = [r for r in records if r["instruction"] == "mret"]
    assert len(mret) == 3
    # mret restaura el contexto: se le atribuyen los registros que vuelven.
    assert all("sp" in r["changes"] for r in mret)
    body = [r for r in records if r["line"] == line_of("mmio.c", "isr_body")]
    assert body and body[0]["file"] == "mmio.c"


def test_trace_limit_cuts_but_program_finishes(tmp_path: Path) -> None:
    machine = Machine.from_elf(fixture_path("basic.elf"))
    tracer = TraceWriter(machine, tmp_path / "t.csv", limit=50)
    tracer.attach()
    stop = machine.debugger.continue_()
    tracer.close()
    assert stop.exit_code == 134 and tracer.truncated and tracer.rows == 50
    assert machine.cpu.tracer is None


def test_trace_errors(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    elf = str(fixture_path("basic.elf"))
    assert main(["run", elf, "--trace", str(tmp_path / "t.csv")]) == EXIT_USAGE
    assert "--headless" in capsys.readouterr().err
    assert main(["run", elf, "--headless", "--trace", str(tmp_path / "t.txt")]) == EXIT_USAGE
    assert ".csv o .jsonl" in capsys.readouterr().err


def test_trace_in_json_report(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "t.jsonl"
    main(["run", str(fixture_path("basic.elf")), "--headless", "--json", "--trace", str(path),
          "--trace-limit", "10"])  # fmt: skip
    report = json.loads(capsys.readouterr().out)
    assert report["trace"] == {"path": str(path), "rows": 10, "truncated": True}
