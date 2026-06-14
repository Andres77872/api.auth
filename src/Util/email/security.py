"""Security helpers for transactional auth email.

Trace:
- SDD email-activation spec: secure link tokens, hash-at-rest semantics,
  normalized email identity, redaction, and encrypted transient render payloads.
- Design decision: split token URL material with HMAC-SHA-256 peppered hashes.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

try:  # pragma: no cover - exercised when dependency is installed.
    from cryptography.fernet import Fernet
except Exception:  # pragma: no cover - local test env may not have deps installed yet.
    Fernet = None  # type: ignore


HASH_VERSION = "v1"
LOOKUP_ID_BYTES = 9  # 9 bytes -> 12 base64url chars without padding.
SECRET_BYTES = 32  # 32 bytes -> 43 base64url chars without padding.
TERMINAL_MESSAGE_STATUSES = {
    "sent",
    "delivered",
    "bounced",
    "complained",
    "suppressed",
    "dead",
    "cancelled",
}
REDACTED = "[REDACTED]"


@dataclass(frozen=True)
class GeneratedLinkToken:
    """One-time return value for a newly generated email link token.

    `secret` and `token` are reveal-once values for URL construction only.  DB
    rows must persist `lookup_id`, `token_hash`, `token_fingerprint`, and expiry
    metadata, never the plaintext secret.
    """

    lookup_id: str
    secret: str
    token: str
    token_hash: bytes
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


def _ensure_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def normalize_email(email: str) -> str:
    """Normalize email identity using the spec-required LOWER(TRIM(email))."""

    return str(email or "").strip().lower()


def mask_email(email: str) -> str:
    """Return a display-safe masked email without exposing the full local part."""

    normalized = normalize_email(email)
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


def hash_email(email: str, *, pepper: str | bytes) -> bytes:
    """Hash a normalized email with server-side HMAC-SHA-256 pepper."""

    return hmac.digest(_ensure_bytes(pepper, name="pepper"), normalize_email(email).encode("utf-8"), "sha256")


def hash_link_token(*, purpose: str, lookup_id: str, secret: str, pepper: str | bytes) -> bytes:
    """Compute the hash-at-rest verifier for a split email link token."""

    material = f"{HASH_VERSION}:{purpose}:{lookup_id}:{secret}".encode("utf-8")
    return hmac.digest(_ensure_bytes(pepper, name="pepper"), material, "sha256")


def parse_link_token(token: str) -> tuple[str, str] | None:
    """Parse `lookup_id.secret` token material without validating it."""

    if not isinstance(token, str) or "." not in token:
        return None
    lookup_id, secret = token.rsplit(".", 1)
    if not lookup_id or not secret:
        return None
    return lookup_id, secret


def generate_link_token(
    *,
    purpose: str,
    ttl_seconds: int,
    pepper: str | bytes,
    now: datetime | None = None,
) -> GeneratedLinkToken:
    """Generate split token URL material and its hash-only persistence values."""

    issued_at = _ensure_aware_utc(now or datetime.now(timezone.utc))
    lookup_id = _urlsafe_token(LOOKUP_ID_BYTES)
    secret = _urlsafe_token(SECRET_BYTES)
    token = f"{lookup_id}.{secret}"
    token_hash = hash_link_token(purpose=purpose, lookup_id=lookup_id, secret=secret, pepper=pepper)
    token_fingerprint = hashlib.blake2s(token.encode("utf-8"), digest_size=6).hexdigest()
    return GeneratedLinkToken(
        lookup_id=lookup_id,
        secret=secret,
        token=token,
        token_hash=token_hash,
        token_fingerprint=token_fingerprint,
        expires_at=issued_at + timedelta(seconds=ttl_seconds),
    )


def _dummy_link_hash(pepper: str | bytes) -> bytes:
    return hmac.digest(_ensure_bytes(pepper, name="pepper"), b"v1:invalid:invalid:invalid", "sha256")


def verify_link_token(
    *,
    token: str,
    purpose: str,
    expected_hash: bytes,
    expires_at: datetime,
    pepper: str | bytes,
    now: datetime | None = None,
) -> bool:
    """Verify a presented link token with constant-time compare on all paths."""

    parsed = parse_link_token(token)
    if parsed is None:
        return hmac.compare_digest(_dummy_link_hash(pepper), expected_hash)

    lookup_id, secret = parsed
    candidate = hash_link_token(purpose=purpose, lookup_id=lookup_id, secret=secret, pepper=pepper)
    matches = hmac.compare_digest(candidate, expected_hash)
    current_time = _ensure_aware_utc(now or datetime.now(timezone.utc))
    expiry = _ensure_aware_utc(expires_at)
    return bool(matches and current_time <= expiry)


def validate_payload_key(key: str | bytes) -> bytes:
    """Validate a Fernet-compatible URL-safe base64 32-byte payload key."""

    key_bytes = key if isinstance(key, bytes) else key.encode("ascii")
    try:
        decoded = base64.urlsafe_b64decode(key_bytes)
    except Exception as exc:
        raise ValueError("payload key must be URL-safe base64") from exc
    if len(decoded) != 32:
        raise ValueError("payload key must decode to exactly 32 bytes")
    return decoded


class _FallbackPayloadCipher:
    """Small authenticated fallback used only when cryptography is unavailable.

    Production installs should use cryptography's Fernet implementation.  The
    fallback still keeps test payloads confidential and tamper-checked using
    stdlib HMAC-derived keystream blocks, so no plaintext link/recipient values
    appear in durable ciphertext during local targeted tests.
    """

    VERSION = b"EPL1"

    def __init__(self, key: str | bytes) -> None:
        self._key = validate_payload_key(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = secrets.token_bytes(16)
        ciphertext = self._xor_with_keystream(plaintext, nonce)
        tag = hmac.digest(self._key, self.VERSION + nonce + ciphertext, "sha256")
        return base64.urlsafe_b64encode(self.VERSION + nonce + tag + ciphertext)

    def decrypt(self, token: bytes | str) -> bytes:
        token_bytes = token if isinstance(token, bytes) else token.encode("ascii")
        decoded = base64.urlsafe_b64decode(token_bytes)
        if len(decoded) < len(self.VERSION) + 16 + 32 or not decoded.startswith(self.VERSION):
            raise ValueError("invalid render payload ciphertext")
        offset = len(self.VERSION)
        nonce = decoded[offset : offset + 16]
        offset += 16
        expected_tag = decoded[offset : offset + 32]
        offset += 32
        ciphertext = decoded[offset:]
        actual_tag = hmac.digest(self._key, self.VERSION + nonce + ciphertext, "sha256")
        if not hmac.compare_digest(actual_tag, expected_tag):
            raise ValueError("invalid render payload ciphertext")
        return self._xor_with_keystream(ciphertext, nonce)

    def _xor_with_keystream(self, data: bytes, nonce: bytes) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < len(data):
            block = hmac.digest(self._key, nonce + counter.to_bytes(4, "big"), "sha256")
            output.extend(block)
            counter += 1
        return bytes(left ^ right for left, right in zip(data, output))


def _payload_cipher(key: str | bytes):
    key_bytes = key if isinstance(key, bytes) else key.encode("ascii")
    if Fernet is not None:
        return Fernet(key_bytes)
    return _FallbackPayloadCipher(key)


def encrypt_render_payload(payload: Mapping[str, Any], *, key: str | bytes) -> bytes:
    """Encrypt transient render payload variables for durable outbox storage."""

    plaintext = json.dumps(dict(payload), sort_keys=True, separators=(",", ":"), default=str).encode("utf-8")
    return _payload_cipher(key).encrypt(plaintext)


def decrypt_render_payload(ciphertext: bytes, *, key: str | bytes) -> dict[str, Any]:
    """Decrypt transient render payload variables in worker memory."""

    plaintext = _payload_cipher(key).decrypt(ciphertext)
    decoded = json.loads(plaintext.decode("utf-8"))
    if not isinstance(decoded, dict):
        raise ValueError("render payload must decrypt to a JSON object")
    return decoded


def purge_render_payload_if_due(message: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    """Return a copy with ciphertext cleared once terminal purge time is due."""

    updated = dict(message)
    purge_at = updated.get("payload_purge_at")
    status = str(updated.get("status") or "").lower()
    if not isinstance(purge_at, datetime):
        return updated

    current_time = _ensure_aware_utc(now or datetime.now(timezone.utc))
    if status in TERMINAL_MESSAGE_STATUSES and current_time >= _ensure_aware_utc(purge_at):
        updated["render_payload_ciphertext"] = None
    return updated


def sanitize_email_log_value(value: Any) -> str:
    """Redact token/link/email/idempotency material from free-form log values."""

    text = str(value or "")
    if not text:
        return text

    sanitized = re.sub(
        r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b",
        REDACTED,
        text,
        flags=re.IGNORECASE,
    )
    sanitized = re.sub(r"https?://\S+", REDACTED, sanitized, flags=re.IGNORECASE)
    sanitized = re.sub(
        r"\b[A-Za-z0-9_-]{6,}\.[A-Za-z0-9_-]{6,}\b",
        REDACTED,
        sanitized,
    )
    sanitized = re.sub(
        r"\b(token|secret|api[_-]?key|idempotency[_-]?key|activation[_-]?link|reset[_-]?link)\s*[:=]\s*\S+",
        lambda match: f"{match.group(1)}={REDACTED}",
        sanitized,
        flags=re.IGNORECASE,
    )
    return sanitized
