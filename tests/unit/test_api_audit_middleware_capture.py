"""The API audit middleware records error bodies and the matched route template.

Regression: `call_next` returns a streamed response, which has no `.body`, so
`error_code`, `error_message` and `response_body` were never captured; and
`route_pattern` was read from `scope["route"]` before routing had set it, so it was
always null.
"""

from __future__ import annotations

from unittest.mock import patch

from fastapi import FastAPI
from fastapi.responses import JSONResponse, PlainTextResponse
from fastapi.testclient import TestClient

from src.middleware.api_audit import APIAuditMiddleware


ERROR = {"status": "error", "error": {"code": "NF_4004", "category": "not_found", "message": "Widget not found"}}


def _client() -> TestClient:
    app = FastAPI()

    @app.get("/widgets/{widget_id}")
    async def get_widget(widget_id: str):
        if widget_id == "missing":
            return JSONResponse(status_code=404, content=ERROR)
        if widget_id == "huge":
            return JSONResponse(status_code=400, content={"error": {"code": "X", "message": "m" * 70_000}})
        return {"id": widget_id}

    @app.get("/text-error")
    async def text_error():
        return PlainTextResponse("teapot", status_code=418)

    app.add_middleware(APIAuditMiddleware)
    return TestClient(app)


def _capture():
    return (
        patch("src.middleware.api_audit.APIAuditLogger.log_request"),
        patch("src.middleware.api_audit.APIAuditLogger.log_response"),
    )


def test_json_error_body_is_captured_and_still_reaches_the_client():
    request_patch, response_patch = _capture()
    with request_patch, response_patch as log_response:
        response = _client().get("/widgets/missing")

    assert response.status_code == 404
    assert response.json() == ERROR
    kwargs = log_response.call_args.kwargs
    assert kwargs["error_code"] == "NF_4004"
    assert kwargs["error_message"] == "Widget not found"
    # Stored through the audit redaction, which masks any key named `code`.
    assert kwargs["response_body"]["error"]["message"] == "Widget not found"


def test_route_pattern_is_the_matched_template():
    request_patch, response_patch = _capture()
    with request_patch as log_request, response_patch:
        _client().get("/widgets/abc-123")

    assert log_request.call_args.kwargs["route_pattern"] == "/widgets/{widget_id}"
    assert log_request.call_args.kwargs["endpoint_path"] == "/widgets/abc-123"


def test_method_mismatch_still_names_the_template_and_unknown_paths_stay_null():
    request_patch, response_patch = _capture()
    client = _client()
    with request_patch as log_request, response_patch:
        client.post("/widgets/abc")
        assert log_request.call_args.kwargs["route_pattern"] == "/widgets/{widget_id}"
        client.get("/no/such/route")
        assert log_request.call_args.kwargs["route_pattern"] is None


def test_oversized_and_non_json_error_bodies_pass_through_uncaptured():
    request_patch, response_patch = _capture()
    client = _client()
    with request_patch, response_patch as log_response:
        huge = client.get("/widgets/huge")
        assert huge.status_code == 400 and len(huge.json()["error"]["message"]) == 70_000
        assert log_response.call_args.kwargs["response_body"] is None

        text = client.get("/text-error")
        assert text.status_code == 418 and text.text == "teapot"
        assert log_response.call_args.kwargs["response_body"] is None
