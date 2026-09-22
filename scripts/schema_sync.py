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
    # OAuth catalog/connections/bindings. Listed before the procedure and trigger files:
    # the external-account triggers validate the provider against oauth_provider_catalog.
    "tables/13_oauth_connections.sql",
    "stored_procedures/14_email_activation.sql",
    "stored_procedures/15_external_accounts.sql",
    "stored_procedures/16_patreon_entitlements.sql",
    "stored_procedures/18_billing_groups.sql",
    "stored_procedures/19_oauth_connections.sql",
    "triggers/04_email_activation_triggers.sql",
    "triggers/05_external_accounts_triggers.sql",
    "triggers/06_patreon_entitlements_triggers.sql",
    "triggers/08_oauth_connections_triggers.sql",
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
    # Namespace-keyed external identities (docs/agnostic_oauth). Additive: the HMAC input and
    # the pepper are untouched, so every existing link keeps resolving.
    (
        "user_external_accounts.identity_namespace",
        "ALTER TABLE user_external_accounts ADD COLUMN identity_namespace VARCHAR(191) NOT NULL DEFAULT '' AFTER provider",
    ),
    (
        "user_external_accounts.connection_id",
        "ALTER TABLE user_external_accounts ADD COLUMN connection_id VARCHAR(64) NULL AFTER identity_namespace",
    ),
    (
        "user_external_accounts.active_user_namespace",
        """
        ALTER TABLE user_external_accounts ADD COLUMN active_user_namespace VARCHAR(256)
            GENERATED ALWAYS AS (
                CASE WHEN status = 'linked' THEN CONCAT(user_id, ':', identity_namespace) ELSE NULL END
            ) VIRTUAL
        """,
    ),
)

# Idempotent data backfills, run after PATCH_FILES. Existing rows predate the namespace
# column; their namespace is their provider ('google', 'patreon').
DATA_PATCHES = (
    (
        "user_external_accounts.identity_namespace backfill",
        "SELECT COUNT(*) AS count FROM user_external_accounts WHERE identity_namespace = ''",
        "UPDATE user_external_accounts SET identity_namespace = provider WHERE identity_namespace = ''",
    ),
)

# Index swap for the namespace-keyed identity, run after the backfill. Each entry is
# (label, table, index_name, action, sql); 'add' runs when the index is missing, 'drop'
# when it is still present. No row is ever deleted.
INDEX_PATCHES = (
    (
        "add uk_external_accounts_active_namespace_sub",
        "user_external_accounts",
        "uk_external_accounts_active_namespace_sub",
        "add",
        "ALTER TABLE user_external_accounts ADD UNIQUE KEY uk_external_accounts_active_namespace_sub (identity_namespace, active_provider_sub_hash)",
    ),
    (
        "add uk_external_accounts_user_namespace",
        "user_external_accounts",
        "uk_external_accounts_user_namespace",
        "add",
        "ALTER TABLE user_external_accounts ADD UNIQUE KEY uk_external_accounts_user_namespace (active_user_namespace)",
    ),
    (
        "drop provider-keyed uk_external_accounts_active_sub",
        "user_external_accounts",
        "uk_external_accounts_active_sub",
        "drop",
        "ALTER TABLE user_external_accounts DROP INDEX uk_external_accounts_active_sub",
    ),
    (
        "drop provider-keyed uk_external_accounts_user_provider",
        "user_external_accounts",
        "uk_external_accounts_user_provider",
        "drop",
        "ALTER TABLE user_external_accounts DROP INDEX uk_external_accounts_user_provider",
    ),
)

# Generated columns made obsolete by INDEX_PATCHES; dropped only once their index is gone.
STALE_COLUMNS = (("user_external_accounts", "active_user_provider"),)

CANONICAL_ENUMS = {
    ("user_external_accounts", "provider"): "enum('google','patreon','github','discord','microsoft','oidc')",
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
        # Widened only by APPENDING values; 'google','patreon' keep their positions.
        "ALTER TABLE user_external_accounts MODIFY provider ENUM('google','patreon','github','discord','microsoft','oidc') NOT NULL",
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
        try:
            cursor.execute(statement)
        except Exception:
            # DDL commits implicitly, so everything before this statement is already live
            # and rollback() cannot undo it. Show where the run stopped; re-running --apply
            # converges because every statement is idempotent.
            head = " ".join(statement.split())[:160]
            print(f"  ! failed after {count} statement(s) of this file, at: {head}", file=sys.stderr)
            raise
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


def _index_exists(cursor, table: str, index_name: str) -> bool:
    cursor.execute(
        """
        SELECT COUNT(*) AS count
        FROM information_schema.statistics
        WHERE table_schema = DATABASE()
          AND table_name = %s
          AND index_name = %s
        """,
        (table, index_name),
    )
    return int(cursor.fetchone()["count"]) > 0


def _apply_data_patches(cursor, *, dry_run: bool) -> list[str]:
    changed: list[str] = []
    for label, count_sql, update_sql in DATA_PATCHES:
        table = label.split(".", 1)[0]
        column = label.split(".", 1)[1].split(" ", 1)[0]
        if not _table_exists(cursor, table) or _column_type(cursor, table, column) is None:
            # Only reachable in a dry run: --apply adds the column first. Say what will
            # happen rather than "skip", which hides the one bulk UPDATE of the plan.
            total = 0
            if _table_exists(cursor, table):
                cursor.execute(f"SELECT COUNT(*) AS count FROM {table}")
                total = int(cursor.fetchone()["count"])
            changed.append(f"{label}: runs once the column is added ({total} existing row(s))")
            continue
        cursor.execute(count_sql)
        pending = int(cursor.fetchone()["count"])
        if pending == 0:
            continue
        changed.append(f"{label}: {pending} row(s)")
        if not dry_run:
            cursor.execute(update_sql)
    return changed


def _apply_index_patches(cursor, *, dry_run: bool) -> list[str]:
    changed: list[str] = []
    for label, table, index_name, action, sql in INDEX_PATCHES:
        if not _table_exists(cursor, table):
            continue
        present = _index_exists(cursor, table, index_name)
        if (action == "add" and present) or (action == "drop" and not present):
            continue
        changed.append(label)
        if not dry_run:
            cursor.execute(sql)
    for table, column in STALE_COLUMNS:
        if _table_exists(cursor, table) and _column_type(cursor, table, column) is not None:
            changed.append(f"drop stale generated column {table}.{column}")
            if not dry_run:
                cursor.execute(f"ALTER TABLE {table} DROP COLUMN {column}")
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


def _extract_oauth_activity_upsert() -> str:
    source = (SCHEMAS_DIR / "tables/08_activity_logging_tables.sql").read_text(encoding="utf-8")
    marker = "-- Provider-agnostic OAuth Activities"
    start = source.find(marker)
    if start < 0:
        raise SystemExit("Could not find OAuth activity catalog block")
    insert_start = source.find("INSERT INTO activity_catalog", start)
    update_end = source.find("is_active = VALUES(is_active);", insert_start)
    if insert_start < 0 or update_end < 0:
        raise SystemExit("Could not extract OAuth activity catalog upsert")
    return source[insert_start : update_end + len("is_active = VALUES(is_active);")]


def _apply_oauth_activity_catalog(cursor, *, dry_run: bool) -> str:
    cursor.execute("SELECT COUNT(*) AS count FROM activity_catalog WHERE activity_code LIKE 'oauth\\_%'")
    before = int(cursor.fetchone()["count"])
    if dry_run:
        return f"upsert provider-agnostic OAuth activity catalog rows (currently {before})"
    cursor.execute(_extract_oauth_activity_upsert())
    return "upserted provider-agnostic OAuth activity catalog rows"


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

    # The stale template is DEACTIVATED, never deleted. Removing its catalog row (below)
    # already makes the code unreachable -- rendering and the admin listing both resolve
    # through email_template_catalog -- so a DELETE would add nothing except risk:
    # email_templates is version history, a delete would take operator-authored versions
    # with it, and gating it on "no email_messages row references the code" would make
    # this additive tool destroy rows at whatever later moment that stops being true.
    active_template_rows = 0
    if _table_exists(cursor, "email_templates"):
        cursor.execute(
            "SELECT COUNT(*) AS count FROM email_templates WHERE template_code = %s AND is_active = TRUE",
            (STALE_TEMPLATE_CODE,),
        )
        active_template_rows = int(cursor.fetchone()["count"])
    if active_template_rows:
        # Reported only while something is still active: a converged database plans nothing.
        actions.append(
            f"deactivate stale template {STALE_TEMPLATE_CODE} ({active_template_rows} active version(s); rows are kept)"
        )
        if not dry_run:
            cursor.execute(
                """
                UPDATE email_templates
                   SET is_active = FALSE
                 WHERE template_code = %s
                   AND is_active = TRUE
                """,
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

    failures.extend(_verify_oauth_markers(cursor))
    return failures


def _verify_oauth_markers(cursor) -> list[str]:
    """Outcome checks for the namespace-keyed identity migration.

    The drift report compares object NAMES only, so a half-applied index swap, a skipped
    backfill or an empty provider catalog would otherwise pass verification.
    """
    failures: list[str] = []
    table = "user_external_accounts"

    for _, _, index_name, action, _ in INDEX_PATCHES:
        present = _index_exists(cursor, table, index_name)
        if action == "add" and not present:
            failures.append(f"missing unique key {index_name}")
        if action == "drop" and present:
            failures.append(f"provider-keyed unique key still present: {index_name}")
    for stale_table, column in STALE_COLUMNS:
        if _column_type(cursor, stale_table, column) is not None:
            failures.append(f"stale generated column still present: {stale_table}.{column}")

    if _column_type(cursor, table, "identity_namespace") is None:
        failures.append("missing column user_external_accounts.identity_namespace")
    else:
        cursor.execute("SELECT COUNT(*) AS count FROM user_external_accounts WHERE identity_namespace = ''")
        pending = int(cursor.fetchone()["count"])
        if pending:
            failures.append(f"identity_namespace backfill incomplete: {pending} row(s)")

    if not _table_exists(cursor, "oauth_provider_catalog"):
        failures.append("missing table oauth_provider_catalog")
    else:
        # The external-account triggers refuse any provider without a catalog row.
        cursor.execute(
            """
            SELECT COUNT(*) AS count
            FROM (SELECT DISTINCT provider FROM user_external_accounts) used
            LEFT JOIN oauth_provider_catalog c ON c.provider_type = used.provider
            WHERE c.provider_type IS NULL
            """
        )
        uncovered = int(cursor.fetchone()["count"])
        if uncovered:
            failures.append(f"{uncovered} provider value(s) in use have no oauth_provider_catalog row")
        for provider_type in ("google", "patreon"):
            cursor.execute(
                "SELECT COUNT(*) AS count FROM oauth_provider_catalog WHERE provider_type = %s",
                (provider_type,),
            )
            if int(cursor.fetchone()["count"]) != 1:
                failures.append(f"oauth_provider_catalog is missing the {provider_type} row")

    expected_oauth_codes = len(re.findall(r"\(\s*'act-cat-\d+'", _extract_oauth_activity_upsert()))
    cursor.execute("SELECT COUNT(*) AS count FROM activity_catalog WHERE activity_code LIKE 'oauth\\_%'")
    if int(cursor.fetchone()["count"]) < expected_oauth_codes:
        failures.append("provider-agnostic OAuth activity catalog range is incomplete")

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
                for action in _apply_data_patches(cursor, dry_run=True):
                    print(f"  - {action}")
                for action in _apply_index_patches(cursor, dry_run=True):
                    print(f"  - {action}")
                print(f"  - {_apply_patreon_activity_catalog(cursor, dry_run=True)}")
                print(f"  - {_apply_oauth_activity_catalog(cursor, dry_run=True)}")
                for action in _cleanup_stale_objects(cursor, dry_run=True):
                    print(f"  - {action}")
                print("\nCurrent object drift:")
                _print_drift(_diff_objects(cursor))
                return 0

            if apply:
                print("\nApplying additive schema catch-up...")
                # A DDL statement that cannot get its metadata lock queues, and every later
                # query on that table queues behind it. Fail fast instead of stalling logins;
                # keep this below the connection's read timeout so the server gives up first.
                lock_wait = int(os.getenv("SCHEMA_SYNC_LOCK_WAIT_TIMEOUT", "15"))
                cursor.execute("SET SESSION lock_wait_timeout = %s", (lock_wait,))
                print(f"  - session lock_wait_timeout = {lock_wait}s")
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
                # Backfill before the index swap: the new unique keys are built over the
                # namespace column, so it must be populated first.
                for action in _apply_data_patches(cursor, dry_run=False):
                    print(f"  - {action}")
                for action in _apply_index_patches(cursor, dry_run=False):
                    print(f"  - {action}")
                print(f"  - {_apply_patreon_activity_catalog(cursor, dry_run=False)}")
                print(f"  - {_apply_oauth_activity_catalog(cursor, dry_run=False)}")
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
