"""Generic billing security, HMAC, fingerprint, and encrypted-ref helpers.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 4.5.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import re
import secrets
from dataclasses import dataclass, field
from typing import Any, Mapping

try:  # pragma: no cover - depends on runtime dependency availability.
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover - local targeted tests can use fallback.
    Fernet = None  # type: ignore[assignment]

    class InvalidToken(Exception):  # type: ignore[no-redef]
        pass


HASH_VERSION = "v1"
PROVIDER_REF_ENCRYPTION_ALGORITHM = "fernet-v1"
KEY_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")
REDACTED = "[REDACTED]"


class BillingSecurityError(RuntimeError):
    """Neutral billing security failure that does not echo secrets or refs."""


class BillingProviderRefDecryptError(BillingSecurityError):
    """Raised when provider refs cannot be decrypted in a fail-closed path."""


@dataclass(frozen=True)
class EncryptedProviderRef:
    ciphertext: bytes = field(repr=False)
    key_id: str
    algorithm: str = PROVIDER_REF_ENCRYPTION_ALGORITHM


class _FallbackProviderRefCipher:
    """Authenticated local fallback if cryptography is unavailable.

    Production installs should use Fernet. This fallback exists so targeted unit
    tests still prove no plaintext provider ref is stored in ciphertext.
    """

    VERSION = b"BPR1"

    def __init__(self, key: str | bytes) -> None:
        self._key = validate_fernet_key(key)

    def encrypt(self, plaintext: bytes) -> bytes:
        nonce = secrets.token_bytes(16)
        encrypted = self._xor_with_keystream(plaintext, nonce)
        tag = hmac.digest(self._key, self.VERSION + nonce + encrypted, "sha256")
        return base64.urlsafe_b64encode(self.VERSION + nonce + tag + encrypted)

    def decrypt(self, token: bytes | str) -> bytes:
        token_bytes = token if isinstance(token, bytes) else token.encode("ascii")
        try:
            decoded = base64.urlsafe_b64decode(token_bytes)
        except Exception as exc:
            raise InvalidToken("invalid provider ref ciphertext") from exc
        if len(decoded) < len(self.VERSION) + 16 + 32 or not decoded.startswith(self.VERSION):
            raise InvalidToken("invalid provider ref ciphertext")
        offset = len(self.VERSION)
        nonce = decoded[offset : offset + 16]
        offset += 16
        expected_tag = decoded[offset : offset + 32]
        offset += 32
        encrypted = decoded[offset:]
        actual_tag = hmac.digest(self._key, self.VERSION + nonce + encrypted, "sha256")
        if not hmac.compare_digest(actual_tag, expected_tag):
            raise InvalidToken("invalid provider ref ciphertext")
        return self._xor_with_keystream(encrypted, nonce)

    def _xor_with_keystream(self, data: bytes, nonce: bytes) -> bytes:
        output = bytearray()
        counter = 0
        while len(output) < len(data):
            block = hmac.digest(self._key, nonce + counter.to_bytes(4, "big"), "sha256")
            output.extend(block)
            counter += 1
        return bytes(left ^ right for left, right in zip(data, output))


def _ensure_bytes(value: str | bytes, *, name: str) -> bytes:
    if isinstance(value, bytes):
        if value:
            return value
    elif isinstance(value, str) and value.strip():
        return value.encode("utf-8")
    raise ValueError(f"{name} must not be empty")


def _first_text(*values: str | None, name: str) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip()
    raise ValueError(f"{name} must not be empty")


def validate_key_id(key_id: str | None) -> str:
    value = _first_text(key_id, name="provider ref key id")
    if not KEY_ID_RE.fullmatch(value):
        raise BillingSecurityError("provider ref key id is invalid")
    return value


def validate_fernet_key(key: str | bytes) -> bytes:
    key_bytes = key if isinstance(key, bytes) else key.encode("ascii")
    try:
        decoded = base64.urlsafe_b64decode(key_bytes)
    except Exception as exc:
        raise BillingSecurityError("provider ref key must be URL-safe base64") from exc
    if len(decoded) != 32:
        raise BillingSecurityError("provider ref key must decode to exactly 32 bytes")
    return decoded


def _provider_ref_cipher(key: str | bytes):
    key_bytes = key if isinstance(key, bytes) else key.encode("ascii")
    validate_fernet_key(key_bytes)
    if Fernet is not None:
        return Fernet(key_bytes)
    return _FallbackProviderRefCipher(key_bytes)


def verify_billing_s2s_bearer_token(
    *,
    presented: str | None = None,
    expected: str | None = None,
    presented_token: str | None = None,
    expected_token: str | None = None,
    token: str | None = None,
) -> bool:
    """Compare dedicated billing S2S bearer tokens with constant-time compare."""

    left = presented if presented is not None else presented_token if presented_token is not None else token
    right = expected if expected is not None else expected_token
    left_text = "" if left is None else str(left)
    right_text = "" if right is None else str(right)
    matches = hmac.compare_digest(left_text, right_text)
    return bool(left_text and right_text and matches)


def verify_s2s_bearer_token(**kwargs: Any) -> bool:
    return verify_billing_s2s_bearer_token(**kwargs)


def constant_time_bearer_equals(**kwargs: Any) -> bool:
    return verify_billing_s2s_bearer_token(**kwargs)


def hmac_provider_ref(
    *,
    provider: str,
    kind: str | None = None,
    raw_id: str | None = None,
    raw_ref: str | None = None,
    ref_type: str | None = None,
    identifier_type: str | None = None,
    identifier: str | None = None,
    secret: str | bytes | None = None,
    pepper: str | bytes | None = None,
) -> bytes:
    provider_value = _first_text(provider, name="provider").lower()
    kind_value = _first_text(kind, ref_type, identifier_type, name="provider ref kind").lower()
    raw_value = _first_text(raw_id, raw_ref, identifier, name="provider ref")
    secret_value = secret if secret is not None else pepper
    material = f"{HASH_VERSION}:{provider_value}:{kind_value}:{raw_value}".encode("utf-8")
    return hmac.digest(_ensure_bytes(secret_value, name="billing HMAC secret"), material, "sha256")


def hash_provider_ref(**kwargs: Any) -> bytes:
    return hmac_provider_ref(**kwargs)


def hmac_billing_identifier(**kwargs: Any) -> bytes:
    return hmac_provider_ref(**kwargs)


def hash_billing_provider_identifier(**kwargs: Any) -> bytes:
    return hmac_provider_ref(**kwargs)


def fingerprint_from_digest(digest: bytes | bytearray | memoryview) -> str:
    value = bytes(digest)
    if len(value) < 6:
        raise ValueError("digest must contain at least 6 bytes")
    return value.hex()[:12]


def billing_fingerprint_from_digest(*, digest: bytes | bytearray | memoryview) -> str:
    return fingerprint_from_digest(digest)


def provider_ref_fingerprint(*, digest: bytes | bytearray | memoryview | None = None, hmac_digest: bytes | bytearray | memoryview | None = None) -> str:
    return fingerprint_from_digest(digest if digest is not None else hmac_digest)  # type: ignore[arg-type]


def fingerprint_provider_ref(**kwargs: Any) -> str:
    return fingerprint_from_digest(hmac_provider_ref(**kwargs))


def encrypt_provider_ref(
    *,
    raw_ref: str | None = None,
    raw_id: str | None = None,
    key: str | bytes | None = None,
    fernet_key: str | bytes | None = None,
    key_id: str,
    provider: str | None = None,
) -> EncryptedProviderRef:
    _ = provider  # provider name is accepted for call-site clarity; encryption is generic.
    raw_value = _first_text(raw_ref, raw_id, name="provider ref")
    active_key = key if key is not None else fernet_key
    ciphertext = _provider_ref_cipher(_ensure_bytes(active_key, name="provider ref encryption key")).encrypt(raw_value.encode("utf-8"))
    return EncryptedProviderRef(ciphertext=ciphertext, key_id=validate_key_id(key_id))


def encrypt_billing_provider_ref(**kwargs: Any) -> EncryptedProviderRef:
    return encrypt_provider_ref(**kwargs)


def encrypt_operational_provider_ref(**kwargs: Any) -> EncryptedProviderRef:
    return encrypt_provider_ref(**kwargs)


def _encrypted_field(encrypted: Any, name: str) -> Any:
    if isinstance(encrypted, Mapping) and name in encrypted:
        return encrypted[name]
    if hasattr(encrypted, name):
        return getattr(encrypted, name)
    return None


def decrypt_provider_ref(
    *,
    ciphertext: bytes | str | None = None,
    key_id: str | None = None,
    keys_by_id: Mapping[str, str | bytes] | None = None,
    encrypted_ref: Any = None,
    encrypted: Any = None,
    decryption_keys: Mapping[str, str | bytes] | None = None,
) -> str:
    encrypted_value = encrypted_ref if encrypted_ref is not None else encrypted
    token = ciphertext if ciphertext is not None else _encrypted_field(encrypted_value, "ciphertext")
    ref_key_id = validate_key_id(key_id or _encrypted_field(encrypted_value, "key_id"))
    key_map = keys_by_id if keys_by_id is not None else decryption_keys if decryption_keys is not None else {}
    key = key_map.get(ref_key_id) if key_map else None
    if not key:
        raise BillingProviderRefDecryptError("provider ref decrypt key not_ready")
    if token is None:
        raise BillingProviderRefDecryptError("provider ref ciphertext missing")
    try:
        plaintext = _provider_ref_cipher(key).decrypt(token)
    except Exception as exc:
        raise BillingProviderRefDecryptError("provider ref decrypt failed") from exc
    try:
        return plaintext.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BillingProviderRefDecryptError("provider ref decrypt failed") from exc


def decrypt_billing_provider_ref(**kwargs: Any) -> str:
    return decrypt_provider_ref(**kwargs)


def decrypt_operational_provider_ref(**kwargs: Any) -> str:
    return decrypt_provider_ref(**kwargs)


def rotate_provider_ref(
    *,
    encrypted_ref: Any = None,
    old_keys_by_id: Mapping[str, str | bytes] | None = None,
    new_key: str | bytes | None = None,
    new_key_id: str | None = None,
    encrypted: Any = None,
    keys_by_id: Mapping[str, str | bytes] | None = None,
    active_key: str | bytes | None = None,
    active_key_id: str | None = None,
) -> EncryptedProviderRef:
    source = encrypted_ref if encrypted_ref is not None else encrypted
    key_map = old_keys_by_id if old_keys_by_id is not None else keys_by_id
    raw_ref = decrypt_provider_ref(encrypted_ref=source, keys_by_id=key_map or {})
    return encrypt_provider_ref(raw_ref=raw_ref, key=new_key if new_key is not None else active_key, key_id=new_key_id or active_key_id)  # type: ignore[arg-type]


def rotate_billing_provider_ref(**kwargs: Any) -> EncryptedProviderRef:
    return rotate_provider_ref(**kwargs)


def reencrypt_provider_ref(**kwargs: Any) -> EncryptedProviderRef:
    return rotate_provider_ref(**kwargs)


def raw_body_sha256(raw_body: bytes | bytearray | memoryview) -> bytes:
    if not isinstance(raw_body, (bytes, bytearray, memoryview)):
        raise TypeError("raw_body must be exact bytes")
    return hashlib.sha256(bytes(raw_body)).digest()


def raw_body_sha256_hex(raw_body: bytes | bytearray | memoryview) -> str:
    return raw_body_sha256(raw_body).hex()


__all__ = [
    "BillingProviderRefDecryptError",
    "BillingSecurityError",
    "EncryptedProviderRef",
    "billing_fingerprint_from_digest",
    "constant_time_bearer_equals",
    "decrypt_billing_provider_ref",
    "decrypt_operational_provider_ref",
    "decrypt_provider_ref",
    "encrypt_billing_provider_ref",
    "encrypt_operational_provider_ref",
    "encrypt_provider_ref",
    "fingerprint_from_digest",
    "fingerprint_provider_ref",
    "hash_billing_provider_identifier",
    "hash_provider_ref",
    "hmac_billing_identifier",
    "hmac_provider_ref",
    "provider_ref_fingerprint",
    "raw_body_sha256",
    "raw_body_sha256_hex",
    "reencrypt_provider_ref",
    "rotate_billing_provider_ref",
    "rotate_provider_ref",
    "validate_fernet_key",
    "validate_key_id",
    "verify_billing_s2s_bearer_token",
    "verify_s2s_bearer_token",
]
