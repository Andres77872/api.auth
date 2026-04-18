# TDD Apply Progress: api-deep-review-coverage (REMEDIATION PASS)

**Workflow**: tdd
**Change**: api-deep-review-coverage
**Mode**: Remediation — fixing verification failures from prior pass

## Authoritative Artifacts

- `strategy.md` — TDD strategy with 16 slices
- `explore.md` — Exploration and defect mapping
- `verify-report.md` — Verification report (FAILED — 4 issues identified)

## Verification Failures Remediated

### Issue 1: `client_no_auth_context` workaround still used in slices 4-5 ✅ FIXED

**Root cause**: The `app_no_auth_context` and `client_no_auth_context` fixtures in
`tests/integration/conftest.py` were still defined and actively used by 15 tests in
slices 4 and 5, bypassing the real middleware stack.

**Fix applied**:
1. Rewrote `tests/integration/test_slice4_auth_validate_logout_refresh.py` — all 7 tests
   now use the REAL `client` fixture with full middleware (CORS, RequestValidation,
   APIAudit, AuthContext). No workaround app.
2. Rewrote `tests/integration/test_slice5_auth_switch_availability.py` — all 8 tests
   now use the REAL `client` fixture with full middleware.
3. Removed `app_no_auth_context` and `client_no_auth_context` fixtures from
   `tests/integration/conftest.py`.

**Evidence**: `pytest tests/integration/test_slice4_auth_validate_logout_refresh.py tests/integration/test_slice5_auth_switch_availability.py -v` → **15 passed**.

### Issue 2: API audit coverage was utility-only, not request-level ✅ FIXED

**Root cause**: `tests/integration/test_slice12_api_audit.py` only tested `APIAuditLogger`
utility methods, not the middleware's behavior during real HTTP requests.

**Fix applied**:
1. Added 3 request-level tests to `test_slice12_api_audit.py`:
   - `test_audit_middleware_logs_login_request` — proves `log_request` is called with
     correct parameters during a real POST /auth/login request through the full middleware stack.
   - `test_audit_middleware_logs_protected_get_request` — proves `log_request` is called
     for GET /users/profile (even when unauthenticated → 401).
   - `test_audit_middleware_extracts_user_context` — proves the middleware extracts
     user_id, session_id, and client_ip from request.state (set by AuthContextMiddleware).
2. Added `test_oversized_post_rejected` to `test_slice11_request_validation.py` — proves
   POST > 8MB → 413 through RequestValidationMiddleware.

**Evidence**: `pytest tests/integration/test_slice11_request_validation.py tests/integration/test_slice12_api_audit.py -v` → **19 passed**.

### Issue 3: Deprecation gate fails ✅ FIXED

**Root cause**: Two sources of DeprecationWarning:
1. `src/Util/log_context_models.py` — Pydantic V2-deprecated `class Config` on 3 models.
2. `tests/unit/test_models.py` — `datetime.utcnow()` in 5 test methods.

**Fix applied**:
1. Replaced `class Config: arbitrary_types_allowed = True` with
   `model_config = ConfigDict(arbitrary_types_allowed=True)` on all 3 models
   (`LogContext`, `UnauthenticatedLogContext`, `OperationMetadata`).
2. Replaced all `datetime.utcnow()` with `datetime.now(timezone.utc)` in
   `tests/unit/test_models.py` (5 occurrences in TestUserEntity and TestProjectEntity).

**Evidence**: `pytest -W error::DeprecationWarning -q` → **496 passed, 0 failed**.

### Issue 4: E2E labeling overstated ✅ FIXED

**Root cause**: The `tests/e2e/` suite was labeled "E2E" but uses patched DB, fakeredis,
and mocked audit logger — making it high-fidelity ASGI integration, not full infra E2E.

**Fix applied**:
1. Updated `tests/e2e/conftest.py` docstring to explicitly state these are
   "High-Fidelity ASGI Integration Tests" and document what is/isn't truly E2E.
2. Updated `tests/e2e/test_api_lifecycle.py` docstring with the same clarification.

## Completed Work (Remediation)

| Remediation | Status | Tests |
|-------------|--------|-------|
| Remove `client_no_auth_context` from slices 4-5 | ✅ | 15 tests pass with real middleware |
| Add request-level audit middleware proof | ✅ | 3 new request-level tests |
| Add POST > 8MB → 413 proof | ✅ | 1 new test |
| Fix Pydantic `class Config` deprecation | ✅ | 0 deprecation warnings |
| Fix `datetime.utcnow()` in tests | ✅ | 0 deprecation warnings |
| Honest E2E labeling | ✅ | Docstrings updated |

## Files Changed

| File | Action | What Was Done |
|------|--------|---------------|
| `src/Util/log_context_models.py` | Modified | Replaced `class Config` with `model_config = ConfigDict(...)` on 3 models |
| `tests/unit/test_models.py` | Modified | Replaced `datetime.utcnow()` → `datetime.now(timezone.utc)` (5 occurrences) |
| `tests/integration/conftest.py` | Modified | Removed `app_no_auth_context` and `client_no_auth_context` fixtures |
| `tests/integration/test_slice4_auth_validate_logout_refresh.py` | Rewritten | All 7 tests use REAL `client` with full middleware stack |
| `tests/integration/test_slice5_auth_switch_availability.py` | Rewritten | All 8 tests use REAL `client` with full middleware stack |
| `tests/integration/test_slice11_request_validation.py` | Modified | Added `test_oversized_post_rejected` (POST > 8MB → 413) |
| `tests/integration/test_slice12_api_audit.py` | Rewritten | Added 3 request-level audit middleware proof tests |
| `tests/e2e/conftest.py` | Modified | Updated docstring to "High-Fidelity ASGI Integration" |
| `tests/e2e/test_api_lifecycle.py` | Modified | Updated docstring to "High-Fidelity ASGI Integration" |

## Test Evidence

| Gate | Command | Result |
|------|---------|--------|
| Full suite + deprecation gate | `pytest tests/ -W error::DeprecationWarning -q` | ✅ **496 passed** |
| Slice 4 (real middleware) | `pytest tests/integration/test_slice4_auth_validate_logout_refresh.py -v` | ✅ 7 passed |
| Slice 5 (real middleware) | `pytest tests/integration/test_slice5_auth_switch_availability.py -v` | ✅ 8 passed |
| Slice 11 (validation) | `pytest tests/integration/test_slice11_request_validation.py -v` | ✅ 4 passed |
| Slice 12 (audit) | `pytest tests/integration/test_slice12_api_audit.py -v` | ✅ 15 passed |
| No workaround fixtures | `grep -r "client_no_auth_context" tests/` | ✅ 0 results |
| No deprecated Config | `grep -r "class Config" src/Util/log_context_models.py` | ✅ 0 results |
| No utcnow in tests | `grep -r "utcnow" tests/unit/test_models.py` | ✅ 0 results |

## Deviations

- **Missing User-Agent → 422**: Cannot be tested through httpx because httpx always sends
  a default User-Agent header. The middleware code path is verified by code review of
  `src/middleware/request_validation.py:55`. Documented in test file docstring.
- **Audit excluded-path request-level test**: Cannot test excluded-path filtering through
  the middleware because patching `APIAuditLogger` replaces the class reference that
  `should_log_request` internally uses to access `EXCLUDED_PATHS`. The excluded-path
  logic is proven at the unit level (`test_should_log_request_excludes_health_paths`).

## Status

**READY FOR VERIFY** — All 4 verification failures from the prior pass have been remediated:
1. ✅ `client_no_auth_context` workaround fully eliminated
2. ✅ Request-level audit middleware proof added
3. ✅ Deprecation gate passes (`pytest -W error::DeprecationWarning`)
4. ✅ E2E labeling corrected to "high-fidelity ASGI integration"
