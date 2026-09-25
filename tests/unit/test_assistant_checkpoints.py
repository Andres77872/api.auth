"""Checkpoint serialization and DB-API boundaries without external storage.

Durability, upserts, rollback and graph reconstruction run against real MySQL in
integration/test_assistant_mysql_real_db.py.
"""
import asyncio
import threading
from collections import deque
from datetime import datetime, timezone
from unittest.mock import MagicMock

import pytest
from langchain_core.messages import AIMessage
from langgraph.checkpoint.base import WRITES_IDX_MAP, empty_checkpoint
from langgraph.checkpoint.serde.types import INTERRUPT

from src.assistant.checkpoints import MySQLCheckpointSaver, namespace_hash
from tests.unit.test_assistant_runtime import environment

pytestmark = pytest.mark.unit


@pytest.fixture
def database():
    """Record DB-API operations and return explicitly supplied query results."""
    connection = MagicMock()
    cursor = connection.cursor.return_value
    cursor.fetchone.return_value = None
    cursor.fetchall.return_value = []
    connection.statements = []
    connection.responses = deque()

    def execute(sql, parameters=()):
        connection.statements.append((sql, parameters, threading.get_ident()))
        if connection.responses:
            rows = connection.responses.popleft()
            cursor.fetchone.return_value = rows[0] if rows else None
            cursor.fetchall.return_value = rows

    cursor.execute.side_effect = execute
    return connection


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


async def test_schema_validation_is_read_only_off_loop_and_releases_connection(database):
    saver = MySQLCheckpointSaver(connection_factory=lambda: database)
    await saver.setup()
    await saver.setup()
    assert len(database.statements) == 2
    assert all(sql.startswith("SELECT ") and sql.endswith(" LIMIT 0") for sql, _, _ in database.statements)
    assert all(thread != threading.get_ident() for _, _, thread in database.statements)
    database.begin.assert_called_once()
    database.commit.assert_called_once()
    database.cursor.return_value.close.assert_called_once()
    database.close.assert_called_once()


async def test_typed_checkpoint_parent_and_pending_writes_serialization(database):
    saver = MySQLCheckpointSaver(connection_factory=lambda: database)
    namespace = "task:nested|" * 300 + "日本語"
    parent = config(namespace=namespace, checkpoint="0001")
    moment = datetime(2026, 1, 1, tzinfo=timezone.utc)
    checkpoint = snapshot("0002", [AIMessage(content="Typed answer", additional_kwargs={"moment": moment})])
    saved = await saver.aput(parent, checkpoint, {"source": "loop", "step": 0}, {})
    _, parameters, _ = database.statements[0]
    assert parameters[:5] == ("session:run", namespace_hash(namespace), namespace, "0002", "0001")
    assert len(namespace_hash(namespace)) == 32
    # Feed the recorded serialized payload back as a database result, omitting
    # the namespace hash which is used only for indexing.
    row = (parameters[0], *parameters[2:])
    database.responses.extend([[row], [("task", INTERRUPT, *saver.serde.dumps_typed({"question": "Choose"}))]])
    read = await saver.aget_tuple(saved)
    assert read.config == saved
    assert read.parent_config == parent
    assert read.checkpoint == checkpoint
    assert read.metadata == {"source": "loop", "step": 0}
    assert read.pending_writes == [("task", INTERRUPT, {"question": "Choose"})]
    query, values, _ = database.statements[1]
    assert "checkpoint_id=%s" in query
    assert values == ["session:run", namespace_hash(namespace), namespace, "0002"]
    assert database.begin.call_count == database.commit.call_count == database.close.call_count == 2


async def test_listing_applies_metadata_filter_before_limit(database):
    saver = MySQLCheckpointSaver(connection_factory=lambda: database)
    rows = []
    for ident, source in [("0002", "loop"), ("0001", "input")]:
        rows.append(("session:run", "child", ident, None, *saver.serde.dumps_typed(snapshot(ident)),
                     *saver.serde.dumps_typed({"source": source})))
    database.responses.extend([rows, []])
    result = [item async for item in saver.alist(config(namespace="child"), before=config(checkpoint="0003"),
                                                filter={"source": "input"}, limit=1)]
    assert [item.config for item in result] == [config(namespace="child", checkpoint="0001")]
    query, parameters, _ = database.statements[0]
    assert "LIMIT" not in query
    assert "checkpoint_id<%s" in query
    assert parameters == ["session:run", namespace_hash("child"), "child", "0003"]
    assert list(saver.list(None, limit=0)) == []
    assert len(database.statements) == 2


@pytest.mark.parametrize("scope,limit,expected", [
    (None, 2, [2]),
    ({"configurable": {"thread_id": "thread"}}, None, ["thread"]),
    (config("thread", "child", "0001"), 3, ["thread", namespace_hash("child"), "child", "0001", 3]),
])
def test_listing_query_scopes_and_limit(database, scope, limit, expected):
    saver = MySQLCheckpointSaver(connection_factory=lambda: database)
    assert list(saver.list(scope, limit=limit)) == []
    query, parameters, _ = database.statements[0]
    assert parameters == expected
    assert (" LIMIT %s" in query) is (limit is not None)
    assert ("checkpoint_ns=%s" in query) is bool(scope and "checkpoint_ns" in scope["configurable"])


async def test_missing_checkpoint_returns_none(database):
    saver = MySQLCheckpointSaver(connection_factory=lambda: database)
    assert await saver.aget_tuple(config()) is None
    assert len(database.statements) == 1
    assert "ORDER BY checkpoint_id DESC LIMIT 1" in database.statements[0][0]


async def test_pending_writes_use_reserved_indexes_and_retry_policy(database):
    saver = MySQLCheckpointSaver(connection_factory=lambda: database)
    saved = config(checkpoint="0001")
    await saver.aput_writes(saved, [("messages", "first")], "task", "parent|child")
    sql, rows = database.cursor.return_value.executemany.call_args.args
    assert sql.endswith("ON DUPLICATE KEY UPDATE idx=idx")
    assert rows[0][:8] == ("session:run", namespace_hash(""), "", "0001", "task", 0, "parent|child", "messages")
    assert saver.serde.loads_typed(rows[0][8:]) == "first"
    await saver.aput_writes(saved, [(INTERRUPT, {"question": "updated"})], "task")
    sql, rows = database.cursor.return_value.executemany.call_args.args
    assert "value=VALUES(value)" in sql
    assert rows[0][5] == WRITES_IDX_MAP[INTERRUPT]
    assert saver.serde.loads_typed(rows[0][8:]) == {"question": "updated"}
    await saver.aput_writes(saved, [], "empty")
    assert database.cursor.return_value.executemany.call_count == 2


async def test_batch_failure_rolls_back_and_releases_connection(database):
    saver = MySQLCheckpointSaver(connection_factory=lambda: database)
    database.cursor.return_value.executemany.side_effect = RuntimeError("Synthetic database failure")
    with pytest.raises(RuntimeError, match="Synthetic"):
        await saver.aput_writes(config(checkpoint="0001"), [("one", 1), ("two", 2)], "failed-task")
    database.rollback.assert_called_once()
    database.commit.assert_not_called()
    database.cursor.return_value.close.assert_called_once()
    database.close.assert_called_once()


async def test_session_delete_escapes_wildcards_and_uses_one_transaction(database):
    saver = MySQLCheckpointSaver(connection_factory=lambda: database)
    await saver.adelete_session("s_!%")
    assert len(database.statements) == 2
    assert all(parameters == ("s_!%", "s!_!!!%:%") for _, parameters, _ in database.statements)
    assert all("ESCAPE '!'" in sql for sql, _, _ in database.statements)
    database.begin.assert_called_once()
    database.commit.assert_called_once()
    database.close.assert_called_once()


def test_versions_increase_and_sort_consistently():
    saver = MySQLCheckpointSaver()
    versions = [saver.get_next_version(None, None)]
    for _ in range(12):
        versions.append(saver.get_next_version(versions[-1], None))
    assert versions == sorted(versions)
    assert len(set(versions)) == len(versions)
    assert [int(version.split(".")[0]) for version in versions] == list(range(1, 14))


async def test_offload_cancellation_waits_for_transaction_completion(database):
    saver = MySQLCheckpointSaver(connection_factory=lambda: database)
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


async def test_runtime_defaults_to_existing_mysql_and_propagates_connection_failure(environment, monkeypatch):
    from src.assistant import checkpoints, runtime

    context = environment[0]
    context.checkpoint_factory = None
    selected = []

    class ExistingDatabaseUnavailable:
        def __init__(self):
            selected.append("mysql")

        async def __aenter__(self):
            raise RuntimeError("Synthetic existing MySQL unavailable")

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(checkpoints, "MySQLCheckpointSaver", ExistingDatabaseUnavailable)
    with pytest.raises(RuntimeError, match="existing MySQL unavailable"):
        async with runtime._checkpoint_saver(context):
            pytest.fail("An unavailable production database must not fall back")
    assert selected == ["mysql"]
