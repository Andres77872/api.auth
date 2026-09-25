"""Real TCP upgrade tests: ASGI TestClient bypasses Uvicorn's WS dependencies."""
import asyncio
import base64
from contextlib import asynccontextmanager
import json
import logging
import os
import socket
import struct
from types import SimpleNamespace

from fastapi import FastAPI
import pytest
import uvicorn

from src.assistant import readiness
from src.assistant.service import AssistantService
from tests.helpers.assistant_sqlite import AssistantStore
from src.routes.assistant import router

pytestmark = pytest.mark.integration


@asynccontextmanager
async def network_server(tmp_path, monkeypatch, *, protocol="auto"):
    monkeypatch.setenv("ALLOWED_ORIGINS", "http://dashboard.test")
    app = FastAPI()
    app.include_router(router)

    async def authenticate(token):
        assert token == "network-root"
        return SimpleNamespace(user_id="root", user_type="root")

    service = AssistantService(app, AssistantStore(tmp_path / "assistant"), authenticator=authenticate)
    app.state.assistant_service = service
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, ws=protocol, loop="asyncio", http="h11",
                                        log_config=None, access_log=False, lifespan="off"))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                    raise AssertionError("Uvicorn stopped before opening the test socket")
                await asyncio.sleep(0.01)
        yield port
    finally:
        server.should_exit = True
        await service.close()
        try:
            await asyncio.wait_for(task, timeout=5)
        finally:
            listener.close()


async def handshake(port, *, origin="http://dashboard.test"):
    reader, writer = await asyncio.open_connection("127.0.0.1", port)
    key = base64.b64encode(os.urandom(16)).decode()
    writer.write((
        f"GET /admin/assistant/ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\n"
        "Upgrade: websocket\r\nConnection: Upgrade\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n"
        f"Origin: {origin}\r\nCookie: session_token=network-root\r\n\r\n"
    ).encode())
    await writer.drain()
    response = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), timeout=3)
    return response, reader, writer


def masked_text(payload):
    encoded = json.dumps(payload).encode()
    assert len(encoded) < 126
    mask = b"\x11\x22\x33\x44"
    return bytes([0x81, 0x80 | len(encoded)]) + mask + bytes(byte ^ mask[i % 4] for i, byte in enumerate(encoded))


async def read_text(reader):
    first, second = await reader.readexactly(2)
    assert first & 0x0F == 1, "Expected a text frame from the real assistant socket"
    assert not second & 0x80, "Server-to-client frames must not be masked"
    length = second & 0x7F
    if length == 126:
        length = struct.unpack("!H", await reader.readexactly(2))[0]
    elif length == 127:
        length = struct.unpack("!Q", await reader.readexactly(8))[0]
    return json.loads(await reader.readexactly(length))


async def close_client(writer):
    writer.close()
    await writer.wait_closed()


@pytest.mark.asyncio
async def test_uvicorn_auto_upgrades_real_assistant_socket_and_serves_rpc(tmp_path, monkeypatch):
    # Deliberately no importorskip: absent transport is a broken deployment,
    # even though in-memory TestClient WebSocket tests would still pass.
    assert readiness.websocket_transport_available(), "Install requirements.txt into the Python interpreter running Uvicorn"
    async with network_server(tmp_path, monkeypatch) as port:
        response, reader, writer = await handshake(port)
        try:
            assert response.startswith(b"HTTP/1.1 101 "), response.decode()
            writer.write(masked_text({"id": "network-ping", "method": "ping", "params": {}}))
            await writer.drain()
            reply = await asyncio.wait_for(read_text(reader), timeout=3)
            assert reply["id"] == "network-ping"
            assert isinstance(reply["result"]["time"], (int, float))
        finally:
            await close_client(writer)


@pytest.mark.asyncio
async def test_real_network_rejects_cross_origin_upgrade(tmp_path, monkeypatch):
    async with network_server(tmp_path, monkeypatch) as port:
        response, _, writer = await handshake(port, origin="https://attacker.test")
        try:
            assert response.startswith(b"HTTP/1.1 403 "), response.decode()
        finally:
            await close_client(writer)


@pytest.mark.asyncio
async def test_missing_uvicorn_auto_protocol_reproduces_404_and_actionable_warning(tmp_path, monkeypatch, caplog):
    # Uvicorn sets this to None when neither websockets nor wsproto imports.
    # Exercise the real HTTP fallback, not a manually invented ASGI scope.
    from uvicorn.protocols.websockets import auto
    monkeypatch.setattr(auto, "AutoWebSocketsProtocol", None)
    with caplog.at_level(logging.WARNING):
        assert not readiness.warn_if_websocket_transport_missing()
    assert "-m pip install -r" in caplog.text
    assert readiness.sys.executable in caplog.text
    assert "/admin/assistant/ws" in caplog.text
    async with network_server(tmp_path, monkeypatch) as port:
        response, _, writer = await handshake(port)
        try:
            assert response.startswith(b"HTTP/1.1 404 "), response.decode()
        finally:
            await close_client(writer)


def test_readiness_is_quiet_when_uvicorn_transport_is_present(caplog):
    with caplog.at_level(logging.WARNING):
        assert readiness.warn_if_websocket_transport_missing()
    assert not caplog.records
