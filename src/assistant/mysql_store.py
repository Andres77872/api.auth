"""Assistant persistence in the application's configured MySQL database.

DDL is installed by the normal schema deployment/migration workflow. This store
never creates a local database, silently falls back, or runs DDL at startup.
All public methods are synchronous for the service's ``asyncio.to_thread``
boundary. Each method owns one transaction and returns detached Python values.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from collections.abc import Callable, Mapping
from contextlib import contextmanager
from typing import Any

import pymysql

from src.assistant.models import AssistantError

ACTIVE_STATUSES = ("queued", "running", "waiting_input", "cancelling")
CAPACITY_STATUSES = ("queued", "running", "cancelling")
MAX_CONCURRENT_RUNS = 8


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def encode(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def _json(value: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    return json.loads(value)


def _default_connection():
    # Lazy import respects the same environment/configuration and pool as the
    # rest of the app without opening a connection when the assistant is off.
    from src.Util.db_config import get_connection
    return get_connection()


class AssistantStore:
    def __init__(self, *, connection_factory: Callable[[], Any] | None = None):
        self.connection_factory = connection_factory or _default_connection

    @contextmanager
    def connection(self, *, consistent_snapshot: bool = False):
        """Yield a native DictCursor, committing once or rolling back on failure."""
        db = self.connection_factory()
        cursor = None
        try:
            cursor = db.cursor(pymysql.cursors.DictCursor)
            if consistent_snapshot:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                cursor.execute("START TRANSACTION WITH CONSISTENT SNAPSHOT")
            else:
                db.begin()
            yield cursor
            db.commit()
        except BaseException:
            db.rollback()
            raise
        finally:
            if cursor is not None:
                cursor.close()
            db.close()

    @staticmethod
    def _session(cursor, owner: str, session_id: str, *, lock: bool = False) -> dict:
        sql = "SELECT * FROM assistant_sessions WHERE owner=%s AND id=%s"
        cursor.execute(sql + (" FOR UPDATE" if lock else ""), (owner, session_id))
        row = cursor.fetchone()
        if not row:
            raise AssistantError("not_found", "Conversation not found")
        return dict(row)

    @staticmethod
    def _lock_session(cursor, session_id: str) -> dict:
        # Also serializes event sequence allocation/commit order for this session.
        cursor.execute("SELECT * FROM assistant_sessions WHERE id=%s FOR UPDATE", (session_id,))
        row = cursor.fetchone()
        if not row:
            raise AssistantError("not_found", "Conversation not found")
        return dict(row)

    @staticmethod
    def _capacity_lock(cursor):
        cursor.execute("SELECT id FROM assistant_runtime_lock WHERE id=1 FOR UPDATE")
        if not cursor.fetchone():
            raise AssistantError("storage_not_configured", "Assistant MySQL schema is missing its runtime lock row; run the assistant schema migration")

    @staticmethod
    def _check_capacity(cursor):
        cursor.execute("SELECT COUNT(*) AS total FROM assistant_runs WHERE status IN ('queued','running','cancelling')")
        if int(cursor.fetchone()["total"]) >= MAX_CONCURRENT_RUNS:
            raise AssistantError("busy", "The assistant is at capacity; wait for another run to finish")

    @staticmethod
    def _run(row: Mapping) -> dict:
        fields = dict(row)
        payload = _json(fields.pop("data"))
        # Metadata is authoritative even if a caller supplied colliding JSON keys.
        return {**payload, **fields}

    @staticmethod
    def _run_row(cursor, owner: str, run_id: str, *, lock: bool = False) -> dict:
        sql = "SELECT * FROM assistant_runs WHERE id=%s AND owner=%s"
        cursor.execute(sql + (" FOR UPDATE" if lock else ""), (run_id, owner))
        row = cursor.fetchone()
        if not row:
            raise AssistantError("not_found", "Run not found")
        return dict(row)

    @staticmethod
    def _latest(cursor, session_id: str) -> dict | None:
        cursor.execute("SELECT * FROM assistant_runs WHERE session_id=%s ORDER BY created_at DESC,id DESC LIMIT 1", (session_id,))
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def _event_value(row: Mapping) -> dict:
        return {**dict(row), "type": "event", "data": _json(row["data"])}

    @staticmethod
    def _insert_event(cursor, session_id: str, kind: str, data: dict, now: float) -> dict:
        # The caller must hold this session's row lock until commit. Reserving an
        # AUTO_INCREMENT value alone does not order commits across transactions.
        cursor.execute("INSERT INTO assistant_events(session_id,kind,data,created_at) VALUES(%s,%s,%s,%s)", (session_id, kind, encode(data), now))
        seq = cursor.lastrowid
        cursor.execute("UPDATE assistant_sessions SET updated_at=%s WHERE id=%s", (now, session_id))
        return {"type": "event", "session_id": session_id, "seq": seq, "kind": kind, "data": data, "created_at": now}

    @staticmethod
    def _insert_message(cursor, session_id: str, run_id: str, role: str, content: str, now: float) -> dict:
        message = {"id": uid("msg"), "session_id": session_id, "run_id": run_id, "role": role, "content": content, "created_at": now}
        cursor.execute("INSERT INTO assistant_messages(id,session_id,run_id,role,content,created_at) VALUES(%s,%s,%s,%s,%s,%s)", tuple(message[key] for key in ("id", "session_id", "run_id", "role", "content", "created_at")))
        cursor.execute("UPDATE assistant_sessions SET updated_at=%s WHERE id=%s", (now, session_id))
        return message

    def get_settings(self, owner: str, defaults: dict) -> dict:
        with self.connection() as cursor:
            cursor.execute("SELECT data FROM assistant_settings WHERE owner=%s", (owner,))
            row = cursor.fetchone()
        return _json(row["data"]) if row else dict(defaults)

    def save_settings(self, owner: str, data: dict) -> dict:
        with self.connection() as cursor:
            cursor.execute("INSERT INTO assistant_settings(owner,data) VALUES(%s,%s) ON DUPLICATE KEY UPDATE data=VALUES(data)", (owner, encode(data)))
        return data

    def _cipher(self):
        from cryptography.fernet import Fernet
        key = os.getenv("ASSISTANT_SECRET_KEY")
        if not key:
            raise AssistantError("encryption_not_configured", "Set ASSISTANT_SECRET_KEY before saving provider credentials")
        try:
            return Fernet(key.encode())
        except (ValueError, TypeError):
            raise AssistantError("encryption_not_configured", "ASSISTANT_SECRET_KEY must be a valid Fernet key") from None

    def ensure_default_profile(self, owner: str):
        profile = {"id": "ollama-default", "name": "Local Ollama", "provider": "ollama", "base_url": "http://localhost:11434", "model": "qwen3:8b", "enabled": True, "temperature": 0, "max_tokens": 4096, "context_window": 32768}
        with self.connection() as cursor:
            self._capacity_lock(cursor)
            cursor.execute("SELECT id FROM assistant_profiles WHERE owner=%s LIMIT 1", (owner,))
            if not cursor.fetchone():
                cursor.execute("INSERT IGNORE INTO assistant_profiles(owner,id,data,secret) VALUES(%s,%s,%s,NULL)", (owner, profile["id"], encode(profile)))

    @staticmethod
    def _public_profile(row: Mapping) -> dict:
        return {**_json(row["data"]), "has_api_key": bool(row["secret"])}

    def profiles(self, owner: str) -> list[dict]:
        with self.connection() as cursor:
            cursor.execute("SELECT data,secret FROM assistant_profiles WHERE owner=%s ORDER BY id", (owner,))
            return [self._public_profile(row) for row in cursor.fetchall()]

    def profile(self, owner: str, profile_id: str, *, decrypt: bool = False) -> dict:
        with self.connection() as cursor:
            cursor.execute("SELECT data,secret FROM assistant_profiles WHERE owner=%s AND id=%s", (owner, profile_id))
            row = cursor.fetchone()
        if not row:
            raise AssistantError("not_found", "Provider profile not found")
        data = self._public_profile(row)
        if decrypt and row["secret"]:
            try:
                data["api_key"] = self._cipher().decrypt(row["secret"].encode()).decode()
            except AssistantError:
                raise
            except Exception:
                raise AssistantError("credential_unavailable", "Provider credentials could not be decrypted; check the encryption key") from None
        return data

    def save_profile(self, owner: str, data: dict) -> dict:
        data = dict(data)
        key = data.pop("api_key", None)
        profile_id = data["id"] = data.get("id") or uid("profile")
        secret = self._cipher().encrypt(key.encode()).decode() if key else None
        with self.connection() as cursor:
            # The single upsert preserves an omitted key atomically, even when
            # another process rotates it concurrently. Empty string clears it.
            cursor.execute(
                "INSERT INTO assistant_profiles(owner,id,data,secret) VALUES(%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE data=VALUES(data),secret=IF(%s,secret,VALUES(secret))",
                (owner, profile_id, encode(data), secret, key is None),
            )
            cursor.execute("SELECT data,secret FROM assistant_profiles WHERE owner=%s AND id=%s", (owner, profile_id))
            return self._public_profile(cursor.fetchone())

    def delete_profile(self, owner: str, profile_id: str):
        with self.connection() as cursor:
            # Creates/resumes use this same guard before changing active counts.
            self._capacity_lock(cursor)
            cursor.execute("SELECT 1 AS found FROM assistant_sessions s JOIN assistant_runs r ON r.session_id=s.id WHERE s.owner=%s AND s.profile_id=%s AND r.status IN ('queued','running','waiting_input','cancelling') LIMIT 1", (owner, profile_id))
            if cursor.fetchone():
                raise AssistantError("conflict", "Finish or cancel this profile's active runs first")
            cursor.execute("DELETE FROM assistant_profiles WHERE owner=%s AND id=%s", (owner, profile_id))

    def create_session(self, owner: str, title: str, profile_id: str) -> dict:
        now = time.time()
        data = {"id": uid("session"), "owner": owner, "title": title, "profile_id": profile_id, "created_at": now, "updated_at": now}
        with self.connection() as cursor:
            cursor.execute("INSERT INTO assistant_sessions(id,owner,title,profile_id,created_at,updated_at) VALUES(%s,%s,%s,%s,%s,%s)", tuple(data[key] for key in ("id", "owner", "title", "profile_id", "created_at", "updated_at")))
        return {**data, "status": "idle"}

    def session(self, owner: str, session_id: str) -> dict:
        with self.connection() as cursor:
            session = self._session(cursor, owner, session_id)
            run = self._latest(cursor, session_id)
        return {**session, "status": run["status"] if run else "idle"}

    def sessions(self, owner: str, limit: int = 100, before: float | None = None) -> list[dict]:
        with self.connection() as cursor:
            cursor.execute("SELECT s.*,COALESCE((SELECT status FROM assistant_runs WHERE session_id=s.id ORDER BY created_at DESC,id DESC LIMIT 1),'idle') AS status FROM assistant_sessions s WHERE s.owner=%s AND s.updated_at<%s ORDER BY s.updated_at DESC,s.id DESC LIMIT %s", (owner, before if before is not None else 1e20, max(1, min(limit, 100))))
            return [dict(row) for row in cursor.fetchall()]

    def delete_session(self, owner: str, session_id: str):
        with self.connection() as cursor:
            self._capacity_lock(cursor)
            self._session(cursor, owner, session_id, lock=True)
            cursor.execute("SELECT id FROM assistant_runs WHERE session_id=%s AND status IN ('queued','running','waiting_input','cancelling') LIMIT 1 FOR UPDATE", (session_id,))
            if cursor.fetchone():
                raise AssistantError("conflict", "Cancel the active run before deleting this conversation")
            # Checkpoints share the same database and transaction as transcripts.
            # Session IDs are server-generated UUIDs, so ':' prefixes cannot
            # contain user-controlled SQL LIKE wildcards.
            for table in ("assistant_checkpoint_writes", "assistant_checkpoints"):
                cursor.execute(f"DELETE FROM {table} WHERE thread_id=%s OR thread_id LIKE %s", (session_id, session_id + ":%"))
            cursor.execute("DELETE q FROM assistant_requests q JOIN assistant_runs r ON r.id=q.run_id WHERE r.session_id=%s", (session_id,))
            cursor.execute("DELETE FROM assistant_sessions WHERE owner=%s AND id=%s", (owner, session_id))

    def messages(self, owner: str, session_id: str) -> list[dict]:
        with self.connection() as cursor:
            self._session(cursor, owner, session_id)
            cursor.execute("SELECT * FROM assistant_messages WHERE session_id=%s ORDER BY created_at DESC,id DESC LIMIT 500", (session_id,))
            return [dict(row) for row in reversed(cursor.fetchall())]

    def message_page(self, owner: str, session_id: str, before_id: str | None = None, limit: int = 100) -> dict:
        limit = max(1, min(int(limit), 500))
        with self.connection() as cursor:
            self._session(cursor, owner, session_id)
            before = None
            if before_id:
                cursor.execute("SELECT created_at,id FROM assistant_messages WHERE session_id=%s AND id=%s", (session_id, before_id))
                before = cursor.fetchone()
                if not before:
                    raise AssistantError("not_found", "Message cursor not found")
            if before:
                cursor.execute("SELECT * FROM assistant_messages WHERE session_id=%s AND (created_at,id)<(%s,%s) ORDER BY created_at DESC,id DESC LIMIT %s", (session_id, before["created_at"], before["id"], limit + 1))
            else:
                cursor.execute("SELECT * FROM assistant_messages WHERE session_id=%s ORDER BY created_at DESC,id DESC LIMIT %s", (session_id, limit + 1))
            rows = cursor.fetchall()
        return {"messages": [dict(row) for row in reversed(rows[:limit])], "has_more": len(rows) > limit}

    def history(self, owner: str, session_id: str) -> list[dict]:
        with self.connection() as cursor:
            self._session(cursor, owner, session_id)
            cursor.execute("SELECT m.role,m.content FROM assistant_messages m JOIN assistant_runs r ON r.id=m.run_id WHERE m.session_id=%s AND r.status='completed' ORDER BY m.created_at DESC,m.id DESC LIMIT 100", (session_id,))
            rows = cursor.fetchall()
        history, size = [], 0
        for row in rows:
            size += len(row["content"])
            if size > 200000:
                break
            history.append(dict(row))
        return list(reversed(history))

    def add_message(self, session_id: str, run_id: str, role: str, content: str) -> dict:
        with self.connection() as cursor:
            self._lock_session(cursor, session_id)
            return self._insert_message(cursor, session_id, run_id, role, content, time.time())

    def event(self, session_id: str, kind: str, data: dict) -> dict:
        with self.connection() as cursor:
            self._lock_session(cursor, session_id)
            return self._insert_event(cursor, session_id, kind, data, time.time())

    def events(self, owner: str, session_id: str, after_seq: int = 0, limit: int = 200) -> list[dict]:
        with self.connection() as cursor:
            self._session(cursor, owner, session_id)
            cursor.execute("SELECT * FROM assistant_events WHERE session_id=%s AND seq>%s ORDER BY seq LIMIT %s", (session_id, after_seq, max(1, min(limit, 500))))
            return [self._event_value(row) for row in cursor.fetchall()]

    def snapshot(self, owner: str, session_id: str) -> dict:
        with self.connection(consistent_snapshot=True) as cursor:
            session = self._session(cursor, owner, session_id)
            cursor.execute("SELECT * FROM assistant_messages WHERE session_id=%s ORDER BY created_at DESC,id DESC LIMIT 501", (session_id,))
            message_rows = cursor.fetchall()
            messages = [dict(row) for row in reversed(message_rows[:500])]
            cursor.execute("SELECT COALESCE(MAX(seq),0) AS last_seq FROM assistant_events WHERE session_id=%s", (session_id,))
            last = int(cursor.fetchone()["last_seq"])
            run = self._latest(cursor, session_id)
            cursor.execute("SELECT * FROM assistant_events WHERE session_id=%s AND kind!='message.delta' ORDER BY seq DESC LIMIT 500", (session_id,))
            events = [self._event_value(row) for row in reversed(cursor.fetchall())]
            partial = []
            if run and run["status"] != "completed" and not any(message["run_id"] == run["id"] and message["role"] == "assistant" for message in messages):
                cursor.execute("SELECT data FROM assistant_events WHERE session_id=%s AND kind='message.delta' AND seq<=%s AND JSON_UNQUOTE(JSON_EXTRACT(data,'$.run_id'))=%s ORDER BY seq", (session_id, last, run["id"]))
                partial = [_json(row["data"]).get("content", "") for row in cursor.fetchall()]
        return {"events": events, "partial_content": "".join(partial), "last_seq": last,
                "run": self._run(run) if run else None, "messages": messages,
                "has_older_messages": len(message_rows) > 500,
                "session": {**session, "status": run["status"] if run else "idle"}}

    def latest_run(self, owner: str, session_id: str) -> dict | None:
        with self.connection() as cursor:
            self._session(cursor, owner, session_id)
            row = self._latest(cursor, session_id)
        return self._run(row) if row else None

    def run(self, owner: str, run_id: str) -> dict:
        with self.connection() as cursor:
            return self._run(self._run_row(cursor, owner, run_id))

    def create_run(self, owner: str, session_id: str, request_id: str, data: dict) -> tuple[dict, bool]:
        now, run_id = time.time(), uid("run")
        with self.connection() as cursor:
            # Global→session is the shared order for capacity-changing operations.
            self._capacity_lock(cursor)
            session = self._session(cursor, owner, session_id, lock=True)
            cursor.execute("SELECT * FROM assistant_runs WHERE owner=%s AND request_id=%s FOR UPDATE", (owner, request_id))
            previous = cursor.fetchone()
            if previous:
                old = self._run(previous)
                if old["session_id"] != session_id or old.get("message") != data.get("message") or old.get("profile_id") != data.get("profile_id"):
                    raise AssistantError("conflict", "This request ID was already used for a different message")
                return old, False
            cursor.execute("SELECT id FROM assistant_runs WHERE session_id=%s AND status IN ('queued','running','waiting_input','cancelling') LIMIT 1 FOR UPDATE", (session_id,))
            if cursor.fetchone():
                raise AssistantError("conflict", "This conversation already has an active run")
            self._check_capacity(cursor)
            try:
                cursor.execute("INSERT INTO assistant_runs(id,session_id,owner,request_id,status,data,worker,heartbeat,created_at,updated_at) VALUES(%s,%s,%s,%s,'queued',%s,NULL,NULL,%s,%s)", (run_id, session_id, owner, request_id, encode(data), now, now))
            except pymysql.IntegrityError:
                raise AssistantError("conflict", "This conversation or request already has an active run") from None
            title = session["title"]
            if title == "New conversation":
                cursor.execute("SELECT COUNT(*) AS total FROM assistant_runs WHERE session_id=%s", (session_id,))
                if int(cursor.fetchone()["total"]) == 1:
                    title = " ".join(data["message"].split())[:80]
            cursor.execute("UPDATE assistant_sessions SET profile_id=%s,updated_at=%s,title=%s WHERE id=%s", (data["profile_id"], now, title, session_id))
            self._insert_message(cursor, session_id, run_id, "user", data["message"], now)
            return self._run(self._run_row(cursor, owner, run_id)), True

    def update_run(self, owner: str, run_id: str, status: str, *, expected_worker: str | None = None, **updates) -> dict:
        with self.connection() as cursor:
            row = self._run_row(cursor, owner, run_id, lock=True)
            if expected_worker is not None and (row["worker"] != expected_worker or row["status"] not in {"running", "cancelling"}):
                raise AssistantError("ownership_lost", "This worker no longer owns the active run")
            data = {**_json(row["data"]), **updates}
            now = time.time()
            cursor.execute("UPDATE assistant_runs SET status=%s,data=%s,updated_at=%s WHERE owner=%s AND id=%s", (status, encode(data), now, owner, run_id))
            return self._run({**row, "status": status, "data": data, "updated_at": now})

    def claim(self, owner: str, run_id: str, worker: str) -> bool:
        with self.connection() as cursor:
            now = time.time()
            cursor.execute("UPDATE assistant_runs SET status='running',worker=%s,heartbeat=%s,updated_at=%s WHERE owner=%s AND id=%s AND status='queued'", (worker, now, now, owner, run_id))
            return cursor.rowcount == 1

    def heartbeat(self, run_id: str, worker: str | None = None) -> bool:
        with self.connection() as cursor:
            if worker is None:
                cursor.execute("UPDATE assistant_runs SET heartbeat=%s WHERE id=%s AND status='running'", (time.time(), run_id))
            else:
                cursor.execute("UPDATE assistant_runs SET heartbeat=%s WHERE id=%s AND status='running' AND worker=%s", (time.time(), run_id, worker))
            return cursor.rowcount == 1

    def resume(self, owner: str, session_id: str, run_id: str, request_id: str, resume: Any) -> tuple[dict, bool]:
        with self.connection() as cursor:
            self._capacity_lock(cursor)
            self._session(cursor, owner, session_id, lock=True)
            cursor.execute("SELECT run_id FROM assistant_requests WHERE owner=%s AND request_id=%s FOR UPDATE", (owner, request_id))
            previous = cursor.fetchone()
            if previous:
                if previous["run_id"] != run_id:
                    raise AssistantError("conflict", "Request ID already used")
                row = self._run_row(cursor, owner, run_id)
                if row["session_id"] != session_id:
                    raise AssistantError("not_found", "Run not found")
                return self._run(row), False
            row = self._run_row(cursor, owner, run_id, lock=True)
            if row["session_id"] != session_id or row["status"] not in {"waiting_input", "interrupted"}:
                raise AssistantError("conflict", "This run is not waiting for input")
            cursor.execute("SELECT id FROM assistant_runs WHERE session_id=%s AND id<>%s AND status IN ('queued','running','waiting_input','cancelling') LIMIT 1 FOR UPDATE", (session_id, run_id))
            if cursor.fetchone():
                raise AssistantError("conflict", "This conversation already has an active run")
            self._check_capacity(cursor)
            now = time.time()
            data = {**_json(row["data"]), "resume": resume, "interrupt": None, "interrupts": []}
            cursor.execute("UPDATE assistant_runs SET status='queued',data=%s,worker=NULL,heartbeat=NULL,updated_at=%s WHERE id=%s", (encode(data), now, run_id))
            cursor.execute("INSERT INTO assistant_requests(owner,request_id,run_id) VALUES(%s,%s,%s)", (owner, request_id, run_id))
            self._insert_event(cursor, session_id, "interrupt.resolved", {"run_id": run_id, "responses": resume}, now)
            answers = [value for value in resume.values() if isinstance(value, str)] if isinstance(resume, dict) else []
            if answers:
                self._insert_message(cursor, session_id, run_id, "user", "\n\n".join(answers), now)
            return self._run({**row, "status": "queued", "data": data, "worker": None, "heartbeat": None, "updated_at": now}), True

    def recover_stale(self) -> list[tuple[str, str]]:
        """Fence orphaned workers; never replay unknown application side effects."""
        with self.connection() as cursor:
            self._capacity_lock(cursor)
            cutoff = time.time() - 90
            cursor.execute("SELECT id,session_id,data FROM assistant_runs WHERE (status IN ('running','cancelling') AND heartbeat<%s) OR (status='queued' AND updated_at<%s) FOR UPDATE", (cutoff, cutoff))
            rows = cursor.fetchall()
            for row in rows:
                data = {**_json(row["data"]), "error": "The server stopped during execution. Inspect activity before starting a new turn; prior changes are never automatically replayed."}
                cursor.execute("UPDATE assistant_runs SET status='interrupted',data=%s,updated_at=%s WHERE id=%s", (encode(data), time.time(), row["id"]))
        return [(row["id"], row["session_id"]) for row in rows]

    def usage(self, owner: str) -> dict:
        with self.connection() as cursor:
            cursor.execute(
                "SELECT COUNT(*) AS runs,"
                "COALESCE(SUM(CAST(JSON_UNQUOTE(JSON_EXTRACT(data,'$.usage.input_tokens')) AS UNSIGNED)),0) AS input_tokens,"
                "COALESCE(SUM(CAST(JSON_UNQUOTE(JSON_EXTRACT(data,'$.usage.output_tokens')) AS UNSIGNED)),0) AS output_tokens,"
                "COALESCE(SUM(CAST(JSON_UNQUOTE(JSON_EXTRACT(data,'$.usage.total_tokens')) AS UNSIGNED)),0) AS total_tokens "
                "FROM assistant_runs WHERE owner=%s", (owner,),
            )
            row = cursor.fetchone()
        return {key: int(row[key] or 0) for key in ("input_tokens", "output_tokens", "total_tokens", "runs")}
