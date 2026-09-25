"""Lossless legacy import, conflicting-target rejection and transaction boundaries."""
from __future__ import annotations

import copy
import hashlib
import json
import re
import sqlite3
from pathlib import Path

import pytest

from scripts.migrations.assistant_storage import (
    ACTIVE_STATUSES,
    MigrationError,
    Snapshot,
    TABLES,
    assert_source_unchanged,
    backup_sources,
    main,
    migrate,
    read_source,
    table_digest,
)


@pytest.fixture
def legacy(tmp_path):
    directory = tmp_path / "legacy"
    directory.mkdir()
    with sqlite3.connect(directory / "assistant.sqlite3") as db:
        db.executescript("""
            CREATE TABLE settings(owner TEXT PRIMARY KEY, data TEXT NOT NULL);
            CREATE TABLE profiles(owner TEXT,id TEXT,data TEXT,secret TEXT,PRIMARY KEY(owner,id));
            CREATE TABLE sessions(id TEXT PRIMARY KEY,owner TEXT,title TEXT,profile_id TEXT,created_at REAL,updated_at REAL);
            CREATE TABLE runs(id TEXT PRIMARY KEY,session_id TEXT,owner TEXT,request_id TEXT,status TEXT,data TEXT,worker TEXT,heartbeat REAL,created_at REAL,updated_at REAL);
            CREATE TABLE messages(id TEXT PRIMARY KEY,session_id TEXT,run_id TEXT,role TEXT,content TEXT,created_at REAL);
            CREATE TABLE events(seq INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT,kind TEXT,data TEXT,created_at REAL);
            CREATE TABLE requests(owner TEXT,request_id TEXT,run_id TEXT,PRIMARY KEY(owner,request_id));
        """)
        db.execute("INSERT INTO settings VALUES (?,?)", ("root-a", '{"mutations_enabled":false,"enabled":true}'))
        db.execute("INSERT INTO profiles VALUES (?,?,?,?)", ("root-a", "café", '{"name":"Remote Ollama","enabled":true}', "opaque-encrypted-sentinel"))
        db.execute("INSERT INTO sessions VALUES (?,?,?,?,?,?)", ("session-a", "root-a", "Unicode café", "café", 1.25, 2.5))
        db.execute("INSERT INTO runs VALUES (?,?,?,?,?,?,?,?,?,?)", ("run-a", "session-a", "root-a", "request-a", "completed", '{"usage":{"total_tokens":17}}', "worker-old", 2.25, 1.5, 2.5))
        db.execute("INSERT INTO messages VALUES (?,?,?,?,?,?)", ("msg-a", "session-a", "run-a", "assistant", "# Markdown\n```mermaid\nflowchart TD; A-->B\n```", 2.0))
        db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (7, "session-a", "message.completed", '{"content":"hello"}', 2.0))
        db.execute("INSERT INTO events VALUES (?,?,?,?,?)", (100, "session-a", "message.delta", '{}', 2.5))
        db.execute("DELETE FROM events WHERE seq=100")
        db.execute("INSERT INTO requests VALUES (?,?,?)", ("root-a", "resume-request", "run-a"))
    with sqlite3.connect(directory / "checkpoints.sqlite3") as db:
        db.executescript("""
            CREATE TABLE checkpoints(thread_id TEXT,checkpoint_ns TEXT,checkpoint_id TEXT,parent_checkpoint_id TEXT,type TEXT,checkpoint BLOB,metadata BLOB,PRIMARY KEY(thread_id,checkpoint_ns,checkpoint_id));
            CREATE TABLE writes(thread_id TEXT,checkpoint_ns TEXT,checkpoint_id TEXT,task_id TEXT,idx INTEGER,channel TEXT,type TEXT,value BLOB,PRIMARY KEY(thread_id,checkpoint_ns,checkpoint_id,task_id,idx));
        """)
        namespace = "task:parent|subagent:child/" + "ü" * 300
        db.execute("INSERT INTO checkpoints VALUES (?,?,?,?,?,?,?)", ("session-a:run-a", namespace, "checkpoint-a", "checkpoint-parent", "msgpack", b"\x00\xffopaque-checkpoint", b'{"source":"loop","step":3}'))
        db.execute("INSERT INTO writes VALUES (?,?,?,?,?,?,?,?)", ("session-a:run-a", namespace, "checkpoint-a", "task-a", -1, "__error__", "msgpack", b"\xff\x00opaque-write"))
    return directory


class FakeConnection:
    """DB-API transaction double; no live database or app imports required."""
    def __init__(self, *, initial=None, next_seq=1):
        self.rows = copy.deepcopy(initial or {table.name: [] for table in TABLES})
        self.durable = copy.deepcopy(self.rows)
        self.next_seq = next_seq
        self.queries = []
        self.inserts = 0
        self.commits = 0
        self.rollbacks = 0
        self.corrupt_verify = False
        self.fail_insert_at = None
        self.fail_alter = False
        self.engine = "InnoDB"
        self.missing = False

    def cursor(self):
        return FakeCursor(self)

    def begin(self):
        self.queries.append("BEGIN")

    def commit(self):
        self.commits += 1
        self.queries.append("COMMIT")
        self.durable = copy.deepcopy(self.rows)

    def rollback(self):
        self.rollbacks += 1
        self.queries.append("ROLLBACK")
        self.rows = copy.deepcopy(self.durable)


class FakeCursor:
    def __init__(self, connection):
        self.db = connection
        self.result = []

    def __enter__(self):
        return self

    def __exit__(self, *_):
        pass

    def fetchall(self):
        return copy.deepcopy(self.result)

    def fetchone(self):
        return copy.deepcopy(self.result[0]) if self.result else None

    def execute(self, query, params=()):
        self.db.queries.append(query)
        self.result = []
        if query.startswith("SET "):
            return
        if query.startswith("SELECT table_name"):
            self.result = [{"name": name, "engine": self.db.engine} for name in params if not (self.db.missing and name == "assistant_checkpoints")]
        elif query.startswith("SELECT id FROM assistant_runtime_lock"):
            self.result = [{"id": 1}]
        elif query.startswith("SELECT AUTO_INCREMENT"):
            self.result = [{"next_seq": self.db.next_seq}]
        elif query.startswith("SELECT "):
            name = re.search(r"FROM `([^`]+)`", query)[1]
            self.result = copy.deepcopy(self.db.rows[name])
            if self.db.corrupt_verify and self.db.inserts and name == "assistant_profiles":
                self.result[0]["secret"] = "altered-ciphertext"
        elif query.startswith("ALTER TABLE assistant_events AUTO_INCREMENT = "):
            assert self.db.commits, "Metadata DDL must not implicitly commit the row transaction"
            if self.db.fail_alter:
                raise OSError("synthetic metadata failure")
            self.db.next_seq = int(query.rsplit(" ", 1)[1])
        else:
            raise AssertionError(query)

    def executemany(self, query, values):
        name = re.search(r"INSERT INTO `([^`]+)`", query)[1]
        columns = re.findall(r"`([^`]+)`", query)[1:]
        for value in values:
            self.db.inserts += 1
            if self.db.fail_insert_at == self.db.inserts:
                raise OSError("synthetic write failure")
            row = dict(zip(columns, value))
            # JSON_VALID-checked LONGTEXT preserves the exact source payload.
            self.db.rows[name].append(row)
            if name == "assistant_events":
                self.db.next_seq = max(self.db.next_seq, row["seq"] + 1)


def test_source_preserves_identifiers_ciphertext_history_and_opaque_checkpoints(legacy):
    before = {p.name: p.read_bytes() for p in legacy.iterdir()}
    snapshot = read_source(legacy)
    assert snapshot.event_watermark == 100
    assert snapshot.rows["assistant_events"][0]["seq"] == 7
    assert snapshot.rows["assistant_profiles"][0]["secret"] == "opaque-encrypted-sentinel"
    assert snapshot.rows["assistant_profiles"][0]["id"] == "café"
    checkpoint = snapshot.rows["assistant_checkpoints"][0]
    assert checkpoint["checkpoint"] == b"\x00\xffopaque-checkpoint"
    assert checkpoint["metadata"] == b'{"source":"loop","step":3}'
    assert checkpoint["metadata_type"] == "json"
    assert checkpoint["checkpoint_ns_hash"] == hashlib.sha256(checkpoint["checkpoint_ns"].encode()).digest()
    pending = snapshot.rows["assistant_checkpoint_writes"][0]
    assert pending["task_path"] == "" and pending["idx"] == -1
    assert pending["value"] == b"\xff\x00opaque-write"
    assert {p.name: p.read_bytes() for p in legacy.iterdir()} == before
    assert "opaque-encrypted-sentinel" not in json.dumps(snapshot.manifest())


@pytest.mark.parametrize("status", sorted(ACTIVE_STATUSES))
def test_active_runs_block_even_a_source_preflight(legacy, status):
    with sqlite3.connect(legacy / "assistant.sqlite3") as db:
        db.execute("UPDATE runs SET status=?", (status,))
    with pytest.raises(MigrationError, match="active runs"):
        read_source(legacy)


def test_missing_source_does_not_create_new_databases(tmp_path):
    with pytest.raises(MigrationError, match="Missing source"):
        read_source(tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_unknown_source_tables_are_not_silently_lost(legacy):
    with sqlite3.connect(legacy / "assistant.sqlite3") as db:
        db.execute("CREATE TABLE future_history(id TEXT)")
    with pytest.raises(MigrationError, match="Unexpected source schema"):
        read_source(legacy)


def test_backups_private_exact_and_never_overwrite(legacy, tmp_path):
    source = read_source(legacy)
    destination = tmp_path / "backup"
    backup_sources(legacy, destination, source)
    assert read_source(destination).manifest() == source.manifest()
    assert destination.stat().st_mode & 0o777 == 0o700
    assert all(path.stat().st_mode & 0o777 == 0o600 for path in destination.iterdir())
    with pytest.raises(FileExistsError):
        backup_sources(legacy, destination, source)
    assert read_source(legacy).manifest() == source.manifest()


def test_changes_during_backup_or_precommit_are_detected(legacy, tmp_path):
    snapshot = read_source(legacy)
    with sqlite3.connect(legacy / "assistant.sqlite3") as db:
        db.execute("UPDATE messages SET content='new concurrent content'")
    with pytest.raises(MigrationError, match="Source changed"):
        assert_source_unchanged(legacy, snapshot)
    with pytest.raises(MigrationError, match="Source changed"):
        backup_sources(legacy, tmp_path / "backup", snapshot)


def test_dry_run_is_read_only_and_reports_deleted_event_high_watermark(legacy):
    source = read_source(legacy)
    db = FakeConnection()
    report = migrate(db, source, apply=False)
    assert report["status"] == "ready"
    assert report["next_event_sequence"] == 101
    assert db.inserts == db.commits == 0 and db.rollbacks == 1
    assert not any(query.startswith("ALTER") for query in db.queries)


def test_apply_verifies_every_row_and_preserves_sequence_with_idempotent_retry(legacy):
    source = read_source(legacy)
    db = FakeConnection()
    callbacks = []
    report = migrate(db, source, apply=True, before_commit=lambda: callbacks.append("verified"))
    assert report["status"] == "imported" and report["verified"]
    assert report["target"] == source.manifest()["tables"]
    assert callbacks == ["verified"]
    assert db.next_seq == 101
    assert db.rows["assistant_profiles"][0]["secret"] == "opaque-encrypted-sentinel"
    assert "SELECT id FROM assistant_runtime_lock WHERE id=1 FOR UPDATE" in db.queries
    first_commit = db.queries.index("COMMIT")
    alter = next(i for i, query in enumerate(db.queries) if query.startswith("ALTER"))
    assert first_commit < alter
    inserts = db.inserts
    repeat = migrate(db, source, apply=True)
    assert repeat["status"] == "already_imported" and db.inserts == inserts
    assert db.next_seq == 101


def test_existing_higher_event_sequence_never_decreases(legacy):
    source = read_source(legacy)
    db = FakeConnection(next_seq=500)
    migrate(db, source, apply=True)
    assert db.next_seq == 500
    assert not any(query.startswith("ALTER") for query in db.queries)


def test_conflicting_or_partial_destination_is_not_merged(legacy):
    source = read_source(legacy)
    rows = {table.name: [] for table in TABLES}
    rows["assistant_profiles"] = source.rows["assistant_profiles"]
    db = FakeConnection(initial=rows)
    with pytest.raises(MigrationError, match="conflicting or partial"):
        migrate(db, source, apply=True)
    assert db.inserts == db.commits == 0
    assert db.rows == rows


def test_checksum_mismatch_rolls_back_every_insert(legacy):
    db = FakeConnection()
    db.corrupt_verify = True
    with pytest.raises(MigrationError, match="checksums differ"):
        migrate(db, read_source(legacy), apply=True)
    assert db.commits == 0 and db.rollbacks == 1
    assert not any(db.rows.values())


def test_mid_import_failure_and_source_race_roll_back(legacy):
    source = read_source(legacy)
    db = FakeConnection()
    db.fail_insert_at = 4
    with pytest.raises(OSError):
        migrate(db, source, apply=True)
    assert db.commits == 0 and not any(db.rows.values())
    db.fail_insert_at = None
    def changed():
        raise MigrationError("Source changed")
    with pytest.raises(MigrationError, match="Source changed"):
        migrate(db, source, apply=True, before_commit=changed)
    assert db.commits == 0 and not any(db.rows.values())


def test_metadata_failure_retains_verified_rows_and_can_retry(legacy):
    source = read_source(legacy)
    db = FakeConnection()
    db.fail_alter = True
    with pytest.raises(MigrationError, match="Rows were verified and committed"):
        migrate(db, source, apply=True)
    assert Snapshot(db.rows, source.event_watermark).manifest() == source.manifest()
    db.fail_alter = False
    assert migrate(db, source, apply=True)["status"] == "already_imported"
    assert db.next_seq == 101


@pytest.mark.parametrize("problem", ["missing", "engine"])
def test_schema_must_exist_and_be_transactional(legacy, problem):
    db = FakeConnection()
    if problem == "missing":
        db.missing = True
    else:
        db.engine = "MyISAM"
    with pytest.raises(MigrationError):
        migrate(db, read_source(legacy), apply=True)
    assert db.inserts == db.commits == 0


def test_apply_requires_maintenance_acknowledgement_before_any_io():
    with pytest.raises(SystemExit) as exc:
        main(["--apply", "--source-dir", "/missing/source"])
    assert exc.value.code == 2


def test_source_only_report_excludes_secrets_and_does_not_connect(legacy, capsys, monkeypatch):
    monkeypatch.setattr("scripts.migrations.assistant_storage.connect_mysql", lambda: pytest.fail("unexpected MySQL connection"))
    assert main(["--source-only", "--source-dir", str(legacy)]) == 0
    output = capsys.readouterr().out
    assert "opaque-encrypted-sentinel" not in output
    assert "opaque-checkpoint" not in output
    assert json.loads(output)["source"]["event_watermark"] == 100


def test_assistant_schema_registered_and_all_tables_innodb():
    root = Path(__file__).resolve().parents[2]
    sql = (root / "schemas/tables/14_assistant.sql").read_text()
    for table in TABLES:
        assert f"CREATE TABLE IF NOT EXISTS {table.name} (" in sql
    assert sql.count("ENGINE=InnoDB") == len(TABLES) + 1
    assert '"tables/14_assistant.sql"' in (root / "scripts/schema_sync.py").read_text()
    for script in ("create_database.py", "recreate_database.py"):
        assert "'tables/14_assistant.sql'" in (root / "scripts" / script).read_text()
    assert "DROP TABLE" not in sql and "TRUNCATE" not in sql


def test_json_hash_detects_even_equivalent_number_reformatting():
    table = TABLES[0]
    source = [{"owner": "root", "data": '{"temperature":0.0,"max_tokens":4e3,"scale":0.0001,"negative_zero":-0.0}'}]
    target = [{"owner": "root", "data": '{"scale":1e-4,"max_tokens":4000.0,"temperature":0,"negative_zero":0}'}]
    assert table_digest(table, source) != table_digest(table, target)


@pytest.mark.parametrize("left,right", [
    ('9007199254740993', '9007199254740992'),
    ('0.123456789012345678901234567890123456789', '0.123456789012345678901234567890123456788'),
    ('1', 'true'), ('1', '"1"'), ('1', '{"$number":"1"}'), ('1', '["number",0,"1",0]'),
])
def test_json_hash_retains_numeric_precision_and_value_types(left, right):
    table = TABLES[0]
    assert table_digest(table, [{"owner": "root", "data": left}]) != table_digest(table, [{"owner": "root", "data": right}])


def test_schema_keeps_json_payloads_as_exact_text_with_validation():
    root = Path(__file__).resolve().parents[2]
    sql = (root / "schemas/tables/14_assistant.sql").read_text()
    assert sql.count("data LONGTEXT NOT NULL") == 4
    assert sql.count("CHECK (JSON_VALID(data))") == 4
    assert "data JSON NOT NULL" not in sql


def test_changed_nested_float_is_never_accepted_as_equivalent():
    table = next(table for table in TABLES if table.name == "assistant_events")
    row = {"seq": 1, "session_id": "session", "kind": "tool.completed", "created_at": 1.0}
    source = [{**row, "data": '{"args":{"score":1.2345678901234567}}'}]
    rounded = [{**row, "data": '{"args":{"score":1.234567890123456}}'}]
    assert table_digest(table, source) != table_digest(table, rounded)
