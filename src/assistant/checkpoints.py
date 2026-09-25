"""LangGraph checkpoints in the application's existing MySQL database.

Schema is managed by the normal application migration, never by this adapter.
Each operation borrows a project connection on a worker thread and completes a
transaction before returning it. No model execution or provider data leaves the
existing DB_HOST/DB_NAME connection boundary through this module.
"""
from __future__ import annotations

import asyncio
import hashlib
import random
from collections.abc import AsyncIterator, Callable, Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from langchain_core.runnables import RunnableConfig
from langgraph.checkpoint.base import (
    WRITES_IDX_MAP,
    BaseCheckpointSaver,
    ChannelVersions,
    Checkpoint,
    CheckpointMetadata,
    CheckpointTuple,
    get_checkpoint_id,
    get_checkpoint_metadata,
)
from langgraph.checkpoint.serde.base import SerializerProtocol


CHECKPOINT_COLUMNS = (
    "thread_id, checkpoint_ns, checkpoint_id, parent_checkpoint_id, "
    "checkpoint_type, checkpoint, metadata_type, metadata"
)


def _project_connection():
    # Lazy import: unit tests inject a connection factory and never resolve any
    # deployment credentials or connect to the real application database.
    from src.Util.db_config import get_connection
    return get_connection()


def namespace_hash(namespace: str) -> bytes:
    """Bound the InnoDB index while preserving arbitrarily nested namespaces."""
    return hashlib.sha256(namespace.encode("utf-8")).digest()


def _config(thread_id: str, namespace: str, checkpoint_id: str) -> RunnableConfig:
    return {"configurable": {"thread_id": thread_id, "checkpoint_ns": namespace,
                             "checkpoint_id": checkpoint_id}}


class MySQLCheckpointSaver(BaseCheckpointSaver[str]):
    """Typed, transactional checkpoint saver using the existing MySQL pool.

    Parent links and pending writes implement BaseCheckpointSaver's default
    delta-channel history traversal too. Ordinary repeated task writes keep the
    first result; special interrupt/error/resume writes replace their reserved
    index, matching the official SQLite/PostgreSQL saver semantics.
    """

    def __init__(self, *, connection_factory: Callable[[], Any] | None = None,
                 serde: SerializerProtocol | None = None) -> None:
        super().__init__(serde=serde)
        self.connection_factory = connection_factory or _project_connection
        self._schema_ready = False

    async def __aenter__(self):
        await self.setup()
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        # Connections are transaction-scoped and released by each operation.
        return False

    @contextmanager
    def _cursor(self):
        connection = self.connection_factory()
        cursor = None
        try:
            connection.begin()
            cursor = connection.cursor()
            yield cursor
            connection.commit()
        except BaseException:
            connection.rollback()
            raise
        finally:
            if cursor is not None:
                cursor.close()
            connection.close()

    async def _offload(self, function, *args, **kwargs):
        # Cancellation must not leave a checkpoint transaction racing later
        # cleanup/resume. Thread offloads cannot be forcibly interrupted.
        pending = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            try:
                await pending
            finally:
                raise

    def validate_schema(self) -> None:
        """Readiness check only. Deployment migration owns all DDL."""
        with self._cursor() as cursor:
            cursor.execute(f"SELECT {CHECKPOINT_COLUMNS}, checkpoint_ns_hash FROM assistant_checkpoints LIMIT 0")
            cursor.execute("SELECT thread_id, checkpoint_ns_hash, checkpoint_ns, checkpoint_id, "
                           "task_id, idx, task_path, channel, type, value "
                           "FROM assistant_checkpoint_writes LIMIT 0")

    async def setup(self) -> None:
        if not self._schema_ready:
            await self._offload(self.validate_schema)
            self._schema_ready = True

    def _tuple(self, cursor, row) -> CheckpointTuple:
        thread_id, namespace, checkpoint_id, parent_id, kind, data, metadata_kind, metadata = row
        cursor.execute(
            "SELECT task_id, channel, type, value FROM assistant_checkpoint_writes "
            "WHERE thread_id=%s AND checkpoint_ns_hash=%s AND checkpoint_ns=%s "
            "AND checkpoint_id=%s ORDER BY task_id, idx",
            (thread_id, namespace_hash(namespace), namespace, checkpoint_id),
        )
        writes = [(task_id, channel, self.serde.loads_typed((value_kind, bytes(value))))
                  for task_id, channel, value_kind, value in cursor.fetchall()]
        return CheckpointTuple(
            _config(thread_id, namespace, checkpoint_id),
            self.serde.loads_typed((kind, bytes(data))),
            self.serde.loads_typed((metadata_kind, bytes(metadata))),
            _config(thread_id, namespace, parent_id) if parent_id else None,
            writes,
        )

    def get_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        namespace = str(configurable.get("checkpoint_ns", ""))
        parameters: list[Any] = [thread_id, namespace_hash(namespace), namespace]
        query = (f"SELECT {CHECKPOINT_COLUMNS} FROM assistant_checkpoints "
                 "WHERE thread_id=%s AND checkpoint_ns_hash=%s AND checkpoint_ns=%s")
        checkpoint_id = get_checkpoint_id(config)
        if checkpoint_id:
            query += " AND checkpoint_id=%s"
            parameters.append(checkpoint_id)
        query += " ORDER BY checkpoint_id DESC LIMIT 1"
        with self._cursor() as cursor:
            cursor.execute(query, parameters)
            row = cursor.fetchone()
            return self._tuple(cursor, row) if row else None

    async def aget_tuple(self, config: RunnableConfig) -> CheckpointTuple | None:
        return await self._offload(self.get_tuple, config)

    def _list(self, config, *, filter=None, before=None, limit=None) -> list[CheckpointTuple]:
        if limit is not None and limit <= 0:
            return []
        clauses = []
        parameters = []
        if config is not None:
            configurable = config["configurable"]
            clauses.append("thread_id=%s")
            parameters.append(str(configurable["thread_id"]))
            if "checkpoint_ns" in configurable:
                namespace = str(configurable["checkpoint_ns"])
                clauses.extend(["checkpoint_ns_hash=%s", "checkpoint_ns=%s"])
                parameters.extend([namespace_hash(namespace), namespace])
            if checkpoint_id := get_checkpoint_id(config):
                clauses.append("checkpoint_id=%s")
                parameters.append(checkpoint_id)
        if before is not None and (checkpoint_id := get_checkpoint_id(before)):
            clauses.append("checkpoint_id<%s")
            parameters.append(checkpoint_id)
        query = f"SELECT {CHECKPOINT_COLUMNS} FROM assistant_checkpoints"
        if clauses:
            query += " WHERE " + " AND ".join(clauses)
        query += " ORDER BY checkpoint_id DESC, thread_id, checkpoint_ns_hash"
        if limit is not None and not filter:
            query += " LIMIT %s"
            parameters.append(int(limit))
        results = []
        with self._cursor() as cursor:
            cursor.execute(query, parameters)
            rows = cursor.fetchall()
            for row in rows:
                if filter:
                    metadata = self.serde.loads_typed((row[6], bytes(row[7])))
                    if not all(metadata.get(key) == value for key, value in filter.items()):
                        continue
                results.append(self._tuple(cursor, row))
                if limit is not None and len(results) >= limit:
                    break
        return results

    def list(self, config: RunnableConfig | None, *, filter: dict[str, Any] | None = None,
             before: RunnableConfig | None = None, limit: int | None = None) -> Iterator[CheckpointTuple]:
        return iter(self._list(config, filter=filter, before=before, limit=limit))

    async def alist(self, config: RunnableConfig | None, *, filter: dict[str, Any] | None = None,
                    before: RunnableConfig | None = None, limit: int | None = None) -> AsyncIterator[CheckpointTuple]:
        for checkpoint in await self._offload(self._list, config, filter=filter, before=before, limit=limit):
            yield checkpoint

    def put(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata,
            new_versions: ChannelVersions) -> RunnableConfig:
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        namespace = str(configurable.get("checkpoint_ns", ""))
        kind, data = self.serde.dumps_typed(checkpoint)
        metadata_kind, metadata_data = self.serde.dumps_typed(get_checkpoint_metadata(config, metadata))
        with self._cursor() as cursor:
            cursor.execute(
                "INSERT INTO assistant_checkpoints "
                "(thread_id, checkpoint_ns_hash, checkpoint_ns, checkpoint_id, parent_checkpoint_id, "
                "checkpoint_type, checkpoint, metadata_type, metadata) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON DUPLICATE KEY UPDATE parent_checkpoint_id=VALUES(parent_checkpoint_id), "
                "checkpoint_type=VALUES(checkpoint_type), checkpoint=VALUES(checkpoint), "
                "metadata_type=VALUES(metadata_type), metadata=VALUES(metadata)",
                (thread_id, namespace_hash(namespace), namespace, checkpoint["id"],
                 configurable.get("checkpoint_id"), kind, data, metadata_kind, metadata_data),
            )
        return _config(thread_id, namespace, checkpoint["id"])

    async def aput(self, config: RunnableConfig, checkpoint: Checkpoint, metadata: CheckpointMetadata,
                   new_versions: ChannelVersions) -> RunnableConfig:
        return await self._offload(self.put, config, checkpoint, metadata, new_versions)

    def put_writes(self, config: RunnableConfig, writes: Sequence[tuple[str, Any]],
                   task_id: str, task_path: str = "") -> None:
        if not writes:
            return
        configurable = config["configurable"]
        thread_id = str(configurable["thread_id"])
        namespace = str(configurable.get("checkpoint_ns", ""))
        query = ("INSERT INTO assistant_checkpoint_writes "
                 "(thread_id, checkpoint_ns_hash, checkpoint_ns, checkpoint_id, task_id, idx, "
                 "task_path, channel, type, value) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ")
        if all(channel in WRITES_IDX_MAP for channel, _ in writes):
            query += ("ON DUPLICATE KEY UPDATE task_path=VALUES(task_path), channel=VALUES(channel), "
                      "type=VALUES(type), value=VALUES(value)")
        else:
            # Avoid INSERT IGNORE, which can silently discard truncation and
            # data-integrity errors unrelated to duplicate retries.
            query += "ON DUPLICATE KEY UPDATE idx=idx"
        values = [(thread_id, namespace_hash(namespace), namespace, configurable["checkpoint_id"],
                   str(task_id), WRITES_IDX_MAP.get(channel, index), task_path, channel,
                   *self.serde.dumps_typed(value)) for index, (channel, value) in enumerate(writes)]
        with self._cursor() as cursor:
            cursor.executemany(query, values)

    async def aput_writes(self, config: RunnableConfig, writes: Sequence[tuple[str, Any]],
                          task_id: str, task_path: str = "") -> None:
        await self._offload(self.put_writes, config, writes, task_id, task_path)

    def delete_thread(self, thread_id: str) -> None:
        with self._cursor() as cursor:
            for table in ("assistant_checkpoint_writes", "assistant_checkpoints"):
                cursor.execute(f"DELETE FROM {table} WHERE thread_id=%s", (str(thread_id),))

    async def adelete_thread(self, thread_id: str) -> None:
        await self._offload(self.delete_thread, thread_id)

    def delete_session(self, session_id: str) -> None:
        """Remove all run-scoped graphs in one session, including old direct ids."""
        prefix = session_id.replace("!", "!!").replace("%", "!%").replace("_", "!_") + ":%"
        with self._cursor() as cursor:
            for table in ("assistant_checkpoint_writes", "assistant_checkpoints"):
                cursor.execute(f"DELETE FROM {table} WHERE thread_id=%s OR thread_id LIKE %s ESCAPE '!'",
                               (session_id, prefix))

    async def adelete_session(self, session_id: str) -> None:
        await self._offload(self.delete_session, session_id)

    def get_next_version(self, current: str | int | None, channel: Any) -> str:
        # Accept the official SQLite format so imported checkpoints continue.
        number = 0 if current is None else int(str(current).split(".")[0])
        return f"{number + 1:032}.{random.random():016}"
