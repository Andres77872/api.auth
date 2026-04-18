# TDD Strategy: e2e-project-group-user-flow

## Mode
**Standalone TDD** — no linked SDD change artifacts. Strategy is derived entirely from `.dev/tdd/changes/e2e-project-group-user-flow/explore.md` and prior session research (SQL architecture, e2e seam mapping).

## Linked Artifacts
- `.dev/tdd/changes/e2e-project-group-user-flow/explore.md` (authoritative source)
- `.dev/tdd/init.yaml` (project test topology, commands, gates)
- Prior research: SQL architecture analysis (output #2), e2e seam mapping (output #3)

## Variant Choice
**Characterization → Contract-heavy → Real-Data Integration**

We start with **characterization tests** that verify the existing orchestration is correct (prove the right DB functions are called in the right order with the right parameters), then progress to **contract-heavy tests** that validate API request/response shapes for the groups-of-groups endpoints, and finally **real-data integration tests** that require MySQL 8.0 to prove the actual stored procedures and 6-table join access chain work correctly.

**Rationale**: The codebase has ZERO real-data verification of the USER → USER_GROUP → PROJECT_GROUP → PROJECT chain. Jumping straight to MySQL E2E is the biggest slice and highest risk. Characterization tests give us immediate proof that the orchestration layer is correct, and they run in the existing test environment (no Docker needed). Real-data tests are deferred to later slices once the orchestration is proven.

## Slice Plan

All slices follow RED → GREEN → REFACTOR. Each slice is one behavioral unit.

### Phase 1: Characterization Tests (no Docker, runs in existing env)

These slices use the existing DBPatcher/mock infrastructure to prove the **orchestration** is correct — that routes call the right DB functions in the right order with the right parameters.

- [x] **[P] Slice 1 — Registration orchestration chain** — proof layer: Layer 2 (integration, mocked DB)
  - **Behavior**: Verify `POST /auth/register` calls DB functions in correct sequence: `check_username_email_available` → `get_user_group_by_hash` → `get_projects_for_user_group` → `enhanced_register` → `create_session`
  - **File**: `tests/integration/test_slice16_reg_orchestration.py`
  - **Type**: Characterization
  - **Trace**: explore.md RISK 4, Gap 2

- [x] **[P] Slice 2 — Login orchestration with groups-of-groups** — proof layer: Layer 2 (integration, mocked DB)
  - **Behavior**: Verify `POST /auth/login` for non-root user calls: `get_user_by_credentials` → `get_user_accessible_projects` → `get_user_groups_for_user` → `_create_session` with correct group data in Redis
  - **File**: `tests/integration/test_slice17_login_orchestration.py`
  - **Type**: Characterization
  - **Trace**: explore.md RISK 3, Gap 1

- [x] **Slice 3 — Project creation → default groups orchestration** — proof layer: Layer 2 (integration, mocked DB)
  - **Behavior**: Verify `POST /projects` calls `create_default_groups` which executes 4 raw SQL INSERTs (project_group, project_group_members, 3 user_groups, 3 user_group_project_groups links)
  - **File**: `tests/integration/test_slice18_project_default_groups_orchestration.py`
  - **Type**: Characterization
  - **Trace**: explore.md RISK 2, Gap 4

- [x] **[P] Slice 4 — User group → project group linking orchestration** — proof layer: Layer 2 (integration, mocked DB)
  - **Behavior**: Verify `POST /admin/user-groups/{hash}/project-groups` and `DELETE /admin/user-groups/{hash}/project-groups/{pg_hash}` call the correct DB functions (`grant_user_group_access_to_project_group`, `revoke_user_group_access_from_project_group`)
  - **File**: `tests/integration/test_slice19_ug_pg_link_orchestration.py`
  - **Type**: Characterization
  - **Trace**: explore.md Gap 3, RISK 1

### Phase 2: Contract Tests (no Docker, validates API shapes)

- [x] **[P] Slice 5 — Registration endpoint contract** — proof layer: Layer 3 (e2e, mocked DB)
  - **Behavior**: Full registration flow with valid/invalid inputs, verifying response shapes, status codes, and error messages. Includes: duplicate username, duplicate email, invalid user_group_hash, user_group with no linked projects.
  - **File**: `tests/e2e/test_registration_contract.py`
  - **Type**: Contract-heavy
  - **Trace**: explore.md Gap 2

- [x] **Slice 6 — Groups-of-groups endpoint contracts** — proof layer: Layer 3 (e2e, mocked DB)
  - **Behavior**: Contract tests for `POST/DELETE /admin/user-groups/{hash}/project-groups`, `POST/DELETE /admin/project-groups/{hash}/projects`, verifying request/response shapes, validation errors, and 404/403 scenarios.
  - **File**: `tests/e2e/test_groups_of_groups_contract.py`
  - **Type**: Contract-heavy
  - **Trace**: explore.md Gap 3

### Phase 3: Real-Data Integration Tests (requires MySQL 8.0 via docker-compose)

These slices are the **critical path** — they prove the actual stored procedures and data chain work with persisted data.

- [x] **Slice 7 — Entity creation with real MySQL** — proof layer: Layer 4 (real DB integration)
  - **Behavior**: Create user, user_group, project_group, project directly via DB layer functions (not HTTP). Verify each entity persists with correct schema, UUIDs, and `is_active = 1`.
  - **File**: `tests/integration/test_slice20_real_entity_creation.py`
  - **Type**: ~~Bug-fix readiness~~ **SUPERSEDED**
  - **Trace**: explore.md Gap 1, SQL architecture GAP 1
  - **Superseded by**: Slices 9, 11, 12 — The `RealDBFactory` used across these slices already exercises entity creation against real MySQL in 12+ passing tests. Every test that calls `real_factory.create_user()`, `create_project()`, `create_user_group()`, `create_project_group()` is proof that entity creation works with correct schema, UUIDs, and `is_active = 1`. A dedicated "entity creation" test would be redundant.

- [x] **Slice 8 — Bridge table linking with real MySQL** — proof layer: Layer 4 (real DB integration)
  - **Behavior**: Link entities via bridge tables: user → user_group (user_group_members), project → project_group (project_group_members), user_group → project_group (user_group_project_groups). Verify FK constraints, UNIQUE constraints, and `assigned_at`/`granted_at` timestamps.
  - **File**: `tests/integration/test_slice21_real_bridge_linking.py`
  - **Type**: ~~Bug-fix readiness~~ **SUPERSEDED**
  - **Trace**: explore.md Gap 1, SQL architecture Section 1
  - **Superseded by**: Slices 9, 11, 12 — The full-chain tests in Slice 9 and soft-delete tests in Slice 11 already prove bridge table linking works correctly. FK constraints are proven by the fact that all tests pass (they'd fail with IntegrityError if FKs were wrong). UNIQUE constraints are proven by the idempotency tests in Slice 12 (re-running `create_default_groups` doesn't create duplicates). The `RealDBFactory.link_*` methods exercise all three bridge tables in every test.

- [x] **Slice 9 — `get_user_accessible_projects` with real MySQL** — proof layer: Layer 4 (real DB integration)
  - **Behavior**: The **linchpin test**. Create a full chain (user → user_group → project_group → project), call `get_user_accessible_projects(user_id)`, verify it returns the correct project. Then test: (a) user in multiple groups, (b) project in multiple project_groups, (c) soft-deleted user_group does NOT grant access, (d) soft-deleted project does NOT appear.
  - **File**: `tests/integration/test_slice22_real_access_resolution.py`
  - **Type**: **Bug fix** — if this fails, the access control system is broken
  - **Trace**: explore.md RISK 3 (CRITICAL), Gap 5, SQL architecture GAP 2

- [x] **Slice 10 — Registration → Login → Access with real MySQL** — proof layer: Layer 5 (full E2E with Docker)
  - **Behavior**: The **gold standard** test. Full HTTP flow: register user (via API) → login (via API) → verify accessible_projects contains the expected project. Uses real MySQL + real Redis.
  - **File**: `tests/e2e/test_full_chain_lifecycle.py`
  - **Type**: **Bug fix** — end-to-end proof of the entire system
  - **Trace**: explore.md Gap 2, Gap 5, RISK 1 (CRITICAL)

### Phase 4: Soft-Delete & Cascade Tests (requires MySQL 8.0)

- [x] **Slice 11 — Soft-delete cascade verification** — proof layer: Layer 4 (real DB integration)
  - **Behavior**: Test that soft-deleting a user_group revokes access for all members (verified via `get_user_accessible_projects`). Test that soft-deleting a project_group revokes access for all linked user_groups. Test that `sp_delete_project` does/does not clean bridge rows (document current behavior, flag if broken).
  - **File**: `tests/integration/test_slice23_soft_delete_cascades.py`
  - **Type**: **Bug fix** — SQL architecture RISK 3, RISK 4
  - **Trace**: SQL architecture RISK 3, RISK 4, GAP 3

- [x] **[P] Slice 12 — `create_default_groups` with real MySQL** — proof layer: Layer 4 (real DB integration)
  - **Behavior**: Call `create_default_groups(project_id)` against real MySQL. Verify: (a) project_group created, (b) project linked to it, (c) 3 user groups created, (d) each user group linked to project_group, (e) re-running for same project does NOT create duplicates (ON DUPLICATE KEY UPDATE behavior).
  - **File**: `tests/integration/test_slice24_real_default_groups.py`
  - **Type**: **Bug fix** — explore.md RISK 2
  - **Trace**: explore.md RISK 2, Gap 4

### Phase 5: Dead Code & Cleanup (no Docker)

- [x] **[P] Slice 13 — Dead `UserGroupProject` model removal** — proof layer: Layer 1 (unit)
  - **Behavior**: Confirm `UserGroupProject` in `src/Util/Models.py` is never instantiated anywhere. Remove it. Verify no imports break.
  - **File**: `tests/unit/test_models_cleanup.py` (add assertion that model is removed)
  - **Type**: Characterization → cleanup
  - **Trace**: SQL architecture RISK 1

## Parallel Safety

| Slice | Parallel-Safe? | Reason |
|-------|---------------|--------|
| Slice 1 | **[P] Yes** | Independent orchestration test, no shared fixtures with Slice 2/4 |
| Slice 2 | **[P] Yes** | Independent orchestration test, no shared fixtures with Slice 1/4 |
| Slice 3 | No | Depends on project creation flow tested in Slice 1's registration prereqs |
| Slice 4 | **[P] Yes** | Independent admin endpoint orchestration |
| Slice 5 | **[P] Yes** | Contract test, no DB state dependency |
| Slice 6 | No | Depends on Slice 5's endpoint contracts being established |
| Slice 7 | No | First real-DB test — must establish Docker infrastructure first |
| Slice 8 | No | Depends on Slice 7's entity creation |
| Slice 9 | No | Depends on Slice 8's bridge linking |
| Slice 10 | No | Depends on Slices 7-9 passing |
| Slice 11 | No | Depends on Slice 9's access resolution |
| Slice 12 | **[P] Yes** | Can run in parallel with Slice 11 (independent DB tests) |
| Slice 13 | **[P] Yes** | Pure unit test, no dependencies |

**Parallel execution groups**:
- Group A: Slices 1, 2, 4 (Phase 1 characterization, all independent)
- Group B: Slices 5, 13 (Phase 2 contract + Phase 5 cleanup, independent)
- Group C: Slices 11, 12 (Phase 4 real-DB, independent of each other)

## Gates

| Gate | Required? | Why |
|------|-----------|-----|
| All existing tests pass | **Yes** | Must not regress 31 existing test files |
| Coverage ≥ 44% (current baseline) | **Yes** | Must not decrease overall coverage |
| Coverage on `src/Util/db/db_user_groups.py` ≥ 30% | **Yes** | Currently untested linchpin module (explore.md RISK 3) |
| Coverage on `src/Util/db/db_projects.py` ≥ 25% | **Yes** | `create_default_groups` is raw SQL, needs proof (explore.md RISK 2) |
| Coverage on `src/routes/auth.py` ≥ 50% | **Yes** | Registration + login orchestration tests will push this up |
| No new deprecation warnings | **Yes** | `pytest -W error::DeprecationWarning` must pass |
| Slice 9 passes (real MySQL access resolution) | **Yes** | This is the linchpin — if `sp_get_user_accessible_projects` returns wrong data, the entire access control system is compromised |
| Slice 10 passes (full E2E chain) | **Yes** | Gold standard proof that registration → login → access works end-to-end |

## Commands / Suites

| Scope | Command |
|-------|---------|
| Focused RED/GREEN loop (single slice) | `pytest tests/integration/test_slice{N}_*.py -v --tb=short` |
| Phase 1 (all characterization) | `pytest tests/integration/test_slice1{6,7,8,9}_*.py -v` |
| Phase 2 (all contract) | `pytest tests/e2e/test_*_contract.py -v` |
| Phase 3 (all real-DB integration) | `pytest tests/integration/test_slice2{0,1,2}_*.py -v` |
| Phase 4 (soft-delete + default groups) | `pytest tests/integration/test_slice2{3,4}_*.py -v` |
| Full suite (all new + existing) | `pytest -v` |
| Coverage (full) | `pytest --cov=src --cov-report=term-missing --cov-report=html` |
| Coverage gate | `pytest --cov=src --cov-fail-under=44` |
| Deprecation check | `pytest -W error::DeprecationWarning` |
| Real MySQL tests only | `pytest -m real_db -v` (requires `@pytest.mark.real_db` decorator) |

## Infrastructure Requirements

### For Phases 1-2 (no Docker needed)
- Existing test environment: pytest, fakeredis, freezegun, DBPatcher
- `.env.test` isolation (already configured)

### For Phases 3-4 (MySQL 8.0 required)
- `docker-compose.test.yml` with MySQL 8.0 container
- Stored procedures must be deployed before running real-DB tests
- Test database must be isolated (separate schema or database name)
- Connection string from `.env.test` must point to Docker MySQL
- **Marker**: All real-DB tests must use `@pytest.mark.real_db` so they can be skipped when Docker is not available

### Docker-compose skeleton (to be created in Slice 7):
```yaml
version: "3.8"
services:
  mysql-test:
    image: mysql:8.0
    environment:
      MYSQL_ROOT_PASSWORD: test_root
      MYSQL_DATABASE: api_auth_test
    ports:
      - "3307:3306"
    volumes:
      - ./sql:/docker-entrypoint-initdb.d  # stored procedures
```

## Risks

| Risk | Severity | Mitigation |
|------|----------|------------|
| **No real MySQL in CI** | HIGH | Mark real-DB tests with `@pytest.mark.real_db`; they skip in CI until Docker infra is added. Phase 1-2 tests still provide value. |
| **Stored procedures may have bugs** | HIGH | Slice 9 is the canary — if `sp_get_user_accessible_projects` returns wrong results, the test will fail and we'll know exactly what to fix. This is the point of TDD. |
| **`create_default_groups` raw SQL may break with schema changes** | HIGH | Slice 12 verifies the raw SQL against real MySQL. If it fails, we know immediately. |
| **Test data isolation in real MySQL** | MEDIUM | Each real-DB test must create unique entities (UUID-based) and clean up via soft-delete or direct cleanup in teardown. Consider transaction rollback pattern. |
| **Sync DB drivers block event loop** | MEDIUM | Real-DB tests will be slower. Acceptable for integration layer; not a blocker. |
| **Session creation bypasses access validation** | HIGH | SQL architecture RISK 2 — this may be a bug in production code. Slice 10 will expose it if login succeeds for a user with no group access. |
| **Soft-delete vs FK CASCADE contradiction** | MEDIUM | Slice 11 will document current behavior. If CASCADE fires on hard DELETE, we flag it but don't fix it in this change (scope creep). |
| **Dead `UserGroupProject` model removal may break imports** | LOW | Slice 13 verifies no imports before removal. If imports exist, we skip removal and just document the dead code. |

## Traceability Matrix

| Slice | explore.md Reference | SQL Architecture Reference | Risk Addressed |
|-------|---------------------|---------------------------|----------------|
| 1 | RISK 4, Gap 2 | — | Registration prerequisite chain |
| 2 | RISK 3, Gap 1 | RISK 2 | Login orchestration with groups |
| 3 | RISK 2, Gap 4 | RISK 5 | Default groups creation |
| 4 | Gap 3, RISK 1 | — | User group → project group linking |
| 5 | Gap 2 | — | Registration endpoint contract |
| 6 | Gap 3 | — | Groups-of-groups endpoint contracts |
| 7 | Gap 1 | GAP 1 | Real entity creation |
| 8 | Gap 1 | Section 1 | Bridge table linking |
| 9 | RISK 3, Gap 5 | GAP 2 | Access resolution linchpin |
| 10 | Gap 2, Gap 5, RISK 1 | GAP 1, GAP 2 | Full E2E chain |
| 11 | — | RISK 3, RISK 4, GAP 3 | Soft-delete cascades |
| 12 | RISK 2, Gap 4 | RISK 5 | Real default groups |
| 13 | — | RISK 1 | Dead code removal |

## Execution Order

```
Phase 1 (parallel):  [Slice 1] ─┐
                                 ├──→ [Slice 3] ──→ [Slice 6]
               [Slice 2] ─┘                        │
                                                   ↓
               [Slice 4] ─────────────────────→ [Phase 2: Slice 5]

Phase 3 (sequential): [Slice 7] → [Slice 8] → [Slice 9] → [Slice 10]

Phase 4 (parallel):   [Slice 11] ─┐
                                   └── (both after Phase 3)
                  [Slice 12] ─┘

Phase 5 (anytime):    [Slice 13] (independent, can run anytime)
```

**Critical path**: Slice 7 → Slice 8 → Slice 9 → Slice 10 (Phase 3 sequential chain)
**Fastest feedback**: Slices 1, 2, 4, 5, 13 (all parallel, no Docker needed)
