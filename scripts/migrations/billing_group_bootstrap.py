"""Bootstrap the first billing group, its project mapping, encrypted Stripe credentials,
and catalog rows.

Idempotent and redacted: deterministic hashes mean re-runs upsert rather than duplicate,
and the script never prints secret material (Stripe secret keys, webhook secrets, or
customer ids) — only fingerprints and counts. Default mode references existing Stripe
prices by ``lookup_key``
(catalog rows are marked active with the lookup key, no api.auth->Stripe write); the admin
API (or a future ``--provision-stripe``) performs real Product/Price provisioning.

Mirrors ``billing_provider_bootstrap.py`` (dry-run default, ``--apply``, ``--check-db``).

Config (env, never printed):
  PROJECT_HASH / BILLING_PROJECT_HASH   the consuming project to attach (required for --apply)
  BILLING_GROUP_NAME                    display name (default "Magic Worlds")
  STRIPE_SECRET_KEY, STRIPE_WEBHOOK_SECRET, STRIPE_PORTAL_CONFIGURATION_ID  (optional creds)
  BILLING_PROVIDER_REF_ENCRYPTION_KEY / _ID, BILLING_ID_HMAC_SECRET         (to store creds)
  BILLING_GROUP_SEED_JSON / BILLING_GROUP_SEED_FILE                          (override catalog)
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import secrets
import sys
from pathlib import Path
from typing import Any

import pymysql
import pymysql.cursors


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

REQUIRED_TABLES = ("billing_providers", "billing_groups", "billing_group_projects", "billing_catalog_items")
REQUIRED_PROCEDURES = (
    "sp_billing_group_create",
    "sp_billing_group_attach_project",
    "sp_billing_group_set_credentials",
    "sp_billing_catalog_item_create",
    "sp_billing_catalog_item_set_provisioned",
)
PROVIDER = "stripe"

# Default catalog mirrors magic-worlds-api/src/services/billing_catalog.py. Consumer-owned
# numeric knobs (daily_credit_limit, credits) live as opaque features; api.auth never reads.
DEFAULT_SEED: dict[str, Any] = {
    "group_name": "Magic Worlds",
    "plans": [
        {"plan_code": "plus", "display_name": "Plus", "tier_code": "plus", "tier_name": "Plus",
         "amount_cents": 999, "currency": "usd", "interval": "month", "lookup_key": "plus_monthly",
         "features": {"daily_credit_limit": 100}},
        {"plan_code": "pro", "display_name": "Pro", "tier_code": "pro", "tier_name": "Pro",
         "amount_cents": 2499, "currency": "usd", "interval": "month", "lookup_key": "pro_monthly",
         "features": {"daily_credit_limit": 500}},
    ],
    "credit_packs": [
        {"plan_code": "payg_100", "display_name": "100 credits", "amount_cents": 500,
         "currency": "usd", "lookup_key": "payg_100", "features": {"credits": 100}},
        {"plan_code": "payg_250", "display_name": "250 credits", "amount_cents": 1000,
         "currency": "usd", "lookup_key": "payg_250", "features": {"credits": 250}},
        {"plan_code": "payg_750", "display_name": "750 credits", "amount_cents": 2500,
         "currency": "usd", "lookup_key": "payg_750", "features": {"credits": 750}},
    ],
}


class BootstrapError(RuntimeError):
    """Safe, non-secret bootstrap validation failure."""


def _load_env_file(path: str | None) -> None:
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


def _load_seed() -> dict[str, Any]:
    raw = os.getenv("BILLING_GROUP_SEED_JSON")
    file_path = os.getenv("BILLING_GROUP_SEED_FILE")
    if file_path:
        raw = Path(file_path).read_text(encoding="utf-8")
    if raw:
        try:
            seed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise BootstrapError("BILLING_GROUP_SEED_JSON/_FILE is not valid JSON") from exc
        if not isinstance(seed, dict):
            raise BootstrapError("billing group seed must be a JSON object")
        return seed
    seed = dict(DEFAULT_SEED)
    seed["group_name"] = os.getenv("BILLING_GROUP_NAME") or seed["group_name"]
    return seed


def _project_hash() -> str:
    return (os.getenv("BILLING_PROJECT_HASH") or os.getenv("PROJECT_HASH") or "").strip()


def _validate_sql_files() -> None:
    files = (
        ROOT / "schemas" / "tables" / "12_billing_provider_facts.sql",
        ROOT / "schemas" / "stored_procedures" / "18_billing_groups.sql",
    )
    missing = [f.relative_to(ROOT).as_posix() for f in files if not f.exists()]
    if missing:
        raise BootstrapError(f"Missing billing SQL files: {', '.join(missing)}")
    combined = "\n".join(f.read_text(encoding="utf-8", errors="ignore") for f in files).lower()
    missing_tables = [t for t in REQUIRED_TABLES if t not in combined]
    missing_procs = [p for p in REQUIRED_PROCEDURES if p not in combined]
    if missing_tables or missing_procs:
        raise BootstrapError(
            f"Billing group SQL readiness failed: missing_tables={missing_tables}, missing_procedures={missing_procs}"
        )


def _check_db_readiness() -> None:
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            placeholders = ", ".join(["%s"] * len(REQUIRED_TABLES))
            cursor.execute(
                "SELECT table_name AS table_name FROM information_schema.tables "
                f"WHERE table_schema = DATABASE() AND table_name IN ({placeholders})",
                REQUIRED_TABLES,
            )
            found = {row["table_name"] for row in cursor.fetchall()}
            cursor.execute(
                "SELECT 1 FROM billing_providers WHERE provider_code = %s LIMIT 1",
                (PROVIDER,),
            )
            provider_ready = cursor.fetchone() is not None
    finally:
        connection.close()
    missing = set(REQUIRED_TABLES) - found
    if missing:
        raise BootstrapError(f"Database not ready: missing billing-group tables {sorted(missing)}")
    if not provider_ready:
        raise BootstrapError(
            "Billing provider registry is missing 'stripe'; run "
            "scripts/migrations/billing_provider_bootstrap.py --apply first"
        )


def _deterministic_hash(*parts: str) -> str:
    return hashlib.sha256(":".join(parts).encode("utf-8")).hexdigest().upper()


def _encrypt_credentials(summary: dict[str, Any]) -> dict[str, Any] | None:
    """Encrypt operator-supplied Stripe creds. Returns proc args or None when unavailable."""
    secret_key = (os.getenv("STRIPE_SECRET_KEY") or "").strip()
    if not secret_key:
        return None
    enc_key = (os.getenv("BILLING_PROVIDER_REF_ENCRYPTION_KEY") or "").strip()
    enc_key_id = (os.getenv("BILLING_PROVIDER_REF_ENCRYPTION_KEY_ID") or "").strip()
    hmac_secret = (os.getenv("BILLING_ID_HMAC_SECRET") or "").strip()
    if not enc_key or not enc_key_id or not hmac_secret:
        summary["credentials"] = "skipped (encryption keys not configured)"
        return None

    from src.Util.billing.security import encrypt_provider_ref, hmac_provider_ref, provider_ref_fingerprint

    def enc(raw: str, kind: str):
        ct = encrypt_provider_ref(raw_ref=raw, key=enc_key, key_id=enc_key_id, provider=PROVIDER).ciphertext
        digest = hmac_provider_ref(provider=PROVIDER, kind=kind, raw_id=raw, secret=hmac_secret)
        return ct, digest, provider_ref_fingerprint(digest=digest)

    secret_ct, secret_hmac, secret_fp = enc(secret_key, "account_secret_key")
    webhook_secret = (os.getenv("STRIPE_WEBHOOK_SECRET") or "").strip()
    webhook_ct = webhook_hmac = webhook_fp = None
    if webhook_secret:
        webhook_ct, webhook_hmac, webhook_fp = enc(webhook_secret, "account_webhook_secret")
    portal_id = (os.getenv("STRIPE_PORTAL_CONFIGURATION_ID") or "").strip()
    portal_ct = encrypt_provider_ref(raw_ref=portal_id, key=enc_key, key_id=enc_key_id, provider=PROVIDER).ciphertext if portal_id else None

    summary["credentials"] = {"secret_key_fingerprint": secret_fp, "webhook_secret_fingerprint": webhook_fp}
    return {
        "label": os.getenv("BILLING_GROUP_NAME") or "Magic Worlds",
        "account_fingerprint": secret_fp,
        "secret_ct": secret_ct, "secret_hmac": secret_hmac, "secret_fp": secret_fp,
        "webhook_ct": webhook_ct, "webhook_hmac": webhook_hmac, "webhook_fp": webhook_fp,
        "portal_ct": portal_ct, "key_id": enc_key_id,
    }


def _apply(seed: dict[str, Any], project_hash: str) -> dict[str, Any]:
    summary: dict[str, Any] = {"group": None, "project_attached": False, "plans": 0, "credit_packs": 0}
    group_name = str(seed.get("group_name") or "Magic Worlds")
    group_hash = _deterministic_hash("billing-group", project_hash or "-", group_name)

    creds = _encrypt_credentials(summary)
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            # Resolve the project.
            cursor.execute("SELECT id FROM projects WHERE project_hash = %s LIMIT 1", (project_hash,))
            project_row = cursor.fetchone()
            if not project_row:
                raise BootstrapError("Project not found for the configured PROJECT_HASH/BILLING_PROJECT_HASH")
            project_id = project_row["id"]

            # Create (or reuse) the billing group.
            cursor.execute("SELECT id FROM billing_groups WHERE billing_group_hash = %s LIMIT 1", (group_hash,))
            existing = cursor.fetchone()
            if existing:
                group_id = existing["id"]
            else:
                group_id = f"bg-{secrets.token_hex(24)}"
                cursor.callproc("sp_billing_group_create", (group_id, group_hash, group_name, None, None, PROVIDER, None))
                cursor.fetchall()
            summary["group"] = group_hash

            # Attach the project (idempotent re-home/no-op on the same group).
            cursor.callproc("sp_billing_group_attach_project", (f"bgp-{secrets.token_hex(24)}", group_id, project_id, None))
            cursor.fetchall()
            summary["project_attached"] = True

            # Store encrypted credentials when supplied.
            if creds:
                cursor.callproc(
                    "sp_billing_group_set_credentials",
                    (group_id, creds["label"], creds["account_fingerprint"],
                     creds["secret_ct"], creds["secret_hmac"], creds["secret_fp"],
                     creds["webhook_ct"], creds["webhook_hmac"], creds["webhook_fp"],
                     creds["portal_ct"], creds["key_id"]),
                )
                cursor.fetchall()

            # Seed catalog items (reference mode: active with lookup_key, no Stripe write).
            for item_type, key in (("subscription_plan", "plans"), ("credit_package", "credit_packs")):
                for item in seed.get(key) or []:
                    plan_code = str(item.get("plan_code") or "").strip()
                    if not plan_code:
                        continue
                    item_hash = _deterministic_hash("catalog", group_id, item_type, plan_code)
                    cursor.execute("SELECT id FROM billing_catalog_items WHERE catalog_item_hash = %s LIMIT 1", (item_hash,))
                    if cursor.fetchone():
                        summary[key] += 1
                        continue
                    item_id = f"bcat-{secrets.token_hex(24)}"
                    cursor.callproc(
                        "sp_billing_catalog_item_create",
                        (item_id, item_hash, group_id, PROVIDER, item_type, plan_code,
                         item.get("tier_code"), item.get("tier_name"), str(item.get("display_name") or plan_code),
                         item.get("currency"), item.get("amount_cents"), item.get("interval"),
                         item.get("lookup_key"), json.dumps(item.get("features") or {}, sort_keys=True),
                         None, item.get("sort_order", 0), None, None),
                    )
                    cursor.fetchall()
                    # Reference existing Stripe price by lookup_key: mark active+provisioned
                    # with no encrypted product/price refs (no api.auth->Stripe write).
                    cursor.callproc(
                        "sp_billing_catalog_item_set_provisioned",
                        (item_id, None, None, None, None, None, None, None, item.get("lookup_key"), True),
                    )
                    cursor.fetchall()
                    summary[key] += 1
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
    return summary


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Bootstrap the first billing group, project mapping, encrypted creds, and catalog")
    parser.add_argument("--env-file", help="Explicit env file for DB/secrets; never loaded by default")
    parser.add_argument("--apply", action="store_true", help="Write the group, mapping, credentials, and catalog")
    parser.add_argument("--dry-run", action="store_true", help="Validate only (default)")
    parser.add_argument("--check-db", action="store_true", help="Validate billing-group tables exist")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    _load_env_file(args.env_file)
    _validate_sql_files()
    seed = _load_seed()
    project_hash = _project_hash()

    if args.check_db or args.apply:
        _check_db_readiness()

    if args.apply:
        if not project_hash:
            raise BootstrapError("--apply requires PROJECT_HASH or BILLING_PROJECT_HASH")
        summary = _apply(seed, project_hash)
        print(
            "Billing group bootstrap applied: "
            f"group={'created/updated' if summary['group'] else 'none'} "
            f"project_attached={summary['project_attached']} plans={summary['plans']} "
            f"credit_packs={summary['credit_packs']} credentials="
            f"{'set' if isinstance(summary.get('credentials'), dict) else summary.get('credentials', 'absent')}; "
            "output=redacted"
        )
    else:
        plans = len(seed.get("plans") or [])
        packs = len(seed.get("credit_packs") or [])
        print(
            "Billing group bootstrap validated: "
            f"mode=dry-run plans={plans} credit_packs={packs} "
            f"project_hash={'set' if project_hash else 'missing'}; output=redacted"
        )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except BootstrapError as exc:
        print(f"Configuration error: {exc}", file=sys.stderr)
        raise SystemExit(2)
