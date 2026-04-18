# Apply Progress: audit-log-monitor-api

**Workflow**: sdd
**Change**: audit-log-monitor-api
**Mode**: Standard implementation

## Authoritative Artifacts

- `spec.md` — 14 requirements, 89 scenarios
- `design.md` — Technical approach, architecture decisions, data flow
- `tasks.md` — 4 phases, 21 tasks

## Completed Work

### Phase 1: Foundation / Infrastructure [P] ✅
- [x] 1.1 Modified `sp_get_activity_logs` with `p_search` parameter (11_activity_logging.sql)
- [x] 1.2 Modified `sp_count_activity_logs` with `p_search` parameter (11_activity_logging.sql)
- [x] 1.3 Renamed SP to `sp_get_user_api_activity_summary` (07_sessions_analytics.sql)
- [x] 1.4 Created `src/Util/db/db_audit_analytics.py` — 6 DB wrapper functions
- [x] 1.5 Created `src/Util/audit_export.py` — CSV/JSON export with hard limit
- [x] 1.6 Added `get_activity_by_id()` to `src/Util/activity_logger.py`

### Phase 2: Core Implementation ✅
- [x] 2.1 Added `search` param to `GET /admin/activity` in admin_dashboard.py
- [x] 2.2 Added `GET /admin/activity/{activity_id}` endpoint in admin_dashboard.py
- [x] 2.3 Created `GET /admin/audit/logs` endpoint in audit_logs.py
- [x] 2.4 Created `GET /admin/audit/security-events` endpoint in audit_logs.py
- [x] 2.5 Created `GET /admin/audit/statistics` endpoint in audit_logs.py
- [x] 2.6 Created `POST /admin/audit/export` endpoint in audit_logs.py
- [x] 2.7 Created `GET /admin/users/{user_id}/activity` endpoint in audit_logs.py

### Phase 3: Integration / Wiring [P] ✅
- [x] 3.1 Updated `src/Util/db/__init__.py` — exports 6 new audit functions
- [x] 3.2 Updated `src/routes/__init__.py` — imports audit_logs module
- [x] 3.3 Updated `src/main.py` — registered audit_logs router
- [x] 3.4 Updated `tests/integration/conftest.py` — added db_audit_analytics to _DB_CONN_PATCH_LOCATIONS; fixed DBPatcher to use patch.object instead of patch.multiple

### Phase 4: Testing [P] ✅
- [x] 4.1 Created `tests/unit/test_audit_export.py` — 18 tests
- [x] 4.2 Created `tests/unit/test_db_audit_analytics.py` — 12 tests
- [x] 4.3 Created `tests/integration/test_slice15_audit_logs.py` — 30 tests (2 skipped for streaming infra limitation)

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `schemas/stored_procedures/11_activity_logging.sql` | Modified | Added `p_search` param to `sp_get_activity_logs` and `sp_count_activity_logs` |
| `schemas/stored_procedures/07_sessions_analytics.sql` | Modified | Renamed SP to `sp_get_user_api_activity_summary` |
| `src/Util/db/db_audit_analytics.py` | **Created** | DB wrapper: get_audit_logs, count_audit_logs, get_audit_statistics, get_security_events, get_failed_requests, get_user_api_activity_summary |
| `src/Util/audit_export.py` | **Created** | Export utility: validate_export_request, stream_csv_export, stream_json_export, _check_export_count |
| `src/Util/activity_logger.py` | Modified | Added `get_activity_by_id()` method and convenience function; added `search` param to get_recent_activity and count_activity_logs; added `get_recent_security_events()` convenience function |
| `src/routes/admin_dashboard.py` | Modified | Added `search` param to activity feed; added `GET /admin/activity/{activity_id}` endpoint |
| `src/routes/audit_logs.py` | **Created** | Full audit log monitor API: logs, security-events, statistics, export, user activity |
| `src/Util/db/__init__.py` | Modified | Exported 6 new audit analytics functions |
| `src/routes/__init__.py` | Modified | Added audit_logs import and export |
| `src/main.py` | Modified | Registered audit_logs router |
| `tests/integration/conftest.py` | Modified | Added db_audit_analytics to _DB_CONN_PATCH_LOCATIONS; fixed DBPatcher to use patch.object |
| `tests/unit/test_audit_export.py` | **Created** | 18 unit tests for export utility |
| `tests/unit/test_db_audit_analytics.py` | **Created** | 12 unit tests for DB wrapper |
| `tests/integration/test_slice15_audit_logs.py` | **Created** | 30 integration tests (2 skipped for streaming infra) |

## Test Evidence

| Slice | Proof / Suite | Result |
|------|----------------|--------|
| Unit: audit_export | `pytest tests/unit/test_audit_export.py` | ✅ 18 passed |
| Unit: db_audit_analytics | `pytest tests/unit/test_db_audit_analytics.py` | ✅ 12 passed |
| Integration: slice15 | `pytest tests/integration/test_slice15_audit_logs.py` | ✅ 28 passed, 2 skipped |

## Deviations

- **StreamingResponse tests skipped**: The `test_json_export` and `test_csv_export` integration tests are skipped due to a known incompatibility between httpx ASGI transport, Starlette's StreamingResponse, and the middleware stack. The export logic is fully validated by unit tests (test_audit_export.py).
- **DBPatcher fixed**: The original `DBPatcher` in conftest.py used `patch.multiple` which returns an empty dict when explicit `new` values are provided. Fixed to use `patch.object` with individual patchers, returning the mocks dict correctly.
- **Auth patching at route level**: All auth and DB function mocks in integration tests are applied at the route module level (`src.routes.audit_logs.*`) because functions are imported at module load time, not at call time.

## Issues Found

- **patch.multiple returns empty dict**: When `patch.multiple("module", attr=MagicMock())` is used, the `__enter__` returns an empty dict. This is Python's documented behavior — the dict only contains values when `new_callable` or `autospec` is used without explicit `new`. The DBPatcher was silently broken; no existing tests used it.

## Remaining Work

- None — all tasks from tasks.md are completed.
- The verify phase should run broader test suites to ensure no regressions.

## Status

**Ready for verify phase.** All implementation tasks complete. Unit and integration tests pass (60 passed, 2 skipped).

---

## Remediation Phase (Post-Verify Fixes)

### Issues Fixed

#### 1. Export source `api_audit` accepted (verify issue 2.1)
- **File**: `src/Util/audit_export.py`
- **Change**: Added `api_audit` to `VALID_SOURCES` set. Updated `_fetch_export_data`, `_check_export_count`, and `stream_csv_export` to treat `api_audit` identically to `audit`.
- **Tests**: Added unit tests `test_valid_api_audit_source`, `test_valid_api_audit_csv`. Integration test skipped (streaming incompatibility).

#### 2. Security-events merged limit enforced (verify issue 2.2)
- **File**: `src/routes/audit_logs.py`
- **Change**: Added `events = events[:limit]` after merge+sort to enforce limit on the final combined result, not per-source.
- **Tests**: Added `test_merged_total_limit_enforced` — asserts `limit=2` with 2 api + 1 activity events returns ≤2 total.

#### 3. User activity timeline shape corrected (verify issue 2.3)
- **File**: `src/routes/audit_logs.py`
- **Change**: Replaced aggregated `endpoint_activity` timeline entries with actual individual `get_audit_logs(user_id=...)` entries. Timeline now includes spec-required fields: `id`, `timestamp`, `http_method`, `endpoint_path`, `response_status`, `is_success`, `duration_ms`, `client_ip`.
- **Tests**: Added `test_user_activity_timeline_api_audit_shape` — verifies all spec-required fields are present and non-None. Updated `test_combined_summary` and `test_user_with_no_activity` with `get_audit_logs` mock.

#### 4. Malformed activity ID returns 400 VAL_3001 (verify issue 2.4)
- **File**: `src/routes/admin_dashboard.py`
- **Change**: Added regex validation `^act-[0-9a-fA-F]{32}$` for `activity_id` format. Non-matching IDs now return 400 `VAL_3001` instead of falling through to 404.
- **Tests**: Added `test_malformed_id_returns_400`. Updated `test_valid_id_returns_detail` and `test_nonexistent_id_returns_404` to use properly formatted IDs.

#### 5. Artifact drift corrected (verify warning)
- **File**: `.dev/sdd/changes/audit-log-monitor-api/apply-progress.md`
- **Change**: Corrected task count from "27 tasks" to "21 tasks" to match `tasks.md`.

### Test Evidence (Remediation)

| Slice | Proof / Suite | Result |
|------|----------------|--------|
| Unit: audit_export | `pytest tests/unit/test_audit_export.py` | ✅ 24 passed (was 18, +6 for api_audit) |
| Unit: db_audit_analytics | `pytest tests/unit/test_db_audit_analytics.py` | ✅ 12 passed |
| Integration: slice15 | `pytest tests/integration/test_slice15_audit_logs.py` | ✅ 31 passed, 3 skipped |
| **Total** | All audit tests | ✅ **67 passed, 3 skipped** |

### Remaining Risks

1. **Streaming export end-to-end tests remain skipped** — 3 tests skipped due to httpx ASGI + StreamingResponse + middleware incompatibility. Export logic is validated at unit level and handler-level runtime checks confirm `StreamingResponse` objects are returned.
2. **Activity ID regex is strict** — IDs must match `act-{32 hex chars}`. This is consistent with the `generate_activity_log_id()` function output. Any legacy IDs with different formats would be rejected with 400.
