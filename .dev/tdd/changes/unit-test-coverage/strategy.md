# TDD Strategy: unit-test-coverage

## Mode
**Standalone TDD** — No SDD artifacts exist for this change. The exploration artifact (`.dev/tdd/changes/unit-test-coverage/explore.md`) is the sole upstream source of truth.

## Linked Artifacts
- `.dev/tdd/init.yaml` — TDD bootstrap with recommended stack, commands, and proving layers
- `.dev/tdd/changes/unit-test-coverage/explore.md` — Full codebase exploration, seam analysis, and phased coverage plan

## Variant Choice
**Classical TDD (Outside-in from pure functions)** — Start with pure, deterministic functions that have zero external dependencies. These are the fastest RED → GREEN → REFACTOR loops and require no mocking infrastructure. Build outward toward modules that need Redis/DB mocking. This is a **pragmatic coverage** strategy: prioritize security-critical seams and high-risk modules first, then fill in the rest.

## Pre-Implementation: Infrastructure Bootstrap (Slice 0)

Before any test can be written, the test infrastructure must exist. This is a **one-time setup slice** that enables all subsequent slices.

### Slice 0 — Test Infrastructure & `.env.test` Bootstrap

**What to create:**

1. **`requirements-test.txt`** — Test dependencies:
   ```
   pytest>=8.0
   pytest-cov>=5.0
   pytest-asyncio>=0.24
   httpx>=0.27
   fakeredis>=2.26
   freezegun>=1.5
   python-dotenv>=1.0
   ```

2. **`.env.test`** — Test environment placeholders (note: the user wrote `.evn.test` — the correct naming convention is `.env.test`, following the standard `.env.{environment}` pattern used by `python-dotenv` and the broader Python ecosystem):
   ```bash
   # .env.test — Test environment placeholders
   # DO NOT commit real credentials. DO NOT use in production.
   # This file is loaded by conftest.py BEFORE any src.* import.

   DB_MYSQL_PASSWORD=test_mysql_password_placeholder
   DB_REDIS_PASSWORD=test_redis_password_placeholder
   JWT_SECRET_KEY=test_jwt_secret_key_for_testing_only_32chars!!
   DEBUG_MODE=true
   LOG_TOKEN_USER=test_log_token_user
   LOG_TOKEN_REALM=test_log_token_realm
   ```

3. **`tests/__init__.py`** — Package marker.

4. **`tests/conftest.py`** — The critical bootstrap fixture file. Must:
   - Load `.env.test` via `python-dotenv` **before** any `src.*` import
   - Override `os.environ` with test values
   - Provide `mock_redis_client` fixture using `fakeredis.FakeStrictRedis`
   - Provide `mock_env_vars` fixture that patches `os.environ.get` / `os.getenv`
   - Provide `test_jwt_secret` constant for deterministic JWT tests
   - Patch `src.Util.db_config.redis_client` at module level after import

   **Critical import-order constraint**: `conftest.py` MUST set environment variables before any `src.*` module is imported. The `db_config.py` module-level `redis_client = get_redis_client()` on line 44 is the **BLOCKER** — it runs at import time and will fail without valid env vars. The strategy is:
   - Set env vars in `conftest.py` at module level (before any test function)
   - Import `src.Util.db_config` after env vars are set
   - Patch `src.Util.db_config.redis_client` with a `fakeredis` instance

5. **`pytest.ini`** or `pyproject.toml` — Test configuration:
   ```ini
   [pytest]
   testpaths = tests
   python_files = test_*.py
   python_classes = Test*
   python_functions = test_*
   asyncio_mode = auto
   addopts = -v --tb=short
   ```

**Proof layer:** Infrastructure (no tests yet, just tooling that passes `pytest --collect-only`)

**Gate:** `pytest --collect-only` succeeds with zero errors

---

## Slice Plan

### Slice 1 — UUID Generator (Pure Functions) **[P]**

**Proof layer:** Unit — pure functions, zero external deps, zero env vars needed
**Modules:** `src/Util/uuid_generator.py`
**Test file:** `tests/unit/test_uuid_generator.py`

**What to test:**
- All 20+ `generate_*` functions return strings with correct prefix
- Returned UUID portion is valid UUID format (regex or `uuid.UUID()` parse)
- `generate_hash()` produces uppercase prefix + uppercase hex without hyphens
- `generate_user_hash()` delegates to `generate_hash("usr")`
- Each call returns a unique value (no collisions in 1000 iterations)
- `generate_project_group_member_id()` and similar strip hyphens

**Coverage goal:** 100% (all functions, all branches)

**Why first:** Zero dependencies. Fastest RED → GREEN loop. Builds confidence in the test infrastructure.

---

### Slice 2 — Password Generator (Pure Logic) **[P]**

**Proof layer:** Unit — `secrets` module is stdlib, no external deps
**Modules:** `src/Util/password_generator.py`
**Test file:** `tests/unit/test_password_generator.py`

**What to test:**
- `generate_temporary_password(8)` returns length 8
- `generate_temporary_password(32)` returns length 32
- `generate_temporary_password(5)` clamps to 8
- `generate_temporary_password(50)` clamps to 32
- Generated password contains at least one uppercase, one lowercase, one digit, one special char
- `generate_reset_token()` returns URL-safe string
- `validate_password_strength("")` → score 0, strength "weak", is_valid False
- `validate_password_strength("Ab1!")` → score 60, strength "medium", is_valid True
- `validate_password_strength("Ab1!xxxx")` → score 70 (length bonus for >=12 not yet)
- `validate_password_strength("Ab1!xxxxxxxx")` → score 80, strength "strong"
- `validate_password_strength("Ab1!xxxxxxxxxxxx")` → score 90, strength "strong"
- `validate_password_strength("Ab1!xxxxxxxxxxxxxxx")` → score 100 (capped), strength "strong"
- `create_password_reset_data()` returns dict with expected keys

**Coverage goal:** 100% (all methods, boundary conditions)

---

### Slice 3 — Password Security (Argon2id + Legacy Migration)

**Proof layer:** Unit — `argon2-cffi` is a dependency but needs no external service
**Modules:** `src/Util/password_security.py`
**Test file:** `tests/unit/test_password_security.py`

**What to test:**
- `hash_password("test")` returns Argon2 hash string (starts with `$argon2`)
- `verify_password("test", hash_password("test"))` → True
- `verify_password("wrong", hash_password("test"))` → False
- `_is_legacy_hash("5e884898da28047151d0e56f8dc6292773603d0d6aabbdd62a11ef721d1542d8")` → True
- `_is_legacy_hash("$argon2id$v=19$...")` → False
- `_is_legacy_hash("not_a_hash")` → False
- `needs_rehash(legacy_sha256_hash)` → True
- `needs_rehash(argon2_hash)` → False (assuming current params)
- `migrate_legacy_hash("correct_password", legacy_hash)` → new Argon2 hash
- `migrate_legacy_hash("wrong_password", legacy_hash)` → None
- `verify_password()` handles legacy SHA256 round-trip

**Coverage goal:** 90%+ (Argon2 is slow — skip extreme performance edge cases)

**Risk:** Argon2 hashing is computationally expensive. Tests will be slower. Use a reduced parameter set in tests if possible (but the module hardcodes params, so this requires mocking the `PasswordHasher` constructor or accepting ~1-2s per test).

---

### Slice 4 — Error Handler Core (UUID Masking, Sanitization, Enums) **[P]**

**Proof layer:** Unit — pure logic, but `DEBUG_MODE` is read from env at import time
**Modules:** `src/Util/error_handler.py`
**Test file:** `tests/unit/test_error_handler.py`

**What to test:**
- `mask_uuid("usr-550e8400-e29b-41d4-a716-446655440000")` → `"usr-[550e]...[0000]"`
- `mask_uuid("550e8400-e29b-41d4-a716-446655440000")` → `"[550e]...[0000]"`
- `mask_uuid("")` → `"[invalid]"`
- `mask_uuid(None)` → `"[invalid]"`
- `mask_uuid("abc")` → `"[abc...]"` (short UUID edge case)
- `mask_multiple_uuids("User usr-abc... and proj-def...")` → both masked
- `sanitize_error_message()` masks UUIDs and `id=`/`user_id=` patterns
- `ErrorCode` and `ErrorCategory` enums have expected values
- `AppException.to_dict()` in DEBUG_MODE includes `details` and `trace`
- `AppException.to_dict()` without DEBUG_MODE excludes `details` and `trace`
- `create_validation_error()`, `create_not_found_error()`, `create_access_denied_error()` return correct exception types with correct codes
- `build_error_response()` handles AppException vs generic Exception
- `get_http_exception_details()` returns correct tuple
- `_extract_function_context()` parses `"create_user(username='john')"` correctly
- `_extract_function_context()` returns None for malformed strings
- `_identify_constraint_type()` for MySQL error codes 1062, 1451, 1452, 1048
- `_get_db_error_severity()` for critical/high/medium/low codes
- `AuthenticationError`, `AuthorizationError`, `ValidationError`, `NotFoundError`, `ConflictError`, `DatabaseError`, `InternalError` — each sets correct status_code and category

**Coverage goal:** 95%+ (all masking paths, all exception classes, DEBUG_MODE on/off)

**Important:** Tests for DEBUG_MODE behavior must toggle `os.environ["DEBUG_MODE"]` and reload or patch the module-level `DEBUG_MODE` variable. Use `importlib.reload()` or direct patching of the module-level constant.

---

### Slice 5 — DB Error Wrapper (Parsing & Validation) **[P]**

**Proof layer:** Unit — pure parsing logic + decorator behavior (mock pymysql/Redis)
**Modules:** `src/Util/db_error_wrapper.py`
**Test file:** `tests/unit/test_db_error_wrapper.py`

**What to test:**
- `parse_duplicate_entry_error("(1062, \"Duplicate entry 'basic' for key 'roles.uk_role_name'\")")` → extracts value="basic", table="roles", key="uk_role_name", field="role_name"
- `parse_duplicate_entry_error()` with various MySQL error formats
- `parse_duplicate_entry_error()` with unrecognized format → defaults
- `validate_uuid_format("usr-550e8400-e29b-41d4-a716-446655440000")` → no exception
- `validate_uuid_format("invalid")` → raises ValidationError
- `validate_uuid_format("")` → raises ValidationError
- `handle_db_operation()` success path returns result
- `handle_db_operation()` with `pymysql.IntegrityError` → raises ConflictError
- `handle_db_operation()` with `pymysql.OperationalError` → raises DatabaseError
- `handle_db_operation()` with `RedisError` → raises InternalError
- `handle_db_operation()` with `default_return` → returns default instead of raising
- `db_operation` decorator wraps function correctly
- `safe_db_operation()` returns None on error

**Coverage goal:** 90%+ (all error paths, all parsing branches; skip actual DB execution paths)

**Mocking strategy:** Mock `pymysql.IntegrityError`, `pymysql.OperationalError`, `pymysql.ProgrammingError`, and `redis.exceptions.RedisError` — these are exception classes, not instances, so we can instantiate them directly in tests.

---

### Slice 6 — Log Context Models (Pydantic Validation) **[P]**

**Proof layer:** Unit — Pydantic models, no external deps
**Modules:** `src/Util/log_context_models.py`
**Test file:** `tests/unit/test_log_context_models.py`

**What to test:**
- `LogContext()` creates with all defaults
- `LogContext(user_id="usr-123")` sets field correctly
- `LogContext(timestamp=...)` accepts explicit datetime
- `UnauthenticatedLogContext()` creates with defaults
- `OperationMetadata(operation_name="test")` requires operation_name
- `OperationMetadata()` without operation_name → validation error

**Coverage goal:** 100%

---

### Slice 7 — API Audit Logger (Filtering & Tagging Logic)

**Proof layer:** Unit — static methods with pure logic (mock DB connection)
**Modules:** `src/Util/api_audit_logger.py`
**Test file:** `tests/unit/test_api_audit_logger.py`

**What to test:**
- `should_log_request("/ping", "GET")` → False (excluded path)
- `should_log_request("/health", "GET")` → False
- `should_log_request("/docs", "GET")` → False
- `should_log_request("/auth/login", "POST")` → True
- `should_log_request("/auth/login", "OPTIONS")` → False (CORS preflight)
- `should_log_request("/auth/login?debug=true", "GET")` → False (has query string? — check actual logic)
- `filter_sensitive_data({"password": "secret", "username": "john"})` → password removed
- `filter_sensitive_data()` with nested dicts → recursively filters
- `filter_sensitive_data()` with lists → filters items
- `filter_headers()` removes Authorization, Cookie, etc.
- `generate_tags("/auth/login", "POST")` → appropriate tags
- `extract_resource_info("/users/usr-abc123")` → extracts resource type and ID
- `is_security_event()` detection logic
- `should_log_request()` for all excluded paths

**Coverage goal:** 95%+ (all filtering, tagging, and path logic; skip actual DB stored procedure calls)

**Mocking strategy:** The `APIAuditLogger` class imports `get_connection` from `db_config`, but the methods we're testing (`should_log_request`, `filter_sensitive_data`, `filter_headers`, `generate_tags`, `extract_resource_info`, `is_security_event`) are static and don't call the DB. Only `log_api_request` and similar methods hit the DB — those are deferred to Layer 2.

---

### Slice 8 — JWT Security (Token Lifecycle)

**Proof layer:** Unit — requires `JWT_SECRET_KEY` env var set before import
**Modules:** `src/Util/JWT_Security.py`
**Test file:** `tests/unit/test_jwt_security.py`

**What to test:**
- `JWTTokenHandler.create_access_token(1, "usr-abc", "proj-xyz")` → valid JWT string
- `JWTTokenHandler.decode_access_token(token)` → payload with session_id, user_hash, collection, type
- Round-trip: create → decode → verify all fields match
- `decode_access_token(expired_token)` → raises HTTPException(401, "Token expired")
- `decode_access_token(tampered_token)` → raises HTTPException(401, "Invalid token")
- `decode_access_token(wrong_type_token)` → raises HTTPException(401, "Invalid token type")
- `extract_session_id(token)` → correct session_id
- `extract_user_hash(token)` → correct user_hash
- `extract_collection(token)` → correct collection
- `validate_token_structure(valid_token)` → True
- `validate_token_structure("not_a_token")` → False
- `validate_token_structure(malformed_payload)` → False
- `jwt_encode()` compat function returns `(token, None)`
- `jwt_decode(valid_token)` → `([session_id], None)`
- `jwt_decode(invalid_token)` → `([0], None)`
- Token with custom `expires_delta` → correct expiration time (use `freezegun`)

**Coverage goal:** 90%+ (all encode/decode/extract paths, all error cases)

**Critical:** `JWT_SECRET_KEY` MUST be set in `conftest.py` before `JWT_Security` is imported. The module-level `os.getenv("JWT_SECRET_KEY", secrets.token_urlsafe(64))` on line 11 means the key is captured at import time. Tests must use `os.environ["JWT_SECRET_KEY"] = "test_key_..."` before any `src.Util.JWT_Security` import.

---

### Slice 9 — Seccurity Helpers (Token Extraction & JSON Responses)

**Proof layer:** Unit — `extract_jwt_token_from_request` and `returnJson_*` helpers are pure
**Modules:** `src/Util/Seccurity.py`
**Test file:** `tests/unit/test_seccurity.py`

**What to test:**
- `extract_jwt_token_from_request(request_with_bearer_header)` → token string
- `extract_jwt_token_from_request(request_with_cookie)` → token string
- `extract_jwt_token_from_request(request_without_token)` → None
- `HTTPBearerOrCookie` with Authorization header → returns credentials
- `HTTPBearerOrCookie` with cookie → returns credentials
- `HTTPBearerOrCookie` with neither → raises HTTPException(401)
- `HTTPBearerOrCookie(auto_error=False)` with neither → returns None
- `returnJson_401()`, `returnJson_403()`, `returnJson_404()`, `returnJson_413()`, `returnJson_422()`, `returnJson_500()`, `returnJson_200()` — each returns correct JSONResponse with correct status code and default message
- All `returnJson_*` functions accept custom `data` parameter

**Coverage goal:** 80%+ (token extraction, all JSON helpers; skip `middleware_user_token_validation` — that requires mocking `validate_session` from `db_enhanced`, which is Layer 2)

**Risk:** `Seccurity.py` imports from `src.Util.db.db_enhanced` (line 9) and `src.Util.db_config` (line 10) at module level. This means importing `Seccurity` in tests will trigger the `db_config` Redis connection. The `conftest.py` must patch `db_config.redis_client` before `Seccurity` is imported.

---

### Slice 10 — System Metrics (Health Score Calculation) **[P]**

**Proof layer:** Unit — `calculate_health_score` is pure arithmetic
**Modules:** `src/Util/system_metrics.py`
**Test file:** `tests/unit/test_system_metrics.py`

**What to test:**
- `calculate_health_score()` with all healthy components → high score
- `calculate_health_score()` with DB down → reduced score
- `calculate_health_score()` with Redis down → reduced score
- `calculate_health_score()` with high CPU → reduced score
- Boundary conditions: all zeros, all max values

**Coverage goal:** 60%+ (focus on `calculate_health_score`; skip `get_system_health` which calls psutil/DB/Redis)

---

### Slice 11 — Pydantic Models (Key Validation Paths)

**Proof layer:** Unit — Pydantic v2 models
**Modules:** `src/Util/Models.py`
**Test file:** `tests/unit/test_models.py`

**What to test:**
- Key request models (`UserLogin`, `LoginRequest`, `RegisterRequest`, etc.) validate correctly with valid data
- Key request models reject invalid data (missing required fields, wrong types)
- Optional fields work correctly (None vs missing)
- Response models serialize correctly
- Default values are applied

**Coverage goal:** 80%+ (key models, not every single response model — there are 80+)

---

## Parallel-Safe Slices

The following slices are marked **[P]** because they have **zero shared state, zero module-level side effects, and zero interdependencies**:

| Slice | Module | Why Parallel-Safe |
|-------|--------|-------------------|
| 1 | `uuid_generator.py` | Pure stdlib functions, no imports from `src` |
| 2 | `password_generator.py` | Pure stdlib (`secrets`, `string`), no `src` imports |
| 4 | `error_handler.py` (core) | Only imports stdlib + `logging`; `DEBUG_MODE` is env-based but testable with reload |
| 5 | `db_error_wrapper.py` (parsing) | `parse_duplicate_entry_error` and `validate_uuid_format` are pure; exception mocking is isolated |
| 6 | `log_context_models.py` | Pure Pydantic models, no `src` imports |
| 10 | `system_metrics.py` (health score) | `calculate_health_score` is pure arithmetic |

**Slices that are NOT parallel-safe:**
- Slice 3 (password_security): Argon2 is slow; running multiple instances in parallel could cause resource contention
- Slice 7 (api_audit_logger): Shares `db_config` import path with other slices
- Slice 8 (JWT_Security): Requires exclusive control of `JWT_SECRET_KEY` env var
- Slice 9 (Seccurity): Imports `db_config` and `db_enhanced` at module level
- Slice 11 (Models): Large file, may have import-time side effects from Pydantic model registration

---

## Gates

| Gate | Required? | Why |
|------|-----------|-----|
| `pytest --collect-only` | **Yes** | Verifies test infrastructure is correctly set up before any test runs |
| `pytest tests/unit/ -v` (all pass) | **Yes** | All unit tests must pass before moving to Layer 2 (service tests) |
| Coverage report generated | **Yes** | `pytest --cov=src/Util --cov-report=term-missing` must run successfully |
| No import-time Redis/DB failures | **Yes** | Tests must not attempt real connections — all external deps mocked |
| `.env.test` exists and is loaded | **Yes** | Tests must not read from `.env` (live credentials) |
| `.env.test` NOT committed to git | **Yes** | Add to `.gitignore` — only `.env.test.example` should be committed |
| DEBUG_MODE = true in test env | **Yes** | Ensures `AppException.to_dict()` includes full details for testing |

---

## Commands / Suites

| Scope | Command |
|-------|---------|
| Install test deps | `pip install -r requirements-test.txt` |
| Run all unit tests | `pytest tests/unit/ -v` |
| Run single slice | `pytest tests/unit/test_uuid_generator.py -v` |
| Run with coverage | `pytest tests/unit/ --cov=src/Util --cov-report=term-missing --cov-report=html:htmlcov` |
| Run last failed only | `pytest --lf -v` |
| Stop on first failure | `pytest -x -v` |
| Watch mode (rerun on change) | `pytest --watch` (requires pytest-watch) |
| Collect only (verify setup) | `pytest --collect-only` |
| Coverage fail threshold | `pytest --cov=src/Util --cov-fail-under=70` |

---

## Fixture & Mocking Strategy

### Environment Loading (conftest.py)

```python
# tests/conftest.py — module-level setup (runs before any test)
import os
from pathlib import Path
from dotenv import load_dotenv

# 1. Load .env.test BEFORE any src.* import
ENV_TEST_PATH = Path(__file__).parent.parent / ".env.test"
load_dotenv(ENV_TEST_PATH, override=True)

# 2. Ensure critical env vars are set
os.environ.setdefault("JWT_SECRET_KEY", "test_jwt_secret_key_for_testing_only_32chars!!")
os.environ.setdefault("DEBUG_MODE", "true")

# 3. NOW import src modules (env vars are set)
import pytest
import fakeredis
from unittest.mock import patch, MagicMock
```

### Redis Mocking

```python
@pytest.fixture
def mock_redis():
    """Provide a fakeredis instance that replaces the global redis_client."""
    fake = fakeredis.FakeStrictRedis()
    with patch("src.Util.db_config.redis_client", fake):
        yield fake
    fake.flushall()
```

### DB Connection Mocking

```python
@pytest.fixture
def mock_db_connection():
    """Mock get_connection to return a fake MySQL connection."""
    mock_conn = MagicMock()
    mock_cursor = MagicMock()
    mock_conn.cursor.return_value.__enter__ = MagicMock(return_value=mock_cursor)
    mock_conn.cursor.return_value.__exit__ = MagicMock(return_value=False)
    mock_conn.close = MagicMock()
    with patch("src.Util.db_config.get_connection", return_value=mock_conn):
        yield mock_conn
```

### JWT Secret Control

```python
@pytest.fixture
def jwt_secret():
    """Return the test JWT secret key."""
    return os.environ["JWT_SECRET_KEY"]
```

### Time Freezing (for JWT expiration tests)

```python
from freezegun import freeze_time

@pytest.fixture
def frozen_time():
    """Freeze time for deterministic JWT tests."""
    with freeze_time("2026-04-15 12:00:00") as frozen:
        yield frozen
```

### Import-Order Constraint Summary

```
conftest.py module-level:
  1. load_dotenv(".env.test", override=True)
  2. os.environ["JWT_SECRET_KEY"] = "..."
  3. os.environ["DEBUG_MODE"] = "true"
  4. os.environ["DB_MYSQL_PASSWORD"] = "..."
  5. os.environ["DB_REDIS_PASSWORD"] = "..."
  6. import pytest, fakeredis, etc.
  7. import src.Util.db_config  # NOW safe — env vars are set
  8. Patch db_config.redis_client with fakeredis
  9. Define fixtures
```

**Any test file that imports from `src.*` MUST do so AFTER conftest.py has run.** Since pytest loads `conftest.py` before test modules, this is guaranteed as long as imports happen inside test functions or at module level of test files (which are loaded after conftest.py).

---

## Coverage Goals by Area (Not Vanity Percentages)

| Area | Target | Rationale |
|------|--------|-----------|
| `uuid_generator.py` | 100% | Pure functions — every branch must be covered |
| `password_generator.py` | 100% | Pure logic — boundary conditions are critical |
| `password_security.py` | 90%+ | Argon2 is slow; skip extreme edge cases |
| `error_handler.py` | 95%+ | Security-critical — masking, DEBUG_MODE gating, all exception classes |
| `db_error_wrapper.py` | 90%+ | All parsing paths, all error mapping branches |
| `api_audit_logger.py` | 95%+ | All filtering, tagging, path logic (skip DB calls) |
| `log_context_models.py` | 100% | Simple Pydantic models — trivial to cover fully |
| `Models.py` | 80%+ | 80+ models — cover key request/response models, not every response variant |
| `JWT_Security.py` | 90%+ | Security-critical — all encode/decode/extract paths, all error cases |
| `Seccurity.py` | 80%+ | Token extraction, JSON helpers; defer full validation flow to Layer 2 |
| `system_metrics.py` | 60%+ | Focus on `calculate_health_score`; skip psutil/DB/Redis integration |
| **Overall (Layer 1)** | **~70-75%** | Realistic target for pure unit tests across 11 modules |

---

## Trace Back to Explore Artifact

| Slice | Explored Seam (explore.md Section) | Risk Level |
|-------|-----------------------------------|------------|
| 1 | Section 3.4: `uuid_generator.py` — pure functions | LOW |
| 2 | Section 3.3: `password_generator.py` — scoring logic | MEDIUM |
| 3 | Section 3.1: `password_security.py` — Argon2id + SHA256 migration | CRITICAL |
| 4 | Section 3.2: `error_handler.py` — UUID masking, DEBUG_MODE gate | HIGH |
| 5 | Section 3.2: `db_error_wrapper.py` — MySQL error parsing | MEDIUM |
| 6 | Section 3.4: `log_context_models.py` — simple Pydantic models | LOW |
| 7 | Section 3.3: `api_audit_logger.py` — sensitive data filtering | MEDIUM |
| 8 | Section 3.1: `JWT_Security.py` — token lifecycle | CRITICAL |
| 9 | Section 3.1: `Seccurity.py` — token extraction, JSON helpers | CRITICAL |
| 10 | Section 3.3: `system_metrics.py` — health score arithmetic | LOW |
| 11 | Section 3.4: `Models.py` — Pydantic validation | LOW |

---

## Risks & Mitigation

| Risk | Severity | Mitigation |
|------|----------|------------|
| **`db_config.py` creates `redis_client` at import time (line 44)** | **BLOCKER** | `conftest.py` MUST set `DB_REDIS_PASSWORD` env var before importing `db_config`. Then patch `db_config.redis_client` with `fakeredis.FakeStrictRedis()`. If this fails, tests cannot import ANY `src.*` module. |
| **`JWT_SECRET_KEY` auto-generates at import if not set** | HIGH | Set `os.environ["JWT_SECRET_KEY"]` in `conftest.py` before importing `JWT_Security`. Use a fixed test key, not a random one, so tokens are deterministic across test runs. |
| **`Seccurity.py` imports `db_enhanced` at module level** | HIGH | This creates a transitive import chain: `Seccurity` → `db_enhanced` → `db_config` → Redis connection. Must patch `db_config.redis_client` before `Seccurity` is imported. Consider deferring `Seccurity` tests to after the mocking infrastructure is solid. |
| **`DEBUG_MODE` is read at module level in `error_handler.py`** | MEDIUM | Tests that verify DEBUG_MODE on/off behavior must either: (a) use `importlib.reload(src.Util.error_handler)` after toggling the env var, or (b) directly patch `src.Util.error_handler.DEBUG_MODE` in the test. Option (b) is simpler and faster. |
| **No dependency injection anywhere** | HIGH | All DB/Redis-dependent code must be tested via `unittest.mock.patch`. This is fragile — if function signatures change, patches break. Document all patch targets in `conftest.py`. |
| **Bare `except:` clauses in `Seccurity.py`, `JWT_Security.py`** | MEDIUM | Tests should verify that error paths still raise/handle correctly. The bare excepts swallow errors silently, making it hard to verify behavior. Use `capsys` to capture `print()` output where applicable. |
| **`print()` statements in production code** | LOW | Use `capsys` fixture in pytest to capture stdout. Or refactor to `logging` in a future phase. |
| **Argon2 hashing is slow (~1s per hash)** | MEDIUM | Slice 3 tests will be slower. Accept this for now — security-critical code deserves thorough testing. Consider reducing Argon2 params in a test-specific subclass if tests become too slow. |
| **Module name `Seccurity.py` (double c) violates PEP 8** | LOW | Affects import paths in tests: `from src.Util.Seccurity import ...`. Just be consistent. |
| **`pytest-asyncio` mode conflicts** | LOW | Set `asyncio_mode = auto` in `pytest.ini` to avoid deprecation warnings. |

### Rollback / Adjustment Guidance

**If import-time side effects block ALL tests:**
1. Create a minimal `tests/conftest.py` that ONLY sets env vars and patches `db_config.redis_client`
2. Run `pytest --collect-only` to verify no import errors
3. If still failing, create a `tests/test_import_smoke.py` that imports each `src.*` module one at a time to identify the exact blocker
4. As a last resort, use `pytest.importorskip()` or `pytest.skip()` for modules that cannot be imported without live connections

**If a slice is too large for one RED → GREEN loop:**
- Split it into sub-slices. For example, Slice 4 (error_handler) can be split into:
  - 4a: `mask_uuid` and `mask_multiple_uuids`
  - 4b: `sanitize_error_message`
  - 4c: `AppException` class (without DEBUG_MODE)
  - 4d: `AppException.to_dict()` with DEBUG_MODE on/off
  - 4e: Specific exception classes (AuthenticationError, etc.)
  - 4f: Helper functions (`create_validation_error`, etc.)

**If coverage is too slow due to Argon2:**
- Mark Argon2 tests with `@pytest.mark.slow` and run them separately
- Or reduce the number of test cases for password hashing (focus on correctness, not exhaustive edge cases)

---

## Next Recommended

After all Layer 1 slices (1-11) are complete and passing:

1. **Layer 2 — Service Tests with Mocking**: `cache_manager.py`, `activity_logger.py`, `decorators.py` (explore.md Section 5, Layer 2)
2. **Layer 3 — Middleware Tests**: `middleware/request_validation.py`, `middleware/auth_context.py`, `middleware/api_audit.py`, `middleware/error_handler.py`, `middleware/authentication.py`
3. **Layer 4 — Route Tests**: `routes/auth.py` (login, register, validate flows)
4. **e2e tests** — explicitly deferred per user request
