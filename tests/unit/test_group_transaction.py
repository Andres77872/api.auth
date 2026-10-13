from unittest.mock import MagicMock, patch
import pytest

from src.Util.db_transaction import group_transaction, current_connection, after_commit, group_savepoint
from tests.support import make_db_connection_mock, make_db_cursor_mock


def connection():
    return make_db_connection_mock(make_db_cursor_mock(fetchone=(1,)))


def test_borrowed_helpers_cannot_commit_close_or_release_lock_early():
    conn = connection()
    callback = MagicMock()
    with patch('src.Util.db_config.get_connection', return_value=conn):
        with group_transaction(write=True) as borrowed:
            assert current_connection() is borrowed
            with borrowed:
                borrowed.commit()
                borrowed.close()
            conn.commit.assert_not_called()
            conn.close.assert_not_called()
            after_commit(callback)
            callback.assert_not_called()
        conn.commit.assert_called_once()
        conn.close.assert_called_once()
        callback.assert_called_once()
        assert current_connection() is None


def test_failure_rolls_back_and_drops_callbacks():
    conn, callback = connection(), MagicMock()
    with patch('src.Util.db_config.get_connection', return_value=conn):
        with pytest.raises(ValueError):
            with group_transaction(write=True):
                after_commit(callback)
                raise ValueError('failed scope')
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    callback.assert_not_called()
    assert current_connection() is None


def test_item_failure_uses_savepoint_without_rolling_back_successful_items():
    conn, callback = connection(), MagicMock()
    with patch('src.Util.db_config.get_connection', return_value=conn):
        with group_transaction(write=True) as borrowed:
            after_commit(callback)
            with pytest.raises(ValueError):
                with group_savepoint():
                    borrowed.rollback()
                    raise ValueError('one item failed')
        conn.rollback.assert_not_called()
        conn.commit.assert_called_once()
        callback.assert_called_once()
    statements = [call.args[0] for call in conn.cursor().execute.call_args_list]
    assert 'ROLLBACK TO SAVEPOINT group_item_0' in statements


def test_missing_graph_lock_fails_closed():
    conn = connection()
    conn.cursor().fetchone.return_value = None
    with patch('src.Util.db_config.get_connection', return_value=conn):
        with pytest.raises(RuntimeError, match='migration'):
            with group_transaction(write=True):
                pytest.fail('must not execute handler without the lock')
    conn.commit.assert_not_called()


def test_all_post_commit_cleanups_are_attempted_when_one_fails():
    conn, remaining = connection(), MagicMock()
    with patch('src.Util.db_config.get_connection', return_value=conn):
        with pytest.raises(ValueError, match='cleanup failed'):
            with group_transaction(write=True):
                after_commit(MagicMock(side_effect=ValueError('cleanup failed')))
                after_commit(remaining)
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    remaining.assert_called_once()
    assert current_connection() is None
