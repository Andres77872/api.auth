# Audit logs architecture

The components that record and serve audit data, the tables they use, and the design limits that
follow. Step-by-step request handling is in [request-flow.md](request-flow.md).

## Components

| Component | File | Role |
| --- | --- | --- |
| `AuthContextMiddleware` | `src/middleware/auth_context.py` | Resolves the caller from `X-API-Key` or the access token and stores it on `request.state`. Never rejects. |
| `APIAuditMiddleware` | `src/middleware/api_audit.py` | Writes one `api_audit_log` row per request and completes it after the response |
| `APIAuditLogger` | `src/Util/api_audit_logger.py` | Exclusion list, redaction, security-event rules, tags, and the calls to `sp_log_api_request` / `sp_update_api_response` |
| `@log_and_handle_errors` | `src/Util/decorators.py` | Validates the session for handlers that take `credentials`, and writes an activity row for the configured `activity_type` |
| `ActivityLogger`, `ActivityType` | `src/Util/activity_logger.py` | Writes and reads `activity_logs` through stored procedures; the enum has 112 members |
| Database triggers | `schemas/triggers/01_activity_logging_triggers.sql`, `schemas/triggers/02_permission_activity_triggers.sql`, `schemas/triggers/03_api_key_activity_triggers.sql` | Write activity rows when users, projects, groups, memberships, roles, permissions, sessions or API keys change |
| Audit analytics queries | `src/Util/db/db_audit_analytics.py` | Wrappers for the `api_audit_log` read procedures |
| Export | `src/Util/audit_export.py` | Validation, the `10,000` record cap, CSV and JSON streaming |
| Routes | `src/routes/audit_logs.py`, `src/routes/admin_dashboard.py` | The read and export endpoints |

`src/middleware/activity_logging.py` defines `ActivityLoggingMiddleware`, which would put the client
IP and user agent in a context variable for activity logging. It is not registered in
`src/main.py`.

## Tables

| Table | Key columns | Notes |
| --- | --- | --- |
| `api_audit_log` | `id` (`audit-{uuid}`), `request_id`, `http_method`, `endpoint_path`, `user_id`, `user_type`, `session_id`, `auth_method`, request and response bodies, headers and sizes, timestamps, `duration_ms`, `client_ip`, `is_success`, `error_code`, `project_id`, `tags`, `security_event` | Defined in `schemas/tables/02_create_tables.sql`. Indexed by time, user, endpoint, status, success, project, request ID and security flag. `auth_method` (`session`, `api_key`, `anonymous`, `email_link`, `webhook`, `oauth`) and headers are stored but no read route returns them. |
| `activity_logs` | `id`, `user_id`, `activity_type` (`VARCHAR(50)`), `activity_catalog_id`, `details` (text), `project_id`, `user_group_id`, `target_user_id`, `ip_address`, `user_agent`, `metadata`, `severity_level` (`info`, `warning`, `critical`), `created_at` | Defined in `schemas/tables/08_activity_logging_tables.sql`. Application rows use `act-{32 hex}` IDs; trigger rows use `act-log-{uuid}`. |
| `activity_catalog` | `id` (`act-cat-NNN`), `activity_code`, `activity_name`, `activity_category`, `severity_level`, `requires_audit`, `is_active` | 111 seeded rows; the source of each type's severity |
| `permission_audit_log` | Permission change history | Written only by `sp_log_permission_change`, which the application does not call |
| `email_messages` | Outbox ledger | Owned by the [email suite](../email/architecture.md); read here through `GET /admin/email/logs` |

The procedures behind these tables are listed in [stored-procedures.md](stored-procedures.md).

## Security events

Two different notions exist:

- **API audit**: `api_audit_log.security_event` is set per request by
  `APIAuditLogger.is_security_event` (rules in
  [reference.md](reference.md#security-event-rules)). Severity is derived later, at read time,
  from the status code.
- **Activity log**: there is no flag. `sp_get_recent_security_events` returns rows whose
  `severity_level` is `warning` or `critical`, a level copied from the catalog when the row is
  written.

`GET /admin/audit/security-events` reads both and merges them.

## Access model

Every audit route calls a user-type check (`_check_admin_access` in `src/routes/audit_logs.py`,
an inline copy in `src/routes/admin_dashboard.py`): root or admin user type, otherwise `403`
`AUTHZ_2001`. There is no project filter on any query, so admins see all projects. The routes do
not use `verify_admin_access`, so a consumer holding an `admin` permission through a global role
is refused here, unlike on some other admin routes.

## Design decisions and limits

- **Request row first, response row later.** The request row is written synchronously before the
  handler runs, so a crash still leaves a record; the response is written by a background task so
  it does not delay the client.
- **Best effort.** Both loggers catch and log their own failures. A database outage does not fail
  requests, but it leaves gaps in the audit trail.
- **Error details come from the JSON error body.** The response reaches the middleware as a
  stream; for a `4xx`/`5xx` with a JSON body of at most 64 KiB, the middleware drains it, fills
  `error_code`, `error_message` and the redacted `response_body`, and replays the same bytes to
  the client. Other error bodies pass through uncaptured.
- **`route_pattern` is matched up front.** Routing runs after the middleware, so the middleware
  matches the app's routes itself; a path no route matches stays `null`.
- **`session_id` is a label, not a credential.** For session requests the auth middleware stores
  the access token's `session_id` claim; the audit and error loggers reduce anything token-shaped
  to that claim or a `tokhash:` keyed hash (`src/Util/audit_session_id.py`). Older rows hold a
  256-character token prefix, which `get_audit_logs` masks on read (see
  [reference.md](reference.md#existing-rows-with-token-prefixes)).
- **No project isolation.** Admins see every project's audit data.
- **No retention.** `sp_cleanup_old_activity_logs(p_retention_days, p_dry_run)` deletes old `info`
  activity rows, but nothing schedules it. `api_audit_log` has no cleanup procedure.
- **Export is bounded, not paged.** An export reads at most `10,000` rows in one query and refuses
  filters that match more, instead of paging through large results.
- **Activity details are free text.** Decorator rows store JSON text in `details`; trigger rows
  store a sentence and put structured data in `metadata`.
- **Triggers do not know the actor.** They take `user_id` from the changed row (for example
  `created_by`, or the updated user itself for `user_update` and `user_type_changed`). To find
  who made a change, match the time against `GET /admin/audit/logs`. Triggers in
  `schemas/triggers/01_activity_logging_triggers.sql` also leave `activity_catalog_id` empty, so
  those rows have no catalog name or category.
