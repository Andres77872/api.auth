"""Explicit SQLite test fixture retained for fast isolated transport tests.

All operations run off the ASGI loop. Transactions arbitrate work between API
processes on the same host. Use a persistent local volume (not NFS). Credentials
are encrypted separately and are never included in public profile responses.
"""
from __future__ import annotations

import json
import os
import sqlite3
import time
import uuid
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from src.assistant.models import AssistantError


def uid(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"


def encode(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


class AssistantStore:
    def __init__(self, directory: str | Path):
        self.directory = Path(directory)
        if self.directory.resolve() in {Path("/"), Path.home().resolve(), Path.cwd().resolve()}:
            raise AssistantError("invalid_storage", "ASSISTANT_DATA_DIR must be a dedicated private directory")
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.directory, 0o700)
        self.path = self.directory / "assistant.sqlite3"
        self.checkpoint_path = str(self.directory / "checkpoints.sqlite3")
        with self.connection() as db:
            db.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE IF NOT EXISTS settings(owner TEXT PRIMARY KEY, data TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS profiles(owner TEXT NOT NULL,id TEXT NOT NULL,data TEXT NOT NULL,secret TEXT,PRIMARY KEY(owner,id));
                CREATE TABLE IF NOT EXISTS sessions(id TEXT PRIMARY KEY,owner TEXT NOT NULL,title TEXT NOT NULL,profile_id TEXT,created_at REAL NOT NULL,updated_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS sessions_owner ON sessions(owner,updated_at DESC);
                CREATE TABLE IF NOT EXISTS runs(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,owner TEXT NOT NULL,request_id TEXT NOT NULL,status TEXT NOT NULL,data TEXT NOT NULL,worker TEXT,heartbeat REAL,created_at REAL NOT NULL,updated_at REAL NOT NULL,UNIQUE(owner,request_id));
                CREATE UNIQUE INDEX IF NOT EXISTS runs_active ON runs(session_id) WHERE status IN ('queued','running','waiting_input','cancelling');
                CREATE TABLE IF NOT EXISTS messages(id TEXT PRIMARY KEY,session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,run_id TEXT,role TEXT NOT NULL,content TEXT NOT NULL,created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS messages_session ON messages(session_id,created_at);
                CREATE TABLE IF NOT EXISTS events(seq INTEGER PRIMARY KEY AUTOINCREMENT,session_id TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,kind TEXT NOT NULL,data TEXT NOT NULL,created_at REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS events_session ON events(session_id,seq);
                CREATE TABLE IF NOT EXISTS requests(owner TEXT NOT NULL,request_id TEXT NOT NULL,run_id TEXT NOT NULL,PRIMARY KEY(owner,request_id));
            ''')
        os.chmod(self.path, 0o600)

    @contextmanager
    def connection(self):
        db = sqlite3.connect(self.path, timeout=15)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        db.execute("PRAGMA busy_timeout=15000")
        try:
            with db:
                yield db
        finally:
            db.close()

    def get_settings(self, owner: str, defaults: dict) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT data FROM settings WHERE owner=?", (owner,)).fetchone()
        return json.loads(row[0]) if row else defaults

    def save_settings(self, owner: str, data: dict) -> dict:
        with self.connection() as db:
            db.execute("INSERT INTO settings VALUES(?,?) ON CONFLICT(owner) DO UPDATE SET data=excluded.data", (owner, encode(data)))
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
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if not db.execute("SELECT 1 FROM profiles WHERE owner=? LIMIT 1", (owner,)).fetchone():
                db.execute("INSERT OR IGNORE INTO profiles(owner,id,data) VALUES(?,?,?)", (owner, profile["id"], encode(profile)))

    def profiles(self, owner: str) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT data,secret FROM profiles WHERE owner=? ORDER BY id", (owner,)).fetchall()
        return [{**json.loads(r["data"]), "has_api_key": bool(r["secret"])} for r in rows]

    def profile(self, owner: str, profile_id: str, *, decrypt=False) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT data,secret FROM profiles WHERE owner=? AND id=?", (owner, profile_id)).fetchone()
        if not row:
            raise AssistantError("not_found", "Provider profile not found")
        data = {**json.loads(row["data"]), "has_api_key": bool(row["secret"])}
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
        with self.connection() as db:
            previous = db.execute("SELECT secret FROM profiles WHERE owner=? AND id=?", (owner, profile_id)).fetchone()
            if key is None and previous:
                secret = previous[0]
            db.execute("INSERT INTO profiles VALUES(?,?,?,?) ON CONFLICT(owner,id) DO UPDATE SET data=excluded.data,secret=excluded.secret", (owner, profile_id, encode(data), secret))
        return self.profile(owner, profile_id)

    def delete_profile(self, owner: str, profile_id: str):
        with self.connection() as db:
            if db.execute("SELECT 1 FROM sessions s JOIN runs r ON r.session_id=s.id WHERE s.owner=? AND s.profile_id=? AND r.status IN ('queued','running','waiting_input','cancelling')", (owner, profile_id)).fetchone():
                raise AssistantError("conflict", "Finish or cancel this profile's active runs first")
            db.execute("DELETE FROM profiles WHERE owner=? AND id=?", (owner, profile_id))

    def create_session(self, owner: str, title: str, profile_id: str) -> dict:
        now = time.time()
        data = {"id": uid("session"), "owner": owner, "title": title, "profile_id": profile_id, "created_at": now, "updated_at": now}
        with self.connection() as db:
            db.execute("INSERT INTO sessions VALUES(:id,:owner,:title,:profile_id,:created_at,:updated_at)", data)
        return {**data, "status": "idle"}

    def session(self, owner: str, session_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT s.*,COALESCE((SELECT status FROM runs WHERE session_id=s.id ORDER BY created_at DESC LIMIT 1),'idle') AS status FROM sessions s WHERE s.owner=? AND s.id=?", (owner, session_id)).fetchone()
        if not row:
            raise AssistantError("not_found", "Conversation not found")
        return dict(row)

    def sessions(self, owner: str, limit: int = 100, before: float | None = None) -> list[dict]:
        with self.connection() as db:
            rows = db.execute("SELECT s.*,COALESCE((SELECT status FROM runs WHERE session_id=s.id ORDER BY created_at DESC LIMIT 1),'idle') AS status FROM sessions s WHERE s.owner=? AND s.updated_at<? ORDER BY s.updated_at DESC LIMIT ?", (owner, before or 1e20, min(limit, 100))).fetchall()
        return [dict(r) for r in rows]

    def delete_session(self, owner: str, session_id: str):
        self.session(owner, session_id)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            if db.execute("SELECT 1 FROM runs WHERE session_id=? AND status IN ('queued','running','waiting_input','cancelling')", (session_id,)).fetchone():
                raise AssistantError("conflict", "Cancel the active run before deleting this conversation")
            db.execute("DELETE FROM requests WHERE run_id IN (SELECT id FROM runs WHERE session_id=?)", (session_id,))
            db.execute("DELETE FROM sessions WHERE owner=? AND id=?", (owner, session_id))
        # LangGraph stores are separate: erase persisted memory as well.
        path = Path(self.checkpoint_path)
        if path.exists():
            with sqlite3.connect(path, timeout=15) as db:
                for table in ("checkpoints", "writes"):
                    if db.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)).fetchone():
                        db.execute(f"DELETE FROM {table} WHERE thread_id=? OR thread_id LIKE ?", (session_id, session_id + ":%"))

    def messages(self, owner: str, session_id: str) -> list[dict]:
        self.session(owner, session_id)
        with self.connection() as db:
            rows = db.execute("SELECT * FROM (SELECT * FROM messages WHERE session_id=? ORDER BY created_at DESC LIMIT 500) ORDER BY created_at", (session_id,)).fetchall()
        return [dict(r) for r in rows]

    def message_page(self, owner: str, session_id: str, before_id: str | None = None, limit: int = 100) -> dict:
        self.session(owner, session_id)
        with self.connection() as db:
            before = None
            if before_id:
                before = db.execute("SELECT created_at,id FROM messages WHERE session_id=? AND id=?", (session_id,before_id)).fetchone()
                if not before:
                    raise AssistantError("not_found", "Message cursor not found")
            if before:
                rows = db.execute("SELECT * FROM messages WHERE session_id=? AND (created_at,id)<(?,?) ORDER BY created_at DESC,id DESC LIMIT ?", (session_id,before["created_at"],before["id"],limit+1)).fetchall()
            else:
                rows = db.execute("SELECT * FROM messages WHERE session_id=? ORDER BY created_at DESC,id DESC LIMIT ?", (session_id,limit+1)).fetchall()
        return {"messages": [dict(row) for row in reversed(rows[:limit])], "has_more": len(rows)>limit}

    def history(self, owner: str, session_id: str) -> list[dict]:
        self.session(owner, session_id)
        with self.connection() as db:
            rows = db.execute("SELECT m.role,m.content FROM messages m JOIN runs r ON r.id=m.run_id WHERE m.session_id=? AND r.status='completed' ORDER BY m.created_at", (session_id,)).fetchall()
        # Graph summarization handles longer active runs. Bound initial history
        # too, without ever rehydrating pending/failed tool-call messages.
        history, size = [], 0
        for row in reversed(rows):
            size += len(row["content"])
            if size > 200000 or len(history) >= 100:
                break
            history.append(dict(row))
        return list(reversed(history))

    def add_message(self, session_id: str, run_id: str, role: str, content: str) -> dict:
        data = {"id": uid("msg"), "session_id": session_id, "run_id": run_id, "role": role, "content": content, "created_at": time.time()}
        with self.connection() as db:
            db.execute("INSERT INTO messages VALUES(:id,:session_id,:run_id,:role,:content,:created_at)", data)
            db.execute("UPDATE sessions SET updated_at=? WHERE id=?", (data["created_at"], session_id))
        return data

    def event(self, session_id: str, kind: str, data: dict) -> dict:
        now = time.time()
        with self.connection() as db:
            cursor = db.execute("INSERT INTO events(session_id,kind,data,created_at) VALUES(?,?,?,?)", (session_id, kind, encode(data), now))
            seq = cursor.lastrowid
            db.execute("UPDATE sessions SET updated_at=? WHERE id=?", (now, session_id))
        return {"type": "event", "session_id": session_id, "seq": seq, "kind": kind, "data": data, "created_at": now}

    def events(self, owner: str, session_id: str, after_seq: int = 0, limit: int = 200) -> list[dict]:
        self.session(owner, session_id)
        with self.connection() as db:
            rows = db.execute("SELECT * FROM events WHERE session_id=? AND seq>? ORDER BY seq LIMIT ?", (session_id, after_seq, min(limit, 500))).fetchall()
        return [{**dict(r), "type": "event", "data": json.loads(r["data"])} for r in rows]

    def snapshot(self, owner: str, session_id: str) -> dict:
        self.session(owner, session_id)
        with self.connection() as db:
            db.execute("BEGIN")
            session_row = db.execute("SELECT * FROM sessions WHERE owner=? AND id=?", (owner,session_id)).fetchone()
            if not session_row:
                raise AssistantError("not_found", "Conversation not found")
            message_rows = db.execute("SELECT * FROM messages WHERE session_id=? ORDER BY created_at DESC,id DESC LIMIT 501", (session_id,)).fetchall()
            messages = [dict(row) for row in reversed(message_rows[:500])]
            last = db.execute("SELECT COALESCE(MAX(seq),0) FROM events WHERE session_id=?", (session_id,)).fetchone()[0]
            run_row = db.execute("SELECT * FROM runs WHERE session_id=? ORDER BY created_at DESC LIMIT 1", (session_id,)).fetchone()
            rows = db.execute("SELECT * FROM (SELECT * FROM events WHERE session_id=? AND kind!='message.delta' ORDER BY seq DESC LIMIT 500) ORDER BY seq", (session_id,)).fetchall()
            partial = []
            if run_row and run_row["status"] != "completed" and not any(m["run_id"] == run_row["id"] and m["role"] == "assistant" for m in messages):
                for row in db.execute("SELECT data FROM events WHERE session_id=? AND kind='message.delta' AND seq<=? ORDER BY seq", (session_id,last)):
                    data = json.loads(row[0])
                    if data.get("run_id") == run_row["id"]:
                        partial.append(data.get("content", ""))
        return {"events": [{**dict(r), "type": "event", "data": json.loads(r["data"])} for r in rows],
                "partial_content": "".join(partial), "last_seq": last,
                "run": self._run(run_row) if run_row else None,
                "messages": messages, "has_older_messages": len(message_rows)>500,
                "session": {**dict(session_row), "status": run_row["status"] if run_row else "idle"}}

    def latest_run(self, owner: str, session_id: str) -> dict | None:
        self.session(owner, session_id)
        with self.connection() as db:
            row = db.execute("SELECT * FROM runs WHERE session_id=? ORDER BY created_at DESC LIMIT 1", (session_id,)).fetchone()
        return self._run(row) if row else None

    @staticmethod
    def _run(row) -> dict:
        data = dict(row)
        payload = json.loads(data.pop("data"))
        return {**data, **payload}

    def run(self, owner: str, run_id: str) -> dict:
        with self.connection() as db:
            row = db.execute("SELECT * FROM runs WHERE id=? AND owner=?", (run_id, owner)).fetchone()
        if not row:
            raise AssistantError("not_found", "Run not found")
        return self._run(row)

    def create_run(self, owner: str, session_id: str, request_id: str, data: dict) -> tuple[dict, bool]:
        self.session(owner, session_id)
        now = time.time()
        run_id = uid("run")
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT * FROM runs WHERE owner=? AND request_id=?", (owner, request_id)).fetchone()
            if previous:
                old = self._run(previous)
                if old["session_id"] != session_id or old.get("message") != data.get("message"):
                    raise AssistantError("conflict", "This request ID was already used for a different message")
                return old, False
            if db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running','cancelling')").fetchone()[0] >= 8:
                raise AssistantError("busy", "The assistant is at capacity; wait for another run to finish")
            try:
                db.execute("INSERT INTO runs VALUES(?,?,?,?,?,?,NULL,NULL,?,?)", (run_id, session_id, owner, request_id, "queued", encode(data), now, now))
            except sqlite3.IntegrityError:
                raise AssistantError("conflict", "This conversation already has an active run") from None
            db.execute("UPDATE sessions SET profile_id=?,updated_at=?,title=CASE WHEN title='New conversation' AND (SELECT COUNT(*) FROM runs WHERE session_id=?)=1 THEN ? ELSE title END WHERE id=?", (data["profile_id"], now, session_id, " ".join(data["message"].split())[:80], session_id))
            db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)", (uid("msg"), session_id, run_id, "user", data["message"], now))
        return self.run(owner, run_id), True

    def update_run(self, owner: str, run_id: str, status: str, *, expected_worker=None, **updates) -> dict:
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT data FROM runs WHERE owner=? AND id=?", (owner, run_id)).fetchone()
            if not row:
                raise AssistantError("not_found", "Run not found")
            data = {**json.loads(row[0]), **updates}
            db.execute("UPDATE runs SET status=?,data=?,updated_at=? WHERE owner=? AND id=?", (status, encode(data), time.time(), owner, run_id))
        return self.run(owner, run_id)

    def claim(self, owner: str, run_id: str, worker: str) -> bool:
        with self.connection() as db:
            result = db.execute("UPDATE runs SET status='running',worker=?,heartbeat=?,updated_at=? WHERE owner=? AND id=? AND status='queued'", (worker, time.time(), time.time(), owner, run_id))
        return result.rowcount == 1

    def heartbeat(self, run_id: str, worker=None):
        with self.connection() as db:
            db.execute("UPDATE runs SET heartbeat=? WHERE id=? AND status='running'", (time.time(), run_id))

    def resume(self, owner: str, session_id: str, run_id: str, request_id: str, resume: Any) -> tuple[dict, bool]:
        self.session(owner, session_id)
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            previous = db.execute("SELECT run_id FROM requests WHERE owner=? AND request_id=?", (owner, request_id)).fetchone()
            if previous:
                if previous[0] != run_id:
                    raise AssistantError("conflict", "Request ID already used")
                return self.run(owner, run_id), False
            row = db.execute("SELECT * FROM runs WHERE owner=? AND session_id=? AND id=?", (owner, session_id, run_id)).fetchone()
            if not row or row["status"] not in {"waiting_input", "interrupted"}:
                raise AssistantError("conflict", "This run is not waiting for input")
            if db.execute("SELECT COUNT(*) FROM runs WHERE status IN ('queued','running','cancelling')").fetchone()[0] >= 8:
                raise AssistantError("busy", "The assistant is at capacity; wait for another run to finish")
            data = {**json.loads(row["data"]), "resume": resume, "interrupt": None}
            db.execute("UPDATE runs SET status='queued',data=?,worker=NULL,heartbeat=NULL,updated_at=? WHERE id=?", (encode(data), time.time(), run_id))
            db.execute("INSERT INTO requests VALUES(?,?,?)", (owner, request_id, run_id))
            db.execute("INSERT INTO events(session_id,kind,data,created_at) VALUES(?,?,?,?)",
                       (session_id, "interrupt.resolved", encode({"run_id": run_id, "responses": resume}), time.time()))
            answers = [value for value in resume.values() if isinstance(value, str)] if isinstance(resume, dict) else []
            if answers:
                db.execute("INSERT INTO messages VALUES(?,?,?,?,?,?)",
                           (uid("msg"), session_id, run_id, "user", "\n\n".join(answers), time.time()))
        return self.run(owner, run_id), True

    def recover_stale(self) -> list[tuple[str, str]]:
        """Never replay unknown side effects after process failure."""
        with self.connection() as db:
            db.execute("BEGIN IMMEDIATE")
            rows = db.execute("SELECT id,session_id,data FROM runs WHERE (status IN ('running','cancelling') AND heartbeat<?) OR (status='queued' AND updated_at<?)", (time.time()-90, time.time()-90)).fetchall()
            for row in rows:
                data = {**json.loads(row["data"]), "error": "The server stopped during execution. Inspect activity before starting a new turn; prior changes are never automatically replayed."}
                db.execute("UPDATE runs SET status='interrupted',data=?,updated_at=? WHERE id=?", (encode(data), time.time(), row["id"]))
        return [(r["id"], r["session_id"]) for r in rows]

    def usage(self, owner: str) -> dict:
        totals = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0, "runs": 0}
        with self.connection() as db:
            rows = db.execute("SELECT data FROM runs WHERE owner=?", (owner,)).fetchall()
        for row in rows:
            totals["runs"] += 1
            usage = json.loads(row[0]).get("usage") or {}
            for key in ("input_tokens", "output_tokens", "total_tokens"):
                totals[key] += int(usage.get(key, 0))
        return totals
