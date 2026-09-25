"""Checkpoint protocol tests with a local DB-API double; no live DB or model.

The double translates MySQL parameter/upsert syntax to SQLite solely to exercise
serialization, transactions and real LangGraph pause/resume in fast unit tests.
Actual MySQL syntax/DDL is covered separately by the opt-in integration suite.
"""
import asyncio
import json
import re
import sqlite3
import threading
from datetime import datetime, timezone

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import empty_checkpoint
from langgraph.checkpoint.serde.types import INTERRUPT

from src.assistant.checkpoints import MySQLCheckpointSaver, namespace_hash
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

pytestmark = pytest.mark.unit


class DBAPIDouble:
    def __init__(self, path):
        self.path = str(path)
        self.statements = []
        self.opened = self.closed = self.rollbacks = 0
        self.fail_batch = False
        with sqlite3.connect(self.path) as connection:
            connection.executescript('''
                PRAGMA journal_mode=WAL;
                CREATE TABLE assistant_checkpoints (
                    thread_id TEXT, checkpoint_ns_hash BLOB, checkpoint_ns TEXT,
                    checkpoint_id TEXT, parent_checkpoint_id TEXT,
                    checkpoint_type TEXT, checkpoint BLOB, metadata_type TEXT, metadata BLOB,
                    PRIMARY KEY(thread_id, checkpoint_ns_hash, checkpoint_id));
                CREATE TABLE assistant_checkpoint_writes (
                    thread_id TEXT, checkpoint_ns_hash BLOB, checkpoint_ns TEXT,
                    checkpoint_id TEXT, task_id TEXT, idx INTEGER, task_path TEXT,
                    channel TEXT, type TEXT, value BLOB,
                    PRIMARY KEY(thread_id, checkpoint_ns_hash, checkpoint_id, task_id, idx));
            ''')

    def connect(self):
        self.opened += 1
        db = self

        class Connection:
            def __init__(self):
                self.raw = sqlite3.connect(db.path, timeout=30)

            def begin(self):
                self.raw.execute("BEGIN")

            def cursor(self):
                return Cursor(self.raw.cursor())

            def commit(self):
                self.raw.commit()

            def rollback(self):
                db.rollbacks += 1
                self.raw.rollback()

            def close(self):
                db.closed += 1
                self.raw.close()

        class Cursor:
            def __init__(self, raw):
                self.raw = raw

            def execute(self, sql, parameters=()):
                db.statements.append((sql, parameters, threading.get_ident()))
                translated = sql.replace("%s", "?").replace("ON DUPLICATE KEY UPDATE", "ON CONFLICT DO UPDATE SET")
                translated = re.sub(r"VALUES\((\w+)\)", r"excluded.\1", translated)
                return self.raw.execute(translated, parameters)

            def executemany(self, sql, rows):
                for row in rows:
                    self.execute(sql, row)
                    if db.fail_batch:
                        db.fail_batch = False
                        raise RuntimeError("Synthetic database failure")

            def fetchone(self):
                return self.raw.fetchone()

            def fetchall(self):
                return self.raw.fetchall()

            def close(self):
                self.raw.close()

        return Connection()


@pytest.fixture
def database(tmp_path):
    return DBAPIDouble(tmp_path / "db-api-double.sqlite")


def config(thread="session:run", namespace="", checkpoint=None):
    value = {"thread_id": thread, "checkpoint_ns": namespace}
    if checkpoint:
        value["checkpoint_id"] = checkpoint
    return {"configurable": value}


def snapshot(ident, value=None):
    checkpoint = empty_checkpoint()
    checkpoint["id"] = ident
    checkpoint["channel_values"] = {"messages": value or [AIMessage(content="Synthetic answer")]}
    return checkpoint


async def test_schema_validation_is_read_only_and_off_loop(database):
    saver = MySQLCheckpointSaver(connection_factory=database.connect)
    await saver.setup()
    assert all(sql.startswith("SELECT ") for sql, _, _ in database.statements)
    assert all(thread != threading.get_ident() for _, _, thread in database.statements)
    assert database.opened == database.closed == 1


async def test_typed_roundtrip_parent_namespace_and_listing(database):
    saver = MySQLCheckpointSaver(connection_factory=database.connect)
    namespace = "task:nested|" * 300 + "日本語"
    first = await saver.aput(config(namespace=namespace), snapshot("0001"), {"source": "input", "step": -1}, {})
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    second = await saver.aput(first, snapshot("0002", [AIMessage(content="With typed metadata", additional_kwargs={"moment": moment})]),
                             {"source": "loop", "step": 0}, {})
    await saver.aput(config(namespace=namespace + "other"), snapshot("9999"), {"source": "loop", "step": 0}, {})
    read = await MySQLCheckpointSaver(connection_factory=database.connect).aget_tuple(config(namespace=namespace))
    assert read.config == second
    assert read.parent_config == first
    assert read.checkpoint["channel_values"]["messages"][0].additional_kwargs["moment"] == moment
    assert len(namespace_hash(namespace)) == 32
    history = [item async for item in saver.alist(config(namespace=namespace), before=second, filter={"source": "input"}, limit=1)]
    assert [item.config for item in history] == [first]
    assert len(list(saver.list({"configurable": {"thread_id": "session:run"}}))) == 3
    assert list(saver.list(None, limit=0)) == []
    assert database.opened == database.closed


async def test_pending_writes_retry_and_reserved_indexes(database):
    saver = MySQLCheckpointSaver(connection_factory=database.connect)
    saved = await saver.aput(config(), snapshot("0001"), {"step": 0}, {})
    await saver.aput_writes(saved, [("messages", "first")], "task", "parent|child")
    await saver.aput_writes(saved, [("messages", "must not replace")], "task", "parent|child")
    await saver.aput_writes(saved, [(INTERRUPT, {"question": "original"})], "task")
    await saver.aput_writes(saved, [(INTERRUPT, {"question": "updated"})], "task")
    result = await saver.aget_tuple(saved)
    assert result.pending_writes == [("task", INTERRUPT, {"question": "updated"}), ("task", "messages", "first")]
    database.fail_batch = True
    with pytest.raises(RuntimeError, match="Synthetic"):
        await saver.aput_writes(saved, [("one", 1), ("two", 2)], "failed-task")
    assert (await saver.aget_tuple(saved)).pending_writes == result.pending_writes
    assert database.rollbacks == 1
    assert database.opened == database.closed


async def test_default_delta_history_follows_parent_chain_without_branch_writes(database):
    saver = MySQLCheckpointSaver(connection_factory=database.connect)
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


async def test_imported_json_metadata_and_string_versions_continue(database):
    saver = MySQLCheckpointSaver(connection_factory=database.connect)
    saved = await saver.aput(config(), snapshot("0001"), {"source": "input"}, {})
    with sqlite3.connect(database.path) as connection:
        connection.execute("UPDATE assistant_checkpoints SET metadata_type='json', metadata=?", (json.dumps({"source": "input", "step": -1}).encode(),))
    result = await saver.aget_tuple(saved)
    assert result.metadata == {"source": "input", "step": -1}
    assert saver.get_next_version("00000000000000000000000000000002.0.012", None).startswith("00000000000000000000000000000003.")


async def test_session_delete_is_literal_and_removes_nested_pending_writes(database):
    saver = MySQLCheckpointSaver(connection_factory=database.connect)
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
    with sqlite3.connect(database.path) as connection:
        assert connection.execute("SELECT count(*) FROM assistant_checkpoint_writes").fetchone()[0] == 2


async def test_offload_cancellation_waits_for_transaction_completion(database):
    saver = MySQLCheckpointSaver(connection_factory=database.connect)
    started, release, completed = threading.Event(), threading.Event(), threading.Event()

    def pending_operation():
        started.set()
        release.wait(timeout=5)
        completed.set()

    running = asyncio.create_task(saver._offload(pending_operation))
    await asyncio.to_thread(started.wait, 2)
    running.cancel()
    await asyncio.sleep(0.01)
    assert not running.done()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await running
    assert completed.is_set()


@pytest.mark.parametrize("scenario", [graph_faq, graph_skill, graph_question, graph_subagent, graph_subagent_approval, graph_cancel])
async def test_real_deep_agent_uses_mysql_adapter_protocol(environment, monkeypatch, database, scenario):
    context = environment[0]
    context.checkpoint_backend = "mysql"
    context.checkpoint_factory = lambda: MySQLCheckpointSaver(connection_factory=database.connect)
    await scenario(environment, monkeypatch)
    assert database.opened == database.closed


@pytest.mark.parametrize("decision,expected", [("approve", 1), ("reject", 0)])
async def test_reconstructed_mutation_approval_with_mysql_adapter(environment, monkeypatch, database, decision, expected):
    context = environment[0]
    context.checkpoint_backend = "mysql"
    context.checkpoint_factory = lambda: MySQLCheckpointSaver(connection_factory=database.connect)
    await graph_approval(environment, monkeypatch, decision, expected)
    assert database.opened == database.closed


async def test_runtime_defaults_to_existing_mysql_without_sqlite_fallback(environment, monkeypatch):
    from pathlib import Path
    from src.assistant import checkpoints, runtime

    explicit_sqlite_context = environment[0]
    context = runtime.RuntimeContext(**{
        key: value for key, value in vars(explicit_sqlite_context).items()
        if key != "checkpoint_backend"
    })
    selected = []

    class ExistingDatabaseUnavailable:
        def __init__(self):
            selected.append("mysql")

        async def __aenter__(self):
            raise RuntimeError("Synthetic existing MySQL unavailable")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(checkpoints, "MySQLCheckpointSaver", ExistingDatabaseUnavailable)
    assert context.checkpoint_backend == "mysql"
    with pytest.raises(RuntimeError, match="existing MySQL unavailable"):
        async with runtime._checkpoint_saver(context):
            pytest.fail("An unavailable production database must not fall back")
    assert selected == ["mysql"]
    assert not Path(context.checkpoint_path).exists()
