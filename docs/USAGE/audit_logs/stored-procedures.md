# Audit log stored procedures

The SQL procedures that write and read `api_audit_log` and `activity_logs`. Use them for reports
the HTTP endpoints do not cover; for everyday work use the routes in [usage.md](usage.md).

Definitions: `schemas/stored_procedures/07_sessions_analytics.sql` (API audit),
`schemas/stored_procedures/11_activity_logging.sql` (activity log) and
`schemas/stored_procedures/12_activity_context.sql` (session variables).

## Inventory

| Procedure | Parameters | Called by the application |
| --- | --- | --- |
| `sp_log_api_request` | `p_id`, `p_request_id`, `p_http_method`, `p_endpoint_path`, `p_route_pattern`, `p_user_id`, `p_user_type`, `p_session_id`, `p_request_headers`, `p_request_body`, `p_request_query`, `p_request_size_bytes`, `p_client_ip`, `p_user_agent`, `p_referer`, `p_project_id`, `p_metadata`, `p_auth_method` | Yes — `APIAuditLogger.log_request` |
| `sp_update_api_response` | `p_id`, `p_response_status`, `p_response_body`, `p_response_headers`, `p_response_size_bytes`, `p_error_code`, `p_error_message`, `p_target_resource_type`, `p_target_resource_id`, `p_tags`, `p_security_event` | Yes — `APIAuditLogger.log_response` |
| `sp_get_audit_logs` | `p_limit`, `p_offset`, `p_user_id`, `p_project_id`, `p_endpoint_path`, `p_http_method`, `p_status_code`, `p_is_success`, `p_security_event`, `p_days` | Yes — audit logs, user activity, export |
| `sp_count_audit_logs` | `p_user_id`, `p_project_id`, `p_endpoint_path`, `p_http_method`, `p_status_code`, `p_is_success`, `p_security_event`, `p_days` | Yes — audit logs, export |
| `sp_get_audit_statistics` | `p_days` | Yes — statistics |
| `sp_get_security_events` | `p_limit`, `p_offset`, `p_days` | Yes — security events |
| `sp_get_failed_requests` | `p_limit`, `p_offset`, `p_days` | No route (wrapper `get_failed_requests` exists) |
| `sp_get_user_api_activity_summary` | `p_user_id`, `p_days` | Yes — user activity |
| `sp_log_activity` | `p_activity_log_id`, `p_user_id`, `p_activity_code`, `p_details`, `p_project_id`, `p_user_group_id`, `p_target_user_id`, `p_ip_address`, `p_user_agent`, `p_metadata` | Yes — `ActivityLogger.log_activity` |
| `sp_get_activity_logs` | `p_limit`, `p_offset`, `p_user_id`, `p_project_id`, `p_activity_code`, `p_days`, `p_search` | Yes — activity feed, user activity, export |
| `sp_count_activity_logs` | `p_user_id`, `p_project_id`, `p_activity_code`, `p_days`, `p_search` | Yes — activity feed, export |
| `sp_get_recent_security_events` | `p_hours`, `p_limit` | Yes — security events |
| `sp_get_activity_catalog` | `p_category` | No route (wrapper exists) |
| `sp_get_activity_by_code` | `p_activity_code` | No route (wrapper exists) |
| `sp_get_activity_stats` | `p_project_id`, `p_days` | No route (wrapper exists) |
| `sp_get_user_activity_summary` | `p_user_id`, `p_days` | No |
| `sp_log_permission_change` | `p_audit_id`, `p_action_type`, `p_project_id`, `p_target_user_id`, `p_user_group_id`, `p_permission_id`, `p_permission_group_id`, `p_performed_by`, `p_old_values`, `p_new_values`, `p_ip_address`, `p_user_agent`, `p_table_name`, `p_record_id` | No (writes `permission_audit_log`) |
| `sp_cleanup_old_activity_logs` | `p_retention_days`, `p_dry_run` | No |
| `sp_set_activity_context` | `p_user_id`, `p_ip_address`, `p_user_agent` | No |
| `sp_clear_activity_context` | — | No |
| `sp_get_activity_context` | — | No |

The activity feed passes `activity_type_filter` as `p_activity_code`, and user activity passes
`p_limit = 500`.

## API audit log

### `sp_get_audit_logs`

Newest first. `p_days` defaults to `30` when `NULL`; every other `NULL` filter is ignored.
`p_endpoint_path` is a substring match, the rest are exact. Returns the 29 stored columns listed in
[reference.md](reference.md#api-audit-log-fields) plus `username`, `user_hash`, `project_name` and
`project_hash`.

```sql
-- Failed requests to the login route in the last 7 days
CALL sp_get_audit_logs(50, 0, NULL, NULL, '/auth/login', NULL, NULL, FALSE, NULL, 7);

-- One user's DELETE requests in the last 30 days
CALL sp_get_audit_logs(100, 0, 'usr-...', NULL, NULL, 'DELETE', NULL, NULL, NULL, 30);
```

### `sp_count_audit_logs`

Same filters as `sp_get_audit_logs`, without paging. Returns `total_count`.

```sql
-- Security-flagged requests in the last 7 days
CALL sp_count_audit_logs(NULL, NULL, NULL, NULL, NULL, NULL, TRUE, 7);
```

### `sp_get_audit_statistics`

Four result sets over the last `p_days` days (default `7` when `NULL`):

1. `total_requests`, `successful_requests`, `failed_requests`, `avg_duration_ms`,
   `max_duration_ms`, `avg_request_size`, `avg_response_size`
2. Per `http_method`: `request_count`, `avg_duration_ms`
3. Top 20 `endpoint_path` values: `request_count`, `avg_duration_ms`, `success_count`,
   `failure_count`
4. Per `response_status`: `count`

```sql
CALL sp_get_audit_statistics(7);
```

### `sp_get_security_events`

Rows with `security_event = TRUE`, newest first; `p_days` defaults to `30`. Returns `id`,
`request_id`, `http_method`, `endpoint_path`, `user_id`, `user_type`, `client_ip`,
`response_status`, `error_code`, `error_message`, `request_timestamp`, `duration_ms`, `tags`,
`metadata`, `username`, `user_hash`.

```sql
CALL sp_get_security_events(50, 0, 7);
```

### `sp_get_failed_requests`

Rows with `is_success = FALSE`, newest first; `p_days` defaults to `7`. Returns the request
identity, user, client IP, status, error fields, timestamp, duration and `username`.

```sql
CALL sp_get_failed_requests(50, 0, 7);
```

### `sp_get_user_api_activity_summary`

Two result sets for one user over `p_days` (default `30`): totals (`total_requests`,
`successful_requests`, `failed_requests`, `unique_endpoints`, `first_request`, `last_request`,
`avg_duration_ms`), then the 20 most recently used `endpoint_path` + `http_method` pairs with
`request_count` and `last_access`. The HTTP route returns only the first set.

```sql
CALL sp_get_user_api_activity_summary('usr-...', 30);
```

## Activity log

### `sp_log_activity`

Inserts one row. Looks up `p_activity_code` in `activity_catalog` (active rows only) to fill
`activity_catalog_id` and `severity_level`; unknown codes get `info` and no catalog link.

### `sp_get_activity_logs`

Newest first, enriched with the acting user, project, target user, user group and catalog fields
(22 columns). Filters are exact except `p_search`, which matches part of `activity_type`,
`details` or the acting username. `p_days` is required: `NULL` matches nothing.

```sql
-- Permission grants in the last 30 days
CALL sp_get_activity_logs(100, 0, NULL, NULL, 'permission_grant', 30, NULL);

-- Free-text search
CALL sp_get_activity_logs(50, 0, NULL, NULL, NULL, 7, 'alice');
```

### `sp_count_activity_logs`

Same filters as `sp_get_activity_logs`. Returns `total_count`.

### `sp_get_recent_security_events`

Rows with `severity_level` `warning` or `critical` from the last `p_hours` hours, newest first.
Returns `id`, `user_id`, `activity_type`, `details`, `ip_address`, `severity_level`, `created_at`,
`username`, `activity_name`, `activity_description`.

```sql
CALL sp_get_recent_security_events(24, 100);
```

### Catalog and summary procedures

- `sp_get_activity_catalog(p_category)` lists active catalog rows, optionally for one category.
- `sp_get_activity_by_code(p_activity_code)` returns one catalog row.
- `sp_get_activity_stats(p_project_id, p_days)` counts rows and distinct users per catalog
  category and severity.
- `sp_get_user_activity_summary(p_user_id, p_days)` counts one user's rows per catalog category
  and name, with the latest time.

### `sp_cleanup_old_activity_logs`

Deletes `info` rows older than `p_retention_days`; `warning` and `critical` rows are kept. With
`p_dry_run = TRUE` it only reports how many rows would go.

```sql
CALL sp_cleanup_old_activity_logs(365, TRUE);
```

## Email delivery logs

`GET /admin/email/logs` has no procedure. It runs an inline query in
`db_email.list_email_delivery_logs`:

```sql
SELECT em.id, em.user_id, em.user_email_id, em.purpose, em.template_code,
       HEX(em.recipient_hash) AS recipient_hash, em.recipient_masked,
       em.provider, em.provider_message_id, em.status, em.priority,
       em.attempt_count, em.max_attempts, em.next_attempt_at, em.sent_at,
       em.terminal_at, em.last_error_code, em.created_at, em.updated_at
FROM email_messages em
-- optional: WHERE em.status = ? AND em.purpose = ? AND em.provider = ?
ORDER BY em.created_at DESC
LIMIT ? OFFSET ?;
```

The query never selects `recipient_email`, `last_error_message`, `render_payload_ciphertext`,
`provider_idempotency_key` or `token_id`.
