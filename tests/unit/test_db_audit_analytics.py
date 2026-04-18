"""Unit tests for src/Util/db/db_audit_analytics.py.

Tests each DB wrapper function with mocked cursors, verifying callproc args
and result parsing. Multi-result-set handling is tested explicitly.
"""

from unittest.mock import MagicMock, patch
from datetime import datetime, timezone

import pytest

from src.Util.db.db_audit_analytics import (
    get_audit_logs,
    count_audit_logs,
    get_audit_statistics,
    get_security_events,
    get_failed_requests,
    get_user_api_activity_summary,
)


def _make_mock_cursor(fetchall_rows=None, fetchone_row=None, nextset_return=None):
    """Create a mock cursor with configurable fetch behavior."""
    cur = MagicMock()
    cur.fetchall.return_value = fetchall_rows or []
    cur.fetchone.return_value = fetchone_row
    cur.nextset.return_value = nextset_return
    return cur


def _make_mock_connection(cursor):
    """Create a mock connection context manager."""
    conn = MagicMock()
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    conn.cursor.return_value = cursor
    return conn


# ─── get_audit_logs ─────────────────────────────────────────────────────────

class TestGetAuditLogs:
    @patch("src.Util.db.db_audit_analytics.get_connection")
    def test_calls_sp_with_correct_args(self, mock_get_conn):
        cur = _make_mock_cursor(fetchall_rows=[])
        conn = _make_mock_connection(cur)
        mock_get_conn.return_value = conn

        result = get_audit_logs(limit=100, offset=10, days=7)

        cur.callproc.assert_called_once()
        call_args = cur.callproc.call_args[0]
        assert call_args[0] == "sp_get_audit_logs"
        params = call_args[1]
        assert params[0] == 100   # limit
        assert params[1] == 10    # offset
        assert params[9] == 7     # days
        assert result == []

    @patch("src.Util.db.db_audit_analytics.get_connection")
    def test_parses_rows_to_dicts(self, mock_get_conn):
        row = (
            "audit-1", "req-1", "GET", "/admin/users", "/admin/users",
            "usr-1", "admin", "sess-1",
            None, None, 0,
            200, None, 1024,
            datetime(2026, 4, 16, tzinfo=timezone.utc),
            datetime(2026, 4, 16, tzinfo=timezone.utc), 45,
            "192.168.1.1", "Mozilla/5.0", None,
            True, None, None,
            "proj-1", None, None,
            None, ["get", "success"], False,
            "adminuser", "usr-hash-1",
            "Test Project", "prj-hash-1",
        )
        cur = _make_mock_cursor(fetchall_rows=[row])
        conn = _make_mock_connection(cur)
        mock_get_conn.return_value = conn

        result = get_audit_logs()

        assert len(result) == 1
        assert result[0]["id"] == "audit-1"
        assert result[0]["http_method"] == "GET"
        assert result[0]["username"] == "adminuser"
        assert result[0]["project_name"] == "Test Project"


# ─── count_audit_logs ───────────────────────────────────────────────────────

class TestCountAuditLogs:
    @patch("src.Util.db.db_audit_analytics.get_connection")
    def test_returns_count(self, mock_get_conn):
        cur = _make_mock_cursor(fetchone_row=(42,))
        conn = _make_mock_connection(cur)
        mock_get_conn.return_value = conn

        result = count_audit_logs(days=7)

        cur.callproc.assert_called_once_with("sp_count_audit_logs", [
            None, None, None, None, None, None, None, 7,
        ])
        assert result == 42

    @patch("src.Util.db.db_audit_analytics.get_connection")
    def test_returns_zero_on_no_row(self, mock_get_conn):
        cur = _make_mock_cursor(fetchone_row=None)
        conn = _make_mock_connection(cur)
        mock_get_conn.return_value = conn

        result = count_audit_logs()
        assert result == 0


# ─── get_audit_statistics (multi-result-set) ────────────────────────────────

class TestGetAuditStatistics:
    @patch("src.Util.db.db_audit_analytics.get_connection")
    def test_handles_4_result_sets(self, mock_get_conn):
        cur = MagicMock()
        cur.fetchone.return_value = (15000, 14200, 800, 45.2, 2340, 1024, 4096)
        cur.fetchall.side_effect = [
            # Result set 2: by_method
            [("GET", 12000, 30.5), ("POST", 2500, 85.1)],
            # Result set 3: top_endpoints
            [("/auth/login", 5000, 120, 4800, 200)],
            # Result set 4: status_distribution
            [(200, 13000), (401, 500)],
        ]
        cur.nextset.return_value = True

        conn = _make_mock_connection(cur)
        mock_get_conn.return_value = conn

        result = get_audit_statistics(days=7)

        assert "overview" in result
        assert result["overview"]["total_requests"] == 15000
        assert result["overview"]["success_rate"] == pytest.approx(94.67, rel=0.1)

        assert len(result["by_method"]) == 2
        assert result["by_method"][0]["http_method"] == "GET"

        assert len(result["top_endpoints"]) == 1
        assert result["top_endpoints"][0]["endpoint_path"] == "/auth/login"

        assert len(result["status_distribution"]) == 2
        assert result["status_distribution"][0]["response_status"] == 200

        # Verify nextset was called 3 times (between 4 result sets)
        assert cur.nextset.call_count == 3

    @patch("src.Util.db.db_audit_analytics.get_connection")
    def test_returns_zeroed_on_empty(self, mock_get_conn):
        cur = MagicMock()
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        cur.nextset.return_value = False

        conn = _make_mock_connection(cur)
        mock_get_conn.return_value = conn

        result = get_audit_statistics()

        # When fetchone returns None, overview dict is empty (no exception raised)
        assert result["overview"] == {}
        assert result["by_method"] == []
        assert result["top_endpoints"] == []
        assert result["status_distribution"] == []


# ─── get_security_events ────────────────────────────────────────────────────

class TestGetSecurityEvents:
    @patch("src.Util.db.db_audit_analytics.get_connection")
    def test_calls_correct_sp(self, mock_get_conn):
        cur = _make_mock_cursor(fetchall_rows=[])
        conn = _make_mock_connection(cur)
        mock_get_conn.return_value = conn

        get_security_events(limit=50, offset=0, days=1)

        cur.callproc.assert_called_once_with("sp_get_security_events", [50, 0, 1])


# ─── get_failed_requests ────────────────────────────────────────────────────

class TestGetFailedRequests:
    @patch("src.Util.db.db_audit_analytics.get_connection")
    def test_calls_correct_sp(self, mock_get_conn):
        cur = _make_mock_cursor(fetchall_rows=[])
        conn = _make_mock_connection(cur)
        mock_get_conn.return_value = conn

        get_failed_requests(limit=25, offset=0, days=7)

        cur.callproc.assert_called_once_with("sp_get_failed_requests", [25, 0, 7])


# ─── get_user_api_activity_summary (multi-result-set) ───────────────────────

class TestGetUserApiActivitySummary:
    @patch("src.Util.db.db_audit_analytics.get_connection")
    def test_handles_2_result_sets(self, mock_get_conn):
        cur = MagicMock()
        cur.fetchone.return_value = (500, 480, 20, 25,
                                      datetime(2026, 4, 1, tzinfo=timezone.utc),
                                      datetime(2026, 4, 16, tzinfo=timezone.utc),
                                      45.2)
        cur.fetchall.return_value = [
            ("/auth/login", "POST", 50, datetime(2026, 4, 16, tzinfo=timezone.utc)),
            ("/admin/users", "GET", 30, datetime(2026, 4, 15, tzinfo=timezone.utc)),
        ]
        cur.nextset.return_value = True

        conn = _make_mock_connection(cur)
        mock_get_conn.return_value = conn

        result = get_user_api_activity_summary(user_id="usr-123", days=30)

        assert "summary" in result
        assert result["summary"]["total_requests"] == 500
        assert result["summary"]["successful_requests"] == 480
        assert result["summary"]["unique_endpoints"] == 25

        assert "endpoint_activity" in result
        assert len(result["endpoint_activity"]) == 2
        assert result["endpoint_activity"][0]["endpoint_path"] == "/auth/login"

        # Verify nextset was called once (between 2 result sets)
        cur.nextset.assert_called_once()

    @patch("src.Util.db.db_audit_analytics.get_connection")
    def test_returns_zeroed_on_empty(self, mock_get_conn):
        cur = MagicMock()
        cur.fetchone.return_value = None
        cur.fetchall.return_value = []
        cur.nextset.return_value = False

        conn = _make_mock_connection(cur)
        mock_get_conn.return_value = conn

        result = get_user_api_activity_summary(user_id="usr-123")

        # When fetchone returns None, summary dict is empty (no exception raised)
        assert result["summary"] == {}
        assert result["endpoint_activity"] == []
