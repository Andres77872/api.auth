# Audit logs request flow

How a request is recorded, and how each read endpoint assembles its answer. Components and
tables are described in [architecture.md](architecture.md).

## Capturing a request

Middleware runs outermost first: `AuthContextMiddleware`, then `APIAuditMiddleware`, then
`RequestValidationMiddleware` and CORS, then the route.

```text
request
  -> AuthContextMiddleware
       X-API-Key present (and path is not /auth/validate or /auth/validate-api-key)?
         validate the key -> request.state.user, session_id = key ID, auth_method = "api_key"
       else Bearer token or access_token cookie?
         validate_session -> request.state.user, session_id = the token's session_id claim, auth_method = "session"
       never rejects the request
  -> APIAuditMiddleware
       skip if OPTIONS, or path is /ping, /health, /metrics, /docs, /redoc, /openapi.json,
       /auth/validate or /webhooks/email (exact or sub-path)
       read user, session_id (never token bytes), project and auth_method from request.state
       redact headers, query and JSON body
       CALL sp_log_api_request  (synchronous, before the route runs; response_status = 0)
  -> RequestValidationMiddleware, CORS, route handler
  <- response
       compute security_event and tags from path, method, status and user type
       attach a background task: CALL sp_update_api_response
         (status, is_success, duration, tags, security_event, resource guess)
  <- response sent, then the background task runs
```

Consequences:

- A request is recorded even if the handler crashes. Requests rejected
  by `RequestValidationMiddleware` (missing `User-Agent`, body over 8 MiB) are recorded too.
- Until the background task runs, the row shows `response_status = 0` and `is_success = null`.
- The middleware receives the response as a stream. For a `4xx`/`5xx` JSON body of at most
  64 KiB it drains the stream, records `error_code`, `error_message` and the redacted
  `response_body`, and replays the same bytes to the client. When an unhandled exception
  escapes, the response row is written at once with status `500` and the exception class name.
- A failure to write the audit row is logged and ignored; the request still proceeds.

## Writing an activity entry

Activity rows come from three places:

```text
@log_and_handle_errors(operation_name, activity_type, log_success)
  handler has a `credentials` parameter?
    validate_session -> LogContext (user, project)
  run the handler
    success and log_success and activity_type -> ActivityLogger.log_activity(...)
    AppException or unexpected error and activity_type -> log_activity(..., success = false)

services (email, OAuth, Patreon, billing, password flows)
  -> ActivityLogger.log_activity(...) with domain details

database triggers on users, projects, groups, memberships, roles, permissions, sessions, API keys
  -> INSERT INTO activity_logs (id = 'act-log-{uuid}')
```

`ActivityLogger.log_activity` calls `sp_log_activity`, which looks up the type in
`activity_catalog` to set `activity_catalog_id` and `severity_level` (`info` when not found). A
failure to write is logged and ignored.

The decorator records `details` as `{"operation", "success", "duration_seconds", "request_id"}`,
plus `error_code` and `error_message` on failure. Read-only audit routes pass `activity_type=None`,
so reading logs writes no activity rows. The dashboard routes pass `admin_action` with
`log_success=False`, so only their failures (for example a `403`) are logged.

## Reading endpoints

Every handler first checks that the caller's user type is root or admin (`403` `AUTHZ_2001`
otherwise).

### Activity feed

```text
GET /admin/activity
  -> sp_get_activity_logs(limit, offset, user_id, project_id, activity_type, days, search)
  -> sp_count_activity_logs(user_id, project_id, activity_type, days, search)
  -> format rows (user / project / target_user objects), has_more = offset + limit < total
```

### API audit logs

```text
GET /admin/audit/logs
  -> sp_get_audit_logs(limit, offset, filters..., days)
  -> sp_count_audit_logs(filters..., days)
  -> has_more = offset + limit < total
```

### Security events

```text
GET /admin/audit/security-events
  source is null or api_audit:
    sp_get_security_events(limit, 0, days)       rows with security_event = true
    severity from status; drop rows not matching `severity`
  source is null or activity_log:
    sp_get_recent_security_events(days * 24, limit)   rows with severity warning or critical
    drop rows not matching `severity`
  merge, sort by timestamp descending, keep the first `limit`
  summary counts are computed on the kept events
```

### Statistics

```text
GET /admin/audit/statistics
  -> sp_get_audit_statistics(days)   four result sets: overview, by method, top 20 endpoints,
                                     status distribution
  -> success_rate = successful / total * 100
```

### User activity

```text
GET /admin/users/{user_id}/activity
  -> get_user_by_id                                   404 NF_4001 if missing
  -> sp_get_activity_logs(500, 0, user_id, ...)       rows where the user is the actor
       group by category and name -> activity_summary
  -> sp_get_user_api_activity_summary(user_id, days)  totals (endpoint breakdown is not returned)
  -> sp_get_audit_logs(50, 0, user_id, ...)           audit rows for the timeline
  -> timeline = first 50 activity rows + 50 audit rows, sorted newest first
```

### Email delivery logs

```text
GET /admin/email/logs
  -> db_email.list_email_delivery_logs   inline SELECT of 19 redacted columns from email_messages,
                                         optional exact filters, ORDER BY created_at DESC
  -> has_more = (returned == limit); no count query
```

### Export

```text
POST /admin/audit/export
  parse JSON body                       400 VAL_3001 if not JSON
  source and format present             400 VAL_3002
  source and format valid               400 VAL_3012
  limit in 1..10000 (default 1000)      400 VAL_3009
  count matching rows (sp_count_audit_logs or sp_count_activity_logs)
    more than 10,000                    400 VAL_3009
  fetch up to `limit` rows (sp_get_audit_logs or sp_get_activity_logs)
  stream CSV (fixed columns) or a JSON array (all fields) as an attachment
```

The count and the fetch are separate queries, so rows written in between can appear in the file.
