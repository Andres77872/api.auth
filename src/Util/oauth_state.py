"""Redis-backed Google OAuth state, nonce, PKCE, link, and reauth storage.

Trace: `.dev/sdd/changes/google-oauth-login/tasks.md` task 6.1.

Security posture:
- Redis keys use HMAC-SHA256 fingerprints; raw state/link/reauth secrets are
  never embedded in keys.
- Raw nonce and PKCE verifier live only in short-lived Redis values because the
  callback needs them for OIDC/PKCE validation.
- Redis errors fail closed by default. There is no process-memory fallback.
- Configuration is loaded lazily through ``google_oauth_config``; this module
  does not parse ``.env`` or read secrets at import time.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from src.Util.auth_constants import (
    GOOGLE_OAUTH_LINK_TOKEN_PREFIX,
    GOOGLE_OAUTH_RECENT_REAUTH_PREFIX,
    GOOGLE_OAUTH_STATE_CONSUMED_PREFIX,
    GOOGLE_OAUTH_STATE_PREFIX,
)
from src.Util.google_oauth_config import load_google_oauth_config


# Test fixtures patch this usage location after the module exists. Keep the
# default ``None`` so importing this module does not import db_config/Redis.
redis_client = None

MAX_OAUTH_STATE_TTL_SECONDS = 600
MIN_OAUTH_SECRET_CHARS = 43  # base64url(32 random bytes) without padding.
_URLSAFE_SECRET_RE = re.compile(r"^[A-Za-z0-9_-]{16,512}$")


class OAuthStateError(RuntimeError):
    """Base class for OAuth state storage errors."""


class OAuthStateStoreUnavailable(OAuthStateError):
    """Raised when Redis cannot safely enforce OAuth state/replay controls."""


class OAuthStateInvalidError(OAuthStateError):
    """Raised when OAuth state is missing, expired, malformed, or unknown."""


class OAuthStateReplayError(OAuthStateInvalidError):
    """Raised when a previously consumed OAuth state/link token is reused."""


@dataclass(frozen=True)
class OAuthMaterial:
    state: str
    nonce: str
    code_verifier: str
    code_challenge: str
    code_challenge_method: str = "S256"


@dataclass(frozen=True)
class OAuthBindingCookieMetadata:
    name: str = "oauth_state"
    samesite: str = "Lax"
    max_age_seconds: int = MAX_OAUTH_STATE_TTL_SECONDS
    httponly: bool = True
    secure: bool = True
    contains_tokens: bool = False


@dataclass(frozen=True)
class OAuthStateCreated:
    state: str
    nonce: str
    code_verifier: str = field(repr=False)
    code_challenge: str
    code_challenge_method: str
    expires_in: int
    expires_at: str
    state_fingerprint: str
    provider_init_fingerprint: str | None
    cookie_metadata: OAuthBindingCookieMetadata


@dataclass(frozen=True)
class OAuthStateRecord:
    provider: str
    purpose: str
    redirect_uri: str | None
    return_origin: str | None
    nonce: str = field(repr=False)
    code_verifier: str = field(repr=False)
    code_challenge: str
    code_challenge_method: str
    state_fingerprint: str
    provider_init_fingerprint: str | None = None
    project_hash: str | None = field(default=None, repr=False)
    user_group_hash: str | None = field(default=None, repr=False)
    scope_fingerprint: str | None = None
    ip_hash: str | None = None
    ua_hash: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    provider_init_binding: Mapping[str, Any] = field(default_factory=dict, repr=False)


def _default_redis_client():
    global redis_client
    if redis_client is not None:
        return redis_client
    from src.Util.db_config import redis_client as configured_redis_client

    redis_client = configured_redis_client
    return configured_redis_client


def _urlsafe_random(num_bytes: int = 32) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(num_bytes)).rstrip(b"=").decode("ascii")


def _b64url_digest(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def build_pkce_s256_challenge(code_verifier: str) -> str:
    """Return the RFC 7636 S256 challenge for a PKCE verifier."""

    digest = hashlib.sha256(str(code_verifier).encode("ascii")).digest()
    return _b64url_digest(digest)


def generate_oauth_material() -> OAuthMaterial:
    """Generate 256-bit state, nonce, and PKCE verifier material."""

    state = _urlsafe_random(32)
    nonce = _urlsafe_random(32)
    code_verifier = _urlsafe_random(32)
    return OAuthMaterial(
        state=state,
        nonce=nonce,
        code_verifier=code_verifier,
        code_challenge=build_pkce_s256_challenge(code_verifier),
    )


def constant_time_equals(left: str | bytes | None, right: str | bytes | None) -> bool:
    """Compare OAuth secrets without timing-short-circuit semantics."""

    if left is None or right is None:
        return False
    if isinstance(left, str):
        left = left.encode("utf-8")
    if isinstance(right, str):
        right = right.encode("utf-8")
    return hmac.compare_digest(left, right)


def fingerprint_oauth_value(value: str | bytes | None, *, length: int = 12) -> str:
    """Return a short non-reversible fingerprint for logs/audit/activity."""

    if value is None:
        value = ""
    if isinstance(value, str):
        value = value.encode("utf-8")
    return hashlib.sha256(value).hexdigest()[:length]


def _utc_timestamp(epoch_seconds: float) -> str:
    return datetime.fromtimestamp(epoch_seconds, tz=timezone.utc).isoformat().replace("+00:00", "Z")


def _ttl(value: int | None, fallback: int) -> int:
    ttl = int(value if value is not None else fallback)
    return max(1, min(ttl, MAX_OAUTH_STATE_TTL_SECONDS))


def _ensure_state_shape(value: str, *, label: str = "state") -> None:
    if not isinstance(value, str) or not _URLSAFE_SECRET_RE.fullmatch(value):
        raise OAuthStateInvalidError(f"OAuth {label} is invalid")


def _json_dumps(payload: Mapping[str, Any]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _json_loads(value: Any) -> dict[str, Any]:
    if value is None:
        raise OAuthStateInvalidError("OAuth state is missing or expired")
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="strict")
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except json.JSONDecodeError as exc:
            raise OAuthStateInvalidError("OAuth state payload is malformed") from exc
        if isinstance(decoded, dict):
            return decoded
    raise OAuthStateInvalidError("OAuth state payload is malformed")


class OAuthStateStore:
    """Redis store for OAuth state, link tokens, and recent reauth markers."""

    def __init__(
        self,
        *,
        redis_client: Any | None = None,
        redis: Any | None = None,
        state_pepper: str | None = None,
        pepper: str | None = None,
        fail_closed: bool | None = None,
    ) -> None:
        config = None
        resolved_pepper = state_pepper or pepper
        if not resolved_pepper or fail_closed is None:
            config = load_google_oauth_config()
        self.redis = redis_client if redis_client is not None else redis if redis is not None else _default_redis_client()
        self.state_pepper = resolved_pepper or config.state_pepper
        self.fail_closed = config.fail_closed_on_redis_error if fail_closed is None else bool(fail_closed)
        if not self.state_pepper:
            raise OAuthStateStoreUnavailable("OAuth state pepper is not configured")

    def _hmac_digest(self, value: str) -> str:
        return hmac.new(
            self.state_pepper.encode("utf-8"),
            str(value).encode("utf-8"),
            hashlib.sha256,
        ).hexdigest()

    def _key(self, prefix: str, value: str) -> str:
        return f"{prefix}{self._hmac_digest(value)[:32]}"

    def _handle_redis_error(self, exc: Exception) -> None:
        if self.fail_closed:
            raise OAuthStateStoreUnavailable("OAuth Redis state store is unavailable") from exc
        raise OAuthStateStoreUnavailable("OAuth Redis state store is unavailable") from exc

    def _set(self, key: str, value: str, *, ttl_seconds: int, nx: bool = False) -> bool:
        try:
            return bool(self.redis.set(key, value, ex=max(1, int(ttl_seconds)), nx=nx))
        except Exception as exc:  # pragma: no cover - exercised by tests with fake redis
            self._handle_redis_error(exc)
            return False

    def _exists(self, key: str) -> bool:
        try:
            return bool(self.redis.exists(key))
        except Exception as exc:
            self._handle_redis_error(exc)
            return False

    def _get_and_delete(self, key: str) -> Any:
        try:
            getdel = getattr(self.redis, "getdel", None)
            if callable(getdel):
                return getdel(key)
            value = self.redis.get(key)
            if value is not None:
                self.redis.delete(key)
            return value
        except Exception as exc:
            self._handle_redis_error(exc)
            return None

    def _write_record(self, *, prefix: str, secret: str, payload: Mapping[str, Any], ttl_seconds: int) -> str:
        key = self._key(prefix, secret)
        if not self._set(key, _json_dumps(payload), ttl_seconds=ttl_seconds, nx=True):
            raise OAuthStateInvalidError("OAuth state collision")
        return key

    def _consume_record(self, *, prefix: str, consumed_prefix: str, secret: str, label: str) -> dict[str, Any]:
        _ensure_state_shape(secret, label=label)
        key = self._key(prefix, secret)
        consumed_key = self._key(consumed_prefix, secret)
        value = self._get_and_delete(key)
        if value is None:
            if self._exists(consumed_key):
                raise OAuthStateReplayError(f"OAuth {label} was already consumed")
            raise OAuthStateInvalidError(f"OAuth {label} is missing or expired")
        self._set(consumed_key, "1", ttl_seconds=MAX_OAUTH_STATE_TTL_SECONDS, nx=False)
        return _json_loads(value)

    def create_state(self, *, provider_init_binding: Mapping[str, Any], ttl_seconds: int | None = None) -> OAuthStateCreated:
        """Create Redis-backed OAuth state bound to a provider-init payload."""

        ttl = _ttl(ttl_seconds, load_google_oauth_config().state_ttl_seconds)
        material = generate_oauth_material()
        now = time.time()
        expires_at = _utc_timestamp(now + ttl)
        binding = dict(provider_init_binding or {})
        provider_init_fingerprint = binding.get("provider_init_fingerprint")
        payload = {
            "version": 1,
            "provider": binding.get("provider", "google"),
            "purpose": binding.get("purpose", "login"),
            "project_hash": binding.get("project_hash"),
            "user_group_hash": binding.get("user_group_hash"),
            "return_origin": binding.get("return_origin"),
            "redirect_uri": binding.get("redirect_uri"),
            "nonce": material.nonce,
            "code_verifier": material.code_verifier,
            "code_challenge": material.code_challenge,
            "code_challenge_method": material.code_challenge_method,
            "state_fingerprint": fingerprint_oauth_value(material.state),
            "provider_init_fingerprint": provider_init_fingerprint,
            "scope_fingerprint": binding.get("scope_fingerprint"),
            "ip_hash": binding.get("ip_hash"),
            "ua_hash": binding.get("ua_hash"),
            "created_at": _utc_timestamp(now),
            "expires_at": expires_at,
        }
        self._write_record(prefix=GOOGLE_OAUTH_STATE_PREFIX, secret=material.state, payload=payload, ttl_seconds=ttl)
        return OAuthStateCreated(
            state=material.state,
            nonce=material.nonce,
            code_verifier=material.code_verifier,
            code_challenge=material.code_challenge,
            code_challenge_method=material.code_challenge_method,
            expires_in=ttl,
            expires_at=expires_at,
            state_fingerprint=payload["state_fingerprint"],
            provider_init_fingerprint=provider_init_fingerprint,
            cookie_metadata=OAuthBindingCookieMetadata(max_age_seconds=ttl),
        )

    create_oauth_state = create_state

    def consume_state(self, state: str) -> OAuthStateRecord:
        """Consume an OAuth state exactly once and return its Redis payload."""

        payload = self._consume_record(
            prefix=GOOGLE_OAUTH_STATE_PREFIX,
            consumed_prefix=GOOGLE_OAUTH_STATE_CONSUMED_PREFIX,
            secret=state,
            label="state",
        )
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

    consume_oauth_state = consume_state

    def create_link_token(self, *, binding: Mapping[str, Any], ttl_seconds: int | None = None) -> OAuthStateCreated:
        """Create a single-use link-token record with the state TTL cap."""

        config = load_google_oauth_config()
        ttl = _ttl(ttl_seconds, config.link_token_ttl_seconds)
        material = generate_oauth_material()
        now = time.time()
        payload = {
            "version": 1,
            "provider": "google",
            "purpose": "link",
            "nonce": material.nonce,
            "code_verifier": material.code_verifier,
            "code_challenge": material.code_challenge,
            "code_challenge_method": material.code_challenge_method,
            "state_fingerprint": fingerprint_oauth_value(material.state),
            "created_at": _utc_timestamp(now),
            "expires_at": _utc_timestamp(now + ttl),
            **dict(binding or {}),
        }
        self._write_record(prefix=GOOGLE_OAUTH_LINK_TOKEN_PREFIX, secret=material.state, payload=payload, ttl_seconds=ttl)
        return OAuthStateCreated(
            state=material.state,
            nonce=material.nonce,
            code_verifier=material.code_verifier,
            code_challenge=material.code_challenge,
            code_challenge_method=material.code_challenge_method,
            expires_in=ttl,
            expires_at=payload["expires_at"],
            state_fingerprint=payload["state_fingerprint"],
            provider_init_fingerprint=payload.get("provider_init_fingerprint"),
            cookie_metadata=OAuthBindingCookieMetadata(name="oauth_link", max_age_seconds=ttl),
        )

    def consume_link_token(self, link_token: str) -> dict[str, Any]:
        """Consume an OAuth link token once."""

        return self._consume_record(
            prefix=GOOGLE_OAUTH_LINK_TOKEN_PREFIX,
            consumed_prefix=GOOGLE_OAUTH_STATE_CONSUMED_PREFIX,
            secret=link_token,
            label="link token",
        )

    def mark_recent_reauth(self, *, user_id: str, session_id: str | None = None, ttl_seconds: int | None = None) -> str:
        """Record a short-lived recent reauthentication marker."""

        config = load_google_oauth_config()
        ttl = max(1, int(ttl_seconds if ttl_seconds is not None else config.recent_reauth_seconds))
        material = f"{user_id}|{session_id or ''}"
        key = self._key(GOOGLE_OAUTH_RECENT_REAUTH_PREFIX, material)
        self._set(key, _json_dumps({"user_id": user_id, "session_id": session_id, "created_at": _utc_timestamp(time.time())}), ttl_seconds=ttl)
        return key

    def has_recent_reauth(self, *, user_id: str, session_id: str | None = None) -> bool:
        """Return whether a recent reauthentication marker exists."""

        return self._exists(self._key(GOOGLE_OAUTH_RECENT_REAUTH_PREFIX, f"{user_id}|{session_id or ''}"))


def create_state(*, provider_init_binding: Mapping[str, Any], ttl_seconds: int | None = None) -> OAuthStateCreated:
    return OAuthStateStore().create_state(provider_init_binding=provider_init_binding, ttl_seconds=ttl_seconds)


def consume_state(state: str) -> OAuthStateRecord:
    return OAuthStateStore().consume_state(state)


__all__ = [
    "OAuthBindingCookieMetadata",
    "OAuthMaterial",
    "OAuthStateCreated",
    "OAuthStateError",
    "OAuthStateInvalidError",
    "OAuthStateRecord",
    "OAuthStateReplayError",
    "OAuthStateStore",
    "OAuthStateStoreUnavailable",
    "build_pkce_s256_challenge",
    "constant_time_equals",
    "consume_state",
    "create_state",
    "fingerprint_oauth_value",
    "generate_oauth_material",
]
