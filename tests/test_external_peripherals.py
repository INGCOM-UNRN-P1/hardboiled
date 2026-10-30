"""Pruebas de periféricos externos y periférico de referencia (teclado matricial)."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from hardboiled.cli import main
from hardboiled.config import BoardConfig
from hardboiled.hardware.external import ExternalPeripheral
from hardboiled.hardware.keypad_ref import Keypad4x4


def test_config_peripheral_external() -> None:
    board_toml = """
    [board]
    name = "test-external"
    clock_hz = 1_000_000

    [memory]
    flash_base = "0x00010000"
    flash_size_kb = 64
    sram_base  = "0x20000000"
    sram_size_kb  = 64
    mmio_base  = "0x40000000"

    [[peripherals]]
    name = "keypad"
    type = "external"
    offset = "0x50"
    external_size = 16
    irq_line = 3
    """
    data = tomllib.loads(board_toml)
    cfg = BoardConfig.model_validate(data)
    ext = next(p for p in cfg.peripherals if p.name == "keypad")
    assert ext.type == "external"
    assert ext.offset == 0x50
    assert ext.size == 16
    assert ext.irq_line == 3


def test_external_peripheral_rw_and_irq() -> None:
    irq_asserted = []

    def raise_irq(line: int) -> None:
        irq_asserted.append((line, True))

    def lower_irq(line: int) -> None:
        irq_asserted.append((line, False))

    dev = ExternalPeripheral(
        name="ext0",
        offset=0x50,
        size=16,
        irq_line=4,
        raise_irq=raise_irq,
        lower_irq=lower_irq,
    )

    assert dev.size == 16
    assert dev.read(0) == 0

    dev.update_shadow(0x04, 0x12345678)
    assert dev.read(0x04) == 0x12345678

    dev.write(0x00, 0xAA, 0xFF)
    assert dev.read(0x00) == 0xAA

    dev.trigger_irq(True)
    dev.trigger_irq(False)
    assert irq_asserted == [(4, True), (4, False)]


def test_keypad_reference_model() -> None:
    keypad = Keypad4x4()
    # Sin teclas apretadas
    keypad.write_filas(0x0F)
    assert keypad.read_columnas() == 0x00

    # Apretar tecla '5' (fila 1, columna 1)
    keypad.press(1, 1)

    # Barrido fila 0: no coincide
    keypad.write_filas(0x01)
    assert keypad.read_columnas() == 0x00

    # Barrido fila 1: coincide y columna 1 se activa (bit 1 = 0x02)
    keypad.write_filas(0x02)
    assert keypad.read_columnas() == 0x02

    # Soltar tecla
    keypad.release(1, 1)
    assert keypad.read_columnas() == 0x00


def test_firmware_teclado_matricial_determinista(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("HARDBOILED_CC", "zig")

    board_toml = """
    [board]
    name = "board-keypad"
    clock_hz = 1_000_000

    [memory]
    flash_base = "0x00010000"
    flash_size_kb = 64
    sram_base  = "0x20000000"
    sram_size_kb  = 64
    mmio_base  = "0x40000000"

    [[peripherals]]
    name = "uart0"
    type = "uart"
    offset = "0x10"

    [[peripherals]]
    name = "keypad"
    type = "external"
    offset = "0x50"
    external_size = 16
    """
    (tmp_path / "board.toml").write_text(board_toml, encoding="utf-8")

    src_dir = Path(__file__).resolve().parent.parent / "src" / "hardboiled" / "examples"
    src_file = src_dir / "teclado_matricial.c"
    (tmp_path / "main.c").write_text(src_file.read_text(encoding="utf-8"), encoding="utf-8")

    # Guion donde inyectamos en ciclo 100 que la tecla '5' está apretada (columna 1 activa = 0x02)
    guion_toml = """
    [[at]]
    cycle = 100
    external_write = [["keypad", 4, 2]]
    """
    (tmp_path / "guion.toml").write_text(guion_toml, encoding="utf-8")

    casos_toml = """
    [[case]]
    name = "teclado_detecta_5"
    script = "guion.toml"
    expect_exit = 0
    expect_uart_contains = ["Tecla detectada: 5"]
    """
    (tmp_path / "casos.toml").write_text(casos_toml, encoding="utf-8")

    # Ejecutar hardboiled test dos veces para comprobar determinismo
    for _ in range(2):
        ret = main(["test", "main.c", "--suite", "casos.toml"])
        out = capsys.readouterr().out
        assert ret == 0, f"Falla en test: {out}"
        assert "ok    teclado_detecta_5" in out
        assert "1/1 casos correctos" in out
