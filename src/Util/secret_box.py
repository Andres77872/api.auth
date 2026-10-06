"""Neutral authenticated-encryption primitives for secrets at rest.

Extracted from the billing security module so that billing and OAuth share one
reviewed mechanism while keeping SEPARATE key sets and rotation schedules. This
module knows nothing about either domain: it validates Fernet keys and builds
a Fernet cipher using the required cryptography dependency.
"""

from __future__ import annotations

import base64
from cryptography.fernet import Fernet, InvalidToken

ENCRYPTION_ALGORITHM = "fernet-v1"


class SecretBoxError(RuntimeError):
    """Neutral failure that never echoes key or plaintext material."""


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
    return Fernet(key_bytes)


__all__ = ["ENCRYPTION_ALGORITHM", "Fernet", "InvalidToken", "SecretBoxError", "build_cipher", "validate_fernet_key"]
