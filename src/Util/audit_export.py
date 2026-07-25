"""
Audit Log Export Utility

Provides CSV/JSON export functionality for activity logs and API audit logs
with hard limit enforcement (10,000 rows) and generator-based streaming.
"""

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, AsyncGenerator, Tuple

from src.Util.error_handler import ErrorCode

logger = logging.getLogger(__name__)

# Hard limit for export operations
EXPORT_HARD_LIMIT = 10_000

# Default export limit when not specified
EXPORT_DEFAULT_LIMIT = 1_000

# Valid export sources and formats
# Note: "api_audit" is the spec-defined source name; "audit" is kept for backward compat.
VALID_SOURCES = {"activity", "audit", "api_audit"}
VALID_FORMATS = {"csv", "json"}


def validate_export_request(
    source: str,
    fmt: str,
    limit: Optional[int] = None,
) -> Tuple[bool, str, int]:
    """
    Validate export request parameters.

    Args:
        source: Data source ("activity" or "audit")
        fmt: Output format ("csv" or "json")
        limit: Optional row limit

    Returns:
        Tuple of (is_valid, error_message, effective_limit)
    """
    # Validate source
    if not source or source not in VALID_SOURCES:
        return False, f"Invalid source. Must be one of: {', '.join(sorted(VALID_SOURCES))}", 0

    # Validate format
    if not fmt or fmt not in VALID_FORMATS:
        return False, f"Invalid format. Must be one of: {', '.join(sorted(VALID_FORMATS))}", 0

    # Determine effective limit
    effective_limit = limit if limit is not None else EXPORT_DEFAULT_LIMIT

    # Validate limit against hard cap
    if effective_limit > EXPORT_HARD_LIMIT:
        return (
            False,
            f"Export limit {effective_limit} exceeds maximum of {EXPORT_HARD_LIMIT} records",
            0,
        )

    if effective_limit <= 0:
        return False, "Export limit must be a positive integer", 0

    return True, "", effective_limit


def _fetch_export_data(
    source: str,
    filters: Dict[str, Any],
    limit: int,
) -> list:
    """
    Fetch export data from the appropriate source.

    Args:
        source: "activity" or "audit"
        filters: Filter parameters passed to the stored procedure
        limit: Maximum number of rows to fetch

    Returns:
        List of row dictionaries
    """
    if source in ("audit", "api_audit"):
        from src.Util.db.db_audit_analytics import get_audit_logs

        return get_audit_logs(
            limit=limit,
            offset=0,
            user_id=filters.get("user_id"),
            project_id=filters.get("project_id"),
            endpoint_path=filters.get("endpoint_path"),
            http_method=filters.get("http_method"),
            status_code=filters.get("status_code"),
            is_success=filters.get("is_success"),
            security_event=filters.get("security_event"),
            days=filters.get("days", 30),
        )

    elif source == "activity":
        from src.Util.activity_logger import get_recent_activity

        return get_recent_activity(
            limit=limit,
            offset=0,
            user_id=filters.get("user_id"),
            project_id=filters.get("project_id"),
            activity_type=filters.get("activity_type"),
            days=filters.get("days", 30),
        )

    return []


def _check_export_count(
    source: str,
    filters: Dict[str, Any],
    limit: int,
) -> int:
    """
    Check the total count of records that would match the export filters.

    Returns:
        Count of matching records
    """
    if source in ("audit", "api_audit"):
        from src.Util.db.db_audit_analytics import count_audit_logs

        return count_audit_logs(
            user_id=filters.get("user_id"),
            project_id=filters.get("project_id"),
            endpoint_path=filters.get("endpoint_path"),
            http_method=filters.get("http_method"),
            status_code=filters.get("status_code"),
            is_success=filters.get("is_success"),
            security_event=filters.get("security_event"),
            days=filters.get("days", 30),
        )

    elif source == "activity":
        from src.Util.activity_logger import count_activity_logs

        return count_activity_logs(
            user_id=filters.get("user_id"),
            project_id=filters.get("project_id"),
            activity_type=filters.get("activity_type"),
            days=filters.get("days", 30),
        )

    return 0


def _format_value(value: Any) -> str:
    """Format a single value for CSV output."""
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value, default=str)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return str(value)


def _serialize_value(value: Any) -> Any:
    """Serialize a value for JSON output."""
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    return value


async def stream_csv_export(
    source: str,
    filters: Dict[str, Any],
    limit: int,
) -> AsyncGenerator[str, None]:
    """
    Generate CSV export rows as a streaming generator.

    Yields CSV header row followed by data rows.

    Args:
        source: "activity" or "audit"
        filters: Filter parameters
        limit: Maximum number of rows

    Yields:
        CSV-formatted string chunks
    """
    data = _fetch_export_data(source, filters, limit)

    if not data:
        # Return empty CSV with just headers
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([])
        yield output.getvalue()
        return

    # Determine columns based on source
    if source in ("audit", "api_audit"):
        columns = [
            "id", "request_id", "http_method", "endpoint_path", "route_pattern",
            "user_id", "user_type", "username", "user_hash",
            "project_id", "project_name", "project_hash",
            "request_timestamp", "response_timestamp", "duration_ms",
            "response_status", "is_success", "error_code", "error_message",
            "client_ip", "user_agent", "security_event", "tags",
        ]
    else:  # activity
        columns = [
            "id", "user_id", "activity_type", "details", "project_id",
            "target_user_id", "ip_address", "user_agent",
            "severity_level", "created_at",
            "username", "user_hash", "project_name", "project_hash",
            "target_username", "target_user_hash",
            "activity_name", "activity_category", "activity_description",
        ]

    # Yield header
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(columns)
    yield output.getvalue()

    # Yield data rows
    for row in data:
        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow([_format_value(row.get(col)) for col in columns])
        yield output.getvalue()


async def stream_json_export(
    source: str,
    filters: Dict[str, Any],
    limit: int,
) -> AsyncGenerator[str, None]:
    """
    Generate JSON export as a streaming generator.

    Yields JSON objects one at a time (JSON Lines format).

    Args:
        source: "activity" or "audit"
        filters: Filter parameters
        limit: Maximum number of rows

    Yields:
        JSON-formatted string chunks
    """
    data = _fetch_export_data(source, filters, limit)

    # Yield opening bracket
    yield "["

    for i, row in enumerate(data):
        # Serialize datetime values
        serialized = {k: _serialize_value(v) for k, v in row.items()}

        # Yield comma separator (not before first item)
        if i > 0:
            yield ","

        yield json.dumps(serialized, default=str)

    # Yield closing bracket
    yield "]"
