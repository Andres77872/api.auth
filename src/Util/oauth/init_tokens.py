"""Init tokens minted by ``POST /auth/oauth/init`` (the inverted handshake).

The consumer backend authenticates to ``api.auth`` with a project credential and
receives an opaque, single-use, short-lived token. The project is derived from
that credential and the provisioning group from ``api.auth``'s own binding row --
neither is ever asserted by the caller (docs/agnostic_oauth F-26, F-27).

Storage mirrors OAuth state: HMAC-keyed Redis records, atomic consume, replay
tombstone, fail closed on Redis errors.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.Util.auth_constants import OAUTH_INIT_TOKEN_CONSUMED_PREFIX, OAUTH_INIT_TOKEN_PREFIX
from src.Util.oauth_state import (
    MAX_OAUTH_STATE_TTL_SECONDS,
    OAuthStateInvalidError,
    OAuthStateReplayError,
    OAuthStateStore,
    _urlsafe_random,
    _utc_timestamp,
    fingerprint_oauth_value,
)


DEFAULT_INIT_TOKEN_TTL_SECONDS = 300
INIT_RECORD_VERSION = 1


class OAuthInitTokenInvalid(OAuthStateInvalidError):
    """The init token is unknown, expired or malformed."""


class OAuthInitTokenReplayed(OAuthStateReplayError):
    """The init token was already consumed."""


@dataclass(frozen=True)
class InitTokenMinted:
    token: str = field(repr=False)
    expires_in: int
    fingerprint: str


@dataclass(frozen=True)
class InitTokenRecord:
    connection_id: str
    binding_id: str
    connection_key: str
    config_source: str
    purpose: str
    project_hash: str = field(repr=False)
    return_origin: str
    remember_me: bool
    fingerprint: str
    raw: Mapping[str, Any] = field(default_factory=dict, repr=False)


class OAuthInitTokenStore:
    def __init__(self, *, redis_client: Any | None = None, state_pepper: str | None = None, fail_closed: bool | None = None) -> None:
        self._store = OAuthStateStore(redis_client=redis_client, state_pepper=state_pepper, fail_closed=fail_closed)

    def mint(self, *, binding: Mapping[str, Any], ttl_seconds: int | None = None) -> InitTokenMinted:
        ttl = max(1, min(int(ttl_seconds or DEFAULT_INIT_TOKEN_TTL_SECONDS), MAX_OAUTH_STATE_TTL_SECONDS))
        token = _urlsafe_random(32)
        now = time.time()
        fingerprint = fingerprint_oauth_value(token)
        payload = {
            "version": INIT_RECORD_VERSION,
            "fingerprint": fingerprint,
            "created_at": _utc_timestamp(now),
            "expires_at": _utc_timestamp(now + ttl),
            **dict(binding or {}),
        }
        self._store._write_record(prefix=OAUTH_INIT_TOKEN_PREFIX, secret=token, payload=payload, ttl_seconds=ttl)
        return InitTokenMinted(token=token, expires_in=ttl, fingerprint=fingerprint)

    def consume(self, token: str) -> InitTokenRecord:
        try:
            payload = self._store._consume_record(
                prefix=OAUTH_INIT_TOKEN_PREFIX,
                consumed_prefix=OAUTH_INIT_TOKEN_CONSUMED_PREFIX,
                secret=token,
                label="init token",
            )
        except OAuthStateReplayError as exc:
            raise OAuthInitTokenReplayed(str(exc)) from exc
        except OAuthStateInvalidError as exc:
            raise OAuthInitTokenInvalid(str(exc)) from exc
        required = ("connection_id", "binding_id", "connection_key", "project_hash", "return_origin")
        if int(payload.get("version") or 0) != INIT_RECORD_VERSION or any(not payload.get(name) for name in required):
            raise OAuthInitTokenInvalid("OAuth init token payload is malformed")
        return InitTokenRecord(
            connection_id=str(payload["connection_id"]),
            binding_id=str(payload["binding_id"]),
            connection_key=str(payload["connection_key"]),
            config_source=str(payload.get("config_source") or ""),
            purpose=str(payload.get("purpose") or "login"),
            project_hash=str(payload["project_hash"]),
            return_origin=str(payload["return_origin"]),
            remember_me=bool(payload.get("remember_me", False)),
            fingerprint=str(payload.get("fingerprint") or fingerprint_oauth_value(token)),
            raw=payload,
        )


__all__ = [
    "DEFAULT_INIT_TOKEN_TTL_SECONDS",
    "InitTokenMinted",
    "InitTokenRecord",
    "OAuthInitTokenInvalid",
    "OAuthInitTokenReplayed",
    "OAuthInitTokenStore",
]
