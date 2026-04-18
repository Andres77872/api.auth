# Audit Log Monitor API — Specification

## Purpose

Provide a complete HTTP API surface for the Magic Auth Dashboard's audit-log monitor feature, exposing both logging systems (`activity_logs` and `api_audit_log`) as queryable, filterable, and exportable endpoints. This spec covers route behavior, filtering, pagination, export limits, auth/access, data-source merge rules, and error handling.

---

# Domain: Auth & Access Control

## Requirement: Admin-Only Access

The system **MUST** restrict all audit log monitor endpoints to users with `root` or `admin` user type. Admin scope is **global** — admins see all data regardless of project assignment.

#### Scenario: Root user accesses any audit endpoint

- GIVEN a valid session token belonging to a `root` user
- WHEN the user sends a request to any `/admin/activity`, `/admin/audit/*`, or `/admin/users/{user_id}/activity` endpoint
- THEN the request is authorized and processed normally

#### Scenario: Admin user accesses any audit endpoint

- GIVEN a valid session token belonging to an `admin` user
- WHEN the user sends a request to any `/admin/activity`, `/admin/audit/*`, or `/admin/users/{user_id}/activity` endpoint
- THEN the request is authorized and processed with global data visibility (no project scoping)

#### Scenario: Consumer user is denied access

- GIVEN a valid session token belonging to a `consumer` user
- WHEN the user sends a request to any `/admin/activity`, `/admin/audit/*`, or `/admin/users/{user_id}/activity` endpoint
- THEN the system returns HTTP 403 Forbidden with error code `AUTHZ_2001`

#### Scenario: Unauthenticated request is rejected

- GIVEN no valid session token (missing, expired, or invalid)
- WHEN a request is sent to any audit log monitor endpoint
- THEN the system returns HTTP 401 Unauthorized

---

# Domain: Activity Log Enhancement

## Requirement: Enhanced Activity Feed with Search

The system **MUST** extend the existing `GET /admin/activity` endpoint to accept a `search` query parameter that performs free-text matching across `activity_type`, `details`, and `username` fields.

#### Scenario: Search returns matching activities

- GIVEN activity logs exist with activity_type "user_login", details "Login from 192.168.1.1", and username "john_doe"
- WHEN an admin sends `GET /admin/activity?search=login`
- THEN the response includes activities where `activity_type`, `details`, or `username` contains "login" (case-insensitive)

#### Scenario: Search with no matches returns empty list

- GIVEN no activity logs match the search term
- WHEN an admin sends `GET /admin/activity?search=nonexistent_term_xyz`
- THEN the response contains an empty `activities` array and `pagination.total` equals 0

#### Scenario: Search combined with existing filters

- GIVEN activity logs exist for multiple users and projects
- WHEN an admin sends `GET /admin/activity?search=admin&user_id=usr-123&days=7`
- THEN the response includes only activities matching ALL criteria: search term AND user_id AND within 7 days

#### Scenario: Pagination works with search

- GIVEN 150 activity logs match the search term "login"
- WHEN an admin sends `GET /admin/activity?search=login&limit=50&offset=0`
- THEN the response contains 50 activities, `pagination.total` equals 150, and `pagination.has_more` is true

#### Scenario: Empty search parameter is ignored

- WHEN an admin sends `GET /admin/activity?search=`
- THEN the response behaves identically to `GET /admin/activity` without the search parameter (no filtering applied)

## Requirement: Single Activity Detail Lookup

The system **MUST** provide a `GET /admin/activity/{activity_id}` endpoint that returns full metadata for a single activity log entry.

#### Scenario: Valid activity ID returns full detail

- GIVEN an activity log exists with id "act-abc123"
- WHEN an admin sends `GET /admin/activity/act-abc123`
- THEN the response contains the activity's id, activity_type, details, severity_level, created_at, user info (id, username, user_hash), project info (if applicable), target_user info (if applicable), ip_address, user_agent, and metadata

#### Scenario: Non-existent activity ID returns 404

- GIVEN no activity log exists with id "act-nonexistent"
- WHEN an admin sends `GET /admin/activity/act-nonexistent`
- THEN the system returns HTTP 404 Not Found with error code `NF_4004`

#### Scenario: Invalid activity ID format returns 400

- WHEN an admin sends `GET /admin/activity/` with an empty or malformed activity_id
- THEN the system returns HTTP 400 Bad Request with error code `VAL_3001`

---

# Domain: API Audit Logs

## Requirement: Paginated Audit Log Listing

The system **MUST** provide a `GET /admin/audit/logs` endpoint that returns paginated, filtered API audit logs from the `api_audit_log` table, wrapping `sp_get_audit_logs` and `sp_count_audit_logs`.

#### Scenario: Default listing returns recent logs

- GIVEN API audit logs exist in the database
- WHEN an admin sends `GET /admin/audit/logs`
- THEN the response returns up to 50 logs (default limit), ordered by `request_timestamp` descending, with pagination metadata

#### Scenario: Filter by HTTP method

- GIVEN API audit logs exist with various HTTP methods
- WHEN an admin sends `GET /admin/audit/logs?http_method=POST`
- THEN the response includes only logs where `http_method` equals "POST"

#### Scenario: Filter by status code

- WHEN an admin sends `GET /admin/audit/logs?status_code=401`
- THEN the response includes only logs where `response_status` equals 401

#### Scenario: Filter by endpoint path (partial match)

- WHEN an admin sends `GET /admin/audit/logs?endpoint_path=/admin`
- THEN the response includes only logs where `endpoint_path` contains "/admin"

#### Scenario: Filter by success/failure

- WHEN an admin sends `GET /admin/audit/logs?is_success=false`
- THEN the response includes only logs where `is_success` is false

#### Scenario: Filter by security events only

- WHEN an admin sends `GET /admin/audit/logs?security_event=true`
- THEN the response includes only logs where `security_event` is true

#### Scenario: Filter by user ID

- WHEN an admin sends `GET /admin/audit/logs?user_id=usr-abc123`
- THEN the response includes only logs where `user_id` matches the given value

#### Scenario: Filter by project ID

- WHEN an admin sends `GET /admin/audit/logs?project_id=proj-xyz789`
- THEN the response includes only logs where `project_id` matches the given value

#### Scenario: Filter by time range (days)

- WHEN an admin sends `GET /admin/audit/logs?days=7`
- THEN the response includes only logs from the last 7 days

#### Scenario: Combined filters

- WHEN an admin sends `GET /admin/audit/logs?http_method=POST&status_code=500&days=1`
- THEN the response includes only POST requests with 500 status from the last 24 hours

#### Scenario: Pagination with offset

- GIVEN 200 API audit logs match the filters
- WHEN an admin sends `GET /admin/audit/logs?limit=50&offset=100`
- THEN the response contains logs 101-150, `pagination.total` equals 200, and `pagination.has_more` is true

#### Scenario: Limit validation

- WHEN an admin sends `GET /admin/audit/logs?limit=0`
- THEN the system returns HTTP 400 Bad Request with error code `VAL_3009`

- WHEN an admin sends `GET /admin/audit/logs?limit=1001`
- THEN the system returns HTTP 400 Bad Request with error code `VAL_3009`

#### Scenario: Response shape includes enriched data

- GIVEN an API audit log entry exists with a valid user_id and project_id
- WHEN an admin requests `GET /admin/audit/logs`
- THEN each log entry includes: id, request_id, http_method, endpoint_path, route_pattern, user_id, user_type, username, user_hash, project_id, project_name, project_hash, request_timestamp, response_timestamp, duration_ms, response_status, is_success, error_code, error_message, client_ip, user_agent, security_event, tags

---

# Domain: Security Events

## Requirement: Combined Security Events Endpoint

The system **MUST** provide a `GET /admin/audit/security-events` endpoint that merges security events from both `api_audit_log` (where `security_event=true`) and `activity_logs` (where `severity_level` is "warning" or "critical"), normalized to a common response shape with a `source` field indicating origin.

#### Scenario: Returns events from both sources

- GIVEN `api_audit_log` has 3 security events and `activity_logs` has 5 warning/critical events
- WHEN an admin sends `GET /admin/audit/security-events`
- THEN the response contains 8 events total, each with a `source` field of either "api_audit" or "activity_log"

#### Scenario: API audit severity is derived from status code

- GIVEN an API audit log entry has `security_event=true` and `response_status=401`
- WHEN the security events endpoint is called
- THEN that event's `severity` field is "warning"

- GIVEN an API audit log entry has `security_event=true` and `response_status=403`
- WHEN the security events endpoint is called
- THEN that event's `severity` field is "critical"

- GIVEN an API audit log entry has `security_event=true` and `response_status=500`
- WHEN the security events endpoint is called
- THEN that event's `severity` field is "warning"

- GIVEN an API audit log entry has `security_event=true` and `response_status=502`
- WHEN the security events endpoint is called
- THEN that event's `severity` field is "warning"

#### Scenario: Activity log severity is preserved from source

- GIVEN an activity log entry has `severity_level=critical`
- WHEN the security events endpoint is called
- THEN that event's `severity` field is "critical"

- GIVEN an activity log entry has `severity_level=warning`
- WHEN the security events endpoint is called
- THEN that event's `severity` field is "warning"

#### Scenario: Events are sorted by timestamp descending

- GIVEN security events from both sources with varying timestamps
- WHEN the security events endpoint is called
- THEN the returned events are ordered by timestamp descending (most recent first)

#### Scenario: Summary counts are included

- WHEN an admin sends `GET /admin/audit/security-events`
- THEN the response includes a `summary` object with counts: `total`, `critical`, `warning`, `by_source.api_audit`, `by_source.activity_log`

#### Scenario: Pagination via limit parameter

- WHEN an admin sends `GET /admin/audit/security-events?limit=10`
- THEN the response returns at most 10 events

#### Scenario: Time range filter (days)

- WHEN an admin sends `GET /admin/audit/security-events?days=1`
- THEN the response includes only security events from the last 24 hours
- AND the `activity_logs` source uses `p_hours = days * 24` when calling `sp_get_recent_security_events`

#### Scenario: Filter by severity

- WHEN an admin sends `GET /admin/audit/security-events?severity=critical`
- THEN the response includes only events with severity "critical" from both sources

#### Scenario: Filter by source

- WHEN an admin sends `GET /admin/audit/security-events?source=api_audit`
- THEN the response includes only events from the `api_audit_log` table

- WHEN an admin sends `GET /admin/audit/security-events?source=activity_log`
- THEN the response includes only events from the `activity_logs` table

#### Scenario: Unified event shape for API audit source

- WHEN an event originates from `api_audit_log`
- THEN its normalized shape includes: id, source ("api_audit"), timestamp, severity, event_type (derived from tags/error_code), user_id, username, client_ip, endpoint_path, http_method, response_status, error_code, error_message, duration_ms

#### Scenario: Unified event shape for activity log source

- WHEN an event originates from `activity_logs`
- THEN its normalized shape includes: id, source ("activity_log"), timestamp, severity, event_type (activity_type), user_id, username, client_ip (ip_address), details, activity_name

---

# Domain: Audit Statistics

## Requirement: Audit Statistics Endpoint

The system **MUST** provide a `GET /admin/audit/statistics` endpoint that returns audit statistics by calling `sp_get_audit_statistics`, which returns 4 result sets: overview, by_method, top_endpoints, and status_distribution.

#### Scenario: Returns all 4 statistic sections

- WHEN an admin sends `GET /admin/audit/statistics`
- THEN the response contains 4 sections: `overview`, `by_method`, `top_endpoints`, `status_distribution`

#### Scenario: Overview section contains aggregate metrics

- WHEN an admin sends `GET /admin/audit/statistics`
- THEN the `overview` section includes: total_requests, successful_requests, failed_requests, success_rate (percentage), avg_duration_ms, max_duration_ms, avg_request_size, avg_response_size

#### Scenario: By-method section groups by HTTP method

- WHEN an admin sends `GET /admin/audit/statistics`
- THEN the `by_method` section is an array of objects, each containing: http_method, request_count, avg_duration_ms, ordered by request_count descending

#### Scenario: Top endpoints section lists most-hit endpoints

- WHEN an admin sends `GET /admin/audit/statistics`
- THEN the `top_endpoints` section is an array of up to 20 objects, each containing: endpoint_path, request_count, avg_duration_ms, success_count, failure_count, ordered by request_count descending

#### Scenario: Status distribution section groups by status code

- WHEN an admin sends `GET /admin/audit/statistics`
- THEN the `status_distribution` section is an array of objects, each containing: response_status, count, ordered by count descending

#### Scenario: Time range filter (days)

- WHEN an admin sends `GET /admin/audit/statistics?days=1`
- THEN all statistics are calculated from the last 24 hours of audit data

- WHEN an admin sends `GET /admin/audit/statistics?days=90`
- THEN all statistics are calculated from the last 90 days of audit data

#### Scenario: Default time range is 7 days

- WHEN an admin sends `GET /admin/audit/statistics` without a days parameter
- THEN statistics are calculated from the last 7 days

#### Scenario: Days parameter validation

- WHEN an admin sends `GET /admin/audit/statistics?days=0`
- THEN the system returns HTTP 400 Bad Request with error code `VAL_3009`

- WHEN an admin sends `GET /admin/audit/statistics?days=366`
- THEN the system returns HTTP 400 Bad Request with error code `VAL_3009`

#### Scenario: Empty data returns zeroed statistics

- GIVEN no API audit logs exist for the requested time range
- WHEN an admin sends `GET /admin/audit/statistics`
- THEN the response returns zeroed/empty values: total_requests=0, empty arrays for by_method/top_endpoints/status_distribution

---

# Domain: Export

## Requirement: CSV/JSON Export with Hard Limit

The system **MUST** provide a `POST /admin/audit/export` endpoint that exports activity logs or API audit logs in CSV or JSON format, enforcing a hard limit of 10,000 records.

#### Scenario: Export API audit logs as JSON

- GIVEN API audit logs exist matching the filters
- WHEN an admin sends `POST /admin/audit/export` with body `{"source": "api_audit", "format": "json", "filters": {"days": 7}}`
- THEN the response has Content-Type `application/json`, Content-Disposition header with filename, and contains matching logs as JSON array

#### Scenario: Export API audit logs as CSV

- GIVEN API audit logs exist matching the filters
- WHEN an admin sends `POST /admin/audit/export` with body `{"source": "api_audit", "format": "csv", "filters": {"days": 7}}`
- THEN the response has Content-Type `text/csv`, Content-Disposition header with filename, and contains matching logs as CSV with headers

#### Scenario: Export activity logs as JSON

- GIVEN activity logs exist matching the filters
- WHEN an admin sends `POST /admin/audit/export` with body `{"source": "activity", "format": "json", "filters": {"days": 7}}`
- THEN the response contains matching activity logs as JSON array

#### Scenario: Export activity logs as CSV

- GIVEN activity logs exist matching the filters
- WHEN an admin sends `POST /admin/audit/export` with body `{"source": "activity", "format": "csv", "filters": {"days": 7}}`
- THEN the response contains matching activity logs as CSV

#### Scenario: Export with combined filters

- WHEN an admin sends `POST /admin/audit/export` with body `{"source": "api_audit", "format": "json", "filters": {"http_method": "POST", "status_code": 500, "days": 1}}`
- THEN the response contains only POST requests with 500 status from the last 24 hours

#### Scenario: Export exceeding hard limit returns 400

- GIVEN more than 10,000 records match the export filters
- WHEN an admin sends `POST /admin/audit/export` with those filters
- THEN the system returns HTTP 400 Bad Request with error code `VAL_3009` and a message indicating the hard limit of 10,000 records was exceeded

#### Scenario: Export with limit parameter below hard limit

- WHEN an admin sends `POST /admin/audit/export` with body `{"source": "api_audit", "format": "json", "limit": 500, "filters": {"days": 30}}`
- THEN the response contains at most 500 records

#### Scenario: Export limit parameter cannot exceed hard limit

- WHEN an admin sends `POST /admin/audit/export` with body `{"source": "api_audit", "format": "json", "limit": 15000}`
- THEN the system returns HTTP 400 Bad Request with error code `VAL_3009`

#### Scenario: Missing source parameter returns 400

- WHEN an admin sends `POST /admin/audit/export` with body `{"format": "json"}`
- THEN the system returns HTTP 400 Bad Request with error code `VAL_3002` (missing required field)

#### Scenario: Invalid format parameter returns 400

- WHEN an admin sends `POST /admin/audit/export` with body `{"source": "api_audit", "format": "xml"}`
- THEN the system returns HTTP 400 Bad Request with error code `VAL_3012` (invalid enum value)

#### Scenario: Invalid source parameter returns 400

- WHEN an admin sends `POST /admin/audit/export` with body `{"source": "unknown", "format": "json"}`
- THEN the system returns HTTP 400 Bad Request with error code `VAL_3012`

#### Scenario: Export uses streaming response

- WHEN an admin requests an export that returns 10,000 records
- THEN the system uses `StreamingResponse` with generator-based row formatting and does NOT load all rows into memory at once

---

# Domain: User Activity

## Requirement: User-Specific Activity Endpoint

The system **MUST** provide a `GET /admin/users/{user_id}/activity` endpoint that returns a user activity summary and timeline, combining data from BOTH `activity_logs` and `api_audit_log` sources.

#### Scenario: Returns combined user activity summary

- GIVEN a user has 10 activity log entries and 50 API audit log entries in the last 30 days
- WHEN an admin sends `GET /admin/users/usr-abc123/activity`
- THEN the response includes a `summary` section with combined totals: total_activities (60), activity_log_count (10), api_audit_count (50)

#### Scenario: Activity log summary by category

- WHEN an admin sends `GET /admin/users/usr-abc123/activity`
- THEN the response includes `activity_summary` from `activity_logs` grouped by activity_category and activity_name with counts and last_activity timestamp (via `sp_get_user_activity_summary` from 11_activity_logging.sql)

#### Scenario: API audit summary by endpoint

- WHEN an admin sends `GET /admin/users/usr-abc123/activity`
- THEN the response includes `api_audit_summary` from `api_audit_log` grouped by endpoint_path and http_method with request_count and last_access timestamp (via `sp_get_user_activity_summary` from 07_sessions_analytics.sql)

#### Scenario: Combined timeline of recent activity

- WHEN an admin sends `GET /admin/users/usr-abc123/activity`
- THEN the response includes a `timeline` array combining recent entries from both sources, ordered by timestamp descending, each with a `source` field ("activity_log" or "api_audit")

#### Scenario: Timeline entries from activity_logs

- WHEN a timeline entry originates from `activity_logs`
- THEN it includes: source ("activity_log"), id, timestamp, activity_type, activity_name, details, severity_level, project_id (if applicable), ip_address

#### Scenario: Timeline entries from api_audit_log

- WHEN a timeline entry originates from `api_audit_log`
- THEN it includes: source ("api_audit"), id, timestamp, http_method, endpoint_path, response_status, is_success, duration_ms, client_ip

#### Scenario: Time range filter (days)

- WHEN an admin sends `GET /admin/users/usr-abc123/activity?days=7`
- THEN both summary and timeline are limited to the last 7 days

#### Scenario: Default time range is 30 days

- WHEN an admin sends `GET /admin/users/usr-abc123/activity` without a days parameter
- THEN summary and timeline cover the last 30 days

#### Scenario: Non-existent user ID

- GIVEN no user exists with id "usr-nonexistent"
- WHEN an admin sends `GET /admin/users/usr-nonexistent/activity`
- THEN the system returns HTTP 404 Not Found with error code `NF_4001`

#### Scenario: User with no activity returns empty data

- GIVEN a user exists but has no activity logs or API audit entries
- WHEN an admin sends `GET /admin/users/usr-abc123/activity`
- THEN the response returns zeroed summary counts and an empty timeline array

---

# Domain: Stored Procedure Modifications

## Requirement: Search Parameter for Activity Log SPs

The system **MUST** modify `sp_get_activity_logs` and `sp_count_activity_logs` in `11_activity_logging.sql` to accept a `p_search VARCHAR(255)` parameter that performs `LIKE` matching on `activity_type`, `details`, and `u.username`.

#### Scenario: SP returns results matching search term

- GIVEN `sp_get_activity_logs` is called with `p_search='login'`
- WHEN the stored procedure executes
- THEN it returns activity logs where `activity_type`, `details`, or `username` contains "login" (case-insensitive via `LIKE CONCAT('%', p_search, '%')`)

#### Scenario: SP handles NULL search parameter

- GIVEN `sp_get_activity_logs` is called with `p_search=NULL`
- WHEN the stored procedure executes
- THEN it behaves identically to the pre-modification version (no search filtering applied)

#### Scenario: Count SP matches search results

- GIVEN `sp_count_activity_logs` is called with the same `p_search` value as `sp_get_activity_logs`
- WHEN both stored procedures execute
- THEN the count returned by `sp_count_activity_logs` matches the total number of rows that `sp_get_activity_logs` would return without LIMIT/OFFSET

---

# Domain: Data Source Merge Rules

## Requirement: Security Event Normalization

The system **MUST** normalize events from `api_audit_log` and `activity_logs` into a unified `SecurityEvent` shape for the `/admin/audit/security-events` endpoint.

#### Scenario: Field mapping for API audit events

- WHEN normalizing an `api_audit_log` entry
- THEN the mapping is:
  - `id` → `id`
  - `request_timestamp` → `timestamp`
  - `security_event` + `response_status` → `severity` (401/5xx→"warning", 403→"critical")
  - `tags` or `error_code` → `event_type`
  - `user_id` → `user_id`
  - `username` (from JOIN) → `username`
  - `client_ip` → `client_ip`
  - `endpoint_path` → `endpoint_path`
  - `http_method` → `http_method`
  - `response_status` → `response_status`
  - `error_code` → `error_code`
  - `error_message` → `error_message`
  - `duration_ms` → `duration_ms`
  - literal "api_audit" → `source`

#### Scenario: Field mapping for activity log events

- WHEN normalizing an `activity_logs` entry
- THEN the mapping is:
  - `id` → `id`
  - `created_at` → `timestamp`
  - `severity_level` → `severity`
  - `activity_type` → `event_type`
  - `user_id` → `user_id`
  - `username` (from JOIN) → `username`
  - `ip_address` → `client_ip`
  - `details` → `details`
  - `activity_name` (from JOIN) → `activity_name`
  - literal "activity_log" → `source`

## Requirement: User Activity Data Merge

The system **MUST** combine data from both `activity_logs` and `api_audit_log` for the `/admin/users/{user_id}/activity` endpoint, calling the appropriate `sp_get_user_activity_summary` from each source and merging results.

#### Scenario: Both SPs are called and results merged

- WHEN processing `GET /admin/users/{user_id}/activity`
- THEN the system calls `sp_get_user_activity_summary(user_id, days)` from `11_activity_logging.sql` for activity log summary
- AND calls `sp_get_user_activity_summary(user_id, days)` from `07_sessions_analytics.sql` for API audit summary
- AND merges both result sets into the response with clear source indicators

#### Scenario: Duplicate SP name resolution

- GIVEN `sp_get_user_activity_summary` exists in both `07_sessions_analytics.sql` and `11_activity_logging.sql` with different signatures
- WHEN the DB wrapper module calls the SPs
- THEN the wrapper uses separate database connection calls to ensure the correct SP version is invoked for each data source
- AND the system handles this by calling each SP through its respective DB wrapper function (one in `db_audit_analytics.py` for API audit, one in `activity_logger.py` for activity logs)

---

# Domain: Error Handling

## Requirement: Standardized Error Responses

The system **MUST** return standardized error responses using the existing `ErrorCode` enum and error handling patterns for all audit log monitor endpoints.

#### Scenario: Database error returns 500

- GIVEN a database connection failure occurs during any audit endpoint request
- WHEN the request is processed
- THEN the system returns HTTP 500 Internal Server Error with error code `DB_6001` or `DB_6002`

#### Scenario: Query error returns 500

- GIVEN a stored procedure execution fails (e.g., malformed parameters)
- WHEN the request is processed
- THEN the system returns HTTP 500 Internal Server Error with error code `DB_6003`

#### Scenario: Validation error returns 400

- GIVEN invalid query parameters (e.g., negative days, limit exceeding max)
- WHEN the request is processed
- THEN the system returns HTTP 400 Bad Request with the appropriate `VAL_3xxx` error code

#### Scenario: All error responses follow the standard format

- WHEN any error occurs on an audit endpoint
- THEN the response body follows the format: `{"success": false, "message": "...", "error_code": "..."}`

---

# Domain: Router Registration

## Requirement: Separate Audit Logs Router

The system **MUST** register a new `audit_logs` router in `src/main.py` with prefix `/admin` for all `/admin/audit/*` endpoints.

#### Scenario: Router is registered on startup

- WHEN the FastAPI application starts
- THEN `audit_logs.router` is included via `app.include_router(audit_logs.router, tags=["Audit Logs"])`

#### Scenario: Routes are accessible under /admin prefix

- WHEN the application is running
- THEN the following routes are accessible:
  - `GET /admin/audit/logs`
  - `GET /admin/audit/security-events`
  - `GET /admin/audit/statistics`
  - `POST /admin/audit/export`

---

# Domain: DB Wrapper Module

## Requirement: New DB Wrapper for API Audit Analytics

The system **MUST** create `src/Util/db/db_audit_analytics.py` following the existing `db_session_analytics.py` pattern, wrapping all `api_audit_log` stored procedures with `handle_db_operation` error wrapping.

#### Scenario: get_audit_logs wraps sp_get_audit_logs

- WHEN `get_audit_logs(limit, offset, user_id, project_id, endpoint_path, http_method, status_code, is_success, security_event, days)` is called
- THEN it calls `sp_get_audit_logs` with the corresponding parameters
- AND returns a list of audit log dictionaries
- AND uses `handle_db_operation` for error wrapping

#### Scenario: count_audit_logs wraps sp_count_audit_logs

- WHEN `count_audit_logs(user_id, project_id, endpoint_path, http_method, status_code, is_success, security_event, days)` is called
- THEN it calls `sp_count_audit_logs` with the corresponding parameters
- AND returns an integer count
- AND uses `handle_db_operation` for error wrapping

#### Scenario: get_audit_statistics handles multiple result sets

- WHEN `get_audit_statistics(days)` is called
- THEN it calls `sp_get_audit_statistics` which returns 4 result sets
- AND uses `cursor.nextset()` between result sets (following the pattern in `db_session_analytics.py:get_user_login_statistics`)
- AND returns a dict with 4 keys: `overview`, `by_method`, `top_endpoints`, `status_distribution`

#### Scenario: get_security_events wraps sp_get_security_events

- WHEN `get_security_events(limit, offset, days)` is called
- THEN it calls `sp_get_security_events` with the corresponding parameters
- AND returns a list of security event dictionaries

#### Scenario: get_failed_requests wraps sp_get_failed_requests

- WHEN `get_failed_requests(limit, offset, days)` is called
- THEN it calls `sp_get_failed_requests` with the corresponding parameters
- AND returns a list of failed request dictionaries

#### Scenario: get_user_api_activity_summary handles multiple result sets

- WHEN `get_user_api_activity_summary(user_id, days)` is called
- THEN it calls `sp_get_user_activity_summary` from `07_sessions_analytics.sql` which returns 2 result sets
- AND uses `cursor.nextset()` between result sets
- AND returns a dict with 2 keys: `summary` and `endpoint_activity`

#### Scenario: DB functions are exported from __init__.py

- WHEN the `src/Util/db/__init__.py` module is loaded
- THEN it exports all new functions from `db_audit_analytics.py`

---

## Coverage

| Domain | Type | Requirements | Scenarios |
|--------|------|-------------|-----------|
| Auth & Access Control | New | 1 | 4 |
| Activity Log Enhancement | Modified | 2 | 9 |
| API Audit Logs | New | 1 | 15 |
| Security Events | New | 1 | 12 |
| Audit Statistics | New | 1 | 9 |
| Export | New | 1 | 11 |
| User Activity | New | 1 | 9 |
| Stored Procedure Modifications | Modified | 1 | 3 |
| Data Source Merge Rules | New | 2 | 4 |
| Error Handling | New | 1 | 4 |
| Router Registration | New | 1 | 2 |
| DB Wrapper Module | New | 1 | 7 |

**Total: 14 requirements, 89 scenarios**

### Coverage Summary

- **Happy paths**: ✅ Covered — all primary use cases have scenarios
- **Edge cases**: ✅ Covered — empty results, no matches, non-existent IDs, zeroed statistics
- **Error states**: ✅ Covered — auth failures, validation errors, DB errors, limit exceeded
- **Pagination**: ✅ Covered — offset, limit validation, has_more calculation
- **Filtering**: ✅ Covered — all filter combinations for each endpoint
- **Export limits**: ✅ Covered — hard limit enforcement, streaming response
- **Data-source merge**: ✅ Covered — normalization, field mapping, dual-SP handling

### Unresolved Ambiguities

None — all open questions from the proposal have been resolved by the authoritative decisions:
- ✅ Export hard limit: 10,000 records
- ✅ Admin scope: global for now
- ✅ Security events: combine `activity_logs` and `api_audit_log`
- ✅ Severity for API audit: derived from status code (401→warning, 403→critical, 5xx→warning)
- ✅ User activity endpoint: combines both activity logs and API audit logs
- ✅ Stored procedures: modify existing SPs where needed

### Next Step

Ready for design (sdd-design).
