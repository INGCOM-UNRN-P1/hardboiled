"""Prueba opcional de navegador con firmware RV32I real. HARDBOILED_BROWSER=1."""

from __future__ import annotations

import os
import queue
from pathlib import Path

import pytest

from hardboiled.cli import main
from hardboiled.config import load_board
from hardboiled.core.events import CmdContinue, CmdShutdown, Command, Event, EvtCpuSuspended
from hardboiled.core.machine import Machine
from hardboiled.core.runner import RunnerThread
from hardboiled.web import WebBridge

ROOT = Path(__file__).parents[1]
pytestmark = pytest.mark.skipif(
    os.environ.get("HARDBOILED_BROWSER") != "1", reason="requiere Chromium"
)


def test_browser_firmware_lcd_rgb_and_keypad(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from playwright.sync_api import expect, sync_playwright

    monkeypatch.setenv("HARDBOILED_CC", "zig")
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    board = ROOT / "docs/examples/panel_web.toml"
    elf = tmp_path / "web.elf"
    assert (
        main(
            [
                "build",
                str(ROOT / "docs/examples/panel_web.c"),
                "--board",
                str(board),
                "-o",
                str(elf),
            ]
        )
        == 0
    )
    machine = Machine.from_elf(elf, load_board(board))
    commands: queue.Queue[Command] = queue.Queue()
    events: queue.Queue[Event] = queue.Queue()
    runner = RunnerThread(machine, commands, events)
    runner.start()
    try:
        while not isinstance(events.get(timeout=5), EvtCpuSuspended):
            pass
        commands.put(CmdContinue())
        with WebBridge(machine, commands, 0) as bridge, sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": 1360, "height": 1000})
            errors: list[str] = []
            page.on("pageerror", lambda error: errors.append(str(error)))
            page.goto(bridge.url)
            expect(page.locator("#status")).to_have_text("Conectado")
            expect(page.locator(".lcd-readable")).to_contain_text("Hola hardboiled")
            expect(page.locator(".lcd-readable")).to_contain_text("Tecla: -")
            expect(page.locator(".percent").nth(0)).to_have_text("25.0 %")
            expect(page.locator(".timing")).to_contain_text("1000.0 Hz")
            button = page.get_by_role("button", name="5", exact=True)
            button.hover()
            page.mouse.down()
            expect(page.locator(".lcd-readable")).to_contain_text("Tecla: 5")
            expect(page.locator(".percent").nth(0)).to_have_text("100.0 %")
            page.mouse.up()
            expect(page.locator(".lcd-readable")).to_contain_text("Tecla: -")
            page.keyboard.down("a")
            expect(page.locator(".lcd-readable")).to_contain_text("Tecla: A")
            page.keyboard.up("a")
            page.keyboard.down("5")
            expect(button).to_have_attribute("aria-pressed", "true")
            page.evaluate("window.dispatchEvent(new Event('blur'))")
            expect(button).to_have_attribute("aria-pressed", "false")
            page.keyboard.up("5")
            page.keyboard.down("5")
            expect(button).to_have_attribute("aria-pressed", "true")
            page.get_by_role("slider").focus()
            page.keyboard.up("5")
            expect(button).to_have_attribute("aria-pressed", "false")
            page.reload()
            expect(page.locator(".lcd-readable")).to_contain_text("Hola hardboiled")
            expect(page.locator(".percent").nth(2)).to_have_text("75.0 %")
            if destination := os.environ.get("HARDBOILED_SCREENSHOT"):
                page.screenshot(path=destination, full_page=True)
            page.set_viewport_size({"width": 375, "height": 812})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth")
            expect(page.get_by_role("button", name="D", exact=True)).to_be_visible()
            if destination := os.environ.get("HARDBOILED_SCREENSHOT"):
                page.screenshot(
                    path=str(Path(destination).with_name("panel_mobile.png")), full_page=True
                )
            assert not errors
            browser.close()
    finally:
        commands.put(CmdShutdown())
        runner.join(5)
    assert not runner.is_alive()
