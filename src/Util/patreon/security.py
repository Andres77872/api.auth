"""Patreon security and privacy primitives.

Trace: SDD change ``patreon-account-link`` tasks 3.4 and requirements for
HMAC provider identity, hash-only proof tokens, raw-body HMAC-MD5 webhook
verification, constant-time S2S bearer comparison, delivery hashes, and
Patreon redaction helpers.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from src.Util import auth_constants as constants


HASH_VERSION = "v1"
PATREON_PROOF_PURPOSE = "patreon_link_proof"
LOOKUP_ID_BYTES = 9  # 9 bytes => 12 URL-safe base64 chars without padding.
SECRET_BYTES = 32  # 32 bytes => 43 URL-safe base64 chars without padding.
WEBHOOK_MD5_HEX_RE = re.compile(r"^[a-fA-F0-9]{32}$")
REDACTED = "[REDACTED]"
PATREON_REDACTION_FIELD_NAMES = constants.PATREON_REDACTION_FIELD_NAMES
PATREON_REDACTION_HEADER_NAMES = constants.PATREON_REDACTION_HEADER_NAMES


@dataclass(frozen=True)
class GeneratedPatreonProofToken:
    """Reveal-once split proof token material and hash-only DB values."""

    lookup_id: str
    secret: str = field(repr=False)
    token: str = field(repr=False)
    token_hash: bytes = field(repr=False)
    token_fingerprint: str
    expires_at: datetime


def _urlsafe_token(num_bytes: int) -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(num_bytes)).rstrip(b"=").decode("ascii")


def _ensure_bytes(value: str | bytes, *, name: str) -> bytes:
    if isinstance(value, bytes):
        if not value:
            raise ValueError(f"{name} must not be empty")
        return value
    if isinstance(value, str) and value.strip():
        return value.encode("utf-8")
    raise ValueError(f"{name} must not be empty")


def _ensure_raw_body(value: bytes | bytearray | memoryview, *, name: str = "raw_body") -> bytes:
    if isinstance(value, bytes):
        return value
    if isinstance(value, (bytearray, memoryview)):
        return bytes(value)
    raise TypeError(f"{name} must be exact raw bytes")


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _first_text(*values: str | None, name: str) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError(f"{name} must not be empty")


def normalize_patreon_email(email: str) -> str:
    """Normalize Patreon email for HMAC identity only: LOWER(TRIM(email))."""

    return str(email or "").strip().lower()


def hash_patreon_identifier(
    *,
    raw_id: str | None = None,
    identifier: str | None = None,
    value: str | None = None,
    kind: str = "user",
    pepper: str | bytes,
) -> bytes:
    """Return HMAC-SHA-256 authority bytes for a raw Patreon provider ID."""

    provider_id = _first_text(raw_id, identifier, value, name="raw Patreon identifier")
    kind_value = _first_text(kind, name="Patreon identifier kind").lower()
    material = f"patreon:{kind_value}:{provider_id}".encode("utf-8")
    return hmac.digest(_ensure_bytes(pepper, name="pepper"), material, "sha256")


def hash_patreon_id(
    *,
    raw_id: str | None = None,
    identifier: str | None = None,
    value: str | None = None,
    kind: str = "user",
    pepper: str | bytes,
) -> bytes:
    return hash_patreon_identifier(raw_id=raw_id, identifier=identifier, value=value, kind=kind, pepper=pepper)


def hash_provider_identifier(
    *,
    raw_id: str | None = None,
    identifier: str | None = None,
    value: str | None = None,
    kind: str = "user",
    pepper: str | bytes,
) -> bytes:
    return hash_patreon_identifier(raw_id=raw_id, identifier=identifier, value=value, kind=kind, pepper=pepper)


def fingerprint_from_digest(digest: bytes) -> str:
    """Return the short non-reversible support marker used by DB rows."""

    if not isinstance(digest, bytes) or len(digest) < 6:
        raise ValueError("digest must contain at least 6 bytes")
    return digest.hex()[:12]


def fingerprint_patreon_identifier(
    *,
    raw_id: str | None = None,
    identifier: str | None = None,
    value: str | None = None,
    kind: str = "user",
    pepper: str | bytes,
) -> str:
    """Return a 12-hex-character support fingerprint for a Patreon ID."""

    digest = hash_patreon_identifier(
        raw_id=raw_id,
        identifier=identifier,
        value=value,
        kind=kind,
        pepper=pepper,
    )
    return fingerprint_from_digest(digest)


def fingerprint_patreon_id(
    *,
    raw_id: str | None = None,
    identifier: str | None = None,
    value: str | None = None,
    kind: str = "user",
    pepper: str | bytes,
) -> str:
    return fingerprint_patreon_identifier(
        raw_id=raw_id,
        identifier=identifier,
        value=value,
        kind=kind,
        pepper=pepper,
    )


def fingerprint_provider_identifier(
    *,
    raw_id: str | None = None,
    identifier: str | None = None,
    value: str | None = None,
    kind: str = "user",
    pepper: str | bytes,
) -> str:
    return fingerprint_patreon_identifier(
        raw_id=raw_id,
        identifier=identifier,
        value=value,
        kind=kind,
        pepper=pepper,
    )


def hash_patreon_email(
    *,
    email: str | None = None,
    raw_email: str | None = None,
    value: str | None = None,
    pepper: str | bytes,
) -> bytes:
    """Return HMAC-SHA-256 bytes for a normalized Patreon email."""

    normalized = normalize_patreon_email(_first_text(email, raw_email, value, name="Patreon email"))
    return hmac.digest(_ensure_bytes(pepper, name="pepper"), normalized.encode("utf-8"), "sha256")


def hash_provider_email(
    *,
    email: str | None = None,
    raw_email: str | None = None,
    value: str | None = None,
    pepper: str | bytes,
) -> bytes:
    return hash_patreon_email(email=email, raw_email=raw_email, value=value, pepper=pepper)


def mask_patreon_email(email: str) -> str:
    """Return a display-safe mask for server-side support views only."""

    normalized = normalize_patreon_email(email)
    if "@" not in normalized:
        return "***"
    local, domain = normalized.rsplit("@", 1)
    if not local:
        masked_local = "***"
    elif len(local) == 1:
        masked_local = "*"
    elif len(local) == 2:
        masked_local = f"{local[0]}*"
    else:
        masked_local = f"{local[0]}***{local[-1]}"
    return f"{masked_local}@{domain}"


def hash_patreon_proof_token(
    *,
    lookup_id: str,
    secret: str,
    pepper: str | bytes,
    purpose: str = PATREON_PROOF_PURPOSE,
) -> bytes:
    """Compute hash-at-rest verifier for a split Patreon proof token."""

    lookup = _first_text(lookup_id, name="lookup_id")
    secret_value = _first_text(secret, name="secret")
    purpose_value = _first_text(purpose, name="purpose")
    material = f"{HASH_VERSION}:{purpose_value}:{lookup}:{secret_value}".encode("utf-8")
    return hmac.digest(_ensure_bytes(pepper, name="pepper"), material, "sha256")


def hash_proof_token(
    *,
    lookup_id: str,
    secret: str,
    pepper: str | bytes,
    purpose: str = PATREON_PROOF_PURPOSE,
) -> bytes:
    return hash_patreon_proof_token(
        lookup_id=lookup_id,
        secret=secret,
        pepper=pepper,
        purpose=purpose,
    )


def hash_link_proof_token(
    *,
    lookup_id: str,
    secret: str,
    pepper: str | bytes,
    purpose: str = PATREON_PROOF_PURPOSE,
) -> bytes:
    return hash_patreon_proof_token(
        lookup_id=lookup_id,
        secret=secret,
        pepper=pepper,
        purpose=purpose,
    )


def generate_patreon_proof_token(
    *,
    ttl_seconds: int,
    pepper: str | bytes,
    purpose: str = PATREON_PROOF_PURPOSE,
    now: datetime | None = None,
) -> GeneratedPatreonProofToken:
    """Generate split proof token URL material and hash-only persistence values."""

    issued_at = _ensure_aware_utc(now or datetime.now(timezone.utc))
    lookup_id = _urlsafe_token(LOOKUP_ID_BYTES)
    secret = _urlsafe_token(SECRET_BYTES)
    token = f"{lookup_id}.{secret}"
    token_hash = hash_patreon_proof_token(
        purpose=purpose,
        lookup_id=lookup_id,
        secret=secret,
        pepper=pepper,
    )
    token_fingerprint = hashlib.blake2s(token.encode("utf-8"), digest_size=6).hexdigest()
    return GeneratedPatreonProofToken(
        lookup_id=lookup_id,
        secret=secret,
        token=token,
        token_hash=token_hash,
        token_fingerprint=token_fingerprint,
        expires_at=issued_at + timedelta(seconds=ttl_seconds),
    )


def generate_proof_token(
    *,
    ttl_seconds: int,
    pepper: str | bytes,
    purpose: str = PATREON_PROOF_PURPOSE,
    now: datetime | None = None,
) -> GeneratedPatreonProofToken:
    return generate_patreon_proof_token(
        ttl_seconds=ttl_seconds,
        pepper=pepper,
        purpose=purpose,
        now=now,
    )


def generate_link_proof_token(
    *,
    ttl_seconds: int,
    pepper: str | bytes,
    purpose: str = PATREON_PROOF_PURPOSE,
    now: datetime | None = None,
) -> GeneratedPatreonProofToken:
    return generate_patreon_proof_token(
        ttl_seconds=ttl_seconds,
        pepper=pepper,
        purpose=purpose,
        now=now,
    )


def parse_patreon_proof_token(token: str) -> tuple[str, str] | None:
    """Parse ``lookup_id.secret`` proof material without verifying it."""

    if not isinstance(token, str) or "." not in token:
        return None
    lookup_id, secret = token.rsplit(".", 1)
    if not lookup_id or not secret:
        return None
    return lookup_id, secret


def _dummy_proof_hash(pepper: str | bytes) -> bytes:
    return hmac.digest(_ensure_bytes(pepper, name="pepper"), b"v1:patreon_link_proof:invalid:invalid", "sha256")


def verify_patreon_proof_token(
    *,
    token: str,
    expected_hash: bytes,
    expires_at: datetime,
    pepper: str | bytes,
    purpose: str = PATREON_PROOF_PURPOSE,
    now: datetime | None = None,
) -> bool:
    """Verify proof material with constant-time hash comparison on all paths."""

    parsed = parse_patreon_proof_token(token)
    if parsed is None:
        candidate = _dummy_proof_hash(pepper)
    else:
        lookup_id, secret = parsed
        candidate = hash_patreon_proof_token(
            purpose=purpose,
            lookup_id=lookup_id,
            secret=secret,
            pepper=pepper,
        )
    matches = hmac.compare_digest(candidate, expected_hash)
    current_time = _ensure_aware_utc(now or datetime.now(timezone.utc))
    expiry = _ensure_aware_utc(expires_at)
    return bool(parsed is not None and matches and current_time <= expiry)


def verify_s2s_bearer_token(
    *,
    presented: str | None = None,
    expected: str | None = None,
    presented_token: str | None = None,
    expected_token: str | None = None,
) -> bool:
    """Compare dedicated internal S2S bearer tokens using constant-time compare."""

    left = presented if presented is not None else presented_token
    right = expected if expected is not None else expected_token
    left_text = "" if left is None else str(left)
    right_text = "" if right is None else str(right)
    matches = hmac.compare_digest(left_text, right_text)
    return bool(left_text and right_text and matches)


def constant_time_s2s_token_equals(
    *,
    presented: str | None = None,
    expected: str | None = None,
    presented_token: str | None = None,
    expected_token: str | None = None,
) -> bool:
    return verify_s2s_bearer_token(
        presented=presented,
        expected=expected,
        presented_token=presented_token,
        expected_token=expected_token,
    )


def verify_internal_bearer_token(
    *,
    presented: str | None = None,
    expected: str | None = None,
    presented_token: str | None = None,
    expected_token: str | None = None,
) -> bool:
    return verify_s2s_bearer_token(
        presented=presented,
        expected=expected,
        presented_token=presented_token,
        expected_token=expected_token,
    )


def compute_patreon_webhook_signature(
    *,
    raw_body: bytes | bytearray | memoryview | None = None,
    body: bytes | bytearray | memoryview | None = None,
    secret: str | bytes,
) -> str:
    """Return Patreon's HMAC-MD5 hex digest over exact raw request bytes."""

    payload = _ensure_raw_body(raw_body if raw_body is not None else body)
    return hmac.new(_ensure_bytes(secret, name="webhook secret"), payload, "md5").hexdigest()


def compute_webhook_signature(
    *,
    raw_body: bytes | bytearray | memoryview | None = None,
    body: bytes | bytearray | memoryview | None = None,
    secret: str | bytes,
) -> str:
    return compute_patreon_webhook_signature(raw_body=raw_body, body=body, secret=secret)


def verify_patreon_webhook_signature(
    *,
    raw_body: bytes | bytearray | memoryview | None = None,
    body: bytes | bytearray | memoryview | None = None,
    signature: str | None,
    secret: str | bytes,
) -> bool:
    """Verify Patreon HMAC-MD5 signature without normalizing the body."""

    try:
        actual = compute_patreon_webhook_signature(raw_body=raw_body, body=body, secret=secret)
    except (TypeError, ValueError):
        hmac.compare_digest("0" * 32, "1" * 32)
        return False

    candidate = str(signature or "").strip().lower()
    valid_shape = bool(WEBHOOK_MD5_HEX_RE.fullmatch(candidate))
    compared = candidate if valid_shape else "0" * 32
    matches = hmac.compare_digest(actual, compared)
    return bool(valid_shape and matches)


def verify_webhook_signature(
    *,
    raw_body: bytes | bytearray | memoryview | None = None,
    body: bytes | bytearray | memoryview | None = None,
    signature: str | None,
    secret: str | bytes,
) -> bool:
    return verify_patreon_webhook_signature(raw_body=raw_body, body=body, signature=signature, secret=secret)


def raw_body_sha256(raw_body: bytes | bytearray | memoryview) -> bytes:
    """Return SHA-256 digest bytes for exact raw webhook/provider body bytes."""

    return hashlib.sha256(_ensure_raw_body(raw_body)).digest()


def raw_body_sha256_hex(raw_body: bytes | bytearray | memoryview) -> str:
    return raw_body_sha256(raw_body).hex()


def compute_patreon_delivery_hash(
    *,
    event_type: str,
    raw_body: bytes | bytearray | memoryview,
    member_id: str | None = None,
    member_reference: str | None = None,
    campaign_id: str | None = None,
    pepper: str | bytes | None = None,
) -> bytes:
    """Return local webhook idempotency hash without storing raw provider IDs in logs.

    The material intentionally uses event type, optional member/campaign reference,
    and the raw-body SHA-256 digest.  Raw body bytes are never embedded in the
    returned value.
    """

    event = _first_text(event_type, name="event_type")
    member = (member_id or member_reference or "").strip()
    campaign = (campaign_id or "").strip()
    body_digest = raw_body_sha256_hex(raw_body)
    material = f"{HASH_VERSION}:patreon_delivery:{event}:{member}:{campaign}:{body_digest}".encode(
        "utf-8"
    )
    if pepper:
        return hmac.digest(_ensure_bytes(pepper, name="delivery pepper"), material, "sha256")
    return hashlib.sha256(material).digest()


def compute_delivery_hash(
    *,
    event_type: str,
    raw_body: bytes | bytearray | memoryview,
    member_id: str | None = None,
    member_reference: str | None = None,
    campaign_id: str | None = None,
    pepper: str | bytes | None = None,
) -> bytes:
    return compute_patreon_delivery_hash(
        event_type=event_type,
        raw_body=raw_body,
        member_id=member_id,
        member_reference=member_reference,
        campaign_id=campaign_id,
        pepper=pepper,
    )


def patreon_redaction_field_names() -> tuple[str, ...]:
    return tuple(PATREON_REDACTION_FIELD_NAMES)


def patreon_redaction_header_names() -> tuple[str, ...]:
    return tuple(PATREON_REDACTION_HEADER_NAMES)


def is_patreon_sensitive_field(name: str) -> bool:
    normalized = str(name or "").strip().lower()
    return normalized in {field.lower() for field in PATREON_REDACTION_FIELD_NAMES}


def redact_patreon_mapping(value: Any) -> Any:
    """Recursively redact configured Patreon-sensitive field names."""

    if isinstance(value, Mapping):
        redacted: dict[Any, Any] = {}
        for key, item in value.items():
            if is_patreon_sensitive_field(str(key)):
                redacted[key] = REDACTED
            else:
                redacted[key] = redact_patreon_mapping(item)
        return redacted
    if isinstance(value, list):
        return [redact_patreon_mapping(item) for item in value]
    if isinstance(value, tuple):
        return tuple(redact_patreon_mapping(item) for item in value)
    return value


def sanitize_patreon_log_value(value: Any) -> str:
    """Best-effort redaction for free-form Patreon log/error text."""

    text = str(value or "")
    if not text:
        return text
    field_pattern = "|".join(re.escape(field) for field in sorted(PATREON_REDACTION_FIELD_NAMES, key=len, reverse=True))
    sanitized = re.sub(
        rf"\b({field_pattern})\b\s*[:=]\s*\S+",
        lambda match: f"{match.group(1)}={REDACTED}",
        text,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        REDACTED,
        sanitized,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"\b[a-f0-9]{32}\b", REDACTED, sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(r"\b[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b", REDACTED, sanitized)
    return sanitized
