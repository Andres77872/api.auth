# Permissions Architecture

Technical architecture of the permissions system as it actually exists in `api.auth`.

---

## Dual-Path Authorization Model

This repository authorizes requests through **two overlapping paths**:

1. **User-type checks** — `root`, `admin`, `consumer`, project access
2. **Global RBAC checks** — roles, permission groups, individual permissions

Those paths are related, but they are NOT the same thing.

```
REQUEST
  └─► token from Authorization header or `session_token` cookie
        └─► validate_session(...)
              ├─► user-type logic
              │     ├─► root: broad allow path
              │     ├─► admin: project-scoped admin access checks
              │     └─► consumer: normal user path
              └─► session permission logic
                    └─► role-derived permissions only

Separate `/permissions/users/...` inspection endpoints
  └─► extended union of role + user-group + direct assignments
```

User-type/project-access checks and permission checks must therefore be
evaluated separately.

---

## Active Tables Behind the Global Permission System

| Table | Purpose |
|------|---------|
| `roles` | Global roles assigned directly to users |
| `global_permission_groups` | Reusable permission-group templates |
| `global_permissions` | Individual global permission names |
| `role_permission_groups` | Links global roles to permission groups |
| `global_permission_group_permissions` | Links permission groups to permissions |
| `user_group_permission_groups` | Grants permission groups to user groups |
| `user_permission_groups` | Grants permission groups directly to users |

The stored procedures in `05_global_roles.sql` and `06_permission_assignments.sql` are the real enforcement backbone for the active public API.

---

## The Three Permission Sources

The extended resolver in `src/Util/db/db_permission_assignments.py` calls `sp_get_user_all_permissions` and `sp_get_user_permission_sources` directly. Its permission-check helper is intended to use the extended permission-check stored procedure, but the Python wrapper currently calls `sp_check_user_has_permission` while `schemas/stored_procedures/06_permission_assignments.sql` defines `sp_check_user_has_permission_extended`.

Those procedures resolve permissions from exactly three sources:

### 1. Role source

```
users.role_id
  → role_permission_groups
  → global_permission_group_permissions
  → global_permissions
```

### 2. User-group source

```
user_group_members
  → user_group_permission_groups
  → global_permission_group_permissions
  → global_permissions
```

### 3. Direct user source

```
user_permission_groups
  → global_permission_group_permissions
  → global_permissions
```

The effective permission set is the **union** of those three sources.

---

## Route and Layer Split

### Global role and permission CRUD

- Route file: `src/routes/global_roles.py`
- DB layer: `src/Util/db/db_global_roles.py`
- Stored procedures: `schemas/stored_procedures/05_global_roles.sql`

### User-group/direct assignments and self-query endpoints

- Route file: `src/routes/permission_assignments.py`
- DB layer: `src/Util/db/db_permission_assignments.py`
- Stored procedures: `schemas/stored_procedures/06_permission_assignments.sql`

### Shared session and middleware behavior

- Session helpers: `src/routes/auth.py`
- Shared exports and user-type checks: `src/Util/db/__init__.py`
- Session validation core: `src/Util/db/db_enhanced.py`
- Middleware guards: `src/middleware/authentication.py`

---

## Admin Guard Matrix

Admin guards are not uniform across route files.

| Area | Guard implementation | What it effectively checks |
|------|----------------------|----------------------------|
| `/roles` | `global_roles.require_admin()` | `root`/`admin` user types, otherwise `manage_roles` via `check_user_has_permission()` |
| `/permissions` admin routes | `permission_assignments.require_admin()` | `root`/`admin` user types, otherwise `manage_roles` via `check_user_has_permission_extended()` |
| `/admin/user-groups` | local `require_admin()` in `admin_user_groups.py` | session permissions must include `admin` or `manage_users` |
| `/admin/project-groups` | local `require_admin()` in `admin_project_groups.py` | session permissions must include `admin` or `manage_roles` |

### Important consequence: permission source coverage is not identical

- `/roles` uses the **role-only** checker from `db_global_roles.py`
- `/permissions` calls the helper named `check_user_has_permission_extended()`,
  but that helper calls a procedure name absent from the canonical schema and
  fails closed for a consumer
- `/admin/user-groups` and `/admin/project-groups` read **session permissions** from `validate_session()`

For consumer users, `validate_session()` currently rebuilds `permissions` with `db_global_roles.get_user_permissions()` — that is the **role-derived** path, not the extended three-source union.

Operationally, a direct or user-group `manage_roles` assignment is visible in
inspection results but does not authorize the active route guards in a fresh
canonical deployment. Root/admin user types still pass the `/permissions`
guard before its broken consumer fallback is needed.

### Procedure-name caveat in the extended checker

There is a concrete fresh-bootstrap mismatch:

- `db_permission_assignments.py` calls `sp_check_user_has_permission`
- `06_permission_assignments.sql` defines `sp_check_user_has_permission_extended`

No compatibility procedure named `sp_check_user_has_permission` exists in the
canonical SQL tree. The wrapper uses `default_return=False`, so this path denies
rather than granting access when the call fails. A separately evolved database
could contain an alias, but that is not part of this repository's bootstrap
contract.

---

## Session, Cache, and Staleness Behavior

### Token sources

`HTTPBearerOrCookie` accepts:

- `Authorization: Bearer ...`
- `session_token` cookie

### Session creation behavior

`src/routes/auth.py` stores a session payload in Redis containing:

- `user_id`
- `user_hash`
- `user_type`
- `project_id` / `project_hash`
- `user_group_ids`
- `user_group_names`

### Validation behavior

`db_enhanced.validate_session()` delegates JWT-shaped access tokens to the lifecycle validator before any cached full-session data is trusted:

- JWT signature, `exp`, `type`, `jti`, `session_id`, and `family_id` are checked first
- Redis authority lives under `session:{access_jti}` and `refresh_family:{family_id}`
- `session_full:{access_jti}` is only a derived cache after session/family/user checks pass
- root/admin/consumer handled differently

### What can go stale

- `/auth/validate` returns the validated access session payload and cached `user_group_names`
- admin guard behavior that relies on session-derived permission snapshots can lag behind configuration changes
- refresh with `refresh_token`, switch-project with access+refresh credentials, or full re-login recreates session context from current DB state

### What is recalculated

For consumer sessions, `validate_session()` recalculates:

- project group membership in the current project
- role-derived permissions via `get_user_permissions()`

This remains different from the extended three-source query used by
`/permissions/users/me/...`.

---

## `require_permission()` Middleware Behavior

`src/middleware/authentication.py` defines `require_permission(permission)`.

Behavior:

1. allow if the permission name is already in `current_user["permissions"]`
2. allow if session permissions include `admin` or `global_admin`
3. for `consumer` users only, fall back to
   `check_user_permission(user_id, project_id, permission)`
4. otherwise return HTTP 403

Two important caveats:

- `require_permission()` is **currently not used by any route file found in this repo search**
- despite accepting `project_id`, its current alias resolves global
  role-derived permissions and does not evaluate the SQL project-scoped deny
  model

The middleware exists but is not the active enforcement pattern for the
permissions suite.

---

## Catalog Metadata vs Actual Authorization

Both route files are explicit about this:

- permission-group project catalog = **metadata only**
- role project catalog = **metadata only**

What catalogs do:

- attach descriptive metadata to project/role or project/permission-group pairings
- support UI suggestion or operator organization workflows

What catalogs do NOT do:

- grant access
- deny access
- limit which role can be assigned
- limit which permission group can be assigned

Authorization still comes from the live assignment tables and permission resolution procedures.

---

## Legacy Project-Scoped Permission Model vs Current Global Model

This repo still contains older or partially parallel artifacts:

- `Permission` and `PermissionGroup` models in `src/Util/Models.py` still carry `project_id`
- `UserProjectPermissionGroup` also carries `project_id`
- schema includes `user_group_project_group_permissions`
- views include `v_user_scoped_permissions` and `v_user_project_scoped_roles`

But the active public route layer documented here uses:

- `global_permissions`
- `global_permission_groups`
- global role assignment
- metadata-only project catalogs

So the honest repo-specific statement is:

- **current public permission CRUD is global**
- **legacy/scoped structures still exist in schema and models**
- **the migration boundary is not fully cleaned up**

Do not sell this as a perfectly pure system. It isn't.

---

## AUTHZ Error Context You Will See Around Permissions

The shared error codes define these authorization families:

| Code | Meaning |
|------|---------|
| `AUTHZ_2001` | Access denied |
| `AUTHZ_2002` | Insufficient permissions |
| `AUTHZ_2003` | Project access denied |
| `AUTHZ_2004` | Group access denied |
| `AUTHZ_2005` | Resource access denied |
| `AUTHZ_2006` | Role assignment denied |
| `AUTHZ_2007` | Permission denied |
| `AUTHZ_2008` | API key has no access to the requested project |

In the permissions area, permission-guard failures usually map to `AUTHZ_2002`, while project-scoping and assigned-project problems surface through `AUTHZ_2003` or `AUTHZ_2008` depending on whether the request is session-authenticated or API-key-authenticated.

---

## Related Documentation

- **[Permissions Overview](README.md)**
- **[Usage](usage.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Document Version**: 1.0
