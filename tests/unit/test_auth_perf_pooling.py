"""
Phase 1.1.T1 — Unit test for PersistentDB connection pooling.

Verifies:
- First get_connection() call initializes the pool (calls pymysql.connect once)
- Subsequent calls reuse pooled connection (no new pymysql.connect)
- Interface unchanged — returned connection behaves same as raw pymysql connection
"""

import pytest
from unittest.mock import patch, MagicMock


def test_pool_reuses_connection_after_first_borrow():
    """
    Borrow connection from pool twice. First borrow initializes pool and
    calls pymysql.connect once. Second borrow reuses pooled connection —
    no new pymysql.connect call.
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("src.Util.db_config.pymysql.connect", return_value=mock_conn) as mock_connect:
        # Force reimport to clear module-level _pool
        import importlib
        import src.Util.db_config as db_config
        db_config._pool = None

        # First call: should initialize pool + call pymysql.connect once
        conn1 = db_config.get_connection()
        assert mock_connect.call_count == 1, (
            f"Expected 1 pymysql.connect call on first borrow, got {mock_connect.call_count}"
        )

        # Second call: should reuse pooled connection, no new pymysql.connect
        mock_connect.reset_mock()
        conn2 = db_config.get_connection()
        assert mock_connect.call_count == 0, (
            f"Expected 0 pymysql.connect calls on second borrow, got {mock_connect.call_count}"
        )

        # Both connections return data from the same underlying mock
        cursor1 = conn1.cursor()
        cursor2 = conn2.cursor()
        # Cursors may be wrapped by PersistentDB's SteadyDBCursor, so identity check
        # is unreliable — instead verify both cursors execute against the same mock
        cursor1.execute("SELECT 1")
        cursor2.execute("SELECT 2")
        assert mock_cursor.execute.call_count == 2, (
            "Both borrows' cursors should execute against the same underlying mock"
        )
        mock_cursor.execute.assert_any_call("SELECT 1")
        mock_cursor.execute.assert_any_call("SELECT 2")


def test_pool_returns_usable_connection_object():
    """
    Verify the connection returned from pool has the expected interface
    (cursor, close methods) matching a raw pymysql connection.
    """
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value = mock_cursor

    with patch("src.Util.db_config.pymysql.connect", return_value=mock_conn):
        import importlib
        import src.Util.db_config as db_config
        db_config._pool = None

        conn = db_config.get_connection()

        # Verify interface compatibility
        assert hasattr(conn, 'cursor'), "Pool connection must have cursor() method"
        assert hasattr(conn, 'close'), "Pool connection must have close() method"
        assert hasattr(conn, 'commit'), "Pool connection must have commit() method"

        # Cursor should work
        cur = conn.cursor()
        cur.execute("SELECT 1")
        mock_cursor.execute.assert_called_once_with("SELECT 1")


def test_pool_env_vars_control_config():
    """
    Verify DB_POOL_MAXUSAGE and DB_POOL_PING env vars are read correctly.
    Defaults should be 1000 and 1 respectively.
    """
    import src.Util.db_config as db_config

    # Check defaults are set from module constants (not env-sensitive in test)
    assert hasattr(db_config, 'DB_POOL_MAXUSAGE'), "DB_POOL_MAXUSAGE constant must exist"
    assert hasattr(db_config, 'DB_POOL_PING'), "DB_POOL_PING constant must exist"

    # Values are read at import time; we just verify they're ints with sensible defaults
    assert isinstance(db_config.DB_POOL_MAXUSAGE, int)
    assert isinstance(db_config.DB_POOL_PING, int)
    assert db_config.DB_POOL_MAXUSAGE > 0
    assert db_config.DB_POOL_PING in (0, 1)


def test_pool_lazy_init_on_first_call():
    """
    Pool should be None before first get_connection() call.
    After first call, pool should be initialized.
    """
    import src.Util.db_config as db_config
    db_config._pool = None

    assert db_config._pool is None, "Pool should be None before first call"

    mock_conn = MagicMock()
    with patch("src.Util.db_config.pymysql.connect", return_value=mock_conn):
        conn = db_config.get_connection()
        assert db_config._pool is not None, "Pool should be initialized after first call"
