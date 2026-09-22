"""Entry points that turn a browser/BFF start request into an authorization round trip.

Two handshakes:

* ``start_from_init_token`` -- the inverted handshake. The token was minted by
  ``POST /auth/oauth/init`` for an authenticated project credential, so project,
  connection and provisioning group are already fixed server-side.
* ``start_from_legacy_provider_init`` -- the compatibility bridge in which
  ``api.auth`` redeems an opaque token at the companion backend. For database
  bindings the redeemed scope MUST equal the binding's own project and group; only
  the environment-sourced wildcard binding still trusts what the backend asserts.
"""

from __future__ import annotations

import hmac
from typing import Any, Awaitable, Callable, Mapping

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
from src.Util.oauth_state import OAuthStateStoreUnavailable
from src.Util.provider_init import (
    LegacyRedeemRuntimeConfig,
    ProviderInitBinding,
    ProviderInitRedeemError,
    fingerprint_provider_init_token,
    validate_provider_init_binding,
)


_BINDING_INVALID_MESSAGE = "Provider-init binding could not be validated."


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


def _pick_redirect_uri(resolved: ResolvedConnection, requested: str | None, *, allow_first_default: bool) -> str | None:
    if requested:
        return requested if resolved.binding.is_redirect_uri_allowed(requested) else None
    sole = resolved.binding.sole_redirect_uri()
    if sole:
        return sole
    # Historical environment behaviour only: default to the first configured URI.
    if allow_first_default and resolved.binding.redirect_uris:
        return resolved.binding.redirect_uris[0]
    return None


def _coerce_binding(
    value: Any,
    *,
    runtime_config: Any,
    expected_provider: str,
    return_origin: str | None,
    token_fingerprint: str,
) -> ProviderInitBinding:
    """Validate whatever the (possibly test-injected) redeemer returned."""

    if isinstance(value, ProviderInitBinding):
        return value
    if isinstance(value, Mapping):
        payload: Mapping[str, Any] = value
    else:
        payload = {
            name: getattr(value, name, None)
            for name in (
                "provider", "purpose", "project_hash", "user_group_hash", "return_origin", "expires_at",
                "expires_in", "issuer", "audience", "provider_init_fingerprint", "scope_fingerprint",
            )
        }
        payload = {"active": True, **{key: item for key, item in payload.items() if item is not None}}
    return validate_provider_init_binding(
        payload,
        config=runtime_config,
        expected_provider=expected_provider,
        requested_return_origin=return_origin,
        token_fingerprint=token_fingerprint,
    )


async def start_from_legacy_provider_init(
    request: Request,
    *,
    pipeline: OAuthPipeline,
    connection_key: str,
    redeem: Callable[..., Awaitable[Any]],
) -> Response:
    deps = pipeline.deps
    correlation_id = new_correlation_id("start")
    body = await read_json_object(request)
    if body is None:
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=400)
    if FORBIDDEN_BROWSER_STRICT_FIELDS.intersection(body):
        await deps.emit(EVENT_INIT_REJECTED, details={"reason": "invalid_start_request", "correlation_id": correlation_id}, request=request)
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=400, message=_BINDING_INVALID_MESSAGE)
    token = str(body.get("provider_init_token") or "").strip()
    if not token or len(token) > 4096:
        await deps.emit(EVENT_INIT_REJECTED, details={"reason": "invalid_start_request", "correlation_id": correlation_id}, request=request)
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=400)
    requested_redirect = str(body.get("redirect_uri") or "").strip() or None
    requested_origin = str(body.get("return_origin") or "").strip() or None

    source = deps.connection_source()
    try:
        candidates = source.find_legacy_bindings(connection_key=connection_key)
    except OAuthConnectionUnavailable as exc:
        return _unavailable_response(exc, correlation_id)

    matches: list[tuple[ResolvedConnection, str, str]] = []
    for candidate in candidates:
        legacy_defaults = candidate.binding.trusts_caller_scope
        redirect_uri = _pick_redirect_uri(candidate, requested_redirect, allow_first_default=legacy_defaults)
        return_origin = requested_origin or (candidate.binding.return_origins[0] if legacy_defaults and candidate.binding.return_origins else None)
        if redirect_uri and candidate.binding.is_return_origin_allowed(return_origin):
            matches.append((candidate, redirect_uri, str(return_origin)))
    # Exactly one binding must own this redirect URI + origin pair: never a union across projects.
    if len(matches) != 1:
        return oauth_error_response(ErrorCode.OAUTH_REDIRECT_URI_NOT_ALLOWED, status_code=400, correlation_id=correlation_id)
    resolved, redirect_uri, return_origin = matches[0]

    fingerprint = fingerprint_provider_init_token(token)
    scope = pipeline._scope(resolved)
    try:
        await pipeline._limit("check_start", request=request, scope=scope, provider_init_fingerprint=fingerprint)
        await pipeline._limit("check_provider_init_redeem", request=request, scope=scope, provider_init_fingerprint=fingerprint)
    except OAuthRateLimitExceeded as exc:
        return oauth_error_response(ErrorCode.OAUTH_RATE_LIMITED, status_code=429, retry_after=exc.retry_after, correlation_id=correlation_id)

    redeem_config = source.load_legacy_redeem(resolved)
    runtime_config = LegacyRedeemRuntimeConfig(
        provider_init_redeem_url=redeem_config.url if redeem_config else None,
        provider_init_redeem_token=redeem_config.token if redeem_config else None,
        provider_init_return_origins=tuple(
            (redeem_config.return_origins if redeem_config and redeem_config.return_origins else resolved.binding.return_origins)
        ),
    )
    try:
        redeemed = await redeem(token, config=runtime_config, return_origin=return_origin)
        binding = _coerce_binding(
            redeemed,
            runtime_config=runtime_config,
            expected_provider=resolved.config.provider_type,
            return_origin=return_origin,
            token_fingerprint=fingerprint,
        )
        _assert_redeemed_scope(resolved, binding)
    except ProviderInitRedeemError as exc:
        await deps.emit(
            EVENT_INIT_REJECTED,
            resolved=resolved,
            details={"reason": exc.reason, "provider_init_fingerprint": fingerprint, "correlation_id": correlation_id},
            request=request,
        )
        return oauth_error_response(
            ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=401, message=_BINDING_INVALID_MESSAGE, correlation_id=correlation_id
        )
    except Exception:
        await deps.emit(
            EVENT_INIT_REJECTED,
            resolved=resolved,
            details={"reason": "provider_init_redeem_failed", "provider_init_fingerprint": fingerprint},
            request=request,
        )
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=401, correlation_id=correlation_id)

    start = AuthorizationStart(
        resolved=resolved,
        purpose=OAUTH_PURPOSE_LOGIN,
        project_hash=binding.project_hash,
        user_group_hash=binding.user_group_hash if resolved.binding.trusts_caller_scope else None,
        redirect_uri=redirect_uri,
        return_origin=binding.return_origin,
        remember_me=bool(body.get("remember_me", False)),
        init_fingerprint=fingerprint,
        scope_fingerprint=binding.scope_fingerprint,
    )
    return await _begin(request, pipeline, start, fingerprint=fingerprint, correlation_id=correlation_id)


def _assert_redeemed_scope(resolved: ResolvedConnection, binding: ProviderInitBinding) -> None:
    """Database bindings never accept a project or group the caller merely asserted."""

    project_binding = resolved.binding
    if project_binding.trusts_caller_scope:
        return
    if not project_binding.project_hash or not hmac.compare_digest(str(binding.project_hash), str(project_binding.project_hash)):
        raise ProviderInitRedeemError("provider_init_project_not_bound", token_fingerprint=binding.provider_init_fingerprint)
    if binding.user_group_hash and not hmac.compare_digest(
        str(binding.user_group_hash), str(project_binding.default_user_group_hash or "")
    ):
        raise ProviderInitRedeemError("provider_init_group_not_bound", token_fingerprint=binding.provider_init_fingerprint)


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
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=400, message=_BINDING_INVALID_MESSAGE)
    token = str(body.get("init_token") or "").strip()
    if not token or len(token) > 512:
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=400)
    fingerprint = fingerprint_provider_init_token(token)

    try:
        await pipeline._limit("check_start", request=request, provider_init_fingerprint=fingerprint)
    except OAuthRateLimitExceeded as exc:
        return oauth_error_response(ErrorCode.OAUTH_RATE_LIMITED, status_code=429, retry_after=exc.retry_after, correlation_id=correlation_id)

    try:
        record = init_store().consume(token)
    except OAuthInitTokenReplayed:
        await deps.emit(EVENT_INIT_REJECTED, details={"reason": "init_token_replayed", "provider_init_fingerprint": fingerprint}, request=request)
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=401, correlation_id=correlation_id)
    except (OAuthInitTokenInvalid, OAuthStateStoreUnavailable):
        await deps.emit(EVENT_INIT_REJECTED, details={"reason": "init_token_invalid", "provider_init_fingerprint": fingerprint}, request=request)
        return oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=401, correlation_id=correlation_id)

    try:
        resolved = deps.connection_source().get_by_ids(connection_id=record.connection_id, binding_id=record.binding_id)
    except OAuthConnectionUnavailable as exc:
        return _unavailable_response(exc, correlation_id)

    redirect_uri = _pick_redirect_uri(resolved, str(body.get("redirect_uri") or "").strip() or None, allow_first_default=False)
    if not redirect_uri or not resolved.binding.is_return_origin_allowed(record.return_origin):
        return oauth_error_response(ErrorCode.OAUTH_REDIRECT_URI_NOT_ALLOWED, status_code=400, correlation_id=correlation_id)

    # ``remember_me`` is a user preference, not security scope, so the browser may still set
    # it at start (as it always could on the legacy route). Everything that IS scope --
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
            details={"reason": reason, "provider_init_fingerprint": fingerprint},
            request=request,
        )
        code = ErrorCode.OAUTH_STATE_INVALID if isinstance(exc, OAuthStateStoreUnavailable) else ErrorCode.OAUTH_PROVIDER_NOT_CONFIGURED
        return oauth_error_response(code, correlation_id=correlation_id)


__all__ = ["read_json_object", "start_from_init_token", "start_from_legacy_provider_init"]
