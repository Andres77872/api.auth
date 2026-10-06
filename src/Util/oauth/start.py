"""Consume a server-minted OAuth init token and start an authorization round trip."""

from __future__ import annotations

from typing import Any, Callable

from fastapi import Request, Response

from src.Util.auth_constants import OAUTH_PURPOSE_LOGIN
from src.Util.error_handler import ErrorCode
from src.Util.oauth.connections import (
    OAuthConnectionUnavailable,
    ResolvedConnection,
    UNAVAILABLE_DISABLED,
)
from src.Util.oauth.init_tokens import OAuthInitTokenInvalid, OAuthInitTokenReplayed, OAuthInitTokenStore
from src.Util.oauth.pipeline import (
    EVENT_INIT_REJECTED,
    FORBIDDEN_BROWSER_STRICT_FIELDS,
    AuthorizationStart,
    OAuthPipeline,
    new_correlation_id,
    oauth_error_response,
)
from src.Util.oauth_rate_limit import OAuthRateLimitExceeded
from src.Util.oauth_state import OAuthStateStoreUnavailable, fingerprint_oauth_value


_BINDING_INVALID_MESSAGE = "OAuth init binding could not be validated."


async def read_json_object(request: Request) -> dict[str, Any] | None:
    try:
        body = await request.json()
    except Exception:
        return {}
    return body if isinstance(body, dict) else None


def _unavailable_response(exc: OAuthConnectionUnavailable, correlation_id: str) -> Response:
    if exc.kind == UNAVAILABLE_DISABLED:
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_DISABLED, status_code=403, correlation_id=correlation_id)
    return oauth_error_response(ErrorCode.OAUTH_PROVIDER_NOT_CONFIGURED, correlation_id=correlation_id)


def _pick_redirect_uri(resolved: ResolvedConnection, requested: str | None) -> str | None:
    if requested:
        return requested if resolved.binding.is_redirect_uri_allowed(requested) else None
    sole = resolved.binding.sole_redirect_uri()
    if sole:
        return sole
    return None


async def start_from_init_token(
    request: Request,
    *,
    pipeline: OAuthPipeline,
    init_store: Callable[[], OAuthInitTokenStore],
) -> Response:
    deps = pipeline.deps
    correlation_id = new_correlation_id("start")
    body = await read_json_object(request)
    if body is None or FORBIDDEN_BROWSER_STRICT_FIELDS.intersection(body):
        return oauth_error_response(ErrorCode.OAUTH_INIT_INVALID, status_code=400, message=_BINDING_INVALID_MESSAGE)
    token = str(body.get("init_token") or "").strip()
    if not token or len(token) > 512:
        return oauth_error_response(ErrorCode.OAUTH_INIT_INVALID, status_code=400)
    fingerprint = fingerprint_oauth_value(token)

    try:
        await pipeline._limit("check_start", request=request, init_token_fingerprint=fingerprint)
    except OAuthRateLimitExceeded as exc:
        return oauth_error_response(ErrorCode.OAUTH_RATE_LIMITED, status_code=429, retry_after=exc.retry_after, correlation_id=correlation_id)

    try:
        record = init_store().consume(token)
    except OAuthInitTokenReplayed:
        await deps.emit(EVENT_INIT_REJECTED, details={"reason": "init_token_replayed", "init_token_fingerprint": fingerprint}, request=request)
        return oauth_error_response(ErrorCode.OAUTH_INIT_INVALID, status_code=401, correlation_id=correlation_id)
    except (OAuthInitTokenInvalid, OAuthStateStoreUnavailable):
        await deps.emit(EVENT_INIT_REJECTED, details={"reason": "init_token_invalid", "init_token_fingerprint": fingerprint}, request=request)
        return oauth_error_response(ErrorCode.OAUTH_INIT_INVALID, status_code=401, correlation_id=correlation_id)

    try:
        resolved = deps.connection_source().get_by_ids(connection_id=record.connection_id, binding_id=record.binding_id)
    except OAuthConnectionUnavailable as exc:
        return _unavailable_response(exc, correlation_id)

    redirect_uri = _pick_redirect_uri(resolved, str(body.get("redirect_uri") or "").strip() or None)
    if not redirect_uri or not resolved.binding.is_return_origin_allowed(record.return_origin):
        return oauth_error_response(ErrorCode.OAUTH_REDIRECT_URI_NOT_ALLOWED, status_code=400, correlation_id=correlation_id)

    # ``remember_me`` is a user preference, not security scope, so the browser may still set
    # it at start. Project, connection, origin and provisioning group
    # project, connection, origin, provisioning group -- stays fixed by the init record.
    remember_me = bool(body["remember_me"]) if isinstance(body.get("remember_me"), bool) else record.remember_me
    start = AuthorizationStart(
        resolved=resolved,
        purpose=record.purpose or OAUTH_PURPOSE_LOGIN,
        project_hash=record.project_hash,
        redirect_uri=redirect_uri,
        return_origin=record.return_origin,
        remember_me=remember_me,
        init_fingerprint=record.fingerprint,
    )
    return await _begin(request, pipeline, start, fingerprint=fingerprint, correlation_id=correlation_id)


async def _begin(request: Request, pipeline: OAuthPipeline, start: AuthorizationStart, *, fingerprint: str, correlation_id: str) -> Response:
    try:
        return await pipeline.begin_authorization(request, start)
    except Exception as exc:
        reason = "state_store_unavailable" if isinstance(exc, OAuthStateStoreUnavailable) else "authorization_start_failed"
        await pipeline.deps.emit(
            EVENT_INIT_REJECTED,
            resolved=start.resolved,
            details={"reason": reason, "init_token_fingerprint": fingerprint},
            request=request,
        )
        code = ErrorCode.OAUTH_STATE_INVALID if isinstance(exc, OAuthStateStoreUnavailable) else ErrorCode.OAUTH_PROVIDER_NOT_CONFIGURED
        return oauth_error_response(code, correlation_id=correlation_id)


__all__ = ["read_json_object", "start_from_init_token"]
