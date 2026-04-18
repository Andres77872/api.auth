# TDD Strategy: api-deep-review-coverage

## Mode
**SDD-assisted TDD** — exploration and defect mapping completed via `explore.md` and deep grep audit. No formal spec/design SDD artifacts exist, but the audit serves as the authoritative defect catalog and requirement source.

## Linked Artifacts
- `.dev/tdd/changes/api-deep-review-coverage/explore.md` — exploration, test seam mapping, slice ordering
- Deep grep audit (context-bridge output #1) — route map, defect catalog, architecture analysis
- No SDD artifacts under `.dev/sdd/changes/api-deep-review-coverage/` (none exist)

## Variant Choice
**Outside-in + Contract-heavy** — tests drive from the HTTP layer inward using `httpx.AsyncClient` against the real FastAPI app. Every slice validates:
1. **HTTP contract** — status codes, response shape, headers, cookies
2. **Behavioral contract** — auth flows, permission boundaries, middleware interactions
3. **Error contract** — standardized error responses via `error_handler.py` exception handlers

**No mocks for the code under test.** The HTTP layer, middleware stack, and route handlers run for real. Test doubles are ONLY used at infrastructure boundaries:
- **DB layer**: `patch("src.Util.db.*")` — route handlers call real DB functions, but we control their return values at the module boundary
- **Redis**: `fakeredis.FakeStrictRedis` — in-memory compatible replacement, not a mock
- **External services**: None exist in this codebase (no email, no webhooks)

---

## Slice Plan

### Slice 0 — [P] Test Infrastructure Bootstrap
**What:** `tests/integration/conftest.py` with fixtures for `httpx.AsyncClient`, FastAPI app instance, DB patching helpers, fakeredis injection, and test user factories.
**Proof layer:** N/A (infrastructure only)
**Gate:** `pytest tests/integration/ --collect-only` succeeds; at least one placeholder test runs and passes.
**Dependencies:** None beyond existing `conftest.py` and `requirements-test.txt`.
**Key design decisions:**
- `app` fixture imports `src.main.app` AFTER `.env.test` is loaded (existing conftest handles this)
- `client` fixture uses `httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test")`
- `patched_db` fixture patches ALL `src.Util.db.*` functions used by routes under test — not a blanket patch, only what each slice needs
- `fake_redis` fixture patches `src.Util.db_config.redis_client` with `fakeredis.FakeStrictRedis()`
- Test user factories return pre-constructed dicts/objects matching what DB functions would return

### Slice 1 — Health & Ping Endpoints (System Routes, No Auth)
**What:** `GET /ping` (204), `GET /system/ping` (200), `GET /system/health` (200), `GET /system/info` (200).
**Proof layer:** Integration via `httpx.AsyncClient` + real app.
**Dependencies:** `system/health` calls `count_users`, `count_projects`, `count_user_groups`, `count_project_permission_groups`, and `redis_client.ping()`. All must be patched.
**Why first:** Zero auth, minimal DB calls, proves the TestClient pipeline works end-to-end through the middleware stack.
**Trace to explore:** Section 6, Slice 1; Section 4.2 "No HTTP-level tests" gap.

### Slice 2 — Auth Flow: Login (Happy Path + Failure Modes)
**What:** `POST /auth/login` — valid credentials (200 + token + cookie), invalid credentials (401), missing fields (422), root user login (no project), consumer user with project, consumer user without project.
**Proof layer:** Integration via `httpx.AsyncClient` + real app + real middleware stack.
**Dependencies:** Patch `get_user_by_credentials`, `get_user_groups_for_user`, `get_user_accessible_projects`, `get_project_by_hash`. Use `fakeredis` for `_store_session`.
**Key behaviors to prove:**
- Successful login returns `LoginResponse` shape with `session_token`, `user`, `accessible_projects`, `user_groups`
- Cookie `session_token` is set with `httponly`, `secure`, `samesite=strict` flags
- Failed login returns standardized error (not raw exception)
- Root user login succeeds without `project_hash`
**Trace to explore:** Section 3.1 CRITICAL; Section 6, Slice 2.
**Defect to catch:** No rate limiting on login (grep audit #5) — test documents absence, does not fix.

### Slice 3 — Auth Flow: Register
**What:** `POST /auth/register` — valid registration (200 + token + cookie), duplicate username (409), invalid group hash (404), group with no projects (400).
**Proof layer:** Integration via `httpx.AsyncClient` + real app.
**Dependencies:** Patch `check_username_email_available`, `get_user_group_by_hash`, `get_projects_for_user_group`, `enhanced_register`. Use `fakeredis`.
**Trace to explore:** Section 3.1 CRITICAL; Section 6, Slice 3.

### Slice 4 — Auth Flow: Validate, Logout, Refresh
**What:** `GET /auth/validate` (valid session → 200, expired → 401, missing token → 401), `POST /auth/logout` (200 + cookie cleared), `POST /auth/refresh` (200 + new token, old token invalidated).
**Proof layer:** Integration via `httpx.AsyncClient` + real app.
**Dependencies:** Requires a valid session from Slice 2. Patch `_get_session`, `_delete_session`, `_store_session` via fakeredis. Patch `get_user_by_hash`, `get_project_by_hash`, `get_user_accessible_projects`, `get_user_groups_for_user`.
**Trace to explore:** Section 3.1; Section 6, Slice 4.

### Slice 5 — Auth Flow: Switch Project + Check Availability
**What:** `POST /auth/switch-project` (valid switch → 200 + new token, invalid project → 404), `POST /auth/check-availability` (available → 200, taken → 409).
**Proof layer:** Integration via `httpx.AsyncClient` + real app.
**Dependencies:** Requires valid session. Patch `_get_session`, `_delete_session`, `_store_session`, `get_user_by_hash`, `get_project_by_hash`, `get_user_accessible_projects`, `get_user_groups_in_project`.
**Trace to explore:** Section 6, Slice 5.

### Slice 6 — Permission Enforcement (Auth Boundary Tests)
**What:** Unauthenticated request → 401 on every protected endpoint category. Consumer user → 403 on admin endpoints. Admin user → 403 on root-only endpoints. Root user → 200 everywhere.
**Proof layer:** Integration via `httpx.AsyncClient` + real app + real middleware.
**Dependencies:** Patch all DB functions. Use different session payloads to simulate root/admin/consumer user types.
**Key behaviors to prove:**
- `verify_session` dependency rejects missing/invalid tokens with 401
- `verify_admin_access` rejects consumer with 403
- `verify_root_access` rejects admin with 403
- `require_permission` rejects users lacking specific permission with 403
**Trace to explore:** Section 3.2 HIGH; Section 6, Slice 6; grep audit "Inconsistent Auth Patterns" (#6).
**Defect to document:** Five different auth check patterns across routes — tests expose the inconsistency.

### Slice 7 — User Profile & Access Summary
**What:** `GET /users/profile` (authenticated → 200 + profile), `GET /users/access-summary` (authenticated → 200 + hierarchical access), `PUT /users/profile` (valid update → 200, invalid → 400).
**Proof layer:** Integration via `httpx.AsyncClient` + real app.
**Dependencies:** Patch `get_user_by_hash`, `get_user_type_info`, `get_user_groups_for_user`, `get_user_accessible_projects`, `get_user_group_membership`, `get_user_effective_permissions`, `update_user`.
**Trace to explore:** Section 6, Slice 7.

### Slice 8 — User Management (Admin Operations)
**What:** `GET /users/list` (admin → 200 + paginated list), `GET /users/{hash}` (self/admin/root → 200), `PUT /users/{hash}/status` (activate/deactivate → 200), `DELETE /users/{hash}` (soft delete → 200), `POST /users/{hash}/reset-password` (admin reset → 200).
**Proof layer:** Integration via `httpx.AsyncClient` + real app.
**Dependencies:** Patch all user DB functions. Patch `invalidate_user_sessions`, `cache_manager.invalidate_user_cache`.
**Defect to FIX:** `POST /users/{hash}/reset-password` returns `temporary_password` in plaintext JSON response body (grep audit #4, `users.py:853`). **This is a security defect — the test MUST fail first, then the code is fixed to NOT return the plaintext password.** The fix: return only `expires_at` and `must_change_on_login`, never the password itself.
**Trace to explore:** Section 6, Slice 8; grep audit "Plaintext Password in Response" (#4).

### Slice 9 — Project CRUD
**What:** `GET /projects` (list with admin/consumer branching), `POST /projects` (admin create → 200), `GET /projects/{hash}` (details → 200), `PUT /projects/{hash}` (admin update → 200), `DELETE /projects/{hash}` (admin delete → 200), `GET /projects/{hash}/members`, `GET /projects/{hash}/activity`, `GET /projects/{hash}/stats`, `GET /projects/{hash}/groups`.
**Proof layer:** Integration via `httpx.AsyncClient` + real app.
**Dependencies:** Patch `validate_session`, `get_user_by_hash`, `create_project`, `get_project_by_hash`, `update_project`, `delete_project`, `list_all_projects`, `search_projects`, `get_user_accessible_projects`, `get_user_project_permissions`, `get_project_members_page`, `get_recent_activity`, `get_project_stats`, `get_user_groups_for_project`, `get_permission_groups_for_project`.
**Defects to FIX:**
1. `PATCH /projects/{hash}/owner` — hardcoded `success = True` with no logic (grep audit #3, `projects.py:795`). **Test fails → implement real ownership transfer or return 501 Not Implemented with proper error.**
2. `PATCH /projects/{hash}/archive` — same stub pattern (`projects.py:882`). **Test fails → implement real archive logic or return 501.**
3. Pagination `total` is `len(projects_with_access)` not actual total (`projects.py:139`). **Test fails → fix to use actual count.**
**Trace to explore:** Section 3.2; Section 6, Slice 9; grep audit "Stub Endpoints" (#3), "Pagination Total Mismatch" (#11).

### Slice 10 — Middleware: Error Handler Contract
**What:** Verify all 5 exception handlers produce standardized responses: `AppException` → structured error with code/category, `HTTPException` → mapped to standard format, `RequestValidationError` → field-level errors, generic `Exception` → 500 with masked UUID, `StarletteHTTPException` → handled.
**Proof layer:** Integration via `httpx.AsyncClient` + real app + registered exception handlers.
**Dependencies:** Trigger errors through real route handlers. No DB patching needed for pure error-shape tests (trigger validation errors, missing auth, etc.).
**Key behaviors to prove:**
- Error response shape: `{status: "error", error: {code, category, message}}`
- UUID masking in error messages (production mode)
- DEBUG_MODE exposes stack traces
- `X-Request-ID` header present
**Trace to explore:** Section 3.3 HIGH; Section 6, Slice 10; grep audit "Error Response Contracts" gap.

### Slice 11 — Middleware: Request Validation + Auth Context
**What:** Missing User-Agent header → 422, POST > 8MB → 413, valid request → `X-Process-Time` header present, auth context extraction (valid token → `request.state.user` populated, invalid token → silent failure).
**Proof layer:** Integration via `httpx.AsyncClient` + real app + real middleware stack.
**Dependencies:** No DB patching needed for User-Agent/size tests. Auth context tests need fakeredis + patched `validate_session`.
**Trace to explore:** Section 3.3; Section 6, Slice 11.

### Slice 12 — Middleware: API Audit
**What:** Verify audit logging captures requests to protected endpoints, excludes health/ping/docs paths, and filters sensitive data from logged request bodies.
**Proof layer:** Integration via `httpx.AsyncClient` + real app.
**Dependencies:** Patch `api_audit_logger.write_audit_log` or verify via mock spy that audit was called with correct parameters.
**Trace to explore:** Section 3.3; Section 6, Slice 12.

### Slice 13 — Security & Contract Tests
**What:** Token tampering → 401, expired token → 401, empty Bearer token → 401 (not 500), CORS headers present on responses, sensitive data not leaked in error responses (passwords, tokens, internal IDs), response shapes match Pydantic models.
**Proof layer:** Integration + contract validation.
**Dependencies:** JWT manipulation via `PyJWT` directly. CORS verification via response headers.
**Defect to FIX:** `src/main.py:50-56` — `allow_origins=["*"]` with `allow_credentials=True` is a security anti-pattern. **Test verifies CORS behavior → fix to use explicit allowed origins list.**
**Defect to FIX:** `Seccurity.py:73` — empty Bearer token `""` accepted. **Test fails → fix to reject empty tokens.**
**Trace to explore:** Section 3.5; Section 6, Slice 13; grep audit "CORS Misconfiguration" (#1), "Empty Bearer Token" (#8).

### Slice 14 — Route Conflict Detection
**What:** Verify that `GET /users/me/permissions` and `GET /users/me/permissions/check/{name}` resolve to the correct handler (shadowed routes from `permission_assignments.py` vs `global_roles.py`).
**Proof layer:** Integration via `httpx.AsyncClient` + real app.
**Dependencies:** Patch both `check_user_has_permission` (old) and `check_user_has_permission_extended` (new) to return different values — verify which one is actually called.
**Defect to FIX:** Route shadowing means `permission_assignments.py` versions are dead code (grep audit #2). **Test fails → fix by removing duplicate routes or merging the implementations.**
**Trace to explore:** grep audit "Duplicate Route Shadowing" (#2).

### Slice 15 — datetime.utcnow() Deprecation Fix
**What:** Find all `datetime.utcnow()` usages, replace with `datetime.now(timezone.utc)`, verify no deprecation warnings in test output.
**Proof layer:** Static analysis + runtime verification (run tests with `-W error::DeprecationWarning`).
**Dependencies:** None — pure code fix.
**Trace to explore:** explore.md Section 3.5; grep audit #9.

---

## Slice Ordering Summary

| # | Slice | Parallel? | Depends On | Defects Addressed |
|---|-------|-----------|------------|-------------------|
| 0 | Test Infrastructure | **[P]** | None | — |
| 1 | Health & Ping | **[P]** | 0 | — |
| 2 | Auth: Login | — | 0 | Documents #5 (no rate limiting) |
| 3 | Auth: Register | **[P]** | 0 | — |
| 4 | Auth: Validate/Logout/Refresh | — | 2 | — |
| 5 | Auth: Switch Project/Availability | — | 2 | — |
| 6 | Permission Enforcement | — | 2 | Documents #6 (inconsistent auth) |
| 7 | User Profile & Access Summary | **[P]** | 6 | — |
| 8 | User Management (Admin) | — | 6 | **Fixes #4** (plaintext password) |
| 9 | Project CRUD | — | 6 | **Fixes #3** (stub endpoints), **#11** (pagination) |
| 10 | Middleware: Error Handler | **[P]** | 0 | — |
| 11 | Middleware: Request Validation | **[P]** | 0 | — |
| 12 | Middleware: API Audit | **[P]** | 10 | — |
| 13 | Security & Contract | — | 2, 6 | **Fixes #1** (CORS), **#8** (empty Bearer) |
| 14 | Route Conflict Detection | **[P]** | 6 | **Fixes #2** (shadowed routes) |
| 15 | datetime.utcnow() Fix | **[P]** | None | **Fixes #9** (deprecation) |

---

## Gates

| Gate | Required? | Why |
|------|-----------|-----|
| **All existing 391 unit tests pass** | **YES** | No regression in pure utility layer |
| **New integration tests pass** | **YES** | Each slice must be GREEN before merging |
| **No new deprecation warnings** | **YES** | `-W error::DeprecationWarning` on test run (Slice 15) |
| **Coverage increase measurable** | **YES** | Routes/middleware/DB coverage must increase from 0% |
| **No test workarounds for real defects** | **YES** | If a test fails due to a real bug, fix the bug — don't skip/xfail/patch around it |
| **Response shape validation** | **YES** | All 2xx/4xx/5xx responses validated against expected structure |
| **Cookie flags verified** | **YES** | `httponly`, `secure`, `samesite=strict` on session_token cookie |
| **CORS headers verified** | **YES** | After fix, explicit origins only (no `*` with credentials) |

---

## Commands / Suites

| Scope | Command |
|-------|---------|
| **Full test suite (existing + new)** | `pytest -v` |
| **Existing unit tests only** | `pytest tests/unit/ -v` |
| **Integration tests only** | `pytest tests/integration/ -v` |
| **Single slice (RED/GREEN loop)** | `pytest tests/integration/test_{slice_name}.py -v --tb=short` |
| **Coverage report** | `pytest --cov=src --cov-report=term-missing --cov-report=html` |
| **Deprecation warning check** | `pytest -W error::DeprecationWarning` |
| **Collect only (infrastructure check)** | `pytest tests/integration/ --collect-only` |
| **Fast feedback (last failed)** | `pytest --lf -v` |

---

## Real Dependency Usage Policy

| Layer | Approach | Rationale |
|-------|----------|-----------|
| **HTTP layer** | **REAL** — `httpx.AsyncClient` + `ASGITransport(app=app)` | User requirement: no mocks for code under test |
| **Middleware stack** | **REAL** — all 4 middleware run in actual order | Middleware interaction is the thing being tested |
| **Exception handlers** | **REAL** — `register_exception_handlers(app)` called on test app | Error response shape is a contract |
| **Route handlers** | **REAL** — handlers execute with real logic | Auth flow, permission checks, business logic must run |
| **JWT creation/decoding** | **REAL** — `JWTTokenHandler` with test secret | Token lifecycle is core behavior |
| **Redis** | **fakeredis** — `FakeStrictRedis` patched at `db_config.redis_client` | In-memory compatible, same API, no network needed |
| **DB functions** | **PATCHED at module boundary** — `patch("src.Util.db.function_name")` | DB requires MySQL + stored procedures; cannot run without Docker/testcontainers. Patching at the `src.Util.db` boundary means route handlers call real functions, we just control the return values. This is the infrastructure boundary, not a mock of business logic. |
| **Cache manager** | **PATCHED** — `patch("src.Util.cache_manager.cache_manager")` | Redis-backed, depends on real Redis connection config |
| **Activity logger** | **PATCHED** — `patch("src.Util.activity_logger.*")` | Writes to DB via stored procedures |
| **Audit logger** | **SPY/MOCK** — verify calls without writing to DB | Audit writes to `api_audit_log` table |

### Why DB is patched, not real

The codebase uses **MySQL stored procedures** for ALL database operations. Running real DB tests would require:
1. A MySQL 8.0 instance with the full schema
2. All stored procedures deployed
3. Test data seeding via SQL fixtures
4. Transaction isolation per test

This is a **separate infrastructure investment** (docker-compose, testcontainers, schema migration). The strategy prioritizes **HTTP-level proof** first. DB integration tests with real MySQL are a **future phase** — not part of this change.

### fakeredis is NOT a mock

`fakeredis.FakeStrictRedis` implements the full Redis API in-memory. It is a **test double that behaves identically** to real Redis for all operations used by this codebase (`set`, `get`, `delete`, `ping`, `flushall`). This satisfies the "no mocks for code under test" requirement because the session storage logic interacts with a real Redis-compatible API.

---

## Blockers & Assumptions

### Blockers

| Blocker | Impact | Resolution |
|---------|--------|------------|
| **No MySQL test instance** | Cannot run real DB integration tests | **Out of scope for this change.** DB patches at `src.Util.db` boundary are the accepted approach. Future: add `docker-compose.test.yml` with MySQL 8.0. |
| **`db_config.py` creates `redis_client` at import time** | Importing `src.main` before patching creates live Redis connection | **Already handled** by existing `conftest.py` — `.env.test` loaded before any `src.*` import. Integration conftest must ensure fakeredis patch is applied BEFORE importing app. |
| **`src/main.py` reads `./src/README.md` at import time** | App import fails if working directory is wrong | Test must run from project root or use `chdir` fixture. |

### Assumptions

| Assumption | Risk | Validation |
|------------|------|------------|
| `fakeredis` supports all Redis commands used by `auth.py` (`set`, `get`, `delete`, `setex`) | Low — these are basic commands | Slice 0 infrastructure test validates this |
| Patching `src.Util.db.*` functions covers all route DB calls | Medium — some routes import directly from submodules (e.g., `from src.Util.db.db_user_groups import ...`) | Patches must target the **import location**, not just `src.Util.db`. E.g., patch `src.routes.auth.get_user_groups_for_user` if auth.py imports it directly. |
| `httpx.AsyncClient` with `ASGITransport` correctly exercises middleware | Low — this is the standard FastAPI testing approach | Slice 1 (health/ping) validates the pipeline |
| Exception handlers registered via `register_exception_handlers(app)` work with TestClient | Low — handlers are app-level, not request-level | Slice 10 validates this |

---

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **Patch target mismatch** — routes import DB functions from submodules, not `src.Util.db` | HIGH | Each slice must audit its route file's imports and patch at the correct module path. E.g., if `auth.py` does `from src.Util.db.db_user_groups import get_user_groups_for_user`, patch `src.routes.auth.get_user_groups_for_user`, not `src.Util.db.get_user_groups_for_user`. |
| **Middleware side effects in tests** — `APIAuditMiddleware` tries to write to DB, `RequestValidationMiddleware` sets context vars | MEDIUM | Patch audit logger and activity logger at the integration conftest level. These are infrastructure boundaries, not business logic. |
| **Test coupling via shared fakeredis state** — sessions from one test leaking to another | MEDIUM | `fake_redis.flushall()` in teardown fixture. Each test gets clean Redis state. |
| **Defect fixes break existing behavior** — fixing CORS, stub endpoints, or password exposure may break clients that depend on current (broken) behavior | MEDIUM | All fixes are security/correctness improvements. Document breaking changes. The current behavior is objectively wrong. |
| **Large number of slices** — 16 slices is a lot of work | LOW | Slices marked `[P]` can run in parallel. Slices 1, 3, 10, 11, 12, 14, 15 are independent after Slice 0. |
| **Route shadowing makes tests non-deterministic** — which handler wins for `/users/me/permissions` depends on registration order | MEDIUM | Slice 14 explicitly tests this. The fix removes ambiguity. |

---

## Defect Remediation Plan

Defects discovered during the deep review MUST be fixed as part of this change, not deferred. Each defect is tied to a specific slice:

| # | Defect | Location | Fix Approach | Slice |
|---|--------|----------|-------------|-------|
| 1 | CORS `allow_origins=["*"]` with `allow_credentials=True` | `src/main.py:50-56` | Replace `["*"]` with explicit origin list from env var (e.g., `ALLOWED_ORIGINS` with default `["http://localhost:3000"]`) | 13 |
| 2 | Duplicate route shadowing (`/users/me/permissions`, `/users/me/permissions/check/{name}`) | `global_roles.py:772` vs `permission_assignments.py:441` | Remove duplicates from `global_roles.py`, keep `permission_assignments.py` versions (newer, uses `check_user_has_permission_extended`) | 14 |
| 3 | Stub endpoints (`/projects/{hash}/owner`, `/projects/{hash}/archive`) | `projects.py:795,882` | Return `501 Not Implemented` with proper error response, OR implement real logic. Strategy recommends 501 with clear error message. | 9 |
| 4 | Plaintext temporary password in reset-password response | `users.py:853` | Remove `temporary_password` from response. Return only `expires_at` and `must_change_on_login`. Password should be delivered out-of-band. | 8 |
| 8 | Empty Bearer token accepted by `extract_jwt_token_from_request` | `Seccurity.py:73` | Return `None` or raise error for empty string after `"Bearer "` prefix | 13 |
| 9 | `datetime.utcnow()` deprecation | Multiple files | Replace with `datetime.now(timezone.utc)` | 15 |
| 11 | Pagination `total` is page count, not total count | `projects.py:139` | Use actual total from DB query, not `len(filtered_page)` | 9 |

Defects #5 (no rate limiting), #6 (inconsistent auth patterns), #7 (log_context always None), #10 (silent error swallowing), #12 (pagination total mismatch in users.py) are **documented by tests but NOT fixed** in this change — they require architectural decisions beyond the scope of test coverage.

---

## Next Recommended

1. **Execute Slice 0** — build the integration test infrastructure (`tests/integration/conftest.py`)
2. **Execute Slice 1** — prove the pipeline works with health/ping endpoints
3. **Execute Slices 2-5** — complete the auth flow (the most critical business logic)
4. **Execute Slice 6** — establish permission boundary proofs
5. **Execute Slices 8, 9, 13, 14** — fix the critical defects found during review
6. **Execute remaining slices** — middleware, security, contract tests
7. **Future phase:** Add real MySQL integration tests with docker-compose/testcontainers
