"""Redis-backed OAuth state, nonce, PKCE and recent-reauth storage (provider-agnostic).

The state record binds the connection and project binding
chosen at start, so the callback selects the provider from the record only and
never from caller input (mix-up defence).

Security posture:
- Redis keys use HMAC-SHA256 fingerprints; raw state/link/reauth secrets are
  never embedded in keys.
- Raw nonce and PKCE verifier live only in short-lived Redis values because the
  callback needs them for OIDC/PKCE validation.
- Redis errors fail closed by default. There is no process-memory fallback.
- Deployment settings are loaded lazily through ``src.Util.oauth.settings``; this
  module does not parse ``.env`` or read secrets at import time.
- Keys use neutral ``oauth_state:`` prefixes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import secrets
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from redis.exceptions import WatchError

from src.Util.auth_constants import OAUTH_COMPLETION_PREFIX, OAUTH_RECENT_REAUTH_PREFIX, OAUTH_STATE_CONSUMED_PREFIX, OAUTH_STATE_PREFIX
from src.Util.oauth.settings import load_oauth_settings


STATE_RECORD_VERSION = 3
_SUPPORTED_STATE_RECORD_VERSIONS = {2, STATE_RECORD_VERSION}


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
class OAuthRecentAuthProof:
    source: str
    authenticated_at_ms: int
    expires_at_ms: int
    marker_fingerprint: str | None = field(default=None, repr=False)


@dataclass(frozen=True)
class OAuthSessionAuthorization:
    user_id: str = field(repr=False)
    user_hash: str = field(repr=False)
    session_id: str = field(repr=False)
    family_id: str = field(repr=False)
    scope: str
    project_hash: str | None = field(repr=False)
    proof: OAuthRecentAuthProof | None = None

    @classmethod
    def from_payload(cls, value: Any) -> OAuthSessionAuthorization:
        if not isinstance(value, dict):
            raise OAuthStateInvalidError("OAuth session authorization is missing")
        required = ("user_id", "user_hash", "session_id", "family_id", "scope")
        if any(not isinstance(value.get(name), str) or not value[name] for name in required):
            raise OAuthStateInvalidError("OAuth session authorization is malformed")
        if value["scope"] not in {"project", "platform"} or (
            value["scope"] == "project" and (not isinstance(value.get("project_hash"), str) or not value["project_hash"])
        ):
            raise OAuthStateInvalidError("OAuth authorization scope is malformed")
        proof = value.get("proof")
        if proof is not None:
            if not isinstance(proof, dict) or proof.get("source") not in {"token", "marker"}:
                raise OAuthStateInvalidError("OAuth authentication proof is malformed")
            for name in ("authenticated_at_ms", "expires_at_ms"):
                if type(proof.get(name)) is not int or proof[name] <= 0:
                    raise OAuthStateInvalidError("OAuth authentication proof is malformed")
            if proof["expires_at_ms"] <= proof["authenticated_at_ms"]:
                raise OAuthStateInvalidError("OAuth authentication proof is malformed")
            marker = proof.get("marker_fingerprint")
            if proof["source"] == "marker" and (not isinstance(marker, str) or not re.fullmatch(r"[0-9a-f]{64}", marker)):
                raise OAuthStateInvalidError("OAuth reauthentication proof is malformed")
            proof = OAuthRecentAuthProof(proof["source"], proof["authenticated_at_ms"], proof["expires_at_ms"], marker)
        return cls(**{name: value[name] for name in required}, project_hash=value.get("project_hash"), proof=proof)


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
    init_token_fingerprint: str | None
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
    init_token_fingerprint: str | None = None
    project_hash: str | None = field(default=None, repr=False)
    scope_fingerprint: str | None = None
    ip_hash: str | None = None
    ua_hash: str | None = None
    created_at: str | None = None
    expires_at: str | None = None
    oauth_binding: Mapping[str, Any] = field(default_factory=dict, repr=False)
    connection_id: str | None = None
    binding_id: str | None = None
    expected_issuer: str | None = None
    delivery_mode: str | None = None
    prompt: str | None = None
    remember_me: bool = False
    user_id: str | None = field(default=None, repr=False)
    session_id: str | None = field(default=None, repr=False)
    authorization: OAuthSessionAuthorization | None = field(default=None, repr=False)
    authorization_ref: str | None = field(default=None, repr=False)
    version: int = STATE_RECORD_VERSION


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
        settings = None
        resolved_pepper = state_pepper or pepper
        if not resolved_pepper or fail_closed is None:
            settings = load_oauth_settings()
        self.redis = redis_client if redis_client is not None else redis if redis is not None else _default_redis_client()
        self.state_pepper = resolved_pepper or settings.state_pepper
        self.fail_closed = settings.fail_closed_on_redis_error if fail_closed is None else bool(fail_closed)
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

    def _consume_record(
        self,
        *,
        prefix: str,
        consumed_prefix: str,
        secret: str,
        label: str,
    ) -> dict[str, Any]:
        _ensure_state_shape(secret, label=label)
        consumed_key = self._key(consumed_prefix, secret)
        value = self._get_and_delete(self._key(prefix, secret))
        if value is None:
            if self._exists(consumed_key):
                raise OAuthStateReplayError(f"OAuth {label} was already consumed")
            raise OAuthStateInvalidError(f"OAuth {label} is missing or expired")
        self._set(consumed_key, "1", ttl_seconds=MAX_OAUTH_STATE_TTL_SECONDS, nx=False)
        return _json_loads(value)

    def create_state(self, *, oauth_binding: Mapping[str, Any], ttl_seconds: int | None = None) -> OAuthStateCreated:
        """Create Redis-backed OAuth state bound to a connection and its init binding."""

        ttl = _ttl(ttl_seconds, load_oauth_settings().max_state_ttl_seconds)
        material = generate_oauth_material()
        now = time.time()
        binding = dict(oauth_binding or {})
        purpose = binding.get("purpose", "login")
        authorization = None
        authorization_ref = None
        expires_at_ms = int((now + ttl) * 1000)
        if purpose in {"link", "reauth"}:
            authorization = OAuthSessionAuthorization.from_payload(binding.get("authorization"))
            if (authorization.user_id != binding.get("user_id") or authorization.session_id != binding.get("session_id")
                    or authorization.project_hash != binding.get("project_hash")):
                raise OAuthStateInvalidError("OAuth authorization binding mismatch")
            if purpose == "link":
                if authorization.proof is None:
                    raise OAuthStateInvalidError("OAuth linking proof is missing")
                expires_at_ms = min(expires_at_ms, authorization.proof.expires_at_ms)
            if expires_at_ms <= int(now * 1000):
                raise OAuthStateInvalidError("OAuth authorization has expired")
            authorization_ref = self._hmac_digest(material.state)[:32]
        expires_at = _utc_timestamp(expires_at_ms / 1000)
        ttl = max(1, math.ceil((expires_at_ms - int(now * 1000)) / 1000))
        init_token_fingerprint = binding.get("init_token_fingerprint")
        payload = {
            "version": STATE_RECORD_VERSION,
            "provider": binding.get("provider", "google"),
            "purpose": binding.get("purpose", "login"),
            "connection_id": binding.get("connection_id"),
            "binding_id": binding.get("binding_id"),
            "expected_issuer": binding.get("expected_issuer"),
            "delivery_mode": binding.get("delivery_mode"),
            "project_hash": binding.get("project_hash"),
            "return_origin": binding.get("return_origin"),
            "redirect_uri": binding.get("redirect_uri"),
            "prompt": binding.get("prompt"),
            "remember_me": bool(binding.get("remember_me", False)),
            "user_id": binding.get("user_id"),
            "session_id": binding.get("session_id"),
            "authorization": asdict(authorization) if authorization else None,
            "authorization_ref": authorization_ref,
            "nonce": material.nonce,
            "code_verifier": material.code_verifier,
            "code_challenge": material.code_challenge,
            "code_challenge_method": material.code_challenge_method,
            "state_fingerprint": fingerprint_oauth_value(material.state),
            "init_token_fingerprint": init_token_fingerprint,
            "scope_fingerprint": binding.get("scope_fingerprint"),
            "ip_hash": binding.get("ip_hash"),
            "ua_hash": binding.get("ua_hash"),
            "created_at": _utc_timestamp(now),
            "expires_at": expires_at,
        }
        if authorization is None:
            self._write_record(prefix=OAUTH_STATE_PREFIX, secret=material.state, payload=payload, ttl_seconds=ttl)
        else:
            state_key = self._key(OAUTH_STATE_PREFIX, material.state)
            completion_key = self.completion_key(authorization_ref)
            try:
                with self.redis.pipeline(transaction=True) as pipe:
                    pipe.watch(state_key, completion_key)
                    if pipe.exists(state_key) or pipe.exists(completion_key):
                        raise OAuthStateInvalidError("OAuth state collision")
                    pipe.multi()
                    pipe.set(state_key, _json_dumps(payload), pxat=expires_at_ms)
                    pipe.set(completion_key, _json_dumps(self._completion_payload(payload)), pxat=expires_at_ms)
                    pipe.execute()
            except WatchError as exc:
                raise OAuthStateInvalidError("OAuth state collision") from exc
            except OAuthStateInvalidError:
                raise
            except Exception as exc:
                self._handle_redis_error(exc)
        return OAuthStateCreated(
            state=material.state,
            nonce=material.nonce,
            code_verifier=material.code_verifier,
            code_challenge=material.code_challenge,
            code_challenge_method=material.code_challenge_method,
            expires_in=ttl,
            expires_at=expires_at,
            state_fingerprint=payload["state_fingerprint"],
            init_token_fingerprint=init_token_fingerprint,
            cookie_metadata=OAuthBindingCookieMetadata(max_age_seconds=ttl),
        )

    create_oauth_state = create_state

    def consume_state(self, state: str) -> OAuthStateRecord:
        """Consume an OAuth state exactly once and return its Redis payload."""

        payload = self._consume_record(
            prefix=OAUTH_STATE_PREFIX,
            consumed_prefix=OAUTH_STATE_CONSUMED_PREFIX,
            secret=state,
            label="state",
        )
        try:
            version = int(payload.get("version") or 0)
        except (TypeError, ValueError) as exc:
            raise OAuthStateInvalidError("OAuth state payload is malformed") from exc
        if version not in _SUPPORTED_STATE_RECORD_VERSIONS:
            raise OAuthStateInvalidError("OAuth state record version is not supported")
        purpose = payload.get("purpose")
        if purpose not in {"login", "link", "reauth"} or (version == 2 and purpose != "login"):
            raise OAuthStateInvalidError("OAuth state purpose/version is not supported")
        authorization = None
        if purpose in {"link", "reauth"}:
            authorization = OAuthSessionAuthorization.from_payload(payload.get("authorization"))
            if (authorization.user_id != payload.get("user_id") or authorization.session_id != payload.get("session_id")
                    or authorization.project_hash != payload.get("project_hash")
                    or payload.get("authorization_ref") != self._hmac_digest(state)[:32]
                    or (purpose == "link" and authorization.proof is None)):
                raise OAuthStateInvalidError("OAuth authorization binding mismatch")
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
            init_token_fingerprint=payload.get("init_token_fingerprint"),
            project_hash=payload.get("project_hash"),
            scope_fingerprint=payload.get("scope_fingerprint"),
            ip_hash=payload.get("ip_hash"),
            ua_hash=payload.get("ua_hash"),
            created_at=payload.get("created_at"),
            expires_at=payload.get("expires_at"),
            oauth_binding=payload,
            connection_id=payload.get("connection_id"),
            binding_id=payload.get("binding_id"),
            expected_issuer=payload.get("expected_issuer"),
            delivery_mode=payload.get("delivery_mode"),
            prompt=payload.get("prompt"),
            remember_me=bool(payload.get("remember_me", False)),
            user_id=payload.get("user_id"),
            session_id=payload.get("session_id"),
            authorization=authorization,
            authorization_ref=payload.get("authorization_ref"),
            version=version,
        )

    consume_oauth_state = consume_state

    @staticmethod
    def _completion_payload(payload: Mapping[str, Any]) -> dict[str, Any]:
        return {name: payload.get(name) for name in ("purpose", "connection_id", "binding_id", "authorization", "expires_at")}

    def completion_key(self, reference: str | None) -> str:
        if not isinstance(reference, str) or not re.fullmatch(r"[0-9a-f]{32}", reference):
            raise OAuthStateInvalidError("OAuth completion authorization is malformed")
        return f"{OAUTH_COMPLETION_PREFIX}{reference}"

    def recent_reauth_key(self, *, user_id: str, session_id: str | None) -> str:
        return self._key(OAUTH_RECENT_REAUTH_PREFIX, f"{user_id}|{session_id or ''}")

    def validate_completion(self, record: OAuthStateRecord, *, reader: Any) -> None:
        key = self.completion_key(record.authorization_ref)
        if reader.pttl(key) <= 0 or _json_loads(reader.get(key)) != self._completion_payload(record.oauth_binding):
            raise OAuthStateInvalidError("OAuth completion authorization has expired or changed")
        try:
            expires_at = datetime.fromisoformat(str(record.expires_at).replace("Z", "+00:00")).timestamp()
        except (ValueError, TypeError) as exc:
            raise OAuthStateInvalidError("OAuth completion deadline is malformed") from exc
        if time.time() >= expires_at:
            raise OAuthStateInvalidError("OAuth completion authorization has expired")

    def recent_reauth_proof(self, *, user_id: str, session_id: str, now_ms: int) -> OAuthRecentAuthProof | None:
        key = self.recent_reauth_key(user_id=user_id, session_id=session_id)
        try:
            raw = self.redis.get(key)
            remaining_ms = self.redis.pttl(key)
        except Exception as exc:
            self._handle_redis_error(exc)
        if raw is None or remaining_ms <= 0:
            return None
        try:
            payload = _json_loads(raw)
            authenticated_at_ms = int(datetime.fromisoformat(payload["created_at"].replace("Z", "+00:00")).timestamp() * 1000)
            if payload.get("user_id") != user_id or payload.get("session_id") != session_id or authenticated_at_ms > now_ms:
                return None
            expires_at_ms = min(now_ms + remaining_ms, authenticated_at_ms + load_oauth_settings().recent_reauth_seconds * 1000)
            if expires_at_ms <= now_ms:
                return None
        except (OAuthStateInvalidError, KeyError, ValueError, TypeError, AttributeError):
            return None
        return OAuthRecentAuthProof("marker", authenticated_at_ms, expires_at_ms, fingerprint_oauth_value(raw, length=64))

    def recent_reauth_write(self, *, user_id: str, session_id: str) -> tuple[str, str, int]:
        now = time.time()
        payload = {"user_id": user_id, "session_id": session_id, "created_at": _utc_timestamp(now), "proof_id": secrets.token_hex(16)}
        return (self.recent_reauth_key(user_id=user_id, session_id=session_id), _json_dumps(payload),
                int(now * 1000) + load_oauth_settings().recent_reauth_seconds * 1000)

    def mark_recent_reauth(self, *, user_id: str, session_id: str | None = None, ttl_seconds: int | None = None) -> str:
        """Record a short-lived recent reauthentication marker."""

        settings = load_oauth_settings()
        ttl = max(1, int(ttl_seconds if ttl_seconds is not None else settings.recent_reauth_seconds))
        key, payload, _ = self.recent_reauth_write(user_id=user_id, session_id=session_id)
        self._set(key, payload, ttl_seconds=ttl)
        return key

    def has_recent_reauth(self, *, user_id: str, session_id: str | None = None) -> bool:
        """Return whether a recent reauthentication marker exists."""

        return self._exists(self.recent_reauth_key(user_id=user_id, session_id=session_id))


def create_state(*, oauth_binding: Mapping[str, Any], ttl_seconds: int | None = None) -> OAuthStateCreated:
    return OAuthStateStore().create_state(oauth_binding=oauth_binding, ttl_seconds=ttl_seconds)


def consume_state(state: str) -> OAuthStateRecord:
    return OAuthStateStore().consume_state(state)


__all__ = [
    "OAuthBindingCookieMetadata",
    "OAuthMaterial",
    "OAuthRecentAuthProof",
    "OAuthSessionAuthorization",
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
