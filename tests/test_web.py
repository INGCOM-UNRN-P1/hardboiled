"""HTTP/WS reales: origen, aislamiento local, estado del runner y teclas por cliente."""

from __future__ import annotations

import asyncio
import json
import queue
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest
from websockets.asyncio.client import connect
from websockets.exceptions import InvalidStatus
from websockets.typing import Origin

from hardboiled.config import load_board
from hardboiled.core.events import CmdShutdown, Command, Event
from hardboiled.core.machine import Machine
from hardboiled.core.runner import RunnerThread
from hardboiled.web import WebBridge
from tests.conftest import FIXTURES

ROOT = FIXTURES.parent.parent


@pytest.fixture
def web(monkeypatch: pytest.MonkeyPatch) -> Iterator[WebBridge]:
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    machine = Machine.from_elf(
        FIXTURES / "basic.elf", load_board(ROOT / "docs/examples/panel_web.toml")
    )
    lcd = machine.external("lcd")
    assert lcd is not None
    lcd.write(0, 0x0C, 255)
    lcd.write(4, 72, 255)
    commands: queue.Queue[Command] = queue.Queue()
    runner = RunnerThread(machine, commands, queue.Queue[Event]())
    runner.start()
    bridge = WebBridge(machine, commands, 0)
    try:
        with bridge:
            yield bridge
    finally:
        commands.put(CmdShutdown())
        runner.join(5)
    assert not runner.is_alive()
    assert not bridge.thread.is_alive() and bridge.error is None


def test_static_assets_and_security(web: WebBridge) -> None:
    fetch = build_opener(ProxyHandler({})).open
    for path, mime in [("", "text/html"), ("app.js", "text/javascript"), ("style.css", "text/css")]:
        with fetch(web.url + path, timeout=2) as response:
            assert response.status == 200
            assert response.headers.get_content_type() == mime
            assert len(response.headers.get_all("Content-Type")) == 1
            assert "frame-ancestors 'none'" in response.headers["Content-Security-Policy"]
            assert response.read()
    for path, headers, status in [
        ("../pyproject.toml", {}, 404),
        ("not-found", {}, 404),
        ("", {"Origin": "https://evil.example"}, 403),
        ("", {"Host": f"evil.example:{web.port}"}, 403),
        ("ws", {}, 403),
    ]:
        with pytest.raises(HTTPError) as exc:
            fetch(Request(web.url + path, headers=headers), timeout=2)
        assert exc.value.code == status


async def state(ws: Any) -> dict[str, Any]:
    for _ in range(30):
        result: dict[str, Any] = json.loads(await asyncio.wait_for(ws.recv(), 2))
        if result["type"] == "STATE":
            return result
    raise AssertionError("no llegó STATE")


def event(pressed: bool = True, **extra: Any) -> str:
    return json.dumps(
        {"cmd": "KEY_EVENT", "device": "keypad", "row": 1, "col": 1, "pressed": pressed, **extra}
    )


async def test_ws_state_reconnect_and_key_ownership(web: WebBridge) -> None:
    url, origin = web.url.replace("http:", "ws:") + "ws", Origin(web.url.rstrip("/"))
    async with connect(url, origin=origin) as first, connect(url, origin=origin) as second:
        hello = json.loads(await first.recv())
        assert hello["type"] == "HELLO" and len(hello["peripherals"]) == 3
        assert (await state(first))["devices"]["lcd"]["cells"][0][0] == 72
        await first.send(event())
        for _ in range(30):
            if (await state(first))["devices"]["keypad"]["pressed"] == [[1, 1]]:
                break
        else:
            pytest.fail("no se aplicó la tecla")
        await second.send(event())
        # Espera una confirmación del servidor antes de cerrar el primer propietario.
        for _ in range(3):
            await state(second)
        await first.close()
        assert (await state(second))["devices"]["keypad"]["pressed"] == [[1, 1]]
        await second.send(event(False))
        for _ in range(30):
            if not (await state(second))["devices"]["keypad"]["pressed"]:
                break
        else:
            pytest.fail("no se soltó la tecla")
        await second.send(event())
        for _ in range(3):
            await state(second)
    async with connect(url, origin=origin) as again:
        result = await state(again)
        assert result["devices"]["keypad"]["pressed"] == []
        assert result["devices"]["lcd"]["cells"][0][0] == 72


async def test_ws_rejects_origin_and_invalid_input(web: WebBridge) -> None:
    url = web.url.replace("http:", "ws:") + "ws"
    for origin in (None, Origin("https://evil.example"), Origin("null")):
        with pytest.raises(InvalidStatus):
            async with connect(url, origin=origin):
                pytest.fail("aceptó un origen ajeno")
    async with connect(url, origin=Origin(web.url.rstrip("/"))) as ws:
        for msg in ("[]", "null", "{", event(row=True), event(device="lcd"), event(col=4)):
            await ws.send(msg)
            while True:
                answer = json.loads(await asyncio.wait_for(ws.recv(), 2))
                if answer["type"] == "ERROR":
                    break
        assert not (await state(ws))["devices"]["keypad"]["pressed"]


def test_cli_rejects_invalid_combinations() -> None:
    from hardboiled.cli import main

    assert main(["run", "missing.c", "--web", "--headless"]) == 2
    assert main(["run", "missing.c", "--web", "--web-port", "65536"]) == 2
    assert main(["run", str(FIXTURES / "basic.elf"), "--web"]) == 2


async def test_tui_opens_local_panel(monkeypatch: pytest.MonkeyPatch) -> None:
    from hardboiled.ui.tui import HardboiledApp

    opened: list[str] = []
    monkeypatch.setattr("hardboiled.ui.tui.open_browser", lambda url: opened.append(url))
    app = HardboiledApp(
        queue.Queue[Command](), queue.Queue[Event](), web_url="http://127.0.0.1:8768/"
    )
    async with app.run_test(size=(120, 40)) as pilot:
        assert app.sub_title == "Web: http://127.0.0.1:8768/"
        await pilot.press("ctrl+w")
        assert opened == ["http://127.0.0.1:8768/"]
