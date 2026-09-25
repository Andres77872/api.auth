"""MySQL transaction/SQL boundary tests; no local database or live DDL."""
from __future__ import annotations

from collections import deque
import json
from unittest.mock import Mock

import pytest
from cryptography.fernet import Fernet

from src.assistant.models import AssistantError
from src.assistant.mysql_store import AssistantStore


class Step:
    def __init__(self, sql, rows=(), *, params=None, rowcount=1, lastrowid=0, error=None):
        self.sql, self.rows, self.params = sql, rows, params
        self.rowcount, self.lastrowid, self.error = rowcount, lastrowid, error


class Cursor:
    def __init__(self, db):
        self.db, self.rows = db, []
        self.rowcount = self.lastrowid = 0

    def execute(self, sql, params=None):
        self.db.trace.append((sql, params))
        assert self.db.steps, f"Unexpected query: {sql}"
        step = self.db.steps.popleft()
        assert step.sql in sql, (step.sql, sql)
        assert "?" not in sql and "PRAGMA" not in sql and "ON CONFLICT" not in sql
        if step.params is not None:
            assert params == step.params
        if step.error:
            raise step.error
        self.rows = list(step.rows(self.db) if callable(step.rows) else step.rows)
        self.rowcount, self.lastrowid = step.rowcount, step.lastrowid
        return self.rowcount

    def fetchone(self):
        return self.rows.pop(0) if self.rows else None

    def fetchall(self):
        rows, self.rows = self.rows, []
        return rows

    def close(self):
        self.db.trace.append(("cursor.close", None))


class Database:
    def __init__(self, *steps):
        self.steps, self.trace = deque(steps), []
        self.begin = Mock(side_effect=lambda: self.trace.append(("begin", None)))
        self.commit = Mock(side_effect=lambda: self.trace.append(("commit", None)))
        self.rollback = Mock(side_effect=lambda: self.trace.append(("rollback", None)))
        self.close = Mock(side_effect=lambda: self.trace.append(("close", None)))

    def cursor(self, cursor_type):
        from pymysql.cursors import DictCursor
        assert cursor_type is DictCursor
        return Cursor(self)

    def store(self):
        return AssistantStore(connection_factory=lambda: self)

    def assert_consumed(self):
        assert not self.steps


SESSION = {"id": "session-1", "owner": "root-a", "title": "Test", "profile_id": "ollama-default", "created_at": 1.0, "updated_at": 2.0}
RUN = {"id": "run-1", "session_id": "session-1", "owner": "root-a", "request_id": "req-1", "status": "queued", "data": json.dumps({"message": "hello", "profile_id": "ollama-default"}), "worker": None, "heartbeat": None, "created_at": 1.0, "updated_at": 2.0}


def lock_step():
    return Step("SELECT id FROM assistant_runtime_lock WHERE id=1 FOR UPDATE", [{"id": 1}])


def session_step(*, lock=False, rows=None):
    return Step("SELECT * FROM assistant_sessions WHERE owner=%s AND id=%s" + (" FOR UPDATE" if lock else ""), [SESSION] if rows is None else rows, params=("root-a", "session-1"))


def test_constructor_is_lazy_and_has_no_local_path_fallback(tmp_path):
    factory = Mock(side_effect=AssertionError("Construction must not open a database"))
    store = AssistantStore(connection_factory=factory)
    factory.assert_not_called()
    assert not hasattr(store, "path") and not hasattr(store, "checkpoint_path")
    with pytest.raises(TypeError):
        AssistantStore(tmp_path)
    assert not list(tmp_path.iterdir())


def test_default_factory_uses_existing_project_database(monkeypatch):
    from src.Util import db_config
    db = Database(Step("SELECT data FROM assistant_settings WHERE owner=%s", [], params=("root-a",)))
    get_connection = Mock(return_value=db)
    monkeypatch.setattr(db_config, "get_connection", get_connection)
    assert AssistantStore().get_settings("root-a", {"enabled": False}) == {"enabled": False}
    get_connection.assert_called_once_with()
    db.commit.assert_called_once()


def test_native_settings_upsert_is_parameterized():
    data = {"enabled": True, "note": "quote ' ; DROP TABLE users"}
    db = Database(Step("ON DUPLICATE KEY UPDATE data=VALUES(data)"))
    assert db.store().save_settings("root-a", data) == data
    sql, params = db.trace[1]
    assert params[0] == "root-a" and json.loads(params[1]) == data
    assert data["note"] not in sql
    db.commit.assert_called_once()
    db.rollback.assert_not_called()
    db.close.assert_called_once()


def test_event_locks_session_before_sequence_allocation_and_holds_through_commit():
    db = Database(
        Step("SELECT * FROM assistant_sessions WHERE id=%s FOR UPDATE", [SESSION], params=("session-1",)),
        Step("INSERT INTO assistant_events", lastrowid=81),
        Step("UPDATE assistant_sessions SET updated_at=%s WHERE id=%s"),
    )
    event = db.store().event("session-1", "message.delta", {"content": "hello"})
    assert event["seq"] == 81 and event["data"] == {"content": "hello"}
    sql = [entry[0] for entry in db.trace]
    assert sql[0] == "begin"
    assert "FOR UPDATE" in sql[1] and "INSERT INTO assistant_events" in sql[2]
    assert sql[4] == "commit"
    db.assert_consumed()


def test_event_failure_rolls_back_without_claiming_a_committed_cursor():
    db = Database(
        Step("SELECT * FROM assistant_sessions WHERE id=%s FOR UPDATE", [SESSION]),
        Step("INSERT INTO assistant_events", error=RuntimeError("Database unavailable")),
    )
    with pytest.raises(RuntimeError):
        db.store().event("session-1", "message.delta", {"content": "x"})
    db.commit.assert_not_called()
    db.rollback.assert_called_once()
    db.close.assert_called_once()


def test_snapshot_reads_messages_cursor_run_and_partial_from_one_rr_snapshot():
    run = {**RUN, "status": "running"}
    db = Database(
        Step("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ"),
        Step("START TRANSACTION WITH CONSISTENT SNAPSHOT"),
        session_step(),
        Step("SELECT * FROM assistant_messages", []),
        Step("SELECT COALESCE(MAX(seq),0) AS last_seq", [{"last_seq": 17}]),
        Step("SELECT * FROM assistant_runs WHERE session_id", [run]),
        Step("SELECT * FROM assistant_events WHERE session_id", [{"seq": 15, "session_id": "session-1", "kind": "run.status", "data": '{"status":"running"}', "created_at": 2.0}]),
        Step("JSON_UNQUOTE(JSON_EXTRACT(data,'$.run_id'))=%s", [{"data": '{"content":"hel"}'}, {"data": '{"content":"lo"}'}], params=("session-1", 17, "run-1")),
    )
    result = db.store().snapshot("root-a", "session-1")
    assert result["partial_content"] == "hello" and result["last_seq"] == 17
    assert result["events"][0]["seq"] == 15
    db.begin.assert_not_called()
    db.commit.assert_called_once()
    db.assert_consumed()


@pytest.mark.parametrize("method", ["session", "events", "messages", "message_page", "history", "latest_run"])
def test_owner_mismatch_stops_before_reading_conversation_data(method):
    db = Database(Step("SELECT * FROM assistant_sessions WHERE owner=%s AND id=%s", [], params=("other-root", "session-1")))
    with pytest.raises(AssistantError, match="not found"):
        getattr(db.store(), method)("other-root", "session-1")
    db.assert_consumed()
    db.commit.assert_not_called()


def test_idempotent_create_locks_global_then_session_and_does_not_insert_twice():
    db = Database(lock_step(), session_step(lock=True), Step("SELECT * FROM assistant_runs WHERE owner=%s AND request_id=%s FOR UPDATE", [RUN]))
    run, created = db.store().create_run("root-a", "session-1", "req-1", {"message": "hello", "profile_id": "ollama-default"})
    assert not created and run["id"] == "run-1"
    assert not any("INSERT" in sql for sql, _ in db.trace)
    db.assert_consumed()


def test_idempotency_rejects_different_profile_as_well_as_different_message():
    db = Database(lock_step(), session_step(lock=True), Step("SELECT * FROM assistant_runs WHERE owner=%s AND request_id=%s FOR UPDATE", [RUN]))
    with pytest.raises(AssistantError, match="different message"):
        db.store().create_run("root-a", "session-1", "req-1", {"message": "hello", "profile_id": "different-provider"})
    db.rollback.assert_called_once()


def test_create_capacity_check_occurs_under_global_and_session_locks():
    db = Database(lock_step(), session_step(lock=True), Step("SELECT * FROM assistant_runs WHERE owner=%s AND request_id", []), Step("status IN ('queued','running','waiting_input','cancelling')", []), Step("SELECT COUNT(*) AS total", [{"total": 8}]))
    with pytest.raises(AssistantError, match="capacity"):
        db.store().create_run("root-a", "session-1", "new", {"message": "hello", "profile_id": "ollama-default"})
    assert not any("INSERT" in sql for sql, _ in db.trace)
    db.rollback.assert_called_once()


def test_missing_runtime_lock_fails_closed_instead_of_unbounded_admission():
    db = Database(Step("SELECT id FROM assistant_runtime_lock", []))
    with pytest.raises(AssistantError, match="schema migration"):
        db.store().create_run("root-a", "session-1", "req", {})
    db.rollback.assert_called_once()


def test_claim_is_atomic_conditional_update():
    db = Database(Step("AND status='queued'", rowcount=1))
    assert db.store().claim("root-a", "run-1", "worker-1")
    assert db.trace[1][1][-2:] == ("root-a", "run-1")
    db = Database(Step("AND status='queued'", rowcount=0))
    assert not db.store().claim("root-a", "run-1", "worker-2")


def test_resume_checks_capacity_and_inserts_event_under_session_lock():
    db = Database(
        lock_step(), session_step(lock=True),
        Step("SELECT run_id FROM assistant_requests", []),
        Step("SELECT * FROM assistant_runs WHERE id=%s AND owner=%s FOR UPDATE", [{**RUN, "status": "waiting_input"}]),
        Step("id<>%s AND status IN", []), Step("SELECT COUNT(*) AS total", [{"total": 7}]),
        Step("UPDATE assistant_runs SET status='queued'"), Step("INSERT INTO assistant_requests"),
        Step("INSERT INTO assistant_events", lastrowid=9), Step("UPDATE assistant_sessions"),
        Step("INSERT INTO assistant_messages"), Step("UPDATE assistant_sessions"),
    )
    result, created = db.store().resume("root-a", "session-1", "run-1", "resume-1", {"question": "Only active accounts"})
    assert created and result["status"] == "queued" and result["worker"] is None
    assert result["interrupts"] == []
    statements = [sql for sql, _ in db.trace]
    assert "assistant_runtime_lock" in statements[1] and "assistant_sessions" in statements[2]
    assert statements.index("commit") > next(i for i, sql in enumerate(statements) if "INSERT INTO assistant_events" in sql)
    db.assert_consumed()


def test_delete_clears_checkpoint_namespaces_and_transcripts_in_same_transaction():
    db = Database(
        lock_step(), session_step(lock=True), Step("SELECT id FROM assistant_runs", []),
        Step("DELETE FROM assistant_checkpoint_writes", params=("session-1", "session-1:%")),
        Step("DELETE FROM assistant_checkpoints", params=("session-1", "session-1:%")),
        Step("DELETE q FROM assistant_requests"),
        Step("DELETE FROM assistant_sessions WHERE owner=%s AND id=%s", params=("root-a", "session-1")),
    )
    db.store().delete_session("root-a", "session-1")
    db.commit.assert_called_once()
    db.assert_consumed()


def test_checkpoint_cleanup_failure_rolls_back_conversation_deletion():
    db = Database(lock_step(), session_step(lock=True), Step("SELECT id FROM assistant_runs", []), Step("DELETE FROM assistant_checkpoint_writes", error=RuntimeError("unavailable")))
    with pytest.raises(RuntimeError):
        db.store().delete_session("root-a", "session-1")
    db.rollback.assert_called_once()
    assert not any("DELETE FROM assistant_sessions" in sql for sql, _ in db.trace)


def test_profile_secret_is_encrypted_before_binding_and_omission_is_atomic(monkeypatch):
    monkeypatch.setenv("ASSISTANT_SECRET_KEY", Fernet.generate_key().decode())
    def saved_row(db):
        insert = next(params for sql, params in db.trace if sql.startswith("INSERT INTO assistant_profiles"))
        return [{"data": insert[2], "secret": insert[3]}]
    db = Database(Step("ON DUPLICATE KEY UPDATE data=VALUES(data),secret=IF(%s,secret,VALUES(secret))"), Step("SELECT data,secret FROM assistant_profiles", saved_row))
    result = db.store().save_profile("root-a", {"id": "provider", "name": "Private", "api_key": "raw-provider-key"})
    assert result["has_api_key"] and "api_key" not in result
    insert = db.trace[1][1]
    assert "raw-provider-key" not in json.dumps(insert)
    assert insert[4] is False
    assert db.store()._cipher().decrypt(insert[3].encode()).decode() == "raw-provider-key"
    db = Database(Step("secret=IF(%s,secret,VALUES(secret))"), Step("SELECT data,secret", [{"data": '{"id":"provider"}', "secret": "existing-encrypted"}]))
    assert db.store().save_profile("root-a", {"id": "provider", "api_key": None})["has_api_key"]
    assert db.trace[1][1][4] is True


def test_credentials_do_not_fall_back_to_plaintext_if_key_is_missing(monkeypatch):
    monkeypatch.delenv("ASSISTANT_SECRET_KEY", raising=False)
    factory = Mock(side_effect=AssertionError("Must not write credentials"))
    with pytest.raises(AssistantError, match="ASSISTANT_SECRET_KEY"):
        AssistantStore(connection_factory=factory).save_profile("root-a", {"api_key": "sensitive"})
    factory.assert_not_called()


def test_run_json_cannot_override_owner_or_claim_metadata():
    run = AssistantStore._run({**RUN, "data": '{"owner":"root-b","worker":"attacker","status":"completed","usage":{"total_tokens":3}}'})
    assert run["owner"] == "root-a" and run["worker"] is None and run["status"] == "queued"
    assert run["usage"]["total_tokens"] == 3



def test_fenced_worker_cannot_publish_terminal_state():
    db = Database(Step("SELECT * FROM assistant_runs WHERE id=%s AND owner=%s FOR UPDATE", [{**RUN, "status": "interrupted", "worker": "old-worker"}]))
    with pytest.raises(AssistantError) as error:
        db.store().update_run("root-a", "run-1", "completed", expected_worker="old-worker", usage={"total_tokens": 3})
    assert error.value.code == "ownership_lost"
    assert not any(sql.startswith("UPDATE") for sql, _ in db.trace)
    db.rollback.assert_called_once()


def test_worker_heartbeat_cannot_refresh_a_reassigned_lease():
    db = Database(Step("AND status='running' AND worker=%s", rowcount=0))
    assert not db.store().heartbeat("run-1", worker="old-worker")
    assert db.trace[1][1][-1] == "old-worker"
