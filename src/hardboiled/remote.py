"""Puente móvil autenticado. La red nunca modifica la máquina fuera de su hilo."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from types import TracebackType
from typing import Any

from cast_tools_common.discovery import (
    MdnsPublisher,
    build_pairing_uri,
    generate_qr_ascii,
    get_local_ip,
)
from cast_tools_common.seguridad import (
    LimitadorIntentos,
    TokensEfimeros,
    generar_pin,
    pin_correcto,
)
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed

from hardboiled.core.events import CmdExternalIrq, CmdPressButton, CmdSetAdcInputs, Command
from hardboiled.core.machine import Machine


def envelope(action: str, payload: dict[str, Any], kind: str = "event") -> str:
    return json.dumps(
        {
            "version": "1.3",
            "sessionId": "hardboiled",
            "source": "daemon",
            "type": kind,
            "action": action,
            "payload": payload,
        }
    )


class RemoteBridge:
    def __init__(
        self,
        machine: Machine,
        commands: queue.Queue[Command],
        host: str = "0.0.0.0",
        port: int = 8767,
        advertise_host: str | None = None,
    ) -> None:
        adc = machine.adc()
        if adc is None or adc.channels < 3:
            raise ValueError("--remote necesita una placa con ADC de al menos tres canales")
        self.device, self.vref = adc.name, adc.vref_mv
        buttons = machine.buttons()
        self.buttons = buttons.width_bits if buttons is not None else 0
        external = machine.external()
        self.irq_device = external.name if external and external.irq_line is not None else None
        self.commands = commands
        self.host, self.port = host, port
        self.advertise_host = advertise_host or get_local_ip()
        self.pin = generar_pin()
        self.session_id = uuid.uuid4().hex
        self.tokens, self.attempts = TokensEfimeros(), LimitadorIntentos()
        self.ready = threading.Event()
        self.error: BaseException | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stop: asyncio.Event | None = None
        self.thread = threading.Thread(target=self._run, name="hardboiled-remote", daemon=True)

    def banner(self) -> str:
        uri = build_pairing_uri("hardboiled", self.advertise_host, self.port, self.pin)
        return (
            f"Cyberdeck: {self.advertise_host}:{self.port}  PIN: {self.pin}\n{uri}\n"
            + generate_qr_ascii(uri)
        )

    def __enter__(self) -> RemoteBridge:
        self.thread.start()
        if not self.ready.wait(15):
            raise OSError("el puente remoto no pudo iniciar a tiempo")
        if self.error:
            raise OSError(f"no se pudo iniciar el puente remoto: {self.error}")
        return self

    def __exit__(
        self,
        typ: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.loop and self.stop:
            self.loop.call_soon_threadsafe(self.stop.set)
        self.thread.join(timeout=15)

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as exc:
            self.error = exc
            self.ready.set()

    async def _serve(self) -> None:
        self.loop = asyncio.get_running_loop()
        self.stop = asyncio.Event()
        async with serve(
            self.handle,
            self.host,
            self.port,
            max_size=4096,
            max_queue=8,
            ping_interval=20,
            close_timeout=1,
        ) as server:
            self.port = server.sockets[0].getsockname()[1]
            publisher = MdnsPublisher(
                f"hardboiled-{self.session_id[:12]}",
                "_bridge-remote._tcp.local.",
                self.port,
                {
                    "service": "hardboiled",
                    "version": "1.3",
                    "requires_pin": "1",
                    "id": self.session_id,
                    "name": "Hardboiled",
                },
                self.advertise_host,
            )
            self.ready.set()
            try:
                await publisher.start()
                await self.stop.wait()
            finally:
                await publisher.stop()
                self.tokens.revocar_todos()

    def capabilities(self) -> dict[str, Any]:
        capabilities: list[dict[str, Any]] = [
            {
                "id": "accelerometer",
                "action": "ADC_SAMPLE",
                "enabled": True,
                "controlType": "accelerometer",
                "device": self.device,
                "channels": [0, 1, 2],
                "vref_mv": self.vref,
                "min_hz": 20,
                "max_hz": 60,
            }
        ]
        if self.buttons:
            capabilities.append(
                {
                    "id": "buttons",
                    "action": "BUTTON_PRESS",
                    "enabled": True,
                    "controlType": "button_bank",
                    "count": self.buttons,
                }
            )
        if self.irq_device:
            capabilities.append(
                {
                    "id": "shake",
                    "action": "IRQ_RAISE",
                    "enabled": True,
                    "controlType": "shake",
                    "device": self.irq_device,
                }
            )
        return {"service": "hardboiled", "capabilities": capabilities}

    def command(self, action: str, payload: dict[str, Any]) -> None:
        command: Command
        if action == "ADC_SAMPLE":
            values = payload.get("millivolts")
            if (
                payload.get("device") != self.device
                or not isinstance(values, list)
                or len(values) != 3
                or any(type(v) is not int or not 0 <= v <= self.vref for v in values)
            ):
                raise ValueError("muestra ADC inválida")
            command = CmdSetAdcInputs(self.device, (values[0], values[1], values[2]))
        elif action == "BUTTON_PRESS":
            pin = payload.get("pin")
            if type(pin) is not int or not 0 <= pin < self.buttons:
                raise ValueError("botón inválido")
            command = CmdPressButton(pin)
        elif action in ("IRQ_RAISE", "IRQ_LOWER") and self.irq_device:
            if payload.get("device") != self.irq_device:
                raise ValueError("periférico IRQ inválido")
            command = CmdExternalIrq(self.irq_device, action == "IRQ_RAISE")
        else:
            raise ValueError("acción no disponible")
        if self.commands.qsize() >= 256:
            raise ValueError("el motor está ocupado")
        self.commands.put_nowait(command)

    async def handle(self, ws: ServerConnection) -> None:
        # Android no manda Origin. Ningún sitio web puede intentar emparejarse.
        if ws.request and ws.request.headers.get("Origin") is not None:
            await ws.close(1008, "origen web no permitido")
            return
        ip = str(ws.remote_address[0]) if ws.remote_address else "unknown"
        authenticated = False
        try:
            while True:
                try:
                    raw = await asyncio.wait_for(ws.recv(), timeout=None if authenticated else 15)
                except TimeoutError:
                    await ws.close(1008, "tiempo de emparejamiento agotado")
                    return
                try:
                    msg = json.loads(raw)
                    if not isinstance(msg, dict) or msg.get("version") != "1.3":
                        raise ValueError("mensaje inválido")
                    action, payload = msg.get("action"), msg.get("payload", {})
                    if not isinstance(payload, dict):
                        raise ValueError("payload inválido")
                    if not authenticated:
                        if self.attempts.bloqueada(ip):
                            await ws.close(1008, "demasiados intentos")
                            return
                        if action != "PAIR_REQUEST" or not (
                            self.tokens.validar(payload.get("token"))
                            or pin_correcto(payload.get("pin"), self.pin)
                        ):
                            self.attempts.fallo(ip)
                            await ws.send(envelope("PAIRING_FAILED", {}, "error"))
                            continue
                        self.attempts.exito(ip)
                        authenticated = True
                        token = (
                            payload.get("token")
                            if self.tokens.validar(payload.get("token"))
                            else self.tokens.emitir(ip)
                        )
                        await ws.send(
                            envelope("PAIRING_SUCCESS", {"token": token, "service": "hardboiled"})
                        )
                    elif action == "GET_CAPABILITIES":
                        await ws.send(envelope("CAPABILITIES_LIST", self.capabilities()))
                    else:
                        self.command(str(action), payload)
                except (ValueError, TypeError, KeyError):
                    await ws.send(envelope("INVALID_COMMAND", {}, "error"))
        except ConnectionClosed:
            pass
        finally:
            if authenticated and self.irq_device:
                # Evita una IRQ pegada cuando el teléfono pierde Wi-Fi.
                self.commands.put_nowait(CmdExternalIrq(self.irq_device, False))
