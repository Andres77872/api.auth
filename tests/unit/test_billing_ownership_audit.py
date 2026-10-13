"""The operational audit must remain read-only and redact connection errors."""
from unittest.mock import MagicMock

import pytest

from scripts.migrations import billing_ownership_audit as audit_module


def test_audit_uses_read_only_transaction_and_never_commits():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"total": 0}
    cursor.fetchall.return_value = []
    report = audit_module.audit(connection)
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert statements[:2] == ["SET TRANSACTION READ ONLY", "START TRANSACTION WITH CONSISTENT SNAPSHOT"]
    assert all(sql.lstrip().upper().startswith("SELECT ") for sql in statements[2:])
    connection.commit.assert_not_called()
    connection.rollback.assert_called_once()
    assert report["read_only"] is True
    assert all(check["count"] == 0 for check in report["checks"].values())


def test_audit_rolls_back_even_when_a_read_fails():
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.execute.side_effect = [None, None, RuntimeError("read failed")]
    with pytest.raises(RuntimeError):
        audit_module.audit(connection)
    connection.rollback.assert_called_once()
    connection.commit.assert_not_called()


def test_cli_redacts_connection_failures(monkeypatch, capsys):
    def fail():
        raise RuntimeError("password=private-provider-secret host=private-host")
    monkeypatch.setattr(audit_module, "_connect", fail)
    assert audit_module.main([]) == 1
    output = capsys.readouterr()
    assert "RuntimeError" in output.err
    assert "private" not in output.err and not output.out
