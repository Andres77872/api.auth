# Roles Architecture

Technical architecture of the global roles system as it actually exists in `api.auth`.

---

## Data Model

### `roles` Table

| Column | Type | Constraints | Default | Notes |
|--------|------|-------------|---------|-------|
| `id` | VARCHAR(64) | PK | — | Format: `role_<16 hex chars>` |
| `role_hash` | VARCHAR(255) | UNIQUE | — | SHA256-based, 32 chars |
| `role_name` | VARCHAR(100) | UNIQUE, NOT NULL | — | Machine-readable, immutable after creation |
| `role_display_name` | VARCHAR(255) | NOT NULL | — | Human-readable label |
| `role_description` | TEXT | NULLABLE | — | Optional description |
| `role_priority` | INT | NOT NULL | 50 | Range 0-100, used for `ORDER BY` only |
| `is_system_role` | BOOLEAN | NOT NULL | FALSE | Protects from deletion |
| `is_active` | BOOLEAN | NOT NULL | TRUE | Soft delete flag |
| `created_at` | DATETIME | NOT NULL | NOW() | — |
| `updated_at` | DATETIME | NULLABLE | — | — |
| `created_by` | VARCHAR(64) | NULLABLE | — | User ID of creator |

### Hash Generation

- `role_hash`: `sha256("role:{role_name}:{timestamp}")[:32]` — deterministic per name + timestamp
- `role_id`: `role_{sha256("role:{timestamp}")[:16]}`

### Related Tables

| Table | Purpose |
|-------|---------|
| `roles` | Global role definitions |
| `role_permission_groups` | Junction: role ↔ permission group (supports soft delete) |
| `global_permission_groups` | Permission group definitions with categories |
| `global_permission_group_permissions` | Junction: permission group ↔ permission (supports soft delete) |
| `global_permissions` | Individual permission definitions |
| `role_project_catalog` | Junction: role ↔ project (METADATA ONLY) |
| `users.role_id` | FK to `roles.id` — one role per user |

---

## Route Organization

All 28 role-related endpoints live in **one file**: `src/routes/global_roles.py` (1066 lines).

| Section | Lines | Endpoints |
|---------|-------|-----------|
| Role CRUD | 100-234 | POST/GET/PUT/DELETE `/roles/roles` + `/roles/roles/{hash}` |
| Role ↔ Permission Group | 241-348 | POST/GET/DELETE `/roles/roles/{hash}/permission-groups` |
| Permission Group CRUD | 355-493 | Full CRUD on `/roles/permission-groups` + permissions sub-routes |
| Permission CRUD | 614-746 | Full CRUD on `/roles/permissions` |
| User Role Assignment | 754-905 | GET `/roles/users/me/role`, PUT/GET/DELETE `/roles/users/{hash}/role` |
| Project Catalog | 912-1066 | POST/GET/DELETE `/roles/projects/{hash}/catalog/roles` |

Router prefix: `/roles`
OpenAPI tag: "Global Role System"

**Related module:** `src/routes/permission_assignments.py` (765 lines, prefix `/permissions`) handles the SECONDARY permission assignment model (permission groups → user groups/users directly). This is a separate authorization path.

---

## Entity Relationships

```
users.role_id ──→ roles.id
                      │
                      ├──→ role_permission_groups ──→ global_permission_groups ──→ global_permission_group_permissions ──→ global_permissions
                      │
                      └──→ role_project_catalog ──→ projects  (METADATA ONLY)

user_groups ──→ user_group_permission_groups ──→ global_permission_groups  (independent of roles)
users ──→ user_permission_groups ──→ global_permission_groups  (direct assignment, independent of roles)

user_groups ──→ user_group_project_group_roles ──→ roles  (project-scoped roles, separate system)
```

| Relationship | Table | Type | Notes |
|-------------|-------|------|-------|
| User → Role | `users.role_id` | 1:1 (nullable) | Each user has ONE global role |
| Role → Permission Groups | `role_permission_groups` | M:N | Junction with soft delete |
| Permission Group → Permissions | `global_permission_group_permissions` | M:N | Junction with soft delete |
| Role → Project (catalog) | `role_project_catalog` | M:N | METADATA ONLY, not auth |
| User Group → Role (scoped) | `user_group_project_group_roles` | M:N | Project-scoped roles, separate from global |

---

## Auth Guards

### `require_admin` in `global_roles.py` (lines 47-82)

```
require_admin(session_data)
  ├─► allow if user_type in {root, admin}
  └─► if user_type == consumer:
        └─► check_user_has_permission(user_id, "manage_roles")
              └─► sp_global_check_user_has_permission (ROLE-ONLY)
```

**Critical:** this uses the **role-only** permission check. A consumer with `manage_roles` granted via user-group assignment or direct assignment would be **DENIED** here, even though they have the permission.

### `require_admin` in `permission_assignments.py` (lines 69-89)

```
require_admin(session_data)
  ├─► allow if user_type in {root, admin}
  └─► if user_type == consumer:
        └─► check_user_has_permission_extended(user_id, "manage_roles")
              └─► extended check (ROLE + USER-GROUP + DIRECT)
```

**This is an inconsistency.** The two modules use different permission check functions, leading to different behavior for consumer users with `manage_roles` via user groups.

### Read endpoints

Most GET endpoints only require a valid session (any authenticated user). They do not check permissions.

---

## Permission Resolution Paths

There are **two** permission resolution paths in this system. The full explanation — including the critical auth-vs-inspection gap, practical examples, and known limitations — lives in **[../permissions/resolution.md](../permissions/resolution.md)**.

Summary:

- **Path A (Auth/Session)**: `sp_global_get_user_permissions` resolves **role only**. Used during login, session creation, and `validate_session`.
- **Path B (Inspection)**: `sp_get_user_all_permissions` resolves **all three sources** (role + user-group + direct). Used by `GET /permissions/users/me/permissions`.

The gap means permissions assigned via user groups or directly to users are visible through inspection endpoints but **not** enforced during authentication.

---

## Session and Cache Behavior

- Role assignment changes do **not** automatically invalidate existing sessions
- The session payload embeds role-derived permissions at login time
- After role changes, the user must re-login, refresh, or switch project to get updated session permissions
- Self-query endpoints (`/permissions/users/me/...`) resolve fresh from the DB and reflect changes immediately

---

## Soft Delete Behavior

- Role deletion sets `is_active = FALSE`
- Permission group removal from role sets `is_active = FALSE, removed_at = NOW()` on the junction row
- **No cascade:** deleting a role does NOT clear `users.role_id` — users retain a reference to a soft-deleted role
- The `sp_global_get_user_role` SP checks `r.is_active = TRUE`, so it returns NULL for soft-deleted roles, but the FK reference persists in the DB

---

## Important Caveats

### `role_priority` is ordering metadata, not permission precedence

- Used only in `ORDER BY role_priority DESC, role_name ASC` for list queries
- Does NOT affect which permissions take effect
- Does NOT influence auth-time resolution

### `role_name` is immutable

- The UPDATE stored procedure does not include `role_name`
- Once created, a role's machine-readable name cannot be changed

### `is_system_role` is not settable via API

- The create endpoint does not expose `is_system_role`
- System roles must be created via direct DB access
- System roles are intended to be blocked from API deletion, but the current route references missing `ErrorCode.OPERATION_NOT_ALLOWED`; until the enum/source is fixed, that path surfaces as a generic 500 rather than a clean 403

### Missing `ErrorCode` members cause 500s on several branches

`global_roles.py` references four `ErrorCode` members that are **absent from the `ErrorCode` enum** in `src/Util/error_handler.py`. Because the code reads the enum attribute while constructing the error, the missing attribute raises `AttributeError` and the request surfaces as a generic **500 INTERNAL_ERROR** instead of the intended status:

| Missing member | Referenced at | Intended status |
|----------------|---------------|-----------------|
| `OPERATION_NOT_ALLOWED` | line 222 (system-role delete) | 403 |
| `PERMISSION_GROUP_NOT_FOUND` | lines 260, 329, 419, 445, 478, 511, 557, 581 (permission-group not-found lookups) | 404 |
| `ALREADY_EXISTS` | line 959 (duplicate project-catalog add) | 409 |
| `NOT_FOUND` | lines 341, 600, 1051 (unlink / catalog-removal "not assigned" branches) | 404 |

Note that `ErrorCode.NOT_FOUND` must not be confused with `ErrorCategory.NOT_FOUND` (which does exist); only the `ErrorCode` member is missing. These are runtime defects, not documented behaviors — see [troubleshooting.md](troubleshooting.md) and [reference.md](reference.md#error-responses).

### Project catalog is metadata only

- Catalog endpoints have `"note": "This is METADATA ONLY"` in responses
- Cataloging a role does NOT restrict which roles can be assigned to users
- Any role can be assigned to any user regardless of project catalog entries

### Category is not DB-enforced

- `group_category` accepts any string at the DB level
- API documentation says `general, admin, api, data` but nothing prevents other values

---

## Related Documentation

- **[Roles Overview](README.md)**
- **[Usage](usage.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**
- **[Permission Resolution](../permissions/resolution.md)** — The critical auth-vs-inspection gap
- **[Permissions Suite](../permissions/README.md)** — Extended permission resolution and assignment paths

---

**Last Updated**: June 2026  
**Document Version**: 1.1
