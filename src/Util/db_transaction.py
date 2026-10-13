"""Request-owned transactions for group authorization and graph mutations.

Existing DB helpers can borrow the connection, but only the owner commits it.
The singleton InnoDB row is also locked by graph-table triggers, including writes
from registration, provisioning, and maintenance procedures.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from functools import wraps
import logging


_transaction = ContextVar("group_transaction", default=None)
logger = logging.getLogger(__name__)


class BorrowedConnection:
    def __init__(self, connection):
        self.connection = connection
        self.callbacks = []
        self.failed = False
        self.savepoints = []

    def __getattr__(self, name):
        return getattr(self.connection, name)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def commit(self):
        # Legacy helpers must not release the authorization lock early.
        pass

    def close(self):
        pass

    def rollback(self):
        if self.savepoints:
            with self.connection.cursor() as cursor:
                cursor.execute(f"ROLLBACK TO SAVEPOINT {self.savepoints[-1]}")
        else:
            self.failed = True


def current_connection():
    return _transaction.get()


def after_commit(callback):
    transaction = _transaction.get()
    if transaction is None:
        return callback()
    transaction.callbacks.append(callback)


@contextmanager
def group_transaction(*, write=False):
    if _transaction.get() is not None:
        raise RuntimeError("Group transactions cannot be nested")
    from src.Util import db_config

    connection = db_config.get_connection()
    borrowed = BorrowedConnection(connection)
    token = None
    committed = False
    try:
        connection.begin()
        if write:
            with connection.cursor() as cursor:
                cursor.execute("SELECT id FROM group_graph_lock WHERE id = 1 FOR UPDATE")
                if cursor.fetchone() is None:
                    raise RuntimeError("Group scope migration has not initialized the graph lock")
        token = _transaction.set(borrowed)
        yield borrowed
        if borrowed.failed:
            raise RuntimeError("A group database operation rolled back the transaction")
        connection.commit()
        committed = True
    except BaseException:
        connection.rollback()
        raise
    finally:
        if token is not None:
            _transaction.reset(token)
        connection.close()
    if committed:
        errors = []
        for callback in borrowed.callbacks:
            try:
                callback()
            except Exception as error:
                logger.exception("Post-commit group access cleanup failed")
                errors.append(error)
        if errors:
            raise errors[0]


@contextmanager
def group_savepoint():
    transaction = _transaction.get()
    if transaction is None:
        yield
        return
    name = f"group_item_{len(transaction.savepoints)}"
    callback_count = len(transaction.callbacks)
    with transaction.connection.cursor() as cursor:
        cursor.execute(f"SAVEPOINT {name}")
    transaction.savepoints.append(name)
    try:
        yield
    except Exception:
        with transaction.connection.cursor() as cursor:
            cursor.execute(f"ROLLBACK TO SAVEPOINT {name}")
        del transaction.callbacks[callback_count:]
        raise
    finally:
        transaction.savepoints.pop()
        with transaction.connection.cursor() as cursor:
            cursor.execute(f"RELEASE SAVEPOINT {name}")


def group_item(function):
    @wraps(function)
    def saved(*args, **kwargs):
        with group_savepoint():
            return function(*args, **kwargs)
    return saved
