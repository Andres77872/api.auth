"""
Audit Log Monitor API Routes

Provides HTTP API surface for the Magic Auth Dashboard's audit-log monitor feature,
exposing both logging systems (activity_logs and api_audit_log) as queryable,
filterable, and exportable endpoints.

All endpoints require root or admin user type with global scope.
"""

import csv
import io
import json
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Depends, Query, Request
from fastapi.responses import StreamingResponse
from fastapi.security import HTTPAuthorizationCredentials

from src.Util.Seccurity import HTTPBearerOrCookie
from src.Util.decorators import log_and_handle_errors
from src.Util.log_context_models import LogContext
from src.Util.error_handler import AuthorizationError, ErrorCode, NotFoundError, ValidationError
from src.Util.db import is_root_user, get_user_type, get_user_by_id
from src.Util.db.db_audit_analytics import (
    get_audit_logs,
    count_audit_logs,
    get_audit_statistics,
    get_security_events,
    get_user_api_activity_summary,
)
from src.Util.activity_logger import (
    get_recent_activity,
    count_activity_logs,
    get_activity_by_id,
    get_recent_security_events as get_activity_security_events,
)
from src.Util.audit_export import (
    EXPORT_HARD_LIMIT,
    validate_export_request,
    stream_csv_export,
    stream_json_export,
    _check_export_count,
)

logger = logging.getLogger(__name__)

# Create router with /admin prefix (coexists with admin_dashboard.py)
router = APIRouter(prefix="/admin", tags=["Audit Logs"])
security = HTTPBearerOrCookie()


# =================== HELPER: Admin Auth Check ===================

def _check_admin_access(log_context: LogContext) -> None:
    """
    Verify the current user is root or admin.
    Raises AuthorizationError for consumer users.
    """
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)

    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED,
        )


# =================== HELPER: Severity Derivation ===================

def _derive_severity_from_status(status_code: Optional[int]) -> str:
    """
    Derive security event severity from HTTP status code.

    Mapping:
        401 -> warning
        403 -> critical
        5xx -> warning
        4xx (other) -> info
        2xx/3xx -> info
    """
    if status_code is None:
        return "info"
    if status_code == 401:
        return "warning"
    if status_code == 403:
        return "critical"
    if 500 <= status_code < 600:
        return "warning"
    return "info"


def _derive_event_type_from_audit_log(audit_entry: Dict[str, Any]) -> str:
    """Derive event_type from api_audit_log tags or error_code."""
    error_code = audit_entry.get("error_code")
    if error_code:
        return str(error_code)

    tags = audit_entry.get("tags")
    if tags:
        if isinstance(tags, str):
            try:
                tags = json.loads(tags)
            except (json.JSONDecodeError, TypeError):
                pass
        if isinstance(tags, list) and tags:
            # Return the most relevant tag (prefer security-related)
            for tag in tags:
                tag_str = str(tag).lower()
                if "security" in tag_str or "auth" in tag_str or "unauthorized" in tag_str:
                    return str(tag)
            return str(tags[0])

    return "api_event"


# =================== GET /admin/audit/logs ===================

@router.get("/audit/logs")
@log_and_handle_errors(
    operation_name="get_audit_logs",
    activity_type=None,  # Read-only, no activity logging needed
    log_success=False,
)
async def list_audit_logs(
    limit: int = Query(50, ge=1, le=1000, description="Number of logs to return"),
    offset: int = Query(0, ge=0, description="Number of logs to skip"),
    user_id: Optional[str] = Query(None, description="Filter by user ID"),
    project_id: Optional[str] = Query(None, description="Filter by project ID"),
    endpoint_path: Optional[str] = Query(None, description="Filter by endpoint path (partial match)"),
    http_method: Optional[str] = Query(None, description="Filter by HTTP method"),
    status_code: Optional[int] = Query(None, description="Filter by response status code"),
    is_success: Optional[bool] = Query(None, description="Filter by success/failure"),
    security_event: Optional[bool] = Query(None, description="Filter by security event flag"),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """
    Get paginated, filtered API audit logs from the api_audit_log table.
    """
    _check_admin_access(log_context)

    # Validate limit range
    if limit < 1 or limit > 1000:
        raise ValidationError(
            message="Limit must be between 1 and 1000",
            error_code=ErrorCode.INVALID_RANGE,
        )

    logs = get_audit_logs(
        limit=limit,
        offset=offset,
        user_id=user_id,
        project_id=project_id,
        endpoint_path=endpoint_path,
        http_method=http_method,
        status_code=status_code,
        is_success=is_success,
        security_event=security_event,
        days=days,
    )

    total_count = count_audit_logs(
        user_id=user_id,
        project_id=project_id,
        endpoint_path=endpoint_path,
        http_method=http_method,
        status_code=status_code,
        is_success=is_success,
        security_event=security_event,
        days=days,
    )

    has_more = (offset + limit) < total_count
    next_offset = offset + limit if has_more else None

    return {
        "logs": logs,
        "pagination": {
            "total": total_count,
            "limit": limit,
            "offset": offset,
            "has_more": has_more,
            "next_offset": next_offset,
        },
        "filters": {
            "user_id": user_id,
            "project_id": project_id,
            "endpoint_path": endpoint_path,
            "http_method": http_method,
            "status_code": status_code,
            "is_success": is_success,
            "security_event": security_event,
            "days": days,
        },
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


# =================== GET /admin/audit/security-events ===================

@router.get("/audit/security-events")
@log_and_handle_errors(
    operation_name="get_security_events",
    activity_type=None,
    log_success=False,
)
async def list_security_events(
    limit: int = Query(100, ge=1, le=500, description="Maximum events to return"),
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    severity: Optional[str] = Query(None, description="Filter by severity (critical/warning)"),
    source: Optional[str] = Query(None, description="Filter by source (api_audit/activity_log)"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """
    Get combined security events from both api_audit_log and activity_logs,
    normalized to a common shape with source indicator.
    """
    _check_admin_access(log_context)

    events: List[Dict[str, Any]] = []

    # Fetch from api_audit_log (unless source filter excludes it)
    if source is None or source == "api_audit":
        api_events = get_security_events(
            limit=limit,
            offset=0,
            days=days,
        )
        for entry in api_events:
            sev = _derive_severity_from_status(entry.get("response_status"))

            # Apply severity filter
            if severity and sev != severity:
                continue

            events.append({
                "id": entry.get("id"),
                "source": "api_audit",
                "timestamp": entry.get("request_timestamp"),
                "severity": sev,
                "event_type": _derive_event_type_from_audit_log(entry),
                "user_id": entry.get("user_id"),
                "username": entry.get("username"),
                "client_ip": entry.get("client_ip"),
                "endpoint_path": entry.get("endpoint_path"),
                "http_method": entry.get("http_method"),
                "response_status": entry.get("response_status"),
                "error_code": entry.get("error_code"),
                "error_message": entry.get("error_message"),
                "duration_ms": entry.get("duration_ms"),
            })

    # Fetch from activity_logs (unless source filter excludes it)
    if source is None or source == "activity_log":
        hours = days * 24
        activity_events = get_activity_security_events(p_hours=hours, p_limit=limit)
        for entry in activity_events:
            sev = entry.get("severity_level", "info")

            # Apply severity filter
            if severity and sev != severity:
                continue

            events.append({
                "id": entry.get("id"),
                "source": "activity_log",
                "timestamp": entry.get("created_at"),
                "severity": sev,
                "event_type": entry.get("activity_type"),
                "user_id": entry.get("user_id"),
                "username": entry.get("username"),
                "client_ip": entry.get("ip_address"),
                "details": entry.get("details"),
                "activity_name": entry.get("activity_name"),
            })

    # Sort by timestamp descending
    def _sort_key(e: Dict[str, Any]) -> Any:
        ts = e.get("timestamp")
        if ts is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if isinstance(ts, datetime):
            return ts
        return ts  # string comparison fallback

    events.sort(key=_sort_key, reverse=True)

    # Apply limit to the final merged result (spec: limit is on total merged events)
    events = events[:limit]

    # Compute summary
    total = len(events)
    by_source = {"api_audit": 0, "activity_log": 0}
    by_severity: Dict[str, int] = {}

    for e in events:
        src = e.get("source", "unknown")
        if src in by_source:
            by_source[src] += 1

        sev = e.get("severity", "info")
        by_severity[sev] = by_severity.get(sev, 0) + 1

    return {
        "events": events,
        "summary": {
            "total": total,
            "by_source": by_source,
            "by_severity": by_severity,
            "period_hours": days * 24,
        },
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


# =================== GET /admin/audit/statistics ===================

@router.get("/audit/statistics")
@log_and_handle_errors(
    operation_name="get_audit_statistics",
    activity_type=None,
    log_success=False,
)
async def get_statistics(
    days: int = Query(7, ge=1, le=365, description="Days to look back"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """
    Get audit statistics from sp_get_audit_statistics.
    Returns 4 sections: overview, by_method, top_endpoints, status_distribution.
    """
    _check_admin_access(log_context)

    # Validate days range
    if days < 1 or days > 365:
        raise ValidationError(
            message="Days must be between 1 and 365",
            error_code=ErrorCode.INVALID_RANGE,
        )

    stats = get_audit_statistics(days=days)

    return {
        "overview": stats.get("overview", {}),
        "by_method": stats.get("by_method", []),
        "top_endpoints": stats.get("top_endpoints", []),
        "status_distribution": stats.get("status_distribution", []),
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }


# =================== POST /admin/audit/export ===================

@router.post("/audit/export")
@log_and_handle_errors(
    operation_name="export_audit_logs",
    activity_type=None,
    log_success=False,
)
async def export_logs(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> StreamingResponse:
    """
    Export activity logs or API audit logs in CSV or JSON format.
    Enforces hard limit of 10,000 records.
    """
    _check_admin_access(log_context)

    # Parse request body
    try:
        body = await request.json()
    except Exception:
        raise ValidationError(
            message="Invalid JSON body",
            error_code=ErrorCode.INVALID_INPUT,
        )

    source = body.get("source")
    fmt = body.get("format")
    limit = body.get("limit")
    filters = body.get("filters", {}) or {}

    # Validate required fields
    if not source:
        raise ValidationError(
            message="Missing required field: source",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
        )

    if not fmt:
        raise ValidationError(
            message="Missing required field: format",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
        )

    # Validate export parameters
    is_valid, error_msg, effective_limit = validate_export_request(source, fmt, limit)
    if not is_valid:
        if "source" in error_msg.lower() or "format" in error_msg.lower():
            raise ValidationError(
                message=error_msg,
                error_code=ErrorCode.INVALID_ENUM_VALUE,
            )
        raise ValidationError(
            message=error_msg,
            error_code=ErrorCode.INVALID_RANGE,
        )

    # Check if total count exceeds hard limit
    total_count = _check_export_count(source, filters, effective_limit)
    if total_count > EXPORT_HARD_LIMIT:
        raise ValidationError(
            message=f"Export would return {total_count} records, exceeding the hard limit of {EXPORT_HARD_LIMIT}",
            error_code=ErrorCode.INVALID_RANGE,
        )

    # Generate filename
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"audit_export_{source}_{timestamp}.{fmt}"

    # Stream the export
    if fmt == "csv":
        return StreamingResponse(
            stream_csv_export(source, filters, effective_limit),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )
    else:  # json
        return StreamingResponse(
            stream_json_export(source, filters, effective_limit),
            media_type="application/json",
            headers={"Content-Disposition": f"attachment; filename={filename}"},
        )


# =================== GET /admin/users/{user_id}/activity ===================

@router.get("/users/{user_id}/activity")
@log_and_handle_errors(
    operation_name="get_user_activity",
    activity_type=None,
    log_success=False,
)
async def get_user_activity(
    user_id: str,
    days: int = Query(30, ge=1, le=365, description="Days to look back"),
    credentials: HTTPAuthorizationCredentials = Depends(security),
    log_context: LogContext = None,
) -> Dict[str, Any]:
    """
    Get combined user activity summary and timeline from both
    activity_logs and api_audit_log sources.
    """
    _check_admin_access(log_context)

    # Check user exists
    user = get_user_by_id(user_id)
    if not user:
        raise NotFoundError(
            message=f"User not found: {user_id}",
            error_code=ErrorCode.USER_NOT_FOUND,
        )

    # Fetch activity log summary (from 11_activity_logging.sql)
    activity_summary_data = get_recent_activity(
        limit=500,
        offset=0,
        user_id=user_id,
        days=days,
    )

    # Build activity summary by category
    activity_by_category: Dict[str, Dict[str, Any]] = {}
    for entry in activity_summary_data:
        cat = entry.get("activity_category", "unknown")
        name = entry.get("activity_name", "unknown")
        key = f"{cat}::{name}"
        if key not in activity_by_category:
            activity_by_category[key] = {
                "activity_category": cat,
                "activity_name": name,
                "count": 0,
                "last_activity": None,
            }
        activity_by_category[key]["count"] += 1
        ts = entry.get("created_at")
        if ts and (activity_by_category[key]["last_activity"] is None or ts > activity_by_category[key]["last_activity"]):
            activity_by_category[key]["last_activity"] = ts

    activity_summary_list = list(activity_by_category.values())
    activity_summary_list.sort(key=lambda x: x["count"], reverse=True)

    # Fetch API audit summary (from 07_sessions_analytics.sql, renamed SP)
    api_summary_data = get_user_api_activity_summary(user_id=user_id, days=days)
    api_summary = api_summary_data.get("summary", {})
    api_endpoint_activity = api_summary_data.get("endpoint_activity", [])

    # Fetch recent API audit log entries for the timeline (individual events, not aggregates)
    api_audit_timeline_entries = get_audit_logs(
        limit=50,
        offset=0,
        user_id=user_id,
        days=days,
    )

    # Build combined timeline
    timeline: List[Dict[str, Any]] = []

    # Add activity log entries to timeline
    for entry in activity_summary_data[:50]:  # Limit timeline entries
        ts = entry.get("created_at")
        timeline.append({
            "source": "activity_log",
            "id": entry.get("id"),
            "timestamp": ts,
            "activity_type": entry.get("activity_type"),
            "activity_name": entry.get("activity_name"),
            "details": entry.get("details"),
            "severity_level": entry.get("severity_level"),
            "project_id": entry.get("project_id"),
            "ip_address": entry.get("ip_address"),
        })

    # Add API audit entries to timeline — use individual log entries with spec-required fields
    for entry in api_audit_timeline_entries[:50]:
        ts = entry.get("request_timestamp")
        timeline.append({
            "source": "api_audit",
            "id": entry.get("id"),
            "timestamp": ts,
            "http_method": entry.get("http_method"),
            "endpoint_path": entry.get("endpoint_path"),
            "response_status": entry.get("response_status"),
            "is_success": entry.get("is_success"),
            "duration_ms": entry.get("duration_ms"),
            "client_ip": entry.get("client_ip"),
        })

    # Sort timeline by timestamp descending
    def _timeline_sort_key(e: Dict[str, Any]) -> Any:
        ts = e.get("timestamp")
        if ts is None:
            return datetime.min.replace(tzinfo=timezone.utc)
        if isinstance(ts, datetime):
            return ts
        return ts

    timeline.sort(key=_timeline_sort_key, reverse=True)

    total_activities = len(activity_summary_data) + api_summary.get("total_requests", 0)

    return {
        "user_id": user_id,
        "summary": {
            "total_activities": total_activities,
            "activity_log_count": len(activity_summary_data),
            "api_audit_count": api_summary.get("total_requests", 0),
            "activity_summary": activity_summary_list,
            "api_audit_summary": api_summary,
        },
        "timeline": timeline,
        "generated_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
