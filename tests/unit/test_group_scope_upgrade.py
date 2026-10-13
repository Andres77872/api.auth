"""Migration safety checks that must pass before opening a deployment connection."""
from copy import deepcopy
from unittest.mock import MagicMock

import pytest

from scripts.migrations import group_scope_upgrade as migration


def test_canonical_plan_replaces_exactly_the_required_lock_triggers():
    statements, definitions = migration.load_plan()
    assert len(definitions) == 19
    assert len(statements) == 38
    assert definitions.keys() == migration.EXPECTED_TRIGGERS.keys()
    assert not any(sql.startswith("USE ") for sql in statements)


@pytest.mark.parametrize("sql", [
    "DELETE FROM user_groups;", "USE another_database;",
    "DROP TRIGGER IF EXISTS trg_unrelated;",
    "DROP TRIGGER IF EXISTS trg_group_scope_user_groups_insert;",
    "CREATE TRIGGER trg_group_scope_user_groups_insert AFTER INSERT ON user_groups FOR EACH ROW BEGIN SELECT 1; END;",
])
def test_plan_rejects_data_writes_wrong_targets_and_partial_replacements(tmp_path, monkeypatch, sql):
    source = tmp_path / "migration.sql"
    source.write_text(sql)
    monkeypatch.setattr(migration, "TRIGGERS", source)
    with pytest.raises(ValueError):
        migration.load_plan()


def test_target_mismatch_never_connects(monkeypatch, capsys):
    connect = MagicMock()
    monkeypatch.setattr(migration, "_connect", connect)
    monkeypatch.setattr(migration, "_db_config", lambda: {"host": "other", "database": "magic_auth"})
    assert migration.main(["--expected-host", "192.168.1.90"]) == 1
    connect.assert_not_called()
    assert "ValueError" in capsys.readouterr().err


@pytest.mark.parametrize("extra", [[], ["--processes-stopped"], ["--backup-dir", "/unused"]])
def test_apply_requires_downtime_and_private_backup(monkeypatch, extra):
    connect = MagicMock()
    monkeypatch.setattr(migration, "_connect", connect)
    with pytest.raises(SystemExit):
        migration.main(["--expected-host", "192.168.1.90", "--apply", *extra])
    connect.assert_not_called()


def sample_evidence():
    return {"tables": {name: [{"id": name, "updated_at": "unchanged", "is_active": 1}]
                       for name in (*migration.GROUP_TABLES, *migration.EDGE_TABLES)},
            "table_definitions": {name: "unchanged" for name in migration.EDGE_TABLES}}


def test_binding_additions_preserve_existing_rows():
    before = sample_evidence()
    after = deepcopy(before)
    for table in migration.GROUP_TABLES:
        after["tables"][table][0]["scope_project_id"] = "A"
    migration.verify_preserved_rows(before, after)


def test_existing_timestamp_triggers_may_update_only_backfilled_groups():
    before = sample_evidence()
    after = deepcopy(before)
    after["tables"]["user_groups"][0].update(scope_project_id="A", updated_at="changed")
    migration.verify_preserved_rows(before, after)


def test_dry_run_never_executes_ddl_or_writes(monkeypatch, capsys):
    connection = MagicMock()
    cursor = connection.cursor.return_value.__enter__.return_value
    cursor.fetchone.return_value = {"db": "magic_auth", "server": "test", "version": "8", "uuid": "test"}
    monkeypatch.setattr(migration, "_db_config", lambda: {"host": "test", "database": "magic_auth"})
    monkeypatch.setattr(migration, "_connect", lambda: connection)
    monkeypatch.setattr(migration, "inventory", lambda _: {})
    assert migration.main(["--expected-host", "test"]) == 0
    statements = [call.args[0] for call in cursor.execute.call_args_list]
    assert not any(sql.startswith(("CREATE ", "DROP ", "ALTER ", "INSERT ", "UPDATE ", "DELETE ")) for sql in statements)
    assert '"applied": false' in capsys.readouterr().out
    connection.close.assert_called_once()


@pytest.mark.parametrize("table,field,value", [
    ("user_group_project_groups", "project_group_id", "foreign"),
    ("project_group_members", "project_id", "foreign"),
    ("user_group_members", "is_active", 0),
    ("user_groups", "updated_at", "changed"),
])
def test_verification_rejects_changed_data_even_when_counts_match(table, field, value):
    before = sample_evidence()
    after = deepcopy(before)
    after["tables"][table][0][field] = value
    with pytest.raises(ValueError, match="data or access relationships changed"):
        migration.verify_preserved_rows(before, after)


def test_verification_preserves_existing_binding():
    before = sample_evidence()
    before["tables"]["user_groups"][0]["scope_project_id"] = "A"
    after = deepcopy(before)
    after["tables"]["user_groups"][0]["scope_project_id"] = "B"
    with pytest.raises(ValueError, match="binding changed"):
        migration.verify_preserved_rows(before, after)
