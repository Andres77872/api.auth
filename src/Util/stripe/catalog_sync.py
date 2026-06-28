"""Reconcile + import the billing catalog FROM a group's Stripe account (pull direction).

api.auth OWNS the catalog (LOCKED DECISION 2): this module NEVER overwrites local money/plan_code
from Stripe. It does two things:

- **reconcile** — drift detection: list the group's active Stripe products/prices, match them to local
  ``billing_catalog_items`` via HMAC fingerprints (the same fingerprints provisioning stores), and
  report mismatches. The only writes it performs are (a) repairing a local row that is missing its
  encrypted provider refs by adopting the matched Stripe ids, and (b) recording the per-group sync
  status/timestamp.
- **import** — adopt orphan Stripe products/prices that have no local counterpart into the group's
  catalog (admin-confirmed two-phase: preview candidates, then insert selected).

Only native Stripe SDK list reads are used (``StripeBillingClient.list_products/list_prices``). Raw
Stripe ids never surface in reports — only fingerprints + (server-side) Fernet ciphertext.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from src.Util.billing.config import load_billing_config
from src.Util.billing.redaction import sanitize_billing_sensitive_text
from src.Util.billing.security import encrypt_provider_ref, hmac_provider_ref, provider_ref_fingerprint
from src.Util.db import db_billing
from src.Util.stripe.account import StripeAccountNotReadyError, get_stripe_client_for_group
from src.Util.stripe.client import StripeAPIError, StripeBillingClient
from src.Util.stripe.config import load_stripe_config


logger = logging.getLogger(__name__)

_PROVIDER = "stripe"
_PRODUCT_KIND = "product_id"
_PRICE_KIND = "price_id"


class CatalogSyncConfigError(RuntimeError):
    """Raised when server-side encryption keys are not configured for catalog sync."""


# --------------------------------------------------------------------------- value objects


@dataclass(frozen=True)
class StripeCatalogPrice:
    price_id: str = field(repr=False)
    product_id: str = field(repr=False)
    product_name: str | None
    currency: str | None
    unit_amount: int | None
    interval: str | None  # None => one-time (credit package)
    lookup_key: str | None
    active: bool
    product_metadata: Mapping[str, Any]
    price_fingerprint: str
    product_fingerprint: str


@dataclass
class StripeCatalogIndex:
    by_price_fp: dict[str, StripeCatalogPrice] = field(default_factory=dict)
    by_lookup_key: dict[str, StripeCatalogPrice] = field(default_factory=dict)


@dataclass
class CatalogDriftEntry:
    item_id: str
    plan_code: str
    item_type: str
    drift_kind: str  # price_archived | amount_mismatch | interval_mismatch | unresolved
    local_unit_amount: int | None = None
    stripe_unit_amount: int | None = None
    local_interval: str | None = None
    stripe_interval: str | None = None
    price_fingerprint: str | None = None


@dataclass
class CatalogImportCandidate:
    item_type: str
    plan_code: str
    display_name: str
    currency: str | None
    unit_amount: int | None
    recurring_interval: str | None
    lookup_key: str | None
    product_fingerprint: str
    price_fingerprint: str
    plan_code_conflict: bool = False
    # Raw ids are kept in-memory to drive the encrypted-ref write in Phase B; never serialized.
    product_id: str = field(default="", repr=False)
    price_id: str = field(default="", repr=False)


@dataclass
class _RepairAction:
    item_id: str
    product_id: str
    price_id: str
    lookup_key: str | None


@dataclass
class CatalogClassification:
    in_sync: int = 0
    drift: list[CatalogDriftEntry] = field(default_factory=list)
    repairs: list[_RepairAction] = field(default_factory=list)
    candidates: list[CatalogImportCandidate] = field(default_factory=list)


@dataclass
class CatalogReconcileReport:
    gated: bool = False
    error: str | None = None
    retryable: bool = False
    retry_after_seconds: int | None = None
    in_sync: int = 0
    missing_ref_repaired: int = 0
    drift: list[CatalogDriftEntry] = field(default_factory=list)
    candidates: list[CatalogImportCandidate] = field(default_factory=list)
    synced_at: str | None = None

    @property
    def counts(self) -> dict[str, int]:
        return {
            "in_sync": self.in_sync,
            "missing_ref_repaired": self.missing_ref_repaired,
            "drifted": len(self.drift),
            "orphans": len(self.candidates),
        }


# --------------------------------------------------------------------------- helpers


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _encryption_material() -> tuple[str, str, str]:
    cfg = load_billing_config()
    key = getattr(cfg, "provider_ref_encryption_key", None)
    key_id = getattr(cfg, "provider_ref_encryption_key_id", None)
    hmac_secret = getattr(cfg, "id_hmac_secret", None)
    if not key or not key_id or not hmac_secret:
        raise CatalogSyncConfigError("billing provider-ref encryption keys are not configured")
    return key, key_id, hmac_secret


def _fingerprint(kind: str, raw_id: str, hmac_secret: str) -> str:
    return provider_ref_fingerprint(
        digest=hmac_provider_ref(provider=_PROVIDER, kind=kind, raw_id=raw_id, secret=hmac_secret)
    )


def _encrypted_ref(raw_id: str, *, kind: str, key: str, key_id: str, hmac_secret: str) -> dict[str, Any]:
    encrypted = encrypt_provider_ref(raw_ref=raw_id, key=key, key_id=key_id, provider=_PROVIDER)
    digest = hmac_provider_ref(provider=_PROVIDER, kind=kind, raw_id=raw_id, secret=hmac_secret)
    return {
        "ciphertext": encrypted.ciphertext,
        "hmac": digest,
        "fingerprint": provider_ref_fingerprint(digest=digest),
    }


def _slug(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").lower()).strip("_")[:64]


def _safe_int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _product_of(price: Mapping[str, Any]) -> tuple[str, str | None, Mapping[str, Any]]:
    """Return (product_id, product_name, product_metadata) whether ``product`` is an id or expanded."""
    product = price.get("product")
    if isinstance(product, Mapping):
        meta = product.get("metadata") if isinstance(product.get("metadata"), Mapping) else {}
        return str(product.get("id") or ""), product.get("name"), dict(meta)
    return str(product or ""), None, {}


def build_stripe_index(prices: list[Mapping[str, Any]], hmac_secret: str) -> StripeCatalogIndex:
    """Index Stripe prices by fingerprint + lookup_key (computing the same fingerprints we store)."""
    index = StripeCatalogIndex()
    for price in prices:
        price_id = str(price.get("id") or "")
        product_id, product_name, product_meta = _product_of(price)
        if not price_id or not product_id:
            continue
        recurring = price.get("recurring") if isinstance(price.get("recurring"), Mapping) else None
        entry = StripeCatalogPrice(
            price_id=price_id,
            product_id=product_id,
            product_name=product_name,
            currency=(str(price.get("currency")).lower() if price.get("currency") else None),
            unit_amount=_safe_int(price.get("unit_amount")),
            interval=(str(recurring.get("interval")) if recurring and recurring.get("interval") else None),
            lookup_key=(str(price.get("lookup_key")) if price.get("lookup_key") else None),
            active=bool(price.get("active", True)),
            product_metadata=product_meta,
            price_fingerprint=_fingerprint(_PRICE_KIND, price_id, hmac_secret),
            product_fingerprint=_fingerprint(_PRODUCT_KIND, product_id, hmac_secret),
        )
        index.by_price_fp[entry.price_fingerprint] = entry
        if entry.lookup_key:
            index.by_lookup_key.setdefault(entry.lookup_key, entry)
    return index


def _match_local(row: Mapping[str, Any], index: StripeCatalogIndex) -> tuple[StripeCatalogPrice | None, bool]:
    """Resolve a local row to a Stripe price. Returns (price, matched_by_lookup_key)."""
    price_fp = row.get("provider_price_id_fingerprint")
    if price_fp and price_fp in index.by_price_fp:
        return index.by_price_fp[price_fp], False
    lookup_key = row.get("lookup_key")
    if lookup_key and lookup_key in index.by_lookup_key:
        return index.by_lookup_key[lookup_key], True
    return None, False


def classify_catalog(local_rows: list[Mapping[str, Any]], index: StripeCatalogIndex) -> CatalogClassification:
    """Classify local catalog rows against the Stripe index (pure; no I/O, no mutation)."""
    result = CatalogClassification()
    claimed_price_fps: set[str] = set()
    active_plan_codes = {
        str(r.get("plan_code"))
        for r in local_rows
        if r.get("active") and str(r.get("provisioning_status") or "") in {"pending", "active"}
    }

    for row in local_rows:
        item_id = str(row.get("id") or "")
        plan_code = str(row.get("plan_code") or "")
        item_type = str(row.get("item_type") or "")
        price, matched_by_lookup = _match_local(row, index)
        if price is not None:
            claimed_price_fps.add(price.price_fingerprint)
            # Repair (side-effect): the row resolved (via lookup_key) but has no/stale stored price
            # fingerprint. Counted as a repair, not as in_sync, so buckets don't double-count.
            needs_repair = row.get("provider_price_id_fingerprint") != price.price_fingerprint
            if needs_repair:
                result.repairs.append(
                    _RepairAction(item_id=item_id, product_id=price.product_id, price_id=price.price_id, lookup_key=price.lookup_key)
                )
            if not price.active and row.get("active"):
                result.drift.append(CatalogDriftEntry(item_id, plan_code, item_type, "price_archived", price_fingerprint=price.price_fingerprint))
            elif _safe_int(row.get("unit_amount")) != price.unit_amount:
                result.drift.append(CatalogDriftEntry(item_id, plan_code, item_type, "amount_mismatch", _safe_int(row.get("unit_amount")), price.unit_amount, price_fingerprint=price.price_fingerprint))
            elif (row.get("recurring_interval") or None) != price.interval:
                result.drift.append(CatalogDriftEntry(item_id, plan_code, item_type, "interval_mismatch", local_interval=row.get("recurring_interval"), stripe_interval=price.interval, price_fingerprint=price.price_fingerprint))
            elif not needs_repair:
                result.in_sync += 1
        else:
            # Provisioned locally but no longer resolvable in Stripe = drift; unprovisioned rows
            # (pending/failed) are the push path's job, not a reconcile concern.
            if str(row.get("provisioning_status") or "") == "active":
                result.drift.append(CatalogDriftEntry(item_id, plan_code, item_type, "unresolved", _safe_int(row.get("unit_amount"))))

    result.candidates = _import_candidates(index, claimed_price_fps, active_plan_codes)
    return result


def _import_candidates(index: StripeCatalogIndex, claimed_price_fps: set[str], active_plan_codes: set[str]) -> list[CatalogImportCandidate]:
    candidates: list[CatalogImportCandidate] = []
    seen_lookup: set[str] = set()
    for price in index.by_price_fp.values():
        if price.price_fingerprint in claimed_price_fps or not price.active:
            continue
        plan_code = price.lookup_key or str(price.product_metadata.get("plan_code") or "") or _slug(price.product_name or "")
        if not plan_code:
            continue
        if price.lookup_key and price.lookup_key in seen_lookup:
            continue
        if price.lookup_key:
            seen_lookup.add(price.lookup_key)
        candidates.append(
            CatalogImportCandidate(
                item_type="subscription_plan" if price.interval else "credit_package",
                plan_code=plan_code,
                display_name=price.product_name or plan_code,
                currency=price.currency,
                unit_amount=price.unit_amount,
                recurring_interval=price.interval,
                lookup_key=price.lookup_key,
                product_fingerprint=price.product_fingerprint,
                price_fingerprint=price.price_fingerprint,
                plan_code_conflict=plan_code in active_plan_codes,
                product_id=price.product_id,
                price_id=price.price_id,
            )
        )
    return candidates


# --------------------------------------------------------------------------- orchestrators


def _build_index_for_group(
    *, billing_group_id: str, client: StripeBillingClient | None, db: Any, hmac_secret: str, decryption_keys_by_id: Mapping[str, str | bytes]
) -> StripeCatalogIndex:
    stripe_client = client or get_stripe_client_for_group(
        billing_group_id=billing_group_id, decryption_keys_by_id=decryption_keys_by_id, db=db
    )
    prices = stripe_client.list_prices(active=True, expand_product=True)
    return build_stripe_index(prices, hmac_secret)


def reconcile_catalog_for_group(
    *,
    billing_group_id: str,
    write: bool = True,
    client: StripeBillingClient | None = None,
    db: Any = db_billing,
    stripe_config: Any = None,
) -> CatalogReconcileReport:
    """List the group's Stripe catalog, classify drift, repair missing refs, persist sync status.

    Gating: global ``billing_enabled`` kill switch AND a buildable per-group client (which fail-closes
    on ``credential_status != active``). Never raises into the caller — Stripe failures return a
    ``retryable`` report so the worker can back off.
    """
    cfg = stripe_config or load_stripe_config()
    if not getattr(cfg, "billing_enabled", False):
        return CatalogReconcileReport(gated=True, error="billing_disabled")
    try:
        key, key_id, hmac_secret = _encryption_material()
    except CatalogSyncConfigError as exc:
        return CatalogReconcileReport(error=str(exc))

    billing_config = load_billing_config()
    try:
        index = _build_index_for_group(
            billing_group_id=billing_group_id,
            client=client,
            db=db,
            hmac_secret=hmac_secret,
            decryption_keys_by_id=billing_config.decryption_keys_by_id,
        )
    except StripeAccountNotReadyError:
        return CatalogReconcileReport(gated=True, error="account_not_ready")
    except StripeAPIError as exc:
        reason = sanitize_billing_sensitive_text(str(exc)) or "catalog reconcile failed"
        logger.warning("Catalog reconcile Stripe read failed for group %s: %s", billing_group_id, type(exc).__name__)
        return CatalogReconcileReport(error=reason, retryable=True, retry_after_seconds=exc.retry_after_seconds)
    except Exception:
        logger.warning("Catalog reconcile unexpected error for group %s", billing_group_id)
        return CatalogReconcileReport(error="catalog reconcile failed", retryable=True)

    local_rows = handle_default_list(lambda: db.list_catalog_refs_for_group(billing_group_id=billing_group_id, include_archived=False))
    classification = classify_catalog(local_rows, index)

    repaired = 0
    if write:
        for action in classification.repairs:
            try:
                product_ref = _encrypted_ref(action.product_id, kind=_PRODUCT_KIND, key=key, key_id=key_id, hmac_secret=hmac_secret)
                price_ref = _encrypted_ref(action.price_id, kind=_PRICE_KIND, key=key, key_id=key_id, hmac_secret=hmac_secret)
                db.adopt_catalog_item_refs(
                    id=action.item_id,
                    provider_product_id_ciphertext=product_ref["ciphertext"],
                    provider_product_id_hmac=product_ref["hmac"],
                    provider_product_id_fingerprint=product_ref["fingerprint"],
                    provider_price_id_ciphertext=price_ref["ciphertext"],
                    provider_price_id_hmac=price_ref["hmac"],
                    provider_price_id_fingerprint=price_ref["fingerprint"],
                    provider_ref_key_id=key_id,
                    lookup_key=action.lookup_key,
                )
                repaired += 1
            except Exception:
                logger.debug("Catalog ref repair skipped for item %s", action.item_id)

    report = CatalogReconcileReport(
        in_sync=classification.in_sync,
        missing_ref_repaired=repaired,
        drift=classification.drift,
        candidates=classification.candidates,
        synced_at=_utc_now_iso(),
    )
    if write:
        status = "drift" if (report.drift or report.candidates) else "ok"
        try:
            db.set_billing_group_catalog_sync_status(id=billing_group_id, status=status, error_redacted=None, synced_at=_utc_now_iso())
        except Exception:
            logger.debug("Catalog sync status write skipped for group %s", billing_group_id)
    return report


def import_selected_candidates(
    *,
    billing_group_id: str,
    selected_price_fingerprints: list[str],
    plan_code_overrides: Mapping[str, str] | None = None,
    client: StripeBillingClient | None = None,
    db: Any = db_billing,
    new_id: Any,
    new_hash: Any,
) -> dict[str, list[str]]:
    """Phase B: adopt selected orphan Stripe prices into the local catalog (idempotent).

    Re-lists Stripe to recover the raw ids behind the candidate fingerprints, then inserts each via
    the idempotent ``import_catalog_item`` proc (re-import of an already-adopted price is a no-op).
    Returns ``{imported, skipped, conflicts}`` lists of plan_codes.
    """
    overrides = dict(plan_code_overrides or {})
    selected = set(selected_price_fingerprints or [])
    out: dict[str, list[str]] = {"imported": [], "skipped": [], "conflicts": []}
    if not selected:
        return out

    cfg = load_stripe_config()
    if not getattr(cfg, "billing_enabled", False):
        return out
    key, key_id, hmac_secret = _encryption_material()
    billing_config = load_billing_config()
    index = _build_index_for_group(
        billing_group_id=billing_group_id,
        client=client,
        db=db,
        hmac_secret=hmac_secret,
        decryption_keys_by_id=billing_config.decryption_keys_by_id,
    )
    local_rows = handle_default_list(lambda: db.list_catalog_refs_for_group(billing_group_id=billing_group_id, include_archived=False))
    active_plan_codes = {
        str(r.get("plan_code")) for r in local_rows if r.get("active") and str(r.get("provisioning_status") or "") in {"pending", "active"}
    }

    for fp in selected:
        price = index.by_price_fp.get(fp)
        if price is None or not price.active:
            out["skipped"].append(fp)
            continue
        derived = price.lookup_key or str(price.product_metadata.get("plan_code") or "") or _slug(price.product_name or "")
        plan_code = overrides.get(fp) or derived
        if not plan_code:
            out["skipped"].append(fp)
            continue
        if plan_code in active_plan_codes:
            out["conflicts"].append(plan_code)
            continue
        item_id = new_id("bcat")
        product_ref = _encrypted_ref(price.product_id, kind=_PRODUCT_KIND, key=key, key_id=key_id, hmac_secret=hmac_secret)
        price_ref = _encrypted_ref(price.price_id, kind=_PRICE_KIND, key=key, key_id=key_id, hmac_secret=hmac_secret)
        idem = hmac_provider_ref(provider=_PROVIDER, kind="catalog_import", raw_id=price.price_id, secret=hmac_secret)
        try:
            db.import_catalog_item(
                id=item_id,
                catalog_item_hash=new_hash(),
                billing_group_id=billing_group_id,
                provider=_PROVIDER,
                item_type="subscription_plan" if price.interval else "credit_package",
                plan_code=plan_code,
                display_name=price.product_name or plan_code,
                currency=price.currency,
                unit_amount=price.unit_amount,
                recurring_interval=price.interval,
                lookup_key=price.lookup_key,
                provider_product_id_ciphertext=product_ref["ciphertext"],
                provider_product_id_hmac=product_ref["hmac"],
                provider_product_id_fingerprint=product_ref["fingerprint"],
                provider_price_id_ciphertext=price_ref["ciphertext"],
                provider_price_id_hmac=price_ref["hmac"],
                provider_price_id_fingerprint=price_ref["fingerprint"],
                provider_ref_key_id=key_id,
                provisioning_idempotency_key_hmac=idem,
            )
            out["imported"].append(plan_code)
            active_plan_codes.add(plan_code)
        except Exception:
            logger.debug("Catalog import skipped for fingerprint %s", fp)
            out["skipped"].append(fp)
    return out


def handle_default_list(fn: Any) -> list[dict[str, Any]]:
    try:
        result = fn()
        return list(result) if result else []
    except Exception:
        return []


__all__ = [
    "CatalogClassification",
    "CatalogDriftEntry",
    "CatalogImportCandidate",
    "CatalogReconcileReport",
    "CatalogSyncConfigError",
    "StripeCatalogIndex",
    "StripeCatalogPrice",
    "build_stripe_index",
    "classify_catalog",
    "import_selected_candidates",
    "reconcile_catalog_for_group",
]
