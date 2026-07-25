"""Wait for the disposable E2E services and verify canonical schema families."""

from __future__ import annotations

import os
import sys
import time
from collections.abc import Iterable
from urllib.request import urlopen

import pymysql
import redis


EXPECTED_TABLES = {
    "users",
    "user_project_api_keys",
    "user_emails",
    "user_external_accounts",
    "patreon_entitlements_current",
    "billing_groups",
    "billing_catalog_items",
}
EXPECTED_VIEWS = {
    "v_user_project_access",
    "v_user_billing_group_access",
}
EXPECTED_PROCEDURES = {
    "sp_create_api_key",
    "sp_claim_email_messages",
    "sp_link_external_account",
    "sp_patreon_admin_list_entitlements",
    "sp_billing_checkout_intent_begin",
    "sp_billing_group_create",
}
EXPECTED_TRIGGERS = {
    "trg_email_messages_before_insert",
    "trg_external_accounts_before_insert",
    "trg_patreon_current_before_insert",
    "trg_billing_groups_before_insert",
}


def _env_int(name: str, default: str) -> int:
    return int(os.environ.get(name, default))


def _redis_password() -> str | None:
    value = os.environ.get("DB_REDIS_PASSWORD")
    return value or None


def _missing_schema_names(
    cur,
    *,
    schema: str,
    information_schema_table: str,
    schema_column: str,
    name_column: str,
    expected: Iterable[str],
) -> set[str]:
    expected_names = set(expected)
    placeholders = ", ".join(["%s"] * len(expected_names))
    cur.execute(
        (
            f"SELECT {name_column} "
            f"FROM information_schema.{information_schema_table} "
            f"WHERE {schema_column} = %s "
            f"AND {name_column} IN ({placeholders})"
        ),
        (schema, *sorted(expected_names)),
    )
    present = {str(row[0]) for row in cur.fetchall()}
    return expected_names - present


def _check_mysql() -> None:
    schema = os.environ.get("REAL_DB_NAME") or os.environ.get("DB_NAME", "magic_auth")
    conn = pymysql.connect(
        host=os.environ.get("REAL_DB_HOST") or os.environ.get("DB_HOST", "mysql-test"),
        port=_env_int("REAL_DB_PORT", os.environ.get("DB_PORT", "3306")),
        user=os.environ.get("REAL_DB_USER") or os.environ.get("DB_USER", "test_user"),
        password=os.environ.get("REAL_DB_PASSWORD")
        or os.environ.get("DB_MYSQL_PASSWORD", "test_mysql_password"),
        database=schema,
        connect_timeout=5,
        read_timeout=10,
        write_timeout=10,
    )
    try:
        with conn.cursor() as cur:
            checks = (
                (
                    "tables",
                    _missing_schema_names(
                        cur,
                        schema=schema,
                        information_schema_table="tables",
                        schema_column="table_schema",
                        name_column="table_name",
                        expected=EXPECTED_TABLES,
                    ),
                ),
                (
                    "views",
                    _missing_schema_names(
                        cur,
                        schema=schema,
                        information_schema_table="views",
                        schema_column="table_schema",
                        name_column="table_name",
                        expected=EXPECTED_VIEWS,
                    ),
                ),
                (
                    "procedures",
                    _missing_schema_names(
                        cur,
                        schema=schema,
                        information_schema_table="routines",
                        schema_column="routine_schema",
                        name_column="routine_name",
                        expected=EXPECTED_PROCEDURES,
                    ),
                ),
                (
                    "triggers",
                    _missing_schema_names(
                        cur,
                        schema=schema,
                        information_schema_table="triggers",
                        schema_column="trigger_schema",
                        name_column="trigger_name",
                        expected=EXPECTED_TRIGGERS,
                    ),
                ),
            )
    finally:
        conn.close()

    missing = {
        family: sorted(names)
        for family, names in checks
        if names
    }
    if missing:
        raise RuntimeError(f"fresh MySQL schema is incomplete: {missing}")


def _check_redis() -> None:
    client = redis.StrictRedis(
        host=os.environ.get("REAL_REDIS_HOST") or os.environ.get("REDIS_HOST", "redis-test"),
        port=_env_int("REAL_REDIS_PORT", os.environ.get("REDIS_PORT", "6379")),
        db=_env_int("REDIS_DB", "0"),
        password=_redis_password(),
        socket_connect_timeout=5,
        socket_timeout=5,
    )
    if not client.ping():
        raise RuntimeError("Redis ping returned a false value")


def _check_mailpit() -> None:
    api_base = os.environ.get("MAILPIT_API_BASE_URL", "http://mailpit-test:8025").rstrip("/")
    with urlopen(f"{api_base}/api/v1/messages", timeout=5) as response:  # noqa: S310
        if response.status != 200:
            raise RuntimeError(f"Mailpit readiness returned HTTP {response.status}")


def main() -> int:
    deadline = time.monotonic() + _env_int("E2E_SERVICE_WAIT_SECONDS", "120")
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            _check_mysql()
            _check_redis()
            _check_mailpit()
            return 0
        except Exception as exc:
            last_error = exc
            time.sleep(1)

    raise SystemExit(
        f"Timed out waiting for fresh E2E MySQL/Redis/Mailpit readiness: {last_error!r}"
    )


if __name__ == "__main__":
    sys.exit(main())
