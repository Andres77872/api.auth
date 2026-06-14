"""RED DB-wrapper contract tests for authenticated password change.

Trace: `.dev/sdd/changes/password-recovery-email-validation/tasks.md` task 1.2.
"""

from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest


USER_ID = "usr-contract-001"
CURRENT_PASSWORD = "current-contract-candidate-2026"
NEW_PASSWORD = "new contract passphrase with spaces"
STORED_HASH = "$argon2id$stored-contract-hash"
NEW_HASH = "$argon2id$new-contract-hash"


class _Row(dict):
    """Dict row that also tolerates tuple-style index access."""

    def __getitem__(self, item):
        if item == 0:
            return self.get("password_hash") or self.get("rows_affected")
        if item == 1:
            return self.get("is_active")
        return super().__getitem__(item)


def _connection_with_rows(*rows):
    conn = MagicMock()
    cursor = MagicMock()
    cursor.fetchone.side_effect = list(rows)
    cursor.fetchall.return_value = []
    cursor.nextset.return_value = None
    cursor.__enter__ = MagicMock(return_value=cursor)
    cursor.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cursor


def _call_change_user_password(db_users):
    return db_users.change_user_password(
        user_id=USER_ID,
        current_password=CURRENT_PASSWORD,
        new_password=NEW_PASSWORD,
        username="contract-user",
        email="contract.user@example.test",
    )


def test_change_user_password_locks_current_hash_verifies_hashes_and_commits_after_success():
    from src.Util.db import db_users

    conn, cursor = _connection_with_rows(
        _Row(password_hash=STORED_HASH, is_active=True),
        _Row(rows_affected=1),
    )
    cache = MagicMock()

    with patch("src.Util.db.db_users.get_connection", return_value=conn), \
         patch("src.Util.db.db_users.verify_password", return_value=True) as verify_password, \
         patch("src.Util.db.db_users.hash_password", return_value=NEW_HASH) as hash_password, \
         patch("src.Util.db.db_users.cache_manager", cache):
        result = _call_change_user_password(db_users)

    executed_sql = "\n".join(
        str(call.args[0]) for call in cursor.execute.call_args_list if call.args
    ).upper()
    assert "FOR UPDATE" in executed_sql
    assert "PASSWORD_HASH" in executed_sql
    verify_password.assert_called_once_with(CURRENT_PASSWORD, STORED_HASH)
    hash_password.assert_called_once_with(NEW_PASSWORD)
    cursor.callproc.assert_called_once_with(
        "sp_change_user_password_if_hash_matches",
        [USER_ID, STORED_HASH, NEW_HASH],
    )
    conn.commit.assert_called_once()
    conn.rollback.assert_not_called()
    cache.invalidate_user_cache.assert_called_once_with(USER_ID)
    assert result["password_changed"] is True


def test_change_user_password_rolls_back_wrong_current_password_without_hashing_or_cache_invalidation():
    from src.Util.db import db_users

    conn, cursor = _connection_with_rows(_Row(password_hash=STORED_HASH, is_active=True))
    cache = MagicMock()

    with patch("src.Util.db.db_users.get_connection", return_value=conn), \
         patch("src.Util.db.db_users.verify_password", return_value=False), \
         patch("src.Util.db.db_users.hash_password") as hash_password, \
         patch("src.Util.db.db_users.cache_manager", cache):
        with pytest.raises(Exception) as exc_info:
            _call_change_user_password(db_users)

    assert "invalid" in repr(exc_info.value).lower() or "credential" in repr(exc_info.value).lower()
    hash_password.assert_not_called()
    cursor.callproc.assert_not_called()
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()
    cache.invalidate_user_cache.assert_not_called()


@pytest.mark.parametrize(
    "row",
    [
        None,
        _Row(password_hash=STORED_HASH, is_active=False),
    ],
)
def test_change_user_password_fails_closed_for_missing_or_inactive_user(row):
    from src.Util.db import db_users

    conn, cursor = _connection_with_rows(row)

    with patch("src.Util.db.db_users.get_connection", return_value=conn), \
         patch("src.Util.db.db_users.verify_password") as verify_password, \
         patch("src.Util.db.db_users.hash_password") as hash_password:
        with pytest.raises(Exception):
            _call_change_user_password(db_users)

    verify_password.assert_not_called()
    hash_password.assert_not_called()
    cursor.callproc.assert_not_called()
    conn.rollback.assert_called_once()
    conn.commit.assert_not_called()


def test_change_user_password_logs_no_plaintext_password_material(caplog):
    from src.Util.db import db_users

    assert hasattr(db_users, "change_user_password")
    conn, _cursor = _connection_with_rows(_Row(password_hash=STORED_HASH, is_active=True))

    with caplog.at_level(logging.INFO), \
         patch("src.Util.db.db_users.get_connection", return_value=conn), \
         patch("src.Util.db.db_users.verify_password", return_value=False):
        with pytest.raises(Exception):
            _call_change_user_password(db_users)

    log_text = caplog.text
    assert CURRENT_PASSWORD not in log_text
    assert NEW_PASSWORD not in log_text
    assert STORED_HASH not in log_text
    assert NEW_HASH not in log_text
