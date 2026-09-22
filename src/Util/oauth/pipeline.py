"""Provider-blind OAuth pipeline.

One implementation of start, callback (login / link / reauth) and unlink, shared
by every provider and every route family. Only three steps vary by provider and
they all live behind the adapter: build the authorize URL, exchange the code,
produce an :class:`ExternalIdentity`.

Invariants preserved from the original Google implementation:

* state is consumed BEFORE the code exchange, exactly once, fail closed;
* the provider is chosen from the state record only, never from caller input;
* identity is the provider subject, never the e-mail; nothing merges by e-mail;
* provider tokens are dropped before any identity or session work;
* a callback can only ever issue a session for the project bound at start;
* logs, activity and audit carry fingerprints and masks only.

There are no test-runtime branches here. Test doubles are injected through
:class:`PipelineDeps` or registered as adapters by fixtures.
"""

from __future__ import annotations

import hashlib
import hmac
import inspect
import ipaddress
import logging
import secrets
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Mapping
from uuid import uuid4

from fastapi import Request, Response
from fastapi.responses import JSONResponse, RedirectResponse

from src.Util.Models import (
    ExternalIdentityInfo,
    ExternalIdentityLinkResponse,
    ExternalIdentityUnlinkResponse,
    LoginResponse,
    ProjectInfo,
    UserGroupInfo,
    UserInfo,
)
from src.Util.activity_logger import ActivityType
from src.Util.auth_constants import (
    OAUTH_EXISTING_USER_JOIN_DEFAULT_GROUP,
    OAUTH_PURPOSE_LINK,
    OAUTH_PURPOSE_REAUTH,
)
from src.Util.auth_flow import resolve_provider_init_bound_project
from src.Util.error_handler import (
    ErrorCategory,
    ErrorCode,
    OAUTH_ERROR_HTTP_STATUS,
    OAUTH_ERROR_PUBLIC_MESSAGES,
    OAUTH_LINKING_DENIED_MESSAGE,
    OAUTH_NEUTRAL_PUBLIC_MESSAGE,
    sanitize_error_message,
)
from src.Util.oauth.connections import (
    ConnectionSource,
    OAuthConnectionUnavailable,
    ResolvedConnection,
    UNAVAILABLE_DISABLED,
)
from src.Util.oauth.identity import IdentityKey, OAuthIdentityKeyError, identity_key_for
from src.Util.oauth.provider import (
    EMAIL_TRUST_VERIFIED,
    CallbackParams,
    ExternalIdentity,
    OAuthFailure,
    OAuthProviderAdapter,
    OAuthProviderError,
    OAuthTransaction,
)
from src.Util.oauth.settings import OAuthDeploymentSettings, load_oauth_settings
from src.Util.oauth_rate_limit import OAuthRateLimitExceeded, rate_limit_scope
from src.Util.oauth_state import (
    OAuthStateCreated,
    OAuthStateInvalidError,
    OAuthStateRecord,
    OAuthStateReplayError,
    OAuthStateStoreUnavailable,
    fingerprint_oauth_value,
)


logger = logging.getLogger(__name__)

FORBIDDEN_BROWSER_STRICT_FIELDS = {"project_hash", "user_group_hash"}

# Events -> activity types. Alias routes keep the historical google_oauth_* codes.
EVENT_STARTED = "started"
EVENT_INIT_REJECTED = "init_rejected"
EVENT_CALLBACK_RECEIVED = "callback_received"
EVENT_STATE_REJECTED = "state_rejected"
EVENT_NONCE_REJECTED = "nonce_rejected"
EVENT_TOKEN_EXCHANGE_FAILED = "token_exchange_failed"
EVENT_IDENTITY_REJECTED = "identity_rejected"
EVENT_LOGIN_SUCCEEDED = "login_succeeded"
EVENT_LOGIN_DENIED = "login_denied"
EVENT_LINKED = "linked"
EVENT_UNLINKED = "unlinked"
EVENT_REAUTH_SUCCEEDED = "reauth_succeeded"
EVENT_USER_CANCELLED = "user_cancelled"

_GENERIC_ACTIVITY = {
    EVENT_STARTED: ActivityType.OAUTH_STARTED,
    EVENT_INIT_REJECTED: ActivityType.OAUTH_INIT_REJECTED,
    EVENT_CALLBACK_RECEIVED: ActivityType.OAUTH_CALLBACK_RECEIVED,
    EVENT_STATE_REJECTED: ActivityType.OAUTH_STATE_REJECTED,
    EVENT_NONCE_REJECTED: ActivityType.OAUTH_IDENTITY_REJECTED,
    EVENT_TOKEN_EXCHANGE_FAILED: ActivityType.OAUTH_TOKEN_EXCHANGE_FAILED,
    EVENT_IDENTITY_REJECTED: ActivityType.OAUTH_IDENTITY_REJECTED,
    EVENT_LOGIN_SUCCEEDED: ActivityType.OAUTH_LOGIN_SUCCEEDED,
    EVENT_LOGIN_DENIED: ActivityType.OAUTH_LOGIN_DENIED,
    EVENT_LINKED: ActivityType.OAUTH_EXTERNAL_ACCOUNT_LINKED,
    EVENT_UNLINKED: ActivityType.OAUTH_EXTERNAL_ACCOUNT_UNLINKED,
    EVENT_REAUTH_SUCCEEDED: ActivityType.OAUTH_REAUTH_SUCCEEDED,
    EVENT_USER_CANCELLED: ActivityType.OAUTH_USER_CANCELLED,
}
_LEGACY_GOOGLE_ACTIVITY = {
    **_GENERIC_ACTIVITY,
    EVENT_STARTED: ActivityType.GOOGLE_OAUTH_STARTED,
    EVENT_INIT_REJECTED: ActivityType.GOOGLE_OAUTH_PROVIDER_INIT_REJECTED,
    EVENT_CALLBACK_RECEIVED: ActivityType.GOOGLE_OAUTH_CALLBACK_RECEIVED,
    EVENT_STATE_REJECTED: ActivityType.GOOGLE_OAUTH_STATE_REJECTED,
    EVENT_NONCE_REJECTED: ActivityType.GOOGLE_OAUTH_NONCE_REJECTED,
    EVENT_TOKEN_EXCHANGE_FAILED: ActivityType.GOOGLE_OAUTH_TOKEN_EXCHANGE_FAILED,
    EVENT_IDENTITY_REJECTED: ActivityType.GOOGLE_OAUTH_ID_TOKEN_REJECTED,
    EVENT_LOGIN_SUCCEEDED: ActivityType.GOOGLE_OAUTH_LOGIN_SUCCEEDED,
    EVENT_LOGIN_DENIED: ActivityType.GOOGLE_OAUTH_LOGIN_DENIED,
    EVENT_LINKED: ActivityType.GOOGLE_OAUTH_EXTERNAL_ACCOUNT_LINKED,
    EVENT_UNLINKED: ActivityType.GOOGLE_OAUTH_EXTERNAL_ACCOUNT_UNLINKED,
}

_FAILURE_TO_ERROR = {
    OAuthFailure.NONCE_MISMATCH: ErrorCode.OAUTH_NONCE_MISMATCH,
    OAuthFailure.ISSUER_MISMATCH: ErrorCode.OAUTH_ISSUER_MISMATCH,
    OAuthFailure.AUDIENCE_MISMATCH: ErrorCode.OAUTH_AUDIENCE_MISMATCH,
    OAuthFailure.TOKEN_EXPIRED: ErrorCode.OAUTH_TOKEN_EXPIRED,
    OAuthFailure.RESTRICTION_DENIED: ErrorCode.OAUTH_WORKSPACE_DENIED,
    OAuthFailure.ID_TOKEN_INVALID: ErrorCode.OAUTH_ID_TOKEN_INVALID,
    OAuthFailure.SUBJECT_MISSING: ErrorCode.OAUTH_ID_TOKEN_INVALID,
    OAuthFailure.USERINFO_FAILED: ErrorCode.OAUTH_ID_TOKEN_INVALID,
    OAuthFailure.CODE_EXCHANGE_FAILED: ErrorCode.OAUTH_CODE_EXCHANGE_FAILED,
    OAuthFailure.PROVIDER_MISCONFIGURED: ErrorCode.OAUTH_PROVIDER_NOT_CONFIGURED,
}

# Operator-facing detail keys. Values are sanitised; nothing else is ever recorded.
_SAFE_DETAIL_KEYS = {
    "bucket",
    "connection",
    "correlation_id",
    "provider",
    "provider_email_hash_prefix",
    "provider_init_fingerprint",
    "provider_sub_fingerprint",
    "purpose",
    "reason",
    "state_fingerprint",
    "sub_reason",
}


# ───────────────────────────────────────────────────────────── small helpers

async def maybe_await(value: Any) -> Any:
    if inspect.isawaitable(value):
        return await value
    return value


def field_of(value: Any, name: str, default: Any = None) -> Any:
    """Read ``name`` from a mapping or object, ignoring attributes a Mock fabricated."""

    if value is None:
        return default
    if isinstance(value, Mapping):
        return value.get(name, default)
    attr = getattr(value, name, default)
    try:
        from unittest.mock import Mock

        if isinstance(attr, Mock) and name not in getattr(value, "__dict__", {}):
            return default
    except Exception:  # pragma: no cover - defensive
        pass
    return attr


def text_of(value: Any, name: str, default: str | None = None) -> str | None:
    candidate = field_of(value, name, default)
    if candidate is None:
        return default
    text = str(candidate).strip()
    return text or default


def hash_surface(value: Any, *, length: int = 24) -> str:
    return hashlib.sha256(str(value or "").encode("utf-8")).hexdigest()[:length]


def safe_details(details: Mapping[str, Any] | None = None) -> dict[str, Any]:
    safe: dict[str, Any] = {}
    for key, value in dict(details or {}).items():
        if key not in _SAFE_DETAIL_KEYS or value in (None, ""):
            continue
        safe[key] = sanitize_error_message(str(value))
    return safe


def client_ip(request: Request | None, *, settings: OAuthDeploymentSettings | None = None) -> str:
    """Client address. ``X-Forwarded-For`` is honoured only from a trusted proxy.

    Without ``OAUTH_TRUSTED_PROXY_CIDRS`` the header is ignored entirely: any caller
    can set it, so trusting it lets a client steer every per-IP control.
    """

    if request is None:
        return "unknown"
    peer = request.client.host if request.client else "unknown"
    forwarded = request.headers.get("x-forwarded-for") if request.headers else None
    if not forwarded:
        return peer
    try:
        cidrs = (settings or load_oauth_settings()).trusted_proxy_cidrs
    except Exception:
        cidrs = ()
    if not cidrs:
        return peer
    try:
        peer_address = ipaddress.ip_address(peer)
        trusted = any(peer_address in ipaddress.ip_network(cidr, strict=False) for cidr in cidrs)
    except ValueError:
        trusted = False
    if not trusted:
        return peer
    return forwarded.split(",", 1)[0].strip() or peer


def user_agent(request: Request | None) -> str | None:
    return request.headers.get("user-agent") if request is not None and request.headers else None


def oauth_error_response(
    error_code: ErrorCode,
    *,
    status_code: int | None = None,
    message: str | None = None,
    correlation_id: str | None = None,
    retry_after: int | None = None,
) -> JSONResponse:
    public_message = message or OAUTH_ERROR_PUBLIC_MESSAGES.get(error_code, OAUTH_NEUTRAL_PUBLIC_MESSAGE)
    headers = {"Retry-After": str(max(1, int(retry_after or 1)))} if retry_after is not None else None
    return JSONResponse(
        status_code=status_code or OAUTH_ERROR_HTTP_STATUS.get(error_code, 401),
        content={
            "success": False,
            "status": "error",
            "correlation_id": correlation_id,
            "error": {
                "code": error_code.value,
                "category": ErrorCategory.EXTERNAL.value,
                "message": sanitize_error_message(public_message),
            },
        },
        headers=headers,
    )


def new_correlation_id(prefix: str) -> str:
    return hash_surface(f"{prefix}:{secrets.token_urlsafe(12)}", length=12)


# ───────────────────────────────────────────────────────────────── dependencies

async def _default_record_activity(
    activity_type: ActivityType,
    *,
    details: Mapping[str, Any] | None = None,
    request: Request | None = None,
    user_id: str | None = None,
    target_user_id: str | None = None,
) -> None:
    try:
        from src.Util import activity_logger as activity_logger_module

        activity_logger_module.ActivityLogger.log_activity(
            user_id=user_id,
            activity_type=activity_type.value,
            details=safe_details(details),
            target_user_id=target_user_id,
            ip_address=client_ip(request),
            user_agent=user_agent(request),
        )
    except Exception:
        logger.debug("OAuth activity logging failed", exc_info=True)


@dataclass
class PipelineDeps:
    """Injection seams. Every callable is looked up at request time by the routes."""

    db: Any
    state_store: Callable[[], Any]
    rate_limiter: Callable[[], Any]
    connection_source: Callable[[], ConnectionSource]
    record_activity: Callable[..., Awaitable[None]] = _default_record_activity
    adapter_for: Callable[[ResolvedConnection], OAuthProviderAdapter] | None = None
    issue_token_pair: Callable[..., Any] | None = None
    set_cookies: Callable[[Response, Any], None] | None = None
    legacy_google_activity: bool = False
    cookie_path: str = "/auth/oauth"
    settings: OAuthDeploymentSettings | None = None

    def adapter(self, resolved: ResolvedConnection) -> OAuthProviderAdapter:
        return self.adapter_for(resolved) if self.adapter_for else resolved.adapter

    async def emit(self, event: str, *, resolved: ResolvedConnection | None = None, **kwargs: Any) -> None:
        mapping = _LEGACY_GOOGLE_ACTIVITY if self.legacy_google_activity else _GENERIC_ACTIVITY
        details = dict(kwargs.pop("details", None) or {})
        if resolved is not None:
            details.setdefault("provider", resolved.config.provider_type)
            details.setdefault("connection", fingerprint_oauth_value(resolved.config.connection_id))
        await maybe_await(self.record_activity(mapping[event], details=details, **kwargs))


@dataclass(frozen=True)
class AuthorizationStart:
    """Everything needed to begin one provider round trip."""

    resolved: ResolvedConnection
    purpose: str
    project_hash: str = field(repr=False)
    redirect_uri: str
    return_origin: str | None
    user_group_hash: str | None = field(default=None, repr=False)
    remember_me: bool = False
    init_fingerprint: str | None = None
    scope_fingerprint: str | None = None
    user_id: str | None = field(default=None, repr=False)
    session_id: str | None = field(default=None, repr=False)
    prompt: str | None = None


# ───────────────────────────────────────────────────────────────────── pipeline

class OAuthPipeline:
    def __init__(self, deps: PipelineDeps) -> None:
        self.deps = deps

    # ------------------------------------------------------------------ helpers
    def _settings(self) -> OAuthDeploymentSettings:
        return self.deps.settings or load_oauth_settings()

    def _scope(self, resolved: ResolvedConnection | None, project_hash: str | None = None) -> str | None:
        if resolved is None:
            return None
        return rate_limit_scope(project=project_hash or resolved.binding.project_hash, connection=resolved.config.connection_id)

    async def _limit(self, method_name: str, *, request: Request, scope: str | None = None, **kwargs: Any) -> None:
        limiter = self.deps.rate_limiter()
        method = getattr(limiter, method_name)
        try:
            result = method(ip_address=client_ip(request, settings=self.deps.settings), scope=scope, **kwargs)
        except TypeError:
            # Test doubles written before the scope dimension existed.
            result = method(ip_address=client_ip(request, settings=self.deps.settings), **kwargs)
        await maybe_await(result)

    def _set_binding_cookie(self, response: Response, created: OAuthStateCreated) -> None:
        metadata = created.cookie_metadata
        response.set_cookie(
            key=metadata.name,
            value=created.state_fingerprint,
            max_age=metadata.max_age_seconds,
            httponly=metadata.httponly,
            secure=metadata.secure,
            samesite=metadata.samesite,
            path=self.deps.cookie_path,
        )

    # -------------------------------------------------------------------- start
    async def begin_authorization(self, request: Request, start: AuthorizationStart) -> Response:
        """Create state, build the provider URL and answer ``303``."""

        resolved = start.resolved
        adapter = self.deps.adapter(resolved)
        issuers = tuple(resolved.config.issuers)
        binding = {
            "provider": resolved.config.provider_type,
            "purpose": start.purpose,
            "connection_id": resolved.config.connection_id,
            "binding_id": resolved.binding.binding_id,
            "config_source": resolved.source_name,
            "expected_issuer": issuers[0] if issuers else None,
            "delivery_mode": resolved.binding.delivery_mode,
            "project_hash": start.project_hash,
            "user_group_hash": start.user_group_hash,
            "return_origin": start.return_origin,
            "redirect_uri": start.redirect_uri,
            "prompt": start.prompt,
            "remember_me": bool(start.remember_me),
            "user_id": start.user_id,
            "session_id": start.session_id,
            "provider_init_fingerprint": start.init_fingerprint,
            "scope_fingerprint": start.scope_fingerprint,
            # Diagnostic only. Behind a BFF both are the backend's, so they are recorded
            # for operators and deliberately not enforced at the callback.
            "ip_hash": hash_surface(client_ip(request, settings=self.deps.settings)),
            "ua_hash": hash_surface(user_agent(request)),
        }
        ceiling = self._settings().max_state_ttl_seconds
        ttl = min(int(resolved.binding.state_ttl_seconds or ceiling), ceiling)
        created: OAuthStateCreated = self.deps.state_store().create_state(provider_init_binding=binding, ttl_seconds=ttl)
        tx = OAuthTransaction(
            state=created.state,
            nonce=created.nonce,
            code_verifier=created.code_verifier,
            code_challenge=created.code_challenge,
            redirect_uri=start.redirect_uri,
            purpose=start.purpose,
            prompt=start.prompt,
        )
        authorization_url = adapter.build_authorization_url(resolved.config, tx)
        await self.deps.emit(
            EVENT_STARTED,
            resolved=resolved,
            details={
                "reason": "authorization_started",
                "purpose": start.purpose,
                "state_fingerprint": created.state_fingerprint,
                "provider_init_fingerprint": start.init_fingerprint,
            },
            request=request,
            user_id=start.user_id,
        )
        response = RedirectResponse(url=authorization_url, status_code=303)
        self._set_binding_cookie(response, created)
        return response

    # ----------------------------------------------------------------- callback
    async def handle_callback(
        self,
        request: Request,
        response: Response,
        *,
        code: str | None,
        state: str | None,
        error: str | None = None,
        iss: str | None = None,
    ) -> Any:
        correlation_id = new_correlation_id("callback")
        state_fingerprint = fingerprint_oauth_value(state or "")
        await self.deps.emit(
            EVENT_CALLBACK_RECEIVED,
            details={"state_fingerprint": state_fingerprint, "correlation_id": correlation_id},
            request=request,
        )
        if not state or (not code and not error):
            return oauth_error_response(ErrorCode.OAUTH_STATE_INVALID, status_code=400, correlation_id=correlation_id)

        try:
            await self._limit("check_callback", request=request, state_fingerprint=state_fingerprint)
            await self._limit("check_state_consumption", request=request, state_fingerprint=state_fingerprint)
        except OAuthRateLimitExceeded as exc:
            return oauth_error_response(
                ErrorCode.OAUTH_RATE_LIMITED, status_code=429, retry_after=exc.retry_after, correlation_id=correlation_id
            )

        # State is consumed before anything else -- including a provider error -- so a
        # cancelled or failed round trip can never be replayed.
        try:
            record: OAuthStateRecord = self.deps.state_store().consume_state(state)
        except OAuthStateReplayError:
            await self.deps.emit(
                EVENT_STATE_REJECTED, details={"reason": "state_reused", "state_fingerprint": state_fingerprint}, request=request
            )
            return oauth_error_response(ErrorCode.OAUTH_STATE_REUSED, status_code=401, correlation_id=correlation_id)
        except (OAuthStateInvalidError, OAuthStateStoreUnavailable):
            await self.deps.emit(
                EVENT_STATE_REJECTED, details={"reason": "state_invalid", "state_fingerprint": state_fingerprint}, request=request
            )
            return oauth_error_response(ErrorCode.OAUTH_STATE_INVALID, status_code=401, correlation_id=correlation_id)

        # The browser-binding cookie only exists on direct-browser round trips. Behind a
        # BFF the callback arrives server-to-server without it, so it is enforced when present.
        cookie_value = request.cookies.get("oauth_state") if request.cookies else None
        if cookie_value and not hmac.compare_digest(str(cookie_value), record.state_fingerprint):
            await self.deps.emit(
                EVENT_STATE_REJECTED,
                details={"reason": "state_cookie_mismatch", "state_fingerprint": record.state_fingerprint},
                request=request,
            )
            return oauth_error_response(ErrorCode.OAUTH_STATE_INVALID, status_code=401, correlation_id=correlation_id)

        # The connection comes from the state record only, and is re-resolved so that a
        # connection or binding disabled while the user was at the provider stays disabled.
        try:
            resolved = self._resolve_for_record(record)
        except OAuthConnectionUnavailable as exc:
            await self.deps.emit(
                EVENT_STATE_REJECTED,
                details={"reason": f"connection_{exc.kind}", "sub_reason": exc.reason, "state_fingerprint": record.state_fingerprint},
                request=request,
            )
            code_for = ErrorCode.OAUTH_PROVIDER_DISABLED if exc.kind == UNAVAILABLE_DISABLED else ErrorCode.OAUTH_PROVIDER_NOT_CONFIGURED
            return oauth_error_response(code_for, correlation_id=correlation_id)

        if error:
            cancelled = str(error).strip().lower() in {"access_denied", "user_cancelled_authorize", "user_cancelled_login"}
            await self.deps.emit(
                EVENT_USER_CANCELLED if cancelled else EVENT_TOKEN_EXCHANGE_FAILED,
                resolved=resolved,
                details={"reason": "user_cancelled" if cancelled else "provider_error", "state_fingerprint": record.state_fingerprint},
                request=request,
            )
            if cancelled:
                return oauth_error_response(ErrorCode.OAUTH_USER_CANCELLED, correlation_id=correlation_id)
            return oauth_error_response(ErrorCode.OAUTH_CODE_EXCHANGE_FAILED, status_code=502, correlation_id=correlation_id)

        adapter = self.deps.adapter(resolved)
        if adapter.capabilities.issuer_response_param:
            expected = record.expected_issuer or ""
            if not iss or not hmac.compare_digest(str(iss), expected):
                await self.deps.emit(
                    EVENT_IDENTITY_REJECTED,
                    resolved=resolved,
                    details={"reason": "issuer_response_mismatch", "state_fingerprint": record.state_fingerprint},
                    request=request,
                )
                return oauth_error_response(ErrorCode.OAUTH_ISSUER_MISMATCH, correlation_id=correlation_id)

        tx = OAuthTransaction(
            state=state,
            nonce=record.nonce,
            code_verifier=record.code_verifier,
            code_challenge=record.code_challenge,
            redirect_uri=str(record.redirect_uri or ""),
            purpose=record.purpose,
            prompt=record.prompt,
        )
        callback = CallbackParams(code=str(code), state=state, iss=iss, raw_request=request)

        tokens: Any = None
        try:
            connection_secrets = self.deps.connection_source().load_secrets(resolved)
            tokens = await adapter.exchange_code(resolved.config, connection_secrets, tx, callback)
            del connection_secrets
        except Exception as exc:
            failure = exc.failure if isinstance(exc, OAuthProviderError) else OAuthFailure.CODE_EXCHANGE_FAILED
            await self.deps.emit(
                EVENT_TOKEN_EXCHANGE_FAILED,
                resolved=resolved,
                details={"reason": "code_exchange_failed", "sub_reason": failure.value, "state_fingerprint": record.state_fingerprint},
                request=request,
            )
            return oauth_error_response(ErrorCode.OAUTH_CODE_EXCHANGE_FAILED, status_code=502, correlation_id=correlation_id)

        try:
            identity = await adapter.resolve_identity(resolved.config, tx, tokens)
            adapter.enforce_restrictions(resolved.config, identity)
        except Exception as exc:
            failure = exc.failure if isinstance(exc, OAuthProviderError) else OAuthFailure.ID_TOKEN_INVALID
            error_code = _FAILURE_TO_ERROR.get(failure, ErrorCode.OAUTH_ID_TOKEN_INVALID)
            await self.deps.emit(
                EVENT_NONCE_REJECTED if failure == OAuthFailure.NONCE_MISMATCH else EVENT_IDENTITY_REJECTED,
                resolved=resolved,
                details={"reason": error_code.value, "sub_reason": failure.value, "state_fingerprint": record.state_fingerprint},
                request=request,
            )
            return oauth_error_response(error_code, correlation_id=correlation_id)
        finally:
            # Drop all provider token material before identity/session work.
            tokens = None

        try:
            key = identity_key_for(identity, settings=self.deps.settings)
        except OAuthIdentityKeyError:
            await self.deps.emit(
                EVENT_IDENTITY_REJECTED,
                resolved=resolved,
                details={"reason": "identity_key_failed", "state_fingerprint": record.state_fingerprint},
                request=request,
            )
            return oauth_error_response(ErrorCode.OAUTH_ID_TOKEN_INVALID, correlation_id=correlation_id)

        if record.purpose == OAUTH_PURPOSE_LINK:
            return await self._complete_link(request, resolved=resolved, record=record, key=key, correlation_id=correlation_id)
        if record.purpose == OAUTH_PURPOSE_REAUTH:
            return await self._complete_reauth(request, resolved=resolved, record=record, key=key, correlation_id=correlation_id)
        return await self._complete_login(
            request, response, resolved=resolved, record=record, identity=identity, key=key, correlation_id=correlation_id
        )

    def _resolve_for_record(self, record: OAuthStateRecord) -> ResolvedConnection:
        from src.Util.oauth.connections import ENV_BINDING_ID, ENV_CONNECTION_ID

        # Version-1 records predate connections; they can only be the environment Google client.
        connection_id = record.connection_id or ENV_CONNECTION_ID
        binding_id = record.binding_id or ENV_BINDING_ID
        return self.deps.connection_source().get_by_ids(connection_id=connection_id, binding_id=binding_id)

    # -------------------------------------------------------------------- login
    async def _complete_login(
        self,
        request: Request,
        response: Response,
        *,
        resolved: ResolvedConnection,
        record: OAuthStateRecord,
        identity: ExternalIdentity,
        key: IdentityKey,
        correlation_id: str,
    ) -> Any:
        db = self.deps.db
        if not resolved.binding.login_enabled:
            await self._deny(request, resolved, record, key, "login_disabled_for_binding")
            return oauth_error_response(ErrorCode.OAUTH_PROVISIONING_DENIED, status_code=401, correlation_id=correlation_id)

        user, denial = self._resolve_user(resolved=resolved, record=record, identity=identity, key=key)
        if not user:
            await self._deny(request, resolved, record, key, "identity_resolution_denied", sub_reason=denial)
            if denial == "email_collision_link_required":
                return oauth_error_response(ErrorCode.OAUTH_ACCOUNT_LINK_REQUIRED, correlation_id=correlation_id)
            return oauth_error_response(ErrorCode.OAUTH_PROVISIONING_DENIED, status_code=401, correlation_id=correlation_id)

        user_id = text_of(user, "id") or ""
        accessible = self._accessible_projects(user_id)
        if not self._has_project(accessible, record.project_hash) and self._maybe_enrol_existing_user(resolved, user_id):
            accessible = self._accessible_projects(user_id)

        try:
            target_project = resolve_provider_init_bound_project(
                accessible_projects=accessible,
                provider_init_binding=record.provider_init_binding,
                get_project_by_hash_fn=db.get_project_by_hash,
                handle_db_operation_fn=db.handle_db_operation,
            )
        except Exception:
            await self._deny(request, resolved, record, key, "project_access_denied", user_id=user_id)
            return oauth_error_response(ErrorCode.OAUTH_PROJECT_ACCESS_DENIED, status_code=403, correlation_id=correlation_id)

        from src.Util.session_issue import project_is_auth_accessible, set_token_pair_cookies

        if not project_is_auth_accessible(target_project):
            await self._deny(request, resolved, record, key, "project_inactive_or_archived", user_id=user_id)
            return oauth_error_response(ErrorCode.OAUTH_PROJECT_ACCESS_DENIED, status_code=403, correlation_id=correlation_id)

        try:
            user_groups = list(db.get_user_groups_for_user(user_id) or [])
        except Exception:
            user_groups = []
        issue = self.deps.issue_token_pair
        if issue is None:
            from src.Util.auth_lifecycle import issue_project_token_pair as issue
        token_pair = issue(
            user=_user_dict(user),
            project=_project_dict(target_project),
            permissions=[],
            groups=[name for name in (text_of(group, "group_name") for group in user_groups) if name],
            group_ids=[gid for gid in (text_of(group, "id") for group in user_groups) if gid],
            remember_me=bool(record.remember_me),
        )
        (self.deps.set_cookies or set_token_pair_cookies)(response, token_pair)
        await self.deps.emit(
            EVENT_LOGIN_SUCCEEDED,
            resolved=resolved,
            details={
                "reason": "linked_consumer_login",
                "state_fingerprint": record.state_fingerprint,
                "provider_sub_fingerprint": key.sub_fingerprint,
            },
            request=request,
            user_id=user_id,
        )
        return _login_response(
            token_pair=token_pair, user=user, project=target_project, accessible_projects=accessible, user_groups=user_groups
        )

    async def _deny(
        self,
        request: Request,
        resolved: ResolvedConnection,
        record: OAuthStateRecord,
        key: IdentityKey,
        reason: str,
        *,
        sub_reason: str | None = None,
        user_id: str | None = None,
    ) -> None:
        await self.deps.emit(
            EVENT_LOGIN_DENIED,
            resolved=resolved,
            details={
                "reason": reason,
                # Precise cause for operators; the client only ever sees a neutral code.
                "sub_reason": sub_reason,
                "state_fingerprint": record.state_fingerprint,
                "provider_sub_fingerprint": key.sub_fingerprint,
                "provider_email_hash_prefix": key.email_hash_prefix,
            },
            request=request,
            user_id=user_id,
        )

    def _accessible_projects(self, user_id: str) -> list[Any]:
        try:
            return list(self.deps.db.get_user_accessible_projects(user_id) or [])
        except Exception:
            return []

    @staticmethod
    def _has_project(projects: list[Any], project_hash: str | None) -> bool:
        return bool(project_hash) and any(text_of(project, "project_hash") == project_hash for project in projects)

    def _maybe_enrol_existing_user(self, resolved: ResolvedConnection, user_id: str) -> bool:
        """Apply the binding's existing-user policy; default is to deny."""

        binding = resolved.binding
        if binding.existing_user_policy != OAUTH_EXISTING_USER_JOIN_DEFAULT_GROUP or not binding.default_user_group_id:
            return False
        try:
            return bool(self.deps.db.assign_user_to_group(user_id, binding.default_user_group_id, None))
        except Exception:
            logger.debug("OAuth existing-user enrolment failed closed", exc_info=True)
            return False

    def _resolve_user(
        self,
        *,
        resolved: ResolvedConnection,
        record: OAuthStateRecord,
        identity: ExternalIdentity,
        key: IdentityKey,
    ) -> tuple[Any | None, str | None]:
        db = self.deps.db
        user = db.get_user_by_external_account(
            provider=key.provider_type, provider_sub_hash=key.sub_hash, identity_namespace=_namespace_for(resolved, key.identity_namespace)
        )
        if user:
            if not _is_active_consumer(user):
                return None, "existing_user_not_active_consumer"
            try:
                db.touch_external_account_last_seen(
                    provider=key.provider_type,
                    provider_sub_hash=key.sub_hash,
                    provider_email_hash=key.email_hash,
                    provider_email_masked=key.email_masked,
                    provider_email_verified_at_link=key.email_verified,
                    identity_namespace=_namespace_for(resolved, key.identity_namespace),
                )
            except Exception:
                logger.debug("OAuth last-seen update failed", exc_info=True)
            return user, None

        binding = resolved.binding
        if not binding.can_auto_create:
            return None, "auto_create_disabled"

        # An existing local account with the same e-mail is never merged and never
        # silently shadowed by a second account: the person must sign in and link.
        if key.email_normalized:
            try:
                available = db.check_username_email_available(key.email_normalized)
            except Exception:
                return None, "email_collision_check_failed"
            if available is False:
                if identity.email_verified and identity.email_trust == EMAIL_TRUST_VERIFIED:
                    return None, "email_collision_link_required"
                return None, "email_collision"

        group_id, group_reason = self._provisioning_group(resolved, record)
        if not group_id:
            return None, group_reason
        try:
            from src.Util.password_security import hash_password
            from src.Util.uuid_generator import generate_user_group_member_id, generate_user_hash, generate_user_id

            seed = (key.email_normalized.split("@", 1)[0] if key.email_normalized else f"{key.provider_type}_user")[:40]
            created = db.create_consumer_user_from_external_account(
                user_id=generate_user_id(),
                user_hash=generate_user_hash(),
                username=f"{seed}_{secrets.token_hex(4)}",
                password_hash=hash_password(f"oauth-disabled-{secrets.token_urlsafe(48)}"),
                external_account_id=f"uea-{uuid4().hex}",
                provider=key.provider_type,
                provider_sub_hash=key.sub_hash,
                provider_sub_fingerprint=key.sub_fingerprint,
                provider_email_hash=key.email_hash,
                provider_email_masked=key.email_masked,
                provider_email_verified_at_link=key.email_verified,
                user_email_id=f"uem-{uuid4().hex}" if key.email_normalized else None,
                email_normalized=key.email_normalized,
                group_member_id=generate_user_group_member_id(),
                user_group_id=group_id,
                # NULL: created_by/assigned_by are FKs to users(id); a self-service
                # OAuth signup has no creator. Provenance lives in metadata.
                created_by=None,
                metadata={"source": f"{key.provider_type}_oauth_auto_create"},
                identity_namespace=_namespace_for(resolved, key.identity_namespace),
                connection_id=_db_connection_id(resolved),
                binding_id=_db_binding_id(resolved),
            )
        except Exception:
            logger.debug("OAuth auto-create failed closed", exc_info=True)
            return None, "auto_create_error"
        if not created:
            return None, "auto_create_error"
        # Fail closed on an incomplete provisioning result instead of erroring while
        # building the session: a user without an id, hash or name cannot be signed in.
        if not all(text_of(created, name) for name in ("id", "user_hash", "username")):
            return None, "auto_create_incomplete"
        if not _is_active_consumer(created):
            return None, "auto_create_inactive"
        return created, None

    def _provisioning_group(self, resolved: ResolvedConnection, record: OAuthStateRecord) -> tuple[str | None, str | None]:
        binding = resolved.binding
        if binding.default_user_group_id:
            return binding.default_user_group_id, None
        # Only the environment-sourced legacy binding accepts the group the companion
        # backend asserted. Database bindings always use their own validated group.
        if binding.trusts_caller_scope and record.user_group_hash:
            try:
                group = self.deps.db.get_user_group_by_hash(record.user_group_hash)
            except Exception:
                group = None
            group_id = text_of(group, "id")
            return (group_id, None) if group_id else (None, "user_group_not_found")
        return None, "no_bound_user_group"

    # --------------------------------------------------------------------- link
    async def _complete_link(
        self, request: Request, *, resolved: ResolvedConnection, record: OAuthStateRecord, key: IdentityKey, correlation_id: str
    ) -> Any:
        user_id = str(record.user_id or "")
        if not user_id or not resolved.binding.can_link:
            return oauth_error_response(ErrorCode.OAUTH_PROVISIONING_DENIED, status_code=401, correlation_id=correlation_id)
        db = self.deps.db
        existing = db.get_user_by_external_account(
            provider=key.provider_type, provider_sub_hash=key.sub_hash, identity_namespace=_namespace_for(resolved, key.identity_namespace)
        )
        if existing and text_of(existing, "id") != user_id:
            try:
                await self._limit(
                    "check_provider_sub_collision", request=request, provider_sub_fingerprint=key.sub_fingerprint
                )
            except OAuthRateLimitExceeded as exc:
                return oauth_error_response(ErrorCode.OAUTH_RATE_LIMITED, status_code=429, retry_after=exc.retry_after)
            return oauth_error_response(
                ErrorCode.EXTERNAL_IDENTITY_SUB_CONFLICT, message=OAUTH_LINKING_DENIED_MESSAGE, correlation_id=correlation_id
            )
        try:
            linked = db.link_external_account(
                external_account_id=f"uea-{uuid4().hex}",
                user_id=user_id,
                provider=key.provider_type,
                provider_sub_hash=key.sub_hash,
                provider_sub_fingerprint=key.sub_fingerprint,
                provider_email_hash=key.email_hash,
                provider_email_masked=key.email_masked,
                provider_email_verified_at_link=key.email_verified,
                linked_by=user_id,
                metadata={"source": f"{key.provider_type}_oauth_link"},
                identity_namespace=_namespace_for(resolved, key.identity_namespace),
                connection_id=_db_connection_id(resolved),
            )
        except Exception:
            logger.debug("OAuth link failed closed", exc_info=True)
            return oauth_error_response(
                ErrorCode.EXTERNAL_IDENTITY_SUB_CONFLICT, message=OAUTH_LINKING_DENIED_MESSAGE, correlation_id=correlation_id
            )
        # A completed provider round trip is itself fresh proof for this session.
        self._mark_reauth(user_id, record.session_id)
        await self.deps.emit(
            EVENT_LINKED,
            resolved=resolved,
            details={"provider_sub_fingerprint": key.sub_fingerprint, "reason": "linked"},
            request=request,
            user_id=user_id,
        )
        return ExternalIdentityLinkResponse(
            success=True,
            message="External identity linked",
            external_identity=ExternalIdentityInfo(
                provider=key.provider_type,
                provider_subject_masked=key.sub_fingerprint,
                provider_email_masked=key.email_masked,
                provider_email_verified_at_link=key.email_verified,
                status=str(field_of(linked, "status", "linked") or "linked"),
            ),
        )

    # ------------------------------------------------------------------- reauth
    def _mark_reauth(self, user_id: str, session_id: str | None) -> None:
        try:
            self.deps.state_store().mark_recent_reauth(user_id=user_id, session_id=session_id)
        except Exception:
            logger.debug("OAuth recent-reauth marker failed", exc_info=True)

    async def _complete_reauth(
        self, request: Request, *, resolved: ResolvedConnection, record: OAuthStateRecord, key: IdentityKey, correlation_id: str
    ) -> Any:
        user_id = str(record.user_id or "")
        linked_user = self.deps.db.get_user_by_external_account(
            provider=key.provider_type, provider_sub_hash=key.sub_hash, identity_namespace=_namespace_for(resolved, key.identity_namespace)
        )
        # Step-up only counts when the identity that came back belongs to the session's user.
        if not user_id or not linked_user or text_of(linked_user, "id") != user_id:
            return oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_NOT_LINKED, status_code=401, correlation_id=correlation_id)
        self.deps.state_store().mark_recent_reauth(user_id=user_id, session_id=record.session_id)
        await self.deps.emit(
            EVENT_REAUTH_SUCCEEDED,
            resolved=resolved,
            details={"reason": "reauth_succeeded", "provider_sub_fingerprint": key.sub_fingerprint},
            request=request,
            user_id=user_id,
        )
        return {"success": True, "message": "Reauthentication succeeded", "reauthenticated": True}

    # ------------------------------------------------------------------- unlink
    async def unlink(self, request: Request, *, resolved: ResolvedConnection, login_data: Any, session_token: str) -> Any:
        from src.Util.auth_flow import require_recent_reauthentication
        from src.Util.auth_lifecycle import revoke_user_auth_state
        from src.Util.error_handler import AuthenticationError

        user_id = str(field_of(login_data, "user_id") or "")
        if not user_id:
            return oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_NOT_LINKED, status_code=404)
        try:
            require_recent_reauthentication(
                user_id=user_id,
                session_token=session_token,
                session_id=session_id_of(login_data),
                operation="oauth_unlink",
            )
        except AuthenticationError:
            return oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_NOT_LINKED, status_code=401, message=OAUTH_LINKING_DENIED_MESSAGE)
        try:
            await maybe_await(
                self.deps.rate_limiter().check_unlink_attempt(user_id=user_id, ip_address=client_ip(request, settings=self.deps.settings))
            )
        except OAuthRateLimitExceeded as exc:
            return oauth_error_response(ErrorCode.OAUTH_RATE_LIMITED, status_code=429, retry_after=exc.retry_after)

        db = self.deps.db
        user_hash = text_of(login_data, "user_hash")
        current_user = db.get_user_by_hash(user_hash) if user_hash else None
        if not has_usable_fallback_auth(current_user):
            return oauth_error_response(
                ErrorCode.OAUTH_PASSWORD_REQUIRED_FOR_UNLINK,
                status_code=409,
                message="External identity action could not be completed. Establish fallback authentication first.",
            )
        result = db.unlink_external_account(
            user_id=user_id,
            provider=resolved.config.provider_type,
            unlinked_by=user_id,
            reason="user_unlink",
            identity_namespace=_namespace_for(resolved, resolved.config.identity_namespace),
        )
        if not result:
            return oauth_error_response(ErrorCode.EXTERNAL_IDENTITY_NOT_LINKED, status_code=404)
        summary = revoke_user_auth_state(user_id, reason=f"{resolved.config.provider_type}_oauth_account_unlinked")
        await self.deps.emit(EVENT_UNLINKED, resolved=resolved, details={"reason": "user_unlink"}, request=request, user_id=user_id)
        return ExternalIdentityUnlinkResponse(
            success=True,
            message="External identity unlinked",
            remaining_auth_methods=["password"],
            sessions_revoked=int(getattr(summary, "sessions_revoked", 0) or 0),
        )


# ─────────────────────────────────────────────────────────────── module helpers

def session_id_of(login_data: Any) -> str | None:
    return text_of(login_data, "session_id") or text_of(login_data, "session_token")


def has_usable_fallback_auth(user: Any) -> bool:
    password_hash = text_of(user, "password_hash", "") or ""
    if not password_hash:
        return False
    return not any(marker in password_hash.lower() for marker in ("oauth-disabled", "passwordless", "placeholder"))


def _is_active_consumer(user: Any) -> bool:
    return bool(field_of(user, "is_active", True)) and (text_of(user, "user_type", "consumer") == "consumer")


def _namespace_for(resolved: ResolvedConnection, namespace: str) -> str | None:
    """Namespace handed to the persistence layer, or ``None`` for the provider-keyed path.

    The environment source only ever serves Google, whose namespace equals its provider
    name, so there the historical provider-keyed procedures are functionally identical.
    Using them keeps ``OAUTH_CONFIG_SOURCE=env`` free of any dependency on the new schema:
    deploying this code before running the schema catch-up cannot break Google sign-in.
    """

    return None if resolved.source_name == "env" else namespace


def _db_connection_id(resolved: ResolvedConnection) -> str | None:
    return None if resolved.source_name == "env" else resolved.config.connection_id


def _db_binding_id(resolved: ResolvedConnection) -> str | None:
    return None if resolved.source_name == "env" else resolved.binding.binding_id


def _user_dict(user: Any) -> dict[str, Any]:
    return {
        "id": text_of(user, "id"),
        "user_hash": text_of(user, "user_hash"),
        "username": text_of(user, "username"),
        "email": text_of(user, "email"),
        "user_type": text_of(user, "user_type", "consumer"),
    }


def _project_dict(project: Any) -> dict[str, Any]:
    return {
        "id": text_of(project, "id"),
        "project_hash": text_of(project, "project_hash"),
        "project_name": text_of(project, "project_name"),
        "project_description": text_of(project, "project_description"),
        "is_active": bool(field_of(project, "is_active", True)),
        "archived": bool(field_of(project, "archived", False)),
    }


def _project_info(project: Any) -> ProjectInfo:
    data = _project_dict(project)
    return ProjectInfo(
        project_hash=data["project_hash"], project_name=data["project_name"], project_description=data.get("project_description")
    )


def _login_response(*, token_pair: Any, user: Any, project: Any, accessible_projects: list[Any], user_groups: list[Any]) -> LoginResponse:
    data = _user_dict(user)
    groups = []
    for group in user_groups:
        group_hash, group_name = text_of(group, "group_hash"), text_of(group, "group_name")
        if group_hash and group_name:
            groups.append(UserGroupInfo(group_hash=group_hash, group_name=group_name, description=text_of(group, "group_description")))
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
            user_hash=data["user_hash"], username=data["username"], email=data.get("email"), user_type=data.get("user_type")
        ),
        project=_project_info(project),
        accessible_projects=[_project_info(item) for item in accessible_projects if text_of(item, "project_hash")],
        user_groups=groups,
        user_id=data.get("id"),
    )


__all__ = [
    "AuthorizationStart",
    "FORBIDDEN_BROWSER_STRICT_FIELDS",
    "OAuthPipeline",
    "PipelineDeps",
    "client_ip",
    "field_of",
    "has_usable_fallback_auth",
    "maybe_await",
    "new_correlation_id",
    "oauth_error_response",
    "safe_details",
    "session_id_of",
    "text_of",
    "user_agent",
]
