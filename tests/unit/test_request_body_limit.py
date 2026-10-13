"""Actual-byte limits, early rejection, exception handling, and ASGI lifecycle."""

import asyncio
import json

from fastapi import FastAPI, Request
import pytest
from starlette.responses import JSONResponse

from src.middleware.body_limit import (
    MAX_REQUEST_BODY_BYTES,
    RequestBodyLimitMiddleware,
    RequestBodyTooLarge,
    request_body_state,
)


def scope_for(method="POST", path="/consume", headers=()):
    return {
        "type": "http", "asgi": {"version": "3.0", "spec_version": "2.4"},
        "http_version": "1.1", "method": method, "scheme": "http", "path": path,
        "raw_path": path.encode(), "query_string": b"", "headers": list(headers),
        "client": ("127.0.0.1", 1000), "server": ("test", 80), "root_path": "",
    }


async def drive(app, total, *, method="POST", path="/consume", headers=(), chunk_size=64 * 1024):
    scope = scope_for(method, path, headers)
    consumed = 0
    messages = []
    complete = asyncio.Event()

    async def receive():
        nonlocal consumed
        if consumed < total:
            size = min(chunk_size, total - consumed)
            consumed += size
            return {"type": "http.request", "body": b"x" * size, "more_body": consumed < total}
        if total == 0 and not request_body_state(scope).complete:
            return {"type": "http.request", "body": b"", "more_body": False}
        await complete.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.body" and not message.get("more_body", False):
            complete.set()

    await asyncio.wait_for(app(scope, receive, send), 5)
    starts = [message for message in messages if message["type"] == "http.response.start"]
    assert len(starts) == 1
    body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
    return starts[0]["status"], dict(starts[0]["headers"]), body, consumed, request_body_state(scope)


@pytest.mark.large_payload
@pytest.mark.parametrize("method", ["POST", "PUT", "PATCH", "DELETE", "GET"])
@pytest.mark.parametrize("offset", [-1, 0, 1])
@pytest.mark.parametrize("declared", [False, True])
async def test_actual_eight_mib_boundary_for_every_method(method, offset, declared):
    app = FastAPI()
    completed = []

    @app.api_route("/consume", methods=[method])
    async def consume(request: Request):
        body = await request.body()
        completed.append(len(body))
        return {"bytes": len(body)}

    size = MAX_REQUEST_BODY_BYTES + offset
    headers = [(b"content-length", str(size).encode())] if declared else []
    status, response_headers, body, consumed, state = await drive(
        RequestBodyLimitMiddleware(app), size, method=method, headers=headers,
    )
    if offset > 0:
        assert status == 413 and completed == []
        error = json.loads(body)["error"]
        assert {key: error[key] for key in ("code", "category", "message")} == {
            "code": "VAL_3010", "category": "validation", "message": "Request payload is too large",
        }
        assert response_headers[b"connection"] == b"close"
        assert consumed == (0 if declared else size)
        assert state.exceeded
    else:
        assert status == 200 and completed == [size] and consumed == size
        assert state.complete and not state.exceeded


@pytest.mark.large_payload
@pytest.mark.parametrize("declared_length", [b"1", b"nonsense", b"-1"])
async def test_inaccurate_or_invalid_length_cannot_disable_actual_byte_meter(declared_length):
    async def read(scope, receive, send):
        while (await receive()).get("more_body", False):
            pass
        raise AssertionError("Oversized body must not reach completed processing")

    total = 2 * MAX_REQUEST_BODY_BYTES
    status, _, _, consumed, state = await drive(
        RequestBodyLimitMiddleware(read), total, headers=[(b"content-length", declared_length)],
    )
    assert status == 413
    assert consumed == MAX_REQUEST_BODY_BYTES + 64 * 1024 < total
    assert state.exceeded and len(state.capture) == 0


@pytest.mark.parametrize("length", [b"9999999999999999999999999", b"0000000000008388609"])
async def test_enormous_declared_length_rejects_without_receive_or_downstream(length):
    async def forbidden(*args):
        raise AssertionError("Must reject before receiving or calling the application")

    messages = []

    async def send(message):
        messages.append(message)

    await RequestBodyLimitMiddleware(forbidden)(scope_for(headers=[(b"content-length", length)]), forbidden, send)
    assert messages[0]["status"] == 413


@pytest.mark.large_payload
@pytest.mark.parametrize("inner_status", [200, 400, 500])
async def test_downstream_exception_handler_cannot_replace_413(inner_status):
    app = FastAPI()

    @app.exception_handler(RequestBodyTooLarge)
    async def normalize(request, exc):
        return JSONResponse({"converted": True}, status_code=inner_status)

    @app.post("/consume")
    async def consume(request: Request):
        await request.body()
        raise AssertionError("Oversized body must abort processing")

    status, _, body, _, _ = await drive(RequestBodyLimitMiddleware(app), MAX_REQUEST_BODY_BYTES + 1)
    assert status == 413 and json.loads(body)["error"]["code"] == "VAL_3010"


async def test_early_response_does_not_read_lengthless_body():
    app = FastAPI()
    status, _, _, consumed, state = await drive(RequestBodyLimitMiddleware(app), 2 * MAX_REQUEST_BODY_BYTES, path="/missing")
    assert status == 404 and consumed == 0 and not state.complete


@pytest.mark.parametrize("origin, allowed", [("https://auth-ui.arz.ai", True), ("http://localhost:5173", True), ("https://untrusted.test", False)])
async def test_early_413_is_readable_only_by_allowed_origins(origin, allowed):
    app = FastAPI()
    status, headers, _, consumed, _ = await drive(
        RequestBodyLimitMiddleware(app, allowed_origins=["https://auth-ui.arz.ai", "http://localhost:5173"]),
        MAX_REQUEST_BODY_BYTES + 1,
        headers=[(b"content-length", str(MAX_REQUEST_BODY_BYTES + 1).encode()), (b"origin", origin.encode())],
    )
    assert status == 413 and consumed == 0
    if allowed:
        assert headers[b"access-control-allow-origin"] == origin.encode()
        assert headers[b"access-control-allow-credentials"] == b"true"
        assert headers[b"vary"] == b"Origin"
    else:
        assert b"access-control-allow-origin" not in headers


@pytest.mark.parametrize("kind", ["websocket", "lifespan"])
async def test_non_http_scope_is_passed_through_untouched(kind):
    scope = {"type": kind}
    calls = []

    async def endpoint(scope, receive, send):
        calls.append(scope.copy())

    await RequestBodyLimitMiddleware(endpoint)(scope, None, None)
    assert calls == [{"type": kind}] and "state" not in scope


async def test_cancellation_and_unrelated_exceptions_propagate():
    for error in [asyncio.CancelledError(), RuntimeError("unrelated")]:
        async def endpoint(scope, receive, send):
            raise error

        with pytest.raises(type(error)):
            await drive(RequestBodyLimitMiddleware(endpoint), 0)


async def test_disconnect_does_not_become_payload_error():
    async def endpoint(scope, receive, send):
        assert await receive() == {"type": "http.disconnect"}

    async def receive():
        return {"type": "http.disconnect"}

    async def send(message):
        raise AssertionError("Disconnect must not invent a response")

    await RequestBodyLimitMiddleware(endpoint)(scope_for(), receive, send)


@pytest.mark.large_payload
async def test_overflow_after_response_start_does_not_send_another_status():
    messages = []

    async def endpoint(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await receive()

    async def receive():
        return {"type": "http.request", "body": b"x" * (MAX_REQUEST_BODY_BYTES + 1), "more_body": False}

    async def send(message):
        messages.append(message)

    with pytest.raises(RequestBodyTooLarge):
        await RequestBodyLimitMiddleware(endpoint)(scope_for(), receive, send)
    assert messages == [{"type": "http.response.start", "status": 200, "headers": []}]


async def test_rejection_log_has_counts_without_payload(caplog):
    status, _, _, _, _ = await drive(
        RequestBodyLimitMiddleware(FastAPI()), MAX_REQUEST_BODY_BYTES + 1,
        headers=[(b"content-length", str(MAX_REQUEST_BODY_BYTES + 1).encode())],
    )
    assert status == 413
    record = next(record for record in caplog.records if record.message.startswith("Rejected oversized HTTP request"))
    assert record.request_method == "POST" and record.request_path == "/consume"
    assert record.received_bytes == 0 and record.body_limit_bytes == MAX_REQUEST_BODY_BYTES
    assert record.rejection_reason == "content_length" and record.exc_info is None
    assert json.loads(record.message.split("Rejected oversized HTTP request ", 1)[1])["received_bytes"] == 0
