"""Idempotency-Key helpers for transactional auth email flows.

Trace:
- SDD `email-activation` task 4.9.
- Spec requirement: public `Idempotency-Key` support, non-reversible key
  hashing, semantic request binding, replay/conflict handling, Redis replay
  cache support, and MySQL as local authoritative truth.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from src.Util.auth_constants import DEFAULT_EMAIL_IDEMPOTENCY_TTL_SECONDS, EMAIL_IDEMPOTENCY_CACHE_PREFIX
from src.Util.error_handler import public_email_accepted_body


IDEMPOTENCY_HASH_VERSION = "v1"
IDEMPOTENCY_KEY_MAX_LENGTH = 128
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class IdempotencyKeyError(ValueError):
    """Raised for structurally invalid public Idempotency-Key headers."""


@dataclass(frozen=True)
class IdempotencyRecord:
    status: str
    idempotency_id: str | None
    replay_status_code: int
    replay_body: dict[str, Any]
    email_message_id: str | None = None
    expires_at: datetime | None = None

    @property
    def is_replay(self) -> bool:
        return self.status in {"complete", "in_progress"}

    @property
    def is_conflict(self) -> bool:
        return self.status == "conflict"


def _ensure_bytes(value: str | bytes, *, name: str) -> bytes:
    if isinstance(value, bytes):
        if value:
            return value
    elif isinstance(value, str) and value.strip():
        return value.encode("utf-8")
    raise ValueError(f"{name} must not be empty")


def validate_idempotency_key(raw_key: str | None) -> str | None:
    """Validate a public Idempotency-Key header without logging it."""

    if raw_key is None:
        return None
    key = str(raw_key).strip()
    if not key:
        return None
    if len(key) > IDEMPOTENCY_KEY_MAX_LENGTH or not IDEMPOTENCY_KEY_RE.match(key):
        raise IdempotencyKeyError("invalid Idempotency-Key header")
    return key


def hash_idempotency_key(key: str, *, pepper: str | bytes) -> bytes:
    """Return the non-reversible local hash for a public idempotency key."""

    validated = validate_idempotency_key(key)
    if not validated:
        raise IdempotencyKeyError("Idempotency-Key header is required")
    material = f"{IDEMPOTENCY_HASH_VERSION}:idempotency-key:{validated}".encode("utf-8")
    return hmac.digest(_ensure_bytes(pepper, name="pepper"), material, "sha256")


def _json_default(value: Any) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def _canonical_body(body: Mapping[str, Any] | None) -> str:
    return json.dumps(body or {}, sort_keys=True, separators=(",", ":"), default=_json_default)


def _hash_or_none(value: str | bytes | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value.hex()
    return str(value)


def request_fingerprint(
    *,
    scope: str,
    user_id: str | None,
    recipient_hash: str | bytes | None,
    body: Mapping[str, Any] | None,
    pepper: str | bytes,
) -> bytes:
    """Bind an idempotency key to endpoint, actor, recipient, and body."""

    canonical = {
        "scope": str(scope or "").strip(),
        "user_id": user_id or None,
        "recipient_hash": _hash_or_none(recipient_hash),
        "body": json.loads(_canonical_body(body)),
    }
    material = (
        f"{IDEMPOTENCY_HASH_VERSION}:request:"
        + json.dumps(canonical, sort_keys=True, separators=(",", ":"), default=_json_default)
    ).encode("utf-8")
    return hmac.digest(_ensure_bytes(pepper, name="pepper"), material, "sha256")


def cache_key_for_replay(scope: str, key_hash: bytes) -> str:
    material = f"{scope}|{key_hash.hex()}"
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:24]
    return f"{EMAIL_IDEMPOTENCY_CACHE_PREFIX}{digest}"


def replay_body_or_default(body: Mapping[str, Any] | None = None) -> dict[str, Any]:
    if body is None:
        return public_email_accepted_body()
    return dict(body)


def _decode_replay_body(value: Any) -> dict[str, Any]:
    if value is None:
        return public_email_accepted_body()
    if isinstance(value, dict):
        return value
    if isinstance(value, bytes):
        value = value.decode("utf-8", errors="ignore")
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
            return decoded if isinstance(decoded, dict) else public_email_accepted_body()
        except json.JSONDecodeError:
            return public_email_accepted_body()
    return public_email_accepted_body()


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def record_from_db_row(row: Mapping[str, Any] | None) -> IdempotencyRecord | None:
    if not row:
        return None
    return IdempotencyRecord(
        status=str(row.get("idempotency_status") or row.get("status") or "unknown"),
        idempotency_id=row.get("idempotency_id") or row.get("id"),
        replay_status_code=int(row.get("replay_status_code") or 202),
        replay_body=_decode_replay_body(row.get("replay_body")),
        email_message_id=row.get("email_message_id"),
        expires_at=_parse_datetime(row.get("expires_at")),
    )


class EmailIdempotencyManager:
    """Thin coordinator: MySQL first, Redis replay cache second."""

    def __init__(
        self,
        *,
        pepper: str | bytes,
        ttl_seconds: int = DEFAULT_EMAIL_IDEMPOTENCY_TTL_SECONDS,
        redis=None,
    ) -> None:
        self.pepper = pepper
        self.ttl_seconds = max(1, int(ttl_seconds))
        self.redis = redis

    def _expires_at(self, now: datetime | None = None) -> datetime:
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        return current + timedelta(seconds=self.ttl_seconds)

    def _cache_set(self, scope: str, key_hash: bytes, record: IdempotencyRecord) -> None:
        if self.redis is None or record.status != "complete":
            return
        try:
            self.redis.set(
                cache_key_for_replay(scope, key_hash),
                json.dumps(
                    {
                        "status": record.status,
                        "idempotency_id": record.idempotency_id,
                        "replay_status_code": record.replay_status_code,
                        "replay_body": record.replay_body,
                        "email_message_id": record.email_message_id,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                    default=_json_default,
                ),
                ex=self.ttl_seconds,
            )
        except Exception:
            # Cache is an optimization; DB idempotency remains authoritative.
            return

    def cached_replay(self, *, scope: str, key_hash: bytes) -> IdempotencyRecord | None:
        if self.redis is None:
            return None
        try:
            raw = self.redis.get(cache_key_for_replay(scope, key_hash))
        except Exception:
            return None
        if raw is None:
            return None
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            decoded = json.loads(raw)
        except json.JSONDecodeError:
            return None
        return record_from_db_row(decoded)

    def begin(
        self,
        *,
        idempotency_id: str,
        raw_key: str | None,
        scope: str,
        user_id: str | None,
        recipient_hash: bytes | None,
        body: Mapping[str, Any] | None,
        replay_body: Mapping[str, Any] | None = None,
        now: datetime | None = None,
    ) -> IdempotencyRecord | None:
        key = validate_idempotency_key(raw_key)
        if key is None:
            return None

        key_hash = hash_idempotency_key(key, pepper=self.pepper)
        request_hash = request_fingerprint(
            scope=scope,
            user_id=user_id,
            recipient_hash=recipient_hash,
            body=body,
            pepper=self.pepper,
        )

        from src.Util.db import db_email

        row = db_email.begin_email_idempotency(
            idempotency_id=idempotency_id,
            scope=scope,
            key_hash=key_hash,
            request_hash=request_hash,
            user_id=user_id,
            recipient_hash=recipient_hash,
            expires_at=self._expires_at(now),
            replay_body=replay_body_or_default(replay_body),
        )
        record = record_from_db_row(row)
        if record:
            self._cache_set(scope, key_hash, record)
        return record

    def complete(
        self,
        *,
        raw_key: str,
        scope: str,
        email_message_id: str | None,
        replay_status_code: int = 202,
        replay_body: Mapping[str, Any] | None = None,
    ) -> IdempotencyRecord:
        key_hash = hash_idempotency_key(raw_key, pepper=self.pepper)
        body = replay_body_or_default(replay_body)

        from src.Util.db import db_email

        db_email.complete_email_idempotency(
            scope=scope,
            key_hash=key_hash,
            email_message_id=email_message_id,
            replay_status_code=replay_status_code,
            replay_body=body,
        )
        record = IdempotencyRecord(
            status="complete",
            idempotency_id=None,
            replay_status_code=replay_status_code,
            replay_body=body,
            email_message_id=email_message_id,
        )
        self._cache_set(scope, key_hash, record)
        return record

    def get(self, *, raw_key: str, scope: str) -> IdempotencyRecord | None:
        key_hash = hash_idempotency_key(raw_key, pepper=self.pepper)
        cached = self.cached_replay(scope=scope, key_hash=key_hash)
        if cached:
            return cached

        from src.Util.db import db_email

        record = record_from_db_row(db_email.get_email_idempotency(scope=scope, key_hash=key_hash))
        if record:
            self._cache_set(scope, key_hash, record)
        return record


__all__ = [
    "EmailIdempotencyManager",
    "IDEMPOTENCY_HASH_VERSION",
    "IDEMPOTENCY_KEY_MAX_LENGTH",
    "IdempotencyKeyError",
    "IdempotencyRecord",
    "cache_key_for_replay",
    "hash_idempotency_key",
    "record_from_db_row",
    "replay_body_or_default",
    "request_fingerprint",
    "validate_idempotency_key",
]
