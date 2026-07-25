# Permission Resolution

How the authorization model actually works — roles, permission groups, user groups, direct assignments, and the important caveats about what is and isn't enforced during authentication.

---

## Table of Contents

- [Overview](#overview)
- [The Three User Types](#the-three-user-types)
- [The Permission Chain](#the-permission-chain)
- [Permission Sources](#permission-sources)
- [Two Resolution Paths (Critical Caveat)](#two-resolution-paths-critical-caveat)
- [Project-Scoped Permissions](#project-scoped-permissions)
- [Conflict & Duplicate Handling](#conflict--duplicate-handling)
- [What the Permissions Endpoints Show vs. What Auth Uses](#what-the-permissions-endpoints-show-vs-what-auth-uses)
- [Practical Examples](#practical-examples)
- [Known Gaps & Limitations](#known-gaps--limitations)

---

## Overview

The API uses a **role-based permission model** with three sources of permissions:

1. **Roles** → Permission Groups → Permissions (primary path, used during auth)
2. **User Groups** → Permission Groups → Permissions (available via inspection endpoints)
3. **Direct User** → Permission Groups → Permissions (available via inspection endpoints)

> **Important**: Not all three sources are active during the authentication flow. See [Two Resolution Paths](#two-resolution-paths-critical-caveat) below.

---

## The Three User Types

| Type | Scope | Permission Model |
|------|-------|-----------------|
| `root` | Global | Bypasses all permission checks. Unrestricted access to everything. |
| `admin` | Project-scoped | Must have `require_admin` or specific permission (e.g., `manage_users`, `manage_roles`). Scoped to assigned projects. |
| `consumer` | Group-scoped | Access controlled entirely through group membership and permission assignments. |

Root users **never** go through permission resolution — they bypass all checks.

---

## The Permission Chain

```
PERMISSIONS
    ↑
PERMISSION GROUPS (collections of permissions)
    ↑
    ├── ROLES ──────────────────────── (assigned to users, used during auth)
    ├── USER GROUPS ────────────────── (assigned to users, NOT used during auth)
    └── DIRECT USER ASSIGNMENTS ────── (assigned to users, NOT used during auth)
```

### Building Blocks

| Concept | Description |
|---------|-------------|
| **Permission** | A single action identifier (e.g., `read`, `write`, `manage_users`, `manage_roles`) |
| **Permission Group** | A named collection of permissions (e.g., `content_management`, `api_access`) |
| **Role** | A named collection of permission groups, assigned to individual users |
| **Role Priority** | A 0-100 number used **only for ordering in catalog listings**, NOT for resolution precedence |

---

## Permission Sources

A user can receive permissions from three sources:

### Source 1: Role Assignment (ACTIVE during auth)

```
User → Role → Permission Groups → Permissions
```

- Each user can have **one global role** assigned
- Roles aggregate permission groups
- This is the **only source evaluated during login/session creation**

### Source 2: User Group Permission Assignment (NOT active during auth)

```
User → User Group → Permission Groups → Permissions
```

- Admins assign permission groups to user groups
- All members of the user group inherit those permission groups
- **These are NOT included in the effective permissions during session creation**
- Visible via `GET /permissions/admin/user-groups/{hash}/permission-groups`

### Source 3: Direct User Permission Assignment (NOT active during auth)

```
User → Permission Groups → Permissions
```

- Admins assign permission groups directly to individual users
- **These are NOT included in the effective permissions during session creation**
- Visible via `GET /permissions/users/{hash}/permission-groups`

---

## Two Resolution Paths (Critical Caveat)

**This is the most important thing to understand about the permission system.**

### Path A: `sp_global_get_user_permissions` — Used During Auth

- **Stored procedure**: `sp_global_get_user_permissions` (in `05_global_roles.sql`)
- **Called by**: Login, session creation, session refresh
- **What it resolves**: **ROLE ONLY**
  ```sql
  users → roles → role_permission_groups → global_permission_group_permissions → global_permissions
  ```
- **What it does NOT include**:
  - Direct user → permission group assignments
  - User group → permission group assignments

**This means**: If you assign a permission group directly to a user or to their user group, those permissions will **NOT** be recognized during authentication. They will not appear in the session's permission list.

### Path B: `sp_get_user_all_permissions` — Used by Inspection Endpoints

- **Stored procedure**: `sp_get_user_all_permissions` (in `06_permission_assignments.sql`)
- **Called by**: `GET /permissions/users/me/permissions` and related endpoints
- **What it resolves**: **ALL THREE SOURCES** (UNION)
  ```sql
  1. Role → role_permission_groups → permissions
  2. User group membership → user_group_permission_groups → permissions
  3. Direct user → user_permission_groups → permissions
  ```

**This means**: `GET /permissions/users/me/permissions` will show permissions
from all three sources, but the **auth flow only uses Source 1 (role)**.

### The Gap

| Aspect | During Auth (Path A) | Via `/permissions/users/me/permissions` (Path B) |
|--------|---------------------|----------------------------|
| Role permissions | Yes | Yes |
| User group permissions | **No** | Yes |
| Direct user permissions | **No** | Yes |
| Deduplication | `SELECT DISTINCT` | `SELECT DISTINCT` |

> **This is a potential architectural gap or bug.** Permissions assigned via user groups or directly to users exist in the database and are visible through inspection endpoints, but they are not enforced during authentication. This may be intentional (roles are the only auth-time mechanism) or it may be an oversight.

---

## Project-Scoped Permissions

There is a separate stored procedure for project-scoped permission checks:

- **Stored procedure**: `sp_check_user_permission_for_project_with_deny`
- **Logic**:
  - Root users bypass all checks
  - Scoped **deny** with priority >= grant priority wins (deny takes precedence at equal priority)
  - Falls back to global permissions if no scoped rules exist

This is a SQL-layer artifact for fine-grained, project-specific access control beyond the global role system. It is **currently unused by application code**; no Python route/helper calls `sp_check_user_permission_for_project_with_deny` today.

---

## Conflict & Duplicate Handling

- Both stored procedures use `SELECT DISTINCT` to eliminate duplicate permission names
- There is **no explicit conflict resolution** — if a permission appears from multiple sources, it is simply returned once
- **Deny takes precedence** in project-scoped checks when deny priority >= grant priority
- **Role priority (0-100) is NOT used for resolution** — it only affects ordering in catalog listings

---

## What the Permissions Endpoints Show vs. What Auth Uses

This table clarifies the disconnect:

| Endpoint | What it shows | Uses which path |
|----------|--------------|----------------|
| `GET /permissions/users/me/permissions` | All permissions from all 3 sources | Path B (comprehensive) |
| `GET /permissions/users/me/permission-groups` | Direct permission groups assigned to user | Direct assignments only |
| `GET /permissions/users/me/permission-sources` | Breakdown of permission sources | Path B (comprehensive) |
| `GET /roles/users/me/role` | Current user's assigned role | Role only |
| **Auth during login/session** | **Only role permissions** | **Path A (role-only)** |

**Practical implication**: A user may see permissions listed by
`GET /permissions/users/me/permissions` that are **not actually effective**
during authenticated API calls, because those permissions come from user-group
or direct assignments that the auth flow does not evaluate.

---

## Practical Examples

### Example 1: Role-Only (Works as Expected)

```
User: alice
Role: "developer" → Permission Groups: ["content_management", "api_access"]
```

- Login resolves alice's permissions via her role
- Session includes all permissions from `content_management` and `api_access`
- All API calls check against this session permission list

### Example 2: User Group Assignment (NOT Effective During Auth)

```
User: bob
Role: "viewer" → Permission Groups: ["read_only"]
User Group: "developers" → Permission Groups: ["api_access", "write_access"]
```

- Login resolves bob's permissions via his role ("viewer") only
- Session includes only `read_only` permissions
- `api_access` and `write_access` from the user group are **NOT** in the session
- `GET /permissions/users/me/permissions` WILL show all permissions (from both sources)
- But API calls will only recognize the role-based permissions

### Example 3: Direct Assignment (NOT Effective During Auth)

```
User: charlie
Role: "viewer" → Permission Groups: ["read_only"]
Direct assignment: "advanced_analytics" permission group
```

- Login resolves charlie's permissions via role only
- `advanced_analytics` permissions are **NOT** in the session
- `GET /permissions/users/me/permission-sources` will show the direct assignment
- But API calls will not recognize those permissions

---

## Known Gaps & Limitations

1. **User group and direct permission assignments are not enforced during auth**. They are visible through inspection endpoints but do not affect session permissions. This may be by design (roles are the only auth mechanism) or it may be an oversight.

2. **Role priority is cosmetic**. Despite having a 0-100 priority field, it only affects catalog ordering, not resolution precedence.

3. **No active deny support in global permissions**. Deny logic exists only in the SQL-only project-scoped procedure (`sp_check_user_permission_for_project_with_deny`), and that procedure is not wired into the current Python application path.

4. **One role per user**. The system assigns a single global role per user. There is no multi-role support.

5. **Permissions are global, not project-scoped** (except for the deny logic). A permission like `manage_users` applies everywhere, not to a specific project.

6. **Cache can cause stale permission views**. Permission checks are cached with a 30-minute TTL (`PERMISSION_CHECK_TTL = 1800`). After admin changes, users may see stale permissions until cache expires or is manually invalidated.

---

## Related Documentation

- [Permissions Documentation Suite](README.md) — Managing roles, permission groups, assignments, and authorization caveats
- [Error Reference](../errors.md) — Authorization error codes and troubleshooting
- [Groups Documentation Suite](../groups/README.md) — User groups and project access chain
- [Getting Started](../getting-started.md) — Initial setup and user onboarding

---

**Document Version**: 1.0
