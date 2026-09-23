"""SDK generado desde board.toml."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from hardboiled import resources
from hardboiled.cli import main
from hardboiled.config import BoardConfig, load_board
from hardboiled.sdk import generate_header, generate_linker_script

ROOT = Path(__file__).parents[1]

CUSTOM_BOARD = """\
[board]
name = "placa-propia"

[memory]
sram_size_kb = 32

[[peripherals]]
name = "leds"
type = "gpio_out"
offset = "0x00"
width_bits = 8

[[peripherals]]
name = "barra"
type = "gpio_out"
offset = "0x40"
width_bits = 4

[[peripherals]]
name = "uart0"
type = "uart"
offset = "0x10"

[[peripherals]]
name = "reloj"
type = "timer"
offset = "0x80"
irq_line = 3
"""


def test_packaged_runtime_is_generated_from_default_board() -> None:
    board = load_board(resources.default_board_path())
    assert resources.header_path().read_text() == generate_header(board)
    assert resources.linker_script().read_text() == generate_linker_script(board)


def test_custom_board_names_and_offsets() -> None:
    board = BoardConfig.model_validate(__import__("tomllib").loads(CUSTOM_BOARD))
    header = generate_header(board)
    assert "#define BARRA" in header and "HB_REG(0x040)" in header
    assert "static inline void barra_set(uint32_t mask)" in header
    assert "#define TIMER_CTRL   HB_REG(0x080)" in header  # primer timer: nombres clásicos
    assert "#define IRQ_RELOJ 3" in header
    assert "LENGTH = 32K" in generate_linker_script(board)


def test_gen_header_command(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    board = tmp_path / "board.toml"
    board.write_text(CUSTOM_BOARD)
    assert main(["gen-header", str(board)]) == 0
    assert "barra_toggle" in capsys.readouterr().out
    out = tmp_path / "hb.ld"
    assert main(["gen-header", str(board), "--linker-script", "-o", str(out)]) == 0
    assert "placa-propia" in out.read_text()


@pytest.mark.skipif(importlib.util.find_spec("ziglang") is None, reason="requiere [zig]")
def test_build_uses_the_project_board(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsysbinary: pytest.CaptureFixture[bytes]
) -> None:
    monkeypatch.setenv("HARDBOILED_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(tmp_path)
    (tmp_path / "board.toml").write_text(CUSTOM_BOARD)
    (tmp_path / "main.c").write_text(
        '#include "hardboiled.h"\n'
        'int main(void) { barra_set(0x5); uart_puts("ok"); return (int)barra_get(); }\n'
    )
    assert main(["run", "main.c", "--headless", "--cc", "zig"]) == 5
    assert capsysbinary.readouterr().out == b"ok"
    generated = list((tmp_path / "cache" / "sdk").glob("*/include/hardboiled.h"))
    assert len(generated) == 1
