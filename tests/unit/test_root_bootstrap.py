"""The first root account requires an operator password and an Argon2id hash."""

from unittest.mock import MagicMock

import pytest

from scripts import bootstrap_root_user as bootstrap
from src.Util.error_handler import ValidationError
from src.Util.password_security import verify_password


PASSWORD = "Q7!vZr9#Lx2@mP8$"


def _connection(existing=0):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = (existing,)
    return connection, cursor


def test_bootstrap_stores_an_argon2id_hash_and_never_plaintext():
    connection, cursor = _connection()
    assert bootstrap.bootstrap_root_user(connection, password=PASSWORD)
    _, parameters = cursor.execute.call_args.args
    stored_hash = parameters[2]
    assert stored_hash.startswith("$argon2id$")
    assert verify_password(PASSWORD, stored_hash)
    assert PASSWORD not in str(cursor.execute.call_args)
    connection.commit.assert_called_once()


def test_bootstrap_does_not_replace_an_existing_root():
    connection, cursor = _connection(existing=1)
    assert not bootstrap.bootstrap_root_user(connection, password=PASSWORD)
    assert cursor.execute.call_count == 1
    connection.commit.assert_not_called()


def test_bootstrap_rejects_a_weak_operator_password_before_database_access():
    connection, _ = _connection()
    with pytest.raises(ValidationError):
        bootstrap.bootstrap_root_user(connection, password="short")
    connection.cursor.assert_not_called()


def test_operator_environment_password_avoids_interactive_input(monkeypatch):
    monkeypatch.setenv("BOOTSTRAP_ROOT_PASSWORD", PASSWORD)
    prompt = MagicMock(side_effect=AssertionError("unexpected interactive prompt"))
    monkeypatch.setattr(bootstrap.getpass, "getpass", prompt)
    assert bootstrap.read_root_password() == PASSWORD
    prompt.assert_not_called()
