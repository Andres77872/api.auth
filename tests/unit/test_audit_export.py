"""Unit tests for src/Util/audit_export.py.

Tests export validation, CSV formatting, JSON formatting, and limit enforcement.
"""

import csv
import io
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import pytest

from src.Util.audit_export import (
    EXPORT_DEFAULT_LIMIT,
    EXPORT_HARD_LIMIT,
    _check_export_count,
    _fetch_export_data,
    validate_export_request,
    _format_value,
    _serialize_value,
    stream_csv_export,
    stream_json_export,
)


AUDIT_COLUMNS = [
    "id", "request_id", "http_method", "endpoint_path", "route_pattern",
    "user_id", "user_type", "username", "user_hash",
    "project_id", "project_name", "project_hash",
    "request_timestamp", "response_timestamp", "duration_ms",
    "response_status", "is_success", "error_code", "error_message",
    "client_ip", "user_agent", "security_event", "tags",
]

ACTIVITY_COLUMNS = [
    "id", "user_id", "activity_type", "details", "project_id",
    "target_user_id", "ip_address", "user_agent",
    "severity_level", "created_at",
    "username", "user_hash", "project_name", "project_hash",
    "target_username", "target_user_hash",
    "activity_name", "activity_category", "activity_description",
]


async def _collect_stream(stream):
    return [chunk async for chunk in stream]


# ─── validate_export_request ────────────────────────────────────────────────

class TestValidateExportRequest:
    def test_valid_activity_csv(self):
        is_valid, msg, limit = validate_export_request("activity", "csv")
        assert is_valid is True
        assert msg == ""
        assert limit == EXPORT_DEFAULT_LIMIT

    def test_valid_audit_json(self):
        is_valid, msg, limit = validate_export_request("audit", "json")
        assert is_valid is True
        assert limit == EXPORT_DEFAULT_LIMIT

    def test_valid_api_audit_source(self):
        """Regression: spec-defined source 'api_audit' must be accepted (verify issue 2.1)."""
        is_valid, msg, limit = validate_export_request("api_audit", "json")
        assert is_valid is True
        assert limit == EXPORT_DEFAULT_LIMIT

    def test_valid_api_audit_csv(self):
        is_valid, msg, limit = validate_export_request("api_audit", "csv", limit=500)
        assert is_valid is True
        assert limit == 500

    def test_valid_with_custom_limit(self):
        is_valid, msg, limit = validate_export_request("audit", "json", limit=500)
        assert is_valid is True
        assert limit == 500

    def test_valid_with_max_limit(self):
        is_valid, msg, limit = validate_export_request("audit", "json", limit=EXPORT_HARD_LIMIT)
        assert is_valid is True
        assert limit == EXPORT_HARD_LIMIT

    def test_invalid_source(self):
        is_valid, msg, limit = validate_export_request("unknown", "json")
        assert is_valid is False
        assert "Invalid source" in msg
        assert limit == 0

    def test_empty_source(self):
        is_valid, msg, limit = validate_export_request("", "json")
        assert is_valid is False
        assert limit == 0

    def test_invalid_format(self):
        is_valid, msg, limit = validate_export_request("audit", "xml")
        assert is_valid is False
        assert "Invalid format" in msg
        assert limit == 0

    def test_limit_exceeds_hard_limit(self):
        is_valid, msg, limit = validate_export_request("audit", "json", limit=15000)
        assert is_valid is False
        assert "exceeds maximum" in msg
        assert limit == 0

    def test_limit_zero(self):
        is_valid, msg, limit = validate_export_request("audit", "json", limit=0)
        assert is_valid is False
        assert limit == 0

    def test_limit_negative(self):
        is_valid, msg, limit = validate_export_request("audit", "json", limit=-1)
        assert is_valid is False
        assert limit == 0

    def test_none_source(self):
        is_valid, msg, limit = validate_export_request(None, "json")  # type: ignore
        assert is_valid is False

    def test_none_format(self):
        is_valid, msg, limit = validate_export_request("audit", None)  # type: ignore
        assert is_valid is False


# ─── _format_value (CSV) ────────────────────────────────────────────────────

class TestFormatValue:
    def test_none_returns_empty(self):
        assert _format_value(None) == ""

    def test_string_passthrough(self):
        assert _format_value("hello") == "hello"

    def test_integer(self):
        assert _format_value(42) == "42"

    def test_dict_serialized(self):
        result = _format_value({"key": "value"})
        assert '"key"' in result
        assert '"value"' in result

    def test_list_serialized(self):
        result = _format_value(["a", "b"])
        assert "a" in result
        assert "b" in result

    def test_datetime_isoformat(self):
        dt = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
        result = _format_value(dt)
        assert "2026-04-16" in result
        assert "Z" in result


# ─── _serialize_value (JSON) ────────────────────────────────────────────────

class TestSerializeValue:
    def test_string_passthrough(self):
        assert _serialize_value("hello") == "hello"

    def test_integer_passthrough(self):
        assert _serialize_value(42) == 42

    def test_none_passthrough(self):
        assert _serialize_value(None) is None

    def test_datetime_to_isoformat(self):
        dt = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
        result = _serialize_value(dt)
        assert isinstance(result, str)
        assert "2026-04-16" in result


# ─── _fetch_export_data routing ─────────────────────────────────────────────

class TestFetchExportData:
    @pytest.mark.parametrize("source", ["audit", "api_audit"])
    @patch("src.Util.db.db_audit_analytics.get_audit_logs")
    def test_audit_sources_forward_every_supported_filter(
        self,
        get_audit_logs,
        source,
    ):
        rows = [{"id": "audit-1"}]
        get_audit_logs.return_value = rows
        filters = {
            "user_id": "usr-1",
            "project_id": "project-1",
            "endpoint_path": "/admin/audit",
            "http_method": "POST",
            "status_code": 403,
            "is_success": False,
            "security_event": True,
            "days": 14,
            "ignored": "not-forwarded",
        }

        result = _fetch_export_data(source, filters, limit=87)

        assert result is rows
        get_audit_logs.assert_called_once_with(
            limit=87,
            offset=0,
            user_id="usr-1",
            project_id="project-1",
            endpoint_path="/admin/audit",
            http_method="POST",
            status_code=403,
            is_success=False,
            security_event=True,
            days=14,
        )

    @patch("src.Util.db.db_audit_analytics.get_audit_logs")
    def test_audit_source_supplies_filter_defaults(self, get_audit_logs):
        get_audit_logs.return_value = []

        assert _fetch_export_data("audit", {}, limit=5) == []
        get_audit_logs.assert_called_once_with(
            limit=5,
            offset=0,
            user_id=None,
            project_id=None,
            endpoint_path=None,
            http_method=None,
            status_code=None,
            is_success=None,
            security_event=None,
            days=30,
        )

    @patch("src.Util.activity_logger.get_recent_activity")
    def test_activity_source_forwards_only_activity_filters(
        self,
        get_recent_activity,
    ):
        rows = [{"id": "activity-1"}]
        get_recent_activity.return_value = rows
        filters = {
            "user_id": "usr-2",
            "project_id": "project-2",
            "activity_type": "user_login",
            "days": 7,
            "endpoint_path": "not-forwarded",
        }

        result = _fetch_export_data("activity", filters, limit=41)

        assert result is rows
        get_recent_activity.assert_called_once_with(
            limit=41,
            offset=0,
            user_id="usr-2",
            project_id="project-2",
            activity_type="user_login",
            days=7,
        )

    @patch("src.Util.activity_logger.get_recent_activity")
    def test_activity_source_supplies_filter_defaults(self, get_recent_activity):
        get_recent_activity.return_value = []

        assert _fetch_export_data("activity", {}, limit=3) == []
        get_recent_activity.assert_called_once_with(
            limit=3,
            offset=0,
            user_id=None,
            project_id=None,
            activity_type=None,
            days=30,
        )

    @patch(
        "src.Util.activity_logger.get_recent_activity",
        side_effect=AssertionError("activity DB adapter must not be called"),
    )
    @patch(
        "src.Util.db.db_audit_analytics.get_audit_logs",
        side_effect=AssertionError("audit DB adapter must not be called"),
    )
    def test_unknown_source_returns_empty_without_calling_an_adapter(
        self,
        get_audit_logs,
        get_recent_activity,
    ):
        assert _fetch_export_data("unknown", {"days": 1}, limit=10) == []
        get_audit_logs.assert_not_called()
        get_recent_activity.assert_not_called()


# ─── _check_export_count routing ────────────────────────────────────────────

class TestCheckExportCount:
    @pytest.mark.parametrize("source", ["audit", "api_audit"])
    @patch("src.Util.db.db_audit_analytics.count_audit_logs")
    def test_audit_sources_forward_every_supported_filter(
        self,
        count_audit_logs,
        source,
    ):
        count_audit_logs.return_value = 23
        filters = {
            "user_id": "usr-1",
            "project_id": "project-1",
            "endpoint_path": "/admin/audit",
            "http_method": "GET",
            "status_code": 200,
            "is_success": True,
            "security_event": False,
            "days": 60,
        }

        result = _check_export_count(source, filters, limit=999)

        assert result == 23
        count_audit_logs.assert_called_once_with(
            user_id="usr-1",
            project_id="project-1",
            endpoint_path="/admin/audit",
            http_method="GET",
            status_code=200,
            is_success=True,
            security_event=False,
            days=60,
        )

    @patch("src.Util.db.db_audit_analytics.count_audit_logs")
    def test_audit_count_supplies_filter_defaults(self, count_audit_logs):
        count_audit_logs.return_value = 0

        assert _check_export_count("audit", {}, limit=1) == 0
        count_audit_logs.assert_called_once_with(
            user_id=None,
            project_id=None,
            endpoint_path=None,
            http_method=None,
            status_code=None,
            is_success=None,
            security_event=None,
            days=30,
        )

    @patch("src.Util.activity_logger.count_activity_logs")
    def test_activity_source_forwards_only_activity_filters(
        self,
        count_activity_logs,
    ):
        count_activity_logs.return_value = 17
        filters = {
            "user_id": "usr-2",
            "project_id": "project-2",
            "activity_type": "user_logout",
            "days": 2,
            "status_code": "not-forwarded",
        }

        result = _check_export_count("activity", filters, limit=500)

        assert result == 17
        count_activity_logs.assert_called_once_with(
            user_id="usr-2",
            project_id="project-2",
            activity_type="user_logout",
            days=2,
        )

    @patch("src.Util.activity_logger.count_activity_logs")
    def test_activity_count_supplies_filter_defaults(self, count_activity_logs):
        count_activity_logs.return_value = 0

        assert _check_export_count("activity", {}, limit=1) == 0
        count_activity_logs.assert_called_once_with(
            user_id=None,
            project_id=None,
            activity_type=None,
            days=30,
        )

    @patch(
        "src.Util.activity_logger.count_activity_logs",
        side_effect=AssertionError("activity DB adapter must not be called"),
    )
    @patch(
        "src.Util.db.db_audit_analytics.count_audit_logs",
        side_effect=AssertionError("audit DB adapter must not be called"),
    )
    def test_unknown_source_defaults_to_zero_without_calling_an_adapter(
        self,
        count_audit_logs,
        count_activity_logs,
    ):
        assert _check_export_count("unknown", {"days": 1}, limit=10) == 0
        count_audit_logs.assert_not_called()
        count_activity_logs.assert_not_called()


# ─── async streaming ────────────────────────────────────────────────────────

class TestStreamCsvExport:
    @pytest.mark.asyncio
    @patch("src.Util.audit_export._fetch_export_data", return_value=[])
    async def test_empty_export_yields_one_blank_csv_record(
        self,
        fetch_export_data,
    ):
        filters = {"days": 3}

        chunks = await _collect_stream(
            stream_csv_export("activity", filters, limit=10)
        )

        assert chunks == ["\r\n"]
        fetch_export_data.assert_called_once_with("activity", filters, 10)

    @pytest.mark.asyncio
    @pytest.mark.parametrize("source", ["audit", "api_audit"])
    @patch("src.Util.audit_export._fetch_export_data")
    async def test_audit_export_yields_header_and_formatted_rows(
        self,
        fetch_export_data,
        source,
    ):
        timestamp = datetime(2026, 7, 25, 10, 30, tzinfo=timezone.utc)
        fetch_export_data.return_value = [
            {
                "id": "audit-1",
                "request_id": "request,with-comma",
                "http_method": "GET",
                "request_timestamp": timestamp,
                "is_success": True,
                "tags": {"security": ["login", "success"]},
            },
            {
                "id": "audit-2",
                "http_method": "POST",
                "request_timestamp": None,
                "is_success": False,
            },
        ]
        filters = {"security_event": True}

        chunks = await _collect_stream(
            stream_csv_export(source, filters, limit=2)
        )
        records = list(csv.reader(io.StringIO("".join(chunks))))

        assert len(chunks) == 3
        assert records[0] == AUDIT_COLUMNS
        first = dict(zip(AUDIT_COLUMNS, records[1]))
        assert first["id"] == "audit-1"
        assert first["request_id"] == "request,with-comma"
        assert first["request_timestamp"] == "2026-07-25T10:30:00Z"
        assert first["is_success"] == "True"
        assert json.loads(first["tags"]) == {"security": ["login", "success"]}
        second = dict(zip(AUDIT_COLUMNS, records[2]))
        assert second["id"] == "audit-2"
        assert second["request_timestamp"] == ""
        fetch_export_data.assert_called_once_with(source, filters, 2)

    @pytest.mark.asyncio
    @patch("src.Util.audit_export._fetch_export_data")
    async def test_activity_export_uses_activity_columns(
        self,
        fetch_export_data,
    ):
        created_at = datetime(2026, 7, 25, 9, 15, tzinfo=timezone.utc)
        fetch_export_data.return_value = [
            {
                "id": "activity-1",
                "user_id": "usr-1",
                "activity_type": "user_login",
                "details": {"method": "password"},
                "severity_level": "info",
                "created_at": created_at,
            }
        ]

        chunks = await _collect_stream(
            stream_csv_export("activity", {}, limit=1)
        )
        records = list(csv.reader(io.StringIO("".join(chunks))))

        assert len(chunks) == 2
        assert records[0] == ACTIVITY_COLUMNS
        row = dict(zip(ACTIVITY_COLUMNS, records[1]))
        assert row["id"] == "activity-1"
        assert row["activity_type"] == "user_login"
        assert json.loads(row["details"]) == {"method": "password"}
        assert row["created_at"] == "2026-07-25T09:15:00Z"
        fetch_export_data.assert_called_once_with("activity", {}, 1)


class TestStreamJsonExport:
    @pytest.mark.asyncio
    @patch("src.Util.audit_export._fetch_export_data", return_value=[])
    async def test_empty_export_yields_valid_empty_json_array(
        self,
        fetch_export_data,
    ):
        filters = {"days": 30}

        chunks = await _collect_stream(
            stream_json_export("audit", filters, limit=50)
        )

        assert chunks == ["[", "]"]
        assert json.loads("".join(chunks)) == []
        fetch_export_data.assert_called_once_with("audit", filters, 50)

    @pytest.mark.asyncio
    @patch("src.Util.audit_export._fetch_export_data")
    async def test_non_empty_export_serializes_datetimes_and_comma_separators(
        self,
        fetch_export_data,
    ):
        requested_at = datetime(2026, 7, 25, 10, 30, tzinfo=timezone.utc)
        responded_at = datetime(
            2026,
            7,
            25,
            5,
            30,
            tzinfo=timezone(timedelta(hours=-5)),
        )
        rows = [
            {
                "id": "audit-1",
                "request_timestamp": requested_at,
                "metadata": {"attempt": 1},
            },
            {
                "id": "audit-2",
                "response_timestamp": responded_at,
                "error_code": None,
            },
        ]
        fetch_export_data.return_value = rows
        filters = {"user_id": "usr-1"}

        chunks = await _collect_stream(
            stream_json_export("api_audit", filters, limit=2)
        )
        payload = json.loads("".join(chunks))

        assert chunks[0] == "["
        assert chunks[2] == ","
        assert chunks[-1] == "]"
        assert payload == [
            {
                "id": "audit-1",
                "request_timestamp": "2026-07-25T10:30:00Z",
                "metadata": {"attempt": 1},
            },
            {
                "id": "audit-2",
                "response_timestamp": "2026-07-25T05:30:00-05:00",
                "error_code": None,
            },
        ]
        assert rows[0]["request_timestamp"] is requested_at
        assert rows[1]["response_timestamp"] is responded_at
        fetch_export_data.assert_called_once_with("api_audit", filters, 2)
