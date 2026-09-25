#!/usr/bin/env python3
"""Explicit, loss-checked import of legacy assistant SQLite files into project MySQL.

Stop the API and every assistant worker first. Apply schemas/tables/14_assistant.sql
separately, review --dry-run, then use --apply --maintenance-confirmed. This script
never creates tables, decrypts credentials, merges differing datasets, or removes
source files. Keep ASSISTANT_SECRET_KEY unchanged so imported ciphertext works.

Rows are imported in one InnoDB transaction and verified before commit. A separate,
monotonic AUTO_INCREMENT adjustment preserves deleted event cursor high-watermarks;
MySQL cannot roll that metadata operation back. If it fails, keep the API stopped
and rerun: an exactly matching destination is an idempotent success.

Examples:
  python scripts/migrations/assistant_storage.py --source-only
  python scripts/migrations/assistant_storage.py --env-file .env --dry-run
  python scripts/migrations/assistant_storage.py --env-file .env --apply \\
      --maintenance-confirmed --backup-dir /private/path/assistant-backup

Output contains only row counts, checksums, and status, never data or credentials.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import sqlite3
import sys
import uuid
from dataclasses import dataclass
from decimal import Decimal
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[2]
ACTIVE_STATUSES = frozenset({"queued", "running", "waiting_input", "cancelling"})
SQLITE_FILES = ("assistant.sqlite3", "checkpoints.sqlite3")


class MigrationError(RuntimeError):
    """Operator-safe message without source records, SQL arguments, or secrets."""


@dataclass(frozen=True)
class Table:
    name: str
    source: str
    columns: tuple[str, ...]
    json_columns: tuple[str, ...] = ()
    binary_columns: tuple[str, ...] = ()


TABLES = (
    Table("assistant_settings", "settings", ("owner", "data"), ("data",)),
    Table("assistant_profiles", "profiles", ("owner", "id", "data", "secret"), ("data",)),
    Table("assistant_sessions", "sessions", ("id", "owner", "title", "profile_id", "created_at", "updated_at")),
    Table("assistant_runs", "runs", ("id", "session_id", "owner", "request_id", "status", "data", "worker", "heartbeat", "created_at", "updated_at"), ("data",)),
    Table("assistant_messages", "messages", ("id", "session_id", "run_id", "role", "content", "created_at")),
    Table("assistant_events", "events", ("seq", "session_id", "kind", "data", "created_at"), ("data",)),
    Table("assistant_requests", "requests", ("owner", "request_id", "run_id")),
    Table("assistant_checkpoints", "checkpoints", ("thread_id", "checkpoint_ns_hash", "checkpoint_ns", "checkpoint_id", "parent_checkpoint_id", "checkpoint_type", "checkpoint", "metadata_type", "metadata"), binary_columns=("checkpoint_ns_hash", "checkpoint", "metadata")),
    Table("assistant_checkpoint_writes", "writes", ("thread_id", "checkpoint_ns_hash", "checkpoint_ns", "checkpoint_id", "task_id", "idx", "task_path", "channel", "type", "value"), binary_columns=("checkpoint_ns_hash", "value")),
)
TABLE_BY_NAME = {table.name: table for table in TABLES}


def _reject_json_constant(_: str) -> Any:
    raise ValueError("Non-finite JSON number")


def _canonical_value(table: Table, column: str, value: Any) -> Any:
    if column in table.json_columns:
        try:
            if not isinstance(value, str):
                raise TypeError("JSON text expected")
            json.loads(value, parse_float=Decimal, parse_int=Decimal,
                       parse_constant=_reject_json_constant)
            # The target uses JSON_VALID-checked LONGTEXT, not native JSON.
            # Verify original text exactly, including full numeric precision.
            return {"json_text": value}
        except (ValueError, TypeError) as exc:
            raise MigrationError(f"Invalid JSON in {table.name}.{column}") from exc
    if column in table.binary_columns:
        if not isinstance(value, (bytes, bytearray, memoryview)):
            raise MigrationError(f"Missing or invalid binary data in {table.name}.{column}")
        return {"bytes": bytes(value).hex()}
    if isinstance(value, float) and not math.isfinite(value):
        raise MigrationError(f"Invalid timestamp in {table.name}.{column}")
    return value


def table_digest(table: Table, rows: list[dict[str, Any]]) -> str:
    """Order-independent hash; JSON text, ciphertext and opaque bytes are exact."""
    hashes = []
    for row in rows:
        try:
            values = [_canonical_value(table, col, row[col]) for col in table.columns]
            encoded = json.dumps(values, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        except (KeyError, ValueError, TypeError) as exc:
            raise MigrationError(f"Invalid record in {table.name}") from exc
        hashes.append(hashlib.sha256(encoded).digest())
    digest = hashlib.sha256()
    for value in sorted(hashes):
        digest.update(value)
    return digest.hexdigest()


@dataclass
class Snapshot:
    rows: dict[str, list[dict[str, Any]]]
    event_watermark: int

    def manifest(self) -> dict[str, Any]:
        return {
            "event_watermark": self.event_watermark,
            "tables": {table.name: {"count": len(self.rows[table.name]), "sha256": table_digest(table, self.rows[table.name])} for table in TABLES},
        }

    def ensure_quiescent(self) -> None:
        active = sum(row["status"] in ACTIVE_STATUSES for row in self.rows["assistant_runs"])
        if active:
            raise MigrationError(f"Source has {active} active runs. Complete or cancel them and stop the API/workers before importing.")


def _source_connection(path: Path) -> sqlite3.Connection:
    if not path.is_file():
        raise MigrationError(f"Missing source file: {path.name}")
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=10)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def read_source(directory: Path) -> Snapshot:
    result: dict[str, list[dict[str, Any]]] = {}
    watermark = 0
    for filename in SQLITE_FILES:
        connection = _source_connection(directory / filename)
        try:
            connection.execute("BEGIN")
            if connection.execute("PRAGMA quick_check").fetchone()[0] != "ok":
                raise MigrationError(f"Source integrity check failed: {filename}")
            if connection.execute("PRAGMA foreign_key_check").fetchone():
                raise MigrationError(f"Source has broken foreign keys: {filename}")
            selected = TABLES[:7] if filename == "assistant.sqlite3" else TABLES[7:]
            expected = {table.source for table in selected}
            actual = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            if actual != expected:
                raise MigrationError(f"Unexpected source schema in {filename}; refusing to omit or invent tables")
            for table in selected:
                rows = []
                for record in connection.execute(f'SELECT * FROM "{table.source}"'):
                    row = dict(record)
                    if table.source in {"checkpoints", "writes"}:
                        namespace = row["checkpoint_ns"]
                        row["checkpoint_ns_hash"] = hashlib.sha256(namespace.encode("utf-8")).digest()
                        if table.source == "checkpoints":
                            row["checkpoint_type"] = row.pop("type")
                            row["metadata_type"] = "json"
                            # SqliteSaver metadata is UTF-8 JSON. Some earlier drivers
                            # returned TEXT rather than BLOB; preserve its exact bytes.
                            if isinstance(row["metadata"], str):
                                row["metadata"] = row["metadata"].encode("utf-8")
                        else:
                            row["task_path"] = ""
                    if set(row) != set(table.columns):
                        raise MigrationError(f"Unexpected columns in {filename}:{table.source}")
                    rows.append(row)
                result[table.name] = rows
            if filename == "assistant.sqlite3":
                row = connection.execute("SELECT seq FROM sqlite_sequence WHERE name='events'").fetchone()
                watermark = max(int(row[0]) if row else 0, max((row["seq"] for row in result["assistant_events"]), default=0))
        finally:
            connection.close()
    snapshot = Snapshot(result, watermark)
    snapshot.manifest()  # Validate JSON and blobs before any target mutations.
    snapshot.ensure_quiescent()
    return snapshot


def backup_sources(source: Path, destination: Path, expected: Snapshot) -> None:
    """New 0700 directory and standalone 0600 SQLite backups, including WAL data."""
    destination.mkdir(mode=0o700, parents=False, exist_ok=False)
    for filename in SQLITE_FILES:
        original = _source_connection(source / filename)
        backup_path = destination / filename
        fd = os.open(backup_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        backup = sqlite3.connect(backup_path)
        try:
            original.backup(backup)
        finally:
            backup.close()
            original.close()
    if read_source(destination).manifest() != expected.manifest():
        raise MigrationError("Source changed while backing up. Keep the API stopped and start a fresh import/backup.")
    assert_source_unchanged(source, expected)
    _write_private_json(destination / "manifest.json", expected.manifest())


def assert_source_unchanged(source: Path, expected: Snapshot) -> None:
    if read_source(source).manifest() != expected.manifest():
        raise MigrationError("Source changed during migration. Target transaction was not committed; stop every writer and retry.")


def _load_env_file(path: Path) -> None:
    if not path.is_file():
        raise MigrationError("Environment file does not exist")
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("export "):
            line = line[7:].strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        os.environ.setdefault(key.strip(), value)


def connect_mysql():
    import pymysql
    import pymysql.cursors

    password = os.getenv("DB_MYSQL_PASSWORD") or os.getenv("DB_PASSWORD")
    if not password:
        raise MigrationError("Missing DB_MYSQL_PASSWORD or DB_PASSWORD")
    return pymysql.connect(
        host=os.getenv("DB_HOST", "localhost"), port=int(os.getenv("DB_PORT", "3306")),
        user=os.getenv("DB_USER", "root"), password=password, database=os.getenv("DB_NAME", "magic_auth"),
        charset="utf8mb4", cursorclass=pymysql.cursors.DictCursor, autocommit=False,
        connect_timeout=10, read_timeout=60, write_timeout=60,
    )


def _check_target_schema(cursor) -> None:
    required = [table.name for table in TABLES] + ["assistant_runtime_lock"]
    cursor.execute("SELECT table_name AS name, engine AS engine FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name IN (" + ",".join(["%s"] * len(required)) + ")", tuple(required))
    found = {row["name"]: row["engine"] for row in cursor.fetchall()}
    if set(found) != set(required):
        raise MigrationError("Target assistant tables are missing. Apply schemas/tables/14_assistant.sql explicitly first.")
    if any(engine.upper() != "INNODB" for engine in found.values()):
        raise MigrationError("All assistant target tables must use InnoDB for transactional import")


def _read_target(cursor, *, lock: bool) -> Snapshot:
    rows = {}
    for table in TABLES:
        columns = ",".join(f"`{col}`" for col in table.columns)
        cursor.execute(f"SELECT {columns} FROM `{table.name}`" + (" FOR UPDATE" if lock else ""))
        rows[table.name] = list(cursor.fetchall())
    return Snapshot(rows, 0)


def _next_event_sequence(cursor) -> int:
    cursor.execute("SELECT AUTO_INCREMENT AS next_seq FROM information_schema.tables WHERE table_schema=DATABASE() AND table_name='assistant_events'")
    return int(cursor.fetchone()["next_seq"] or 1)


def compare_target(source: Snapshot, target: Snapshot) -> str:
    expected = source.manifest()["tables"]
    actual = target.manifest()["tables"]
    if expected == actual:
        return "already_imported"
    if any(row["count"] for row in actual.values()):
        raise MigrationError("Target contains conflicting or partial assistant data. No rows were changed; automatic merging is prohibited.")
    return "ready"


def migrate(connection, source: Snapshot, *, apply: bool, before_commit: Callable[[], None] | None = None) -> dict[str, Any]:
    """Import/verify all rows atomically. Never commit partial or mismatched data."""
    source.ensure_quiescent()
    manifest = source.manifest()
    committed = False
    try:
        with connection.cursor() as cursor:
            # MySQL 8 caches information_schema auto-increment metadata otherwise.
            cursor.execute("SET SESSION information_schema_stats_expiry = 0")
            cursor.execute("SET SESSION sql_mode = 'STRICT_ALL_TABLES,NO_ENGINE_SUBSTITUTION,NO_AUTO_VALUE_ON_ZERO'")
            cursor.execute("SET TRANSACTION ISOLATION LEVEL SERIALIZABLE")
            connection.begin()
            _check_target_schema(cursor)
            cursor.execute("SELECT id FROM assistant_runtime_lock WHERE id=1" + (" FOR UPDATE" if apply else ""))
            if not cursor.fetchone():
                raise MigrationError("Target runtime lock seed is missing; reapply the canonical assistant schema")
            target = _read_target(cursor, lock=apply)
            state = compare_target(source, target)
            previous_next = _next_event_sequence(cursor)
            required_next = max(previous_next, source.event_watermark + 1)
            report = {"mode": "apply" if apply else "dry-run", "status": state, "source": manifest, "target": target.manifest()["tables"], "next_event_sequence": required_next}
            if not apply:
                connection.rollback()
                return report
            if state == "ready":
                for table in TABLES:
                    columns = ",".join(f"`{column}`" for column in table.columns)
                    placeholders = ",".join(["%s"] * len(table.columns))
                    query = f"INSERT INTO `{table.name}` ({columns}) VALUES ({placeholders})"
                    rows = source.rows[table.name]
                    for offset in range(0, len(rows), 200):
                        cursor.executemany(query, [tuple(row[column] for column in table.columns) for row in rows[offset:offset + 200]])
            verified = _read_target(cursor, lock=True).manifest()["tables"]
            if verified != manifest["tables"]:
                different = [name for name in verified if verified[name] != manifest["tables"][name]]
                raise MigrationError("Post-import counts/checksums differ in " + ", ".join(different) + ". Target transaction was rolled back.")
            if before_commit:
                before_commit()
            connection.commit()
            committed = True
            # This explicit metadata step is deliberately after the verified row
            # transaction: ALTER TABLE implicitly commits in MySQL. Increasing the
            # counter is safe to retry and never changes any imported record.
            if _next_event_sequence(cursor) < required_next:
                cursor.execute(f"ALTER TABLE assistant_events AUTO_INCREMENT = {int(required_next)}")
            if _next_event_sequence(cursor) < required_next:
                raise MigrationError("Event sequence watermark was not retained")
            connection.commit()
            report["status"] = "imported" if state == "ready" else "already_imported"
            report["target"] = verified
            report["verified"] = True
            return report
    except BaseException as exc:
        connection.rollback()
        if committed:
            raise MigrationError("Rows were verified and committed, but the event-counter finalization failed. Keep the API stopped and rerun --apply; identical data is safe to retry.") from exc
        raise


def _write_private_json(path: Path, value: dict[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(value, handle, ensure_ascii=False, sort_keys=True, indent=2)
        handle.write("\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--source-dir", type=Path, default=ROOT / ".assistant-data")
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Validate source and target without writing either (default)")
    mode.add_argument("--apply", action="store_true")
    mode.add_argument("--source-only", action="store_true", help="Inventory and validate source without connecting to MySQL")
    parser.add_argument("--maintenance-confirmed", action="store_true", help="Confirm the API and all assistant workers are stopped")
    parser.add_argument("--backup-dir", type=Path, help="New private directory; apply always backs up both SQLite databases")
    parser.add_argument("--report", type=Path, help="Write a new private JSON report; existing files are never overwritten")
    args = parser.parse_args(argv)
    if args.apply and not args.maintenance_confirmed:
        parser.error("--apply requires --maintenance-confirmed after stopping the API and all assistant workers")
    connection = None
    try:
        source = read_source(args.source_dir)
        if args.source_only:
            report = {"mode": "source-only", "status": "quiescent", "source": source.manifest()}
        else:
            if args.apply:
                backup_dir = args.backup_dir or args.source_dir / ("mysql-backup-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])
                backup_sources(args.source_dir, backup_dir, source)
            _load_env_file(args.env_file)
            connection = connect_mysql()
            report = migrate(connection, source, apply=args.apply, before_commit=lambda: assert_source_unchanged(args.source_dir, source))
            if args.apply:
                report["backup_directory"] = str(backup_dir.resolve())
        if args.report:
            _write_private_json(args.report, report)
        print(json.dumps(report, sort_keys=True, indent=2))
        return 0
    except MigrationError as exc:
        print(json.dumps({"status": "blocked", "error": str(exc)}), file=sys.stderr)
        return 1
    except Exception as exc:
        # Driver errors can include parameters, ciphertext, or remote credentials.
        print(json.dumps({"status": "blocked", "error": f"Migration failed ({type(exc).__name__}); no record values are logged. Inspect configuration/schema and rerun dry-run."}), file=sys.stderr)
        return 1
    finally:
        if connection is not None:
            connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
