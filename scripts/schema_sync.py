#!/usr/bin/env python3
"""Audit and apply additive MySQL schema catch-up for the dev database.

This tool is intentionally conservative: it does not drop or recreate the
database. It applies only canonical schema files and explicit stale-artifact
cleanup that can be verified from the checked-out SQL.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pymysql
import pymysql.cursors


ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "schemas"

PATCH_FILES = (
    "tables/09_email_activation_tables.sql",
    "tables/10_external_accounts.sql",
    "tables/11_patreon_entitlements.sql",
    "stored_procedures/14_email_activation.sql",
    "stored_procedures/15_external_accounts.sql",
    "stored_procedures/16_patreon_entitlements.sql",
    "stored_procedures/18_billing_groups.sql",
    "triggers/04_email_activation_triggers.sql",
    "triggers/05_external_accounts_triggers.sql",
    "triggers/06_patreon_entitlements_triggers.sql",
)

# Additive column catch-up for existing DBs (MySQL has no ADD COLUMN IF NOT EXISTS).
COLUMN_PATCHES = (
    (
        "billing_groups.last_catalog_synced_at",
        "ALTER TABLE billing_groups ADD COLUMN last_catalog_synced_at DATETIME NULL",
    ),
    (
        "billing_groups.catalog_sync_status",
        "ALTER TABLE billing_groups ADD COLUMN catalog_sync_status ENUM('never','ok','drift','error') NOT NULL DEFAULT 'never'",
    ),
    (
        "billing_groups.catalog_sync_error_redacted",
        "ALTER TABLE billing_groups ADD COLUMN catalog_sync_error_redacted TEXT NULL",
    ),
)

CANONICAL_ENUMS = {
    ("user_external_accounts", "provider"): "enum('google','patreon')",
    (
        "email_messages",
        "purpose",
    ): "enum('email_activation','password_reset','admin_password_reset','security_notification','delivery_operation','patreon_link_proof')",
    (
        "email_delivery_attempts",
        "status",
    ): "enum('sent','temporary_failure','permanent_failure','suppressed','cancelled','webhook_event')",
}

ENUM_PATCHES = (
    (
        "user_external_accounts.provider",
        "ALTER TABLE user_external_accounts MODIFY provider ENUM('google','patreon') NOT NULL",
    ),
    (
        "email_messages.purpose",
        """
        ALTER TABLE email_messages
            MODIFY purpose ENUM(
                'email_activation',
                'password_reset',
                'admin_password_reset',
                'security_notification',
                'delivery_operation',
                'patreon_link_proof'
            ) NOT NULL
        """,
    ),
    (
        "email_delivery_attempts.status",
        """
        ALTER TABLE email_delivery_attempts
            MODIFY status ENUM(
                'sent',
                'temporary_failure',
                'permanent_failure',
                'suppressed',
                'cancelled',
                'webhook_event'
            ) NOT NULL
        """,
    ),
)

STALE_PROCEDURES = ("sp_backfill_legacy_user_emails",)
STALE_TEMPLATE_CODE = "free_credit_invite"


@dataclass(frozen=True)
class Drift:
    kind: str
    missing_in_db: tuple[str, ...]
    extra_in_db: tuple[str, ...]


def _load_env_file(path: Path) -> None:
    if not path.exists():
        raise SystemExit(f"Env file not found: {path}")

    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export ") :].strip()
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if (
            len(value) >= 2
            and value[0] == value[-1]
            and value[0] in {"'", '"'}
        ):
            value = value[1:-1]
        os.environ.setdefault(key, value)


def _db_config() -> dict[str, object]:
    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": int(os.getenv("DB_PORT", "3306")),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_MYSQL_PASSWORD") or os.getenv("DB_PASSWORD"),
        "database": os.getenv("DB_NAME", "magic_auth"),
        "charset": "utf8mb4",
        "cursorclass": pymysql.cursors.DictCursor,
        "autocommit": False,
        "connect_timeout": 10,
        "read_timeout": 30,
        "write_timeout": 30,
    }


def _connect():
    cfg = _db_config()
    if not cfg["password"]:
        raise SystemExit("Missing DB_MYSQL_PASSWORD or DB_PASSWORD")
    return pymysql.connect(**cfg)


def _target_label() -> str:
    cfg = _db_config()
    return f"{cfg['host']}:{cfg['port']}/{cfg['database']} as {cfg['user']} (password redacted)"


def _split_sql_statements(sql_content: str) -> list[str]:
    current_delimiter = ";"
    current_statement: list[str] = []
    statements: list[str] = []

    def flush() -> None:
        if not current_statement:
            return
        stmt = "\n".join(current_statement).strip()
        current_statement.clear()
        if stmt:
            statements.append(stmt)

    for line in sql_content.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("--"):
            continue
        if stripped.upper().startswith("DELIMITER"):
            flush()
            parts = stripped.split()
            if len(parts) > 1:
                current_delimiter = parts[1]
            continue

        current_statement.append(line)
        if stripped.endswith(current_delimiter):
            stmt = "\n".join(current_statement).strip()
            if current_delimiter == ";":
                stmt = stmt[:-1].strip()
            else:
                stmt = stmt[: -len(current_delimiter)].strip()
            current_statement.clear()
            if stmt:
                statements.append(stmt)

    flush()
    return statements


def _execute_statements(cursor, statements: Iterable[str]) -> int:
    count = 0
    for statement in statements:
        cursor.execute(statement)
        count += 1
    return count


def _run_sql_file(cursor, relative_path: str) -> int:
    path = SCHEMAS_DIR / relative_path
    if not path.exists():
        raise SystemExit(f"Missing canonical SQL file: {path}")
    statements = _split_sql_statements(path.read_text(encoding="utf-8"))
    return _execute_statements(cursor, statements)


def _column_type(cursor, table: str, column: str) -> str | None:
    cursor.execute(
        """
        SELECT COLUMN_TYPE
        FROM information_schema.columns
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND column_name = %s
        """,
        (table, column),
    )
    row = cursor.fetchone()
    return None if row is None else str(row["COLUMN_TYPE"]).lower()


def _table_exists(cursor, table: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.tables
        WHERE table_schema = DATABASE()
          AND table_name = %s
        """,
        (table,),
    )
    return int(cursor.fetchone()["count"]) == 1


def _apply_enum_patches(cursor, *, dry_run: bool) -> list[str]:
    changed: list[str] = []
    for label, sql in ENUM_PATCHES:
        table, column = label.split(".", 1)
        current = _column_type(cursor, table, column)
        expected = CANONICAL_ENUMS[(table, column)]
        if current is None:
            changed.append(f"skip missing column {label}; canonical files will create it if needed")
            continue
        if current == expected:
            continue
        changed.append(f"widen {label}: {current} -> {expected}")
        if not dry_run:
            cursor.execute(sql)
    return changed


def _apply_column_patches(cursor, *, dry_run: bool) -> list[str]:
    changed: list[str] = []
    for label, sql in COLUMN_PATCHES:
        table, column = label.split(".", 1)
        if _column_type(cursor, table, column) is not None:
            continue
        changed.append(f"add column {label}")
        if not dry_run:
            cursor.execute(sql)
    return changed


def _extract_patreon_activity_upsert() -> str:
    source = (SCHEMAS_DIR / "tables/08_activity_logging_tables.sql").read_text(
        encoding="utf-8"
    )
    marker = "-- Patreon Entitlement/Link Activities"
    start = source.find(marker)
    if start < 0:
        raise SystemExit("Could not find Patreon activity catalog block")
    insert_start = source.find("INSERT INTO activity_catalog", start)
    update_end = source.find("is_active = VALUES(is_active);", insert_start)
    if insert_start < 0 or update_end < 0:
        raise SystemExit("Could not extract Patreon activity catalog upsert")
    update_end += len("is_active = VALUES(is_active);")
    return source[insert_start:update_end]


def _apply_patreon_activity_catalog(cursor, *, dry_run: bool) -> str:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM activity_catalog
        WHERE activity_code LIKE 'patreon_%'
        """
    )
    before = int(cursor.fetchone()["count"])
    if dry_run:
        return f"upsert Patreon activity catalog rows (currently {before})"
    cursor.execute(_extract_patreon_activity_upsert())
    return "upserted Patreon activity catalog rows"


def _cleanup_stale_objects(cursor, *, dry_run: bool) -> list[str]:
    actions: list[str] = []
    for procedure in STALE_PROCEDURES:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM information_schema.routines
            WHERE routine_schema = DATABASE()
              AND routine_type = 'PROCEDURE'
              AND routine_name = %s
            """,
            (procedure,),
        )
        if int(cursor.fetchone()["count"]) > 0:
            actions.append(f"drop stale procedure {procedure}")
            if not dry_run:
                cursor.execute(f"DROP PROCEDURE IF EXISTS {procedure}")

    message_refs = 0
    if _table_exists(cursor, "email_messages"):
        cursor.execute(
            "SELECT COUNT(*) AS count FROM email_messages WHERE template_code = %s",
            (STALE_TEMPLATE_CODE,),
        )
        message_refs = int(cursor.fetchone()["count"])

    template_rows = 0
    if _table_exists(cursor, "email_templates"):
        cursor.execute(
            "SELECT COUNT(*) AS count FROM email_templates WHERE template_code = %s",
            (STALE_TEMPLATE_CODE,),
        )
        template_rows = int(cursor.fetchone()["count"])
    if template_rows:
        if message_refs:
            actions.append(
                f"deactivate stale template {STALE_TEMPLATE_CODE}; referenced by {message_refs} email_messages rows"
            )
            if not dry_run:
                cursor.execute(
                    """
                    UPDATE email_templates
                       SET is_active = FALSE
                     WHERE template_code = %s
                    """,
                    (STALE_TEMPLATE_CODE,),
                )
        else:
            actions.append(f"delete unreferenced stale template {STALE_TEMPLATE_CODE}")
            if not dry_run:
                cursor.execute(
                    "DELETE FROM email_templates WHERE template_code = %s",
                    (STALE_TEMPLATE_CODE,),
                )

    catalog_rows = 0
    if _table_exists(cursor, "email_template_catalog"):
        cursor.execute(
            "SELECT COUNT(*) AS count FROM email_template_catalog WHERE template_code = %s",
            (STALE_TEMPLATE_CODE,),
        )
        catalog_rows = int(cursor.fetchone()["count"])
    if catalog_rows:
        actions.append(f"remove stale catalog row {STALE_TEMPLATE_CODE}")
        if not dry_run:
            cursor.execute(
                "DELETE FROM email_template_catalog WHERE template_code = %s",
                (STALE_TEMPLATE_CODE,),
            )

    return actions


def _clean_name(name: str) -> str:
    cleaned = name.strip().strip("`")
    if "." in cleaned:
        cleaned = cleaned.split(".")[-1].strip("`")
    return cleaned


def _expected_objects() -> dict[str, set[str]]:
    patterns = {
        "tables": re.compile(
            r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?([`\w.]+)",
            re.IGNORECASE,
        ),
        "views": re.compile(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+([`\w.]+)",
            re.IGNORECASE,
        ),
        "procedures": re.compile(
            r"CREATE\s+PROCEDURE\s+([`\w.]+)",
            re.IGNORECASE,
        ),
        "triggers": re.compile(
            r"CREATE\s+TRIGGER\s+([`\w.]+)",
            re.IGNORECASE,
        ),
    }
    expected = {kind: set() for kind in patterns}
    for path in sorted(SCHEMAS_DIR.glob("**/*.sql")):
        source = path.read_text(encoding="utf-8")
        for kind, pattern in patterns.items():
            expected[kind].update(_clean_name(match.group(1)) for match in pattern.finditer(source))
    return expected


def _live_objects(cursor) -> dict[str, set[str]]:
    queries = {
        "tables": """
            SELECT table_name AS name
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_type = 'BASE TABLE'
        """,
        "views": """
            SELECT table_name AS name
            FROM information_schema.views
            WHERE table_schema = DATABASE()
        """,
        "procedures": """
            SELECT routine_name AS name
            FROM information_schema.routines
            WHERE routine_schema = DATABASE()
              AND routine_type = 'PROCEDURE'
        """,
        "triggers": """
            SELECT trigger_name AS name
            FROM information_schema.triggers
            WHERE trigger_schema = DATABASE()
        """,
    }
    live: dict[str, set[str]] = {}
    for kind, query in queries.items():
        cursor.execute(query)
        live[kind] = {str(row["name"]) for row in cursor.fetchall()}
    return live


def _diff_objects(cursor) -> list[Drift]:
    expected = _expected_objects()
    live = _live_objects(cursor)
    drift: list[Drift] = []
    for kind in ("tables", "views", "procedures", "triggers"):
        missing = tuple(sorted(expected[kind] - live[kind]))
        extra = tuple(sorted(live[kind] - expected[kind]))
        drift.append(Drift(kind, missing, extra))
    return drift


def _verify_markers(cursor) -> list[str]:
    failures: list[str] = []
    for (table, column), expected in CANONICAL_ENUMS.items():
        current = _column_type(cursor, table, column)
        if current != expected:
            failures.append(f"{table}.{column} is {current!r}, expected {expected!r}")

    for table in (
        "email_template_catalog",
        "patreon_link_proofs",
        "patreon_campaigns",
        "patreon_tier_map",
        "patreon_memberships",
        "patreon_member_snapshots",
        "patreon_member_snapshot_history",
        "patreon_entitlements_current",
        "patreon_entitlement_history",
        "patreon_webhook_deliveries",
        "patreon_sync_jobs",
        "patreon_raw_payload_quarantine",
        "patreon_provider_token_state",
    ):
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM information_schema.tables
            WHERE table_schema = DATABASE()
              AND table_name = %s
            """,
            (table,),
        )
        if int(cursor.fetchone()["count"]) != 1:
            failures.append(f"missing table {table}")

    for procedure in STALE_PROCEDURES:
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM information_schema.routines
            WHERE routine_schema = DATABASE()
              AND routine_type = 'PROCEDURE'
              AND routine_name = %s
            """,
            (procedure,),
        )
        if int(cursor.fetchone()["count"]) != 0:
            failures.append(f"stale procedure still exists: {procedure}")

    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM email_templates
        WHERE template_code = %s
          AND is_active = TRUE
        """,
        (STALE_TEMPLATE_CODE,),
    )
    if int(cursor.fetchone()["count"]) != 0:
        failures.append(f"stale template still active: {STALE_TEMPLATE_CODE}")

    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM activity_catalog
        WHERE activity_code LIKE 'patreon_%'
        """
    )
    if int(cursor.fetchone()["count"]) < 16:
        failures.append("Patreon activity catalog range is incomplete")

    return failures


def _print_drift(drift: Iterable[Drift]) -> bool:
    has_drift = False
    for item in drift:
        if item.missing_in_db or item.extra_in_db:
            has_drift = True
        print(
            f"{item.kind}: missing_in_db={len(item.missing_in_db)} extra_in_db={len(item.extra_in_db)}"
        )
        for name in item.missing_in_db:
            print(f"  missing: {name}")
        for name in item.extra_in_db:
            print(f"  extra: {name}")
    return has_drift


def run(*, dry_run: bool, apply: bool, verify: bool) -> int:
    print(f"Target: {_target_label()}")
    connection = _connect()
    try:
        with connection.cursor() as cursor:
            if dry_run:
                print("\nPlanned additive actions:")
                enum_actions = _apply_enum_patches(cursor, dry_run=True)
                for action in enum_actions:
                    print(f"  - {action}")
                for action in _apply_column_patches(cursor, dry_run=True):
                    print(f"  - {action}")
                for relative_path in PATCH_FILES:
                    print(f"  - execute canonical SQL {relative_path}")
                print(f"  - {_apply_patreon_activity_catalog(cursor, dry_run=True)}")
                for action in _cleanup_stale_objects(cursor, dry_run=True):
                    print(f"  - {action}")
                print("\nCurrent object drift:")
                _print_drift(_diff_objects(cursor))
                return 0

            if apply:
                print("\nApplying additive schema catch-up...")
                for action in _apply_enum_patches(cursor, dry_run=False):
                    print(f"  - {action}")
                for action in _apply_column_patches(cursor, dry_run=False):
                    print(f"  - {action}")
                # Column patches must precede the billing procs file (some procs reference the
                # new columns at runtime; MySQL doesn't validate proc bodies at CREATE time, but
                # ordering keeps a clean apply log).
                for relative_path in PATCH_FILES:
                    count = _run_sql_file(cursor, relative_path)
                    print(f"  - executed {relative_path} ({count} statements)")
                print(f"  - {_apply_patreon_activity_catalog(cursor, dry_run=False)}")
                for action in _cleanup_stale_objects(cursor, dry_run=False):
                    print(f"  - {action}")
                connection.commit()

            if verify:
                print("\nVerifying live DB against canonical SQL...")
                drift = _diff_objects(cursor)
                has_drift = _print_drift(drift)
                failures = _verify_markers(cursor)
                if failures:
                    print("\nMarker failures:")
                    for failure in failures:
                        print(f"  - {failure}")
                if has_drift or failures:
                    return 1
                print("Verification passed: live DB matches canonical SQL and cleanup markers.")
                return 0

        return 0
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Audit/apply additive schema cleanup against a MySQL env file."
    )
    parser.add_argument("--env-file", default=".env", help="Env file with DB_* settings")
    parser.add_argument("--dry-run", action="store_true", help="Show planned actions")
    parser.add_argument("--apply", action="store_true", help="Apply additive cleanup")
    parser.add_argument("--verify", action="store_true", help="Verify object drift and markers")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    if args.dry_run and args.apply:
        parser.error("--dry-run cannot be combined with --apply")

    env_path = Path(args.env_file)
    if not env_path.is_absolute():
        env_path = ROOT / env_path
    _load_env_file(env_path)

    dry_run = args.dry_run or not args.apply and not args.verify
    return run(dry_run=dry_run, apply=args.apply, verify=args.verify)


if __name__ == "__main__":
    raise SystemExit(main())
