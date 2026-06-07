# Roles Endpoint and Operational Reference

Reference for the roles-related API surface in `api.auth`.

---

## Role CRUD

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/roles/roles` | POST | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | Form | Create role |
| `/roles/roles` | GET | Valid session | Query params | List roles (ordered by priority DESC, name ASC) |
| `/roles/roles/{hash}` | GET | Valid session | — | Get role details + linked permission groups |
| `/roles/roles/{hash}` | PUT | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | Form | Update role metadata (partial) |
| `/roles/roles/{hash}` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | — | Soft-delete role (blocked for system roles) |

---

## Role ↔ Permission Group

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/roles/roles/{hash}/permission-groups/{pg_hash}` | POST | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | — | Attach permission group to role (reactivates if soft-deleted) |
| `/roles/roles/{hash}/permission-groups` | GET | Valid session | — | List role's permission groups |
| `/roles/roles/{hash}/permission-groups/{pg_hash}` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | — | Remove permission group from role (soft delete) |

---

## Permission Group CRUD

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/roles/permission-groups` | POST | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | Form | Create permission group |
| `/roles/permission-groups` | GET | Valid session | Query params | List permission groups (optional `category` filter) |
| `/roles/permission-groups/{hash}` | GET | Valid session | — | Get permission group details + linked permissions |
| `/roles/permission-groups/{hash}` | PUT | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | Form | Update permission group |
| `/roles/permission-groups/{hash}` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | — | Soft-delete permission group |

---

## Permission Group ↔ Permission

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/roles/permission-groups/{hash}/permissions/{perm_hash}` | POST | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | — | Add permission to group |
| `/roles/permission-groups/{hash}/permissions` | GET | Valid session | — | List permissions in group |
| `/roles/permission-groups/{hash}/permissions/{perm_hash}` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | — | Remove permission from group |

---

## Permission CRUD

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/roles/permissions` | POST | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | Form | Create permission |
| `/roles/permissions` | GET | Valid session | Query params | List permissions |
| `/roles/permissions/{hash}` | GET | Valid session | — | Get permission details |
| `/roles/permissions/{hash}` | PUT | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | Form | Update permission |
| `/roles/permissions/{hash}` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | — | Soft-delete permission |

---

## User Role Assignment

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/roles/users/me/role` | GET | Valid session | — | Get current user's role (null if none) |
| `/roles/users/{user_hash}/role` | PUT | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | Form | Assign role to user (replaces existing) |
| `/roles/users/{user_hash}/role` | GET | Valid session | — | Get any user's role |
| `/roles/users/{user_hash}/role` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | — | Remove role from user (sets role_id = NULL) |

---

## Project Role Catalog (Metadata Only)

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/roles/projects/{hash}/catalog/roles/{role_hash}` | POST | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | Form | Add role to project catalog |
| `/roles/projects/{hash}/catalog/roles` | GET | Valid session | — | List cataloged roles for project |
| `/roles/projects/{hash}/catalog/roles/{role_hash}` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via **role-only** check | — | Remove role from project catalog |

---

## Bulk Role Assignment (BROKEN)

| Endpoint | Method | Auth | Content Type | Purpose |
|----------|--------|------|--------------|---------|
| `/admin/projects/{hash}/bulk-assign-roles` | POST | Admin | Form | Bulk assign roles to project users |

**This endpoint does not work.** There is a parameter mismatch between the route and the utility function. See [troubleshooting.md](troubleshooting.md#bulk-role-assignment-always-fails).

---

## Operational Notes

### Request Shapes

- All write operations under `/roles` use **form data** (`multipart/form-data` via `Form(...)`)
- Read operations use path params or query params
- No JSON bodies in this module

### Pagination

- `limit`: 1-100, default 50
- `offset`: default 0
- **Caveat:** `total` in list responses is `len(results)` — the page count, NOT the global DB total. Clients cannot calculate total pages from this value.

### Guard Differences

See the canonical explanation in **[Permissions Reference → Guard differences](../permissions/reference.md#guard-differences)**. In short: `/roles` write routes use a narrower role-only `manage_roles` fallback, while `/permissions` admin routes use the extended three-source check.

### Soft Delete Behavior

- Role deletion: `is_active = FALSE`
- Permission group removal from role: `is_active = FALSE, removed_at = NOW()` on junction row
- No cascade on role deletion — user FK references and junction rows persist

### Error Responses

| Status | Error Code | When |
|--------|-----------|------|
| 401 | `SESSION_INVALID` | Invalid/expired session token |
| 403 | `INSUFFICIENT_PERMISSIONS` | Non-admin without `manage_roles` |
| 403 | `ACCOUNT_INACTIVE` | Target user is inactive (role assignment) |
| 500 | `INTERNAL_ERROR` | Current code defect: system-role delete references missing `ErrorCode.OPERATION_NOT_ALLOWED` instead of returning the intended 403 |
| 404 | `ROLE_NOT_FOUND` | Role hash not found |
| 500 | `INTERNAL_ERROR` | Current code defect: permission-group not-found paths reference missing `ErrorCode.PERMISSION_GROUP_NOT_FOUND` |
| 404 | `USER_NOT_FOUND` | User hash not found |
| 404 | `PROJECT_NOT_FOUND` | Project hash not found (catalog endpoints) |
| 409 | `DUPLICATE_ENTRY` | Duplicate role name through DB conflict handling |
| 500 | `INTERNAL_ERROR` | Current code defect: duplicate project-catalog entry references missing `ErrorCode.ALREADY_EXISTS` |
| 500 | `INTERNAL_ERROR` | DB operation failed |

---

## Related Documentation

- **[Roles Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Troubleshooting](troubleshooting.md)**
- **[Permissions Reference](../permissions/reference.md)** — Extended permission assignment endpoints

---

**Last Updated**: April 2026  
**Document Version**: 1.0
