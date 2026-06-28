#!/usr/bin/env python3
"""Bootstrap provider-agnostic billing providers with redacted output.

Default mode is dry-run validation. Use --apply to seed disabled provider rows.
This script never prints raw provider operational identifiers, provider credentials,
HMAC values, encrypted payloads, database passwords, or environment values.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pymysql
import pymysql.cursors


ROOT = Path(__file__).resolve().parents[2]
REQUIRED_SQL_FILES = (
    ROOT / "schemas" / "tables" / "12_billing_provider_facts.sql",
    ROOT / "schemas" / "stored_procedures" / "17_billing_provider_facts.sql",
    ROOT / "schemas" / "stored_procedures" / "18_billing_groups.sql",
    ROOT / "schemas" / "triggers" / "07_billing_provider_facts_triggers.sql",
)
REQUIRED_TABLES = (
    "billing_providers",
    "billing_groups",
    "billing_group_projects",
    "billing_catalog_items",
    "billing_customers",
    "billing_checkout_intents",
    "billing_subscriptions",
    "billing_subscription_snapshots",
    "billing_entitlements_current",
    "billing_entitlement_history",
    "billing_purchase_events",
    "billing_purchase_history",
    "billing_webhook_deliveries",
    "billing_sync_jobs",
    "billing_raw_payload_quarantine",
)
REQUIRED_PROCEDURES = (
    "sp_billing_resolve_user_project",
    "sp_billing_resolve_user_billing_group",
    "sp_billing_get_current_by_user_project",
    "sp_billing_get_session_plan",
    "sp_billing_checkout_intent_begin",
    "sp_billing_checkout_intent_complete",
    "sp_billing_customer_upsert",
    "sp_billing_get_customer_operational_ref",
    "sp_billing_webhook_delivery_record",
    "sp_billing_subscription_observe",
    "sp_billing_purchase_event_record",
    "sp_billing_sync_job_enqueue",
    "sp_billing_sync_job_claim",
    "sp_billing_sync_job_complete",
    "sp_billing_retention_purge",
    "sp_billing_group_create",
    "sp_billing_group_update",
    "sp_billing_group_set_capabilities",
    "sp_billing_group_set_credentials",
    "sp_billing_group_get_operational_credentials",
    "sp_billing_group_get_by_hash",
    "sp_billing_group_list",
    "sp_billing_group_delete",
    "sp_billing_group_resolve_by_webhook_secret_hmac",
    "sp_billing_group_attach_project",
    "sp_billing_group_detach_project",
    "sp_billing_group_list_projects",
    "sp_billing_catalog_item_create",
    "sp_billing_catalog_item_set_provisioned",
    "sp_billing_catalog_item_set_failed",
    "sp_billing_catalog_item_set_active",
    "sp_billing_catalog_item_archive",
    "sp_billing_catalog_item_update",
    "sp_billing_catalog_get_operational_refs",
    "sp_billing_catalog_get_by_hash",
    "sp_billing_catalog_list_for_group",
    "sp_billing_catalog_list_for_project",
    "sp_billing_admin_metrics",
)


class BootstrapError(RuntimeError):
    """Raised for safe, non-secret bootstrap validation failures."""


@dataclass(frozen=True)
class ProviderSeed:
    id: str
    provider_code: str
    display_name: str
    status: str
    api_version: str
    checkout_enabled: bool = False
    portal_enabled: bool = False
    webhooks_enabled: bool = False
    sync_enabled: bool = False


DEFAULT_PROVIDER_SEEDS = (
    ProviderSeed(
        id="billing-provider-stripe",
        provider_code="stripe",
        display_name="Stripe",
        status="disabled",
        api_version="2026-05-27.dahlia",
    ),
)


def _load_env_file(path: str | None) -> None:
    """Load an explicit env file only when operators request it."""

    if not path:
        return
    env_path = Path(path)
    if not env_path.exists():
        raise BootstrapError(f"Env file not found: {path}")

    for raw in env_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _db_config() -> dict[str, Any]:
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_MYSQL_PASSWORD") or os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME", "magic_auth"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False,
    }


def _connect():
    config = _db_config()
    if not config["password"]:
        raise BootstrapError("Missing DB_MYSQL_PASSWORD or DB_PASSWORD for --apply/--check-db")
    return pymysql.connect(**config)


def _validate_sql_files() -> None:
    missing = [path.relative_to(ROOT).as_posix() for path in REQUIRED_SQL_FILES if not path.exists()]
    if missing:
        raise BootstrapError(f"Missing billing SQL files: {', '.join(missing)}")

    combined = "\n".join(path.read_text(encoding="utf-8", errors="ignore") for path in REQUIRED_SQL_FILES).lower()
    missing_tables = [name for name in REQUIRED_TABLES if name not in combined]
    missing_procedures = [name for name in REQUIRED_PROCEDURES if name not in combined]
    if missing_tables or missing_procedures:
        raise BootstrapError(
            "Billing SQL readiness validation failed: "
            f"missing_tables={len(missing_tables)}, missing_procedures={len(missing_procedures)}"
        )


def _check_db_readiness() -> tuple[int, int]:
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT table_name AS table_name
                FROM information_schema.tables
                WHERE table_schema = DATABASE()
                  AND table_name LIKE 'billing\\_%'
                """
            )
            found_tables = {row["table_name"] for row in cursor.fetchall()}

            cursor.execute(
                """
                SELECT routine_name AS routine_name
                FROM information_schema.routines
                WHERE routine_schema = DATABASE()
                  AND routine_type = 'PROCEDURE'
                  AND routine_name LIKE 'sp\\_billing\\_%'
                """
            )
            found_procedures = {row["routine_name"] for row in cursor.fetchall()}
    finally:
        connection.close()

    missing_tables = set(REQUIRED_TABLES) - found_tables
    missing_procedures = set(REQUIRED_PROCEDURES) - found_procedures
    if missing_tables or missing_procedures:
        raise BootstrapError(
            "Database billing schema is not ready: "
            f"missing_tables={len(missing_tables)}, missing_procedures={len(missing_procedures)}"
        )
    return len(found_tables), len(found_procedures)


def _apply_provider_seeds(seeds: tuple[ProviderSeed, ...]) -> int:
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            for seed in seeds:
                cursor.execute(
                    """
                    INSERT INTO billing_providers (
                        id, provider_code, display_name, status, checkout_enabled,
                        portal_enabled, webhooks_enabled, sync_enabled, api_version,
                        capability_metadata, created_at, updated_at
                    ) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW())
                    ON DUPLICATE KEY UPDATE
                        display_name = VALUES(display_name),
                        status = VALUES(status),
                        checkout_enabled = FALSE,
                        portal_enabled = FALSE,
                        webhooks_enabled = FALSE,
                        sync_enabled = FALSE,
                        api_version = VALUES(api_version),
                        capability_metadata = VALUES(capability_metadata),
                        updated_at = NOW()
                    """,
                    (
                        seed.id,
                        seed.provider_code,
                        seed.display_name,
                        seed.status,
                        seed.checkout_enabled,
                        seed.portal_enabled,
                        seed.webhooks_enabled,
                        seed.sync_enabled,
                        seed.api_version,
                        json.dumps(
                            {
                                "source": "billing_provider_bootstrap",
                                "default_status": "disabled",
                                "raw_values_printed": False,
                            },
                            sort_keys=True,
                        ),
                    ),
                )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return len(seeds)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap disabled billing provider registry rows")
    parser.add_argument("--env-file", help="Explicit env file for DB connection values; never loaded by default")
    parser.add_argument("--apply", action="store_true", help="Write provider seeds to billing_providers")
    parser.add_argument("--dry-run", action="store_true", help="Validate only; default behavior")
    parser.add_argument("--check-db", action="store_true", help="Validate billing tables/procedures exist in the configured DB")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _load_env_file(args.env_file)
    _validate_sql_files()

    db_summary = "db_check=skipped"
    if args.check_db or args.apply:
        table_count, procedure_count = _check_db_readiness()
        db_summary = f"db_check=ready tables={table_count} procedures={procedure_count}"

    if args.apply:
        count = _apply_provider_seeds(DEFAULT_PROVIDER_SEEDS)
        print(f"Billing provider bootstrap applied: providers={count}; {db_summary}; output=redacted")
    else:
        print(
            "Billing provider bootstrap validated: "
            f"providers={len(DEFAULT_PROVIDER_SEEDS)}; mode=dry-run; {db_summary}; output=redacted"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BootstrapError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2)
