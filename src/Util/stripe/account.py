"""Per-billing-group Stripe account resolution.

Each billing group owns its own standalone Stripe account (LOCKED DECISION 1): the
secret key, webhook secret, and optional portal configuration id are stored as Fernet
ciphertext on ``billing_groups`` and decrypted in-memory only when a server-side Stripe
operation needs them. This module keeps ``config.py`` import-side-effect-free and
``client.py`` agnostic of where the key came from.

Security posture:
- Decrypted secrets live only on a short-lived ``StripeAccountSecrets`` instance with
  ``repr=False`` on every secret field; we never cache them across requests.
- Failures are fail-closed and neutral; raw key material never reaches logs.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Mapping

from src.Util.billing.security import decrypt_provider_ref
from src.Util.stripe.client import StripeBillingClient
from src.Util.stripe.config import SUPPORTED_STRIPE_API_VERSION, StripeConfig, load_stripe_config
from src.Util.db import db_billing


logger = logging.getLogger(__name__)


class StripeAccountNotReadyError(RuntimeError):
    """Raised when a billing group's Stripe account is missing or not active."""


@dataclass(frozen=True)
class StripeAccountSecrets:
    """Decrypted, in-memory-only per-group Stripe credentials."""

    billing_group_id: str
    billing_group_hash: str | None
    secret_key: str = field(repr=False)
    webhook_secret: str | None = field(default=None, repr=False)
    portal_configuration_id: str | None = field(default=None, repr=False)
    api_version: str = SUPPORTED_STRIPE_API_VERSION
    credential_key_id: str | None = None


def _decrypt_optional(ciphertext: Any, *, key_id: str | None, keys_by_id: Mapping[str, str | bytes]) -> str | None:
    if ciphertext is None:
        return None
    if isinstance(ciphertext, (bytes, bytearray, memoryview)) and len(bytes(ciphertext)) == 0:
        return None
    return decrypt_provider_ref(ciphertext=bytes(ciphertext) if not isinstance(ciphertext, str) else ciphertext, key_id=key_id, keys_by_id=keys_by_id)


def get_stripe_account_secrets_for_group(
    *,
    billing_group_id: str,
    decryption_keys_by_id: Mapping[str, str | bytes],
    api_version: str | None = None,
    db: Any = db_billing,
    billing_group_hash: str | None = None,
) -> StripeAccountSecrets:
    """Load and decrypt a billing group's Stripe credentials (fail-closed)."""

    row = db.get_billing_group_operational_credentials(id=billing_group_id)
    if not row:
        raise StripeAccountNotReadyError("billing account not found")
    if str(row.get("credential_status") or "") != "active":
        raise StripeAccountNotReadyError("billing account credentials not active")

    key_id = row.get("credential_key_id")
    try:
        secret_key = decrypt_provider_ref(
            ciphertext=row.get("stripe_secret_key_ciphertext"),
            key_id=key_id,
            keys_by_id=decryption_keys_by_id,
        )
        webhook_secret = _decrypt_optional(row.get("stripe_webhook_secret_ciphertext"), key_id=key_id, keys_by_id=decryption_keys_by_id)
        portal_configuration_id = _decrypt_optional(row.get("stripe_portal_configuration_id_ciphertext"), key_id=key_id, keys_by_id=decryption_keys_by_id)
    except Exception:
        # Never log key material or decrypt internals; correlate by group only.
        logger.warning("Stripe account credential decrypt failed for billing group %s", billing_group_id)
        raise StripeAccountNotReadyError("billing account credentials unavailable")

    return StripeAccountSecrets(
        billing_group_id=billing_group_id,
        billing_group_hash=billing_group_hash or row.get("billing_group_hash"),
        secret_key=secret_key,
        webhook_secret=webhook_secret,
        portal_configuration_id=portal_configuration_id,
        api_version=api_version or SUPPORTED_STRIPE_API_VERSION,
        credential_key_id=key_id,
    )


def get_stripe_client_for_group(
    *,
    billing_group_id: str,
    decryption_keys_by_id: Mapping[str, str | bytes],
    stripe_global_config: StripeConfig | None = None,
    secrets: StripeAccountSecrets | None = None,
    db: Any = db_billing,
) -> StripeBillingClient:
    """Build a fresh per-request Stripe client bound to a group's account key.

    Decrypted secrets are not cached across requests. The api_version is pinned to the
    global config so the SDK version contract stays uniform across accounts.
    """

    cfg = stripe_global_config or load_stripe_config()
    if secrets is None:
        secrets = get_stripe_account_secrets_for_group(
            billing_group_id=billing_group_id,
            decryption_keys_by_id=decryption_keys_by_id,
            api_version=cfg.api_version,
            db=db,
        )
    return StripeBillingClient(secret_key=secrets.secret_key, api_version=cfg.api_version)


__all__ = [
    "StripeAccountNotReadyError",
    "StripeAccountSecrets",
    "get_stripe_account_secrets_for_group",
    "get_stripe_client_for_group",
]
