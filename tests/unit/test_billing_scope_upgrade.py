"""The narrow migration must fail closed before any unrelated DDL or data change."""
from unittest.mock import MagicMock

import pytest

from scripts.migrations import billing_provider_bootstrap as bootstrap
from scripts.migrations import billing_scope_upgrade as upgrade


def test_canonical_upgrade_contains_only_replaced_billing_definitions():
    statements, objects = upgrade.load_plan()
    assert len([kind for kind, _ in objects if kind == "PROCEDURE"]) == 23
    assert len([kind for kind, _ in objects if kind == "TRIGGER"]) == 31
    assert all(sql.startswith(("USE ", "SET ", "CREATE PROCEDURE ", "DROP PROCEDURE ",
                               "CREATE TRIGGER ", "DROP TRIGGER ")) for sql in statements)


@pytest.mark.parametrize("sql", ["DELETE FROM billing_purchase_events;", "DROP TABLE billing_customers;",
                               "DROP PROCEDURE IF EXISTS sp_unrelated;",
                               "DROP PROCEDURE IF EXISTS sp_billing_old;", "USE another_database;"])
def test_plan_rejects_data_writes_unrelated_objects_and_unreplaced_drops(tmp_path, monkeypatch, sql):
    source = tmp_path / "migration.sql"
    source.write_text(sql)
    monkeypatch.setattr(upgrade, "SQL_FILES", (source,))
    with pytest.raises(ValueError):
        upgrade.load_plan()


def test_target_mismatch_never_connects(monkeypatch, capsys):
    connect = MagicMock()
    monkeypatch.setattr(upgrade, "_connect", connect)
    monkeypatch.setattr(upgrade, "_db_config", lambda: {"host": "other", "database": "magic_auth"})
    assert upgrade.main(["--expected-host", "192.168.1.90"]) == 1
    connect.assert_not_called()
    assert "ValueError" in capsys.readouterr().err


def test_apply_requires_explicit_downtime_and_backup_before_connecting(monkeypatch):
    connect = MagicMock()
    monkeypatch.setattr(upgrade, "_connect", connect)
    with pytest.raises(SystemExit):
        upgrade.main(["--expected-host", "192.168.1.90", "--apply"])
    connect.assert_not_called()


def test_dry_run_never_executes_replacement_definitions(monkeypatch, capsys):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"acquired": 1}
    monkeypatch.setattr(upgrade, "_db_config", lambda: {"host": "test", "database": "magic_auth"})
    monkeypatch.setattr(upgrade, "_connect", lambda: connection)
    monkeypatch.setattr(upgrade, "inventory", lambda _: {"definitions": {}, "tables": {}})
    monkeypatch.setattr(upgrade, "audit", lambda _: {"read_only": True, "checks": {}})
    assert upgrade.main(["--expected-host", "test"]) == 0
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert not any(sql.startswith(("CREATE ", "DROP ", "INSERT ", "UPDATE ", "DELETE ")) for sql in statements)
    assert '"applied": false' in capsys.readouterr().out
    connection.close.assert_called_once()


def test_verification_rejects_changed_data_even_with_matching_row_counts():
    before = {"tables": {"billing_customers": {"count": 1, "checksum": 1}}}
    after = {"tables": {"billing_customers": {"count": 1, "checksum": 2}}}
    with pytest.raises(ValueError, match="data changed"):
        upgrade.verify(MagicMock(), before, after, {})


def test_verification_rejects_incorrect_billing_definition():
    before = {"tables": {}, "definitions": {}}
    after = {"tables": {}, "definitions": {"PROCEDURE:sp_billing_test": {
        "Create Procedure": "CREATE PROCEDURE sp_billing_test() BEGIN SELECT 1; END"}}}
    with pytest.raises(ValueError, match="definition verification failed"):
        upgrade.verify(MagicMock(), before, after, {("PROCEDURE", "sp_billing_test"): "BEGIN SELECT 2; END"})


@pytest.mark.parametrize("parameter_count", [8, 11])
def test_readiness_checks_the_deployed_resolver_signature(monkeypatch, parameter_count):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchall.side_effect = [
        [{"table_name": name} for name in bootstrap.REQUIRED_TABLES],
        [{"routine_name": name} for name in bootstrap.REQUIRED_PROCEDURES],
    ]
    cursor.fetchone.return_value = {"parameter_count": parameter_count}
    monkeypatch.setattr(bootstrap, "_connect", lambda: connection)
    if parameter_count == 8:
        with pytest.raises(bootstrap.BootstrapError, match="eleven parameters"):
            bootstrap._check_db_readiness()
    else:
        assert bootstrap._check_db_readiness() == (len(bootstrap.REQUIRED_TABLES), len(bootstrap.REQUIRED_PROCEDURES))
