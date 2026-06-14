# Audit Log Stored Procedures

SQL stored procedures for querying the `api_audit_log` and `activity_logs` tables directly. These are used when you need database-level access beyond the HTTP API.

> **Note**: The HTTP API endpoints (`/admin/audit/*`, `/admin/activity`) are the primary interface for most use cases. Stored procedures are useful for custom reporting, direct database queries, or when the HTTP API does not cover a specific query pattern.

---

## Table of Contents

- [API Audit Log Procedures](#api-audit-log-procedures)
- [API Audit Security Procedures](#api-audit-security-procedures)
- [Statistics Procedures](#statistics-procedures)
- [User Activity Procedures](#user-activity-procedures)
- [Email Delivery Logs (No Stored Procedure)](#email-delivery-logs-no-stored-procedure)

---

## API Audit Log Procedures

These procedures query the `api_audit_log` table (populated by middleware).

### `sp_get_audit_logs`

Retrieve paginated API audit logs with filtering.

```sql
CALL sp_get_audit_logs(
  p_limit,          -- INT: max results
  p_offset,         -- INT: skip count
  p_user_id,        -- VARCHAR: filter by user ID (exact)
  p_project_id,     -- VARCHAR: filter by project ID (exact)
  p_endpoint_path,  -- VARCHAR: filter by endpoint (partial match)
  p_http_method,    -- VARCHAR: GET, POST, PUT, DELETE, PATCH
  p_status_code,    -- INT: exact HTTP status code
  p_is_success,     -- BOOLEAN: TRUE=2xx, FALSE=non-2xx
  p_security_event, -- BOOLEAN: security-flagged only
  p_days            -- INT: lookback window (1-365)
);
```

**Examples:**

```sql
-- Get recent audit logs (last 7 days)
CALL sp_get_audit_logs(50, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 7);

-- Filter by user
CALL sp_get_audit_logs(50, 0, 'user-id-123', NULL, NULL, NULL, NULL, NULL, NULL, 7);

-- Filter by endpoint
CALL sp_get_audit_logs(50, 0, NULL, NULL, '/auth/login', NULL, NULL, NULL, NULL, 7);

-- Filter by HTTP method
CALL sp_get_audit_logs(50, 0, NULL, NULL, NULL, 'POST', NULL, NULL, NULL, 7);

-- Filter by status code
CALL sp_get_audit_logs(50, 0, NULL, NULL, NULL, NULL, 401, NULL, NULL, 7);

-- Filter failed requests only
CALL sp_get_audit_logs(50, 0, NULL, NULL, NULL, NULL, NULL, FALSE, NULL, 7);

-- Filter security events only
CALL sp_get_audit_logs(50, 0, NULL, NULL, NULL, NULL, NULL, NULL, TRUE, 7);
```

### `sp_count_audit_logs`

Count audit logs matching filters (useful for pagination).

```sql
CALL sp_count_audit_logs(
  p_user_id,        -- VARCHAR: filter by user ID
  p_project_id,     -- VARCHAR: filter by project ID
  p_endpoint_path,  -- VARCHAR: filter by endpoint (partial match)
  p_http_method,    -- VARCHAR: GET, POST, PUT, DELETE
  p_status_code,    -- INT: exact status code
  p_is_success,     -- BOOLEAN: success or failure
  p_security_event, -- BOOLEAN: security events only
  p_days            -- INT: lookback window
);
```

**Example:**

```sql
-- Count security events in last 7 days
CALL sp_count_audit_logs(NULL, NULL, NULL, NULL, NULL, NULL, TRUE, 7);
```

---

## API Audit Security Procedures

These procedures query the `api_audit_log` table for security-relevant HTTP events captured by middleware.

### `sp_get_security_events`

Retrieve security-relevant events (failed auth, unauthorized access, admin actions, deletes, permission changes, password resets).

```sql
CALL sp_get_security_events(
  p_limit,   -- INT: max results
  p_offset,  -- INT: skip count
  p_days     -- INT: lookback window (1-365)
);
```

**Example:**

```sql
-- Get recent security events
CALL sp_get_security_events(50, 0, 7);
```

**Response fields:**

| Field | Description |
|-------|-------------|
| `id` | Audit log ID |
| `request_id` | Request correlation ID |
| `http_method` | GET, POST, PUT, DELETE, PATCH |
| `endpoint_path` | Full request path |
| `user_id` | Authenticated user (if any) |
| `user_type` | root, admin, consumer |
| `client_ip` | Client IP address |
| `response_status` | HTTP status code |
| `error_code` | Error code (if failed) |
| `error_message` | Error details (if failed) |
| `request_timestamp` | When request was received |
| `duration_ms` | Request processing time |
| `tags` | Searchable tags array |
| `metadata` | Additional structured request metadata |
| `username` | Username (if authenticated) |
| `user_hash` | Public user hash (if authenticated) |

### `sp_get_failed_requests`

Retrieve failed API requests for monitoring.

```sql
CALL sp_get_failed_requests(
  p_limit,   -- INT: max results
  p_offset,  -- INT: skip count
  p_days     -- INT: lookback window (1-365)
);
```

**Example:**

```sql
-- Get recent failed requests
CALL sp_get_failed_requests(50, 0, 7);
```

---

## Statistics Procedures

### `sp_get_audit_statistics`

Get comprehensive audit analytics. Returns **multiple result sets**:

```sql
CALL sp_get_audit_statistics(p_days);
```

**Result sets:**

1. **Overall Statistics**: Total requests, success/failure counts, average duration
2. **Requests by Method**: Breakdown by GET, POST, PUT, DELETE
3. **Top Endpoints**: Most accessed endpoints with success/failure rates
4. **Status Code Distribution**: Count of each HTTP status code

**Example:**

```sql
-- Get audit statistics for last 7 days
CALL sp_get_audit_statistics(7);
```

---

## User Activity Procedures

### `sp_get_user_activity_summary`

Get a specific user's activity-log summary. Returns **one result set** grouped by activity category and name:

```sql
CALL sp_get_user_activity_summary(p_user_id, p_days);
```

**Result set fields:**

- `activity_category`
- `activity_name`
- `activity_count`
- `last_activity`

> **Current application status:** this stored procedure is defined in SQL but is not called by the Python application. The HTTP user-activity endpoint uses the API-audit summary path plus activity-log queries instead of this two-step stored-procedure contract.

**Example:**

```sql
-- Get user activity summary for last 30 days
CALL sp_get_user_activity_summary('user-id-123', 30);
```

---

## Email Delivery Logs (No Stored Procedure)

`GET /admin/email/logs` does **not** use a stored procedure. It runs an inline `SELECT` against the `email_messages` table via `db_email.list_email_delivery_logs()`. Do not look for an `sp_` procedure for email delivery logs — there is none.

The equivalent direct query (redacted columns only):

```sql
SELECT em.id,
       em.user_id,
       em.user_email_id,
       em.purpose,
       em.template_code,
       HEX(em.recipient_hash) AS recipient_hash,
       em.recipient_masked,
       em.provider,
       em.provider_message_id,
       em.status,
       em.priority,
       em.attempt_count,
       em.max_attempts,
       em.next_attempt_at,
       em.sent_at,
       em.terminal_at,
       em.last_error_code,
       em.created_at,
       em.updated_at
FROM email_messages em
-- optional, AND-combined: WHERE em.status = ? AND em.purpose = ? AND em.provider = ?
ORDER BY em.created_at DESC
LIMIT ? OFFSET ?;
```

The plaintext columns on `email_messages` (`recipient_email`, `last_error_message`, `render_payload_ciphertext`, `provider_idempotency_key`, `token_id`, …) are intentionally **not** selected, so they never reach the API surface.

---

## Related Documentation

- **[Audit Logs Overview](README.md)** — Dual logging system overview
- **[Usage](usage.md)** — HTTP API workflows
- **[Reference](reference.md)** — HTTP endpoint and filter reference
- **[Error Reference](../errors.md)** — Error codes and troubleshooting

---

**Last Updated**: June 2026
**Document Version**: 1.1
