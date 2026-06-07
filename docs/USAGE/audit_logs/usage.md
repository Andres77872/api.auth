# Audit Logs Usage

Practical usage guide for operating the audit and activity logging systems in `api.auth`.

---

## Table of Contents

- [System Distinction](#system-distinction)
- [Activity Feed (Dashboard)](#activity-feed-dashboard)
- [API Audit Logs](#api-audit-logs)
- [Security Events](#security-events)
- [Audit Statistics](#audit-statistics)
- [User Activity](#user-activity)
- [Export](#export)

---

## System Distinction

There are **two logging systems** in this API. They serve different purposes and have different endpoints:

| Aspect | `/admin/activity` (Dashboard) | `/admin/audit/*` (Dedicated Audit) |
|--------|-------------------------------|-----------------------------------|
| **Data source** | `activity_logs` table only | `api_audit_log` table, or BOTH combined |
| **Logged by** | `@log_and_handle_errors` decorator on route handlers | `APIAuditMiddleware` on every HTTP request |
| **Granularity** | Semantic operations (e.g., `user_login`, `project_creation`) | Raw HTTP request/response pairs |
| **Pagination** | `limit` (1-500), `offset` | `limit` (1-1000 for logs, 1-500 for security events), `offset` |
| **Search** | Free-text `search` param across activity_type, details, username | No free-text; structured filters only |
| **Export** | None | CSV/JSON via `POST /admin/audit/export` |
| **Statistics** | None | Full analytics via `GET /admin/audit/statistics` |

**Do not confuse them.** The activity feed shows "what happened" in business terms. The audit logs show "what HTTP requests were made" in technical terms.

---

## Activity Feed (Dashboard)

### Get Activity Feed

```bash
curl -X GET "http://localhost:8000/admin/activity?limit=50&offset=0&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Query parameters:**

| Param | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `limit` | int | 50 | 1-500 | Records per page |
| `offset` | int | 0 | >=0 | Skip count |
| `activity_type_filter` | string | null | — | Filter by activity type (e.g., `user_login`) |
| `user_id` | string | null | — | Filter by user ID |
| `project_id` | string | null | — | Filter by project ID |
| `days` | int | 30 | 1-365 | Lookback window |
| `search` | string | null | — | Free-text search across activity_type, details, username |

**Response shape:**

```json
{
  "activities": [...],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 123,
    "has_more": true
  },
  "filters": {
    "activity_type_filter": null,
    "user_id": null,
    "project_id": null,
    "days": 30,
    "search": null
  },
  "generated_at": "2026-04-01T12:00:00Z"
}
```

The list key is `activities`, not `logs`.

**Example: filter by activity type**

```bash
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=user_login&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Example: free-text search**

```bash
curl -X GET "http://localhost:8000/admin/activity?search=john_doe&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Get Activity Types

Returns the full list of 30 activity types available for filtering:

```bash
curl -X GET "http://localhost:8000/admin/activity/types" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Response includes: `user_login`, `user_logout`, `user_registration`, `user_update`, `user_status_change`, `user_password_reset`, `user_type_changed`, `project_creation`, `project_update`, `project_delete`, `project_member_add`, `project_member_remove`, `project_member_removed`, `project_ownership_transferred`, `project_archived`, `project_unarchived`, `group_creation`, `group_update`, `group_delete`, `user_group_assign`, `user_group_remove`, `permission_grant`, `permission_revoke`, `role_removed`, `bulk_role_assignment`, `bulk_group_assignment`, `bulk_user_update`, `bulk_user_delete`, `admin_action`, `system_event`.

---

## API Audit Logs

### List Audit Logs

Paginated, filtered access to the raw HTTP audit trail:

```bash
curl -X GET "http://localhost:8000/admin/audit/logs?limit=50&offset=0&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Query parameters:**

| Param | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `limit` | int | 50 | 1-1000 | Records per page |
| `offset` | int | 0 | >=0 | Skip count |
| `user_id` | string | null | — | Filter by user ID |
| `project_id` | string | null | — | Filter by project ID |
| `endpoint_path` | string | null | — | **Partial match** on endpoint path |
| `http_method` | string | null | — | Exact match (GET, POST, PUT, DELETE, PATCH) |
| `status_code` | int | null | — | Exact HTTP status code |
| `is_success` | bool | null | — | True=2xx, False=non-2xx |
| `security_event` | bool | null | — | Security-flagged requests only |
| `days` | int | 30 | 1-365 | Lookback window |

**Example: find failed login attempts**

```bash
curl -X GET "http://localhost:8000/admin/audit/logs?endpoint_path=/auth/login&is_success=false&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Example: find all DELETE requests**

```bash
curl -X GET "http://localhost:8000/admin/audit/logs?http_method=DELETE&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Example: find 500 errors**

```bash
curl -X GET "http://localhost:8000/admin/audit/logs?status_code=500&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Response shape:**

```json
{
  "logs": [...],
  "pagination": { "total": N, "limit": 50, "offset": 0, "has_more": true, "next_offset": 50 },
  "filters": { ...applied filters... },
  "generated_at": "2024-..."
}
```

---

## Security Events

Combined security events from **both** data sources (`api_audit_log` + `activity_logs`), normalized to a common shape:

```bash
curl -X GET "http://localhost:8000/admin/audit/security-events?limit=100&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Query parameters:**

| Param | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `limit` | int | 100 | 1-500 | Max events (applied to **merged** result) |
| `days` | int | 30 | 1-365 | Lookback window |
| `severity` | string | null | — | Filter: `critical` or `warning` |
| `source` | string | null | — | Filter: `api_audit` or `activity_log` |

**Severity derivation:**

| Status | Severity |
|--------|----------|
| 401 | `warning` |
| 403 | `critical` |
| 5xx | `warning` |
| Everything else | `info` |

**Caveat:** this endpoint has **no pagination**. The limit applies to the final merged result, not per-source. For large datasets, use the `source` filter to split by data source.

**Example: critical events only**

```bash
curl -X GET "http://localhost:8000/admin/audit/security-events?severity=critical&days=1" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Example: split by source**

```bash
# API audit security events
curl -X GET "http://localhost:8000/admin/audit/security-events?source=api_audit&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Activity log security events
curl -X GET "http://localhost:8000/admin/audit/security-events?source=activity_log&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## Audit Statistics

Four-section analytics overview from the `api_audit_log` table:

```bash
curl -X GET "http://localhost:8000/admin/audit/statistics?days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Query parameters:**

| Param | Type | Default | Range |
|-------|------|---------|-------|
| `days` | int | 7 | 1-365 |

**Returns 4 sections:**

- `overview` — total requests, success/failure counts, average duration
- `by_method` — breakdown by HTTP method (GET, POST, PUT, DELETE, PATCH)
- `top_endpoints` — most accessed endpoints with success/failure rates
- `status_distribution` — count of each HTTP status code

---

## User Activity

Combined activity summary and timeline for a specific user, merging **both** data sources:

```bash
curl -X GET "http://localhost:8000/admin/users/{user_id}/activity?days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Query parameters:**

| Param | Type | Default | Range |
|-------|------|---------|-------|
| `days` | int | 30 | 1-365 |

**Response contains:**

- `user_id` — the queried user
- `summary` — combined counts and per-category breakdown
  - `total_activities` — combined total count
  - `activity_log_count` — number of semantic activity-log entries
  - `api_audit_count` — number of API-audit entries
  - `activity_summary` — activity log entries grouped by category/name
  - `api_audit_summary` — API audit summary (total requests, success/failure, unique endpoints)
- `timeline` — merged timeline (up to 50 entries from each source, sorted by timestamp descending)
- `generated_at` — response generation timestamp

**Caveat:** the timeline has **no pagination**. It returns a fixed-size merge.

---

## Export

Exports activity logs or API audit logs in CSV or JSON format.

**This endpoint requires a JSON body** — unlike 99% of the API which uses `multipart/form-data`.

```bash
curl -X POST "http://localhost:8000/admin/audit/export" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "api_audit",
    "format": "csv",
    "limit": 1000,
    "filters": {
      "days": 30
    }
  }'
```

**Request body fields:**

| Field | Type | Required | Values | Description |
|-------|------|----------|--------|-------------|
| `source` | string | Yes | `activity`, `audit`, `api_audit` | Data source. `audit` and `api_audit` are aliases (both query `api_audit_log`) |
| `format` | string | Yes | `csv`, `json` | Output format |
| `limit` | int | No | 1-10,000 | Row limit (default 1,000) |
| `filters` | object | No | — | Same filters as the corresponding list endpoint |

**Filters for `api_audit` source:** `user_id`, `project_id`, `endpoint_path`, `http_method`, `status_code`, `is_success`, `security_event`, `days`

**Filters for `activity` source:** `user_id`, `project_id`, `activity_type`, `days`

**Important constraints:**

- Hard limit: **10,000 records**. If filters match more than 10,000, the export returns 400 `INVALID_RANGE`.
- A pre-export count check runs before streaming. If the count exceeds the hard limit, the request is rejected.
- Response is a `StreamingResponse` with `Content-Disposition: attachment; filename=audit_export_{source}_{timestamp}.{fmt}`

**CSV columns for `api_audit`:** 23 columns — `id`, `request_id`, `http_method`, `endpoint_path`, `route_pattern`, `user_id`, `user_type`, `username`, `user_hash`, `project_id`, `project_name`, `project_hash`, `request_timestamp`, `response_timestamp`, `duration_ms`, `response_status`, `is_success`, `error_code`, `error_message`, `client_ip`, `user_agent`, `security_event`, `tags`

**CSV columns for `activity`:** 19 columns — `id`, `user_id`, `activity_type`, `details`, `project_id`, `target_user_id`, `ip_address`, `user_agent`, `severity_level`, `created_at`, `username`, `user_hash`, `project_name`, `project_hash`, `target_username`, `target_user_hash`, `activity_name`, `activity_category`, `activity_description`

**Caveat:** when no data matches export filters, CSV returns a single empty row (not a proper header row).

---

## Related Documentation

- **[Audit Logs Overview](README.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**
- **[Admin Usage Cases](../admin-usage-cases.md)** — Dashboard, activity feed quick reference
- **[Error Reference](../errors.md)** — Error codes and response shapes

---

**Last Updated**: April 2026
**Document Version**: 1.0
