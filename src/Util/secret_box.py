"""Neutral authenticated-encryption primitives for secrets at rest.

Extracted from the billing security module so that billing and OAuth share one
reviewed mechanism while keeping SEPARATE key sets and rotation schedules. This
module knows nothing about either domain: it validates Fernet keys, builds a
cipher, and provides an authenticated local fallback used only when the
``cryptography`` package is unavailable in a test environment.
"""

from __future__ import annotations

import base64
import hmac
import secrets

try:  # pragma: no cover - depends on runtime dependency availability.
    from cryptography.fernet import Fernet, InvalidToken
except Exception:  # pragma: no cover - local targeted tests can use fallback.
    Fernet = None  # type: ignore[assignment]

    class InvalidToken(Exception):  # type: ignore[no-redef]
        pass


ENCRYPTION_ALGORITHM = "fernet-v1"


class SecretBoxError(RuntimeError):
    """Neutral failure that never echoes key or plaintext material."""


class FallbackCipher:
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


def validate_fernet_key(key: str | bytes) -> bytes:
    key_bytes = key if isinstance(key, bytes) else key.encode("ascii")
    try:
        decoded = base64.urlsafe_b64decode(key_bytes)
    except Exception as exc:
        raise SecretBoxError("provider ref key must be URL-safe base64") from exc
    if len(decoded) != 32:
        raise SecretBoxError("provider ref key must decode to exactly 32 bytes")
    return decoded


def build_cipher(key: str | bytes):
    key_bytes = key if isinstance(key, bytes) else key.encode("ascii")
    validate_fernet_key(key_bytes)
    if Fernet is not None:
        return Fernet(key_bytes)
    return FallbackCipher(key_bytes)


__all__ = ["ENCRYPTION_ALGORITHM", "FallbackCipher", "Fernet", "InvalidToken", "SecretBoxError", "build_cipher", "validate_fernet_key"]
