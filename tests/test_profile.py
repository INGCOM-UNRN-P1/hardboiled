"""Perfil de ejecución: instrucciones por línea y por función, CLI y mapa de calor."""

from __future__ import annotations

import json

import pytest

from hardboiled.cli import EXIT_USAGE, main
from hardboiled.core.machine import Machine
from hardboiled.core.profile import build_profile
from hardboiled.ui.widgets.code_view import compact_count
from tests.conftest import fixture_path, line_of

BASIC = str(fixture_path("basic.elf"))


def square_calls(machine: Machine) -> int:
    lines = build_profile(machine).line_counts(str(fixture_path("basic.c")))
    return lines[line_of("basic.c", "square_body")]


@pytest.mark.parametrize("mode", ["fast", "step"])
def test_counts_add_up_to_executed_instructions(mode: str) -> None:
    machine = Machine.from_elf(fixture_path("mmio.elf"))
    machine.switches().set_value(1)  # type: ignore[union-attr]
    debugger = machine.debugger
    if mode == "fast":
        debugger.toggle_line_breakpoint(line_of("mmio.c", "isr_body"), "mmio.c")
        while debugger.continue_().reason.value == "break":  # cortes a mitad de bloque
            pass
    else:
        debugger._run(lambda pc: False)
    profile = build_profile(machine)
    assert profile.total == machine.cpu.instructions
    body = profile.line_counts(str(fixture_path("mmio.c")))
    assert body[line_of("mmio.c", "isr_body")] > 0


def test_fast_and_step_profiles_are_identical() -> None:
    fast, step = Machine.from_elf(fixture_path("basic.elf")), Machine.from_elf(BASIC)
    fast.debugger.continue_()
    step.debugger._run(lambda pc: False)
    assert fast.cpu.execution_counts() == step.cpu.execution_counts()
    assert build_profile(fast) == build_profile(step)


def test_profile_reflects_the_work_done() -> None:
    machine = Machine.from_elf(BASIC)
    machine.debugger.continue_()
    profile = build_profile(machine)
    names = [cost.name for cost in profile.functions]
    assert {"main", "square", "sum_squares", "factorial"} <= set(names)
    # square() se llama 3 veces (counter = 3): cada instrucción de su cuerpo, 3 veces.
    counts = machine.cpu.execution_counts()
    square = machine.image.symbol_address("square")
    assert square is not None and counts[square] == 3
    assert square_calls(machine) % 3 == 0
    machine.reset()
    assert build_profile(machine).total == 0


def test_cli_profile_report(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["run", BASIC, "--headless", "--profile"]) == 134
    err = capsys.readouterr().err
    assert "Perfil:" in err and "funciones:" in err and "líneas más ejecutadas:" in err
    assert "basic.c:" in err and "│" in err
    assert main(["run", BASIC, "--profile"]) == EXIT_USAGE
    assert "tecla h" in capsys.readouterr().err


def test_json_profile(capsys: pytest.CaptureFixture[str]) -> None:
    main(["run", BASIC, "--headless", "--json", "--profile"])
    profile = json.loads(capsys.readouterr().out)["profile"]
    assert profile["total"] == sum(f["count"] for f in profile["functions"])
    assert {"file", "line", "count"} == set(profile["lines"][0])


def test_compact_count() -> None:
    assert [compact_count(n) for n in (7, 999, 1_234, 56_789, 123_456, 5_600_000)] == [
        "7", "999", "1.2k", "56.8k", "123k", "5.6M",
    ]  # fmt: skip


async def test_tui_heatmap() -> None:
    from hardboiled.ui.tui import HardboiledApp
    from hardboiled.ui.widgets.code_view import CodeView
    from tests.conftest import Harness

    h = Harness("basic")
    app = HardboiledApp(h.cmd, h.evt, h.runner)
    async with app.run_test(size=(140, 45)) as pilot:
        for _ in range(100):
            await pilot.pause(0.02)
            if app._suspended is not None:
                break
        code = app.query_one(CodeView)
        width = code.gutter_width
        await pilot.press("h")
        await pilot.press("c")  # hasta el final
        target = line_of("basic.c", "square_body")
        source = str(fixture_path("basic.c"))
        for _ in range(200):
            await pilot.pause(0.02)
            if (code._profile or {}).get((source, target)):
                break
        code.show_file(source)  # terminó en crt0.s (el ebreak): se abre el .c
        await pilot.pause()
        assert code._heat[target] % 3 == 0
        assert code.gutter_width == width + 8
        rendered = code.render_line(target - 1 - int(code.scroll_offset.y)).text
        assert rendered.lstrip().startswith(compact_count(code._heat[target]))
        await pilot.press("h")
        await pilot.pause(0.05)
        assert code.gutter_width == width
        await pilot.press("q")
