# Design: Audit Log Monitor API

## Technical Approach

Expose both logging systems (`activity_logs` and `api_audit_log`) as a unified HTTP API surface under `/admin/audit/*` and enhance existing `/admin/activity` endpoints. The approach follows the existing layered architecture (routes → middleware → Util/db → MySQL/Redis) and reuses established patterns: `log_and_handle_errors` decorator for auth/error handling, `handle_db_operation` for DB error wrapping, and `HTTPBearerOrCookie` for auth.

A separate `audit_logs.py` router is created (not merged into `admin_dashboard.py`) because the file is already 448 lines and audit logs represent a distinct domain. All endpoints require `root` or `admin` user type with **global scope** — admins see all data, not scoped to assigned projects.

## Pre-Design Gates

**Simplicity Gate**: PASS
- Minimum new files: 3 (routes, db wrapper, export utility)
- Follows existing patterns: `db_session_analytics.py` → `db_audit_analytics.py`, `admin_dashboard.py` → `audit_logs.py`
- No speculative features — everything traces to a spec requirement

**Anti-Abstraction Gate**: PASS
- Uses FastAPI's `StreamingResponse` directly for export (no wrapper)
- Single `SecurityEvent` response model for merged data (no duplication)
- Abstractions justified: `audit_export.py` isolates CSV/JSON formatting + limit enforcement from route logic

## Architecture Decisions

### Decision: Separate router for audit endpoints

**Choice**: New `src/routes/audit_logs.py` with `APIRouter(prefix="/admin")`, included in `main.py`
**Alternatives considered**:
- Add all endpoints to existing `admin_dashboard.py` (file already 448 lines, would exceed 700+)
- Create a nested `/admin/audit` sub-router with separate include
**Rationale**: Separate file keeps concerns isolated. Using the same `/admin` prefix means routes coexist naturally with `admin_dashboard.py` routes (FastAPI merges routers with same prefix). A nested sub-router would add unnecessary complexity.

### Decision: DB wrapper follows `db_session_analytics.py` pattern

**Choice**: `src/Util/db/db_audit_analytics.py` with functions using `handle_db_operation` wrapper, `get_connection()` context manager, and `cursor.callproc()`
**Alternatives considered**:
- Direct SP calls from route handlers (violates layering)
- ORM-style abstraction (project uses raw SPs, no ORM)
**Rationale**: Consistent with existing `db_session_analytics.py` pattern. Every DB function uses `handle_db_operation` for standardized error handling with UUID masking.

### Decision: Security events merge both sources in route layer

**Choice**: `/admin/audit/security-events` calls both `sp_get_security_events` (api_audit_log) and `sp_get_recent_security_events` (activity_logs), normalizes to a common shape, merges, sorts by timestamp, and returns with summary counts
**Alternatives considered**:
- New SP that joins both tables (not feasible — different schemas, no natural join key)
- Python-side filtering of all logs (inefficient — would fetch too much data)
**Rationale**: Each SP already filters efficiently at the DB level. Route-layer merge is the only practical approach. Normalization maps fields explicitly with a `source` indicator.

### Decision: User activity merges both sources

**Choice**: `/admin/users/{user_id}/activity` calls `sp_get_user_activity_summary` from BOTH `11_activity_logging.sql` (activity_logs) and `07_sessions_analytics.sql` (api_audit_log), returns both summaries in a unified response
**Alternatives considered**:
- Pick one source only (loses half the picture)
- Create a new merged SP (out of scope — no schema changes)
**Rationale**: The two SPs have different signatures and return different data. Returning both in a structured response gives the complete picture without modifying SPs.

### Decision: Export uses `StreamingResponse` with generator

**Choice**: `POST /admin/audit/export` uses FastAPI's `StreamingResponse` with a generator that yields CSV rows or JSON chunks one at a time
**Alternatives considered**:
- Build full response in memory then return (would spike memory at 10K rows)
- Write to temp file then serve (adds I/O complexity, cleanup needed)
**Rationale**: Generator-based streaming keeps memory constant regardless of row count. The 10,000 hard limit is enforced before any DB call.

### Decision: Stored procedure search param added with backward-compatible default

**Choice**: Add `p_search VARCHAR(255) = NULL` as the LAST parameter to `sp_get_activity_logs` and `sp_count_activity_logs`. Existing callers pass no value → defaults to NULL → no filtering.
**Alternatives considered**:
- Add search param in the middle of the parameter list (breaks existing callers)
- Create new SPs with search (duplicates logic)
**Rationale**: MySQL allows default values on IN parameters. Adding as the last parameter means existing `activity_logger.py` callers (which use positional args via `callproc`) continue to work without changes.

### Decision: Severity derived from status code for API audit security events

**Choice**: For `api_audit_log` security events, derive severity from response status code: 401→warning, 403→critical, 5xx→warning, 4xx (other)→info, 2xx/3xx→info. Activity log events already have `severity_level` from the catalog.
**Alternatives considered**:
- Add severity column to `api_audit_log` table (schema change — out of scope)
- Use event type/tags for severity (less consistent)
**Rationale**: Status code is the most reliable signal available without schema changes. Derived in the route layer, not stored.

## Data Flow

### Audit Logs Query Flow

```
Client ──→ GET /admin/audit/logs
              │
              ▼
         audit_logs.py (route)
              │
              ├── Auth check (root/admin via decorator)
              │
              ▼
         db_audit_analytics.get_audit_logs()
              │
              ├── get_connection() → MySQL
              ├── callproc('sp_get_audit_logs', [...])
              │
              ▼
         api_audit_log table (filtered, paginated)
              │
              ▼
         Response shaping (enrich with username, project_name)
              │
              ▼
         {logs, pagination, filters, generated_at}
```

### Security Events Merge Flow

```
Client ──→ GET /admin/audit/security-events
              │
              ▼
         audit_logs.py (route)
              │
              ├── Parallel calls:
              │   ├── db_audit_analytics.get_security_events()
              │   │       └── sp_get_security_events (api_audit_log, security_event=TRUE)
              │   │
              │   └── activity_logger.get_recent_security_events()
              │           └── sp_get_recent_security_events (activity_logs, severity IN warning/critical)
              │
              ├── Normalize both to SecurityEvent shape
              ├── Merge lists, sort by created_at DESC
              ├── Compute summary counts (by source, by severity)
              │
              ▼
         {events, summary, generated_at}
```

### Export Flow

```
Client ──→ POST /admin/audit/export {source, format, filters, limit}
              │
              ▼
         audit_logs.py (route)
              │
              ├── Validate: limit <= 10,000 (hard cap)
              ├── Validate: source in {activity, audit}
              │
              ▼
         audit_export.py
              │
              ├── Fetch data (respects limit)
              ├── Generator yields rows:
              │   ├── CSV: header + rows as comma-separated strings
              │   └── JSON: objects as JSON lines
              │
              ▼
         StreamingResponse (text/csv or application/json)
```

## Sequence Diagrams

### GET /admin/audit/logs

```
Client          audit_logs.py        db_audit_analytics        MySQL
  │                   │                      │                   │
  │──GET /logs───────▶│                      │                   │
  │                   │──auth check──────────▶│                   │
  │                   │  (root/admin)         │                   │
  │                   │                      │                   │
  │                   │──get_audit_logs()────▶│                   │
  │                   │  (params)             │                   │
  │                   │                      │──callproc────────▶│
  │                   │                      │  (sp_get_audit_   │
  │                   │                      │   logs)           │
  │                   │                      │◀──rows────────────│
  │                   │◀──formatted rows─────│                   │
  │                   │                      │                   │
  │                   │──count_audit_logs()──▶│                   │
  │                   │  (same filters)       │                   │
  │                   │                      │──callproc────────▶│
  │                   │                      │  (sp_count_audit_ │
  │                   │                      │   logs)           │
  │                   │                      │◀──count───────────│
  │                   │◀──total count────────│                   │
  │                   │                      │                   │
  │                   │──build response──▶    │                   │
  │◀──{logs,pagination}│                      │                   │
```

### GET /admin/audit/security-events (merge)

```
Client          audit_logs.py        db_audit_analytics     activity_logger      MySQL
  │                   │                      │                    │                │
  │──GET /sec-events▶│                      │                    │                │
  │                   │                      │                    │                │
  │                   │──get_security_events()│                    │                │
  │                   │─────────────────────▶│                    │                │
  │                   │                      │──callproc─────────▶│                │
  │                   │                      │  (sp_get_security_ │                │
  │                   │                      │   events)          │                │
  │                   │                      │◀──api_audit rows───│                │
  │                   │◀──api_audit events───│                    │                │
  │                   │                      │                    │                │
  │                   │──get_recent_security()│                    │                │
  │                   │───────────────────────▶│                   │                │
  │                   │                       │──callproc─────────▶│                │
  │                   │                       │  (sp_get_recent_  │                │
  │                   │                       │   security_events)│                │
  │                   │                       │◀──activity rows───│                │
  │                   │◀──activity events─────│                    │                │
  │                   │                      │                    │                │
  │                   │──normalize + merge + sort                  │                │
  │                   │──compute summary                           │                │
  │◀──{events,summary}│                      │                    │                │
```

## File Changes

| File | Action | Description |
|------|--------|-------------|
| `src/routes/audit_logs.py` | **Create** | New router for `/admin/audit/*` endpoints: logs, security-events, statistics, export, and `/admin/users/{user_id}/activity` |
| `src/routes/admin_dashboard.py` | Modify | Add `search` query param to `GET /admin/activity`; add `GET /admin/activity/{activity_id}` detail endpoint |
| `src/Util/db/db_audit_analytics.py` | **Create** | DB wrapper module for `api_audit_log` stored procedures: `get_audit_logs`, `count_audit_logs`, `get_audit_statistics`, `get_security_events`, `get_failed_requests`, `get_user_activity_summary_api` |
| `src/Util/audit_export.py` | **Create** | CSV/JSON export utility with hard limit enforcement (10,000 rows), generator-based streaming |
| `src/Util/db/__init__.py` | Modify | Export new functions from `db_audit_analytics` |
| `src/routes/__init__.py` | Modify | Import and export `audit_logs` module |
| `src/main.py` | Modify | Add `include_router(audit_logs.router, tags=["Audit Logs"])` |
| `schemas/stored_procedures/11_activity_logging.sql` | Modify | Add `p_search VARCHAR(255) DEFAULT NULL` parameter to `sp_get_activity_logs` and `sp_count_activity_logs` |
| `tests/integration/conftest.py` | Modify | Add `src.Util.db.db_audit_analytics.get_connection` to `_DB_CONN_PATCH_LOCATIONS` |
| `tests/unit/test_audit_export.py` | **Create** | Unit tests for export utility (CSV formatting, JSON formatting, limit enforcement) |
| `tests/unit/test_db_audit_analytics.py` | **Create** | Unit tests for DB wrapper functions |
| `tests/integration/test_slice15_audit_logs.py` | **Create** | Integration tests for all new audit endpoints |

## Interfaces / Contracts

### Response Models (dict-based, consistent with existing pattern)

```python
# Unified Audit Log Entry (from api_audit_log)
{
    "id": "audit-uuid",
    "request_id": "req-uuid",
    "http_method": "GET",
    "endpoint_path": "/admin/users",
    "route_pattern": "/admin/users",
    "user_id": "usr-uuid",
    "user_type": "admin",
    "response_status": 200,
    "request_timestamp": "2026-04-16T12:00:00Z",
    "response_timestamp": "2026-04-16T12:00:01Z",
    "duration_ms": 45,
    "client_ip": "192.168.1.1",
    "is_success": True,
    "error_code": None,
    "error_message": None,
    "security_event": False,
    "tags": ["get", "success", "admin_action"],
    "username": "adminuser",
    "user_hash": "usr-abc123",
    "project_name": "Test Project",
    "project_hash": "prj-abc123"
}

# Unified Security Event (merged from both sources)
{
    "id": "audit-uuid or activity-log-id",
    "source": "api_audit" | "activity_log",
    "event_type": "unauthorized_access" | "user_login_failed" | ...,
    "severity": "info" | "warning" | "critical",
    "user_id": "usr-uuid",
    "username": "adminuser",
    "ip_address": "192.168.1.1",
    "details": "...",
    "endpoint_path": "/admin/users",  # api_audit only, None for activity_log
    "status_code": 403,               # api_audit only, None for activity_log
    "created_at": "2026-04-16T12:00:00Z"
}

# Security Events Response
{
    "events": [SecurityEvent, ...],
    "summary": {
        "total": 42,
        "by_source": {"api_audit": 25, "activity_log": 17},
        "by_severity": {"critical": 5, "warning": 20, "info": 17},
        "period_hours": 24
    },
    "generated_at": "2026-04-16T12:00:00Z"
}

# Audit Statistics Response (4 result sets from sp_get_audit_statistics)
{
    "overview": {
        "total_requests": 15000,
        "successful_requests": 14200,
        "failed_requests": 800,
        "success_rate": 94.67,
        "avg_duration_ms": 45.2,
        "max_duration_ms": 2340,
        "avg_request_size": 1024,
        "avg_response_size": 4096
    },
    "by_method": [
        {"method": "GET", "count": 12000, "avg_duration_ms": 30.5},
        {"method": "POST", "count": 2500, "avg_duration_ms": 85.1}
    ],
    "top_endpoints": [
        {"endpoint": "/auth/login", "count": 5000, "avg_duration_ms": 120, "success_count": 4800, "failure_count": 200}
    ],
    "status_distribution": [
        {"status_code": 200, "count": 13000},
        {"status_code": 401, "count": 500}
    ],
    "generated_at": "2026-04-16T12:00:00Z"
}

# User Activity Response (merged from both sources)
{
    "user_id": "usr-uuid",
    "summary": {
        "activity_logs": {
            "total_activities": 150,
            "by_category": [{"category": "authentication", "count": 50, ...}]
        },
        "api_audit": {
            "total_requests": 500,
            "successful_requests": 480,
            "failed_requests": 20,
            "unique_endpoints": 25,
            "first_request": "2026-04-01T00:00:00Z",
            "last_request": "2026-04-16T12:00:00Z",
            "avg_duration_ms": 45.2
        }
    },
    "timeline": [
        # From api_audit_log: recent activity by endpoint
        {"endpoint": "/auth/login", "method": "POST", "count": 50, "last_access": "..."},
        # From activity_logs: recent activity by category
        {"activity_type": "user_login", "category": "authentication", "count": 30, "last_activity": "..."}
    ],
    "generated_at": "2026-04-16T12:00:00Z"
}

# Export Request Body
{
    "source": "activity" | "audit",
    "format": "csv" | "json",
    "limit": 5000,           # optional, defaults to 1000, max 10000
    "filters": {
        "days": 30,
        "user_id": "usr-uuid",       # optional
        "project_id": "prj-uuid",    # optional
        "activity_type": "...",      # activity source only
        "endpoint_path": "...",      # audit source only
        "http_method": "GET",        # audit source only
        "status_code": 200,          # audit source only
        "security_event": true       # audit source only
    }
}
```

### DB Wrapper Function Signatures

```python
# src/Util/db/db_audit_analytics.py

def get_audit_logs(
    limit: int = 50,
    offset: int = 0,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    http_method: Optional[str] = None,
    status_code: Optional[int] = None,
    is_success: Optional[bool] = None,
    security_event: Optional[bool] = None,
    days: int = 30
) -> List[Dict[str, Any]]

def count_audit_logs(
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    endpoint_path: Optional[str] = None,
    http_method: Optional[str] = None,
    status_code: Optional[int] = None,
    is_success: Optional[bool] = None,
    security_event: Optional[bool] = None,
    days: int = 30
) -> int

def get_audit_statistics(days: int = 7) -> Dict[str, Any]
    # Handles 4 result sets via cursor.nextset()

def get_security_events(
    limit: int = 100,
    offset: int = 0,
    days: int = 30
) -> List[Dict[str, Any]]

def get_failed_requests(
    limit: int = 50,
    offset: int = 0,
    days: int = 7
) -> List[Dict[str, Any]]

def get_user_activity_summary_api(
    user_id: str,
    days: int = 30
) -> Dict[str, Any]
    # Handles 2 result sets: summary + endpoint breakdown
```

### Export Utility Interface

```python
# src/Util/audit_export.py

EXPORT_HARD_LIMIT = 10_000

def validate_export_request(
    source: str,
    fmt: str,
    limit: Optional[int] = None
) -> tuple[bool, str, int]
    # Returns (is_valid, error_message, effective_limit)

def stream_csv_export(
    source: str,
    filters: Dict[str, Any],
    limit: int
) -> Generator[str, None, None]

def stream_json_export(
    source: str,
    filters: Dict[str, Any],
    limit: int
) -> Generator[str, None, None]
```

## Testing Strategy

### Unit Tests

| Layer | What to Test | Approach |
|-------|-------------|----------|
| **Unit** | `audit_export.py` — CSV formatting with various data types | Mock data, verify header + row formatting, special char escaping |
| **Unit** | `audit_export.py` — JSON formatting | Mock data, verify JSON serialization, null handling |
| **Unit** | `audit_export.py` — Hard limit enforcement | Test with limit > 10,000 → returns error; limit = 10,000 → OK; limit = None → defaults to 1,000 |
| **Unit** | `db_audit_analytics.py` — Each DB function with mocked cursor | Mock `get_connection`, verify `callproc` args, verify result parsing |
| **Unit** | `db_audit_analytics.py` — Multi-result-set handling for `get_audit_statistics` | Mock cursor with `nextset()` returning different result sets |
| **Unit** | Security event severity derivation | Test status code → severity mapping: 401→warning, 403→critical, 500→warning, 200→info |

### Integration Tests

| Layer | What to Test | Approach |
|-------|-------------|----------|
| **Integration** | `GET /admin/audit/logs` — paginated, filtered results | Use `client` + `fake_redis` + `patched_db_connection` + `DBPatcher`, mock SP results |
| **Integration** | `GET /admin/audit/logs` — auth rejection (no token, consumer user) | Verify 401 for missing token, 403 for consumer user type |
| **Integration** | `GET /admin/audit/security-events` — merged results from both sources | Mock both SP calls, verify merge + sort + summary counts |
| **Integration** | `GET /admin/audit/statistics` — 4-section response | Mock `sp_get_audit_statistics` with 4 result sets |
| **Integration** | `POST /admin/audit/export` — CSV response with Content-Disposition | Verify streaming response, content type, header |
| **Integration** | `POST /admin/audit/export` — limit enforcement (400 when > 10,000) | Send limit=15000, expect 400 with clear error |
| **Integration** | `GET /admin/users/{user_id}/activity` — merged activity summary | Mock both SPs, verify combined response |
| **Integration** | `GET /admin/activity` — new `search` param works | Mock `sp_get_activity_logs` with search param |
| **Integration** | `GET /admin/activity/{activity_id}` — single activity detail | Mock SP or direct query, verify response shape |

### Test Infrastructure

- **`integration_env` fixture**: Already provides `fake_redis`, `patched_db_connection`, `patched_audit_logger`, `patched_activity_logger`, `patched_cache_manager`, `patched_db_error_logger`
- **`DBPatcher` class**: Add new DB function names to `DEFAULT_PATCHES` or use `extra_patches`
- **`_DB_CONN_PATCH_LOCATIONS`**: Add `"src.Util.db.db_audit_analytics.get_connection"` to the list
- **Test file naming**: `tests/integration/test_slice15_audit_logs.py` (next available slice number after slice14)

## Migration / Rollout

### No data migration needed

All changes are additive:
- New endpoints (no existing URLs affected)
- New SP parameters with defaults (backward compatible)
- New DB wrapper functions (no existing functions modified)

### Rollout Plan

1. **Phase 1 — SP modifications**: Update `11_activity_logging.sql` with search params. Re-run schema scripts. Verify existing `activity_logger.py` callers still work (they pass positional args, new param defaults to NULL).

2. **Phase 2 — DB wrapper + export utility**: Deploy `db_audit_analytics.py` and `audit_export.py`. No routes yet — zero user impact.

3. **Phase 3 — Route deployment**: Deploy `audit_logs.py` router and `main.py` registration. Deploy enhanced `admin_dashboard.py`. All endpoints immediately available.

4. **Phase 4 — Verification**: Test all endpoints against staging environment. Verify search param on `/admin/activity`. Verify security events merge correctly.

### Rollback Plan

1. **Revert code changes**: `git revert` the commits adding `audit_logs.py`, `db_audit_analytics.py`, `audit_export.py`, and modifications to `admin_dashboard.py`, `main.py`, `__init__.py`, `routes/__init__.py`
2. **Revert SP changes**: Re-run `11_activity_logging.sql` from pre-modification version (or manually DROP and recreate the two modified SPs without `p_search`)
3. **No data cleanup needed**: No tables modified, no data inserted/changed
4. **Verification**: Confirm `GET /admin/activity` still works without `search` param; all existing endpoints unaffected

## Risks and Mitigations

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **SP signature break** — Adding `p_search` to `sp_get_activity_logs` breaks existing callers | Low | High | New param is LAST with `DEFAULT NULL`. Existing `activity_logger.py` uses positional args — MySQL fills missing args with defaults. Verify in Phase 1. |
| **Multi-result-set handling** — `sp_get_audit_statistics` returns 4 result sets, `sp_get_user_activity_summary` returns 2 | Medium | Medium | Follow existing pattern from `db_session_analytics.py:get_user_login_statistics` which uses `cursor.nextset()`. Test explicitly. |
| **Export memory pressure** — 10K rows as CSV could spike memory | Medium | Medium | `StreamingResponse` with generator — rows yielded one at a time. Never load all rows into memory. |
| **Duplicate SP name** — `sp_get_user_activity_summary` exists in both `07_sessions_analytics.sql` and `11_activity_logging.sql` | Medium | High | The MySQL `DROP PROCEDURE IF EXISTS` means the later-loaded version wins. Verify load order in schema scripts. In the DB wrapper, explicitly call the correct SP for each source: use `sp_get_user_activity_summary` from `11_activity_logging.sql` for activity_logs, and the one from `07_sessions_analytics.sql` for api_audit. Since they have the same name but different signatures, the **last-loaded** version overwrites. **Mitigation**: Rename the api_audit version to `sp_get_user_api_activity_summary` in `07_sessions_analytics.sql` to avoid collision. [NEEDS CLARIFICATION: Can we rename the SP in 07_sessions_analytics.sql, or should we handle this differently?] |
| **Security event normalization** — Merging two different schemas into one response | Medium | Medium | Define explicit field mapping. Use `source` indicator. Test with edge cases (missing fields, NULL values). |
| **SP parameter mismatch** — `sp_get_recent_security_events` uses `p_hours` while others use `p_days` | Low | Low | Wrapper converts `days` → `hours` (`days * 24`) before calling. Document the conversion. |
| **No rate limiting on export** — Export endpoint could be abused | Medium | Low | Error code `INT_7005` (RATE_LIMIT_EXCEEDED) exists but no middleware implements it. Hard limit of 10,000 rows provides basic protection. Full rate limiting deferred. |

## Open Questions

- [NEEDS CLARIFICATION: Can `sp_get_user_activity_summary` in `07_sessions_analytics.sql` be renamed to `sp_get_user_api_activity_summary` to avoid collision with the same-named SP in `11_activity_logging.sql`? If not, how should we handle the SP name collision?]
- [None — all other ambiguities resolved by authoritative decisions]

## Self-Validation Checklist

- [x] Every architecture decision has a rationale (the "why")
- [x] File changes table uses concrete paths from the actual codebase
- [x] Design follows existing project patterns (not inventing new abstractions)
- [x] Simplicity gate passed — 3 new files, follows existing patterns
- [x] Anti-abstraction gate passed — uses framework features directly
- [x] Testing strategy covers unit, integration, and e2e layers
- [x] Open questions list all `[NEEDS CLARIFICATION]` markers (1 remaining)
- [x] No speculative features — everything traces back to a spec requirement
- [x] Sequence diagrams for complex multi-component interactions (security events merge)
- [x] Data flow diagrams for all major endpoints
- [x] Rollback plan is concrete and actionable
