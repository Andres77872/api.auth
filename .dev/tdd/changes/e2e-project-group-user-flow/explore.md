# TDD Exploration: e2e-project-group-user-flow

**Date**: 2026-04-17
**Change**: e2e-project-group-user-flow
**Phase**: Explore
**Status**: READY FOR `tdd-strategy`

---

## Executive Summary

The codebase implements a **groups-of-groups architecture** for multi-project auth:
`USER → USER_GROUP → PROJECT_GROUP → PROJECT`. The current test suite has 31 test files (13 unit, 17 integration, 1 e2e) with 44% coverage. **Zero tests verify that the full chain of entity creation, linking, and access resolution actually works end-to-end.** All integration tests use MagicMock stubs at the DB boundary. The single e2e file (`tests/e2e/test_api_lifecycle.py`) covers auth lifecycle, CORS, and error shapes — but **nothing** about project/group/user creation flows, membership linking, or the groups-of-groups access chain.

**The biggest gap**: There is no test that proves a consumer user, created via registration, assigned to a user group, which is linked to a project group containing a project, can actually access that project through the full chain. Every test stubs out the DB layer.

---

## 1. Current Test Topology

### Files by Layer

| Layer | Count | Files |
|-------|-------|-------|
| Unit | 13 | `test_models.py`, `test_seccurity.py`, `test_jwt_security.py`, `test_password_generator.py`, `test_password_security.py`, `test_uuid_generator.py`, `test_db_error_wrapper.py`, `test_error_handler.py`, `test_system_metrics.py`, `test_api_audit_logger.py`, `test_db_audit_analytics.py`, `test_audit_export.py`, `test_log_context_models.py` |
| Integration | 17 | Slices 0-15: `test_slice0_infrastructure.py` through `test_slice15_audit_logs.py` |
| E2E | 1 | `test_api_lifecycle.py` |

### Relevant Integration Slices for This Change

| Slice | File | What It Covers | Stub Level |
|-------|------|----------------|------------|
| 7 | `test_slice7_user_profile.py` | GET/PUT /users/profile, GET /users/access-summary | All DB calls mocked |
| 8 | `test_slice8_user_management.py` | GET /users/list, GET /users/{hash}, PUT status, DELETE, reset-password | All DB calls mocked |
| 9 | `test_slice9_project_crud.py` | GET/POST/PUT/DELETE /projects, members, activity, stats | All DB calls mocked |
| 11 | `test_slice11_admin_project_groups.py` | GET/POST/PUT/DELETE /admin/project-groups, assign/remove projects | All DB calls mocked |
| 6 | `test_slice6_permission_enforcement.py` | Auth boundary: 401/403 by user type | All DB calls mocked |

### E2E File (`tests/e2e/test_api_lifecycle.py`)

- **E2E 1**: Health check pipeline (GET /ping)
- **E2E 2**: Auth flow — login with **fully mocked** `get_user_by_credentials`, `get_user_accessible_projects`, `get_project_by_hash`, `get_user_groups_for_user` (lines 73-76)
- **E2E 3**: Unauthenticated access denied
- **E2E 4**: Error response shape
- **E2E 5**: CORS, empty bearer, password leak

**Critical finding**: The e2e login test (line 59-95) uses `MagicMock` for user, project, and group objects. No real data flows through the system. The test verifies response shape and cookie flags, but **proves nothing about the data chain**.

---

## 2. Architecture & Data Model

### The Groups-of-Groups Chain

The architecture is documented in multiple places:

- `src/routes/projects.py` lines 973-987: Explicit comment block
- `src/Util/db/db_user_groups.py` lines 525-538: Comment block
- `src/Util/Models.py` lines 255-259: `ProjectGroupInfo` docstring

**The chain**: `USER → USER_GROUP → PROJECT_GROUP → PROJECT`

### Key Tables (inferred from stored procedure calls and raw SQL)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `users` | User records | id, user_hash, username, email, password_hash, user_type, is_active |
| `user_groups` | Global user groups | id, group_hash, group_name, group_description, is_active |
| `user_group_members` | User ↔ UserGroup membership | id, user_id, user_group_id, assigned_at, is_active |
| `project_groups` | Project groups (containers) | id, group_hash, group_name, group_description, is_active |
| `project_group_members` | Project ↔ ProjectGroup membership | id, project_id, project_group_id, assigned_at, is_active |
| `user_group_project_groups` | UserGroup ↔ ProjectGroup link | id, user_group_id, project_group_id, granted_at, is_active |
| `projects` | Project records | id, project_hash, project_name, project_description, is_active |

### Default Group Creation (on project creation)

`src/Util/db/db_projects.py` lines 444-526: `create_default_groups()` creates:
1. A default `project_group` named `default_{project_id}`
2. Links the project to it via `project_group_members`
3. Creates 3 user groups: `admin_{project_id}`, `user_{project_id}`, `readonly_{project_id}`
4. Links each user group to the project group via `user_group_project_groups`

**This uses raw SQL INSERT with ON DUPLICATE KEY UPDATE**, not stored procedures. This is the **only place** in the DB layer that bypasses stored procedures.

### Registration Flow

`src/routes/auth.py` lines 302-440:
1. Validates username/email availability
2. Validates `user_group_hash` exists
3. Validates user group has linked projects (`get_projects_for_user_group`)
4. Calls `enhanced_register(username, password, email, user_group_hash)`
5. Returns session token + cookie

### Login Flow

`src/routes/auth.py` lines 117-299:
1. `get_user_by_credentials(username, password)` → User object
2. For root: global session, no project binding
3. For non-root: `get_user_accessible_projects(user_id)` → list of ProjectSummary
4. If no accessible projects → 403
5. If `project_hash` specified: verify access, else use first accessible
6. `_create_session()` → stores in Redis with user_group_ids/names
7. Returns LoginResponse with accessible_projects and user_groups

---

## 3. Risky Seams & Blind Spots

### RISK 1: No End-to-End Chain Verification (CRITICAL)

**Where**: Entire codebase
**What**: No test creates a real user, real user group, real project group, real project, links them all together, and verifies the user can access the project through the chain.
**Impact**: The groups-of-groups architecture could be completely broken and no test would catch it. All tests mock at the DB boundary.

### RISK 2: `create_default_groups()` Uses Raw SQL (HIGH)

**Where**: `src/Util/db/db_projects.py` lines 474-519
**What**: Bypasses stored procedures, uses raw `INSERT ... ON DUPLICATE KEY UPDATE`. This is the only DB function that does this.
**Impact**: If table schema changes, this will break silently in tests (mocked) but fail in production. Also, the `ON DUPLICATE KEY UPDATE` means re-creating defaults for an existing project silently reactivates — no test verifies this behavior.

### RISK 3: `get_user_accessible_projects` Is the Linchpin (HIGH)

**Where**: `src/Util/db/db_user_groups.py` lines 606-648
**What**: This stored procedure call (`sp_get_user_accessible_projects`) is the **single point of truth** for determining what projects a user can see. It's called in login, project listing, profile, access-summary, user management, and project details.
**Impact**: If this SP returns wrong data, the entire access control system is compromised. No integration test verifies its behavior with real linked data.

### RISK 4: Registration Requires Pre-Existing User Group With Projects (MEDIUM)

**Where**: `src/routes/auth.py` lines 379-392
**What**: Registration validates that the user group has linked projects. But the flow to **create** that linkage is:
1. Create project (auto-creates default groups)
2. Create user group (manually)
3. Grant user group access to project group via `POST /admin/user-groups/{hash}/project-groups`

There's no test that verifies this prerequisite chain works.

### RISK 5: Session Data Staleness (MEDIUM)

**Where**: `src/Util/db/db_users.py` lines 982-1030 (`validate_session`)
**What**: Session data stored in Redis at login time includes `user_group_ids` and `user_group_names`. If a user's group membership changes after login, the session data is stale until next login or session refresh.
**Impact**: A user removed from a group may still have access until session expires. No test verifies session invalidation on membership change.

### RISK 6: `get_user_project_permissions` Returns GLOBAL Permissions (MEDIUM)

**Where**: `src/Util/db/db_project_groups.py` lines 613-628
**What**: The function comment explicitly says: "After refactor to global role system, permissions are now global (not project-specific). This function maintains backward compatibility by returning global permissions."
**Impact**: Any code calling `get_user_project_permissions(user_id, project_id)` ignores the `project_id` parameter. This is documented but could lead to subtle authorization bugs if callers assume project-scoped permissions.

### RISK 7: Admin Multi-Project Access Via User Groups (MEDIUM)

**Where**: `src/Util/db/db_users.py` lines 1127-1184 (`add_admin_to_project`)
**What**: Admin users are added to projects by being placed in the project's admin user group (`sp_find_admin_group_for_project`). This is a different mechanism than consumer users (who access via user_group → project_group → project).
**Impact**: Two different access mechanisms exist. No test verifies that an admin added to a project via `add_admin_to_project` can actually see that project in `get_user_accessible_projects`.

### RISK 8: Duplicate `count_user_groups` / `get_total_user_groups_count` (LOW)

**Where**: `src/Util/db/db_user_groups.py` lines 651-692
**What**: Both functions call the same stored procedure `sp_count_user_groups` with no parameters. They are functionally identical.
**Impact**: Maintenance burden, potential for drift if one is updated and the other isn't.

---

## 4. Current Proof Gaps

### Gap 1: No Real Data Flow Through Groups-of-Groups Chain

Every integration test mocks:
- `get_user_accessible_projects` → returns pre-built list
- `get_user_groups_for_user` → returns pre-built list
- `get_project_by_hash` → returns MagicMock
- `get_user_by_hash` → returns MagicMock

**Missing**: A test that uses the actual DB layer functions to create entities, link them, and verify the chain resolves correctly.

### Gap 2: No Registration → Login → Access Flow

The registration endpoint (`POST /auth/register`) is tested nowhere. The integration slices cover auth login/validate/logout (slice 4) and auth register availability (slice 3), but not the full registration flow with group assignment.

### Gap 3: No User Group → Project Group Linking Tests

The endpoints `POST /admin/user-groups/{hash}/project-groups` and `DELETE /admin/user-groups/{hash}/project-groups/{pg_hash}` exist in `admin_user_groups.py` (lines 482-649) but have **zero test coverage** in any slice.

### Gap 4: No Project Creation → Default Groups Verification

When a project is created, `create_default_groups()` runs automatically. No test verifies that the default groups are actually created and linked.

### Gap 5: No Consumer User Access Resolution

No test verifies that a consumer user, assigned to a user group that is linked to a project group containing a project, can actually list and access that project.

### Gap 6: No Cross-Entity Deletion Cascade Tests

What happens when:
- A user group is deleted? (Should revoke all memberships and project group links)
- A project group is deleted? (Should revoke all user group links and project memberships)
- A project is deleted? (Should clean up project group memberships)

No tests verify cascade behavior.

---

## 5. Candidate Proving Layers

### Layer 1: Unit (Already Complete)
Pure function tests for models, UUID generation, password hashing, etc. **No changes needed here.**

### Layer 2: Integration (Already Complete but Stubbed)
HTTP-level tests with real FastAPI app but mocked DB. **These are valuable for route/response shape testing but cannot prove data flow.**

### Layer 3: Contract Testing (Missing)
Schema validation of API request/response contracts. Could use schemathesis or manual Pydantic validation tests.

### Layer 4: **Real Data Flow Integration** (RECOMMENDED NEXT)
Tests that use an in-memory SQLite or real MySQL with actual stored procedures to verify:
- Entity creation (user, user group, project group, project)
- Linking (user → user group, project → project group, user group → project group)
- Access resolution (`get_user_accessible_projects` returns correct results)
- The full registration → login → access chain

### Layer 5: E2E with Docker (Future)
Full MySQL 8.0 + Redis container with real stored procedures deployed. This is the "gold standard" but requires infrastructure setup.

---

## 6. Recommended Direction

### Immediate Next Step: Real Data Flow Integration Tests

Create a new proving layer that sits between the current mocked integration tests and a full Docker-based E2E. Options:

**Option A: SQLite with simplified schema** — Fast, no Docker, but stored procedures won't work. Would require rewriting DB layer for test mode.

**Option B: Real MySQL via docker-compose** — Most realistic, but requires infrastructure setup. The stored procedures are the source of truth and cannot be tested without MySQL.

**Option C: Characterization tests with enhanced mocking** — Keep mocks but build a "scenario runner" that chains entity creation through the mocked layer, verifying that the correct DB functions are called with correct parameters in the correct order. This proves the **orchestration** is correct even if the DB layer isn't tested.

**Recommendation**: Start with **Option C** (characterization tests) as the smallest proof slice, then progress to **Option B** (real MySQL) for the full chain verification.

### Smallest Next Proof Slices (in priority order)

1. **Registration → Login → Access Chain** (characterization): Mock the DB layer but verify the correct sequence of calls: `check_username_email_available` → `get_user_group_by_hash` → `get_projects_for_user_group` → `enhanced_register` → `get_user_accessible_projects` → `get_project_by_hash` → `_create_session`.

2. **Project Creation → Default Groups** (characterization): Verify that `create_project` calls `create_default_groups` and that the correct user groups and project group are created with correct linkages.

3. **User Group → Project Group Access Grant** (characterization): Verify the full chain: create user group, create project group, link project to project group, grant user group access to project group, verify `get_user_accessible_projects` returns the project.

4. **Consumer Access Resolution** (integration with real DB): The first test that requires real MySQL. Create entities, link them, and verify the stored procedure returns correct results.

---

## 7. Files Affected by This Change

### Production Code (for reference)
| File | Role |
|------|------|
| `src/Util/Models.py` | All entity models (User, Project, UserGroup, ProjectGroup, relationships) |
| `src/Util/db/db_users.py` | User CRUD, session management, admin multi-project |
| `src/Util/db/db_projects.py` | Project CRUD, `create_default_groups()` |
| `src/Util/db/db_user_groups.py` | User group CRUD, membership, groups-of-groups access |
| `src/Util/db/db_project_groups.py` | Project group CRUD, project assignment |
| `src/Util/db/db_global_roles.py` | Global role system (permissions, roles) |
| `src/Util/db/__init__.py` | Re-export surface for all DB functions |
| `src/routes/auth.py` | Login, register, validate, logout, refresh, switch-project |
| `src/routes/projects.py` | Project CRUD, members, activity, stats |
| `src/routes/admin_user_groups.py` | User group admin + groups-of-groups endpoints |
| `src/routes/admin_project_groups.py` | Project group admin endpoints |
| `src/routes/users.py` | User profile, management, access-summary |

### Test Code (to be created/modified)
| File | Status |
|------|--------|
| `tests/e2e/test_api_lifecycle.py` | Needs new test classes for project/group/user flows |
| `tests/e2e/conftest.py` | Needs factories for entity creation scenarios |
| `tests/integration/test_slice11_admin_project_groups.py` | Missing user-group → project-group linking tests |
| **NEW**: `tests/integration/test_slice16_project_group_user_flow.py` | Proposed new slice |
| **NEW**: `tests/e2e/test_full_chain_lifecycle.py` | Proposed new e2e file |

---

## 8. [NEEDS CLARIFICATION] Items

1. **Stored procedure availability**: Can stored procedures be tested without a real MySQL 8.0 instance? If docker-compose is acceptable, what is the project's policy on CI infrastructure?
2. **Test data isolation**: Should each test create and clean up its own data, or is there a seed/fixture mechanism that pre-populates test data?
3. **Scope of "real flow"**: Does "real flow" mean real DB (MySQL) or real orchestration (correct function call sequence with mocks)?

---

## 9. Engram Discoveries

The following discrete insights have been saved to persistent memory:

- **tdd/e2e-project-group-user-flow: create_default_groups bypasses stored procedures** — Only DB function using raw SQL INSERT, not tested
- **tdd/e2e-project-group-user-flow: get_user_accessible_projects is the single access control linchpin** — Called by 10+ endpoints, zero real-data tests
- **tdd/e2e-project-group-user-flow: registration requires pre-existing user group with projects** — No test verifies the prerequisite chain
- **tdd/e2e-project-group-user-flow: session data includes stale group membership** — No invalidation test on membership change
- **tdd/e2e-project-group-user-flow: user_group → project_group endpoints have zero test coverage** — Critical gap in groups-of-groups architecture

---

## Result Contract

| Field | Value |
|-------|-------|
| **Status** | ✅ READY FOR `tdd-strategy` |
| **Executive Summary** | 31 test files exist but ALL mock the DB boundary. Zero tests verify the groups-of-groups chain (USER → USER_GROUP → PROJECT_GROUP → PROJECT) with real data. The registration → login → access flow is completely untested. 8 risky seams identified, 6 proof gaps documented. |
| **Artifacts** | `.dev/tdd/changes/e2e-project-group-user-flow/explore.md` |
| **Next Recommended** | `tdd-strategy` — define proving layers starting with characterization tests for the registration → login → access chain, then progress to real MySQL integration tests for the full groups-of-groups chain |
| **Risks** | HIGH: No end-to-end chain verification; `create_default_groups()` uses raw SQL; `get_user_accessible_projects` is untested linchpin. MEDIUM: Session staleness, dual admin access mechanisms, global vs project-scoped permissions confusion. |
