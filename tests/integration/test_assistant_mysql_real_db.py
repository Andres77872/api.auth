"""Live assistant persistence checks in an explicitly isolated MySQL schema.

Run with REAL_DB_* pointing at a disposable database named assistant_verify_*.
The tests never create, clear or write the application's magic_auth schema.
Canonical tables/14_assistant.sql must already be applied to that test schema.
"""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from types import SimpleNamespace
import asyncio
import threading
import uuid

import pymysql
import pytest
from cryptography.fernet import Fernet
from langchain_core.messages import AIMessage
from langgraph.checkpoint.serde.types import INTERRUPT

from src.assistant.checkpoints import MySQLCheckpointSaver, namespace_hash
from tests.unit.test_assistant_checkpoints import config, snapshot
from tests.unit.test_assistant_runtime import (
    environment,
    test_faq_uses_real_deep_agent_without_app_tools as graph_faq,
    test_skill_read_progressively_enables_tools_and_resets_next_turn as graph_skill,
    test_ask_user_checkpoint_survives_new_graph_and_resumes as graph_question,
    test_subagent_mutation_keeps_approval_gate_across_resume as graph_subagent_approval,
    test_mutation_interrupt_requires_explicit_human_decision as graph_approval,
    test_subagent_uses_scoped_skills_and_aggregate_usage as graph_subagent,
    test_cancellation_closes_graph_and_allows_an_independent_recovery_run as graph_cancel,
)

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
                                     executor=SimpleNamespace(),
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


async def test_typed_roundtrip_parent_namespace_and_listing(store, mysql_factory):
    saver = MySQLCheckpointSaver(connection_factory=mysql_factory)
    namespace = "task:nested|" * 300 + "日本語"
    first = await saver.aput(config(namespace=namespace), snapshot("0001"), {"source": "input", "step": -1}, {})
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second = await saver.aput(first, snapshot("0002", [AIMessage(content="With typed metadata", additional_kwargs={"moment": moment})]),
                             {"source": "loop", "step": 0}, {})
    await saver.aput(config(namespace=namespace + "other"), snapshot("9999"), {"source": "loop", "step": 0}, {})
    read = await MySQLCheckpointSaver(connection_factory=mysql_factory).aget_tuple(config(namespace=namespace))
    assert read.config == second
    assert read.parent_config == first
    assert read.checkpoint["channel_values"]["messages"][0].additional_kwargs["moment"] == moment
    assert len(namespace_hash(namespace)) == 32
    history = [item async for item in saver.alist(config(namespace=namespace), before=second, filter={"source": "input"}, limit=1)]
    assert [item.config for item in history] == [first]
    assert len(list(saver.list({"configurable": {"thread_id": "session:run"}}))) == 3
    assert list(saver.list(None, limit=0)) == []


async def test_pending_writes_retry_and_reserved_indexes(store, mysql_factory):
    saver = MySQLCheckpointSaver(connection_factory=mysql_factory)
    saved = await saver.aput(config(), snapshot("0001"), {"step": 0}, {})
    await saver.aput_writes(saved, [("messages", "first")], "task", "parent|child")
    await saver.aput_writes(saved, [("messages", "must not replace")], "task", "parent|child")
    await saver.aput_writes(saved, [(INTERRUPT, {"question": "original"})], "task")
    await saver.aput_writes(saved, [(INTERRUPT, {"question": "updated"})], "task")
    result = await saver.aget_tuple(saved)
    assert result.pending_writes == [("task", INTERRUPT, {"question": "updated"}), ("task", "messages", "first")]
    with pytest.raises(pymysql.err.DataError):
        await saver.aput_writes(saved, [("one", 1), ("x" * 256, 2)], "failed-task")
    assert (await saver.aget_tuple(saved)).pending_writes == result.pending_writes


async def test_default_delta_history_follows_parent_chain_without_branch_writes(store, mysql_factory):
    saver = MySQLCheckpointSaver(connection_factory=mysql_factory)
    seed = snapshot("0001")
    seed["channel_values"] = {"events": ["seed"]}
    first = await saver.aput(config(), seed, {}, {})
    await saver.aput_writes(first, [("events", ["first-delta"])], "task-first")
    middle = snapshot("0002")
    middle["channel_values"] = {}
    second = await saver.aput(first, middle, {}, {})
    await saver.aput_writes(second, [("events", ["second-delta"])], "task-second")
    branch = snapshot("0003")
    branch["channel_values"] = {}
    fork = await saver.aput(first, branch, {}, {})
    await saver.aput_writes(fork, [("events", ["wrong-branch"])], "task-fork")
    head = snapshot("0004")
    head["channel_values"] = {}
    target = await saver.aput(second, head, {}, {})
    history = await saver.aget_delta_channel_history(config=target, channels=["events"])
    assert history["events"]["seed"] == ["seed"]
    assert [write[2] for write in history["events"]["writes"]] == [["first-delta"], ["second-delta"]]


async def test_session_delete_is_literal_and_removes_nested_pending_writes(store, mysql_factory):
    saver = MySQLCheckpointSaver(connection_factory=mysql_factory)
    for thread in ("s_%", "s_%:run", "sXYZ:run", "s_%:different"):
        for namespace in ("", "task:child"):
            saved = await saver.aput(config(thread, namespace), snapshot("0001"), {}, {})
            await saver.aput_writes(saved, [("messages", "value")], "task")
    await saver.adelete_thread("s_%:different")
    assert await saver.aget_tuple(config("s_%:different", "task:child")) is None
    await saver.adelete_session("s_%")
    remaining = [item async for item in saver.alist(None)]
    assert len(remaining) == 2
    assert all(item.config["configurable"]["thread_id"] == "sXYZ:run" for item in remaining)
    with store.connection() as cursor:
        cursor.execute("SELECT COUNT(*) AS total FROM assistant_checkpoint_writes")
        assert cursor.fetchone()["total"] == 2


@pytest.mark.parametrize("scenario", [graph_faq, graph_skill, graph_question, graph_subagent, graph_subagent_approval, graph_cancel])
async def test_real_deep_agent_uses_mysql_adapter_protocol(environment, monkeypatch, store, mysql_factory, scenario):
    context = environment[0]
    context.checkpoint_factory = lambda: MySQLCheckpointSaver(connection_factory=mysql_factory)
    await scenario(environment, monkeypatch)


@pytest.mark.parametrize("decision,expected", [("approve", 1), ("reject", 0)])
async def test_reconstructed_mutation_approval_with_mysql_adapter(environment, monkeypatch, store, mysql_factory, decision, expected):
    context = environment[0]
    context.checkpoint_factory = lambda: MySQLCheckpointSaver(connection_factory=mysql_factory)
    await graph_approval(environment, monkeypatch, decision, expected)
