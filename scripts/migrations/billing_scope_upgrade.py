#!/usr/bin/env python3
"""Replace billing ownership procedures/triggers without changing tables or records.

Dry-run is the default. MySQL DDL is not transactional: keep API/worker stopped
through an interrupted migration, then reapply the reviewed definitions. Backups
are evidence, not permission to restore vulnerable processing.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from scripts.migrations.billing_ownership_audit import audit
from scripts.migrations.billing_provider_bootstrap import _connect, _db_config, _load_env_file
from scripts.schema_sync import _split_sql_statements

SQL_FILES = (
    ROOT / "schemas/stored_procedures/17_billing_provider_facts.sql",
    ROOT / "schemas/triggers/07_billing_provider_facts_triggers.sql",
)
LOCK_NAME = "magic_auth.billing_scope_upgrade"


def _identifier(value):
    if not re.fullmatch(r"[A-Za-z0-9_]+", value):
        raise ValueError("Unexpected SQL identifier")
    return f"`{value}`"


def _body(statement):
    match = re.search(r"\bBEGIN\b.*", statement, re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError("Missing SQL object body")
    return " ".join(match.group().split())


def load_plan():
    """Reject unrelated top-level SQL even if a canonical file is edited later."""
    statements, objects = [], {}
    for path in SQL_FILES:
        for statement in _split_sql_statements(path.read_text(encoding="utf-8")):
            if re.fullmatch(r"SELECT '[^']*' AS status,\s*'[^']*' AS details", statement):
                continue  # Canonical files finish with a literal-only status message.
            match = re.match(r"^(CREATE|DROP) (PROCEDURE|TRIGGER) (?:IF EXISTS )?(\w+)\b", statement)
            if match:
                action, kind, name = match.groups()
                prefix = "sp_billing_" if kind == "PROCEDURE" else "trg_billing_"
                if not name.startswith(prefix):
                    raise ValueError("Migration contains an unrelated SQL object")
                if action == "CREATE":
                    objects[(kind, name)] = _body(statement)
            elif statement != "USE magic_auth" and not re.match(
                r"^SET (?:NAMES|character_set_(?:client|connection|results)|collation_connection)\b", statement
            ):
                raise ValueError("Migration contains an unsupported statement")
            statements.append(statement)
    dropped = {(m.group(1), m.group(2)) for sql in statements
               if (m := re.match(r"^DROP (PROCEDURE|TRIGGER) IF EXISTS (\w+)$", sql))}
    if dropped != set(objects):
        raise ValueError("Every dropped billing definition must have a replacement")
    return statements, objects


def inventory(connection):
    definitions, tables = {}, {}
    with connection.cursor() as cursor:
        cursor.execute("""SELECT ROUTINE_NAME AS name FROM information_schema.ROUTINES
            WHERE ROUTINE_SCHEMA=DATABASE() AND ROUTINE_TYPE='PROCEDURE'
              AND LEFT(ROUTINE_NAME,11)='sp_billing_' ORDER BY ROUTINE_NAME""")
        procedures = [row["name"] for row in cursor.fetchall()]
        cursor.execute("""SELECT TRIGGER_NAME AS name FROM information_schema.TRIGGERS
            WHERE TRIGGER_SCHEMA=DATABASE() AND LEFT(TRIGGER_NAME,12)='trg_billing_'
            ORDER BY TRIGGER_NAME""")
        triggers = [row["name"] for row in cursor.fetchall()]
        for kind, names, field in (("PROCEDURE", procedures, "Create Procedure"),
                                   ("TRIGGER", triggers, "SQL Original Statement")):
            for name in names:
                cursor.execute(f"SHOW CREATE {kind} {_identifier(name)}")
                definitions[f"{kind}:{name}"] = cursor.fetchone()
                if not definitions[f"{kind}:{name}"].get(field):
                    raise ValueError("Cannot back up a billing definition")
        cursor.execute("""SELECT TABLE_NAME AS name FROM information_schema.TABLES
            WHERE TABLE_SCHEMA=DATABASE() AND TABLE_TYPE='BASE TABLE'
              AND LEFT(TABLE_NAME,8)='billing_' ORDER BY TABLE_NAME""")
        names = [row["name"] for row in cursor.fetchall()]
        for name in names:
            cursor.execute(f"SHOW CREATE TABLE {_identifier(name)}")
            table_sql = cursor.fetchone()["Create Table"]
            cursor.execute(f"SELECT COUNT(*) AS total FROM {_identifier(name)}")
            count = int(cursor.fetchone()["total"])
            cursor.execute(f"CHECKSUM TABLE {_identifier(name)}")
            checksum = cursor.fetchone()["Checksum"]
            tables[name] = {"count": count, "checksum": checksum,
                           "schema_sha256": hashlib.sha256(table_sql.encode()).hexdigest()}
    connection.rollback()
    return {"definitions": definitions, "tables": tables}


def verify(connection, before, after, objects):
    if before["tables"] != after["tables"]:
        raise ValueError("Billing table definitions or data changed during migration")
    for (kind, name), expected_body in objects.items():
        row = after["definitions"].get(f"{kind}:{name}", {})
        field = "Create Procedure" if kind == "PROCEDURE" else "SQL Original Statement"
        if not row.get(field) or _body(row[field]) != expected_body:
            raise ValueError(f"Billing definition verification failed: {name}")
    replaced = {f"{kind}:{name}" for kind, name in objects}
    for key, definition in before["definitions"].items():
        if key not in replaced and after["definitions"].get(key) != definition:
            raise ValueError("An unrelated billing definition changed")
    with connection.cursor() as cursor:
        cursor.execute("""SELECT COUNT(*) AS total FROM information_schema.PARAMETERS
            WHERE SPECIFIC_SCHEMA=DATABASE() AND SPECIFIC_NAME='sp_billing_resolve_event_scope'
              AND PARAMETER_MODE='IN'""")
        if cursor.fetchone()["total"] != 11:
            raise ValueError("Billing scope resolver must accept eleven parameters")
        # Read-only smoke checks exercise the deployed signature and purchase query.
        cursor.callproc("sp_billing_resolve_event_scope", ["stripe"] + [None] * 10)
        while cursor.nextset():
            pass
        cursor.callproc("sp_billing_get_purchase_status_by_ref",
                        ["migration-no-user", "migration-no-project", "migration-no-purchase", "stripe"])
        if cursor.fetchall():
            raise ValueError("Unexpected purchase smoke-check result")
        while cursor.nextset():
            pass
    connection.rollback()


def _write_json(path, value):
    with path.open("x", encoding="utf-8") as output:
        json.dump(value, output, indent=2, default=str)
        output.write("\n")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file")
    parser.add_argument("--expected-host", required=True)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--processes-stopped", action="store_true", help="Confirm API and worker downtime")
    parser.add_argument("--backup-dir", help="New private directory for definitions and verification reports")
    args = parser.parse_args(argv)
    if args.apply and (not args.processes_stopped or not args.backup_dir):
        parser.error("--apply requires --processes-stopped and --backup-dir")
    os.umask(0o077)
    connection, lock_held, backup_dir, backup_created = None, False, None, False
    try:
        _load_env_file(args.env_file)
        config = _db_config()
        if config["host"] != args.expected_host or config["database"] != "magic_auth":
            raise ValueError("Database target does not match the requested host and magic_auth database")
        statements, objects = load_plan()
        connection = _connect()
        with connection.cursor() as cursor:
            cursor.execute("SET SESSION lock_wait_timeout=15")
            cursor.execute("SET SESSION innodb_lock_wait_timeout=15")
            cursor.execute("SELECT GET_LOCK(%s, 0) AS acquired", (LOCK_NAME,))
            lock_held = cursor.fetchone()["acquired"] == 1
            if not lock_held:
                raise ValueError("Another billing migration holds the database lock")
        before = inventory(connection)
        before_audit = audit(connection)
        report = {"target": {"host": config["host"], "database": config["database"]},
                  "applied": False, "procedures": sum(kind == "PROCEDURE" for kind, _ in objects),
                  "triggers": sum(kind == "TRIGGER" for kind, _ in objects),
                  "row_counts": {name: table["count"] for name, table in before["tables"].items()},
                  "audit_before": before_audit}
        if args.apply:
            backup_dir = Path(args.backup_dir).resolve()
            backup_dir.mkdir(mode=0o700, parents=True, exist_ok=False)
            backup_created = True
            _write_json(backup_dir / "before.json", before)
            _write_json(backup_dir / "audit-before.json", before_audit)
            _write_json(backup_dir / "sources.json", {
                str(path.relative_to(ROOT)): hashlib.sha256(path.read_bytes()).hexdigest() for path in SQL_FILES
            })
            with connection.cursor() as cursor:
                for statement in statements:
                    cursor.execute(statement)
            after = inventory(connection)
            _write_json(backup_dir / "after.json", after)
            verify(connection, before, after, objects)
            report.update(applied=True, tables_and_records_unchanged=True, resolver_parameters=11,
                          backup_directory=str(backup_dir), audit_after=audit(connection))
            _write_json(backup_dir / "report.json", report)
        print(json.dumps(report, indent=2))
        return 0
    except Exception as exc:
        error = {"error_type": type(exc).__name__, "keep_processing_stopped": args.apply}
        if exc.args and isinstance(exc.args[0], int):
            error["database_error_code"] = exc.args[0]
        if backup_created:
            error["backup_directory"] = str(backup_dir)
            try:
                _write_json(backup_dir / "failure.json", error)
            except OSError:
                pass
        # Database exceptions can include sensitive evidence; never print their message.
        print(json.dumps(error), file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            try:
                if lock_held:
                    with connection.cursor() as cursor:
                        cursor.execute("SELECT RELEASE_LOCK(%s)", (LOCK_NAME,))
            finally:
                connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
