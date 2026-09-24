"""Provision catalog items into a billing group's own Stripe account.

api.auth owns the catalog (LOCKED DECISION 2): creating/updating a catalog item drives a
Stripe ``Product``/``Price`` on the group's account (per-account key resolved via
``stripe.account``). Stripe prices are immutable, so a price change creates a new Price on
the item's existing Product and then deactivates the old one. All Stripe ids are stored
encrypted (+ HMAC/fingerprint); failures are recorded as ``provisioning_status='failed'``
with a redacted reason — never raising into the admin request beyond a neutral result.

Idempotency keys: the first provisioning of an item is keyed by the item id. Each price
rotation gets its own keys (item id + a per-rotation nonce), because Stripe keeps a key's
first result for 24 hours: reusing the item-id keys for a new price would replay the old
request or fail with ``idempotency_error``.

Gating: Stripe is only contacted when the global kill switch is on AND the group has
``provisioning_enabled`` AND ``credential_status='active'``. Otherwise the catalog row is
left ``pending`` (authorable offline; re-provision once enabled).
"""

from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from typing import Any, Mapping

from src.Util.billing.config import load_billing_config
from src.Util.billing.idempotency import derive_stripe_api_idempotency_key
from src.Util.billing.redaction import sanitize_billing_sensitive_text
from src.Util.billing.security import decrypt_provider_ref, encrypt_provider_ref, hmac_provider_ref, provider_ref_fingerprint
from src.Util.db import db_billing
from src.Util.stripe.account import StripeAccountNotReadyError, get_stripe_client_for_group
from src.Util.stripe.client import StripeAPIError, StripeBillingClient
from src.Util.stripe.config import load_stripe_config


logger = logging.getLogger(__name__)

_PROVIDER = "stripe"


class CatalogProvisioningConfigError(RuntimeError):
    """Raised when server-side encryption keys are not configured for provisioning."""


@dataclass(frozen=True)
class CatalogProvisionResult:
    catalog_item_id: str
    provisioning_status: str  # active | failed | pending
    product_fingerprint: str | None = None
    price_fingerprint: str | None = None
    reason: str | None = None
    row: Mapping[str, Any] | None = None


def provisioning_allowed(group_row: Mapping[str, Any] | None, *, stripe_config: Any = None) -> bool:
    """Effective gate: global kill switch AND group provisioning_enabled AND active creds."""

    if not group_row:
        return False
    cfg = stripe_config or load_stripe_config()
    if not getattr(cfg, "billing_enabled", False):
        return False
    return bool(group_row.get("provisioning_enabled")) and str(group_row.get("credential_status") or "") == "active"


def _encryption_material() -> tuple[str, str, str]:
    config = load_billing_config()
    key = getattr(config, "provider_ref_encryption_key", None)
    key_id = getattr(config, "provider_ref_encryption_key_id", None)
    hmac_secret = getattr(config, "id_hmac_secret", None)
    if not key or not key_id or not hmac_secret:
        raise CatalogProvisioningConfigError("billing provider-ref encryption keys are not configured")
    return key, key_id, hmac_secret


def _encrypted_ref(raw_id: str, *, kind: str, key: str, key_id: str, hmac_secret: str) -> dict[str, Any]:
    encrypted = encrypt_provider_ref(raw_ref=raw_id, key=key, key_id=key_id, provider=_PROVIDER)
    digest = hmac_provider_ref(provider=_PROVIDER, kind=kind, raw_id=raw_id, secret=hmac_secret)
    return {
        "ciphertext": encrypted.ciphertext,
        "hmac": digest,
        "fingerprint": provider_ref_fingerprint(digest=digest),
    }


def provision_catalog_item(
    *,
    billing_group_id: str,
    catalog_item_id: str,
    item_type: str,
    display_name: str,
    currency: str | None,
    unit_amount: int | None,
    recurring_interval: str | None,
    lookup_key: str | None,
    metadata: Mapping[str, Any] | None = None,
    client: StripeBillingClient | None = None,
    db: Any = db_billing,
) -> CatalogProvisionResult:
    """Create the Stripe Product + Price for a pending catalog row and mark it provisioned.

    Failure is captured on the row (``failed`` + redacted reason); this never raises a
    Stripe error into the caller.
    """

    return _provision(
        billing_group_id=billing_group_id,
        catalog_item_id=catalog_item_id,
        item_type=item_type,
        display_name=display_name,
        currency=currency,
        unit_amount=unit_amount,
        recurring_interval=recurring_interval,
        lookup_key=lookup_key,
        metadata=metadata,
        client=client,
        db=db,
        idempotency_ref=catalog_item_id,
    )


def _provision(
    *,
    billing_group_id: str,
    catalog_item_id: str,
    item_type: str,
    display_name: str,
    currency: str | None,
    unit_amount: int | None,
    recurring_interval: str | None,
    lookup_key: str | None,
    metadata: Mapping[str, Any] | None,
    client: StripeBillingClient | None,
    db: Any,
    idempotency_ref: str,
    reprice: bool = False,
) -> CatalogProvisionResult:
    """Create a Price (and, unless repricing onto an existing Product, a Product) and store the refs.

    ``idempotency_ref`` scopes every Stripe idempotency key of this attempt. With ``reprice``
    the item's stored Product is reused and its previous Price is deactivated only after the
    new one is stored, so a failed reprice leaves the old price live.
    """

    try:
        key, key_id, hmac_secret = _encryption_material()
    except CatalogProvisioningConfigError as exc:
        row = db.set_catalog_item_failed(id=catalog_item_id, provisioning_error_redacted=str(exc))
        return CatalogProvisionResult(catalog_item_id, "failed", reason=str(exc), row=row)

    if unit_amount is None or not currency:
        reason = "catalog item missing price (currency/unit_amount) for provisioning"
        row = db.set_catalog_item_failed(id=catalog_item_id, provisioning_error_redacted=reason)
        return CatalogProvisionResult(catalog_item_id, "failed", reason=reason, row=row)

    try:
        billing_config = load_billing_config()
        stripe_client = client or get_stripe_client_for_group(
            billing_group_id=billing_group_id,
            decryption_keys_by_id=billing_config.decryption_keys_by_id,
            db=db,
        )

        product_id: str | None = None
        old_price_id: str | None = None
        if reprice:
            refs = db.get_catalog_operational_refs(id=catalog_item_id) or {}
            product_id = _decrypt_stored_ref(refs, "provider_product_id_ciphertext", billing_config, catalog_item_id)
            old_price_id = _decrypt_stored_ref(refs, "provider_price_id_ciphertext", billing_config, catalog_item_id)

        if not product_id:
            safe_metadata = {"catalog_item_id_fp": provider_ref_fingerprint(
                digest=hmac_provider_ref(provider=_PROVIDER, kind="catalog_item", raw_id=catalog_item_id, secret=hmac_secret)
            )}
            if metadata:
                # Opaque consumer metadata is not forwarded to Stripe verbatim to stay agnostic.
                safe_metadata["has_features"] = "1"

            product = stripe_client.create_product(
                name=display_name,
                metadata=safe_metadata,
                idempotency_key=derive_stripe_api_idempotency_key(internal_ref=idempotency_ref, operation="product_create"),
            )
            product_id = str(product.get("id") or "")
            if not product_id:
                raise StripeAPIError(message="Stripe product create returned no id")

        price_kwargs: dict[str, Any] = {
            "product": product_id,
            "currency": str(currency).lower(),
            "unit_amount": int(unit_amount),
            "idempotency_key": derive_stripe_api_idempotency_key(internal_ref=idempotency_ref, operation="price_create"),
        }
        if lookup_key:
            price_kwargs["lookup_key"] = lookup_key
            price_kwargs["transfer_lookup_key"] = True
        if item_type == "subscription_plan" and recurring_interval:
            price_kwargs["recurring"] = {"interval": recurring_interval}
        price = stripe_client.create_price(**price_kwargs)
        price_id = str(price.get("id") or "")
        if not price_id:
            raise StripeAPIError(message="Stripe price create returned no id")

        product_ref = _encrypted_ref(product_id, kind="product_id", key=key, key_id=key_id, hmac_secret=hmac_secret)
        price_ref = _encrypted_ref(price_id, kind="price_id", key=key, key_id=key_id, hmac_secret=hmac_secret)

        row = db.set_catalog_item_provisioned(
            id=catalog_item_id,
            provider_product_id_ciphertext=product_ref["ciphertext"],
            provider_product_id_hmac=product_ref["hmac"],
            provider_product_id_fingerprint=product_ref["fingerprint"],
            provider_price_id_ciphertext=price_ref["ciphertext"],
            provider_price_id_hmac=price_ref["hmac"],
            provider_price_id_fingerprint=price_ref["fingerprint"],
            provider_ref_key_id=key_id,
            lookup_key=lookup_key,
            activate=True,
        )
        if old_price_id and old_price_id != price_id:
            _deactivate_price(stripe_client, old_price_id, idempotency_ref=idempotency_ref, catalog_item_id=catalog_item_id)
        return CatalogProvisionResult(
            catalog_item_id,
            "active",
            product_fingerprint=product_ref["fingerprint"],
            price_fingerprint=price_ref["fingerprint"],
            row=row,
        )
    except (StripeAPIError, StripeAccountNotReadyError) as exc:
        reason = sanitize_billing_sensitive_text(str(exc)) or "stripe provisioning failed"
        logger.warning("Catalog provisioning failed for item %s: %s", catalog_item_id, type(exc).__name__)
        row = db.set_catalog_item_failed(id=catalog_item_id, provisioning_error_redacted=reason)
        return CatalogProvisionResult(catalog_item_id, "failed", reason=reason, row=row)
    except Exception as exc:  # never leak; record neutral failure
        logger.warning("Catalog provisioning unexpected error for item %s: %s", catalog_item_id, type(exc).__name__)
        row = db.set_catalog_item_failed(id=catalog_item_id, provisioning_error_redacted="provisioning failed")
        return CatalogProvisionResult(catalog_item_id, "failed", reason="provisioning failed", row=row)


def reprovision_price(
    *,
    billing_group_id: str,
    catalog_item_id: str,
    item_type: str,
    display_name: str,
    currency: str | None,
    unit_amount: int | None,
    recurring_interval: str | None,
    lookup_key: str | None,
    client: StripeBillingClient | None = None,
    db: Any = db_billing,
) -> CatalogProvisionResult:
    """Rotate to a new Stripe Price (immutability): create the new one, store it, then deactivate the old.

    The new Price goes on the item's existing Product (a new Product is created only when
    the stored one is missing or unreadable). Every rotation uses fresh idempotency keys, so
    repricing again within Stripe's 24h key window works. If the new Price cannot be created
    the item is marked ``failed`` and the old Price stays active in Stripe; deactivating the
    old Price is best-effort once the new one is stored.
    """

    return _provision(
        billing_group_id=billing_group_id,
        catalog_item_id=catalog_item_id,
        item_type=item_type,
        display_name=display_name,
        currency=currency,
        unit_amount=unit_amount,
        recurring_interval=recurring_interval,
        lookup_key=lookup_key,
        metadata=None,
        client=client,
        db=db,
        idempotency_ref=f"{catalog_item_id}:{secrets.token_hex(8)}",
        reprice=True,
    )


def _decrypt_stored_ref(refs: Mapping[str, Any], field: str, billing_config: Any, catalog_item_id: str) -> str | None:
    ciphertext = refs.get(field)
    key_id = refs.get("provider_ref_key_id")
    if not ciphertext or not key_id:
        return None
    try:
        return decrypt_provider_ref(ciphertext=ciphertext, key_id=key_id, keys_by_id=billing_config.decryption_keys_by_id)
    except Exception:
        logger.warning("Stored Stripe ref %s unreadable for catalog item %s", field, catalog_item_id)
        return None


def _deactivate_price(stripe_client: StripeBillingClient, price_id: str, *, idempotency_ref: str, catalog_item_id: str) -> None:
    try:
        stripe_client.update_price(
            price_id,
            active=False,
            idempotency_key=derive_stripe_api_idempotency_key(internal_ref=idempotency_ref, operation="price_deactivate"),
        )
    except Exception as exc:
        logger.warning("Old price deactivate failed for catalog item %s: %s", catalog_item_id, type(exc).__name__)


__all__ = [
    "CatalogProvisionResult",
    "CatalogProvisioningConfigError",
    "provision_catalog_item",
    "provisioning_allowed",
    "reprovision_price",
]
