#!/usr/bin/env python3
"""Seed Patreon campaign/tier map rows without exposing raw provider IDs.

Inputs are server-only configuration. Raw campaign IDs, tier IDs, and HMAC secrets are
never printed. The database stores only HMAC-SHA256 bytes and short non-reversible
fingerprints plus internal plan/tier codes.

Expected config shape in PATREON_TIER_MAP_JSON or PATREON_TIER_MAP_FILE:
[
  {
    "campaign_id": "server-only raw campaign id",
    "campaign_name": "optional operator label",
    "tier_id": "server-only raw tier id",
    "plan_code": "pro",
    "tier_code": "artisan",
    "tier_name": "Artisan",
    "priority": 100,
    "active": true
  }
]

Use --apply to write rows. The default is validation-only dry run.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymysql
import pymysql.cursors


DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "3306")),
    "user": os.getenv("DB_USER", "root"),
    "password": os.getenv("DB_MYSQL_PASSWORD") or os.getenv("DB_PASSWORD"),
    "database": os.getenv("DB_NAME", "magic_auth"),
    "charset": "utf8mb4",
    "cursorclass": pymysql.cursors.DictCursor,
    "autocommit": False,
}


@dataclass(frozen=True)
class TierMapEntry:
    campaign_id: str
    campaign_name: str | None
    tier_id: str
    plan_code: str
    tier_code: str
    tier_name: str | None
    priority: int
    active: bool


@dataclass(frozen=True)
class SafeSeedRow:
    campaign_db_id: str
    campaign_hash: bytes
    campaign_fingerprint: str
    campaign_name: str | None
    tier_db_id: str
    tier_hash: bytes
    tier_fingerprint: str
    plan_code: str
    tier_code: str
    tier_name: str | None
    priority: int
    active: bool


class ConfigError(ValueError):
    """Raised for non-secret configuration validation failures."""


def _load_json_config(args: argparse.Namespace) -> list[dict[str, Any]]:
    if args.config_json:
        raw = args.config_json
    elif args.config_file:
        raw = Path(args.config_file).read_text(encoding="utf-8")
    elif os.getenv("PATREON_TIER_MAP_FILE"):
        raw = Path(os.environ["PATREON_TIER_MAP_FILE"]).read_text(encoding="utf-8")
    else:
        raw = os.getenv("PATREON_TIER_MAP_JSON", "")

    if not raw.strip():
        raise ConfigError("Missing PATREON_TIER_MAP_JSON or PATREON_TIER_MAP_FILE")

    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ConfigError(f"Invalid tier map JSON at byte offset {exc.pos}") from exc

    if not isinstance(parsed, list):
        raise ConfigError("Tier map config must be a JSON array")
    return parsed


def _required_text(item: dict[str, Any], key: str, index: int) -> str:
    value = item.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ConfigError(f"Tier map entry #{index} is missing required field {key}")
    return value.strip()


def _optional_text(item: dict[str, Any], key: str) -> str | None:
    value = item.get(key)
    if value is None:
        return None
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def _parse_entries(raw_entries: list[dict[str, Any]]) -> list[TierMapEntry]:
    entries: list[TierMapEntry] = []
    for index, item in enumerate(raw_entries, start=1):
        if not isinstance(item, dict):
            raise ConfigError(f"Tier map entry #{index} must be an object")

        priority_value = item.get("priority", 0)
        if not isinstance(priority_value, int):
            raise ConfigError(f"Tier map entry #{index} priority must be an integer")

        active_value = item.get("active", True)
        if not isinstance(active_value, bool):
            raise ConfigError(f"Tier map entry #{index} active must be a boolean")

        entries.append(
            TierMapEntry(
                campaign_id=_required_text(item, "campaign_id", index),
                campaign_name=_optional_text(item, "campaign_name"),
                tier_id=_required_text(item, "tier_id", index),
                plan_code=_required_text(item, "plan_code", index),
                tier_code=_required_text(item, "tier_code", index),
                tier_name=_optional_text(item, "tier_name"),
                priority=priority_value,
                active=active_value,
            )
        )
    return entries


def _validate_ambiguity(entries: list[TierMapEntry]) -> None:
    by_campaign_tier: dict[tuple[str, str], TierMapEntry] = {}
    active_priority_by_campaign: dict[tuple[str, int], TierMapEntry] = {}

    for index, entry in enumerate(entries, start=1):
        pair = (entry.campaign_id, entry.tier_id)
        prior = by_campaign_tier.get(pair)
        if prior and (
            prior.plan_code != entry.plan_code
            or prior.tier_code != entry.tier_code
            or prior.priority != entry.priority
            or prior.active != entry.active
        ):
            raise ConfigError(f"Ambiguous duplicate campaign/tier mapping at entry #{index}")
        by_campaign_tier[pair] = entry

        if entry.active:
            priority_key = (entry.campaign_id, entry.priority)
            prior_priority = active_priority_by_campaign.get(priority_key)
            if prior_priority and prior_priority.tier_id != entry.tier_id:
                raise ConfigError(f"Ambiguous active priority within a campaign at entry #{index}")
            active_priority_by_campaign[priority_key] = entry


def _hmac_digest(secret: bytes, kind: str, raw_value: str) -> bytes:
    scoped = f"patreon:{kind}:{raw_value}".encode("utf-8")
    return hmac.new(secret, scoped, hashlib.sha256).digest()


def _fingerprint(digest: bytes) -> str:
    return digest.hex()[:12]


def _safe_rows(entries: list[TierMapEntry], secret: bytes) -> list[SafeSeedRow]:
    rows: list[SafeSeedRow] = []
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        campaign_hash = _hmac_digest(secret, "campaign", entry.campaign_id)
        tier_hash = _hmac_digest(secret, "tier", entry.tier_id)
        campaign_fp = _fingerprint(campaign_hash)
        tier_fp = _fingerprint(tier_hash)
        dedupe_key = (campaign_fp, tier_fp)
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        rows.append(
            SafeSeedRow(
                campaign_db_id=f"pcamp-{campaign_fp}",
                campaign_hash=campaign_hash,
                campaign_fingerprint=campaign_fp,
                campaign_name=entry.campaign_name,
                tier_db_id=f"ptier-{campaign_fp}-{tier_fp}",
                tier_hash=tier_hash,
                tier_fingerprint=tier_fp,
                plan_code=entry.plan_code,
                tier_code=entry.tier_code,
                tier_name=entry.tier_name,
                priority=entry.priority,
                active=entry.active,
            )
        )
    return rows


def _connect():
    if not DB_CONFIG["password"]:
        raise ConfigError("Missing DB_MYSQL_PASSWORD or DB_PASSWORD for --apply")
    return pymysql.connect(**DB_CONFIG)


def _seed(rows: list[SafeSeedRow]) -> None:
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            for row in rows:
                cursor.execute(
                    """
                    INSERT INTO patreon_campaigns (
                        id, campaign_id_hash, campaign_id_fingerprint,
                        display_name, status, enabled, metadata, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE
                        display_name = VALUES(display_name),
                        status = VALUES(status),
                        enabled = VALUES(enabled),
                        metadata = VALUES(metadata),
                        updated_at = NOW()
                    """,
                    (
                        row.campaign_db_id,
                        row.campaign_hash,
                        row.campaign_fingerprint,
                        row.campaign_name,
                        "enabled" if row.active else "disabled",
                        row.active,
                        json.dumps({"source": "server_only_tier_map_seed"}),
                    ),
                )
                cursor.execute(
                    """
                    INSERT INTO patreon_tier_map (
                        id, campaign_id, tier_id_hash, tier_id_fingerprint,
                        plan_code, tier_code, tier_name, priority, active,
                        effective_from, created_at, updated_at, metadata
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW(), NOW(), %s)
                    ON DUPLICATE KEY UPDATE
                        plan_code = VALUES(plan_code),
                        tier_code = VALUES(tier_code),
                        tier_name = VALUES(tier_name),
                        priority = VALUES(priority),
                        active = VALUES(active),
                        effective_until = NULL,
                        metadata = VALUES(metadata),
                        updated_at = NOW()
                    """,
                    (
                        row.tier_db_id,
                        row.campaign_db_id,
                        row.tier_hash,
                        row.tier_fingerprint,
                        row.plan_code,
                        row.tier_code,
                        row.tier_name,
                        row.priority,
                        row.active,
                        json.dumps({"source": "server_only_tier_map_seed"}),
                    ),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Seed Patreon tier map from server-only config")
    parser.add_argument("--config-json", help="JSON array. Prefer PATREON_TIER_MAP_JSON in server-only env.")
    parser.add_argument("--config-file", help="Path to JSON array. Prefer PATREON_TIER_MAP_FILE in server-only env.")
    parser.add_argument("--apply", action="store_true", help="Write validated HMAC/fingerprint rows to DB")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; default behavior")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    secret = os.getenv("PATREON_ID_HMAC_SECRET") or os.getenv("PATREON_HMAC_SECRET")
    if not secret:
        raise ConfigError("Missing PATREON_ID_HMAC_SECRET or PATREON_HMAC_SECRET")

    raw_entries = _load_json_config(args)
    entries = _parse_entries(raw_entries)
    _validate_ambiguity(entries)
    rows = _safe_rows(entries, secret.encode("utf-8"))

    campaign_count = len({row.campaign_db_id for row in rows})
    tier_count = len(rows)

    if args.apply:
        _seed(rows)
        print(f"Patreon tier map seed applied: campaigns={campaign_count}, tiers={tier_count}. Raw IDs/secrets not printed.")
    else:
        print(f"Patreon tier map seed validated: campaigns={campaign_count}, tiers={tier_count}. Dry run only; raw IDs/secrets not printed.")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ConfigError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2)
