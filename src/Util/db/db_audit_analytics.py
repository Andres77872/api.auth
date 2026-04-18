"""
API Audit Analytics Database Functions

Provides database functions for querying and analyzing API audit logs.
Wraps stored procedures from 07_sessions_analytics.sql with handle_db_operation error wrapping.
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

from src.Util.db_config import get_connection
from src.Util.db_error_wrapper import handle_db_operation

# Configure logging
logger = logging.getLogger(__name__)


# =================== AUDIT LOGS ===================

def get_audit_logs(
    limit: int = 50,
    offset: int = 0,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    http_method: Optional[str] = None,
    status_code: Optional[int] = None,
    is_success: Optional[bool] = None,
    security_event: Optional[bool] = None,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """
    Get paginated, filtered API audit logs.

    Args:
        limit: Maximum number of results (default 50)
        offset: Number of results to skip (default 0)
        user_id: Filter by user ID
        project_id: Filter by project ID
        endpoint_path: Filter by endpoint path (partial match)
        http_method: Filter by HTTP method
        status_code: Filter by response status code
        is_success: Filter by success/failure
        security_event: Filter by security event flag
        days: Number of days to look back (default 30)

    Returns:
        List of audit log dictionaries with enriched fields
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_audit_logs', [
                limit,
                offset,
                user_id,
                project_id,
                endpoint_path,
                http_method,
                status_code,
                is_success,
                security_event,
                days,
            ])

            columns = [
                'id', 'request_id', 'http_method', 'endpoint_path', 'route_pattern',
                'user_id', 'user_type', 'session_id',
                'request_body', 'request_query', 'request_size_bytes',
                'response_status', 'response_body', 'response_size_bytes',
                'request_timestamp', 'response_timestamp', 'duration_ms',
                'client_ip', 'user_agent', 'referer',
                'is_success', 'error_code', 'error_message',
                'project_id', 'target_resource_type', 'target_resource_id',
                'metadata', 'tags', 'security_event',
                'username', 'user_hash',
                'project_name', 'project_hash',
            ]

            results = cur.fetchall()
            logs = []
            for row in results:
                log = {}
                for i, col in enumerate(columns):
                    log[col] = row[i] if i < len(row) else None
                logs.append(log)

            return logs

    return handle_db_operation(
        _get,
        error_context=f"get_audit_logs(limit={limit}, offset={offset}, days={days})",
        default_return=[],
    )


def count_audit_logs(
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    http_method: Optional[str] = None,
    status_code: Optional[int] = None,
    is_success: Optional[bool] = None,
    security_event: Optional[bool] = None,
    days: int = 30,
) -> int:
    """
    Count API audit logs matching filters.

    Returns:
        Integer count of matching logs
    """
    def _count():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_count_audit_logs', [
                user_id,
                project_id,
                endpoint_path,
                http_method,
                status_code,
                is_success,
                security_event,
                days,
            ])

            row = cur.fetchone()
            return row[0] if row else 0

    return handle_db_operation(
        _count,
        error_context=f"count_audit_logs(days={days})",
        default_return=0,
    )


# =================== AUDIT STATISTICS ===================

def get_audit_statistics(days: int = 7) -> Dict[str, Any]:
    """
    Get comprehensive audit statistics.

    Calls sp_get_audit_statistics which returns 4 result sets:
    1. Overview (total requests, success/failure rates, duration stats)
    2. By method (grouped by HTTP method)
    3. Top endpoints (most-hit endpoints, up to 20)
    4. Status distribution (grouped by status code)

    Returns:
        Dict with keys: overview, by_method, top_endpoints, status_distribution
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_audit_statistics', [days])

            # Result set 1: Overview
            overview_row = cur.fetchone()
            overview = {}
            if overview_row:
                overview = {
                    'total_requests': overview_row[0] or 0,
                    'successful_requests': overview_row[1] or 0,
                    'failed_requests': overview_row[2] or 0,
                    'success_rate': round((overview_row[1] or 0) / max(overview_row[0] or 1, 1) * 100, 2),
                    'avg_duration_ms': round(float(overview_row[3] or 0), 2),
                    'max_duration_ms': overview_row[4] or 0,
                    'avg_request_size': round(float(overview_row[5] or 0), 2),
                    'avg_response_size': round(float(overview_row[6] or 0), 2),
                }

            cur.nextset()

            # Result set 2: By method
            by_method_rows = cur.fetchall()
            by_method = []
            for row in by_method_rows:
                by_method.append({
                    'http_method': row[0],
                    'request_count': row[1],
                    'avg_duration_ms': round(float(row[2] or 0), 2),
                })

            cur.nextset()

            # Result set 3: Top endpoints
            top_endpoints_rows = cur.fetchall()
            top_endpoints = []
            for row in top_endpoints_rows:
                top_endpoints.append({
                    'endpoint_path': row[0],
                    'request_count': row[1],
                    'avg_duration_ms': round(float(row[2] or 0), 2),
                    'success_count': row[3] or 0,
                    'failure_count': row[4] or 0,
                })

            cur.nextset()

            # Result set 4: Status distribution
            status_dist_rows = cur.fetchall()
            status_distribution = []
            for row in status_dist_rows:
                status_distribution.append({
                    'response_status': row[0],
                    'count': row[1],
                })

            return {
                'overview': overview,
                'by_method': by_method,
                'top_endpoints': top_endpoints,
                'status_distribution': status_distribution,
            }

    return handle_db_operation(
        _get,
        error_context=f"get_audit_statistics(days={days})",
        default_return={
            'overview': {
                'total_requests': 0, 'successful_requests': 0, 'failed_requests': 0,
                'success_rate': 0.0, 'avg_duration_ms': 0.0, 'max_duration_ms': 0,
                'avg_request_size': 0.0, 'avg_response_size': 0.0,
            },
            'by_method': [],
            'top_endpoints': [],
            'status_distribution': [],
        },
    )


# =================== SECURITY EVENTS ===================

def get_security_events(
    limit: int = 100,
    offset: int = 0,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """
    Get security events from api_audit_log (security_event=TRUE).

    Returns:
        List of security event dictionaries
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_security_events', [limit, offset, days])

            columns = [
                'id', 'request_id', 'http_method', 'endpoint_path',
                'user_id', 'user_type', 'client_ip',
                'response_status', 'error_code', 'error_message',
                'request_timestamp', 'duration_ms',
                'tags', 'metadata',
                'username', 'user_hash',
            ]

            results = cur.fetchall()
            events = []
            for row in results:
                event = {}
                for i, col in enumerate(columns):
                    event[col] = row[i] if i < len(row) else None
                events.append(event)

            return events

    return handle_db_operation(
        _get,
        error_context=f"get_security_events(limit={limit}, offset={offset}, days={days})",
        default_return=[],
    )


# =================== FAILED REQUESTS ===================

def get_failed_requests(
    limit: int = 50,
    offset: int = 0,
    days: int = 7,
) -> List[Dict[str, Any]]:
    """
    Get failed API requests from api_audit_log.

    Returns:
        List of failed request dictionaries
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_failed_requests', [limit, offset, days])

            columns = [
                'id', 'request_id', 'http_method', 'endpoint_path',
                'user_id', 'user_type', 'client_ip',
                'response_status', 'error_code', 'error_message',
                'request_timestamp', 'duration_ms',
                'username',
            ]

            results = cur.fetchall()
            requests = []
            for row in results:
                req = {}
                for i, col in enumerate(columns):
                    req[col] = row[i] if i < len(row) else None
                requests.append(req)

            return requests

    return handle_db_operation(
        _get,
        error_context=f"get_failed_requests(limit={limit}, offset={offset}, days={days})",
        default_return=[],
    )


# =================== USER API ACTIVITY SUMMARY ===================

def get_user_api_activity_summary(
    user_id: str,
    days: int = 30,
) -> Dict[str, Any]:
    """
    Get user activity summary from api_audit_log.

    Calls sp_get_user_api_activity_summary which returns 2 result sets:
    1. Summary (total requests, success/failure, unique endpoints, time range)
    2. Endpoint activity breakdown (grouped by endpoint + method)

    Returns:
        Dict with keys: summary (single row dict), endpoint_activity (list of dicts)
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_user_api_activity_summary', [user_id, days])

            # Result set 1: Summary
            summary_row = cur.fetchone()
            summary = {}
            if summary_row:
                summary = {
                    'total_requests': summary_row[0] or 0,
                    'successful_requests': summary_row[1] or 0,
                    'failed_requests': summary_row[2] or 0,
                    'unique_endpoints': summary_row[3] or 0,
                    'first_request': summary_row[4],
                    'last_request': summary_row[5],
                    'avg_duration_ms': round(float(summary_row[6] or 0), 2),
                }

            cur.nextset()

            # Result set 2: Endpoint activity
            endpoint_rows = cur.fetchall()
            endpoint_activity = []
            for row in endpoint_rows:
                endpoint_activity.append({
                    'endpoint_path': row[0],
                    'http_method': row[1],
                    'request_count': row[2],
                    'last_access': row[3],
                })

            return {
                'summary': summary,
                'endpoint_activity': endpoint_activity,
            }

    return handle_db_operation(
        _get,
        error_context=f"get_user_api_activity_summary(user_id={user_id}, days={days})",
        default_return={
            'summary': {
                'total_requests': 0, 'successful_requests': 0, 'failed_requests': 0,
                'unique_endpoints': 0, 'first_request': None, 'last_request': None,
                'avg_duration_ms': 0.0,
            },
            'endpoint_activity': [],
        },
    )
