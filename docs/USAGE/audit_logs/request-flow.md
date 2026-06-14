# Audit Logs Request and Data Flow

End-to-end runtime flows for the audit and activity logging systems in `api.auth`.

---

## Flow 1: HTTP Request Captured by Middleware

```
HTTP Request arrives
  └─► APIAuditMiddleware.dispatch()
        ├─► Check: APIAuditLogger.should_log_request(path, method)?
        │     ├─► Excluded paths: /ping, /health, /metrics, /docs, /redoc, /openapi.json
        │     └─► Excluded methods: OPTIONS
        │
        ├─► If excluded: call_next(endpoint) — no logging
        │
        └─► If not excluded:
              ├─► Generate audit_id, request_id (from X-Request-ID header or new)
              ├─► Extract user context from request.state (user_id, user_type, session_id, project_id)
              ├─► Extract client_ip (X-Forwarded-For > X-Real-IP > direct)
              ├─► Read request body (POST/PUT/PATCH/DELETE only, re-populate for downstream)
              ├─► Extract route_pattern from request.scope
              │
              ├─► APIAuditLogger.log_request() — SYNCHRONOUS, immediate
              │     └─► INSERT into api_audit_log (request side)
              │
              ├─► call_next(endpoint) — process the request
              │
              └─► After response:
                    ├─► Calculate duration_ms
                    ├─► Extract error_code/error_message from response body (if status >= 400)
                    ├─► Extract resource_type/resource_id from path
                    ├─► Determine is_security_event (path + method + status + user_type)
                    ├─► Generate tags (path, method, status, user_type)
                    │
                    └─► Background task: APIAuditLogger.log_response()
                          ├─► Filter sensitive data from error response body
                          └─► UPDATE api_audit_log (response side)
```

**Key detail:** the request is logged synchronously before the endpoint runs. This guarantees the request is captured even if the endpoint crashes. The response is logged as a background task to avoid blocking the response.

---

## Flow 2: Semantic Activity Logging via Decorator

```
Route handler invocation
  └─► @log_and_handle_errors(operation_name, activity_type, log_success)
        ├─► Execute the wrapped handler
        │
        ├─► On success:
        │     └─► If activity_type is not None AND log_success is True:
        │           └─► ActivityLogger.log_activity(activity_type, details, ...)
        │                 └─► INSERT into activity_logs
        │
        └─► On error:
              └─► ActivityLogger.log_error_activity(operation_name, error, ...)
                    └─► INSERT into activity_logs with error details
```

**Key detail:** read-only audit endpoints pass `activity_type=None` and `log_success=False` to avoid creating activity log entries for audit reads.

---

## Flow 3: Security Event Aggregation

```
GET /admin/audit/security-events
  └─► _check_admin_access() — root or admin only
  │
  ├─► Fetch from api_audit_log (unless source=activity_log filter)
  │     └─► get_security_events(limit, offset=0, days)
  │           └─► sp_get_security_events — returns rows with security_event=TRUE
  │     └─► For each entry:
  │           ├─► Derive severity from response_status (401→warning, 403→critical, 5xx→warning, else→info)
  │           ├─► Derive event_type from error_code or tags
  │           └─► Normalize to common shape with source="api_audit"
  │
  ├─► Fetch from activity_logs (unless source=api_audit filter)
  │     └─► get_activity_security_events(p_hours=days*24, p_limit)
  │           └─► sp_get_recent_security_events — returns rows with severity_level
  │     └─► For each entry:
  │           ├─► Use severity_level from the row
  │           └─► Normalize to common shape with source="activity_log"
  │
  ├─► Merge both lists
  ├─► Sort by timestamp descending
  ├─► Apply limit to final merged result (NOT per-source)
  │
  └─► Return: events[], summary{total, by_source, by_severity, period_hours}
```

**Key detail:** the limit applies to the **merged** result, not per-source. If you request 100 events, you get up to 100 total from both sources combined.

---

## Flow 4: Export

```
POST /admin/audit/export (JSON body)
  └─► _check_admin_access() — root or admin only
  │
  ├─► Parse JSON body: source, format, limit, filters
  │
  ├─► Validate:
  │     ├─► source in {activity, audit, api_audit}
  │     ├─► format in {csv, json}
  │     └─► limit <= 10,000 (EXPORT_HARD_LIMIT)
  │
  ├─► Pre-export count check:
  │     └─► _check_export_count(source, filters, limit)
  │           ├─► If source=audit/api_audit: count_audit_logs(filters)
  │           └─► If source=activity: count_activity_logs(filters)
  │     └─► If count > 10,000 → 400 INVALID_RANGE
  │
  ├─► Generate filename: audit_export_{source}_{timestamp}.{format}
  │
  └─► Stream response:
        ├─► If format=csv:
        │     └─► stream_csv_export(source, filters, limit)
        │           ├─► _fetch_export_data() — get rows
        │           ├─► Yield header row
        │           └─► Yield data rows (one per row)
        │
        └─► If format=json:
              └─► stream_json_export(source, filters, limit)
                    ├─► _fetch_export_data() — get rows
                    ├─► Yield "["
                    ├─► Yield each row as JSON object (JSON Lines)
                    └─► Yield "]"
```

**Key detail:** the export uses a **pre-export count check** before streaming. If the count exceeds 10,000, the request is rejected with 400 — no partial export occurs.

---

## Flow 5: User Activity Merge

```
GET /admin/users/{user_id}/activity
  └─► _check_admin_access() — root or admin only
  │
  ├─► Check user exists → 404 if not found
  │
  ├─► Fetch activity log summary:
  │     └─► get_recent_activity(limit=500, offset=0, user_id, days)
  │     └─► Group by activity_category::activity_name
  │     └─► Count and track last_activity per group
  │     └─► Sort by count descending
  │
  ├─► Fetch API audit summary:
  │     └─► get_user_api_activity_summary(user_id, days)
  │           └─► sp_get_user_api_activity_summary
  │           └─► Returns: summary{total_requests, success_count, failure_count, ...}
  │                 + endpoint_activity[] (top endpoints)
  │
  ├─► Fetch API audit timeline entries:
  │     └─► get_audit_logs(limit=50, offset=0, user_id, days)
  │
  ├─► Build combined timeline:
  │     ├─► Add up to 50 activity_log entries (source="activity_log")
  │     ├─► Add up to 50 api_audit entries (source="api_audit")
  │     └─► Sort by timestamp descending
  │
  └─► Return: user_id, summary{total_activities, activity_log_count, api_audit_count, activity_summary, api_audit_summary}, timeline[]
```

**Key detail:** the timeline is a **fixed-size merge** — up to 50 entries from each source, sorted together. There is no pagination.

---

## Flow 6: Audit Statistics

```
GET /admin/audit/statistics
  └─► _check_admin_access() — root or admin only
  │
  ├─► Validate days in range 1-365
  │
  ├─► get_audit_statistics(days)
  │     └─► sp_get_audit_statistics(days)
  │           └─► Returns 4 result sets:
  │                 1. overview — total_requests, success_count, failure_count, avg_duration_ms
  │                 2. by_method — [{method, count, success_rate}]
  │                 3. top_endpoints — [{endpoint, count, success_rate, avg_duration_ms}]
  │                 4. status_distribution — [{status_code, count}]
  │
  └─► Return: {overview, by_method, top_endpoints, status_distribution, generated_at}
```

---

## Flow 7: Email Delivery Log Query

```
GET /admin/email/logs
  └─► _check_admin_access() — root or admin only
  │
  ├─► db_email.list_email_delivery_logs(limit, offset, status, purpose, provider)
  │     └─► Inline SELECT (no stored procedure):
  │           SELECT id, user_id, user_email_id, purpose, template_code,
  │                  HEX(recipient_hash) AS recipient_hash, recipient_masked,
  │                  provider, provider_message_id, status, priority,
  │                  attempt_count, max_attempts, next_attempt_at, sent_at,
  │                  terminal_at, last_error_code, created_at, updated_at
  │           FROM email_messages
  │           [WHERE status=? AND purpose=? AND provider=?]   -- only present filters
  │           ORDER BY created_at DESC
  │           LIMIT ? OFFSET ?
  │
  └─► Return: { success, logs[], pagination, filters, generated_at }
        └─► pagination.has_more = (len(logs) == limit)   -- page-fill heuristic, NO count query
        └─► pagination.next_offset = offset + limit if has_more else null
```

**Key detail:** this flow has **no count query**. `has_more` is derived purely from whether the returned page is full (`len(logs) == limit`), so an exactly-full final page reports `has_more: true` even though the next page is empty. The query selects only redacted columns — the plaintext recipient, body, template variables, and provider payloads in `email_messages` are never read.

---

## Related Documentation

- **[Audit Logs Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: June 2026
**Document Version**: 1.1
