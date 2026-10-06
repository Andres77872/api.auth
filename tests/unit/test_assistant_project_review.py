"""Regression coverage for database contract defects found in assistant review."""
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from src.Util.db import db_project_groups, db_projects
from src.Util.error_handler import ValidationError


def _connection(monkeypatch, module, cursor):
    con = MagicMock()
    con.cursor.return_value = cursor
    manager = MagicMock()
    manager.__enter__.return_value = con
    monkeypatch.setattr(module, "get_connection", lambda: manager)
    return con


def test_project_group_update_matches_three_argument_canonical_procedure(monkeypatch):
    cursor = Mock()
    cursor.nextset.side_effect = [True, False]
    con = _connection(monkeypatch, db_project_groups, cursor)
    expected = SimpleNamespace(group_name="Renamed")
    monkeypatch.setattr(db_project_groups, "get_project_group_by_id", lambda group_id: expected)
    result = db_project_groups.update_project_group("pg-1", "Renamed", "Description")
    cursor.callproc.assert_called_once_with("sp_update_project_group", ["pg-1", "Renamed", "Description"])
    con.commit.assert_called_once()
    assert result is expected


def test_project_group_update_does_not_silently_drop_unsupported_permissions():
    with pytest.raises(TypeError):
        db_project_groups.update_project_group("pg-1", permissions=["admin"])


def test_project_statistics_follow_canonical_three_result_sets(monkeypatch):
    cursor = Mock()
    cursor.fetchall.side_effect = [
        [("prj-1", "Example", "Description", "owner-1", False)],
        [("Editors", 8), ("Viewers", 15)],
    ]
    cursor.fetchone.return_value = (20, 2, 3)
    cursor.nextset.side_effect = [True, True, True, False]
    _connection(monkeypatch, db_projects, cursor)
    result = db_projects.get_project_stats("prj-1")
    assert result == {
        "total_users": 20, "total_groups": 2,
        "total_project_groups": 3, "group_distribution": {"Editors": 8, "Viewers": 15},
    }
    cursor.callproc.assert_called_once_with("sp_get_project_statistics", ["prj-1"])
    assert cursor.nextset.call_count == 4


def test_project_statistics_preserve_zero_counts_and_empty_distribution(monkeypatch):
    cursor = Mock()
    cursor.fetchall.side_effect = [[("prj-empty", "Empty", None, None, False)], []]
    cursor.fetchone.return_value = (0, 0, 0)
    cursor.nextset.side_effect = [True, True, False]
    _connection(monkeypatch, db_projects, cursor)
    result = db_projects.get_project_stats("prj-empty")
    assert result["total_users"] == 0
    assert result["group_distribution"] == {}
    assert "active_sessions" not in result
