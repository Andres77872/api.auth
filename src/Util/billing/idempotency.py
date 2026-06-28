"""Provider-agnostic billing idempotency helpers.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 4.6.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping


IDEMPOTENCY_HASH_VERSION = "v1"
IDEMPOTENCY_KEY_MAX_LENGTH = 128
IDEMPOTENCY_KEY_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
INTERNAL_REF_RE = re.compile(r"^(?:bco|bpo|bcu|bsub|bpur|bsj|bcat)-[A-Za-z0-9._:-]{6,128}$")
RAW_PROVIDER_REF_RE = re.compile(r"^(?:cus|sub|price|prod|in|pi|ch|cs|bps|evt)_[A-Za-z0-9_]+")


class BillingIdempotencyError(ValueError):
    """Raised for invalid billing idempotency inputs without echoing keys."""


@dataclass(frozen=True)
class BillingIdempotencyHash:
    digest: bytes = field(repr=False)
    scope: str
    fingerprint: str


@dataclass(frozen=True)
class BillingIdempotencyDecision:
    status: str
    replay: bool = False
    conflict: bool = False
    request_hash: bytes | None = field(default=None, repr=False)

    @property
    def is_replay(self) -> bool:
        return self.replay

    @property
    def is_conflict(self) -> bool:
        return self.conflict


def _ensure_bytes(value: str | bytes | None, *, name: str) -> bytes:
    if isinstance(value, bytes) and value:
        return value
    if isinstance(value, str) and value.strip():
        return value.encode("utf-8")
    raise BillingIdempotencyError(f"{name} must not be empty")


def _json_default(value: Any) -> str:
    if isinstance(value, (bytes, bytearray, memoryview)):
        return bytes(value).hex()
    if isinstance(value, datetime):
        if value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value.astimezone(timezone.utc).isoformat()
    return str(value)


def canonical_json(value: Any) -> str:
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError:
            return value.strip()
        return json.dumps(parsed, sort_keys=True, separators=(",", ":"), default=_json_default)
    return json.dumps(value or {}, sort_keys=True, separators=(",", ":"), default=_json_default)


def validate_idempotency_key(raw_key: str | None) -> str | None:
    if raw_key is None:
        return None
    key = str(raw_key).strip()
    if not key:
        return None
    if len(key) > IDEMPOTENCY_KEY_MAX_LENGTH or not IDEMPOTENCY_KEY_RE.fullmatch(key):
        raise BillingIdempotencyError("invalid billing Idempotency-Key")
    return key


def build_billing_idempotency_scope(*, route: str, provider: str, user_id: str, project_id: str) -> str:
    parts = [route, provider, user_id, project_id]
    cleaned = [str(part or "").strip().lower() for part in parts]
    if not all(cleaned):
        raise BillingIdempotencyError("billing idempotency scope is incomplete")
    return f"billing:{cleaned[0]}:{cleaned[1]}:{cleaned[2]}:{cleaned[3]}"


def hash_s2s_idempotency_key(
    *,
    route: str | None = None,
    provider: str | None = None,
    user_id: str | None = None,
    project_id: str | None = None,
    idempotency_key: str | None = None,
    secret: str | bytes | None = None,
    scope: str | None = None,
    raw_key: str | None = None,
) -> bytes:
    resolved_key = validate_idempotency_key(idempotency_key if idempotency_key is not None else raw_key)
    if not resolved_key:
        raise BillingIdempotencyError("billing Idempotency-Key is required")
    resolved_scope = scope or build_billing_idempotency_scope(
        route=route or "",
        provider=provider or "",
        user_id=user_id or "",
        project_id=project_id or "",
    )
    material = f"{IDEMPOTENCY_HASH_VERSION}:{resolved_scope}:{resolved_key}".encode("utf-8")
    return hmac.digest(_ensure_bytes(secret, name="billing idempotency secret"), material, "sha256")


def derive_s2s_idempotency_hash(**kwargs: Any) -> bytes:
    return hash_s2s_idempotency_key(**kwargs)


def billing_idempotency_hmac(**kwargs: Any) -> bytes:
    return hash_s2s_idempotency_key(**kwargs)


def idempotency_hash_result(**kwargs: Any) -> BillingIdempotencyHash:
    digest = hash_s2s_idempotency_key(**kwargs)
    scope = kwargs.get("scope") or build_billing_idempotency_scope(
        route=kwargs.get("route") or "",
        provider=kwargs.get("provider") or "",
        user_id=kwargs.get("user_id") or "",
        project_id=kwargs.get("project_id") or "",
    )
    return BillingIdempotencyHash(digest=digest, scope=scope, fingerprint=digest.hex()[:12])


def canonical_request_hash(
    *,
    payload: Any = None,
    body: Any = None,
    canonical_json: str | None = None,
) -> bytes:
    canonical = canonical_json if canonical_json is not None else globals()["canonical_json"](payload if payload is not None else body)
    return hashlib.sha256(str(canonical).encode("utf-8")).digest()


def hash_canonical_request(**kwargs: Any) -> bytes:
    return canonical_request_hash(**kwargs)


def canonical_billing_request_hash(**kwargs: Any) -> bytes:
    return canonical_request_hash(**kwargs)


def compare_idempotent_request(
    *,
    stored_request_hash: bytes | str | None,
    candidate_request_hash: bytes | str | None,
) -> BillingIdempotencyDecision:
    stored = bytes.fromhex(stored_request_hash) if isinstance(stored_request_hash, str) and re.fullmatch(r"[a-fA-F0-9]{64}", stored_request_hash) else stored_request_hash
    candidate = bytes.fromhex(candidate_request_hash) if isinstance(candidate_request_hash, str) and re.fullmatch(r"[a-fA-F0-9]{64}", candidate_request_hash) else candidate_request_hash
    if stored is None:
        return BillingIdempotencyDecision(status="new", request_hash=candidate if isinstance(candidate, bytes) else None)
    if isinstance(stored, bytes) and isinstance(candidate, bytes) and hmac.compare_digest(stored, candidate):
        return BillingIdempotencyDecision(status="replay", replay=True, request_hash=candidate)
    return BillingIdempotencyDecision(status="conflict", conflict=True, request_hash=candidate if isinstance(candidate, bytes) else None)


def _validate_internal_ref(internal_ref: str) -> str:
    value = str(internal_ref or "").strip()
    if RAW_PROVIDER_REF_RE.match(value):
        raise BillingIdempotencyError("raw provider refs cannot be used as provider API idempotency keys")
    if not INTERNAL_REF_RE.fullmatch(value):
        raise BillingIdempotencyError("internal opaque billing ref is required")
    return value


def derive_provider_api_idempotency_key(
    *,
    internal_ref: str,
    operation: str,
    provider: str = "stripe",
) -> str:
    ref = _validate_internal_ref(internal_ref)
    op = str(operation or "").strip().lower()
    prov = str(provider or "").strip().lower()
    if not op or not prov:
        raise BillingIdempotencyError("provider API idempotency operation scope is required")
    digest = hashlib.sha256(f"{IDEMPOTENCY_HASH_VERSION}:{prov}:{op}:{ref}".encode("utf-8")).hexdigest()[:32]
    return f"api-auth-{prov}-{op}-{digest}"


def derive_stripe_api_idempotency_key(*, internal_ref: str, operation: str) -> str:
    return derive_provider_api_idempotency_key(internal_ref=internal_ref, operation=operation, provider="stripe")


def webhook_event_id_hmac(*, provider: str, event_id: str, secret: str | bytes) -> bytes:
    prov = str(provider or "").strip().lower()
    event = str(event_id or "").strip()
    if not prov or not event:
        raise BillingIdempotencyError("provider webhook event scope is incomplete")
    material = f"{IDEMPOTENCY_HASH_VERSION}:webhook:{prov}:{event}".encode("utf-8")
    return hmac.digest(_ensure_bytes(secret, name="billing event HMAC secret"), material, "sha256")


__all__ = [
    "BillingIdempotencyDecision",
    "BillingIdempotencyError",
    "BillingIdempotencyHash",
    "IDEMPOTENCY_HASH_VERSION",
    "build_billing_idempotency_scope",
    "billing_idempotency_hmac",
    "canonical_billing_request_hash",
    "canonical_json",
    "canonical_request_hash",
    "compare_idempotent_request",
    "derive_provider_api_idempotency_key",
    "derive_s2s_idempotency_hash",
    "derive_stripe_api_idempotency_key",
    "hash_canonical_request",
    "hash_s2s_idempotency_key",
    "idempotency_hash_result",
    "validate_idempotency_key",
    "webhook_event_id_hmac",
]
