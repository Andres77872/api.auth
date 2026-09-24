"""Patreon campaign/tier-map catalog mirror.

The server-only tier-map configuration (``PATREON_CAMPAIGN_TIER_MAP`` and friends)
is the classification authority. The database keeps an HMAC/fingerprint mirror of
it because memberships reference their campaign row and the ROOT dashboard lists
the map. This module keeps that mirror in step with the configuration so an
operator never has to remember to re-run the seed script after editing config.

It also owns the mapping between raw configured campaign IDs and the internal
``pcamp-<fingerprint>`` IDs stored in the database. Raw IDs never leave memory.
"""

from __future__ import annotations

import hashlib
import logging
import threading
from typing import Any

from src.Util.db import db_patreon
from src.Util.patreon.security import fingerprint_from_digest, hash_patreon_identifier


logger = logging.getLogger(__name__)

_lock = threading.Lock()
_synced_fingerprint: str | None = None


def _id_secret(config: Any) -> str | bytes | None:
    return getattr(config, "id_hmac_secret", None) or getattr(config, "provider_sub_pepper", None)


def campaign_db_id(raw_campaign_id: str | None, config: Any) -> str | None:
    """Return the internal ``pcamp-<fingerprint>`` id for a raw campaign id."""

    secret = _id_secret(config)
    if not raw_campaign_id or not secret:
        return None
    digest = hash_patreon_identifier(raw_id=str(raw_campaign_id), kind="campaign", pepper=secret)
    return f"pcamp-{fingerprint_from_digest(digest)}"


def configured_campaign_ids(config: Any) -> tuple[str, ...]:
    """Raw campaign ids from the tier map plus ``PATREON_CAMPAIGN_IDS``, in order."""

    ids = getattr(config, "campaign_ids", None)
    if isinstance(ids, (list, tuple)):
        return tuple(str(item).strip() for item in ids if str(item).strip())
    return ()


def raw_campaign_id_for(campaign_id: str | None, config: Any) -> str | None:
    """Resolve a stored campaign reference to a configured raw campaign id.

    Sync jobs store the internal ``pcamp-...`` id (raw ids are never persisted);
    the Patreon API needs the raw id. Unknown references resolve to ``None`` so a
    caller falls back to scanning every configured campaign instead of calling
    Patreon with an id it does not know.
    """

    if not campaign_id:
        return None
    configured = configured_campaign_ids(config)
    if campaign_id in configured:
        return campaign_id
    for raw_id in configured:
        if campaign_db_id(raw_id, config) == campaign_id:
            return raw_id
    return None


def _catalog_rows(config: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    secret = _id_secret(config)
    if not secret:
        return [], []
    campaign_names: dict[str, str | None] = {}
    tiers: list[dict[str, Any]] = []
    for entry in getattr(config, "campaign_tier_maps", ()) or ():
        raw_campaign = getattr(entry, "campaign_id", None)
        raw_tier = getattr(entry, "tier_id", None)
        if not raw_campaign or not raw_tier:
            continue
        if not campaign_names.get(raw_campaign):
            campaign_names[raw_campaign] = getattr(entry, "campaign_name", None)
        campaign_hash = hash_patreon_identifier(raw_id=raw_campaign, kind="campaign", pepper=secret)
        tier_hash = hash_patreon_identifier(raw_id=raw_tier, kind="tier", pepper=secret)
        campaign_fp = fingerprint_from_digest(campaign_hash)
        tier_fp = fingerprint_from_digest(tier_hash)
        tiers.append(
            {
                "tier_map_id": f"ptier-{campaign_fp}-{tier_fp}",
                "campaign_db_id": f"pcamp-{campaign_fp}",
                "tier_id_hash": tier_hash,
                "tier_id_fingerprint": tier_fp,
                "plan_code": entry.plan_code,
                "tier_code": entry.tier_code,
                "tier_name": getattr(entry, "tier_name", None),
                "priority": int(getattr(entry, "priority", 0) or 0),
                "active": bool(getattr(entry, "active", True)),
            }
        )
    for raw_campaign in configured_campaign_ids(config):
        campaign_names.setdefault(raw_campaign, None)

    campaigns: list[dict[str, Any]] = []
    for raw_campaign, name in campaign_names.items():
        campaign_hash = hash_patreon_identifier(raw_id=raw_campaign, kind="campaign", pepper=secret)
        campaign_fp = fingerprint_from_digest(campaign_hash)
        campaigns.append(
            {
                "campaign_db_id": f"pcamp-{campaign_fp}",
                "campaign_id_hash": campaign_hash,
                "campaign_id_fingerprint": campaign_fp,
                "display_name": str(name)[:120] if name else None,
                "enabled": True,
            }
        )
    return campaigns, tiers


def _rows_fingerprint(campaigns: list[dict[str, Any]], tiers: list[dict[str, Any]]) -> str:
    material = repr(
        (
            sorted((row["campaign_db_id"], row["display_name"]) for row in campaigns),
            sorted(
                (
                    row["tier_map_id"],
                    row["plan_code"],
                    row["tier_code"],
                    row["tier_name"],
                    row["priority"],
                    row["active"],
                )
                for row in tiers
            ),
        )
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def ensure_patreon_catalog(config: Any, *, db_module: Any = db_patreon, force: bool = False) -> dict[str, int]:
    """Mirror the configured campaigns/tier map into the DB catalog, idempotently.

    Runs once per distinct configuration per process (``force`` re-runs it). An
    empty tier map never retires anything: that is a misconfiguration readiness
    already reports, not an instruction to disable every campaign.
    """

    global _synced_fingerprint

    campaigns, tiers = _catalog_rows(config)
    if not campaigns:
        return {"campaigns": 0, "tiers": 0, "skipped": 1}
    fingerprint = _rows_fingerprint(campaigns, tiers)
    with _lock:
        if not force and fingerprint == _synced_fingerprint:
            return {"campaigns": len(campaigns), "tiers": len(tiers), "skipped": 1}
        for row in campaigns:
            db_module.upsert_patreon_catalog_campaign(**row)
        for row in tiers:
            db_module.upsert_patreon_catalog_tier(**row)
        if tiers:
            db_module.retire_unconfigured_patreon_catalog(
                campaign_db_ids=[row["campaign_db_id"] for row in campaigns],
                tier_map_ids=[row["tier_map_id"] for row in tiers],
            )
        _synced_fingerprint = fingerprint
    logger.info("Patreon catalog mirrored: campaigns=%s tiers=%s", len(campaigns), len(tiers))
    return {"campaigns": len(campaigns), "tiers": len(tiers), "skipped": 0}


def ensure_patreon_catalog_safely(config: Any, *, db_module: Any = db_patreon) -> bool:
    """``ensure_patreon_catalog`` for request/worker paths: never raises."""

    try:
        ensure_patreon_catalog(config, db_module=db_module)
        return True
    except Exception as exc:  # noqa: BLE001 - callers degrade instead of failing the request
        logger.warning("Patreon catalog mirror failed: %s", type(exc).__name__)
        return False


def reset_catalog_cache() -> None:
    """Forget the last mirrored configuration (tests, config reloads)."""

    global _synced_fingerprint
    with _lock:
        _synced_fingerprint = None


__all__ = [
    "campaign_db_id",
    "configured_campaign_ids",
    "ensure_patreon_catalog",
    "ensure_patreon_catalog_safely",
    "raw_campaign_id_for",
    "reset_catalog_cache",
]
