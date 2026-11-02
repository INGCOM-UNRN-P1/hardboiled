"""SPA y WebSocket de loopback. Sólo el runner lee o modifica los modelos MMIO."""

from __future__ import annotations

import asyncio
import contextlib
import json
import queue
import threading
from http import HTTPStatus
from importlib.resources import files
from types import TracebackType
from typing import Any

from cast_tools_common.seguridad import es_loopback
from websockets.asyncio.server import ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.http11 import Request, Response

from hardboiled.core.events import CmdKeyEvent, CmdWebState, Command
from hardboiled.core.machine import Machine
from hardboiled.hardware.external import ExternalPeripheral

ASSETS = {
    "/": ("index.html", "text/html"),
    "/app.js": ("app.js", "text/javascript"),
    "/style.css": ("style.css", "text/css"),
}


class WebBridge:
    def __init__(self, machine: Machine, commands: queue.Queue[Command], port: int = 8768) -> None:
        self.commands, self.port = commands, port
        self.catalog = [
            {"name": dev.name, "type": dev.model_kind, "offset": dev.offset, "size": dev.size}
            for dev in machine.peripherals
            if isinstance(dev, ExternalPeripheral) and dev.model is not None
        ]
        if not self.catalog:
            raise ValueError("--web necesita periféricos external con external_model en la placa")
        self.board = machine.board.board.name
        self.keypads = {dev["name"] for dev in self.catalog if dev["type"] == "keypad_4x4"}
        self.clients: dict[ServerConnection, set[tuple[str, int, int]]] = {}
        self.ready = threading.Event()
        self.error: BaseException | None = None
        self.loop: asyncio.AbstractEventLoop | None = None
        self.stop: asyncio.Event | None = None
        self.thread = threading.Thread(target=self._run, name="hardboiled-web", daemon=True)

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}/"

    def __enter__(self) -> WebBridge:
        self.thread.start()
        if not self.ready.wait(10):
            raise OSError("el panel web no pudo iniciar a tiempo")
        if self.error:
            raise OSError(f"no se pudo iniciar el panel web: {self.error}")
        return self

    def __exit__(
        self,
        typ: type[BaseException] | None,
        value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self.loop and self.stop:
            self.loop.call_soon_threadsafe(self.stop.set)
        self.thread.join(timeout=5)

    def _run(self) -> None:
        try:
            asyncio.run(self._serve())
        except BaseException as exc:
            self.error = exc
            self.ready.set()

    async def _serve(self) -> None:
        self.loop, self.stop = asyncio.get_running_loop(), asyncio.Event()
        async with serve(
            self.handle,
            "127.0.0.1",
            self.port,
            process_request=self.request,
            max_size=1024,
            max_queue=8,
            close_timeout=1,
        ) as server:
            self.port = server.sockets[0].getsockname()[1]
            self.ready.set()
            task = asyncio.create_task(self.broadcast())
            try:
                await self.stop.wait()
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    def request(self, connection: ServerConnection, request: Request) -> Response | None:
        host = request.headers.get("Host", "")
        origins = {f"http://127.0.0.1:{self.port}", f"http://localhost:{self.port}"}
        local_hosts = {f"127.0.0.1:{self.port}", f"localhost:{self.port}"}
        ip = str(connection.remote_address[0]) if connection.remote_address else ""
        origin = request.headers.get("Origin")
        if (
            not es_loopback(ip)
            or host not in local_hosts
            or (origin is not None and origin != f"http://{host}")
        ):
            return connection.respond(HTTPStatus.FORBIDDEN, "Origen local requerido\n")
        if request.path == "/ws":
            if origin not in origins:
                return connection.respond(HTTPStatus.FORBIDDEN, "Origin requerido\n")
            return None
        if request.path not in ASSETS:
            return connection.respond(HTTPStatus.NOT_FOUND, "No existe ese recurso\n")
        name, mime = ASSETS[request.path]
        body = files("hardboiled").joinpath("web_assets", name).read_text(encoding="utf-8")
        response = connection.respond(HTTPStatus.OK, body)
        del response.headers["Content-Type"]
        response.headers["Content-Type"] = f"{mime}; charset=utf-8"
        response.headers["Cache-Control"] = "no-store"
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Content-Security-Policy"] = (
            "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
            "frame-ancestors 'none'; base-uri 'none'"
        )
        return response

    async def broadcast(self) -> None:
        while True:
            if self.clients and self.commands.qsize() < 128:
                reply: queue.Queue[dict[str, Any]] = queue.Queue(maxsize=1)
                self.commands.put_nowait(CmdWebState(reply))
                try:
                    state = await asyncio.to_thread(reply.get, True, 0.5)
                except queue.Empty:
                    continue
                payload = json.dumps(state)
                for ws in tuple(self.clients):
                    try:
                        await asyncio.wait_for(ws.send(payload), 0.25)
                    except (ConnectionClosed, TimeoutError):
                        await ws.close(1013, "cliente lento")
            await asyncio.sleep(1 / 30)

    def key(self, ws: ServerConnection, msg: Any) -> None:
        if not isinstance(msg, dict) or msg.get("cmd") != "KEY_EVENT":
            raise ValueError("comando inválido")
        device, row, col, pressed = (msg.get(key) for key in ("device", "row", "col", "pressed"))
        if (
            not isinstance(device, str)
            or device not in self.keypads
            or type(row) is not int
            or type(col) is not int
            or not 0 <= row < 4
            or not 0 <= col < 4
            or type(pressed) is not bool
        ):
            raise ValueError("tecla inválida")
        key = (device, row, col)
        owned = self.clients[ws]
        if pressed and self.commands.qsize() >= 128:
            raise ValueError("el motor está ocupado")
        active = any(key in keys for keys in self.clients.values())
        if pressed:
            owned.add(key)
            if not active:
                self.commands.put_nowait(CmdKeyEvent(device, row, col, True))
        else:
            owned.discard(key)
            if active and not any(key in keys for keys in self.clients.values()):
                self.commands.put_nowait(CmdKeyEvent(device, row, col, False))

    async def handle(self, ws: ServerConnection) -> None:
        if len(self.clients) >= 8:
            await ws.close(1013, "demasiados paneles")
            return
        self.clients[ws] = set()
        try:
            await ws.send(
                json.dumps({"type": "HELLO", "board": self.board, "peripherals": self.catalog})
            )
            async for raw in ws:
                try:
                    self.key(ws, json.loads(raw))
                except (ValueError, TypeError):
                    await ws.send(
                        json.dumps({"type": "ERROR", "message": "Evento de tecla inválido"})
                    )
        except ConnectionClosed:
            pass
        finally:
            owned = self.clients.pop(ws)
            for device, row, col in owned:
                if not any((device, row, col) in keys for keys in self.clients.values()):
                    self.commands.put_nowait(CmdKeyEvent(device, row, col, False))
