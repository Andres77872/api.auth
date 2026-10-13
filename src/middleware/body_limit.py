"""Bound received HTTP bytes before body readers, with optional bounded audit capture."""

from dataclasses import dataclass, field
import json
import logging
import os
import time
from typing import Sequence

from starlette.datastructures import Headers
from starlette.exceptions import HTTPException
from starlette.responses import JSONResponse, Response
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from src.Util.auth_constants import DEFAULT_ALLOWED_ORIGINS
from src.Util.error_handler import ErrorCode, ValidationError, build_error_response

MAX_REQUEST_BODY_BYTES = 8 * 1024 * 1024
MAX_AUDIT_CAPTURE_BYTES = 64 * 1024
_STATE_KEY = "_request_body_state"
logger = logging.getLogger(__name__)


@dataclass(slots=True)
class RequestBodyState:
    received_bytes: int = 0
    complete: bool = False
    exceeded: bool = False
    capture_enabled: bool = False
    capture_truncated: bool = False
    capture: bytearray = field(default_factory=bytearray)

    def observe(self, message: Message) -> None:
        if message["type"] != "http.request":
            return
        chunk = message.get("body", b"")
        self.received_bytes += len(chunk)
        self.complete = not message.get("more_body", False)
        if self.capture_enabled and not self.capture_truncated:
            if self.received_bytes > MAX_AUDIT_CAPTURE_BYTES:
                self.capture_truncated = True
                self.capture.clear()
            else:
                self.capture.extend(chunk)


def request_body_state(scope: Scope) -> RequestBodyState | None:
    return scope.get("state", {}).get(_STATE_KEY)


def configured_origins() -> list[str]:
    configured = os.environ.get("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
    return [origin.strip() for origin in configured.split(",") if origin.strip()]


def apply_reject_cors_headers(scope: Scope, response: Response, allowed_origins: Sequence[str]) -> None:
    origin = Headers(scope=scope).get("origin")
    if origin and origin in allowed_origins:
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
        response.headers.append("Vary", "Origin")


def payload_too_large_response(scope: Scope, allowed_origins: Sequence[str] | None = None) -> JSONResponse:
    response = JSONResponse(
        status_code=413,
        content=build_error_response(ValidationError("Request payload is too large", ErrorCode.INVALID_LENGTH)),
    )
    apply_reject_cors_headers(scope, response, configured_origins() if allowed_origins is None else allowed_origins)
    if scope.get("http_version") in {"1.0", "1.1"}:
        response.headers["Connection"] = "close"
    return response


class RequestBodyTooLarge(HTTPException):
    def __init__(self) -> None:
        super().__init__(status_code=413, detail="Request payload is too large")


class RequestBodyLimitMiddleware:
    """Meter receive without pre-reading or retaining the complete request body.

    Overflow is sticky: downstream exception handlers cannot change its status.
    A response already started cannot be replaced; the exception then aborts the
    connection instead. Cancellation and unrelated failures always propagate.
    """

    def __init__(self, app: ASGIApp, *, allowed_origins: Sequence[str] | None = None) -> None:
        self.app = app
        self.allowed_origins = configured_origins() if allowed_origins is None else tuple(allowed_origins)

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        state = RequestBodyState()
        scope.setdefault("state", {})[_STATE_KEY] = state
        started_at = time.monotonic()
        response_started = False
        rejected = False

        # This is only an early-rejection optimization. Invalid framing belongs
        # to the HTTP server; missing/malformed lengths never disable metering.
        lengths = Headers(scope=scope).getlist("content-length")
        declared_length = None
        for value in lengths:
            if value.isascii() and value.isdecimal():
                significant = value.lstrip("0") or "0"
                # Saturate enormous lengths instead of converting unbounded
                # header integers; they still receive an immediate rejection.
                length = int(significant) if len(significant) < 20 else MAX_REQUEST_BODY_BYTES + 1
                declared_length = max(declared_length or 0, length)

        def log_rejection(reason: str) -> None:
            fields = {
                "request_method": scope["method"],
                "request_path": scope["path"],
                "received_bytes": state.received_bytes,
                "body_limit_bytes": MAX_REQUEST_BODY_BYTES,
                "declared_content_length": declared_length,
                "rejection_reason": reason,
            }
            # Retain structured LogRecord fields and include them in the default
            # text output used by the container's ordinary logging formatter.
            logger.warning("Rejected oversized HTTP request %s", json.dumps(fields), extra=fields)

        async def reject() -> None:
            nonlocal response_started, rejected
            response_started = rejected = True
            response = payload_too_large_response(scope, self.allowed_origins)
            response.headers["X-Process-Time"] = str(time.monotonic() - started_at)
            await response(scope, receive, send)

        if declared_length is not None and declared_length > MAX_REQUEST_BODY_BYTES:
            state.exceeded = True
            log_rejection("content_length")
            await reject()
            return

        async def limited_receive() -> Message:
            if state.exceeded:
                raise RequestBodyTooLarge()
            message = await receive()
            state.observe(message)
            if state.received_bytes > MAX_REQUEST_BODY_BYTES:
                state.exceeded = True
                state.capture.clear()
                log_rejection("received_bytes")
                # Do not retain an offending frame in an exception traceback.
                del message
                raise RequestBodyTooLarge()
            return message

        async def limited_send(message: Message) -> None:
            nonlocal response_started
            if state.exceeded:
                if not response_started:
                    await reject()
                if rejected:
                    return
                raise RequestBodyTooLarge()
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, limited_receive, limited_send)
        except Exception:
            if not state.exceeded or (response_started and not rejected):
                raise
            if not rejected:
                await reject()
        else:
            if state.exceeded and not response_started:
                await reject()
