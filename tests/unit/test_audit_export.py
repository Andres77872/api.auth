"""Unit tests for src/Util/audit_export.py.

Tests export validation, CSV formatting, JSON formatting, and limit enforcement.
"""

import pytest

from src.Util.audit_export import (
    EXPORT_HARD_LIMIT,
    EXPORT_DEFAULT_LIMIT,
    validate_export_request,
    _format_value,
    _serialize_value,
)


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
        from datetime import datetime, timezone
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
        from datetime import datetime, timezone
        dt = datetime(2026, 4, 16, 12, 0, 0, tzinfo=timezone.utc)
        result = _serialize_value(dt)
        assert isinstance(result, str)
        assert "2026-04-16" in result
