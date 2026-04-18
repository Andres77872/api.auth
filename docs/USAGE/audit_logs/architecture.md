# Audit Logs Architecture

Technical architecture of the audit and activity logging systems as they actually exist in `api.auth`.

---

## Data Sources

### Source A: `activity_logs` Table

| Aspect | Detail |
|--------|--------|
| **Populated by** | `ActivityLogger` class via `@log_and_handle_errors` decorator |
| **Decorator location** | `src/Util/activity_logger.py` |
| **Granularity** | Semantic operations (e.g., `user_login`, `project_creation`, `permission_grant`) |
| **Activity types** | 29 enum values in `ActivityType` |
| **Stored procedures** | `sp_get_activity_logs`, `sp_count_activity_logs`, `sp_get_recent_security_events` |

**Core schema fields:** `id`, `user_id`, `activity_type`, `details`, `project_id`, `user_group_id`, `target_user_id`, `ip_address`, `user_agent`, `metadata`, `severity_level`, `created_at`

**Enriched fields** (added at query time): `username`, `user_hash`, `project_name`, `project_hash`, `target_username`, `target_user_hash`, `user_group_name`, `activity_name`, `activity_category`, `activity_description`

### Source B: `api_audit_log` Table

| Aspect | Detail |
|--------|--------|
| **Populated by** | `APIAuditMiddleware` (`src/middleware/api_audit.py`) |
| **Granularity** | Raw HTTP request/response pairs |
| **Scope** | Every HTTP request except excluded paths |
| **Stored procedures** | `sp_get_audit_logs`, `sp_count_audit_logs`, `sp_get_audit_statistics`, `sp_get_security_events`, `sp_get_failed_requests`, `sp_get_user_api_activity_summary` |

**Core schema fields:** `id`, `request_id`, `http_method`, `endpoint_path`, `route_pattern`, `user_id`, `user_type`, `session_id`, `request_body`, `request_query`, `request_size_bytes`, `response_status`, `response_body`, `response_size_bytes`, `request_timestamp`, `response_timestamp`, `duration_ms`, `client_ip`, `user_agent`, `referer`, `is_success`, `error_code`, `error_message`, `project_id`, `target_resource_type`, `target_resource_id`, `metadata`, `tags`, `security_event`

**Enriched fields** (added at query time): `username`, `user_hash`, `project_name`, `project_hash`

**Excluded paths** (not logged): `/ping`, `/health`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`

**Excluded methods:** `OPTIONS` (CORS preflight)

**Sensitive data filtering:** Passwords, tokens, API keys are masked as `***FILTERED***` in request/response bodies and headers. This is intentional and cannot be disabled.

### Security Event Detection

The middleware flags requests as security events when:

- 401 on `/auth/` paths
- Any 403
- Any `/admin/` path with root/admin user
- Any DELETE request
- Paths containing `/user-type`, `/permissions`, `/roles`
- Paths containing `/password` or `/reset`

---

## Route Organization

### Dedicated Audit Endpoints (`src/routes/audit_logs.py`, 572 lines)

All routes use `APIRouter(prefix="/admin")` — they coexist with `admin_dashboard.py` under the same `/admin` prefix.

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| GET | `/admin/audit/logs` | `list_audit_logs()` | Paginated API audit logs from `api_audit_log` |
| GET | `/admin/audit/security-events` | `list_security_events()` | Combined security events from BOTH sources |
| GET | `/admin/audit/statistics` | `get_statistics()` | 4-section audit analytics |
| POST | `/admin/audit/export` | `export_logs()` | CSV/JSON export, max 10,000 records |
| GET | `/admin/users/{user_id}/activity` | `get_user_activity()` | Per-user combined activity summary + timeline |

### Admin Dashboard Activity Endpoints (`src/routes/admin_dashboard.py`, 542 lines)

| Method | Path | Handler | Purpose |
|--------|------|---------|---------|
| GET | `/admin/activity` | `get_activity_feed()` | Activity feed from `activity_logs` table |
| GET | `/admin/activity/{activity_id}` | `get_activity_detail()` | Single activity log detail by ID |
| GET | `/admin/activity/types` | `get_activity_types()` | Enum of all activity types |

---

## Logging Mechanisms

### Middleware Logging (`APIAuditMiddleware`)

```
HTTP Request
  └─► APIAuditMiddleware.dispatch()
        ├─► Check: should_log(path, method)?
        ├─► Generate audit_id, request_id
        ├─► Extract user context from request.state
        ├─► APIAuditLogger.log_request() — immediate, synchronous
        ├─► call_next(endpoint)
        └─► Background task: APIAuditLogger.log_response()
              └─► Filters sensitive data from error responses
```

The request is logged **immediately and synchronously** before the endpoint runs. The response is logged as a **background task** after the endpoint completes. This ensures the request is always captured even if the endpoint crashes.

### Decorator Logging (`@log_and_handle_errors`)

```
Route handler
  └─► @log_and_handle_errors(operation_name, activity_type, ...)
        ├─► Execute handler
        ├─► On success: ActivityLogger.log_activity() if activity_type is set
        └─► On error: ActivityLogger.log_error_activity()
```

The decorator wraps individual route handlers. It logs semantic events (not raw HTTP). Read-only endpoints typically pass `activity_type=None` and `log_success=False` to skip activity logging.

---

## Auth Model

All audit endpoints require **root or admin** user type:

```python
def _check_admin_access(log_context: LogContext) -> None:
    user_type = get_user_type(log_context.user_id)
    is_root = is_root_user(log_context.user_id)
    if not is_root and user_type != 'admin':
        raise AuthorizationError(
            message="Admin access required",
            error_code=ErrorCode.ACCESS_DENIED,
        )
```

**Auth mechanism:** `HTTPBearerOrCookie()` — accepts `Authorization: Bearer <token>` OR `Cookie: session_token=<token>`.

**CRITICAL: No project scoping.** Any admin can see ALL audit logs across ALL projects. There is no project-level access check. This is a data isolation gap.

---

## Data Flow Diagram

```
                         ┌─────────────────────────┐
                         │   HTTP Request          │
                         └───────────┬─────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
                    ▼                ▼                ▼
         ┌──────────────────┐  ┌────────────┐  ┌──────────────┐
         │ APIAuditMiddleware│  │ Auth Check │  │ Excluded?    │
         │ (api_audit.py)   │  │            │  │ (skip log)   │
         └────────┬─────────┘  └─────┬──────┘  └──────────────┘
                  │                  │
                  ▼                  ▼
         ┌──────────────────┐  ┌────────────────────┐
         │ api_audit_log    │  │ Route Handler      │
         │ (raw HTTP)       │  │ @log_and_handle_   │
         │                  │  │ errors             │
         └────────┬─────────┘  └─────────┬──────────┘
                  │                      │
                  │                      ▼
                  │             ┌────────────────────┐
                  │             │ activity_logs      │
                  │             │ (semantic events)  │
                  │             └─────────┬──────────┘
                  │                       │
                  ▼                       ▼
         ┌─────────────────────────────────────────────┐
         │              Query Endpoints                │
         │  /admin/audit/logs        /admin/activity   │
         │  /admin/audit/security-events (MERGED)      │
         │  /admin/audit/statistics                    │
         │  /admin/audit/export                        │
         │  /admin/users/{id}/activity  (MERGED)       │
         └─────────────────────────────────────────────┘
```

---

## Related Documentation

- **[Audit Logs Overview](README.md)**
- **[Usage](usage.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**
- **[Admin Usage Cases](../admin-usage-cases.md)** — Dashboard, activity feed quick reference
- **[Database Schema](../../../schemas/)** — SQL tables, views, and stored procedures

---

**Last Updated**: April 2026
**Document Version**: 1.0
