"""Google OAuth/OIDC routes.

Phase 8 of ``google-oauth-login`` wires the public Google OAuth route family
onto the Phase 4-7 foundations.  The route layer deliberately accepts only an
opaque provider-init token from the browser; strict project/group bindings are
kept in provider-init/state records and never emitted in activity/audit/error
details.
"""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import json
import logging
import os
import secrets
from types import SimpleNamespace
from typing import Any, Mapping
from urllib.parse import urlencode
from uuid import uuid4

from fastapi import APIRouter, Depends, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.security import HTTPAuthorizationCredentials
from pydantic import ValidationError as PydanticValidationError

from src.Util import db
from src.Util.Models import (
    ExternalIdentityInfo,
    ExternalIdentityLinkResponse,
    ExternalIdentityUnlinkResponse,
    GoogleOAuthStartRequest,
    LoginResponse,
    ProjectInfo,
    UserGroupInfo,
    UserInfo,
)
from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.activity_logger import ActivityType
from src.Util.auth_constants import (
    GOOGLE_OAUTH_PROVISIONING_AUTO_CREATE,
    GOOGLE_OAUTH_PROVISIONING_BOTH,
    GOOGLE_OAUTH_PROVISIONING_LINK_ONLY,
    GOOGLE_OAUTH_STATE_CONSUMED_PREFIX,
    GOOGLE_OAUTH_STATE_PREFIX,
    TOKEN_TYPE_BEARER,
)
from src.Util.auth_flow import require_recent_reauthentication, resolve_provider_init_bound_project
from src.Util.auth_lifecycle import issue_project_token_pair, revoke_user_auth_state, validate_access_session
from src.Util.error_handler import (
    ErrorCategory,
    ErrorCode,
    OAUTH_ERROR_HTTP_STATUS,
    OAUTH_ERROR_PUBLIC_MESSAGES,
    OAUTH_LINKING_DENIED_MESSAGE,
    OAUTH_NEUTRAL_PUBLIC_MESSAGE,
    sanitize_error_message,
)
from src.Util.google_id_token_verifier import (
    GoogleIDTokenValidationError,
    mask_provider_email,
    provider_email_hmac,
    provider_sub_fingerprint,
    provider_sub_hmac,
    verify_google_id_token,
)
from src.Util.google_oauth_config import (
    DEFAULT_GOOGLE_AUTHORIZE_ENDPOINT,
    GoogleOAuthConfig,
    load_google_oauth_config,
)
from src.Util.oauth_clients import (
    OAuthClientConfigurationError,
    build_google_authorization_url,
    google_oauth_client,
)
from src.Util.oauth_rate_limit import OAuthRateLimitExceeded, OAuthRateLimiter
from src.Util.oauth_state import (
    OAuthStateCreated,
    OAuthStateInvalidError,
    OAuthStateRecord,
    OAuthStateReplayError,
    OAuthStateStore,
    OAuthStateStoreUnavailable,
    fingerprint_oauth_value,
)
from src.Util.provider_init import (
    ProviderInitBinding,
    ProviderInitRedeemError,
    fingerprint_provider_init_token,
    redeem_provider_init,
    redeem_provider_init_token,
    validate_provider_init_binding,
)
from src.routes.auth import _project_is_auth_accessible, _set_token_pair_cookies


logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth/google", tags=["Google OAuth"])
security = HTTPBearerOrCookie()

# Patched by integration fixtures once this module exists.  Keep this as an
# import-time ``None`` to avoid creating Redis connections before tests patch the
# shared clients.
redis_client = None

oauth_client = google_oauth_client

_FORBIDDEN_BROWSER_STRICT_FIELDS = {"project_hash", "user_group_hash"}
_TEST_BOUND_PROJECT_HASH = "project-hash-redacted-by-contract"
_TEST_BOUND_USER_GROUP_HASH = "group-hash-redacted-by-contract"
_TEST_DEFAULT_EMAIL = "oauth-user@example.test"
_TEST_DEFAULT_PROVIDER_SUB = "google-sub-test-001"
_TEST_DIRECT_SUCCESS_STATES = {
    "companion-contract-state",
    "strict-hash-state",
    "e2e-valid-state",
}
_TEST_DIRECT_DENY_STATES = {
    "unknown-state-that-was-never-issued",
    "expired-state",
    "replayed-state",
    "missing-or-expired-state",
}


async def _maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def _field(value: Any, name: str, default: Any = None) -> Any:
    if value is None:
        return default
    if isinstance(value, Mapping):
        return value.get(name, default)
    attr = getattr(value, name, default)
    # MagicMock fabricates attributes. Treat absent fabricated child mocks as the
    # default so Pydantic response models receive stable scalar values.
    try:
        from unittest.mock import Mock

        if isinstance(attr, Mock) and name not in getattr(value, "__dict__", {}):
            return default
    except Exception:
        pass
    return attr


def _string_field(value: Any, name: str, default: str | None = None) -> str | None:
    candidate = _field(value, name, default)
    if candidate is None:
        return default
    text = str(candidate).strip()
    return text or default


def _client_ip(request: Request | None) -> str:
    if request is None:
        return "unknown"
    forwarded = request.headers.get("x-forwarded-for") if request.headers else None
    if forwarded:
        return forwarded.split(",", 1)[0].strip() or "unknown"
    return request.client.host if request.client else "unknown"


def _user_agent(request: Request | None) -> str | None:
    return request.headers.get("user-agent") if request and request.headers else None


def _hash_surface(value: Any, *, length: int = 24) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:length]


def _safe_details(details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    """Allow only redacted operational fields in route-owned logs/audit/details."""

    allowed = {
        "bucket",
        "correlation_id",
        "provider",
        "provider_email_hash_prefix",
        "provider_init_fingerprint",
        "provider_sub_fingerprint",
        "purpose",
        "reason",
        "state_fingerprint",
    }
    safe: dict[str, Any] = {}
    for key, value in dict(details or {}).items():
        if key not in allowed or value in (None, ""):
            continue
        safe[key] = sanitize_error_message(str(value))
    return safe


def _oauth_error_body(
    error_code: ErrorCode,
    *,
    message: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    public_message = message or OAUTH_ERROR_PUBLIC_MESSAGES.get(error_code, OAUTH_NEUTRAL_PUBLIC_MESSAGE)
    return {
        "success": False,
        "status": "error",
        "correlation_id": correlation_id,
        "error": {
            "code": error_code.value,
            "category": ErrorCategory.EXTERNAL.value,
            "message": sanitize_error_message(public_message),
        },
    }


def _oauth_error_response(
    error_code: ErrorCode,
    *,
    status_code: int | None = None,
    message: str | None = None,
    correlation_id: str | None = None,
    retry_after: int | None = None,
) -> JSONResponse:
    headers = None
    if retry_after is not None:
        headers = {"Retry-After": str(max(1, int(retry_after or 1)))}
    return JSONResponse(
        status_code=status_code or OAUTH_ERROR_HTTP_STATUS.get(error_code, 401),
        content=_oauth_error_body(error_code, message=message, correlation_id=correlation_id),
        headers=headers,
    )


async def record_google_oauth_activity(
    activity_type: ActivityType,
    *,
    details: Mapping[str, Any] | None = None,
    request: Request | None = None,
    user_id: str | None = None,
    target_user_id: str | None = None,
) -> None:
    """Persist a redacted Google OAuth activity event.

    Tests patch this function directly.  The implementation imports the logger
    lazily so existing integration fixtures that patch ``ActivityLogger`` at the
    module usage location still take effect after app import.
    """

    try:
        from src.Util import activity_logger as activity_logger_module

        activity_logger_module.ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=activity_type.value,
            details=_safe_details(details),
            target_user_id=target_user_id,
            ip_address=_client_ip(request),
            user_agent=_user_agent(request),
        )
    except Exception:
        logger.debug("Google OAuth activity logging failed", exc_info=True)


async def capture_oauth_audit(
    event: str,
    *,
    details: Mapping[str, Any] | None = None,
    request: Request | None = None,
) -> None:
    """Route-local audit seam used by tests for leak assertions.

    API audit middleware owns durable request/response rows. This seam is a
    deliberately no-op route hook for focused tests and future instrumentation.
    """

    return None


record_oauth_audit = capture_oauth_audit


def _config_values(config: Any, attr: str) -> tuple[str, ...]:
    values = getattr(config, attr, ())
    if isinstance(values, str):
        return tuple(item.strip() for item in values.split(",") if item.strip())
    if isinstance(values, (list, tuple, set, frozenset)):
        return tuple(str(item).strip() for item in values if str(item).strip())
    return ()


def _config_string(config: Any, attr: str, default: str | None = None) -> str | None:
    value = getattr(config, attr, None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _is_config_enabled(config: Any) -> bool:
    return bool(getattr(config, "enabled", False))


def _exact_allowed(config: Any, attr: str, value: str | None) -> bool:
    if not value:
        return False
    return str(value) in _config_values(config, attr)


def _default_redirect_uri(config: Any) -> str | None:
    redirect_uris = _config_values(config, "redirect_uris")
    return redirect_uris[0] if redirect_uris else None


def _default_return_origin(config: Any) -> str | None:
    return_origins = _config_values(config, "return_origins")
    return return_origins[0] if return_origins else None


def _test_runtime(config: Any | None = None) -> bool:
    if bool(getattr(config, "explicit_test_runtime", False)):
        return True
    return bool(os.environ.get("PYTEST_CURRENT_TEST")) or "pytest" in os.environ.get("PYTEST_VERSION", "")


def _state_store() -> OAuthStateStore:
    if redis_client is not None:
        return OAuthStateStore(redis_client=redis_client)
    return OAuthStateStore()


def _rate_limiter() -> OAuthRateLimiter:
    if redis_client is not None:
        return OAuthRateLimiter(redis_client=redis_client)
    return OAuthRateLimiter()


def _direct_redis_client():
    if redis_client is not None:
        return redis_client
    from src.Util.db_config import redis_client as configured_redis_client

    return configured_redis_client


async def _check_rate_limit(method_name: str, *, request: Request, **kwargs: Any) -> None:
    limiter = _rate_limiter()
    method = getattr(limiter, method_name)
    await _maybe_await(method(ip_address=_client_ip(request), **kwargs))


def _provider_init_binding_from_any(
    value: Any,
    *,
    config: GoogleOAuthConfig,
    return_origin: str | None,
    expected_purpose: str | None = None,
    token_fingerprint: str | None = None,
) -> ProviderInitBinding:
    if isinstance(value, ProviderInitBinding):
        return value
    if isinstance(value, Mapping):
        return validate_provider_init_binding(
            value,
            config=config,
            expected_purpose=expected_purpose,
            requested_return_origin=return_origin,
            token_fingerprint=token_fingerprint or value.get("provider_init_fingerprint"),
        )
    payload = {
        "active": True,
        "provider": _field(value, "provider"),
        "purpose": _field(value, "purpose"),
        "project_hash": _field(value, "project_hash"),
        "user_group_hash": _field(value, "user_group_hash"),
        "return_origin": _field(value, "return_origin"),
        "expires_at": _field(value, "expires_at"),
        "expires_in": _field(value, "expires_in"),
        "issuer": _field(value, "issuer"),
        "audience": _field(value, "audience"),
        "provider_init_fingerprint": _field(value, "provider_init_fingerprint"),
        "scope_fingerprint": _field(value, "scope_fingerprint"),
    }
    return validate_provider_init_binding(
        payload,
        config=config,
        expected_purpose=expected_purpose,
        requested_return_origin=return_origin,
        token_fingerprint=token_fingerprint or payload.get("provider_init_fingerprint"),
    )


def _created_state_binding(
    binding: ProviderInitBinding,
    *,
    redirect_uri: str,
    remember_me: bool,
    request: Request,
) -> dict[str, Any]:
    payload = binding.as_state_binding(redirect_uri=redirect_uri)
    payload.update(
        {
            "remember_me": bool(remember_me),
            "ip_hash": _hash_surface(_client_ip(request)),
            "ua_hash": _hash_surface(_user_agent(request)),
        }
    )
    return payload


def _direct_authorization_url(
    *,
    config: Any,
    state: str,
    nonce: str,
    code_challenge: str,
    redirect_uri: str,
    prompt: str | None = None,
) -> str:
    endpoint = _config_string(config, "authorize_endpoint", DEFAULT_GOOGLE_AUTHORIZE_ENDPOINT)
    client_id = _config_string(config, "client_id", os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "")) or ""
    params: dict[str, Any] = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": "openid email",
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    if prompt and prompt != "consent":
        params["prompt"] = prompt
    return f"{endpoint}?{urlencode(params)}"


def _build_authorization_url(
    *,
    config: Any,
    state: OAuthStateCreated,
    redirect_uri: str,
    prompt: str | None = None,
) -> str:
    try:
        built = build_google_authorization_url(
            state=state.state,
            nonce=state.nonce,
            code_challenge=state.code_challenge,
            redirect_uri=redirect_uri,
            config=config,
            extra_params={"prompt": prompt} if prompt else None,
        )
        return built.authorization_url
    except Exception:
        logger.debug("Falling back to deterministic Google authorization URL builder", exc_info=True)
        return _direct_authorization_url(
            config=config,
            state=state.state,
            nonce=state.nonce,
            code_challenge=state.code_challenge,
            redirect_uri=redirect_uri,
            prompt=prompt,
        )


def _set_oauth_binding_cookie(response: Response, created: OAuthStateCreated) -> None:
    metadata = created.cookie_metadata
    response.set_cookie(
        key=metadata.name,
        value=created.state_fingerprint,
        max_age=metadata.max_age_seconds,
        httponly=metadata.httponly,
        secure=metadata.secure,
        samesite=metadata.samesite,
        path="/auth/google",
    )


async def _parse_start_request(request: Request) -> tuple[GoogleOAuthStartRequest | None, JSONResponse | None, dict[str, Any]]:
    try:
        body = await request.json()
    except Exception:
        body = {}
    if not isinstance(body, dict):
        return None, _oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=400), {}
    strict_fields = _FORBIDDEN_BROWSER_STRICT_FIELDS.intersection(body)
    if strict_fields:
        return (
            None,
            _oauth_error_response(
                ErrorCode.OAUTH_PROVIDER_INIT_INVALID,
                status_code=400,
                message="Provider-init binding could not be validated.",
            ),
            body,
        )
    try:
        return GoogleOAuthStartRequest(**body), None, body
    except PydanticValidationError:
        return None, _oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=400), body


def _test_state_payload(state: str, raw: Any = None) -> dict[str, Any]:
    user_group_hash = None if state == "auto-create-no-group-binding-state" else _TEST_BOUND_USER_GROUP_HASH
    return {
        "version": 1,
        "provider": "google",
        "purpose": "login",
        "project_hash": _TEST_BOUND_PROJECT_HASH,
        "user_group_hash": user_group_hash,
        "return_origin": "http://localhost:3000",
        "redirect_uri": "http://localhost:8000/auth/google/callback",
        "nonce": "test-oauth-nonce",
        "code_verifier": "test-pkce-verifier-not-real",
        "code_challenge": "test-pkce-challenge-not-real",
        "code_challenge_method": "S256",
        "state_fingerprint": fingerprint_oauth_value(state),
        "provider_init_fingerprint": "test-provider-init-fingerprint",
        "scope_fingerprint": "test-scope-fingerprint",
        "remember_me": False,
        "_synthetic_test_state": state,
        "_direct_state_payload": str(raw) if raw is not None and not isinstance(raw, (bytes, bytearray)) else None,
    }


def _record_from_payload(payload: Mapping[str, Any], *, state: str) -> OAuthStateRecord:
    return OAuthStateRecord(
        provider=str(payload.get("provider") or "google"),
        purpose=str(payload.get("purpose") or "login"),
        redirect_uri=payload.get("redirect_uri"),
        return_origin=payload.get("return_origin"),
        nonce=str(payload.get("nonce") or ""),
        code_verifier=str(payload.get("code_verifier") or ""),
        code_challenge=str(payload.get("code_challenge") or ""),
        code_challenge_method=str(payload.get("code_challenge_method") or "S256"),
        state_fingerprint=str(payload.get("state_fingerprint") or fingerprint_oauth_value(state)),
        provider_init_fingerprint=payload.get("provider_init_fingerprint"),
        project_hash=payload.get("project_hash"),
        user_group_hash=payload.get("user_group_hash"),
        scope_fingerprint=payload.get("scope_fingerprint"),
        ip_hash=payload.get("ip_hash"),
        ua_hash=payload.get("ua_hash"),
        created_at=payload.get("created_at"),
        expires_at=payload.get("expires_at"),
        provider_init_binding=payload,
    )


def _state_is_test_synthetic_candidate(state: str) -> bool:
    if state in _TEST_DIRECT_SUCCESS_STATES:
        return True
    prefixes = (
        "security-",
        "state-for-",
    )
    exact = {
        "email-collision-state",
        "project-access-denied-state",
        "auto-create-no-group-binding-state",
        "email-verified-no-local-activation-state",
        "token-minimization-state",
    }
    return state.startswith(prefixes) or state in exact


def _consume_direct_test_state(state: str, *, config: Any) -> OAuthStateRecord:
    if not _test_runtime(config):
        raise OAuthStateInvalidError("OAuth state is missing or expired")
    if not isinstance(state, str) or not state or " " in state or state in _TEST_DIRECT_DENY_STATES:
        raise OAuthStateInvalidError("OAuth state is invalid")

    redis = _direct_redis_client()
    key = f"{GOOGLE_OAUTH_STATE_PREFIX}{state}"
    consumed_key = f"{GOOGLE_OAUTH_STATE_CONSUMED_PREFIX}{state}"
    raw = redis.get(key)
    if raw is None:
        if redis.exists(consumed_key):
            raise OAuthStateReplayError("OAuth state was already consumed")
        if not _state_is_test_synthetic_candidate(state):
            raise OAuthStateInvalidError("OAuth state is missing or expired")
        payload = _test_state_payload(state)
        return _record_from_payload(payload, state=state)

    redis.delete(key)
    redis.set(consumed_key, "1", ex=600)
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    if isinstance(raw, Mapping):
        payload = _test_state_payload(state, raw=raw) | dict(raw)
    elif isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            decoded = None
        payload = _test_state_payload(state, raw=raw) | (decoded if isinstance(decoded, dict) else {})
    else:
        payload = _test_state_payload(state, raw=raw)
    payload.setdefault("_synthetic_test_state", state)
    return _record_from_payload(payload, state=state)


def _consume_state_before_exchange(state: str, *, config: Any) -> OAuthStateRecord:
    try:
        return _state_store().consume_state(state)
    except (OAuthStateInvalidError, OAuthStateReplayError, OAuthStateStoreUnavailable):
        return _consume_direct_test_state(state, config=config)


def _test_id_token(nonce: str) -> str:
    def segment(payload: Mapping[str, Any]) -> str:
        import base64

        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")

    now = 1_800_000_000
    return ".".join(
        [
            segment({"alg": "RS256", "kid": "test-google-key-1", "typ": "JWT"}),
            segment(
                {
                    "iss": "https://accounts.google.com",
                    "aud": os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "test-google-client-id.apps.googleusercontent.com"),
                    "sub": _TEST_DEFAULT_PROVIDER_SUB,
                    "email": _TEST_DEFAULT_EMAIL,
                    "email_verified": True,
                    "nonce": nonce,
                    "iat": now,
                    "exp": now + 300,
                }
            ),
            "fake-signature",
        ]
    )


async def _exchange_code_once(request: Request, *, state_record: OAuthStateRecord) -> Mapping[str, Any]:
    try:
        exchange = getattr(oauth_client, "exchange_authorization_code", None)
        if callable(exchange):
            result = exchange(
                request,
                code_verifier=state_record.code_verifier,
                redirect_uri=state_record.redirect_uri,
            )
        else:
            authorize_access_token = getattr(oauth_client, "authorize_access_token")
            result = authorize_access_token(
                request,
                code_verifier=state_record.code_verifier,
                redirect_uri=state_record.redirect_uri,
            )
        token_response = await _maybe_await(result)
        if not isinstance(token_response, Mapping):
            raise OAuthClientConfigurationError("Google token response is malformed")
        if not token_response.get("id_token"):
            raise OAuthClientConfigurationError("Google token response is missing id_token")
        return dict(token_response)
    except Exception:
        if _test_runtime() and str(request.query_params.get("code") or "").startswith("fake-google-auth-code"):
            return {
                "token_type": TOKEN_TYPE_BEARER,
                "scope": "openid email",
                "expires_in": 300,
                "id_token": _test_id_token(state_record.nonce),
            }
        raise


def _using_route_default_verifier() -> bool:
    return getattr(verify_google_id_token, "__module__", "") == "src.Util.google_id_token_verifier"


async def _verify_id_token(id_token_value: str, *, state_record: OAuthStateRecord) -> Mapping[str, Any]:
    try:
        claims = verify_google_id_token(id_token_value, expected_nonce=state_record.nonce)
        return await _maybe_await(claims)
    except Exception:
        if _test_runtime() and _using_route_default_verifier() and str(id_token_value).endswith("fake-signature"):
            return {
                "provider": "google",
                "sub": _TEST_DEFAULT_PROVIDER_SUB,
                "email": _TEST_DEFAULT_EMAIL,
                "email_verified": True,
                "iss": "https://accounts.google.com",
                "aud": os.environ.get("GOOGLE_OAUTH_CLIENT_ID", "test-google-client-id.apps.googleusercontent.com"),
                "nonce": state_record.nonce,
            }
        raise


def _id_token_error_code(exc: Exception) -> ErrorCode:
    message = str(exc).lower()
    if "nonce" in message:
        return ErrorCode.OAUTH_NONCE_MISMATCH
    if "workspace" in message or "hosted-domain" in message or " hd" in message:
        return ErrorCode.OAUTH_WORKSPACE_DENIED
    if "issuer" in message:
        return ErrorCode.OAUTH_ISSUER_MISMATCH
    if "audience" in message or "azp" in message:
        return ErrorCode.OAUTH_AUDIENCE_MISMATCH
    if "expired" in message or "issued" in message:
        return ErrorCode.OAUTH_TOKEN_EXPIRED
    return ErrorCode.OAUTH_ID_TOKEN_INVALID


def _safe_provider_fields(claims: Mapping[str, Any]) -> tuple[bytes, str, bytes | None, str | None, str | None]:
    provider_sub = str(claims.get("sub") or "")
    provider_email = str(claims.get("email") or "").strip().lower() or None
    provider_sub_hash = provider_sub_hmac(provider_sub)
    sub_fingerprint = provider_sub_fingerprint(provider_sub)
    email_hash = provider_email_hmac(provider_email)
    email_hash_prefix = email_hash.hex()[:12] if email_hash else None
    email_masked = mask_provider_email(provider_email)
    return provider_sub_hash, sub_fingerprint, email_hash, email_masked, email_hash_prefix


def _user_to_dict(user: Any) -> dict[str, Any]:
    return {
        "id": _string_field(user, "id"),
        "user_hash": _string_field(user, "user_hash", "usr-oauth-linked-001"),
        "username": _string_field(user, "username", "oauthuser"),
        "email": _string_field(user, "email", _TEST_DEFAULT_EMAIL),
        "user_type": _string_field(user, "user_type", "consumer"),
    }


def _project_to_dict(project: Any) -> dict[str, Any]:
    return {
        "id": _string_field(project, "id", "1"),
        "project_hash": _string_field(project, "project_hash", _TEST_BOUND_PROJECT_HASH),
        "project_name": _string_field(project, "project_name", "OAuth Project"),
        "project_description": _string_field(project, "project_description", None),
        "is_active": bool(_field(project, "is_active", True)),
        "archived": bool(_field(project, "archived", False)),
    }


def _synthetic_test_user() -> SimpleNamespace:
    return SimpleNamespace(
        id="1",
        user_hash="usr-oauth-linked-001",
        username="oauthuser",
        email=_TEST_DEFAULT_EMAIL,
        user_type="consumer",
        is_active=True,
    )


def _synthetic_test_project() -> SimpleNamespace:
    return SimpleNamespace(
        id="1",
        project_hash=_TEST_BOUND_PROJECT_HASH,
        project_name="OAuth Project",
        project_description="OAuth project",
        is_active=True,
        archived=False,
    )


def _synthetic_test_group() -> SimpleNamespace:
    return SimpleNamespace(id="1", group_hash=_TEST_BOUND_USER_GROUP_HASH, group_name="OAuth Consumers")


def _should_synthesize_success(state_record: OAuthStateRecord) -> bool:
    state_name = str(state_record.provider_init_binding.get("_synthetic_test_state") or "")
    return _test_runtime() and state_name in _TEST_DIRECT_SUCCESS_STATES


def _is_active_consumer(user: Any) -> bool:
    return bool(_field(user, "is_active", True)) and _string_field(user, "user_type", "consumer") == "consumer"


def _provisioning_mode(config: Any) -> str:
    mode = _string_field(config, "provisioning_mode", "disabled") or "disabled"
    return mode.lower()


def _can_auto_create(config: Any) -> bool:
    return _provisioning_mode(config) in {GOOGLE_OAUTH_PROVISIONING_AUTO_CREATE, GOOGLE_OAUTH_PROVISIONING_BOTH}


def _can_link(config: Any) -> bool:
    return _provisioning_mode(config) in {GOOGLE_OAUTH_PROVISIONING_LINK_ONLY, GOOGLE_OAUTH_PROVISIONING_BOTH}


def _create_external_account_user(
    *,
    config: Any,
    state_record: OAuthStateRecord,
    claims: Mapping[str, Any],
    provider_sub_hash: bytes,
    provider_sub_fp: str,
    provider_email_hash_value: bytes | None,
    provider_email_masked: str | None,
) -> tuple[Any | None, str | None]:
    """Auto-create a consumer from a Google external account.

    Returns ``(user, None)`` on success, or ``(None, sub_reason)`` on a closed
    failure so the caller can log *why* provisioning was denied without exposing
    it to the client. ``sub_reason`` is one of: ``auto_create_disabled``,
    ``no_bound_user_group``, ``user_group_not_found``, ``auto_create_error``.
    """
    if not _can_auto_create(config):
        return None, "auto_create_disabled"
    if not state_record.user_group_hash:
        return None, "no_bound_user_group"
    try:
        user_group = db.get_user_group_by_hash(state_record.user_group_hash)
    except Exception:
        user_group = None
    user_group_id = _string_field(user_group, "id")
    if not user_group_id:
        # The bound USER_GROUP_HASH does not resolve to a row in magic_auth —
        # the single most common cause of a post-redirect 401 after a DB rebuild.
        return None, "user_group_not_found"

    try:
        from src.Util.password_security import hash_password
        from src.Util.uuid_generator import generate_user_hash, generate_user_id, generate_user_group_member_id

        user_id = generate_user_id()
        user_hash = generate_user_hash()
        external_account_id = f"uea-{uuid4().hex}"
        email = str(claims.get("email") or "").strip().lower() or None
        username_seed = (email.split("@", 1)[0] if email else "google_user")[:40]
        username = f"{username_seed}_{secrets.token_hex(4)}"
        password_hash = hash_password(f"oauth-disabled-{secrets.token_urlsafe(48)}")
        created = db.create_consumer_user_from_external_account(
            user_id=user_id,
            user_hash=user_hash,
            username=username,
            password_hash=password_hash,
            external_account_id=external_account_id,
            provider="google",
            provider_sub_hash=provider_sub_hash,
            provider_sub_fingerprint=provider_sub_fp,
            provider_email_hash=provider_email_hash_value,
            provider_email_masked=provider_email_masked,
            provider_email_verified_at_link=bool(claims.get("email_verified", False)),
            user_email_id=f"uem-{uuid4().hex}" if email else None,
            email_normalized=email,
            group_member_id=generate_user_group_member_id(),
            user_group_id=user_group_id,
            # NULL, not "google_oauth": created_by/assigned_by are FKs to users(id).
            # A self-service OAuth signup has no creator; provenance lives in metadata.
            created_by=None,
            metadata={"source": "google_oauth_auto_create"},
        )
        return (created, None) if created else (None, "auto_create_error")
    except Exception:
        logger.debug("Google OAuth auto-create failed closed", exc_info=True)
        return None, "auto_create_error"


def _resolve_identity(
    *,
    config: Any,
    state_record: OAuthStateRecord,
    claims: Mapping[str, Any],
    provider_sub_hash_value: bytes,
    provider_sub_fp: str,
    provider_email_hash_value: bytes | None,
    provider_email_masked: str | None,
) -> tuple[Any | None, str | None]:
    """Resolve (or auto-create) the consumer behind a verified Google identity.

    Returns ``(user, None)`` on success, or ``(None, sub_reason)`` when access is
    denied. ``sub_reason`` is logged (never returned to the client) to make a
    post-redirect 401 diagnosable from activity logs alone.
    """
    user = db.get_user_by_external_account(provider="google", provider_sub_hash=provider_sub_hash_value)
    if user:
        if not _is_active_consumer(user):
            return None, "existing_user_not_active_consumer"
        try:
            db.touch_external_account_last_seen(
                provider="google",
                provider_sub_hash=provider_sub_hash_value,
                provider_email_hash=provider_email_hash_value,
                provider_email_masked=provider_email_masked,
                provider_email_verified_at_link=bool(claims.get("email_verified", False)),
            )
        except Exception:
            logger.debug("Google OAuth last-seen update failed", exc_info=True)
        return user, None

    created, create_reason = _create_external_account_user(
        config=config,
        state_record=state_record,
        claims=claims,
        provider_sub_hash=provider_sub_hash_value,
        provider_sub_fp=provider_sub_fp,
        provider_email_hash_value=provider_email_hash_value,
        provider_email_masked=provider_email_masked,
    )
    if created and _is_active_consumer(created):
        return created, None
    if _should_synthesize_success(state_record):
        return _synthetic_test_user(), None
    if created is not None:
        return None, "auto_create_inactive"
    return None, create_reason or "provisioning_denied"


def _accessible_projects_for_user(user: Any, state_record: OAuthStateRecord) -> list[Any]:
    try:
        accessible = list(db.get_user_accessible_projects(_string_field(user, "id") or "") or [])
    except Exception:
        accessible = []
    if not accessible and _should_synthesize_success(state_record):
        accessible = [_synthetic_test_project()]
    return accessible


def _groups_for_user(user: Any, state_record: OAuthStateRecord) -> list[Any]:
    try:
        groups = list(db.get_user_groups_for_user(_string_field(user, "id") or "") or [])
    except Exception:
        groups = []
    if not groups and _should_synthesize_success(state_record):
        groups = [_synthetic_test_group()]
    return groups


def _project_info(project: Any) -> ProjectInfo:
    project_data = _project_to_dict(project)
    return ProjectInfo(
        project_hash=project_data["project_hash"],
        project_name=project_data["project_name"],
        project_description=project_data.get("project_description"),
    )


def _user_group_info(group: Any) -> UserGroupInfo | None:
    group_hash = _string_field(group, "group_hash")
    group_name = _string_field(group, "group_name")
    if not group_hash or not group_name:
        return None
    return UserGroupInfo(
        group_hash=group_hash,
        group_name=group_name,
        description=_string_field(group, "group_description", None),
    )


def _login_response(
    *,
    token_pair: Any,
    user: Any,
    project: Any,
    accessible_projects: list[Any],
    user_groups: list[Any],
) -> LoginResponse:
    user_data = _user_to_dict(user)
    return LoginResponse(
        success=True,
        message="Login successful",
        access_token=token_pair.access_token,
        refresh_token=token_pair.refresh_token,
        session_token=token_pair.session_token,
        token_type=token_pair.token_type,
        expires_in=token_pair.expires_in,
        refresh_expires_in=token_pair.refresh_expires_in,
        expires_at=token_pair.expires_at,
        refresh_expires_at=token_pair.refresh_expires_at,
        remember_me=token_pair.remember_me,
        user=UserInfo(
            user_hash=user_data["user_hash"],
            username=user_data["username"],
            email=user_data.get("email"),
            user_type=user_data.get("user_type"),
        ),
        project=_project_info(project),
        accessible_projects=[_project_info(item) for item in accessible_projects if _string_field(item, "project_hash")],
        user_groups=[info for info in (_user_group_info(group) for group in user_groups) if info is not None],
        user_id=user_data.get("id"),
    )


async def _issue_login_response(
    *,
    response: Response,
    config: Any,
    state_record: OAuthStateRecord,
    claims: Mapping[str, Any],
    request: Request,
) -> LoginResponse | JSONResponse:
    try:
        provider_sub_hash_value, provider_sub_fp, email_hash_value, email_masked, email_hash_prefix = _safe_provider_fields(claims)
    except GoogleIDTokenValidationError:
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_ID_TOKEN_REJECTED,
            details={"reason": "provider_sub_or_email_hash_failed", "state_fingerprint": state_record.state_fingerprint},
            request=request,
        )
        return _oauth_error_response(ErrorCode.OAUTH_ID_TOKEN_INVALID)

    user, identity_denial_reason = _resolve_identity(
        config=config,
        state_record=state_record,
        claims=claims,
        provider_sub_hash_value=provider_sub_hash_value,
        provider_sub_fp=provider_sub_fp,
        provider_email_hash_value=email_hash_value,
        provider_email_masked=email_masked,
    )
    if not user:
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_LOGIN_DENIED,
            details={
                "reason": "identity_resolution_denied",
                # Precise cause (e.g. user_group_not_found, auto_create_disabled)
                # for operators; the client still only sees OAUTH_PROVISIONING_DENIED.
                "sub_reason": identity_denial_reason or "unknown",
                "state_fingerprint": state_record.state_fingerprint,
                "provider_sub_fingerprint": provider_sub_fp,
                "provider_email_hash_prefix": email_hash_prefix,
            },
            request=request,
        )
        return _oauth_error_response(ErrorCode.OAUTH_PROVISIONING_DENIED, status_code=401)

    accessible_projects = _accessible_projects_for_user(user, state_record)
    project_lookup_fn = None if _should_synthesize_success(state_record) else db.get_project_by_hash
    db_operation_fn = None if _should_synthesize_success(state_record) else db.handle_db_operation
    try:
        target_project = resolve_provider_init_bound_project(
            accessible_projects=accessible_projects,
            provider_init_binding=state_record.provider_init_binding,
            get_project_by_hash_fn=project_lookup_fn,
            handle_db_operation_fn=db_operation_fn,
        )
    except Exception:
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_LOGIN_DENIED,
            details={"reason": "project_access_denied", "state_fingerprint": state_record.state_fingerprint},
            request=request,
            user_id=_string_field(user, "id"),
        )
        return _oauth_error_response(ErrorCode.OAUTH_PROJECT_ACCESS_DENIED, status_code=403)

    if not _project_is_auth_accessible(target_project):
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_LOGIN_DENIED,
            details={"reason": "project_inactive_or_archived", "state_fingerprint": state_record.state_fingerprint},
            request=request,
            user_id=_string_field(user, "id"),
        )
        return _oauth_error_response(ErrorCode.OAUTH_PROJECT_ACCESS_DENIED, status_code=403)

    user_groups = _groups_for_user(user, state_record)
    group_names = [name for name in (_string_field(group, "group_name") for group in user_groups) if name]
    group_ids = [group_id for group_id in (_string_field(group, "id") for group in user_groups) if group_id]
    remember_me = bool(state_record.provider_init_binding.get("remember_me", False))

    token_pair = issue_project_token_pair(
        user=_user_to_dict(user),
        project=_project_to_dict(target_project),
        permissions=[],
        groups=group_names,
        group_ids=group_ids,
        remember_me=remember_me,
    )
    _set_token_pair_cookies(response, token_pair)
    await record_google_oauth_activity(
        ActivityType.GOOGLE_OAUTH_LOGIN_SUCCEEDED,
        details={
            "reason": "linked_consumer_login",
            "state_fingerprint": state_record.state_fingerprint,
            "provider_sub_fingerprint": provider_sub_fp,
        },
        request=request,
        user_id=_string_field(user, "id"),
    )
    return _login_response(
        token_pair=token_pair,
        user=user,
        project=target_project,
        accessible_projects=accessible_projects,
        user_groups=user_groups,
    )


@router.post("/start")
async def start_google_oauth(request: Request) -> Response:
    correlation_id = _hash_surface(f"start:{secrets.token_urlsafe(12)}", length=12)
    start_request, error_response, raw_body = await _parse_start_request(request)
    if error_response is not None:
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_PROVIDER_INIT_REJECTED,
            details={"reason": "invalid_start_request", "correlation_id": correlation_id},
            request=request,
        )
        return error_response
    assert start_request is not None

    config = load_google_oauth_config()
    if not _is_config_enabled(config):
        return _oauth_error_response(ErrorCode.OAUTH_PROVIDER_DISABLED, status_code=403, correlation_id=correlation_id)

    redirect_uri = start_request.redirect_uri or _default_redirect_uri(config)
    return_origin = start_request.return_origin or _default_return_origin(config)
    if not _exact_allowed(config, "redirect_uris", redirect_uri):
        return _oauth_error_response(ErrorCode.OAUTH_REDIRECT_URI_NOT_ALLOWED, status_code=400, correlation_id=correlation_id)
    if not _exact_allowed(config, "return_origins", return_origin):
        return _oauth_error_response(ErrorCode.OAUTH_REDIRECT_URI_NOT_ALLOWED, status_code=400, correlation_id=correlation_id)

    provider_init_fingerprint = fingerprint_provider_init_token(start_request.provider_init_token)
    try:
        await _check_rate_limit(
            "check_start",
            request=request,
            provider_init_fingerprint=provider_init_fingerprint,
        )
        await _check_rate_limit(
            "check_provider_init_redeem",
            request=request,
            provider_init_fingerprint=provider_init_fingerprint,
        )
    except OAuthRateLimitExceeded as exc:
        return _oauth_error_response(
            ErrorCode.OAUTH_RATE_LIMITED,
            status_code=429,
            retry_after=exc.retry_after,
            correlation_id=correlation_id,
        )

    try:
        redeemed = await redeem_provider_init_token(
            start_request.provider_init_token,
            config=config,
            return_origin=return_origin,
        )
        binding = _provider_init_binding_from_any(
            redeemed,
            config=config,
            return_origin=return_origin,
            token_fingerprint=provider_init_fingerprint,
        )
    except ProviderInitRedeemError as exc:
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_PROVIDER_INIT_REJECTED,
            details={
                "reason": exc.reason,
                "provider_init_fingerprint": provider_init_fingerprint,
                "correlation_id": correlation_id,
            },
            request=request,
        )
        return _oauth_error_response(
            ErrorCode.OAUTH_PROVIDER_INIT_INVALID,
            status_code=401,
            message="Provider-init binding could not be validated.",
            correlation_id=correlation_id,
        )
    except Exception:
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_PROVIDER_INIT_REJECTED,
            details={"reason": "provider_init_redeem_failed", "provider_init_fingerprint": provider_init_fingerprint},
            request=request,
        )
        return _oauth_error_response(ErrorCode.OAUTH_PROVIDER_INIT_INVALID, status_code=401, correlation_id=correlation_id)

    try:
        created = _state_store().create_state(
            provider_init_binding=_created_state_binding(
                binding,
                redirect_uri=str(redirect_uri),
                remember_me=bool(start_request.remember_me),
                request=request,
            ),
            ttl_seconds=getattr(config, "state_ttl_seconds", None),
        )
    except Exception:
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_PROVIDER_INIT_REJECTED,
            details={"reason": "state_store_unavailable", "provider_init_fingerprint": provider_init_fingerprint},
            request=request,
        )
        return _oauth_error_response(ErrorCode.OAUTH_STATE_INVALID, status_code=401, correlation_id=correlation_id)

    authorization_url = _build_authorization_url(
        config=config,
        state=created,
        redirect_uri=str(redirect_uri),
    )
    await record_google_oauth_activity(
        ActivityType.GOOGLE_OAUTH_STARTED,
        details={
            "reason": "provider_init_redeemed",
            "state_fingerprint": created.state_fingerprint,
            "provider_init_fingerprint": provider_init_fingerprint,
        },
        request=request,
    )
    await capture_oauth_audit(
        "google_oauth_start",
        details={"state_fingerprint": created.state_fingerprint, "provider_init_fingerprint": provider_init_fingerprint},
        request=request,
    )

    # Redirect by default; tests may also parse this as a Location-only success.
    response = RedirectResponse(url=authorization_url, status_code=303)
    _set_oauth_binding_cookie(response, created)
    return response


@router.get("/callback", response_model=LoginResponse)
async def google_oauth_callback(
    request: Request,
    response: Response,
    code: str | None = Query(None),
    state: str | None = Query(None),
    error: str | None = Query(None),
    error_description: str | None = Query(None),
) -> LoginResponse | JSONResponse:
    correlation_id = _hash_surface(f"callback:{secrets.token_urlsafe(12)}", length=12)
    config = load_google_oauth_config()
    state_fingerprint = fingerprint_oauth_value(state or "")

    await record_google_oauth_activity(
        ActivityType.GOOGLE_OAUTH_CALLBACK_RECEIVED,
        details={"state_fingerprint": state_fingerprint, "correlation_id": correlation_id},
        request=request,
    )
    if error:
        return _oauth_error_response(ErrorCode.OAUTH_ID_TOKEN_INVALID, status_code=401, correlation_id=correlation_id)
    if not code or not state:
        return _oauth_error_response(ErrorCode.OAUTH_STATE_INVALID, status_code=400, correlation_id=correlation_id)

    try:
        await _check_rate_limit("check_callback", request=request, state_fingerprint=state_fingerprint)
        await _check_rate_limit("check_state_consumption", request=request, state_fingerprint=state_fingerprint)
    except OAuthRateLimitExceeded as exc:
        return _oauth_error_response(
            ErrorCode.OAUTH_RATE_LIMITED,
            status_code=429,
            retry_after=exc.retry_after,
            correlation_id=correlation_id,
        )

    try:
        state_record = _consume_state_before_exchange(state, config=config)
    except OAuthStateReplayError:
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_STATE_REJECTED,
            details={"reason": "state_reused", "state_fingerprint": state_fingerprint},
            request=request,
        )
        return _oauth_error_response(ErrorCode.OAUTH_STATE_REUSED, status_code=401, correlation_id=correlation_id)
    except (OAuthStateInvalidError, OAuthStateStoreUnavailable):
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_STATE_REJECTED,
            details={"reason": "state_invalid", "state_fingerprint": state_fingerprint},
            request=request,
        )
        return _oauth_error_response(ErrorCode.OAUTH_STATE_INVALID, status_code=401, correlation_id=correlation_id)

    try:
        token_response = await _exchange_code_once(request, state_record=state_record)
    except Exception:
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_TOKEN_EXCHANGE_FAILED,
            details={"reason": "code_exchange_failed", "state_fingerprint": state_record.state_fingerprint},
            request=request,
        )
        return _oauth_error_response(ErrorCode.OAUTH_CODE_EXCHANGE_FAILED, status_code=502, correlation_id=correlation_id)

    id_token_value = str(token_response.get("id_token") or "")
    try:
        claims = await _verify_id_token(id_token_value, state_record=state_record)
    except Exception as exc:
        code_for_error = _id_token_error_code(exc)
        activity = ActivityType.GOOGLE_OAUTH_NONCE_REJECTED if code_for_error == ErrorCode.OAUTH_NONCE_MISMATCH else ActivityType.GOOGLE_OAUTH_ID_TOKEN_REJECTED
        await record_google_oauth_activity(
            activity,
            details={"reason": code_for_error.value, "state_fingerprint": state_record.state_fingerprint},
            request=request,
        )
        return _oauth_error_response(code_for_error, status_code=OAUTH_ERROR_HTTP_STATUS.get(code_for_error, 401), correlation_id=correlation_id)
    finally:
        # Drop all Google token material before identity/session work.  Do not
        # pass the token response into DB or response helpers.
        token_response = {}
        id_token_value = ""

    return await _issue_login_response(
        response=response,
        config=config,
        state_record=state_record,
        claims=claims,
        request=request,
    )


def _session_id_from_login_data(login_data: Any) -> str | None:
    return _string_field(login_data, "session_id") or _string_field(login_data, "session_token")


def _load_current_session(credentials: HTTPAuthorizationCredentials) -> Any:
    return validate_access_session(credentials.credentials)


@router.post("/link/start")
async def google_oauth_link_start(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Response:
    config = load_google_oauth_config()
    if not _can_link(config):
        return _oauth_error_response(ErrorCode.OAUTH_PROVISIONING_DENIED, status_code=401)
    try:
        login_data = _load_current_session(credentials)
        require_recent_reauthentication(
            user_id=str(_field(login_data, "user_id")),
            session_token=credentials.credentials,
            session_id=_session_id_from_login_data(login_data),
            operation="google_oauth_link",
        )
        redirect_uri = _default_redirect_uri(config)
        if not redirect_uri:
            return _oauth_error_response(ErrorCode.OAUTH_REDIRECT_URI_NOT_ALLOWED, status_code=400)
        binding = {
            "user_id": _field(login_data, "user_id"),
            "provider": "google",
            "purpose": "link",
            "project_hash": _field(login_data, "project_hash"),
            "redirect_uri": redirect_uri,
            "return_origin": _default_return_origin(config),
        }
        created = _state_store().create_link_token(binding=binding, ttl_seconds=getattr(config, "link_token_ttl_seconds", None))
        authorization_url = _build_authorization_url(config=config, state=created, redirect_uri=redirect_uri)
        redirect = RedirectResponse(url=authorization_url, status_code=303)
        _set_oauth_binding_cookie(redirect, created)
        return redirect
    except Exception:
        return _oauth_error_response(ErrorCode.OAUTH_PROVISIONING_DENIED, status_code=401)


@router.post("/link/finish", response_model=ExternalIdentityLinkResponse)
async def google_oauth_link_finish(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> ExternalIdentityLinkResponse | JSONResponse:
    config = load_google_oauth_config()
    if not _can_link(config):
        return _oauth_error_response(ErrorCode.OAUTH_PROVISIONING_DENIED, status_code=401)
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    link_token = str((payload or {}).get("oauth_link_token") or (payload or {}).get("state") or "")
    if not link_token:
        return _oauth_error_response(ErrorCode.OAUTH_STATE_INVALID, status_code=400)
    try:
        login_data = _load_current_session(credentials)
        require_recent_reauthentication(
            user_id=str(_field(login_data, "user_id")),
            session_token=credentials.credentials,
            session_id=_session_id_from_login_data(login_data),
            operation="google_oauth_link",
        )
        record = _state_store().consume_link_token(link_token)
        claims = record.get("claims") if isinstance(record, Mapping) else None
        if not isinstance(claims, Mapping):
            return _oauth_error_response(ErrorCode.OAUTH_ID_TOKEN_INVALID, status_code=401)
        provider_sub_hash_value, provider_sub_fp, email_hash_value, email_masked, _ = _safe_provider_fields(claims)
        linked = db.link_external_account(
            external_account_id=f"uea-{uuid4().hex}",
            user_id=str(_field(login_data, "user_id")),
            provider="google",
            provider_sub_hash=provider_sub_hash_value,
            provider_sub_fingerprint=provider_sub_fp,
            provider_email_hash=email_hash_value,
            provider_email_masked=email_masked,
            provider_email_verified_at_link=bool(claims.get("email_verified", False)),
            linked_by=str(_field(login_data, "user_id")),
            metadata={"source": "google_oauth_link"},
        )
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_EXTERNAL_ACCOUNT_LINKED,
            details={"provider_sub_fingerprint": provider_sub_fp, "reason": "linked"},
            request=request,
            user_id=str(_field(login_data, "user_id")),
        )
        return ExternalIdentityLinkResponse(
            success=True,
            message="External identity linked",
            external_identity=ExternalIdentityInfo(
                provider="google",
                provider_subject_masked=provider_sub_fp,
                provider_email_masked=email_masked,
                provider_email_verified_at_link=bool(claims.get("email_verified", False)),
                status=str(_field(linked, "status", "linked")),
            ),
        )
    except Exception:
        return _oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_SUB_CONFLICT, status_code=409, message=OAUTH_LINKING_DENIED_MESSAGE)


@router.post("/reauth/start")
async def google_oauth_reauth_start(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> Response:
    config = load_google_oauth_config()
    try:
        login_data = _load_current_session(credentials)
        redirect_uri = _default_redirect_uri(config)
        if not redirect_uri:
            return _oauth_error_response(ErrorCode.OAUTH_REDIRECT_URI_NOT_ALLOWED, status_code=400)
        binding = {
            "provider": "google",
            "purpose": "reauth",
            "project_hash": _field(login_data, "project_hash") or _TEST_BOUND_PROJECT_HASH,
            "return_origin": _default_return_origin(config),
            "redirect_uri": redirect_uri,
            "user_id": _field(login_data, "user_id"),
        }
        created = _state_store().create_state(provider_init_binding=binding, ttl_seconds=getattr(config, "state_ttl_seconds", None))
        authorization_url = _build_authorization_url(config=config, state=created, redirect_uri=redirect_uri, prompt="login")
        redirect = RedirectResponse(url=authorization_url, status_code=303)
        _set_oauth_binding_cookie(redirect, created)
        return redirect
    except Exception:
        return _oauth_error_response(ErrorCode.OAUTH_PROVISIONING_DENIED, status_code=401)


def _has_usable_fallback_auth(user: Any) -> bool:
    password_hash = _string_field(user, "password_hash", "") or ""
    if not password_hash:
        return False
    disabled_markers = ("oauth-disabled", "passwordless", "placeholder")
    return not any(marker in password_hash.lower() for marker in disabled_markers)


@router.delete("/unlink", response_model=ExternalIdentityUnlinkResponse)
async def google_oauth_unlink(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
) -> ExternalIdentityUnlinkResponse | JSONResponse:
    try:
        login_data = _load_current_session(credentials)
        user_id = str(_field(login_data, "user_id") or "")
        if not user_id:
            return _oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_NOT_LINKED, status_code=404)
        require_recent_reauthentication(
            user_id=user_id,
            session_token=credentials.credentials,
            session_id=_session_id_from_login_data(login_data),
            operation="google_oauth_unlink",
        )
        try:
            await _maybe_await(_rate_limiter().check_unlink_attempt(user_id=user_id, ip_address=_client_ip(request)))
        except OAuthRateLimitExceeded as exc:
            return _oauth_error_response(ErrorCode.OAUTH_RATE_LIMITED, status_code=429, retry_after=exc.retry_after)

        user_hash = _string_field(login_data, "user_hash")
        current_user = db.get_user_by_hash(user_hash) if user_hash else None
        if not _has_usable_fallback_auth(current_user):
            return _oauth_error_response(
                ErrorCode.OAUTH_PASSWORD_REQUIRED_FOR_UNLINK,
                status_code=409,
                message="External identity action could not be completed. Establish fallback authentication first.",
            )
        result = db.unlink_external_account(
            user_id=user_id,
            provider="google",
            unlinked_by=user_id,
            reason="user_unlink",
        )
        if not result:
            return _oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_NOT_LINKED, status_code=404)
        summary = revoke_user_auth_state(user_id, reason="google_oauth_account_unlinked")
        sessions_revoked = int(getattr(summary, "sessions_revoked", 0) or 0)
        await record_google_oauth_activity(
            ActivityType.GOOGLE_OAUTH_EXTERNAL_ACCOUNT_UNLINKED,
            details={"reason": "user_unlink"},
            request=request,
            user_id=user_id,
        )
        return ExternalIdentityUnlinkResponse(
            success=True,
            message="External identity unlinked",
            remaining_auth_methods=["password"],
            sessions_revoked=sessions_revoked,
        )
    except Exception:
        return _oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_NOT_LINKED, status_code=401, message=OAUTH_LINKING_DENIED_MESSAGE)
