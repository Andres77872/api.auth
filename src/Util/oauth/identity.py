"""Durable identity keys for external accounts.

The identity key is ``(identity_namespace, HMAC-SHA256(pepper, subject))``.

INVARIANT (docs/agnostic_oauth risk R-01): the HMAC input is the raw provider
subject and nothing else, and the key is the deployment-wide provider-sub pepper.
The namespace is a separate column and is NEVER mixed into the hashed string.
Changing any of that orphans every linked identity. A golden test pins the
digest for a fixed subject and pepper.
"""

from __future__ import annotations

import hashlib
import hmac
from dataclasses import dataclass, field

from src.Util.oauth.provider import ExternalIdentity
from src.Util.oauth.settings import OAuthDeploymentSettings, load_oauth_settings


class OAuthIdentityKeyError(RuntimeError):
    """Raised when an identity key cannot be derived (missing pepper or subject)."""


def provider_sub_hmac(subject: str, *, pepper: str | None = None, settings: OAuthDeploymentSettings | None = None) -> bytes:
    """Return the durable 32-byte HMAC authority key for a provider subject."""

    secret = pepper or (settings or load_oauth_settings()).provider_sub_pepper
    if not secret:
        raise OAuthIdentityKeyError("Provider-sub pepper is not configured")
    if not subject:
        raise OAuthIdentityKeyError("Provider subject is missing")
    return hmac.new(secret.encode("utf-8"), str(subject).encode("utf-8"), hashlib.sha256).digest()


def provider_sub_fingerprint(subject: str) -> str:
    """Short non-reversible fingerprint for support, logs and masked display."""

    return hashlib.sha256(str(subject).encode("utf-8")).hexdigest()[:12]


def provider_email_hmac(
    email: str | None,
    *,
    pepper: str | None = None,
    settings: OAuthDeploymentSettings | None = None,
) -> bytes | None:
    if not email:
        return None
    secret = pepper or (settings or load_oauth_settings()).email_hash_pepper
    if not secret:
        raise OAuthIdentityKeyError("Provider-email pepper is not configured")
    return hmac.new(secret.encode("utf-8"), str(email).strip().lower().encode("utf-8"), hashlib.sha256).digest()


def mask_provider_email(email: str | None) -> str | None:
    if not email or "@" not in str(email):
        return None
    local, domain = str(email).split("@", 1)
    if len(local) <= 2:
        local_mask = local[:1] + "***"
    else:
        local_mask = f"{local[0]}***{local[-1]}"
    return f"{local_mask}@{domain}"


@dataclass(frozen=True)
class IdentityKey:
    """Everything the persistence layer may see about an external identity."""

    provider_type: str
    identity_namespace: str
    sub_hash: bytes = field(repr=False)
    sub_fingerprint: str
    email_hash: bytes | None = field(default=None, repr=False)
    email_masked: str | None = None
    email_verified: bool = False
    email_normalized: str | None = field(default=None, repr=False)

    @property
    def email_hash_prefix(self) -> str | None:
        return self.email_hash.hex()[:12] if self.email_hash else None


def identity_key_for(identity: ExternalIdentity, *, settings: OAuthDeploymentSettings | None = None) -> IdentityKey:
    settings = settings or load_oauth_settings()
    email = (identity.email or "").strip().lower() or None
    return IdentityKey(
        provider_type=identity.provider_type,
        identity_namespace=identity.identity_namespace,
        sub_hash=provider_sub_hmac(identity.subject, settings=settings),
        sub_fingerprint=provider_sub_fingerprint(identity.subject),
        email_hash=provider_email_hmac(email, settings=settings),
        email_masked=mask_provider_email(email),
        email_verified=bool(identity.email_verified),
        email_normalized=email,
    )


__all__ = [
    "IdentityKey",
    "OAuthIdentityKeyError",
    "identity_key_for",
    "mask_provider_email",
    "provider_email_hmac",
    "provider_sub_fingerprint",
    "provider_sub_hmac",
]
