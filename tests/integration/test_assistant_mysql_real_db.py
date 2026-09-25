"""Live assistant persistence checks in an explicitly isolated MySQL schema.

Run with REAL_DB_* pointing at a disposable database named assistant_verify_*.
The tests never create, clear or write the application's magic_auth schema.
Canonical tables/14_assistant.sql must already be applied to that test schema.
"""
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
import asyncio
import threading
import uuid

import pymysql
import pytest
from cryptography.fernet import Fernet

from src.assistant.models import AssistantError
from src.assistant.mysql_store import AssistantStore
from tests.integration.conftest import _REAL_DB_CONFIG

pytestmark = pytest.mark.real_db


@pytest.fixture
def mysql_factory():
    config = dict(_REAL_DB_CONFIG)
    database = config.get("database", "")
    if not database.startswith("assistant_verify_"):
        pytest.skip("Requires disposable assistant_verify_* schema; never writes application tables")
    config.pop("cursorclass", None)
    config["autocommit"] = False

    def connect():
        return pymysql.connect(**config)

    return connect


@pytest.fixture
def store(mysql_factory):
    value = AssistantStore(connection_factory=mysql_factory)
    yield value
    # This is a dedicated disposable schema, protected by mysql_factory above.
    with value.connection() as cursor:
        for table in ("assistant_checkpoint_writes", "assistant_checkpoints", "assistant_requests",
                      "assistant_events", "assistant_messages", "assistant_runs", "assistant_sessions",
                      "assistant_profiles", "assistant_settings"):
            cursor.execute(f"DELETE FROM {table}")


def conversation(store, owner="test-root"):
    store.ensure_default_profile(owner)
    return store.create_session(owner, "New conversation", "ollama-default")


def test_profile_encryption_owner_isolation_and_reload(store, mysql_factory, monkeypatch):
    monkeypatch.setenv("ASSISTANT_SECRET_KEY", Fernet.generate_key().decode())
    store.save_settings("test-root", {"enabled": True, "mutations_enabled": False})
    profile = store.save_profile("test-root", {"id": "private", "name": "Private", "api_key": "test-only-key"})
    assert profile["has_api_key"] and "api_key" not in profile
    reloaded = AssistantStore(connection_factory=mysql_factory)
    assert reloaded.profile("test-root", "private", decrypt=True)["api_key"] == "test-only-key"
    assert not reloaded.profiles("other-root")
    assert reloaded.get_settings("test-root", {})["enabled"]
    with reloaded.connection() as cursor:
        cursor.execute("SELECT secret FROM assistant_profiles WHERE owner=%s AND id=%s", ("test-root", "private"))
        assert "test-only-key" not in cursor.fetchone()["secret"]
    reloaded.save_profile("test-root", {"id": "private", "name": "Changed", "api_key": None})
    assert reloaded.profile("test-root", "private", decrypt=True)["api_key"] == "test-only-key"


def test_racing_requests_and_worker_claims_are_atomic(store):
    session = conversation(store)
    payload = {"message": "hello", "profile_id": "ollama-default"}
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: store.create_run("test-root", session["id"], "same", payload), range(8)))
    assert len({run["id"] for run, _ in results}) == 1
    assert sum(created for _, created in results) == 1
    assert len(store.messages("test-root", session["id"])) == 1
    run = results[0][0]
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(pool.map(lambda number: store.claim("test-root", run["id"], str(number)), range(8)))
    assert sum(claims) == 1
    with pytest.raises(AssistantError):
        store.create_run("test-root", session["id"], "same", {**payload, "message": "different"})
    with pytest.raises(AssistantError):
        store.run("other-root", run["id"])


def test_global_capacity_is_transactional_across_sessions(store):
    sessions = [conversation(store) for _ in range(12)]
    def start(item):
        try:
            store.create_run("test-root", item["id"], item["id"], {"message": "hi", "profile_id": "ollama-default"})
            return True
        except AssistantError as error:
            assert error.code == "busy"
            return False
    with ThreadPoolExecutor(max_workers=12) as pool:
        assert sum(pool.map(start, sessions)) == 8


def test_snapshot_full_text_replay_and_session_event_lock(store, mysql_factory):
    session = conversation(store)
    run, _ = store.create_run("test-root", session["id"], "stream", {"message": "hi", "profile_id": "ollama-default"})
    for _ in range(610):
        store.event(session["id"], "message.delta", {"run_id": run["id"], "content": "x"})
    snapshot = AssistantStore(connection_factory=mysql_factory).snapshot("test-root", session["id"])
    assert snapshot["partial_content"] == "x" * 610
    assert store.events("test-root", session["id"], snapshot["last_seq"]) == []
    started = threading.Event()
    def late_event():
        started.set()
        return store.event(session["id"], "message.delta", {"content": "y", "run_id": run["id"]})
    with ThreadPoolExecutor(max_workers=1) as pool:
        with store.connection() as cursor:
            cursor.execute("SELECT id FROM assistant_sessions WHERE id=%s FOR UPDATE", (session["id"],))
            future = pool.submit(late_event)
            assert started.wait(2)
            # A competing insert may not allocate/commit a replay sequence while
            # another transaction owns this conversation's serialization lock.
            with pytest.raises(TimeoutError):
                future.result(timeout=0.1)
        event = future.result(timeout=5)
    assert store.events("test-root", session["id"], snapshot["last_seq"]) == [event]
    with pytest.raises(AssistantError):
        store.snapshot("other-root", session["id"])


@pytest.mark.asyncio
async def test_real_deep_agent_interrupt_survives_new_mysql_saver(mysql_factory, monkeypatch):
    from langchain_core.messages import AIMessage, ToolMessage
    from src.assistant import catalog, runtime, tools
    from src.assistant.checkpoints import MySQLCheckpointSaver
    from tests.unit.test_assistant_runtime import ScriptedModel, call

    monkeypatch.setattr(catalog, "skill_catalog", lambda: [])
    monkeypatch.setattr(catalog, "skill_files", lambda enabled: {})
    monkeypatch.setattr(tools, "build_agent_tools", lambda *args, **kwargs: [])
    model = ScriptedModel(responses=[call("ask_user", {"question": "Which fixture?", "options": ["A", "B"]})])
    monkeypatch.setattr(runtime, "build_model", lambda _: model)
    thread_id = "verify-" + uuid.uuid4().hex
    context = runtime.RuntimeContext(session_id=thread_id, run_id="run", message="Ask which fixture",
                                     profile={}, settings={"enabled_skills": [], "enabled_tools": [], "features": {}},
                                     checkpoint_path="", executor=SimpleNamespace(), checkpoint_backend="mysql",
                                     checkpoint_factory=lambda: MySQLCheckpointSaver(connection_factory=mysql_factory))
    events = []
    async def emit(kind, data):
        events.append((kind, data))
    result = await runtime.run_agent(context, emit)
    assert result.status == "waiting_input"
    resumed_model = ScriptedModel(responses=[AIMessage(content="Fixture A selected.")])
    monkeypatch.setattr(runtime, "build_model", lambda _: resumed_model)
    context.message = None
    context.resume = runtime.normalize_resume(result.interrupts, {"answer": "A"})
    resumed = await runtime.run_agent(context, emit)
    assert resumed.content == "Fixture A selected."
    assert any(isinstance(message, ToolMessage) and message.content == "A" for message in resumed_model.seen_messages[0])
    async with MySQLCheckpointSaver(connection_factory=mysql_factory) as saver:
        saved = await saver.aget_tuple({"configurable": {"thread_id": thread_id}})
        assert saved is not None
        assert len([checkpoint async for checkpoint in saver.alist({"configurable": {"thread_id": thread_id}})]) > 1
        await saver.adelete_thread(thread_id)
        assert await saver.aget_tuple({"configurable": {"thread_id": thread_id}}) is None


def test_long_nested_namespaces_pending_writes_and_atomic_delete(store, mysql_factory):
    from langgraph.checkpoint.base import empty_checkpoint
    from src.assistant.checkpoints import MySQLCheckpointSaver
    session = conversation(store)
    saver = MySQLCheckpointSaver(connection_factory=mysql_factory)
    namespace = "専門家:" * 500
    config = {"configurable": {"thread_id": session["id"] + ":run", "checkpoint_ns": namespace}}
    saved = saver.put(config, empty_checkpoint(), {"source": "input", "step": 0, "parents": {}}, {})
    saver.put_writes(saved, [("fixture", {"count": 17})], "task-1")
    saver.put_writes(saved, [("fixture", {"count": 99})], "task-1")
    saver.put_writes(saved, [("__error__", "first")], "task-1")
    saver.put_writes(saved, [("__error__", "latest")], "task-1")
    result = saver.get_tuple(saved)
    assert result.config["configurable"]["checkpoint_ns"] == namespace
    values = {channel: value for _, channel, value in result.pending_writes}
    assert values["fixture"] == {"count": 17}
    assert values["__error__"] == "latest"
    store.delete_session("test-root", session["id"])
    assert saver.get_tuple(saved) is None
    with store.connection() as cursor:
        cursor.execute("SELECT COUNT(*) AS total FROM assistant_checkpoint_writes")
        assert cursor.fetchone()["total"] == 0
