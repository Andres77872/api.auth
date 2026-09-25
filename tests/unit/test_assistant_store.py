"""Durability, tenant isolation and at-most-once scheduling invariants."""
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor

import pytest
from cryptography.fernet import Fernet

from src.assistant.models import AssistantError, ProfileInput, Settings
from tests.helpers.assistant_sqlite import AssistantStore


@pytest.fixture
def store(tmp_path):
    return AssistantStore(tmp_path / "assistant")


def conversation(store, owner="root-a"):
    store.ensure_default_profile(owner)
    return store.create_session(owner, "test", "ollama-default")


def test_credentials_encrypted_write_only_and_omission_preserves(store, monkeypatch):
    monkeypatch.setenv("ASSISTANT_SECRET_KEY", Fernet.generate_key().decode())
    profile = store.save_profile("root-a", {"id": "p", "name": "Test", "provider": "openai", "api_key": "sentinel-sensitive-key"})
    assert profile["has_api_key"] and "api_key" not in profile
    assert "sentinel-sensitive-key" not in store.path.read_bytes().decode(errors="ignore")
    store.save_profile("root-a", {"id": "p", "name": "Renamed", "provider": "openai", "api_key": None})
    assert store.profile("root-a", "p", decrypt=True)["api_key"] == "sentinel-sensitive-key"
    assert "api_key" not in store.profiles("root-a")[0]
    assert not store.profiles("root-b")
    with pytest.raises(AssistantError, match="not found"):
        store.profile("root-b", "p")
    store.save_profile("root-a", {"id": "p", "name": "Cleared", "api_key": ""})
    assert not store.profile("root-a", "p")["has_api_key"]


def test_no_plaintext_fallback_without_key(store, monkeypatch):
    monkeypatch.delenv("ASSISTANT_SECRET_KEY", raising=False)
    with pytest.raises(AssistantError, match="ASSISTANT_SECRET_KEY"):
        store.save_profile("root-a", {"api_key": "secret"})
    assert not store.profiles("root-a")


def test_creation_idempotent_with_racing_requests(store):
    session = conversation(store)
    def create(_):
        return store.create_run("root-a", session["id"], "same-request", {"message": "hello", "profile_id": "ollama-default"})
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(create, range(8)))
    assert len({run["id"] for run, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    assert len(store.messages("root-a", session["id"])) == 1
    with pytest.raises(AssistantError, match="different message"):
        store.create_run("root-a", session["id"], "same-request", {"message": "different", "profile_id": "ollama-default"})
    with pytest.raises(AssistantError, match="active run"):
        store.create_run("root-a", session["id"], "other-request", {"message": "hello", "profile_id": "ollama-default"})


def test_claim_only_one_worker_and_stale_run_never_replayed(store):
    session = conversation(store)
    run, _ = store.create_run("root-a", session["id"], "req", {"message": "hello", "profile_id": "ollama-default"})
    assert store.claim("root-a", run["id"], "first")
    assert not store.claim("root-a", run["id"], "second")
    with store.connection() as db:
        db.execute("UPDATE runs SET heartbeat=? WHERE id=?", (time.time()-100, run["id"]))
    assert store.recover_stale() == [(run["id"], session["id"])]
    assert store.run("root-a", run["id"])["status"] == "interrupted"
    assert not store.claim("root-a", run["id"], "third")


def test_reconnect_snapshot_covers_more_than_one_replay_page(store):
    session = conversation(store)
    run, _ = store.create_run("root-a", session["id"], "req", {"message": "hello", "profile_id": "ollama-default"})
    for _ in range(610):
        store.event(session["id"], "message.delta", {"content": "x", "run_id": run["id"]})
    store.event(session["id"], "interrupt", {"question": "Continue?"})
    reloaded = AssistantStore(store.directory)
    snapshot = reloaded.snapshot("root-a", session["id"])
    assert snapshot["partial_content"] == "x" * 610
    assert snapshot["last_seq"] == 611
    assert snapshot["events"][0]["kind"] == "interrupt"
    assert reloaded.events("root-a", session["id"], snapshot["last_seq"]) == []
    later = reloaded.event(session["id"], "message.delta", {"content": "y"})
    assert reloaded.events("root-a", session["id"], snapshot["last_seq"]) == [later]
    for method in (reloaded.session, reloaded.events, reloaded.messages, reloaded.snapshot):
        with pytest.raises(AssistantError, match="not found"):
            method("root-b", session["id"])


def test_delete_removes_logs_messages_and_all_checkpoint_namespaces(store):
    session = conversation(store)
    store.add_message(session["id"], "r", "assistant", "private")
    store.event(session["id"], "tool.audit", {"operation": "read"})
    with sqlite3.connect(store.checkpoint_path) as db:
        db.execute("CREATE TABLE checkpoints(thread_id TEXT)")
        db.executemany("INSERT INTO checkpoints VALUES(?)", [(session["id"],), (session["id"]+":run-2",), ("different",)])
    store.delete_session("root-a", session["id"])
    assert not store.sessions("root-a")
    with store.connection() as db:
        assert db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
        assert db.execute("SELECT COUNT(*) FROM events").fetchone()[0] == 0
    with sqlite3.connect(store.checkpoint_path) as db:
        assert db.execute("SELECT thread_id FROM checkpoints").fetchall() == [("different",)]


def test_configuration_defaults_and_provider_network_scope(monkeypatch):
    assert not Settings().mutations_enabled
    assert Settings().features.subagents
    with pytest.raises(ValueError):
        Settings(features={"subagents": False})
    base = {"name": "test", "provider": "ollama", "model": "tool-model"}
    assert ProfileInput(**base, base_url="http://localhost:11434").enabled
    for url in ("http://169.254.169.254", "file:///etc/passwd", "https://user:pass@api.openai.com", "https://api.openai.com?api_key=secret", "http://api.openai.com"):
        with pytest.raises(ValueError):
            ProfileInput(**base, base_url=url)
    monkeypatch.setenv("ASSISTANT_PROVIDER_HOSTS", "ollama.internal")
    assert ProfileInput(**base, base_url="http://ollama.internal:11434")


def test_private_storage_tightens_existing_directory(tmp_path):
    target = tmp_path / "private"
    target.mkdir(mode=0o755)
    AssistantStore(target)
    assert target.stat().st_mode & 0o777 == 0o700


def test_resumes_share_global_run_capacity(store):
    paused_session = conversation(store)
    paused, _ = store.create_run("root-a", paused_session["id"], "paused", {"message": "Hi", "profile_id": "ollama-default"})
    store.update_run("root-a", paused["id"], "waiting_input")
    for index in range(8):
        session = conversation(store)
        store.create_run("root-a", session["id"], str(index), {"message": "Hi", "profile_id": "ollama-default"})
    with pytest.raises(AssistantError, match="capacity"):
        store.resume("root-a", paused_session["id"], paused["id"], "resume", "answer")
    assert store.run("root-a", paused["id"])["status"] == "waiting_input"


def test_transcript_pagination_is_chronological_and_isolated(store):
    session = conversation(store)
    sent = [store.add_message(session["id"], "run", "user", str(index)) for index in range(7)]
    latest = store.message_page("root-a", session["id"], limit=3)
    assert [m["content"] for m in latest["messages"]] == ["4", "5", "6"]
    assert latest["has_more"]
    older = store.message_page("root-a", session["id"], latest["messages"][0]["id"], 3)
    assert [m["content"] for m in older["messages"]] == ["1", "2", "3"]
    first = store.message_page("root-a", session["id"], older["messages"][0]["id"], 3)
    assert [m["id"] for m in first["messages"]] == [sent[0]["id"]]
    assert not first["has_more"]
    with pytest.raises(AssistantError):
        store.message_page("root-b", session["id"])
    with pytest.raises(AssistantError):
        store.message_page("root-a", session["id"], "unrelated-id")


def test_first_prompt_names_conversation_and_resume_preserves_human_decisions(store):
    session = store.create_session("root-a", "New conversation", "ollama-default")
    run, _ = store.create_run("root-a", session["id"], "start", {"message": "Review  users\n and groups", "profile_id": "ollama-default"})
    assert store.session("root-a", session["id"])["title"] == "Review users and groups"
    store.update_run("root-a", run["id"], "waiting_input")
    resume = {"ask-1": "Only active users", "approve-1": {"decisions": [{"type": "reject"}]}}
    store.resume("root-a", session["id"], run["id"], "reply", resume)
    assert store.messages("root-a", session["id"])[-1]["content"] == "Only active users"
    event = store.events("root-a", session["id"])[-1]
    assert event["kind"] == "interrupt.resolved"
    assert event["data"]["responses"] == resume
    assert store.recover_stale() == []
