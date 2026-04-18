# Exploration: Audit Log Monitor API

**Change**: `audit-log-monitor-api`
**Date**: 2026-04-16
**Scope**: Backend/API surface needed in `api.auth` to support the Magic Auth Dashboard audit-log monitor plan

---

## 1. Backend-Relevant Requirements (from PRD)

### Core Data Sources
The dashboard plan expects **two logging systems**:

| Source | Table | Current API | Status |
|--------|-------|-------------|--------|
| Activity Logs | `activity_logs` | `GET /admin/activity` | **EXISTS** (needs enhancements) |
| API Audit Logs | `api_audit_log` | None | **MISSING** — only stored procedures |

### Requirements Mapping to Backend

| PRD Requirement | Backend Need | Current State |
|-----------------|-------------|---------------|
| **Req 1**: Activity Log Viewing (paginated list) | `GET /admin/activity` | ✅ Exists, returns correct shape |
| **Req 2**: Activity Log Filtering (type, user, project, date, search) | Filter params on activity endpoint | ⚠️ Missing `search` param |
| **Req 3**: Security Events Dashboard (root-only, severity, failed logins, unauthorized) | New endpoint for security events | ❌ No HTTP endpoint (SP exists: `sp_get_recent_security_events`) |
| **Req 4**: Activity Detail View (single activity by ID) | `GET /admin/activity/{id}` | ❌ No single-item endpoint |
| **Req 5**: Audit Statistics (total requests, success rate, avg duration, by method, top endpoints, status distribution) | `GET /admin/audit/statistics` | ❌ No HTTP endpoint (SP exists: `sp_get_audit_statistics`) |
| **Req 6**: Real-time Updates (polling every 30s) | No backend change needed | ✅ Frontend polling on existing endpoints |
| **Req 7**: Export (CSV/JSON with filters) | `POST /admin/audit/export` | ❌ No export endpoint |
| **Req 8**: User Activity Tracking (timeline, summary for specific user) | `GET /admin/users/{id}/activity` | ❌ No HTTP endpoint (SP exists: `sp_get_user_activity_summary`) |
| **Req 9-10**: Responsive + Accessibility | Frontend only | N/A |

---

## 2. Current Reusable Capabilities

### 2.1 Existing Activity Log Endpoint (`GET /admin/activity`)

**File**: `src/routes/admin_dashboard.py` (lines 130-227)

Already provides:
- Pagination: `limit` (1-500), `offset`
- Filters: `activity_type_filter`, `user_id`, `project_id`, `days` (1-365)
- Response shape matches dashboard plan almost exactly:
  ```json
  {
    "activities": [...],
    "pagination": { "total", "limit", "offset", "has_more", "next_offset" },
    "filters": { "activity_type", "user_id", "project_id", "days" },
    "generated_at": "..."
  }
  ```
- Auth: Requires `root` or `admin` user type
- Each activity includes: `id`, `activity_type`, `details`, `created_at`, `user`, `project`, `target_user`, `ip_address`

### 2.2 Activity Types Endpoint (`GET /admin/activity/types`)

**File**: `src/routes/admin_dashboard.py` (lines 298-329)

Returns all `ActivityType` enum values. Already aligned with plan.

### 2.3 Activity Logger Utility

**File**: `src/Util/activity_logger.py` (975 lines)

Rich utility with:
- `ActivityType` enum (28 types, all matching PRD's `ActivityType` union)
- `get_recent_activity()` — paginated, filtered retrieval via `sp_get_activity_logs`
- `count_activity_logs()` — filtered count via `sp_count_activity_logs`
- `get_activity_stats()` — category/severity breakdown via `sp_get_activity_stats`
- `get_activity_catalog()` — catalog entries with severity levels
- `get_activity_by_code()` — single catalog lookup
- Convenience functions exported at module level

### 2.4 API Audit Logger Utility

**File**: `src/Util/api_audit_logger.py` (420 lines)

Already has:
- `APIAuditLogger` class with sensitive data filtering
- `is_security_event()` — determines if request is security-relevant
- `generate_tags()` — generates searchable tags
- `extract_resource_info()` — extracts resource type/ID from path
- `log_request()` / `log_response()` — write to `api_audit_log` via SPs

### 2.5 API Audit Middleware

**File**: `src/middleware/api_audit.py` (334 lines)

Automatically captures ALL HTTP requests/responses to `api_audit_log` table:
- Request: method, path, headers, body, query, IP, user-agent, user context
- Response: status, duration, error code/message, resource info, security flag, tags
- Excludes: `/ping`, `/health`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`, OPTIONS

### 2.6 Stored Procedures (All Exist, No HTTP Layer)

**File**: `schemas/stored_procedures/07_sessions_analytics.sql`

| Stored Procedure | Purpose | Parameters |
|-----------------|---------|------------|
| `sp_get_audit_logs` | Paginated audit logs with filters | limit, offset, user_id, project_id, endpoint_path, http_method, status_code, is_success, security_event, days |
| `sp_count_audit_logs` | Count matching audit logs | Same filters as above |
| `sp_get_audit_statistics` | Multi-result-set statistics | days |
| `sp_get_security_events` | Security-flagged events | limit, offset, days |
| `sp_get_failed_requests` | Failed requests | limit, offset, days |
| `sp_get_user_activity_summary` | User activity from audit logs | user_id, days |
| `sp_log_api_request` | Insert request record | 17 params |
| `sp_update_api_response` | Update with response data | 11 params |

**File**: `schemas/stored_procedures/11_activity_logging.sql`

| Stored Procedure | Purpose |
|-----------------|---------|
| `sp_get_recent_security_events` | Security events from activity_logs (severity warning/critical) |
| `sp_get_user_activity_summary` | User activity summary from activity_logs |
| `sp_get_activity_stats` | Activity stats by category/severity |

### 2.7 Dashboard Stats Endpoint (`GET /admin/dashboard/stats`)

**File**: `src/routes/admin_dashboard.py` (lines 36-127)

Already provides system health, user/project counts, growth metrics. Auth: root/admin.

### 2.8 System Metrics Utility

**File**: `src/Util/system_metrics.py` (393 lines)

Provides `get_system_overview()`, `get_user_statistics()`, `get_project_statistics()`, `get_api_metrics()` (placeholder).

---

## 3. Concrete Gaps and Recommended API Surface

### 3.1 Gap Analysis

| # | Gap | Severity | Effort |
|---|-----|----------|--------|
| G1 | No HTTP endpoints for API audit logs (`api_audit_log` table) | **Critical** | Medium |
| G2 | No security events endpoint (combined from both tables) | **Critical** | Low |
| G3 | No audit statistics endpoint (from `api_audit_log`) | **Critical** | Low |
| G4 | No single activity lookup by ID | Medium | Low |
| G5 | No `search` parameter on `/admin/activity` | Medium | Low |
| G6 | No export endpoint (CSV/JSON) | Medium | Medium |
| G7 | No user-specific activity endpoint (from audit logs) | Low | Low |
| G8 | No admin-scope filtering on activity (admin sees only their projects) | Medium | Medium |

### 3.2 Recommended API Surface

All endpoints under `GET/POST /admin/...` requiring `root` or `admin` auth (existing pattern).

#### A. Enhance Existing: `GET /admin/activity`

**File to modify**: `src/routes/admin_dashboard.py`

Add parameter:
```python
search: Optional[str] = Query(None, description="Free-text search across activity type, details, username")
```

Implementation: Pass to `sp_get_activity_logs` — **[NEEDS CLARIFICATION: does the SP support free-text search?]** If not, add `LIKE` filter on `activity_type`, `details`, and joined `username` columns in a new SP variant or modify the existing one.

#### B. New: `GET /admin/audit/logs` — API Audit Logs

```
GET /admin/audit/logs
  ?limit=50&offset=0
  &user_id=&project_id=
  &endpoint_path=&http_method=
  &status_code=&is_success=&security_event=
  &days=30
```

Response:
```json
{
  "logs": [
    {
      "id": "audit-uuid",
      "request_id": "req-uuid",
      "http_method": "POST",
      "endpoint_path": "/auth/login",
      "user": { "id": "...", "username": "...", "user_hash": "..." } | null,
      "project": { "id": "...", "name": "...", "hash": "..." } | null,
      "response_status": 200,
      "duration_ms": 45,
      "client_ip": "192.168.1.1",
      "user_agent": "...",
      "is_success": true,
      "security_event": false,
      "error_code": null,
      "error_message": null,
      "tags": ["post", "success", "authentication"],
      "request_timestamp": "2026-04-16T...",
      "response_timestamp": "2026-04-16T..."
    }
  ],
  "pagination": { "total", "limit", "offset", "has_more", "next_offset" },
  "filters": { ... },
  "generated_at": "..."
}
```

**DB layer**: Wrap `sp_get_audit_logs` + `sp_count_audit_logs` in new functions in `src/Util/db/` (new file `db_audit_analytics.py` or extend existing).

#### C. New: `GET /admin/audit/security-events` — Security Events (Root Only)

```
GET /admin/audit/security-events
  ?limit=50&offset=0&days=30
```

Response:
```json
{
  "events": [...],  // Combined from api_audit_log (security_event=true) + activity_logs (severity warning/critical)
  "summary": {
    "total_events": 142,
    "failed_logins": 23,
    "unauthorized_attempts": 15,
    "critical_events": 5,
    "last_event_timestamp": "2026-04-16T..."
  },
  "generated_at": "..."
}
```

**DB layer**: Call both `sp_get_security_events` (from 07_sessions_analytics.sql) and `sp_get_recent_security_events` (from 11_activity_logging.sql), merge results.

#### D. New: `GET /admin/audit/statistics` — Audit Statistics (Root Only)

```
GET /admin/audit/statistics?days=30
```

Response (aligned with PRD `AuditStatistics` interface):
```json
{
  "overview": {
    "total_requests": 15420,
    "success_count": 14800,
    "failure_count": 620,
    "success_rate": 95.98,
    "avg_duration_ms": 42.5
  },
  "by_method": [
    { "method": "GET", "count": 10200, "success_rate": 98.2 },
    { "method": "POST", "count": 4100, "success_rate": 92.1 }
  ],
  "top_endpoints": [
    { "endpoint": "/auth/validate", "count": 5200, "success_rate": 99.1, "avg_duration_ms": 12.3 }
  ],
  "status_distribution": [
    { "status_code": 200, "count": 12000, "percentage": 77.8 }
  ],
  "generated_at": "..."
}
```

**DB layer**: Wrap `sp_get_audit_statistics` — it already returns 4 result sets (overview, by method, top endpoints, status distribution).

#### E. New: `GET /admin/activity/{activity_id}` — Single Activity Detail

```
GET /admin/activity/{activity_id}
```

Response: Same shape as individual activity from the list endpoint, with full `metadata` field included.

**DB layer**: New SP or direct query on `activity_logs` by ID.

#### F. New: `POST /admin/audit/export` — Export Activity/Audit Logs

```
POST /admin/audit/export
Body: {
  "source": "activity" | "audit",
  "format": "csv" | "json",
  "filters": { ... same filters as the list endpoints ... }
}
```

Response: `StreamingResponse` with `Content-Disposition: attachment; filename="audit-export-20260416.csv"`

**Implementation**: Query data with filters, format as CSV/JSON server-side, stream response.

#### G. New: `GET /admin/users/{user_id}/activity` — User Activity

```
GET /admin/users/{user_id}/activity?days=30
```

Response:
```json
{
  "user": { "id": "...", "username": "...", "user_hash": "..." },
  "summary": {
    "total_actions": 342,
    "most_common_actions": [
      { "activity_type": "user_login", "count": 120 },
      { "activity_type": "user_update", "count": 45 }
    ],
    "last_active": "2026-04-16T..."
  },
  "activities": [...],  // Same shape as /admin/activity
  "generated_at": "..."
}
```

**DB layer**: Wrap `sp_get_user_activity_summary` (from both 07 and 11 SP files).

### 3.3 Suggested File Structure

```
src/
  routes/
    admin_dashboard.py        # Modify: add search param to /activity
    audit_logs.py             # NEW: /admin/audit/* endpoints
  Util/
    db/
      db_audit_analytics.py   # NEW: wrappers for api_audit_log SPs
    audit_export.py           # NEW: CSV/JSON export utilities
```

---

## 4. Risks, Migrations, Dependencies, Rollout

### 4.1 Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| **api_audit_log table size** — no retention policy defined | Query performance degrades over time | Add pagination limits, consider index on `request_timestamp` + `security_event` |
| **SP returns multiple result sets** — `sp_get_audit_statistics` returns 4 result sets | PyMySQL needs `cursor.nextset()` between them | Handle carefully in DB wrapper layer |
| **No rate limiting** — export endpoint could be abused | Server load, DoS | **[NEEDS CLARIFICATION: should rate limiting be added?]** Error code `INT_7005` exists but no middleware |
| **Sensitive data in audit logs** — request/response bodies may contain PII | Compliance risk | Already filtered by `APIAuditLogger.filter_sensitive_data()` — verify completeness |
| **Form-data vs JSON** — all existing endpoints use `Form(...)`, but export needs JSON body | Inconsistent API style | Use JSON for export endpoint (already done for bulk operations) |
| **Admin scope leakage** — non-root admins might see all audit data | Security vulnerability | Add project-scope filtering for admin users on all new endpoints |

### 4.2 Database Migrations

**No new tables needed.** All tables (`activity_logs`, `api_audit_log`, `activity_catalog`) already exist.

**Stored procedures already exist** for all needed queries. The gap is purely the HTTP layer.

**Recommended index check**:
```sql
-- Verify these indexes exist on api_audit_log
SHOW INDEX FROM api_audit_log;
-- Should have indexes on: request_timestamp, security_event, user_id, is_success, response_status
```

### 4.3 Dependencies

- **Internal**: `src/Util/db/__init__.py` — needs to export new DB functions
- **Internal**: `src/Util/activity_logger.py` — reusable as-is
- **Internal**: `src/Util/api_audit_logger.py` — reusable as-is
- **Internal**: `src/middleware/authentication.py` — `verify_session`, `require_permission` for auth
- **External**: No new dependencies needed

### 4.4 Rollout Strategy

1. **Phase 1** (Low risk): Enhance `/admin/activity` with `search` param, add `/admin/activity/{id}`
2. **Phase 2** (Medium risk): Add `/admin/audit/logs`, `/admin/audit/statistics` — read-only, no data mutation
3. **Phase 3** (Higher risk): Add `/admin/audit/security-events`, `/admin/users/{id}/activity` — combines data from two sources
4. **Phase 4** (Highest risk): Add `/admin/audit/export` — streaming response, potential for heavy queries

Each phase can be deployed independently. All endpoints are read-only except export (which is also read-only, just different response format).

---

## 5. Ambiguities

1. **[NEEDS CLARIFICATION: Search parameter]** — The existing `sp_get_activity_logs` SP does NOT support free-text search. Should we:
   - (a) Modify the SP to add `LIKE` matching on `activity_type`, `details`, `username`?
   - (b) Create a new SP variant with search support?
   - (c) Implement search at the Python layer (less efficient)?

2. **[NEEDS CLARIFICATION: Admin scope]** — The PRD says admin users can access "activity logs within their permission scope." What does "scope" mean for audit logs?
   - (a) Only activities in projects the admin is assigned to?
   - (b) All activities (same as root)?
   - (c) Only activities performed by the admin themselves?

3. **[NEEDS CLARIFICATION: Security event severity]** — The PRD expects `info | warning | critical` severity for security events. The `api_audit_log` table has a boolean `security_event` flag but no severity field. The `activity_logs` table has `severity_level`. How should we map:
   - `api_audit_log.security_event=true` → what severity?
   - Should we derive severity from status code (401=warning, 403=critical)?

4. **[NEEDS CLARIFICATION: Export volume limits]** — Should export have a maximum record limit? The PRD doesn't specify. Without limits, exporting 1M+ rows could crash the server.

5. **[NEEDS CLARIFICATION: Audit log retention]** — The `sp_cleanup_old_activity_logs` SP exists for `activity_logs` but there's no equivalent for `api_audit_log`. Should we add retention policy before exposing these endpoints?

6. **[NEEDS CLARIFICATION: Real-time vs polling]** — The PRD says "auto-refresh at configurable interval (default 30 seconds)." This is frontend polling. Should we consider SSE/WebSocket for true real-time? (Out of scope for this change but worth noting.)

7. **[NEEDS CLARIFICATION: Combined vs separate security events]** — The PRD's Security Events tab doesn't specify whether it should show events from `activity_logs`, `api_audit_log`, or both. The recommendation above is to combine both, but this needs confirmation.

---

## 6. Summary: What Needs to Be Built

| Endpoint | Method | Source | Effort |
|----------|--------|--------|--------|
| `GET /admin/activity` (enhanced) | GET | Modify existing | Low |
| `GET /admin/activity/{activity_id}` | GET | New | Low |
| `GET /admin/audit/logs` | GET | New (SP wrapper) | Medium |
| `GET /admin/audit/security-events` | GET | New (SP wrapper, combined) | Medium |
| `GET /admin/audit/statistics` | GET | New (SP wrapper) | Low |
| `POST /admin/audit/export` | POST | New (streaming) | Medium |
| `GET /admin/users/{user_id}/activity` | GET | New (SP wrapper) | Low |

**Total estimated effort**: ~5-7 new route handlers + 1 new DB module + 1 export utility. No database schema changes required. All stored procedures already exist.
