"""Ordinary HTTP framing and connection lifecycle through a real Uvicorn server."""

import asyncio
from contextlib import asynccontextmanager
import json
import socket
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
import pytest
import uvicorn

from src.middleware.api_audit import APIAuditMiddleware
from src.middleware.auth_context import AuthContextMiddleware
from src.middleware.body_limit import MAX_REQUEST_BODY_BYTES, RequestBodyLimitMiddleware
from src.middleware.request_validation import RequestValidationMiddleware
from src.Util.api_audit_logger import APIAuditLogger

pytestmark = pytest.mark.integration


@asynccontextmanager
async def network_server(monkeypatch):
    monkeypatch.setattr(APIAuditLogger, "log_request", MagicMock())
    monkeypatch.setattr(APIAuditLogger, "log_response", MagicMock())
    monkeypatch.setattr("src.middleware.request_validation.logger", AsyncMock())
    app = FastAPI()
    completed = []

    @app.post("/consume")
    async def consume(request: Request):
        body = await request.body()
        completed.append(len(body))
        return {"bytes": len(body)}

    origins = ["https://auth-ui.arz.ai", "http://localhost:5173"]
    app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True)
    app.add_middleware(RequestValidationMiddleware)
    app.add_middleware(APIAuditMiddleware)
    app.add_middleware(AuthContextMiddleware)
    app.add_middleware(RequestBodyLimitMiddleware, allowed_origins=origins)
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen(8)
    listener.setblocking(False)
    port = listener.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(
        app, http="h11", loop="asyncio", lifespan="off", log_config=None,
        access_log=False, timeout_graceful_shutdown=2,
    ))
    task = asyncio.create_task(server.serve(sockets=[listener]))
    try:
        async with asyncio.timeout(5):
            while not server.started:
                if task.done():
                    await task
                    raise AssertionError("Uvicorn stopped before opening the socket")
                await asyncio.sleep(0.01)
        yield port, completed
    finally:
        server.should_exit = True
        try:
            await asyncio.wait_for(task, 5)
        finally:
            listener.close()


async def read_response(reader):
    headers = await asyncio.wait_for(reader.readuntil(b"\r\n\r\n"), 5)
    lines = headers.split(b"\r\n")
    status = int(lines[0].split()[1])
    fields = dict(line.lower().split(b": ", 1) for line in lines[1:] if line)
    body = await asyncio.wait_for(reader.readexactly(int(fields[b"content-length"])), 5)
    return status, fields, json.loads(body)


async def send_request(reader, writer, size, *, chunked):
    framing = "Transfer-Encoding: chunked" if chunked else f"Content-Length: {size}"
    writer.write((f"POST /consume HTTP/1.1\r\nHost: localhost\r\nUser-Agent: bounded-network-test\r\n"
                  f"Content-Type: application/octet-stream\r\n{framing}\r\n\r\n").encode())
    sent = 0
    while sent < size:
        chunk_size = min(64 * 1024, size - sent)
        body = b"x" * chunk_size
        writer.write(f"{chunk_size:x}\r\n".encode() + body + b"\r\n" if chunked else body)
        sent += chunk_size
        await writer.drain()
        await asyncio.sleep(0)
    if chunked:
        writer.write(b"0\r\n\r\n")
        await writer.drain()
    return await read_response(reader)


async def close(writer):
    writer.close()
    try:
        await writer.wait_closed()
    except ConnectionError:
        pass


@pytest.mark.large_payload
async def test_real_chunked_overflow_and_fresh_connection_after_413(monkeypatch):
    async with network_server(monkeypatch) as (port, completed):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            status, headers, body = await send_request(reader, writer, MAX_REQUEST_BODY_BYTES + 1, chunked=True)
            assert status == 413 and body["error"]["code"] == "VAL_3010"
            assert headers[b"connection"] == b"close" and completed == []
            assert await asyncio.wait_for(reader.read(), 5) == b""
        finally:
            await close(writer)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            assert (await send_request(reader, writer, 100, chunked=False))[0] == 200
            assert completed == [100]
        finally:
            await close(writer)


async def test_declared_oversize_rejected_without_upload_and_has_browser_cors(monkeypatch):
    async with network_server(monkeypatch) as (port, completed):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            writer.write((f"POST /consume HTTP/1.1\r\nHost: localhost\r\nUser-Agent: bounded-network-test\r\n"
                          f"Content-Length: {MAX_REQUEST_BODY_BYTES + 1}\r\n"
                          "Origin: https://auth-ui.arz.ai\r\nExpect: 100-continue\r\n\r\n").encode())
            await writer.drain()
            status, headers, body = await read_response(reader)
            assert status == 413 and body["error"]["code"] == "VAL_3010"
            assert headers[b"access-control-allow-origin"] == b"https://auth-ui.arz.ai"
            assert headers[b"access-control-allow-credentials"] == b"true"
            assert headers[b"vary"] == b"origin" and completed == []
            assert await asyncio.wait_for(reader.read(), 5) == b""
        finally:
            await close(writer)


async def test_accepted_requests_reuse_connection_and_reset_body_state(monkeypatch):
    async with network_server(monkeypatch) as (port, completed):
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            for size, chunked in [(128 * 1024, True), (120, False)]:
                status, _, body = await send_request(reader, writer, size, chunked=chunked)
                assert status == 200 and body["bytes"] == size
            assert completed == [128 * 1024, 120]
        finally:
            await close(writer)


@pytest.mark.large_payload
async def test_concurrent_bounded_requests_do_not_share_counters(monkeypatch):
    async with network_server(monkeypatch) as (port, completed):
        async def one(size):
            reader, writer = await asyncio.open_connection("127.0.0.1", port)
            try:
                return (await send_request(reader, writer, size, chunked=True))[0]
            finally:
                await close(writer)

        statuses = await asyncio.wait_for(asyncio.gather(
            one(100), one(MAX_REQUEST_BODY_BYTES + 1), one(200), one(MAX_REQUEST_BODY_BYTES + 1),
        ), 10)
        assert statuses == [200, 413, 200, 413] and sorted(completed) == [100, 200]


async def test_disconnected_upload_does_not_stall_the_server(monkeypatch):
    async with network_server(monkeypatch) as (port, completed):
        _, writer = await asyncio.open_connection("127.0.0.1", port)
        writer.write(b"POST /consume HTTP/1.1\r\nHost: localhost\r\nUser-Agent: bounded-network-test\r\nContent-Length: 10000\r\n\r\npartial")
        await writer.drain()
        await close(writer)
        reader, writer = await asyncio.open_connection("127.0.0.1", port)
        try:
            assert (await send_request(reader, writer, 100, chunked=True))[0] == 200
            assert completed == [100]
        finally:
            await close(writer)
