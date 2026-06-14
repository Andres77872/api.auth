# Audit Logs Endpoint and Operational Reference

Reference for the audit and activity logging API surface in `api.auth`.

---

## Table of Contents

- [Dedicated Audit Endpoints](#dedicated-audit-endpoints)
- [Dashboard Activity Endpoints](#dashboard-activity-endpoints)
- [Filter Reference](#filter-reference)
- [Export Reference](#export-reference)
- [Operational Notes](#operational-notes)

---

## Dedicated Audit Endpoints

These endpoints are defined in `src/routes/audit_logs.py` (6 endpoints) and require **root or admin** user type (checked by `_check_admin_access`). Auth via `HTTPBearerOrCookie()`.

| Endpoint | Method | Auth | Content Type | Purpose |
|----------|--------|------|--------------|---------|
| `/admin/email/logs` | GET | root/admin | Query params | Email delivery logs from `email_messages` (recipient hash + masked email only) |
| `/admin/audit/logs` | GET | root/admin | Query params | Paginated API audit logs from `api_audit_log` |
| `/admin/audit/security-events` | GET | root/admin | Query params | Combined security events from BOTH audit sources |
| `/admin/audit/statistics` | GET | root/admin | Query params | 4-section audit analytics |
| `/admin/audit/export` | POST | root/admin | **JSON** | CSV/JSON export, max 10,000 records |
| `/admin/users/{user_id}/activity` | GET | root/admin | Query params | Per-user combined activity + timeline |

---

## Dashboard Activity Endpoints

All endpoints under `/admin/activity*` require **root or admin** user type. Auth via `HTTPBearerOrCookie()`.

| Endpoint | Method | Auth | Content Type | Purpose |
|----------|--------|------|--------------|---------|
| `/admin/activity` | GET | root/admin | Query params | Activity feed from `activity_logs` table |
| `/admin/activity/{activity_id}` | GET | root/admin | — | Single activity log detail by ID |
| `/admin/activity/types` | GET | root/admin | — | Enum of all 30 activity types |

---

## Filter Reference

### `/admin/email/logs` Filters

| Param | Type | Default | Range | Match Type | Description |
|-------|------|---------|-------|------------|-------------|
| `limit` | int | 50 | 1-500 | — | Records per page |
| `offset` | int | 0 | >=0 | — | Skip count |
| `status` | string | null | — | Exact | Outbox status (see enum below) |
| `purpose` | string | null | — | Exact | Transactional purpose (see enum below) |
| `provider` | string | null | — | Exact | Provider name (e.g. `resend`) |

**`status` values:** `pending`, `processing`, `sent`, `delivered`, `bounced`, `complained`, `suppressed`, `retry`, `dead`, `cancelled`

**`purpose` values:** `email_activation`, `password_reset`, `admin_password_reset`, `security_notification`, `delivery_operation`

**Pagination note:** unlike `/admin/audit/logs` (which runs a real count query and reports a `total`), this endpoint uses a **page-fill heuristic**: `has_more` is `true` whenever the page is exactly full (`returned == limit`) and `null`/`false` otherwise. There is no total count. On an exactly-full final page, `has_more` can be `true` even though the next page is empty.

**Response fields** (per log row, redacted):

| Field | Notes |
|-------|-------|
| `id` | Message ID |
| `user_id` | Owning user (nullable) |
| `user_email_id` | Associated `user_emails` row (nullable) |
| `purpose` | One of the `purpose` enum values |
| `template_code` | Template identifier |
| `recipient_hash` | **HEX** of the `BINARY(32)` recipient hash |
| `recipient_masked` | Masked email (e.g. `j***@e***.com`) |
| `provider` | Provider name |
| `provider_message_id` | Provider-assigned message ID (nullable) |
| `status` | One of the `status` enum values |
| `priority` | Outbox priority (TINYINT) |
| `attempt_count` | Delivery attempts so far |
| `max_attempts` | Max attempts before dead-letter |
| `next_attempt_at` | Next scheduled retry time |
| `sent_at` | When the provider accepted the message (nullable) |
| `terminal_at` | When the message reached a terminal state (nullable) |
| `last_error_code` | Last error code (nullable) |
| `created_at` | Row creation time |
| `updated_at` | Last update time (nullable) |

**Redaction guarantee:** the query selects only the fields above. It never exposes the plaintext recipient (`recipient_email`), subject/body, template variables (`render_payload_ciphertext`), `last_error_message`, `provider_idempotency_key`, token references, or provider credentials/payloads.

### `/admin/audit/logs` Filters

| Param | Type | Default | Range | Match Type | Description |
|-------|------|---------|-------|------------|-------------|
| `limit` | int | 50 | 1-1000 | — | Records per page |
| `offset` | int | 0 | >=0 | — | Skip count |
| `user_id` | string | null | — | Exact | Filter by user ID |
| `project_id` | string | null | — | Exact | Filter by project ID |
| `endpoint_path` | string | null | — | **Partial** | Partial match on endpoint path |
| `http_method` | string | null | — | Exact | GET, POST, PUT, DELETE, PATCH |
| `status_code` | int | null | — | Exact | HTTP status code |
| `is_success` | bool | null | — | Exact | True=2xx, False=non-2xx |
| `security_event` | bool | null | — | Exact | Security-flagged only |
| `days` | int | 30 | 1-365 | — | Lookback window |

### `/admin/audit/security-events` Filters

| Param | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `limit` | int | 100 | 1-500 | Applied to **merged** result (no pagination) |
| `days` | int | 30 | 1-365 | Lookback window |
| `severity` | string | null | — | `critical` or `warning` |
| `source` | string | null | — | `api_audit` or `activity_log` |

### `/admin/audit/statistics` Filters

| Param | Type | Default | Range |
|-------|------|---------|-------|
| `days` | int | 7 | 1-365 |

### `/admin/activity` Filters

| Param | Type | Default | Range | Description |
|-------|------|---------|-------|-------------|
| `limit` | int | 50 | 1-500 | Records per page |
| `offset` | int | 0 | >=0 | Skip count |
| `activity_type_filter` | string | null | — | Filter by activity type |
| `user_id` | string | null | — | Filter by user ID |
| `project_id` | string | null | — | Filter by project ID |
| `days` | int | 30 | 1-365 | Lookback window |
| `search` | string | null | — | Free-text search across activity_type, details, username |

### `/admin/users/{user_id}/activity` Filters

| Param | Type | Default | Range |
|-------|------|---------|-------|
| `days` | int | 30 | 1-365 |

---

## Export Reference

### Request Body

**Content-Type:** `application/json` — note this is unusual; most POST/PUT/PATCH endpoints in the API use `multipart/form-data`. Other JSON-body endpoints include `POST /admin/user-groups/{hash}/members/bulk` and the Google sign-in endpoints in `auth_google.py` (e.g. `POST /auth/google/start`, `/link/finish`, `/reauth/start`).

```json
{
  "source": "api_audit",
  "format": "csv",
  "limit": 1000,
  "filters": {}
}
```

### Source Values

| Source | Data Source | Notes |
|--------|-------------|-------|
| `activity` | `activity_logs` table | Semantic events |
| `api_audit` | `api_audit_log` table | Raw HTTP audit (canonical name) |
| `audit` | `api_audit_log` table | Alias for `api_audit` (backward compatibility) |

### Format Values

| Format | Content-Type | Structure |
|--------|-------------|-----------|
| `csv` | `text/csv` | Header row + data rows |
| `json` | `application/json` | JSON array of objects |

### CSV Columns

**For `api_audit` / `audit` source (23 columns):**

`id`, `request_id`, `http_method`, `endpoint_path`, `route_pattern`, `user_id`, `user_type`, `username`, `user_hash`, `project_id`, `project_name`, `project_hash`, `request_timestamp`, `response_timestamp`, `duration_ms`, `response_status`, `is_success`, `error_code`, `error_message`, `client_ip`, `user_agent`, `security_event`, `tags`

**For `activity` source (19 columns):**

`id`, `user_id`, `activity_type`, `details`, `project_id`, `target_user_id`, `ip_address`, `user_agent`, `severity_level`, `created_at`, `username`, `user_hash`, `project_name`, `project_hash`, `target_username`, `target_user_hash`, `activity_name`, `activity_category`, `activity_description`

### Filters by Source

**For `api_audit` / `audit`:** `user_id`, `project_id`, `endpoint_path`, `http_method`, `status_code`, `is_success`, `security_event`, `days`

**For `activity`:** `user_id`, `project_id`, `activity_type`, `days`

### Limits

| Constraint | Value | Behavior |
|------------|-------|----------|
| Default limit | 1,000 | Used when `limit` is not specified |
| Hard limit | 10,000 | If filters match more records, export returns 400 `INVALID_RANGE` |
| Pre-check | Yes | Count is checked before streaming begins |

---

## Operational Notes

### Auth Requirements

All audit endpoints require **root or admin** user type. Consumer users receive 403 `ACCESS_DENIED`.

**No project scoping:** any admin can view audit logs for ALL projects. This is a data isolation gap.

### Pagination Behavior

| Endpoint | Pagination | Notes |
|----------|-----------|-------|
| `/admin/audit/logs` | Yes (limit + offset) | `has_more` and `next_offset` in response |
| `/admin/audit/security-events` | **No** | Flat list, limit applied to merged result |
| `/admin/audit/statistics` | N/A | Single response, no pagination |
| `/admin/activity` | Yes (limit + offset) | Standard pagination |
| `/admin/users/{user_id}/activity` | **No** | Fixed-size merge (50 per source max) |
| `/admin/email/logs` | Yes (limit + offset) | `has_more`/`next_offset` via page-fill heuristic (`returned == limit`); **no** total count |

### Sensitive Data Filtering

Passwords, tokens, and API keys are masked as `***FILTERED***` in:
- Request bodies
- Response bodies
- Headers

This filtering is applied by `APIAuditLogger.filter_sensitive_data()` and cannot be disabled.

### Response Format

All audit endpoints return a JSON object with `generated_at` timestamp. The export endpoint returns a `StreamingResponse` with `Content-Disposition` header.

### Error Responses

| Status | Error Code | When |
|--------|-----------|------|
| 403 | `ACCESS_DENIED` | Consumer user accesses audit endpoint |
| 400 | `INVALID_RANGE` | Limit/days out of range, or export exceeds 10,000 |
| 400 | `INVALID_INPUT` | Invalid JSON body (export) |
| 400 | `MISSING_REQUIRED_FIELD` | Missing `source` or `format` (export) |
| 400 | `INVALID_ENUM_VALUE` | Invalid source/format value (export) |
| 404 | `USER_NOT_FOUND` | User ID not found (user activity endpoint, `audit_logs.py`) |
| 404 | `RESOURCE_NOT_FOUND` | Activity ID not found (activity detail — handled in `admin_dashboard.py`, not `audit_logs.py`) |
| 400 | `INVALID_INPUT` | Activity ID format invalid (must match `act-[0-9a-fA-F]{32}`; `admin_dashboard.py`) |

Note: `GET /admin/email/logs` returns no body-validation errors of its own — its only failure path is 403 `ACCESS_DENIED` for non-admin users. Invalid `limit`/`offset` values are rejected by FastAPI as 422 before the handler runs; unknown `status`/`purpose`/`provider` values are accepted and simply match nothing.

---

## Related Documentation

- **[Audit Logs Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Stored Procedures](stored-procedures.md)** — SQL procedures for direct DB queries
- **[Troubleshooting](troubleshooting.md)**
- **[Error Reference](../errors.md)** — All error codes and response shapes

---

**Last Updated**: June 2026
**Document Version**: 1.1
