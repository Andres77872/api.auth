# Proposal: Audit Log Monitor API

## Intent

Provide a complete HTTP API surface for the Magic Auth Dashboard's audit-log monitor feature, exposing both existing logging systems (`activity_logs` and `api_audit_log`) as queryable, filterable, and exportable endpoints. Currently, `api_audit_log` has **zero HTTP endpoints** despite having 8 stored procedures, and `activity_logs` is missing search, detail view, and user-specific activity endpoints. This change closes the gap between the data layer and the dashboard frontend.

## Scope

### In Scope

- **Enhance `GET /admin/activity`** — Add `search` query param (free-text across activity_type, details, username)
- **New `GET /admin/activity/{activity_id}`** — Single activity detail lookup
- **New `GET /admin/audit/logs`** — Paginated, filtered API audit log listing (wraps `sp_get_audit_logs` + `sp_count_audit_logs`)
- **New `GET /admin/audit/security-events`** — Combined security events from BOTH `api_audit_log` (security_event=true) and `activity_logs` (severity warning/critical), with summary counts
- **New `GET /admin/audit/statistics`** — Audit statistics (total requests, success rate, avg duration, by method, top endpoints, status distribution) via `sp_get_audit_statistics`
- **New `POST /admin/audit/export`** — CSV/JSON export of activity or audit logs with filters, enforcing a hard record limit
- **New `GET /admin/users/{user_id}/activity`** — User-specific activity summary and timeline
- **Modify stored procedures** — Add `search` parameter support to `sp_get_activity_logs` and `sp_count_activity_logs` in `11_activity_logging.sql`
- **New DB wrapper module** — `src/Util/db/db_audit_analytics.py` wrapping all `api_audit_log` stored procedures
- **New export utility** — `src/Util/audit_export.py` for CSV/JSON formatting and streaming
- **Register new router** — `include_router(audit_logs.router)` in `src/main.py`

### Out of Scope

- New database tables or schema changes (all tables and SPs exist)
- Retention policy for `api_audit_log` table (no equivalent to `sp_cleanup_old_activity_logs` yet)
- Rate limiting middleware (error code `INT_7005` exists but no implementation — deferred)
- SSE/WebSocket for real-time updates (frontend polling at 30s is sufficient)
- Admin scope filtering per project (admin scope is **global** for this feature per user clarification)
- Frontend dashboard implementation (separate change)

## Approach

### Architecture

**Separate router pattern** (recommended over adding to `admin_dashboard.py`):
- New `src/routes/audit_logs.py` with its own `APIRouter(prefix="/admin")` for clean separation
- New `src/Util/db/db_audit_analytics.py` following the existing `db_session_analytics.py` pattern
- New `src/Util/audit_export.py` for export formatting logic

### Auth Model

All endpoints require `root` or `admin` user type (same pattern as existing `admin_dashboard.py`). Per user clarification, **admin scope is global** for this feature — admins see all data, same as root.

### Security Events

The `/admin/audit/security-events` endpoint merges two sources:
1. **`api_audit_log`** — via `sp_get_security_events` (security_event=true), severity derived from status code (401→warning, 403→critical, 5xx→warning) and/or event type
2. **`activity_logs`** — via `sp_get_recent_security_events` (severity warning/critical), already has severity

Results are normalized to a common shape with `source` field indicating origin (`api_audit` or `activity_log`).

### Stored Procedure Modifications

- **`sp_get_activity_logs`** (11_activity_logging.sql): Add `p_search VARCHAR(255)` parameter with `LIKE` matching on `activity_type`, `details`, `u.username`
- **`sp_count_activity_logs`** (11_activity_logging.sql): Add matching `p_search` parameter for accurate pagination counts
- No new SPs needed — all others already exist and are sufficient

### Export Hard Limit

Export endpoint enforces a configurable hard limit (default: 10,000 records). Requests exceeding the limit return a 400 with a clear error message.

## Affected Areas

| Area | Impact | Description |
|------|--------|-------------|
| `src/routes/audit_logs.py` | **New** | Router for all `/admin/audit/*` endpoints (logs, security-events, statistics, export) |
| `src/routes/admin_dashboard.py` | Modified | Add `search` param to `GET /admin/activity`; add `GET /admin/activity/{activity_id}` |
| `src/Util/db/db_audit_analytics.py` | **New** | DB wrappers for `api_audit_log` SPs: `get_audit_logs`, `count_audit_logs`, `get_audit_statistics`, `get_security_events`, `get_failed_requests`, `get_user_activity_summary` |
| `src/Util/db/__init__.py` | Modified | Export new functions from `db_audit_analytics` |
| `src/Util/audit_export.py` | **New** | CSV/JSON export utility with hard limit enforcement |
| `src/main.py` | Modified | Add `include_router(audit_logs.router)` |
| `schemas/stored_procedures/11_activity_logging.sql` | Modified | Add `p_search` param to `sp_get_activity_logs` and `sp_count_activity_logs` |

## Risks

| Risk | Likelihood | Mitigation |
|------|------------|------------|
| **Multi-result-set handling** — `sp_get_audit_statistics` returns 4 result sets; `sp_get_user_activity_summary` returns 2 | Medium | Use `cursor.nextset()` between result sets in DB wrapper (pattern already exists in `db_session_analytics.py:get_user_login_statistics`) |
| **SP signature change** — Adding `p_search` param breaks existing callers of `sp_get_activity_logs` | Low | System is still in design phase with no meaningful data (per user). All existing callers are in `activity_logger.py` — update them to pass `None` for search |
| **Export memory pressure** — Streaming 10K rows as CSV could spike memory | Medium | Use `StreamingResponse` with generator-based row formatting; never load all rows into memory at once |
| **Security event normalization** — Merging two different schemas into one response shape | Medium | Define a unified `SecurityEvent` response model; map fields explicitly with clear `source` indicator |
| **SP parameter mismatch** — `sp_get_recent_security_events` uses `p_hours` while others use `p_days` | Low | Wrapper converts `days` param to hours (`days * 24`) before calling the SP |
| **Duplicate SP names** — `sp_get_user_activity_summary` exists in BOTH `07_sessions_analytics.sql` and `11_activity_logging.sql` with different signatures | Medium | The MySQL `DROP PROCEDURE IF EXISTS` means the later-loaded version wins. Verify load order in schema scripts; use the correct one for each data source |

## Rollback Plan

1. **Revert code changes**: `git revert` the commit(s) adding `audit_logs.py`, `db_audit_analytics.py`, `audit_export.py`, and modifications to `admin_dashboard.py`, `main.py`, `__init__.py`
2. **Revert SP changes**: Re-run `11_activity_logging.sql` from the pre-modification version (or manually `DROP` and recreate the two modified SPs without the `p_search` parameter)
3. **No data migration needed**: All changes are additive (new endpoints, new SP params) — no data is modified or deleted
4. **Verification**: After rollback, confirm `GET /admin/activity` still works without the `search` param and all existing endpoints are unaffected

## Dependencies

- **Internal**: `src/Util/activity_logger.py` — existing `get_recent_activity`, `count_activity_logs` functions
- **Internal**: `src/Util/api_audit_logger.py` — existing `APIAuditLogger` class
- **Internal**: `src/Util/db/db_session_analytics.py` — pattern reference for multi-result-set handling
- **Internal**: `src/middleware/authentication.py` — `verify_session`, auth guards
- **Internal**: `src/Util/Seccurity.py` — `HTTPBearerOrCookie` security scheme
- **Internal**: `src/Util/error_handler.py` — `AuthorizationError`, `ErrorCode`
- **Internal**: `src/Util/decorators.py` — `log_and_handle_errors`
- **External**: No new dependencies required

## Open Questions

- [NEEDS CLARIFICATION: What should the export hard limit default be? Proposing 10,000 records — is this acceptable or should it be higher/lower?]
- [NEEDS CLARIFICATION: For the duplicate `sp_get_user_activity_summary` (exists in both 07_sessions_analytics.sql for api_audit_log and 11_activity_logging.sql for activity_logs), should the `/admin/users/{user_id}/activity` endpoint call BOTH and merge results, or just one source?]

## Success Criteria

- [ ] `GET /admin/activity` accepts `search` param and returns filtered results matching free-text query
- [ ] `GET /admin/activity/{activity_id}` returns a single activity with full metadata
- [ ] `GET /admin/audit/logs` returns paginated, filtered API audit logs matching the response shape defined in exploration
- [ ] `GET /admin/audit/security-events` returns combined events from both `api_audit_log` and `activity_logs` with correct summary counts
- [ ] `GET /admin/audit/statistics` returns 4-section statistics (overview, by_method, top_endpoints, status_distribution)
- [ ] `POST /admin/audit/export` returns CSV or JSON with correct Content-Disposition header and enforces hard limit
- [ ] `GET /admin/users/{user_id}/activity` returns user summary + activity timeline
- [ ] All endpoints require root/admin auth and reject unauthenticated/unauthorized requests
- [ ] All new DB functions follow the `handle_db_operation` error-wrapping pattern
- [ ] Stored procedure modifications do not break existing `activity_logger.py` callers
