"""Unit tests for src/Util/db/db_api_keys.py — Slice 7.

Tests each DB wrapper function calls the correct stored procedure,
handle_db_operation error wrapping is applied, and cache invalidation
is triggered on revoke/update.
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest


def _make_mock_cursor(row_tuple=None, columns=None):
    """Create a mock cursor that returns the given row tuple via fetchone/nextset.

    Args:
        row_tuple: A tuple of values to return from fetchone()
        columns: A list of column name strings for the description
    """
    mock_cursor = MagicMock()
    mock_conn = MagicMock()
    mock_conn.__enter__ = MagicMock(return_value=mock_conn)
    mock_conn.__exit__ = MagicMock(return_value=False)
    mock_conn.cursor.return_value = mock_cursor
    # nextset returns False when no more result sets (prevents infinite loop)
    mock_cursor.nextset.return_value = False

    if row_tuple is not None and columns is not None:
        mock_result_set = MagicMock()
        mock_result_set.fetchone.return_value = row_tuple
        mock_result_set.description = [(col,) for col in columns]
        mock_result_set.fetchall.return_value = [row_tuple]
        mock_cursor.stored_results.return_value = [mock_result_set]
        # Also configure direct cursor methods for the new implementation
        mock_cursor.fetchone.return_value = row_tuple
        mock_cursor.description = [(col,) for col in columns]
        mock_cursor.fetchall.return_value = [row_tuple]
    else:
        mock_cursor.stored_results.return_value = []
        mock_cursor.fetchone.return_value = None
        mock_cursor.description = None

    return mock_conn, mock_cursor


# ─── Slice 7: DB wrapper contract tests ─────────────────────────────────────

class TestCreateApiKey:
    """Test create_api_key calls sp_create_api_key with correct params."""

    def test_calls_correct_stored_procedure(self):
        from src.Util.db.db_api_keys import create_api_key
        cols = ["id", "public_id", "project_id", "owner_user_id", "created_by",
                "name", "description", "hash_algorithm", "fingerprint", "secret_last4",
                "is_active", "expires_at", "created_at"]
        row = ("key-1", "abc123def456", "proj-1", "usr-1", "usr-2",
               "Test Key", None, "hmac-sha256-v1", "a1b2c3d4e5f6", "xyz9",
               True, datetime(2027, 1, 1, tzinfo=timezone.utc),
               datetime(2026, 1, 1, tzinfo=timezone.utc))
        mock_conn, mock_cursor = _make_mock_cursor(row, cols)

        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            create_api_key(
                key_id="key-1", public_id="abc123def456", project_id="proj-1",
                owner_user_id="usr-1", created_by="usr-2", name="Test Key",
                description=None, secret_hash=b"\x00" * 32,
                hash_algorithm="hmac-sha256-v1", fingerprint="a1b2c3d4e5f6",
                secret_last4="xyz9", expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
            )

        mock_cursor.callproc.assert_called_once_with("sp_create_api_key", [
            "key-1", "abc123def456", "proj-1", "usr-1", "usr-2",
            "Test Key", None, b"\x00" * 32, "hmac-sha256-v1",
            "a1b2c3d4e5f6", "xyz9", datetime(2027, 1, 1, tzinfo=timezone.utc),
        ])

    def test_returns_key_metadata(self):
        from src.Util.db.db_api_keys import create_api_key
        cols = ["id", "public_id"]
        row = ("key-1", "abc123def456")
        mock_conn, _ = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            result = create_api_key(
                key_id="key-1", public_id="abc123def456", project_id="proj-1",
                owner_user_id="usr-1", created_by="usr-2", name="Test Key",
                description=None, secret_hash=b"\x00" * 32,
                hash_algorithm="hmac-sha256-v1", fingerprint="a1b2c3d4e5f6",
                secret_last4="xyz9", expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
            )
        assert result is not None
        assert result["id"] == "key-1"
        assert result["public_id"] == "abc123def456"

    def test_returns_none_on_empty_result(self):
        from src.Util.db.db_api_keys import create_api_key
        mock_conn, _ = _make_mock_cursor()
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            result = create_api_key(
                key_id="key-1", public_id="abc123def456", project_id="proj-1",
                owner_user_id="usr-1", created_by="usr-2", name="Test Key",
                description=None, secret_hash=b"\x00" * 32,
                hash_algorithm="hmac-sha256-v1", fingerprint="a1b2c3d4e5f6",
                secret_last4="xyz9", expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
            )
        assert result is None


class TestGetApiKeyByPublicId:
    """Test get_api_key_by_public_id calls sp_get_api_key_by_prefix."""

    def test_calls_correct_stored_procedure(self):
        from src.Util.db.db_api_keys import get_api_key_by_public_id
        cols = ["id", "public_id", "name"]
        row = ("key-1", "abc123def456", "Test Key")
        mock_conn, mock_cursor = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            get_api_key_by_public_id("abc123def456")
        mock_cursor.callproc.assert_called_once_with("sp_get_api_key_by_prefix", ["abc123def456"])

    def test_returns_none_when_not_found(self):
        from src.Util.db.db_api_keys import get_api_key_by_public_id
        mock_conn, _ = _make_mock_cursor()
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            result = get_api_key_by_public_id("nonexistent")
        assert result is None


class TestValidateApiKeyLookup:
    """Test validate_api_key_lookup calls sp_validate_api_key."""

    def test_calls_correct_stored_procedure(self):
        from src.Util.db.db_api_keys import validate_api_key_lookup
        cols = ["id", "public_id", "validation_status", "secret_hash",
                "owner_user_id", "project_id"]
        row = ("key-1", "abc123def456", "valid", b"\x00" * 32, "usr-1", "proj-1")
        mock_conn, mock_cursor = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            validate_api_key_lookup("abc123def456")
        mock_cursor.callproc.assert_called_once_with("sp_validate_api_key", ["abc123def456"])

    def test_returns_validation_data(self):
        from src.Util.db.db_api_keys import validate_api_key_lookup
        cols = ["validation_status", "secret_hash"]
        row = ("valid", b"\x00" * 32)
        mock_conn, _ = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            result = validate_api_key_lookup("abc123def456")
        assert result["validation_status"] == "valid"


class TestRevokeApiKey:
    """Test revoke_api_key calls sp_revoke_api_key."""

    def test_calls_correct_stored_procedure(self):
        from src.Util.db.db_api_keys import revoke_api_key
        cols = ["affected_rows"]
        row = (1,)
        mock_conn, mock_cursor = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            revoke_api_key("key-1", "usr-2", "no longer needed")
        mock_cursor.callproc.assert_called_once_with("sp_revoke_api_key", ["key-1", "usr-2", "no longer needed"])

    def test_returns_affected_rows(self):
        from src.Util.db.db_api_keys import revoke_api_key
        cols = ["affected_rows"]
        row = (1,)
        mock_conn, _ = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            result = revoke_api_key("key-1", "usr-2")
        assert result == 1


class TestRevokeApiKeyWithCacheInvalidation:
    """Test revoke_api_key_with_cache_invalidation calls both revoke + cache invalidate."""

    def test_calls_revoke_and_cache_invalidate(self):
        from src.Util.db.db_api_keys import revoke_api_key_with_cache_invalidation
        cols = ["affected_rows"]
        row = (1,)
        mock_conn, _ = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn), \
             patch("src.Util.db.db_api_keys.cache_manager") as mock_cache:
            result = revoke_api_key_with_cache_invalidation("key-1", "abc123def456", "usr-2")

        assert result == 1
        mock_cache.invalidate_api_key.assert_called_once_with("abc123def456")

    def test_does_not_invalidate_cache_on_failed_revoke(self):
        from src.Util.db.db_api_keys import revoke_api_key_with_cache_invalidation
        mock_conn, _ = _make_mock_cursor()  # No result → None returned
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn), \
             patch("src.Util.db.db_api_keys.cache_manager") as mock_cache:
            result = revoke_api_key_with_cache_invalidation("key-1", "abc123def456", "usr-2")

        assert result is None
        mock_cache.invalidate_api_key.assert_not_called()


class TestListUserApiKeys:
    """Test list_user_api_keys calls sp_list_user_api_keys and returns tuple."""

    def test_calls_correct_stored_procedure(self):
        from src.Util.db.db_api_keys import list_user_api_keys
        cols = ["id", "public_id", "name"]
        row = ("key-1", "abc123", "Key 1")
        mock_conn, mock_cursor = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            list_user_api_keys("usr-1", limit=10, offset=0)
        mock_cursor.callproc.assert_called_once_with("sp_list_user_api_keys", ["usr-1", 10, 0])

    def test_returns_tuple_of_keys_and_total(self):
        from src.Util.db.db_api_keys import list_user_api_keys
        mock_conn, mock_cursor = _make_mock_cursor()
        # Configure for new implementation: fetchall + nextset pattern
        mock_cursor.description = [("id",), ("name",), ("public_id",)]
        mock_cursor.fetchall.return_value = [
            ("key-1", "Key 1", "abc123"),
            ("key-2", "Key 2", "def456"),
            ("key-3", "Key 3", "ghi789"),
            ("key-4", "Key 4", "jkl012"),
            ("key-5", "Key 5", "mno345"),
        ]
        # nextset: first call returns True (move to total count), second returns False
        mock_cursor.nextset.side_effect = [True, False]
        mock_cursor.fetchone.return_value = (5,)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            keys, total = list_user_api_keys("usr-1")
        assert isinstance(keys, list)
        assert total == 5

    def test_returns_empty_tuple_on_error(self):
        from src.Util.db.db_api_keys import list_user_api_keys
        mock_conn, _ = _make_mock_cursor()
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            keys, total = list_user_api_keys("usr-1")
        assert keys == []
        assert total == 0


class TestListProjectApiKeys:
    """Test list_project_api_keys calls sp_list_project_api_keys."""

    def test_calls_correct_stored_procedure(self):
        from src.Util.db.db_api_keys import list_project_api_keys
        cols = ["id", "name"]
        row = ("key-1", "Key 1")
        mock_conn, mock_cursor = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            list_project_api_keys("proj-1", limit=10, offset=0, active_only=True)
        mock_cursor.callproc.assert_called_once_with("sp_list_project_api_keys", ["proj-1", 10, 0, True])

    def test_returns_tuple_of_keys_and_total(self):
        from src.Util.db.db_api_keys import list_project_api_keys
        mock_conn, mock_cursor = _make_mock_cursor()
        # Configure for new implementation: fetchall + nextset pattern
        mock_cursor.description = [("id",), ("name",), ("public_id",)]
        mock_cursor.fetchall.return_value = [
            ("key-1", "Key 1", "abc123"),
            ("key-2", "Key 2", "def456"),
            ("key-3", "Key 3", "ghi789"),
        ]
        mock_cursor.nextset.side_effect = [True, False]
        mock_cursor.fetchone.return_value = (3,)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            keys, total = list_project_api_keys("proj-1")
        assert isinstance(keys, list)
        assert total == 3


class TestUpdateApiKey:
    """Test update_api_key calls sp_update_api_key and conditionally invalidates cache."""

    def test_calls_correct_stored_procedure(self):
        from src.Util.db.db_api_keys import update_api_key
        cols = ["id", "name"]
        row = ("key-1", "Updated Name")
        mock_conn, mock_cursor = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            update_api_key("key-1", name="Updated Name")
        mock_cursor.callproc.assert_called_once_with("sp_update_api_key", ["key-1", "Updated Name", None, None])

    def test_invalidates_cache_when_expires_at_and_public_id_provided(self):
        from src.Util.db.db_api_keys import update_api_key
        cols = ["id"]
        row = ("key-1",)
        mock_conn, _ = _make_mock_cursor(row, cols)
        new_expiry = datetime(2027, 6, 1, tzinfo=timezone.utc)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn), \
             patch("src.Util.db.db_api_keys.cache_manager") as mock_cache:
            update_api_key("key-1", expires_at=new_expiry, public_id="abc123def456")
        mock_cache.invalidate_api_key.assert_called_once_with("abc123def456")

    def test_does_not_invalidate_cache_when_only_name_changes(self):
        from src.Util.db.db_api_keys import update_api_key
        cols = ["id"]
        row = ("key-1",)
        mock_conn, _ = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn), \
             patch("src.Util.db.db_api_keys.cache_manager") as mock_cache:
            update_api_key("key-1", name="New Name")
        mock_cache.invalidate_api_key.assert_not_called()

    def test_does_not_invalidate_cache_when_expires_at_but_no_public_id(self):
        from src.Util.db.db_api_keys import update_api_key
        cols = ["id"]
        row = ("key-1",)
        mock_conn, _ = _make_mock_cursor(row, cols)
        new_expiry = datetime(2027, 6, 1, tzinfo=timezone.utc)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn), \
             patch("src.Util.db.db_api_keys.cache_manager") as mock_cache:
            update_api_key("key-1", expires_at=new_expiry)
        mock_cache.invalidate_api_key.assert_not_called()


class TestCleanupExpiredKeys:
    """Test cleanup_expired_keys calls sp_cleanup_expired_api_keys."""

    def test_calls_correct_stored_procedure(self):
        from src.Util.db.db_api_keys import cleanup_expired_keys
        cols = ["deactivated_count"]
        row = (3,)
        mock_conn, mock_cursor = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            cleanup_expired_keys()
        mock_cursor.callproc.assert_called_once_with("sp_cleanup_expired_api_keys")

    def test_returns_deactivated_count(self):
        from src.Util.db.db_api_keys import cleanup_expired_keys
        cols = ["deactivated_count"]
        row = (3,)
        mock_conn, _ = _make_mock_cursor(row, cols)
        with patch("src.Util.db.db_api_keys.get_connection", return_value=mock_conn):
            result = cleanup_expired_keys()
        assert result == 3


class TestHandleDbOperationErrorWrapping:
    """Test that handle_db_operation error wrapping is applied."""

    def test_create_api_key_wraps_db_errors(self):
        from src.Util.db.db_api_keys import create_api_key
        from src.Util.error_handler import InternalError

        with patch("src.Util.db.db_api_keys.get_connection", side_effect=Exception("DB connection failed")):
            with pytest.raises(InternalError, match="DB connection failed"):
                create_api_key(
                    key_id="key-1", public_id="abc123def456", project_id="proj-1",
                    owner_user_id="usr-1", created_by="usr-2", name="Test Key",
                    description=None, secret_hash=b"\x00" * 32,
                    hash_algorithm="hmac-sha256-v1", fingerprint="a1b2c3d4e5f6",
                    secret_last4="xyz9", expires_at=datetime(2027, 1, 1, tzinfo=timezone.utc),
                )

    def test_validate_api_key_lookup_wraps_db_errors(self):
        from src.Util.db.db_api_keys import validate_api_key_lookup
        from src.Util.error_handler import InternalError

        with patch("src.Util.db.db_api_keys.get_connection", side_effect=Exception("DB error")):
            with pytest.raises(InternalError, match="DB error"):
                validate_api_key_lookup("abc123def456")
