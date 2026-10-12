"""Small, process-local store double for assistant transport/lifecycle tests.

Only the methods exercised by those tests are implemented. This fake makes no
persistence or database concurrency guarantees; production storage is covered by
MySQL store unit tests and the isolated real-database integration suite.
"""
from copy import deepcopy
from functools import wraps
from threading import RLock
import time

from src.assistant.models import AssistantError
from src.assistant.mysql_store import uid


def serialized(method):
    """Service calls run in worker threads; return detached values like the store."""
    @wraps(method)
    def call(self, *args, **kwargs):
        with self._lock:
            return deepcopy(method(self, *args, **kwargs))
    return call


class MemoryAssistantStore:
    def __init__(self):
        self._lock = RLock()
        self._settings = {}
        self._profiles = {}
        self._sessions = {}
        self._runs = {}
        self._messages = []
        self._events = []

    @serialized
    def get_settings(self, owner, defaults):
        return self._settings.get(owner, defaults)

    @serialized
    def save_settings(self, owner, data):
        self._settings[owner] = deepcopy(data)
        return data

    @serialized
    def ensure_default_profile(self, owner):
        self._profiles.setdefault(owner, {"id": "ollama-default", "name": "Local Ollama",
            "provider": "ollama", "base_url": "http://localhost:11434", "model": "qwen3:8b",
            "enabled": True, "temperature": 0, "max_tokens": 4096,
            "context_window": 32768, "has_api_key": False})

    @serialized
    def profiles(self, owner):
        return [self._profiles[owner]] if owner in self._profiles else []

    @serialized
    def profile(self, owner, profile_id, *, decrypt=False):
        profile = self._profiles.get(owner)
        if profile is None or profile["id"] != profile_id:
            raise AssistantError("not_found", "Provider profile not found")
        return profile

    @serialized
    def create_session(self, owner, title, profile_id):
        now = time.time()
        session = {"id": uid("session"), "owner": owner, "title": title,
                   "profile_id": profile_id, "created_at": now, "updated_at": now}
        self._sessions[session["id"]] = session
        return {**session, "status": "idle"}

    @serialized
    def session(self, owner, session_id):
        session = self._sessions.get(session_id)
        if session is None or session["owner"] != owner:
            raise AssistantError("not_found", "Conversation not found")
        runs = [run for run in self._runs.values() if run["session_id"] == session_id]
        return {**session, "status": runs[-1]["status"] if runs else "idle"}

    @serialized
    def sessions(self, owner):
        return [self.session(owner, row["id"]) for row in self._sessions.values() if row["owner"] == owner]

    @serialized
    def run(self, owner, run_id):
        run = self._runs.get(run_id)
        if run is None or run["owner"] != owner:
            raise AssistantError("not_found", "Run not found")
        return run

    @serialized
    def create_run(self, owner, session_id, request_id, data):
        self.session(owner, session_id)
        for run in self._runs.values():
            if run["owner"] == owner and run["request_id"] == request_id:
                if any(run.get(key) != value for key, value in {
                    "session_id": session_id, "message": data["message"], "profile_id": data["profile_id"],
                }.items()):
                    raise AssistantError("conflict", "This request ID was already used for a different message")
                return run, False
        now = time.time()
        run = {**deepcopy(data), "id": uid("run"), "owner": owner, "session_id": session_id,
               "request_id": request_id, "status": "queued", "worker": None,
               "heartbeat": None, "created_at": now, "updated_at": now}
        self._runs[run["id"]] = run
        self.add_message(session_id, run["id"], "user", data["message"])
        return run, True

    @serialized
    def update_run(self, owner, run_id, status, *, expected_worker=None, **updates):
        self.run(owner, run_id)
        row = self._runs[run_id]
        if expected_worker is not None and (row["worker"] != expected_worker or row["status"] not in {"running", "cancelling"}):
            raise AssistantError("ownership_lost", "This worker no longer owns the active run")
        row.update(deepcopy(updates), status=status, updated_at=time.time())
        return row

    @serialized
    def claim(self, owner, run_id, worker):
        run = self.run(owner, run_id)
        if run["status"] != "queued":
            return False
        self._runs[run_id].update(status="running", worker=worker, heartbeat=time.time())
        return True

    @serialized
    def heartbeat(self, run_id, worker=None):
        run = self._runs[run_id]
        if run["status"] != "running" or (worker is not None and run["worker"] != worker):
            return False
        run["heartbeat"] = time.time()
        return True

    def recover_stale(self):
        """A fresh in-process fake has no persisted orphaned workers to recover."""
        return []

    @serialized
    def reassign_worker(self, run_id, worker):
        """Inject a competing worker claim for lifecycle race tests."""
        self._runs[run_id]["worker"] = worker

    @serialized
    def add_message(self, session_id, run_id, role, content):
        message = {"id": uid("msg"), "session_id": session_id, "run_id": run_id,
                   "role": role, "content": content, "created_at": time.time()}
        self._messages.append(message)
        self._sessions[session_id]["updated_at"] = message["created_at"]
        return message

    @serialized
    def messages(self, owner, session_id):
        self.session(owner, session_id)
        return [message for message in self._messages if message["session_id"] == session_id]

    @serialized
    def history(self, owner, session_id):
        return [{"role": message["role"], "content": message["content"]}
                for message in self.messages(owner, session_id)
                if self._runs[message["run_id"]]["status"] == "completed"]

    @serialized
    def event(self, session_id, kind, data):
        event = {"type": "event", "session_id": session_id, "seq": len(self._events) + 1,
                 "kind": kind, "data": deepcopy(data), "created_at": time.time()}
        self._events.append(event)
        self._sessions[session_id]["updated_at"] = event["created_at"]
        return event

    @serialized
    def events(self, owner, session_id, after_seq=0, limit=200):
        self.session(owner, session_id)
        return [event for event in self._events if event["session_id"] == session_id and event["seq"] > after_seq][:limit]

    @serialized
    def snapshot(self, owner, session_id):
        session = self.session(owner, session_id)
        events = [event for event in self._events if event["session_id"] == session_id]
        messages = self.messages(owner, session_id)
        runs = [run for run in self._runs.values() if run["session_id"] == session_id]
        run = runs[-1] if runs else None
        partial = ""
        if run and run["status"] != "completed" and not any(message["run_id"] == run["id"] and message["role"] == "assistant" for message in messages):
            partial = "".join(event["data"].get("content", "") for event in events
                              if event["kind"] == "message.delta" and event["data"].get("run_id") == run["id"])
        return {"session": session, "run": run, "messages": messages[-500:],
                "events": [event for event in events if event["kind"] != "message.delta"][-500:],
                "partial_content": partial, "last_seq": events[-1]["seq"] if events else 0,
                "has_older_messages": len(messages) > 500}

    @serialized
    def usage(self, owner):
        runs = [run for run in self._runs.values() if run["owner"] == owner]
        return {"runs": len(runs), **{key: sum(run.get("usage", {}).get(key, 0) for run in runs)
                for key in ("input_tokens", "output_tokens", "total_tokens")}}
