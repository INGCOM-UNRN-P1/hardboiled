"""Contrato móvil: autenticación real, capacidades y muestras hasta ADC/MMIO."""

from __future__ import annotations

import asyncio
import json
import queue
from pathlib import Path
from typing import Any

import pytest
from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from websockets.typing import Origin

from hardboiled.config import BoardConfig
from hardboiled.core.events import CmdExternalIrq, CmdSetAdcInputs, Command, Event
from hardboiled.core.machine import Machine
from hardboiled.core.runner import RunnerThread
from hardboiled.hardware.adc import CTRL, CTRL_START, DATA
from hardboiled.remote import RemoteBridge

FIXTURE = Path(__file__).parent / "fixtures/basic.elf"


@pytest.fixture
def bridge(monkeypatch: pytest.MonkeyPatch) -> RemoteBridge:
    monkeypatch.setenv("no_proxy", "127.0.0.1,localhost")
    monkeypatch.setenv("NO_PROXY", "127.0.0.1,localhost")
    board = BoardConfig.model_validate(
        {
            "peripherals": [
                {"name": "adc0", "type": "adc", "offset": "0x80", "channels": 4},
                {"name": "impact", "type": "external", "offset": "0x100", "irq_line": 3},
            ]
        }
    )
    return RemoteBridge(
        Machine.from_elf(FIXTURE, board), queue.Queue[Command](), "127.0.0.1", 0, "127.0.0.1"
    )


def message(action: str, **payload: Any) -> str:
    return json.dumps({"version": "1.3", "action": action, "payload": payload})


async def receive(ws: Any) -> dict[str, Any]:
    result: dict[str, Any] = json.loads(await asyncio.wait_for(ws.recv(), 2))
    return result


async def test_pairing_capabilities_sensor_and_token(bridge: RemoteBridge) -> None:
    async with serve(bridge.handle, "127.0.0.1", 0) as server:
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}/ws"
        async with connect(url) as ws:
            await ws.send(message("ADC_SAMPLE", device="adc0", millivolts=[0, 1650, 3300]))
            assert (await receive(ws))["action"] == "PAIRING_FAILED"
            assert bridge.commands.empty()
            await ws.send(message("PAIR_REQUEST", pin=bridge.pin))
            paired = await receive(ws)
            token = paired["payload"]["token"]
            assert paired["action"] == "PAIRING_SUCCESS"
            await ws.send(message("GET_CAPABILITIES"))
            caps = (await receive(ws))["payload"]
            assert caps["service"] == "hardboiled"
            assert caps["capabilities"][0]["vref_mv"] == 3300
            await ws.send(message("ADC_SAMPLE", device="adc0", millivolts=[0, 1650, 3300]))
            await ws.send(message("GET_CAPABILITIES"))
            await receive(ws)
            assert bridge.commands.get_nowait() == CmdSetAdcInputs("adc0", (0, 1650, 3300))
        async with connect(url) as ws:
            await ws.send(message("PAIR_REQUEST", token=token))
            assert (await receive(ws))["action"] == "PAIRING_SUCCESS"


async def test_rate_limit_malformed_and_origin(bridge: RemoteBridge) -> None:
    async with serve(bridge.handle, "127.0.0.1", 0) as server:
        url = f"ws://127.0.0.1:{server.sockets[0].getsockname()[1]}"
        async with connect(url, origin=Origin("https://example.org")) as ws:
            with pytest.raises(ConnectionClosed):
                await ws.recv()
        async with connect(url) as ws:
            for raw in ("null", "[]", "{"):
                await ws.send(raw)
                assert (await receive(ws))["type"] == "error"
            for _ in range(5):
                await ws.send(message("PAIR_REQUEST", pin="000000"))
                assert (await receive(ws))["action"] == "PAIRING_FAILED"
            await ws.send(message("PAIR_REQUEST", pin=bridge.pin))
            with pytest.raises(ConnectionClosed):
                await ws.recv()
            assert bridge.commands.empty()


@pytest.mark.parametrize("values", [[1, True, 3], [1, 2, 3301], [1, 2]])
def test_invalid_samples_do_not_reach_motor(bridge: RemoteBridge, values: list[int]) -> None:
    with pytest.raises(ValueError):
        bridge.command("ADC_SAMPLE", {"device": "adc0", "millivolts": values})
    assert bridge.commands.empty()


def test_motor_applies_samples_before_firmware_conversion(bridge: RemoteBridge) -> None:
    board = BoardConfig.model_validate(
        {
            "peripherals": [
                {"name": "adc0", "type": "adc", "offset": "0x80", "channels": 4},
            ]
        }
    )
    machine = Machine.from_elf(FIXTURE, board)
    runner = RunnerThread(machine, bridge.commands, queue.Queue[Event]())
    bridge.command("ADC_SAMPLE", {"device": "adc0", "millivolts": [0, 1650, 3300]})
    runner._apply_live(bridge.commands.get_nowait())
    adc = machine.adc()
    assert adc is not None
    assert adc.millivolts[:3] == [0, 1650, 3300]
    adc.write(CTRL, 2 | CTRL_START, 0xFFFFFFFF)
    adc.service(machine.cpu.clock.cycles + adc.conversion_cycles)
    assert adc.read(DATA) == adc.max_code


def test_queue_backpressure_and_irq(bridge: RemoteBridge) -> None:
    bridge.command("IRQ_RAISE", {"device": "impact"})
    assert bridge.commands.get_nowait() == CmdExternalIrq("impact", True)
    for _ in range(256):
        bridge.command("ADC_SAMPLE", {"device": "adc0", "millivolts": [0, 0, 0]})
    with pytest.raises(ValueError, match="ocupado"):
        bridge.command("ADC_SAMPLE", {"device": "adc0", "millivolts": [0, 0, 0]})


def test_requires_adc_and_cli_options() -> None:
    from hardboiled.cli import build_parser

    with pytest.raises(ValueError, match="ADC"):
        RemoteBridge(Machine.from_elf(FIXTURE), queue.Queue[Command]())
    args = build_parser().parse_args(["run", "example.c", "--remote", "--remote-port", "9999"])
    assert args.remote and args.remote_port == 9999


async def test_thread_lifecycle_and_pairing(bridge: RemoteBridge) -> None:
    with bridge:
        assert bridge.port > 0
        assert "service=hardboiled" in bridge.banner()
        async with connect(f"ws://127.0.0.1:{bridge.port}/ws") as ws:
            await ws.send(message("PAIR_REQUEST", pin=bridge.pin))
            assert (await receive(ws))["action"] == "PAIRING_SUCCESS"
    assert not bridge.thread.is_alive()
    assert bridge.error is None
    assert len(bridge.tokens) == 0


async def test_pairing_visible_inside_tui() -> None:
    from hardboiled.ui.tui import HardboiledApp
    from hardboiled.ui.widgets.pairing_screen import PairingScreen

    app = HardboiledApp(queue.Queue[Command](), queue.Queue[Event](), remote_banner="PIN: 123456")
    async with app.run_test(size=(120, 40)) as pilot:
        await pilot.pause()
        assert isinstance(app.screen, PairingScreen)
        assert app.screen.banner == "PIN: 123456"
        await pilot.press("escape")
        assert not isinstance(app.screen, PairingScreen)
        await pilot.press("ctrl+k")
        assert isinstance(app.screen, PairingScreen)
