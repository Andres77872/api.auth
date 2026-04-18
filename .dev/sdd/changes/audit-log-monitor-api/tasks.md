# Tasks: Audit Log Monitor API

## Phase 1: Foundation / Infrastructure [P]

- [x] 1.1 Modify `schemas/stored_procedures/11_activity_logging.sql`: Add `p_search VARCHAR(255) DEFAULT NULL` as the LAST parameter to `sp_get_activity_logs`. Add `AND (p_search IS NULL OR al.activity_type LIKE CONCAT('%', p_search, '%') OR al.details LIKE CONCAT('%', p_search, '%') OR u.username LIKE CONCAT('%', p_search, '%'))` to the WHERE clause.
- [x] 1.2 Modify `schemas/stored_procedures/11_activity_logging.sql`: Add `p_search VARCHAR(255) DEFAULT NULL` as the LAST parameter to `sp_count_activity_logs`. Add the same search LIKE condition to its WHERE clause.
- [x] 1.3 Rename SP in `schemas/stored_procedures/07_sessions_analytics.sql`: Change `sp_get_user_activity_summary` to `sp_get_user_api_activity_summary` (both DROP PROCEDURE IF EXISTS and CREATE PROCEDURE lines) to avoid collision with the same-named SP in `11_activity_logging.sql`.
- [x] 1.4 Create `src/Util/db/db_audit_analytics.py`: DB wrapper module following `db_session_analytics.py` pattern. Implement 6 functions using `handle_db_operation` and `get_connection()`:
  - `get_audit_logs(limit=50, offset=0, user_id=None, project_id=None, endpoint_path=None, http_method=None, status_code=None, is_success=None, security_event=None, days=30)` → calls `sp_get_audit_logs`, returns list of dicts with enriched fields (username, user_hash, project_name, project_hash)
  - `count_audit_logs(user_id=None, project_id=None, endpoint_path=None, http_method=None, status_code=None, is_success=None, security_event=None, days=30)` → calls `sp_count_audit_logs`, returns int
  - `get_audit_statistics(days=7)` → calls `sp_get_audit_statistics`, handles 4 result sets via `cursor.nextset()`, returns dict with keys: `overview`, `by_method`, `top_endpoints`, `status_distribution`
  - `get_security_events(limit=100, offset=0, days=30)` → calls `sp_get_security_events`, returns list of dicts
  - `get_failed_requests(limit=50, offset=0, days=7)` → calls `sp_get_failed_requests`, returns list of dicts
  - `get_user_api_activity_summary(user_id, days=30)` → calls `sp_get_user_api_activity_summary` (renamed SP), handles 2 result sets via `cursor.nextset()`, returns dict with keys: `summary` (single row) and `endpoint_activity` (list of rows)
- [x] 1.5 Create `src/Util/audit_export.py`: Export utility with hard limit enforcement. Implement:
  - `EXPORT_HARD_LIMIT = 10_000` constant
  - `validate_export_request(source: str, fmt: str, limit: Optional[int] = None) -> tuple[bool, str, int]` — validates source in {activity, audit}, format in {csv, json}, limit <= 10000; returns (is_valid, error_message, effective_limit)
  - `stream_csv_export(source, filters, limit) -> Generator[str, None, None]` — generator yielding CSV header + rows; fetches data from appropriate SP based on source
  - `stream_json_export(source, filters, limit) -> Generator[str, None, None]` — generator yielding JSON objects one at a time
  - Internal helper `_fetch_export_data(source, filters, limit)` to call the correct DB function based on source
- [x] 1.6 Add `get_activity_by_id(activity_id: str) -> Optional[Dict[str, Any]]` to `src/Util/activity_logger.py`: New static method that queries `activity_logs` table directly (or via a new inline SP call) to retrieve a single activity log entry by ID with the same enriched fields as `get_recent_activity` (joins users, projects, activity_catalog).

## Phase 2: Core Implementation

- [x] 2.1 Modify `src/routes/admin_dashboard.py`: Add `search: Optional[str] = Query(None)` parameter to `get_activity_feed()` endpoint. Pass `search` to `get_recent_activity()` and `count_activity_logs()` calls. Empty string should be treated as None (no filtering).
- [x] 2.2 Modify `src/routes/admin_dashboard.py`: Add new `GET /admin/activity/{activity_id}` endpoint with `@log_and_handle_errors` decorator, admin auth check, calls `get_activity_by_id()`, returns 404 with `NF_4004` if not found, returns 400 with `VAL_3001` for invalid/empty ID format. Response shape matches existing activity format with all enriched fields.
- [x] 2.3 Create `src/routes/audit_logs.py`: New router with `APIRouter(prefix="/admin")`. Implement `GET /admin/audit/logs` endpoint:
  - Auth: `@log_and_handle_errors` decorator, check `is_root_user()` or `user_type == 'admin'`, raise `AuthorizationError` with `AUTHZ_2001` for consumers
  - Query params: `limit` (default 50, 1-1000), `offset` (default 0, >=0), `user_id`, `project_id`, `endpoint_path`, `http_method`, `status_code`, `is_success` (bool), `security_event` (bool), `days` (default 30, 1-365)
  - Validate `limit` range → 400 with `VAL_3009` if out of bounds
  - Call `db_audit_analytics.get_audit_logs()` and `count_audit_logs()`
  - Return `{logs: [...], pagination: {total, limit, offset, has_more, next_offset}, filters: {...}, generated_at}`
- [x] 2.4 Create `src/routes/audit_logs.py`: Add `GET /admin/audit/security-events` endpoint:
  - Auth: same pattern as 2.3
  - Query params: `limit` (default 100), `days` (default 30), `severity` (filter: critical/warning), `source` (filter: api_audit/activity_log)
  - Call `db_audit_analytics.get_security_events()` for api_audit source
  - Call `activity_logger.get_recent_security_events()` or inline SP call for activity_logs source (convert `days` → `hours = days * 24`)
  - Normalize both sources to unified `SecurityEvent` shape with `source` field
  - Derive severity for api_audit events: 401→warning, 403→critical, 5xx→warning, other→info
  - Merge lists, sort by timestamp DESC
  - Compute summary: `{total, by_source: {api_audit, activity_log}, by_severity: {critical, warning, info}, period_hours}`
  - Return `{events: [...], summary: {...}, generated_at}`
- [x] 2.5 Create `src/routes/audit_logs.py`: Add `GET /admin/audit/statistics` endpoint:
  - Auth: same pattern as 2.3
  - Query params: `days` (default 7, 1-365), validate range → 400 with `VAL_3009`
  - Call `db_audit_analytics.get_audit_statistics(days)`
  - Handle empty data: return zeroed values (total_requests=0, empty arrays)
  - Return `{overview: {...}, by_method: [...], top_endpoints: [...], status_distribution: [...], generated_at}`
- [x] 2.6 Create `src/routes/audit_logs.py`: Add `POST /admin/audit/export` endpoint:
  - Auth: same pattern as 2.3
  - Request body (JSON): `{source: "activity"|"audit", format: "csv"|"json", limit: int (optional), filters: {...}}`
  - Validate: missing source → 400 `VAL_3002`, invalid source/format → 400 `VAL_3012`, limit > 10000 → 400 `VAL_3009`
  - Use `audit_export.validate_export_request()` for validation
  - Return `StreamingResponse` with generator from `audit_export.stream_csv_export()` or `stream_json_export()`
  - Set Content-Type (`text/csv` or `application/json`) and Content-Disposition header with filename
- [x] 2.7 Create `src/routes/audit_logs.py`: Add `GET /admin/users/{user_id}/activity` endpoint:
  - Auth: same pattern as 2.3
  - Validate `user_id` format, check user exists via `get_user_by_id()` → 404 `NF_4001` if not found
  - Query params: `days` (default 30, 1-365)
  - Call `activity_logger`'s `sp_get_user_activity_summary` (from `11_activity_logging.sql`) for activity log summary
  - Call `db_audit_analytics.get_user_api_activity_summary()` (from `07_sessions_analytics.sql`, renamed SP) for API audit summary
  - Build combined timeline from both sources (recent entries, ordered by timestamp DESC, with `source` field)
  - Return `{user_id, summary: {activity_logs: {...}, api_audit: {...}}, timeline: [...], generated_at}`

## Phase 3: Integration / Wiring [P]

- [x] 3.1 Modify `src/Util/db/__init__.py`: Add imports and exports for all 6 new functions from `db_audit_analytics.py` (`get_audit_logs`, `count_audit_logs`, `get_audit_statistics`, `get_security_events`, `get_failed_requests`, `get_user_api_activity_summary`). Add to `__all__` list under a new "Audit Analytics" section.
- [x] 3.2 Modify `src/routes/__init__.py`: Add `from . import audit_logs` and include `'audit_logs'` in `__all__`.
- [x] 3.3 Modify `src/main.py`: Add `audit_logs` to the import from `src.routes`. Add `app.include_router(audit_logs.router, tags=["Audit Logs"])` after the existing router registrations.
- [x] 3.4 Modify `tests/integration/conftest.py`: Add `"src.Util.db.db_audit_analytics.get_connection"` to `_DB_CONN_PATCH_LOCATIONS` list. Also add `"src.Util.audit_export.get_connection"` if the export utility imports `get_connection` directly.

## Phase 4: Testing [P]

- [x] 4.1 Create `tests/unit/test_audit_export.py`: Unit tests for export utility:
  - Test `validate_export_request()` with valid inputs (activity/csv, audit/json, with/without limit)
  - Test `validate_export_request()` with invalid source → returns (False, error, 0)
  - Test `validate_export_request()` with invalid format → returns (False, error, 0)
  - Test `validate_export_request()` with limit > 10000 → returns (False, error, 0)
  - Test `validate_export_request()` with limit=None → defaults to 1000
  - Test `validate_export_request()` with limit=10000 → returns (True, "", 10000)
  - Test CSV formatting: header row generation, special character escaping, None/null handling
  - Test JSON formatting: serialization, null handling, proper JSON structure
- [x] 4.2 Create `tests/unit/test_db_audit_analytics.py`: Unit tests for DB wrapper:
  - Test `get_audit_logs()` with mocked cursor: verify `callproc('sp_get_audit_logs', [...])` with correct args, verify result parsing to list of dicts
  - Test `count_audit_logs()` with mocked cursor: verify `callproc` args, verify integer return
  - Test `get_audit_statistics()` with mocked multi-result-set cursor: verify `cursor.nextset()` called between result sets, verify dict with 4 keys returned
  - Test `get_user_api_activity_summary()` with mocked 2-result-set cursor: verify `cursor.nextset()` called, verify dict with 2 keys returned
  - Test `get_security_events()` and `get_failed_requests()` with mocked cursors
  - Test error handling: verify `handle_db_operation` wraps errors correctly
- [x] 4.3 Create `tests/integration/test_slice15_audit_logs.py`: Integration tests for all new endpoints using `integration_env` fixture and `DBPatcher`:
  - Test `GET /admin/audit/logs` — default listing returns paginated results with correct shape
  - Test `GET /admin/audit/logs` — filters (http_method, status_code, endpoint_path, is_success, security_event, user_id, project_id, days)
  - Test `GET /admin/audit/logs` — combined filters work together
  - Test `GET /admin/audit/logs` — pagination with offset, has_more calculation
  - Test `GET /admin/audit/logs` — limit validation (0 → 400 VAL_3009, 1001 → 400 VAL_3009)
  - Test `GET /admin/audit/logs` — auth rejection: no token → 401, consumer user → 403 AUTHZ_2001
  - Test `GET /admin/audit/security-events` — merged results from both sources with summary counts
  - Test `GET /admin/audit/security-events` — severity derivation (401→warning, 403→critical, 500→warning)
  - Test `GET /admin/audit/security-events` — events sorted by timestamp DESC
  - Test `GET /admin/audit/security-events` — filter by severity, filter by source
  - Test `GET /admin/audit/statistics` — 4-section response with correct shape
  - Test `GET /admin/audit/statistics` — days parameter (default 7, custom range)
  - Test `GET /admin/audit/statistics` — days validation (0 → 400, 366 → 400)
  - Test `GET /admin/audit/statistics` — empty data returns zeroed statistics
  - Test `POST /admin/audit/export` — JSON export with Content-Type and Content-Disposition
  - Test `POST /admin/audit/export` — CSV export with headers
  - Test `POST /admin/audit/export` — limit enforcement (15000 → 400 VAL_3009)
  - Test `POST /admin/audit/export` — missing source → 400 VAL_3002, invalid format → 400 VAL_3012
  - Test `GET /admin/activity?search=login` — search returns matching activities
  - Test `GET /admin/activity?search=` — empty search treated as no filter
  - Test `GET /admin/activity?search=xyz&user_id=usr-123&days=7` — combined search + filters
  - Test `GET /admin/activity/{activity_id}` — valid ID returns full detail
  - Test `GET /admin/activity/{activity_id}` — non-existent ID → 404 NF_4004
  - Test `GET /admin/activity/{activity_id}` — empty/malformed ID → 400 VAL_3001
  - Test `GET /admin/users/{user_id}/activity` — combined summary from both sources
  - Test `GET /admin/users/{user_id}/activity` — non-existent user → 404 NF_4001
  - Test `GET /admin/users/{user_id}/activity` — user with no activity returns zeroed counts + empty timeline
  - Test `GET /admin/users/{user_id}/activity?days=7` — time range filter works

## Parallel Groups

- **Parallel-safe `[P]`**: Phase 1 (all tasks write to different files: 1.1/1.2/1.3 touch SQL files, 1.4 creates `db_audit_analytics.py`, 1.5 creates `audit_export.py`, 1.6 modifies `activity_logger.py`). Phase 3 (all tasks modify different files: `__init__.py`, `routes/__init__.py`, `main.py`, `conftest.py`). Phase 4 (each test file is independent).
- **Sequential**: Phase 2 tasks all write to `src/routes/audit_logs.py` — must be done sequentially (2.3 → 2.4 → 2.5 → 2.6 → 2.7). Phase 2 depends on Phase 1 (routes import from db_audit_analytics and audit_export). Phase 3 depends on Phase 2 (wiring requires the route module to exist). Phase 4 depends on Phase 2+3 (tests require all code to be in place).

## Implementation Order

1. **Phase 1** (all parallel): Start with SP modifications and new modules. These are independent foundation work. The DB wrapper (1.4) and export utility (1.5) have no runtime dependencies on each other.
2. **Phase 2** (sequential): Build the route file incrementally. Start with the simplest endpoint (audit logs listing, 2.3), then security events (2.4, most complex merge logic), statistics (2.5), export (2.6), and user activity (2.7). Modify admin_dashboard.py (2.1, 2.2) in parallel with 2.3 since it's a different file.
3. **Phase 3** (all parallel): Wire everything together — router registration, imports, test infrastructure.
4. **Phase 4** (all parallel): Write tests. Unit tests (4.1, 4.2) can be written before integration tests (4.3).
