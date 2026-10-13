#!/usr/bin/env python3
"""Add group scope metadata and graph locks. Default mode is a read-only inventory.

Pause graph writers while applying DDL; MySQL DDL is not transactional. Reapplying
after interruption is safe. No memberships, grants, or project links are removed.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.migrations.billing_provider_bootstrap import _connect, _db_config, _load_env_file
from scripts.schema_sync import _split_sql_statements

TRIGGERS = ROOT / "schemas/triggers/09_group_scope_triggers.sql"
GROUP_TABLES = ("user_groups", "project_groups")
EDGE_TABLES = ("user_group_members", "project_group_members", "user_group_project_groups")
LOCK_NAME = "magic_auth.group_scope_upgrade"
EXPECTED_TRIGGERS = {
    f"trg_group_scope_{table}_{event.lower()}": (table, event)
    for table, events in (
        *((table, ("INSERT", "UPDATE", "DELETE")) for table in (*GROUP_TABLES, *EDGE_TABLES)),
        ("users", ("UPDATE", "DELETE")), ("projects", ("UPDATE", "DELETE")),
    )
    for event in events
}
BACKFILLS = (
    """UPDATE project_groups g JOIN (
        SELECT project_group_id, MIN(project_id) AS project_id
        FROM project_group_members WHERE is_active = 1
        GROUP BY project_group_id HAVING COUNT(DISTINCT project_id) = 1
    ) bound ON bound.project_group_id = g.id
    SET g.scope_project_id = bound.project_id, g.updated_at = g.updated_at
    WHERE g.scope_project_id IS NULL""",
    """UPDATE user_groups g JOIN (
        SELECT link.user_group_id, MIN(footprint.project_id) AS project_id
        FROM user_group_project_groups link
        JOIN (
            SELECT id AS project_group_id, scope_project_id AS project_id FROM project_groups
            WHERE scope_project_id IS NOT NULL
            UNION
            SELECT project_group_id, project_id FROM project_group_members WHERE is_active = 1
        ) footprint ON footprint.project_group_id = link.project_group_id
        WHERE link.is_active = 1
        GROUP BY link.user_group_id HAVING COUNT(DISTINCT footprint.project_id) = 1
    ) bound ON bound.user_group_id = g.id
    SET g.scope_project_id = bound.project_id, g.updated_at = g.updated_at
    WHERE g.scope_project_id IS NULL""",
)


def _body(sql):
    return " ".join(sql[sql.index("BEGIN"):].split())


def load_plan():
    """Validate the complete replacement set before connecting or executing DDL."""
    statements, definitions, dropped = [], {}, set()
    for sql in _split_sql_statements(TRIGGERS.read_text(encoding="utf-8")):
        if sql == "USE magic_auth":
            continue  # Never switch away from the selected connection database.
        drop = re.fullmatch(r"DROP TRIGGER IF EXISTS (\w+)", sql)
        create = re.match(r"CREATE TRIGGER (\w+) BEFORE (INSERT|UPDATE|DELETE) ON (\w+) FOR EACH ROW\s+BEGIN\b", sql)
        if drop and drop[1] in EXPECTED_TRIGGERS:
            dropped.add(drop[1])
        elif create and EXPECTED_TRIGGERS.get(create[1]) == (create[3], create[2]):
            if create[1] in definitions:
                raise ValueError("Duplicate group lock trigger")
            definitions[create[1]] = {"table": create[3], "event": create[2],
                                       "timing": "BEFORE", "body": _body(sql)}
        else:
            raise ValueError("Unexpected statement in group scope trigger definitions")
        statements.append(sql)
    if dropped != set(EXPECTED_TRIGGERS) or set(definitions) != set(EXPECTED_TRIGGERS):
        raise ValueError("The complete group lock trigger replacement set is required")
    return statements, definitions


def _exists(cursor, query, params):
    cursor.execute(query, params)
    return bool(cursor.fetchone()["total"])


def inventory(connection):
    report = {}
    with connection.cursor() as cursor:
        for table in GROUP_TABLES:
            has_scope = _exists(cursor, """SELECT COUNT(*) AS total FROM information_schema.COLUMNS
                WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND COLUMN_NAME = 'scope_project_id'""", (table,))
            cursor.execute(f"SELECT COUNT(*) AS total FROM {table}")
            report[table] = {"total": cursor.fetchone()["total"], "scope_column": has_scope}
            if has_scope:
                cursor.execute(f"SELECT COUNT(*) AS total FROM {table} WHERE scope_project_id IS NULL")
                report[table]["unbound"] = cursor.fetchone()["total"]
        for table in EDGE_TABLES:
            cursor.execute(f"SELECT COUNT(*) AS total, SUM(is_active = 1) AS active FROM {table}")
            report[table] = dict(cursor.fetchone())
            report[table]["active"] = int(report[table]["active"] or 0)
        cursor.execute("""SELECT COUNT(*) AS total FROM information_schema.TRIGGERS
            WHERE TRIGGER_SCHEMA = DATABASE() AND LEFT(TRIGGER_NAME, 16) = 'trg_group_scope_'""")
        report["lock_triggers"] = cursor.fetchone()["total"]
    connection.rollback()
    return report


def evidence(connection):
    """Recoverable private backups of affected tables and every existing trigger."""
    tables, definitions, triggers = {}, {}, {}
    with connection.cursor() as cursor:
        for table in (*GROUP_TABLES, *EDGE_TABLES, "group_graph_lock"):
            if not _exists(cursor, """SELECT COUNT(*) AS total FROM information_schema.TABLES
                WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s""", (table,)):
                continue
            cursor.execute(f"SHOW CREATE TABLE `{table}`")
            definitions[table] = cursor.fetchone()["Create Table"]
            cursor.execute(f"SELECT * FROM `{table}` ORDER BY id")
            tables[table] = cursor.fetchall()
        cursor.execute("""SELECT TRIGGER_NAME AS name, EVENT_OBJECT_TABLE AS object_table,
            EVENT_MANIPULATION AS event, ACTION_TIMING AS timing, ACTION_STATEMENT AS body
            FROM information_schema.TRIGGERS WHERE TRIGGER_SCHEMA=DATABASE() ORDER BY TRIGGER_NAME""")
        rows = cursor.fetchall()
        for row in rows:
            cursor.execute(f"SHOW CREATE TRIGGER `{row['name'].replace('`', '``')}`")
            triggers[row["name"]] = {"table": row["object_table"], "event": row["event"],
                                     "timing": row["timing"], "body": " ".join(row["body"].split()),
                                     "definition": cursor.fetchone()}
    connection.rollback()
    return {"tables": tables, "table_definitions": definitions, "triggers": triggers}


def verify_preserved_rows(before, after):
    for table in (*GROUP_TABLES, *EDGE_TABLES):
        ignored = {"scope_project_id", "updated_at"} if table in GROUP_TABLES else set()
        comparable = lambda rows: [{k: v for k, v in row.items() if k not in ignored} for row in rows]
        if comparable(before["tables"][table]) != comparable(after["tables"][table]):
            raise ValueError(f"Existing group data or access relationships changed: {table}")
        for old, new in zip(before["tables"][table], after["tables"][table]):
            if old.get("scope_project_id") is not None and old["scope_project_id"] != new["scope_project_id"]:
                raise ValueError("An existing administrative binding changed")
            # Existing BEFORE UPDATE triggers set NOW even for scope-only updates.
            # Permit that timestamp change only when a NULL binding was backfilled.
            if old.get("scope_project_id") == new.get("scope_project_id") and old.get("updated_at") != new.get("updated_at"):
                raise ValueError("Existing group data or access relationships changed: timestamp")
        if table in EDGE_TABLES and before["table_definitions"][table] != after["table_definitions"][table]:
            raise ValueError("An access relationship table definition changed")


def verify(connection, before, after, expected):
    verify_preserved_rows(before, after)
    for name, definition in expected.items():
        actual = after["triggers"].get(name, {})
        if any(actual.get(key) != value for key, value in definition.items()):
            raise ValueError(f"Group lock trigger verification failed: {name}")
    for name, definition in before["triggers"].items():
        if name not in expected and after["triggers"].get(name) != definition:
            raise ValueError("An unrelated trigger changed")
    with connection.cursor() as cursor:
        for table in GROUP_TABLES:
            _validate_scope_schema(cursor, table, required=True)
        cursor.execute("SELECT id FROM group_graph_lock ORDER BY id")
        if cursor.fetchall() != [{"id": 1}]:
            raise ValueError("Group coordination row is invalid")
    connection.rollback()


def _validate_scope_schema(cursor, table, *, required=False):
    cursor.execute("""SELECT DATA_TYPE AS type, CHARACTER_MAXIMUM_LENGTH AS length,
        IS_NULLABLE AS nullable FROM information_schema.COLUMNS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME='scope_project_id'""", (table,))
    column = cursor.fetchone()
    if column is None:
        if required:
            raise ValueError("Group scope column is missing")
        return
    if column != {"type": "varchar", "length": 64, "nullable": "YES"}:
        raise ValueError("Group scope column has an incompatible definition")
    cursor.execute("""SELECT COLUMN_NAME AS col, NON_UNIQUE AS non_unique FROM information_schema.STATISTICS
        WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND INDEX_NAME=%s ORDER BY SEQ_IN_INDEX""",
        (table, f"idx_{table}_scope"))
    index = cursor.fetchall()
    if (index or required) and index != [{"col": "scope_project_id", "non_unique": 1}]:
        raise ValueError("Group scope index has an incompatible definition")
    cursor.execute("""SELECT k.COLUMN_NAME AS col, k.REFERENCED_TABLE_SCHEMA AS db,
        k.REFERENCED_TABLE_NAME AS ref_table, k.REFERENCED_COLUMN_NAME AS ref_col,
        r.DELETE_RULE AS delete_rule, r.UPDATE_RULE AS update_rule
        FROM information_schema.KEY_COLUMN_USAGE k JOIN information_schema.REFERENTIAL_CONSTRAINTS r
        ON r.CONSTRAINT_SCHEMA=k.CONSTRAINT_SCHEMA AND r.CONSTRAINT_NAME=k.CONSTRAINT_NAME
        WHERE k.TABLE_SCHEMA=DATABASE() AND k.TABLE_NAME=%s AND k.CONSTRAINT_NAME=%s""",
        (table, f"fk_{table}_scope"))
    foreign_keys = cursor.fetchall()
    cursor.execute("SELECT DATABASE() AS db")
    database = cursor.fetchone()["db"]
    if foreign_keys or required:
        if len(foreign_keys) != 1 or any(foreign_keys[0].get(key) != value for key, value in
            {"col": "scope_project_id", "db": database, "ref_table": "projects", "ref_col": "id"}.items()) or any(
                foreign_keys[0][key] not in ("RESTRICT", "NO ACTION") for key in ("delete_rule", "update_rule")):
            raise ValueError("Group scope foreign key has an incompatible definition")


def _acquire_lock(connection):
    with connection.cursor() as cursor:
        cursor.execute("SET SESSION lock_wait_timeout=15")
        cursor.execute("SET SESSION innodb_lock_wait_timeout=15")
        cursor.execute("SELECT GET_LOCK(%s, 0) AS acquired", (LOCK_NAME,))
        if cursor.fetchone()["acquired"] != 1:
            raise RuntimeError("Another group scope migration is running")


def _release_lock(connection):
    connection.rollback()
    with connection.cursor() as cursor:
        cursor.execute("SELECT RELEASE_LOCK(%s)", (LOCK_NAME,))


def upgrade(connection, *, backup_dir=None):
    statements, expected = load_plan()
    _acquire_lock(connection)
    try:
        before = evidence(connection)
        if backup_dir is not None:
            _write_json(backup_dir / "before.json", before)
            _write_json(backup_dir / "source.json", {"sha256": hashlib.sha256(TRIGGERS.read_bytes()).hexdigest()})
        with connection.cursor() as cursor:
            for table in GROUP_TABLES:
                _validate_scope_schema(cursor, table)
            cursor.execute("""CREATE TABLE IF NOT EXISTS group_graph_lock (
                id INT NOT NULL PRIMARY KEY,
                CONSTRAINT ck_group_graph_lock_singleton CHECK (id = 1)
            ) ENGINE=InnoDB""")
            cursor.execute("INSERT IGNORE INTO group_graph_lock (id) VALUES (1)")
            connection.commit()
            for table in GROUP_TABLES:
                if not _exists(cursor, """SELECT COUNT(*) AS total FROM information_schema.COLUMNS
                    WHERE TABLE_SCHEMA=DATABASE() AND TABLE_NAME=%s AND COLUMN_NAME='scope_project_id'""", (table,)):
                    cursor.execute(f"ALTER TABLE {table} ADD COLUMN scope_project_id VARCHAR(64) NULL")
                if not _exists(cursor, """SELECT COUNT(*) AS total FROM information_schema.STATISTICS
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND INDEX_NAME = %s""",
                    (table, f"idx_{table}_scope")):
                    cursor.execute(f"ALTER TABLE {table} ADD INDEX idx_{table}_scope (scope_project_id)")
                if not _exists(cursor, """SELECT COUNT(*) AS total FROM information_schema.KEY_COLUMN_USAGE
                    WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s AND CONSTRAINT_NAME = %s""",
                    (table, f"fk_{table}_scope")):
                    cursor.execute(f"ALTER TABLE {table} ADD CONSTRAINT fk_{table}_scope "
                                   "FOREIGN KEY (scope_project_id) REFERENCES projects(id)")
            for statement in statements:
                cursor.execute(statement)
            cursor.execute("SELECT id FROM group_graph_lock WHERE id = 1 FOR UPDATE")
            for statement in BACKFILLS:
                cursor.execute(statement)
            connection.commit()
        after = evidence(connection)
        if backup_dir is not None:
            _write_json(backup_dir / "after.json", after)
        verify(connection, before, after, expected)
        return inventory(connection)
    finally:
        _release_lock(connection)


def _write_json(path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, default=str)
        output.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--apply", action="store_true", help="Apply after pausing graph writers")
    parser.add_argument("--processes-stopped", action="store_true")
    parser.add_argument("--backup-dir", help="New private directory for affected table backups and reports")
    args = parser.parse_args(argv)
    if args.apply and (not args.processes_stopped or not args.backup_dir):
        parser.error("--apply requires --processes-stopped and --backup-dir")
    os.umask(0o077)
    connection, backup_dir = None, None
    try:
        _load_env_file(args.env_file)
        config = _db_config()
        if config["host"] != args.expected_host or config["database"] != "magic_auth":
            raise ValueError("Database target does not match the requested host and magic_auth database")
        load_plan()
        connection = _connect()
        with connection.cursor() as cursor:
            cursor.execute("SELECT DATABASE() AS db, @@hostname AS server, @@version AS version, @@server_uuid AS uuid")
            identity = cursor.fetchone()
        if identity["db"] != config["database"]:
            raise ValueError("Connected database does not match the requested target")
        report = {"target": {"host": config["host"], **identity}, "applied": False,
                  "before": inventory(connection)}
        if args.apply:
            backup_dir = Path(args.backup_dir).resolve()
            backup_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
            _write_json(backup_dir / "target.json", report["target"])
            report.update(applied=True, after=upgrade(connection, backup_dir=backup_dir),
                          access_relationships_preserved=True, backup_directory=str(backup_dir),
                          allowed_group_changes=["scope_project_id", "updated_at on newly bound groups"])
            _write_json(backup_dir / "report.json", report)
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        error = {"error_type": type(exc).__name__, "keep_writers_stopped": args.apply}
        if exc.args and isinstance(exc.args[0], int):
            error["database_error_code"] = exc.args[0]
        if backup_dir is not None:
            error["backup_directory"] = str(backup_dir)
        # Database errors can contain private records or configuration.
        print(json.dumps(error), file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
