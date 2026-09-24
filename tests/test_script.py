"""Guion de entrada (--script): estímulos a los periféricos en ciclos dados."""

from __future__ import annotations

from pathlib import Path

import pytest

from hardboiled.cli import EXIT_TRAP, EXIT_USAGE, main
from hardboiled.config import BoardConfig
from hardboiled.core.cpu import StopReason
from hardboiled.core.machine import Machine
from hardboiled.script import ScriptError, attach_script, load_script
from tests.conftest import fixture_path

TICK = 20_000  # TICK_CYCLES de fixtures/hwloop.c

SCRIPT = """
[[at]]
cycle = 60_000
switches = 0b1010

[[at]]
cycle = 80_000
press = 0

[[at]]
cycle = 120_000
press = [1, 2]
uart = "hola"

[[at]]
cycle = 200_000
uart = "q"
"""


def write(tmp_path: Path, text: str) -> Path:
    path = tmp_path / "entrada.toml"
    path.write_text(text, encoding="utf-8")
    return path


def test_script_drives_the_hardware_loop(tmp_path: Path) -> None:
    machine = Machine.from_elf(fixture_path("hwloop.elf"))
    player = attach_script(machine, write(tmp_path, SCRIPT), None)
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.EXITED and stop.exit_code == 3
    uart = machine.uart()
    assert uart is not None and bytes(uart.transmitted) == b"listo\nHOLAfin\n"
    assert [a.cycle for a in player.applied] == [60_000, 80_000, 120_000, 200_000]
    assert player.applied[2].description == "uart 'hola'; botón 1, 2"
    assert player.pending == 0


def test_reset_and_step_back_replay_the_script(tmp_path: Path) -> None:
    machine = Machine.from_elf(fixture_path("hwloop.elf"))
    player = attach_script(machine, write(tmp_path, SCRIPT), None)
    first = machine.debugger.continue_()
    machine.reset()
    assert player.pending == 4 and player.applied == []
    snap = machine.snapshot()
    assert machine.debugger.continue_() == first
    machine.restore(snap)
    assert player.pending == 4


def test_wfi_sleeps_until_the_next_stimulus(tmp_path: Path) -> None:
    # Un estímulo lejano no obliga a ejecutar instrucciones hasta él: `wfi` salta.
    machine = Machine.from_elf(fixture_path("hwloop.elf"))
    attach_script(machine, write(tmp_path, '[[at]]\ncycle = 5_000_000\nuart = "q"\n'), None)
    stop = machine.debugger.continue_()
    assert stop.reason is StopReason.EXITED
    cpu = machine.cpu
    assert 5_000_000 <= cpu.clock.cycles < 5_000_000 + TICK
    assert cpu.instructions < cpu.clock.cycles // 10  # durmió la mayor parte del tiempo


def test_milliseconds_need_a_clock(tmp_path: Path) -> None:
    machine = Machine.from_elf(fixture_path("hwloop.elf"))
    path = write(tmp_path, '[[at]]\nms = 2.5\nuart = "q"\n')
    with pytest.raises(ScriptError, match="clock_hz"):
        attach_script(machine, path, None)
    player = attach_script(machine, path, 1_000_000)
    assert player.next_deadline() == 2_500


@pytest.mark.parametrize(
    ("text", "error"),
    [
        ("[[at]]\nswitches = 1\n", "`cycle` o `ms`"),
        ("[[at]]\ncycle = 1\nms = 1\nuart = 'x'\n", "`cycle` o `ms`"),
        ("[[at]]\ncycle = 1\n", "no hace nada"),
        ("[[at]]\ncycle = 1\nled = 3\n", "led"),
        ("[[at]\n", "TOML inválido"),
    ],
)
def test_invalid_scripts(tmp_path: Path, text: str, error: str) -> None:
    with pytest.raises(ScriptError, match=error):
        load_script(write(tmp_path, text))


def test_unknown_button_is_rejected(tmp_path: Path) -> None:
    machine = Machine.from_elf(fixture_path("hwloop.elf"), BoardConfig())
    with pytest.raises(ScriptError, match="botón 7"):
        attach_script(machine, write(tmp_path, "[[at]]\ncycle = 1\npress = 7\n"), None)


def test_cli_run_with_script(tmp_path: Path, capsysbinary: pytest.CaptureFixture[bytes]) -> None:
    script = write(tmp_path, SCRIPT)
    code = main(["run", str(fixture_path("hwloop.elf")), "--headless", "--script", str(script)])
    assert code == 3
    assert capsysbinary.readouterr().out == b"listo\nHOLAfin\n"
    # Sin la 'q' final el programa se duerme para siempre: deadlock detectado.
    short = write(tmp_path, SCRIPT.rsplit("[[at]]", 1)[0])
    assert main(["run", str(fixture_path("hwloop.elf")), "--headless", "--script", str(short)]) == (
        EXIT_TRAP
    )
    bad = write(tmp_path, "[[at]]\n")
    assert main(["run", str(fixture_path("hwloop.elf")), "--headless", "--script", str(bad)]) == (
        EXIT_USAGE
    )
