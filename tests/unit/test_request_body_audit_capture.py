"""Audit capture follows normal reads, stays small, and preserves request timing."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import FastAPI, Form, Request
from fastapi.testclient import TestClient
import pytest
from starlette.responses import StreamingResponse

from src.middleware.api_audit import APIAuditMiddleware
from src.middleware.auth_context import AuthContextMiddleware
from src.middleware.body_limit import MAX_AUDIT_CAPTURE_BYTES, request_body_state
from src.middleware.request_validation import RequestValidationMiddleware
from src.Util.api_audit_logger import APIAuditLogger


@pytest.fixture
def body_client():
    app = FastAPI()
    events = []
    states = []

    @app.post("/consume")
    async def consume(request: Request):
        raw = await request.body()
        events.append("body_processed")
        states.append(request_body_state(request.scope))
        return {"bytes": len(raw)}

    @app.post("/form")
    async def form(value: str = Form(...)):
        return {"value": value}

    @app.post("/export")
    async def export(request: Request):
        await request.json()

        async def chunks():
            yield b"first,"
            yield b"second"

        return StreamingResponse(chunks(), media_type="text/csv")

    async def webhook(request: Request):
        raw = await request.body()
        states.append(request_body_state(request.scope))
        return {"bytes": len(raw)}

    for path in ["/webhooks/email/resend", "/webhooks/patreon", "/webhooks/stripe/group"]:
        app.add_api_route(path, webhook, methods=["POST"])

    app.add_middleware(RequestValidationMiddleware)
    app.add_middleware(APIAuditMiddleware)
    app.add_middleware(AuthContextMiddleware)
    with patch.object(APIAuditLogger, "log_request", side_effect=lambda **kwargs: events.append("request_logged")) as start, \
         patch.object(APIAuditLogger, "log_response") as finish, \
         patch("src.middleware.request_validation.logger", new=AsyncMock()):
        with TestClient(app) as client:
            yield client, start, finish, events, states


def test_small_json_is_redacted_on_completion_without_delaying_audit_start(body_client):
    client, start, finish, events, states = body_client
    raw = json.dumps({"safe": "visible", "password": "do-not-log", "nested": {"access_token": "do-not-log-either"}}).encode()
    response = client.post("/consume", content=raw)
    assert response.status_code == 200
    assert events == ["request_logged", "body_processed"]
    assert start.call_count == finish.call_count == 1
    assert start.call_args.kwargs["request_body"] is None
    captured = finish.call_args.kwargs
    assert captured["request_body"]["safe"] == "visible"
    assert "do-not-log" not in json.dumps(captured["request_body"])
    assert captured["request_size_bytes"] == len(raw)
    assert captured["request_metadata"] == {"body_complete": True, "body_capture": "complete"}
    assert len(states[0].capture) <= MAX_AUDIT_CAPTURE_BYTES


@pytest.mark.parametrize("offset", [-1, 0, 1])
def test_audit_boundary_and_omission_marker(body_client, offset):
    client, _, finish, _, states = body_client
    empty_size = len(json.dumps({"safe": ""}).encode())
    raw = json.dumps({"safe": "x" * (MAX_AUDIT_CAPTURE_BYTES + offset - empty_size)}).encode()
    assert client.post("/consume", content=raw).status_code == 200
    captured = finish.call_args.kwargs
    if offset > 0:
        assert captured["request_metadata"]["body_capture"] == "audit_limit"
        assert captured["request_body"] == {"_note": "Request body omitted: exceeds 64 KiB audit limit"}
        assert states[0].capture == b""
    else:
        assert captured["request_body"]["safe"] == json.loads(raw)["safe"]
        assert captured["request_metadata"]["body_capture"] == "complete"
    assert captured["request_size_bytes"] == len(raw)
    assert len(states[0].capture) <= MAX_AUDIT_CAPTURE_BYTES


@pytest.mark.parametrize("path", ["/webhooks/patreon", "/webhooks/stripe/group", "/webhooks/email/resend"])
def test_webhook_bytes_remain_exact_and_are_never_captured(body_client, path):
    client, start, finish, _, states = body_client
    raw = b'{ "secret": "raw-provider-material" }'
    response = client.post(path, content=raw)
    assert response.json()["bytes"] == len(raw)
    assert states[0].capture == b"" and not states[0].capture_enabled
    if path.startswith("/webhooks/email"):
        start.assert_not_called()
        finish.assert_not_called()
    else:
        captured = finish.call_args.kwargs
        assert captured["request_body"] == {"_note": "Request body excluded from audit"}
        assert captured["request_size_bytes"] == len(raw)
        assert "raw-provider-material" not in json.dumps(captured)


@pytest.mark.parametrize("multipart", [False, True])
def test_form_parsing_and_legacy_non_json_note(body_client, multipart):
    client, _, finish, _, _ = body_client
    response = client.post("/form", files={"value": (None, "unchanged")}) if multipart else client.post("/form", data={"value": "unchanged"})
    assert response.json() == {"value": "unchanged"}
    captured = finish.call_args.kwargs
    assert captured["request_body"] == {"_note": "Non-JSON body"}
    assert captured["request_metadata"] == {"body_complete": True, "body_capture": "non_json"}


def test_streamed_export_is_not_hung_by_audit_capture(body_client):
    client, _, finish, _, _ = body_client
    response = client.post("/export", json={"source": "api_audit"})
    assert response.status_code == 200 and response.content == b"first,second"
    assert finish.call_args.kwargs["request_body"] == {"source": "api_audit"}


def test_utf8_input_whose_redacted_serialization_expands_is_omitted(body_client):
    client, _, finish, _, _ = body_client
    raw = json.dumps({"safe": "\U0001f600" * 6000}, ensure_ascii=False).encode("utf-8")
    assert len(raw) < MAX_AUDIT_CAPTURE_BYTES
    assert client.post("/consume", content=raw).status_code == 200
    assert finish.call_args.kwargs["request_metadata"]["body_capture"] == "audit_limit"
    assert finish.call_args.kwargs["request_body"] == {"_note": "Request body omitted: exceeds 64 KiB audit limit"}


def test_unknown_path_is_not_buffered_for_audit(body_client):
    client, start, finish, _, _ = body_client
    assert client.post("/missing", content=b"not-read").status_code == 404
    assert start.call_args.kwargs["request_body"] is None
    assert finish.call_args.kwargs["request_metadata"]["body_capture"] == "incomplete"
    assert finish.call_args.kwargs["request_size_bytes"] == 0


def _connection():
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.__exit__.return_value = False
    return conn


def _finish_kwargs():
    return dict(audit_id="audit-existing", response_status=200, response_body=None,
                response_headers={}, response_size_bytes=0, error_code=None, error_message=None,
                target_resource_type=None, target_resource_id=None, tags=[], security_event=False)


def test_capture_update_preserves_timestamp_and_shares_response_transaction():
    conn = _connection()
    with patch("src.Util.api_audit_logger.get_connection", return_value=conn):
        assert APIAuditLogger.log_response(
            **_finish_kwargs(), request_body={"password": "must-be-redacted", "safe": "kept"},
            request_size_bytes=100, request_metadata={"body_complete": True},
        )
    cursor = conn.cursor.return_value
    query, args = cursor.execute.call_args.args
    assert "request_timestamp" not in query and "JSON_MERGE_PATCH" in query
    assert "%s" in query and args[-1] == "audit-existing" and args[1] == 100
    assert "must-be-redacted" not in args[0] and json.loads(args[0])["safe"] == "kept"
    assert cursor.method_calls[0][0] == "execute"
    assert cursor.method_calls[1][0] == "callproc"
    assert cursor.callproc.call_args.args[0] == "sp_update_api_response"
    conn.commit.assert_called_once()


def test_legacy_response_logger_does_not_replace_request_capture():
    conn = _connection()
    with patch("src.Util.api_audit_logger.get_connection", return_value=conn):
        assert APIAuditLogger.log_response(**_finish_kwargs())
    conn.cursor.return_value.execute.assert_not_called()
    conn.commit.assert_called_once()
