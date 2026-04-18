# Exploration: API Deep Review Coverage — `api-deep-review-coverage`

**Date:** 2026-04-15
**Project:** api.auth (3-Tier User Type Multi-Project Authentication API)
**Stack:** Python 3.12, FastAPI 0.115, Pydantic 2, PyMySQL, Redis, python-jose, Argon2
**Prior Change:** `unit-test-coverage` (391 unit tests, all passing, 23% overall coverage)

---

## 1. Current Test Topology

| Dimension | Status |
|-----------|--------|
| **Unit tests** | **391 tests** — all passing, covering 11 pure-utility modules in `tests/unit/` |
| **Integration tests** | **ZERO** — no `tests/integration/` directory exists |
| **E2E / API tests** | **ZERO** — no `tests/routes/`, no `tests/e2e/`, no `httpx` TestClient usage |
| **Middleware tests** | **ZERO** — all 5 middleware classes are completely untested |
| **Route tests** | **ZERO** — all 11 route modules (auth, users, projects, admin_*, etc.) are untested |
| **DB layer tests** | **ZERO** — all 7 DB modules (`db_*.py`) are untested (only `db_error_wrapper` parsing is tested) |
| **Service tests** | **ZERO** — `cache_manager`, `activity_logger`, `decorators` are untested |
| **Coverage** | **23% overall** — good for pure utilities, catastrophic for routes/middleware/DB |

### Coverage Breakdown by Layer

| Layer | Files | Coverage | Tests |
|-------|-------|----------|-------|
| **Pure Utilities** | `uuid_generator`, `password_generator`, `password_security`, `error_handler`, `db_error_wrapper`, `api_audit_logger`, `log_context_models`, `Models`, `JWT_Security`, `Seccurity`, `system_metrics` | **60-100%** | 391 tests |
| **DB Layer** | `db_users`, `db_projects`, `db_user_groups`, `db_project_groups`, `db_enhanced`, `db_global_roles`, `db_permission_assignments`, `db_session_analytics`, `db_error_logger` | **0-19%** | 0 tests |
| **Services** | `cache_manager`, `activity_logger`, `decorators`, `bulk_operations`, `logger_ws`, `documentation_renderer` | **0-34%** | 0 tests |
| **Middleware** | `authentication`, `error_handler`, `request_validation`, `auth_context`, `api_audit`, `activity_logging` | **0%** | 0 tests |
| **Routes** | `auth`, `users`, `user_types_auth`, `projects`, `admin_user_groups`, `admin_project_groups`, `admin_dashboard`, `system`, `bulk_operations`, `global_roles`, `permission_assignments` | **0%** | 0 tests |
| **App Entry** | `main.py` | **0%** | 0 tests |

---

## 2. API Surface Map (All Endpoints)

### Auth Routes (`/auth/*`) — 7 endpoints
| Method | Path | Auth Required | DB Calls | Redis Calls |
|--------|------|--------------|----------|-------------|
| POST | `/auth/login` | No | `get_user_by_credentials`, `get_user_groups_for_user`, `get_user_accessible_projects`, `get_project_by_hash` | `_store_session` (set) |
| POST | `/auth/register` | No | `check_username_email_available`, `get_user_group_by_hash`, `get_projects_for_user_group`, `enhanced_register` | `_store_session` (via enhanced_register) |
| GET | `/auth/validate` | Yes (Bearer/Cookie) | `_get_session` (Redis) | `_get_session` (get) |
| POST | `/auth/logout` | Yes | `_delete_session` (Redis) | `_delete_session` (del) |
| POST | `/auth/refresh` | Yes | `_get_session`, `get_user_by_hash`, `get_project_by_hash`, `get_user_accessible_projects`, `get_user_groups_for_user` | `_delete_session` + `_store_session` |
| POST | `/auth/switch-project` | Yes | `_get_session`, `get_user_by_hash`, `get_project_by_hash`, `get_user_accessible_projects`, `get_user_groups_in_project` | `_delete_session` + `_store_session` |
| POST | `/auth/check-availability` | No | `check_username_email_available` | None |

### User Routes (`/users/*`) — 10 endpoints
| Method | Path | Auth Required | DB Calls |
|--------|------|--------------|----------|
| GET | `/users/profile` | Yes (via `log_context.user_hash`) | `get_user_by_hash`, `get_user_type_info`, `get_user_groups_for_user`, `get_user_accessible_projects`, `get_user_group_membership`, `get_user_effective_permissions` |
| PUT | `/users/profile` | Yes | `get_user_by_hash`, `update_user` |
| GET | `/users/access-summary` | Yes | `get_user_by_hash`, `get_user_type_info`, `get_user_groups_for_user`, `get_user_accessible_projects`, `get_projects_for_user_group`, `get_user_group_membership`, `get_user_effective_permissions`, `get_user_groups_in_project_by_hash` |
| GET | `/users/list` | Yes (root/admin) | `get_user_by_hash`, `is_root_user`, `get_user_type`, `list_users_with_access`, `count_users`, `get_user_accessible_projects`, `get_user_type_info`, `get_project_by_hash`, `get_user_effective_permissions` |
| GET | `/users/{user_hash}` | Yes | `get_user_by_hash` (×2), `is_root_user`, `get_user_type`, `get_user_accessible_projects` (×2), `get_user_type_info`, `get_user_groups_for_user`, `get_user_group_membership`, `get_projects_for_user_group`, `get_user_effective_permissions`, `get_user_groups_in_project_by_hash` |
| PUT | `/users/{user_hash}/status` | Yes | `get_user_by_hash` (×2), `is_root_user`, `get_user_type`, `get_user_accessible_projects` (×2), `update_user`, `invalidate_user_sessions`, `cache_manager.invalidate_user_cache` |
| POST | `/users/{user_hash}/reset-password` | Yes (admin) | `get_user_by_hash` (×2), `get_user_type`, `is_root_user`, `update_user` |
| DELETE | `/users/{user_hash}` | Yes (admin/root) | `get_user_by_hash` (×2), `is_root_user`, `get_user_type`, `get_user_accessible_projects` (×2), `delete_user`, `invalidate_user_sessions`, `cache_manager.invalidate_user_cache` |
| GET | `/users/search/query` | Yes (admin/root) | `get_user_by_hash`, `is_root_user`, `get_user_type`, `search_users` |
| PATCH | `/users/{user_hash}/type` | Yes (root only) | `get_user_by_hash` (×2), `is_root_user`, `update_user_type` |
| PUT | `/users/{user_hash}` | Yes (admin/root) | `get_user_by_hash` (×2), `is_root_user`, `get_user_type`, `get_user_accessible_projects` (×2), `update_user` |

### Project Routes (`/projects/*`) — 10 endpoints
| Method | Path | Auth Required | DB Calls |
|--------|------|--------------|----------|
| GET | `/projects` | Yes | `validate_session`, `get_user_by_hash`, `list_all_projects`/`search_projects`/`get_user_accessible_projects`, `get_user_project_permissions` |
| POST | `/projects` | Yes (admin) | `validate_session`, `get_user_by_hash`, `create_project` |
| GET | `/projects/{hash}` | Yes | `validate_session`, `get_user_by_hash`, `get_project_by_hash`, `get_user_project_permissions`, `get_project_stats`, `get_user_groups_for_user`, `get_permission_groups_for_project` |
| PUT | `/projects/{hash}` | Yes (admin) | `validate_session`, `get_user_by_hash`, `get_project_by_hash`, `update_project` |
| DELETE | `/projects/{hash}` | Yes (admin) | `validate_session`, `get_user_by_hash`, `get_project_by_hash`, `delete_project` |
| GET | `/projects/{hash}/members` | Yes (admin/manage_users) | `validate_session`, `get_project_by_hash`, `get_project_members_page`, `get_user_project_permissions`, `get_user_groups_for_user` |
| GET | `/projects/{hash}/activity` | Yes | `validate_session`, `get_user_by_hash`, `get_project_by_hash`, `get_user_project_permissions`, `get_recent_activity` |
| GET | `/projects/{hash}/stats` | Yes | `validate_session`, `get_user_by_hash`, `get_project_by_hash`, `get_user_project_permissions`, `get_project_stats` |
| PATCH | `/projects/{hash}/owner` | Yes (admin) | `validate_session`, `get_user_by_hash` (×3), `get_project_by_hash` — **TODO: placeholder implementation** |
| PATCH | `/projects/{hash}/archive` | Yes (admin) | `validate_session`, `get_user_by_hash`, `get_project_by_hash` — **TODO: placeholder implementation** |
| GET | `/projects/{hash}/groups` | Yes (admin/manage_users) | `validate_session`, `get_project_by_hash`, `get_user_groups_for_project` |

### System Routes (`/system/*`) — 6 endpoints
| Method | Path | Auth Required | DB/Redis |
|--------|------|--------------|----------|
| GET | `/system/info` | No | `count_users`, `count_projects`, `count_user_groups`, `count_project_permission_groups` |
| GET | `/system/health` | No | `count_users`, `redis_client.ping()` |
| GET | `/system/ping` | No | None |
| GET | `/system/cache/stats` | Yes | `cache_manager.get_cache_stats()` |
| POST | `/system/cache/clear` | Yes (admin/root) | `get_user_type`, `is_root_user`, `cache_manager.clear_all_cache()` |
| POST | `/system/cache/invalidate/user/{hash}` | Yes (admin/root) | `get_user_type`, `is_root_user`, `get_user_by_hash`, `cache_manager.invalidate_user_cache()` |
| POST | `/system/cache/invalidate/project/{id}` | Yes (admin/root) | `get_user_type`, `is_root_user`, `cache_manager.invalidate_project_cache()` |

### Other Route Modules (not enumerated in detail)
- `/admin/dashboard/*` — 4+ endpoints (stats, activity, health)
- `/admin/user-groups/*` — 8+ endpoints (CRUD, members, project-groups)
- `/admin/project-groups/*` — 6+ endpoints (CRUD, projects)
- `/user-types/*` — 4+ endpoints (root/admin user creation)
- `/bulk/*` — 4+ endpoints (bulk operations)
- `/global-roles/*` — 8+ endpoints (RBAC management)
- `/permission-assignments/*` — 8+ endpoints (permission group assignments)

---

## 3. Risky Seams & Blind Spots

### 3.1 CRITICAL: Auth Flow — Zero Integration Testing

| Seam | Risk | Why |
|------|------|-----|
| `routes/auth.py` — full login flow | **CRITICAL** | 7 endpoints, zero tests. Login touches: credential verification, user group resolution, project access resolution, JWT creation, Redis session storage, cookie setting. A regression here breaks the entire system. |
| `routes/auth.py` — register flow | **CRITICAL** | Multi-step: availability check → group validation → group-project linkage → user creation → session creation → cookie. No test coverage. |
| `routes/auth.py` — refresh/switch-project | **HIGH** | Session rotation, new JWT generation, old session deletion. Token lifecycle bugs = auth bypass or session fixation. |
| `db/db_enhanced.py` — `validate_session` | **CRITICAL** | Cache-first validation with 10% coverage. Core auth gate for all protected endpoints. Complex branching for root/admin/consumer. |
| `middleware/authentication.py` | **HIGH** | `verify_session`, `verify_admin_access`, `verify_root_access`, `require_permission` — 0% coverage. These are the authorization backbone. |

### 3.2 HIGH: Permission Enforcement — Untested Branches

| Seam | Risk | Why |
|------|------|-----|
| `routes/users.py` — admin vs root vs consumer branching | **HIGH** | Every user endpoint has complex permission checks: `is_root_user()`, `get_user_type()`, project overlap checks. 0% tested. |
| `routes/projects.py` — admin permission gating | **HIGH** | Create/update/delete all require `'admin' in user_permissions`. List has admin vs consumer branching. 0% tested. |
| `routes/projects.py` — placeholder endpoints | **MEDIUM** | `/projects/{hash}/owner` and `/projects/{hash}/archive` have `success = True` hardcoded (TODO). No test will catch this. |
| Groups-of-groups permission resolution | **HIGH** | `get_user_project_permissions` in `db_project_groups.py` (14% coverage) is the core permission resolver. Complex SQL with multiple JOINs. |

### 3.3 HIGH: Middleware Stack — Completely Untested

| Seam | Risk | Why |
|------|------|-----|
| `middleware/error_handler.py` — exception handlers | **HIGH** | 4 handlers (AppException, HTTPException, validation, generic). DB error logging, UUID masking, function context extraction. 0% coverage. |
| `middleware/api_audit.py` — audit logging | **MEDIUM** | Full request/response capture, background task attachment, sensitive data filtering at middleware level. 0% coverage. |
| `middleware/auth_context.py` — context extraction | **MEDIUM** | Sets `request.state.user` from JWT. Silent failure on errors. 0% coverage. |
| `middleware/request_validation.py` — input validation | **MEDIUM** | User-agent enforcement, 8MB POST limit, IP extraction, activity context. 0% coverage. |
| Middleware ordering dependency | **HIGH** | `main.py` adds middleware in this order: CORS → RequestValidation → APIAudit → AuthContext. If order changes, auth_context won't be available for audit logging. No test verifies this. |

### 3.4 MEDIUM: DB Layer — Near-Zero Coverage

| Seam | Risk | Why |
|------|------|-----|
| `db/db_users.py` — 469 stmts, 12% coverage | **HIGH** | User CRUD, session management, admin project assignments. 413 lines untested. |
| `db/db_enhanced.py` — 211 stmts, 10% coverage | **CRITICAL** | `enhanced_login`, `enhanced_register`, `validate_session`, session creation with user type context. 189 lines untested. |
| `db/db_user_groups.py` — 246 stmts, 13% coverage | **HIGH** | Group CRUD, membership, project access via groups-of-groups. 214 lines untested. |
| `db/db_project_groups.py` — 214 stmts, 14% coverage | **HIGH** | Permission groups, effective permission resolution. 185 lines untested. |
| `cache_manager.py` — 225 stmts, 20% coverage | **MEDIUM** | Redis caching for sessions, permissions, user info. 180 lines untested. |
| `activity_logger.py` — 330 stmts, 0% coverage | **MEDIUM** | Stored procedure calls, context vars, 30+ convenience methods. |

### 3.5 LOW: Known Code Quality Issues

| Issue | Location | Impact |
|-------|----------|--------|
| Bare `except:` in `is_root_user`, `is_admin_user`, `is_consumer_user`, `check_admin_project_access` | `db/db_enhanced.py:64-94` | Swallows all errors, returns False silently. Could mask DB failures as "not root" |
| `print()` statements in `JWT_Security.py`, `Seccurity.py` | Multiple | Not logging, goes to stdout. Hard to capture in tests. |
| `datetime.utcnow()` deprecation warnings | Multiple files | 29 warnings in test run. Will break in Python 3.14+. |
| Hardcoded `success = True` in project owner/archive endpoints | `routes/projects.py:795,882` | TODO placeholders that always succeed. |

---

## 4. Current Proof Gaps

### 4.1 What IS Tested (Layer 1 — Pure Unit Tests)

| Module | Tests | Coverage | What's Covered |
|--------|-------|----------|----------------|
| `uuid_generator.py` | ~30 | 100% | All generators, uniqueness, format |
| `password_generator.py` | ~25 | 100% | Temp passwords, reset tokens, strength validation |
| `password_security.py` | ~18 | 88% | Argon2 hash/verify, legacy migration, `_is_legacy_hash` |
| `error_handler.py` | ~45 | 91% | UUID masking, enums, exception classes, DEBUG_MODE |
| `db_error_wrapper.py` | ~20 | 91% | Duplicate parsing, UUID validation, `handle_db_operation` with mocked exceptions |
| `api_audit_logger.py` | ~45 | 81% | Path filtering, sensitive data filtering, tag generation, resource extraction |
| `log_context_models.py` | ~12 | 100% | Pydantic model defaults and validation |
| `Models.py` | ~25 | 100% | Key request/response models |
| `JWT_Security.py` | ~18 | 94% | Token create/decode/extract/validate, compat functions |
| `Seccurity.py` | ~16 | 60% | Token extraction, `returnJson_*` helpers, `HTTPBearerOrCookie` |
| `system_metrics.py` | ~20 | 34% | `calculate_health_score` only |

### 4.2 What IS NOT Tested (The Gaps)

| Gap Category | Specific Gaps | Risk Level |
|-------------|--------------|------------|
| **No HTTP-level tests** | No `httpx` TestClient usage. No endpoint is called through the FastAPI app. | **CRITICAL** |
| **No auth flow tests** | Login → validate → logout cycle never tested end-to-end. | **CRITICAL** |
| **No permission tests** | Admin vs consumer vs root access control never verified at the HTTP level. | **CRITICAL** |
| **No session lifecycle tests** | Session creation, storage, retrieval, deletion, rotation — all untested. | **HIGH** |
| **No cookie behavior tests** | Cookie setting, clearing, httpOnly/secure/samesite flags — untested. | **HIGH** |
| **No middleware behavior tests** | Error handler responses, audit logging, auth context extraction, request validation — untested. | **HIGH** |
| **No DB integration tests** | All DB functions tested only via mocked exceptions, never with real queries. | **HIGH** |
| **No Redis integration tests** | `cache_manager` and session storage tested only with `fakeredis` in unit tests, never through the app. | **MEDIUM** |
| **No error response shape tests** | Error responses from the API (via middleware handlers) never validated. | **MEDIUM** |
| **No 401/403 behavior tests** | What happens when an unauthenticated request hits a protected endpoint? Untested. | **HIGH** |
| **No CORS behavior tests** | `allow_origins=["*"]` — no test verifies CORS headers. | **LOW** |
| **No documentation endpoint tests** | `/documentation/*`, `/docs/USAGE/*` — untested. | **LOW** |

### 4.3 Mock vs Real Dependency Analysis

Current tests use mocks for:
- `db_config.redis_client` → `fakeredis.FakeStrictRedis`
- `db_config.get_connection` → `MagicMock`
- `pymysql.*` exceptions → instantiated directly
- `freezegun` for time freezing

**What should use REAL dependencies (per user request: "NO mocks for the code under test"):**
- Auth flow tests should use **real Redis** (via fakeredis is acceptable for session storage since it's in-memory compatible)
- Permission tests should use **real DB queries** (or at minimum, integration-level fixtures with a test database)
- Middleware tests should run through the **real FastAPI app** with `httpx.TestClient`
- Error handler tests should exercise the **real exception handlers** registered on the app

---

## 5. Candidate Proving Layers

### Layer 1: Unit Tests (EXISTING — 391 tests, 23% coverage)
Already complete for pure utilities. No changes needed here.

### Layer 2: Integration Tests — Auth Flow Through TestClient
**Proof layer:** Component-level HTTP tests using `httpx.AsyncClient` with FastAPI's `TestClient`.
**Dependencies:** Real app instance, mocked DB connections, `fakeredis` for Redis.
**What to prove:**
- Login with valid credentials → 200 + session_token + cookie
- Login with invalid credentials → 401
- Register new user → 200 + session_token + cookie
- Validate valid session → 200 + user info
- Validate expired session → 401
- Logout → 200 + cookie cleared
- Refresh token → 200 + new session_token
- Switch project → 200 + new session_token
- Check availability → 200 + availability status

### Layer 3: Integration Tests — Permission Enforcement
**Proof layer:** HTTP tests verifying access control at the route level.
**What to prove:**
- Unauthenticated request to protected endpoint → 401
- Consumer user accessing admin endpoint → 403
- Admin user accessing root-only endpoint → 403
- Root user accessing any endpoint → 200
- Admin user managing users in their project → 200
- Admin user managing users outside their project → 403

### Layer 4: Integration Tests — Project CRUD
**Proof layer:** HTTP tests for project lifecycle.
**What to prove:**
- Create project (admin) → 200
- List projects (admin sees all, consumer sees accessible) → 200
- Get project details → 200
- Update project (admin) → 200
- Delete project (admin) → 200
- Project not found → 404

### Layer 5: Integration Tests — Middleware Behavior
**Proof layer:** HTTP tests verifying middleware stack behavior.
**What to prove:**
- Request without user-agent → 422
- POST > 8MB → 413
- Unhandled exception → standardized error response (500)
- Validation error → standardized error response (400)
- AppException → standardized error response with correct code/category
- Audit logging captures requests (verify via mock/spy)

### Layer 6: Contract Tests — Response Shape Validation
**Proof layer:** Schema validation of API responses.
**What to prove:**
- All responses match their Pydantic response models
- Error responses have consistent structure: `{status, error: {code, category, message}}`
- Pagination responses have consistent structure

### Layer 7: Security Tests
**Proof layer:** Behavioral security tests.
**What to prove:**
- Token tampering → 401
- Expired token → 401
- SQL injection in form fields → rejected or safe
- XSS in response bodies → sanitized
- Sensitive data not leaked in error responses (passwords, tokens)
- CORS headers present

---

## 6. Recommended Slice Order (Smallest Sensible Slices)

### Slice 0 — Test Infrastructure for Integration Tests
**What:** Add `conftest.py` fixtures for `httpx.AsyncClient`, test app instance, mocked DB/Redis at integration level.
**Gate:** `pytest --collect-only` succeeds with integration test files.

### Slice 1 — Health & Ping Endpoints (System Routes)
**What:** `GET /ping`, `GET /system/ping`, `GET /system/info`, `GET /system/health`.
**Why first:** Simplest endpoints, no auth required, minimal DB calls. Proves TestClient works.
**Proof layer:** Layer 2 (integration).

### Slice 2 — Auth Flow: Login (Happy Path + Failures)
**What:** `POST /auth/login` with valid credentials, invalid credentials, missing fields, root user, consumer user with/without project.
**Proof layer:** Layer 2 (integration).
**Dependencies:** Requires mocked DB for `get_user_by_credentials`, `get_user_groups_for_user`, `get_user_accessible_projects`, `get_project_by_hash`. Requires `fakeredis` for session storage.

### Slice 3 — Auth Flow: Register
**What:** `POST /auth/register` with valid data, duplicate username, missing group, group without projects.
**Proof layer:** Layer 2 (integration).

### Slice 4 — Auth Flow: Validate, Logout, Refresh
**What:** `GET /auth/validate`, `POST /auth/logout`, `POST /auth/refresh`.
**Proof layer:** Layer 2 (integration).
**Dependencies:** Requires a valid session from Slice 2.

### Slice 5 — Auth Flow: Switch Project + Check Availability
**What:** `POST /auth/switch-project`, `POST /auth/check-availability`.
**Proof layer:** Layer 2 (integration).

### Slice 6 — Permission Enforcement (Auth Boundary Tests)
**What:** Unauthenticated → 401 on all protected endpoints. Consumer → 403 on admin endpoints. Root → 200 everywhere.
**Proof layer:** Layer 3 (integration).

### Slice 7 — User Profile & Access Summary
**What:** `GET /users/profile`, `GET /users/access-summary`, `PUT /users/profile`.
**Proof layer:** Layer 2 (integration).

### Slice 8 — User Management (Admin Operations)
**What:** `GET /users/list`, `GET /users/{hash}`, `PUT /users/{hash}/status`, `DELETE /users/{hash}`, `POST /users/{hash}/reset-password`.
**Proof layer:** Layer 3 (integration).

### Slice 9 — Project CRUD
**What:** Full project lifecycle: create, list, get, update, delete.
**Proof layer:** Layer 4 (integration).

### Slice 10 — Middleware: Error Handler
**What:** Standardized error responses, validation errors, unhandled exceptions, DEBUG_MODE behavior.
**Proof layer:** Layer 5 (integration).

### Slice 11 — Middleware: Request Validation + Auth Context
**What:** User-agent rejection, POST size limit, auth context extraction, activity logging context.
**Proof layer:** Layer 5 (integration).

### Slice 12 — Middleware: API Audit
**What:** Audit logging captures requests, excludes health/ping/docs, filters sensitive data.
**Proof layer:** Layer 5 (integration).

### Slice 13 — Security & Contract Tests
**What:** Response shape validation, token tampering, SQL injection resistance, sensitive data leakage.
**Proof layer:** Layer 6 + 7.

---

## 7. Major Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **All route handlers call real DB functions** | **CRITICAL** | Integration tests MUST mock DB at the function level (`patch("src.Util.db.get_user_by_credentials", ...)`). This is fragile — if function signatures change, patches break. |
| **`db_config.py` creates `redis_client` at import time** | **HIGH** | Already handled by `conftest.py` with `fakeredis`. Integration tests must ensure this patch is active before importing the app. |
| **`validate_session` in routes uses the old `db.validate_session` (from `db_enhanced`)** | **HIGH** | This function calls Redis + DB + cache. Must mock it entirely for route tests, or use a real test DB. |
| **`log_context` dependency injection** | **MEDIUM** | Routes expect `log_context: LogContext = None` from dependency injection. TestClient must provide this via custom dependencies override. |
| **Middleware ordering affects behavior** | **MEDIUM** | If middleware order changes in `main.py`, auth_context won't be available for audit. No test currently verifies middleware order. |
| **Placeholder endpoints (`/projects/{hash}/owner`, `/projects/{hash}/archive`)** | **MEDIUM** | Always return `success = True`. Tests will pass but behavior is wrong. Should be flagged and fixed. |
| **Bare `except:` in `db_enhanced.py` type checkers** | **LOW** | `is_root_user()`, `is_admin_user()`, `is_consumer_user()` swallow all errors. Tests should verify they return False on DB failure. |
| **`datetime.utcnow()` deprecation** | **LOW** | 29 warnings. Will break in Python 3.14+. Should fix as part of this change. |
| **No test database available** | **HIGH** | Integration tests need either: (a) a real test MySQL instance, (b) Docker-based testcontainers, or (c) extensive mocking. Option (c) is the only viable path without infrastructure changes. |

---

## 8. Recommended Direction

### Immediate Priorities (Week 1)
1. **Set up integration test infrastructure**: `conftest.py` fixtures for `httpx.AsyncClient`, app instance, DB/Redis mocking at integration level
2. **Write health/ping tests** (Slice 1) — prove the TestClient works
3. **Write auth login tests** (Slice 2) — the most critical flow
4. **Write permission boundary tests** (Slice 6) — verify 401/403 behavior

### Short-term (Week 2)
5. **Complete auth flow** (Slices 3-5) — register, validate, logout, refresh, switch-project
6. **User profile and management** (Slices 7-8)
7. **Project CRUD** (Slice 9)

### Medium-term (Week 3)
8. **Middleware tests** (Slices 10-12) — error handler, request validation, audit
9. **Security and contract tests** (Slice 13)

### Key Principles
- **NO mocks for the HTTP layer** — use real `httpx.AsyncClient` against the real FastAPI app
- **Mock at the DB boundary** — patch `src.Util.db.*` functions, not the HTTP layer
- **Use `fakeredis` for Redis** — it's an in-memory compatible replacement, not a mock
- **Test error paths** — 401, 403, 404, 500 responses are as important as 200
- **Verify response shapes** — every response should match its Pydantic model
- **Fix defects found** — if placeholder endpoints or bare excepts cause test failures, fix the root cause

---

## 9. Fixture Strategy for Integration Tests

```python
# tests/conftest.py — additional fixtures for integration tests

@pytest.fixture
def app():
    """Return the FastAPI app instance."""
    from src.main import app
    return app

@pytest.fixture
async def client(app):
    """Async httpx test client."""
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test"
    ) as ac:
        yield ac

@pytest.fixture
def mock_db():
    """Mock all DB functions at the module level."""
    with patch.multiple(
        "src.Util.db",
        get_user_by_credentials=MagicMock(),
        get_user_by_hash=MagicMock(),
        get_user_groups_for_user=MagicMock(return_value=[]),
        get_user_accessible_projects=MagicMock(return_value=[]),
        get_project_by_hash=MagicMock(),
        validate_session=MagicMock(),
        # ... add more as needed
    ) as mocks:
        yield mocks

@pytest.fixture
def mock_redis():
    """fakeredis for session storage."""
    fake = fakeredis.FakeStrictRedis()
    with patch("src.Util.db_config.redis_client", fake):
        yield fake
    fake.flushall()
```

---

## 10. Status: READY FOR `tdd-strategy`

The exploration is complete. The codebase has been fully mapped at the API, route, middleware, and DB layer levels. 391 unit tests exist and pass (23% coverage), but **zero integration, e2e, or route-level tests exist**. The recommended slice order prioritizes auth flow and permission enforcement first, then expands to CRUD and middleware behavior.
