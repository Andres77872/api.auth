"""Encryption of OAuth connection secrets at rest.

Same mechanism as billing (Fernet with a key id and a decrypt-key map for rotation,
see :mod:`src.Util.secret_box`) but a SEPARATE key set, so the two domains rotate
independently:

    OAUTH_SECRET_ENCRYPTION_KEY / OAUTH_SECRET_ENCRYPTION_KEY_ID   active key
    OAUTH_SECRET_DECRYPTION_KEYS_JSON                               {key_id: key} for rotation
    OAUTH_SECRET_HMAC_KEY                                           row-binding HMAC

Fernet has no associated data, so a ciphertext copied from one row to another would
still decrypt. Every ciphertext is therefore stored beside an HMAC over a
purpose-separated input -- ``v1:oauth:<connection_id>:<kind>:<value>`` -- that is
re-verified after decryption. A row-swapped ciphertext fails that check.

Decrypted values live on ``repr``-suppressed objects for the duration of one token
exchange. They are never cached, never placed in Redis, and never appear in an
exception message.
"""

from __future__ import annotations

import hashlib
import hmac
import re
from dataclasses import dataclass, field
from typing import Mapping

from src.Util.oauth.settings import OAuthDeploymentSettings, load_oauth_settings
from src.Util.secret_box import ENCRYPTION_ALGORITHM, SecretBoxError, build_cipher


HASH_VERSION = "v1"
KIND_CLIENT_SECRET = "client_secret"
KIND_SIGNING_KEY = "signing_key"
KIND_LEGACY_REDEEM_URL = "legacy_redeem_url"
KIND_LEGACY_REDEEM_TOKEN = "legacy_redeem_token"
_KEY_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class OAuthSecretError(RuntimeError):
    """Neutral secret-handling failure. Never echoes key, plaintext or ciphertext."""


class OAuthSecretsNotReady(OAuthSecretError):
    """The server has no OAuth encryption key configured."""


@dataclass(frozen=True)
class EncryptedSecret:
    ciphertext: bytes = field(repr=False)
    digest: bytes = field(repr=False)
    fingerprint: str
    key_id: str
    algorithm: str = ENCRYPTION_ALGORITHM


def _require_ready(settings: OAuthDeploymentSettings) -> None:
    if not settings.secrets_ready:
        raise OAuthSecretsNotReady("OAuth secret encryption keys are not configured")
    if not _KEY_ID_RE.fullmatch(str(settings.secret_encryption_key_id)):
        raise OAuthSecretError("OAuth secret key id is invalid")


def secret_hmac(*, owner_id: str, kind: str, value: str, settings: OAuthDeploymentSettings | None = None) -> bytes:
    """Row-binding HMAC of a secret. Stable across re-encryption, so rotation keeps it."""

    settings = settings or load_oauth_settings()
    if not settings.secret_hmac_key:
        raise OAuthSecretsNotReady("OAuth secret HMAC key is not configured")
    material = f"{HASH_VERSION}:oauth:{owner_id}:{kind}:{value}"
    return hmac.new(settings.secret_hmac_key.encode("utf-8"), material.encode("utf-8"), hashlib.sha256).digest()


def fingerprint_from_digest(digest: bytes) -> str:
    return bytes(digest).hex()[:12]


def encrypt_secret(*, owner_id: str, kind: str, value: str, settings: OAuthDeploymentSettings | None = None) -> EncryptedSecret:
    settings = settings or load_oauth_settings()
    _require_ready(settings)
    if not isinstance(value, str) or not value:
        raise OAuthSecretError("secret value must not be empty")
    try:
        ciphertext = build_cipher(str(settings.secret_encryption_key)).encrypt(value.encode("utf-8"))
    except SecretBoxError as exc:
        raise OAuthSecretError("OAuth secret encryption key is invalid") from exc
    digest = secret_hmac(owner_id=owner_id, kind=kind, value=value, settings=settings)
    return EncryptedSecret(
        ciphertext=ciphertext,
        digest=digest,
        fingerprint=fingerprint_from_digest(digest),
        key_id=str(settings.secret_encryption_key_id),
    )


def decrypt_secret(
    *,
    owner_id: str,
    kind: str,
    ciphertext: bytes | str | None,
    key_id: str | None,
    expected_digest: bytes | None = None,
    settings: OAuthDeploymentSettings | None = None,
) -> str:
    """Decrypt and, when a digest is stored, verify the ciphertext belongs to this row."""

    settings = settings or load_oauth_settings()
    if ciphertext is None or not key_id:
        raise OAuthSecretError("OAuth secret is not set")
    keys: Mapping[str, str] = settings.decryption_keys_by_id
    key = keys.get(str(key_id))
    if not key:
        raise OAuthSecretsNotReady("OAuth secret decrypt key is not available")
    token = bytes(ciphertext) if isinstance(ciphertext, (bytes, bytearray, memoryview)) else str(ciphertext).encode("ascii")
    try:
        plaintext = build_cipher(key).decrypt(token).decode("utf-8")
    except Exception as exc:
        raise OAuthSecretError("OAuth secret decrypt failed") from exc
    if expected_digest is not None:
        actual = secret_hmac(owner_id=owner_id, kind=kind, value=plaintext, settings=settings)
        if not hmac.compare_digest(bytes(expected_digest), actual):
            raise OAuthSecretError("OAuth secret does not belong to this record")
    return plaintext


def reencrypt_secret(
    *,
    owner_id: str,
    kind: str,
    ciphertext: bytes | str,
    key_id: str,
    expected_digest: bytes | None = None,
    settings: OAuthDeploymentSettings | None = None,
) -> EncryptedSecret:
    """Re-encrypt under the active key (encryption-key rotation)."""

    settings = settings or load_oauth_settings()
    plaintext = decrypt_secret(
        owner_id=owner_id, kind=kind, ciphertext=ciphertext, key_id=key_id, expected_digest=expected_digest, settings=settings
    )
    return encrypt_secret(owner_id=owner_id, kind=kind, value=plaintext, settings=settings)


__all__ = [
    "EncryptedSecret",
    "KIND_CLIENT_SECRET",
    "KIND_LEGACY_REDEEM_TOKEN",
    "KIND_LEGACY_REDEEM_URL",
    "KIND_SIGNING_KEY",
    "OAuthSecretError",
    "OAuthSecretsNotReady",
    "decrypt_secret",
    "encrypt_secret",
    "fingerprint_from_digest",
    "reencrypt_secret",
    "secret_hmac",
]
