# Roles Usage

Practical usage guide for operating the global roles system in `api.auth`.

---

## Table of Contents

- [Authentication and Route Ownership](#authentication-and-route-ownership)
- [Creating Roles](#creating-roles)
- [Reading Roles](#reading-roles)
- [Updating Roles](#updating-roles)
- [Deleting Roles](#deleting-roles)
- [Permission Group Management](#permission-group-management)
- [Permission Management](#permission-management)
- [User Role Assignment](#user-role-assignment)
- [Project Role Catalog](#project-role-catalog)

---

## Authentication and Route Ownership

All role-related endpoints live in a single route file:

| Concern | Route Prefix | Auth Gate |
|---------|-------------|-----------|
| Role CRUD | `/roles/roles` | Admin (root/admin) or consumer with `manage_roles` via **role-only** check |
| Role ↔ Permission Group | `/roles/roles/{hash}/permission-groups` | Same as above |
| Permission Group CRUD | `/roles/permission-groups` | Same as above |
| Permission CRUD | `/roles/permissions` | Same as above |
| User Role Assignment | `/roles/users/{hash}/role`, `/roles/users/me/role` | Admin for writes, any valid session for reads |
| Project Role Catalog | `/roles/projects/{hash}/catalog/roles` | Admin for writes, any valid session for reads |

**Important:** all write endpoints use `multipart/form-data` via FastAPI `Form(...)`. Sending `application/json` returns 422.

**Auth gate caveat:** the `require_admin` guard in `global_roles.py` uses `check_user_has_permission()` which is the **role-only** resolver. A consumer with `manage_roles` granted via user-group assignment would be **denied** here. See [architecture.md](architecture.md#auth-guards) for details.

---

## Creating Roles

```bash
curl -X POST "http://localhost:8000/roles/roles" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_name=editor&role_display_name=Content Editor&role_description=Can create and edit content&role_priority=60"
```

**Required fields:**
- `role_name` — unique machine-readable identifier (max 100 chars)
- `role_display_name` — human-readable label (max 255 chars)

**Optional fields:**
- `role_description` — free text description
- `role_priority` — integer 0-100, default 50 (used for ordering only)

**What this does:**
- Creates a row in `roles` with `is_system_role = FALSE` and `is_active = TRUE`
- Generates `role_hash` (SHA256-based, 32 chars) and `role_id` (`role_` + 16 hex chars)
- Returns 201 Created

**Constraints:**
- `role_name` must be unique (DB constraint `uk_role_name`)
- Duplicate name returns 409 `ConflictError`
- `is_system_role` is **not** exposed in the API — always `FALSE` for user-created roles

---

## Reading Roles

### List all roles

```bash
curl -X GET "http://localhost:8000/roles/roles?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

- Ordered by `role_priority DESC, role_name ASC`
- Pagination: `limit` (1-100, default 50), `offset` (default 0)
- **Caveat:** `total` in the response is `len(roles)` — the page count, NOT the global total. See [troubleshooting.md](troubleshooting.md#pagination-total-is-wrong).

### Get a single role

```bash
curl -X GET "http://localhost:8000/roles/roles/ROLE_HASH" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Returns the role object **plus** an array of linked `permission_groups`.

---

## Updating Roles

```bash
curl -X PUT "http://localhost:8000/roles/roles/ROLE_HASH" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_display_name=Senior Editor&role_priority=70"
```

- All fields are optional (partial update)
- Uses `COALESCE` — omitted fields retain current values
- **`role_name` CANNOT be changed** — not included in the UPDATE stored procedure
- Returns the updated role via a second DB fetch

---

## Deleting Roles

```bash
curl -X DELETE "http://localhost:8000/roles/roles/ROLE_HASH" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

- **SOFT DELETE** — sets `is_active = FALSE`
- **INTENDED BLOCK** if `is_system_role = TRUE` — current code references missing `ErrorCode.OPERATION_NOT_ALLOWED`, so this path currently surfaces as generic 500 until the enum/source is fixed
- Does **NOT** cascade-delete user role assignments — `users.role_id` remains pointing to the deleted role
- Does **NOT** remove permission group assignments from `role_permission_groups`

**After deletion:**
- The role disappears from list queries (filtered by `is_active = TRUE`)
- `GET /roles/roles/{hash}` returns whatever `get_role_by_hash` yields — the route handler does not filter on `is_active`, so a direct fetch by hash can still return a soft-deleted role
- Users with this role assigned will see `null` when querying their role via `GET /roles/users/me/role` (the SP checks `is_active`)

---

## Permission Group Management

Permission groups are the bridge between roles and individual permissions.

### Create a permission group

```bash
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=data_readers&group_display_name=Data Readers&group_category=general&group_description=Read-only data access"
```

### Attach a permission group to a role

```bash
curl -X POST "http://localhost:8000/roles/roles/ROLE_HASH/permission-groups/PG_HASH" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

- Uses `ON DUPLICATE KEY UPDATE` — reactivates if previously soft-deleted

### Remove a permission group from a role

```bash
curl -X DELETE "http://localhost:8000/roles/roles/ROLE_HASH/permission-groups/PG_HASH" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

- **SOFT DELETE** — sets `is_active = FALSE, removed_at = NOW()` on the junction row
- **Defect:** if the group is **not currently assigned** to the role, the handler references the missing `ErrorCode.NOT_FOUND`, so that branch surfaces as a generic 500 instead of the intended 404. See [troubleshooting.md](troubleshooting.md#removing-an-already-removed-linkcatalog-entry-returns-500-instead-of-404).

### List permission groups

```bash
curl -X GET "http://localhost:8000/roles/permission-groups?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

- Optional `category` filter: `general`, `admin`, `api`, `data`
- **Caveat:** `total` is page count, not DB total

### Get a permission group with its permissions

```bash
curl -X GET "http://localhost:8000/roles/permission-groups/PG_HASH" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

Returns the group plus an array of linked `permissions`.

---

## Permission Management

Individual permissions are the leaf nodes of the authorization tree.

### Create a permission

```bash
curl -X POST "http://localhost:8000/roles/permissions" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_name=read_data&permission_display_name=Read Data&permission_description=Read access to project data&permission_category=data"
```

- `permission_category` is optional and defaults to `general`

### Add a permission to a permission group

```bash
curl -X POST "http://localhost:8000/roles/permission-groups/PG_HASH/permissions/PERM_HASH" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

### Remove a permission from a permission group

```bash
curl -X DELETE "http://localhost:8000/roles/permission-groups/PG_HASH/permissions/PERM_HASH" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

- **Defect:** if the permission is **not currently assigned** to the group, the handler references the missing `ErrorCode.NOT_FOUND`, so that branch surfaces as a generic 500 instead of the intended 404. See [troubleshooting.md](troubleshooting.md#removing-an-already-removed-linkcatalog-entry-returns-500-instead-of-404).

### List / get / update / delete permissions

Standard CRUD on `/roles/permissions` and `/roles/permissions/{hash}`. All follow the same patterns as role CRUD.

---

## User Role Assignment

### Check my own role

```bash
curl -X GET "http://localhost:8000/roles/users/me/role" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

- Returns `null` role if `users.role_id` is NULL
- Returns 403 if user is inactive

### Assign a role to a user

```bash
curl -X PUT "http://localhost:8000/roles/users/USER_HASH/role" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_hash=ROLE_HASH"
```

- User must be active — blocked with 403 `ACCOUNT_INACTIVE` if inactive
- Replaces any existing role (one role per user)
- Returns user info plus assigned role info
- The API accepts public `role_hash`; internally the route resolves it to the role's numeric `id` before updating `users.role_id`

### Get another user's role

```bash
curl -X GET "http://localhost:8000/roles/users/USER_HASH/role" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

- Any authenticated user can look up ANY user's role (not just their own)

### Remove a user's role

```bash
curl -X DELETE "http://localhost:8000/roles/users/USER_HASH/role" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

- Sets `users.role_id = NULL`
- Returns `previous_role` in the response
- Blocked if user is inactive

### Bulk role assignment (BROKEN)

The endpoint `POST /admin/projects/{hash}/bulk-assign-roles` **does not work**. There is a parameter mismatch between the route and the utility function. See [troubleshooting.md](troubleshooting.md#bulk-role-assignment-always-fails).

---

## Project Role Catalog

**These endpoints are METADATA ONLY.** They do not restrict role assignment or affect authorization.

### Add a role to a project's catalog

```bash
curl -X POST "http://localhost:8000/roles/projects/PROJ_HASH/catalog/roles/ROLE_HASH" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "catalog_purpose=Recommended for project editors&notes=Metadata only"
```

- Returns a `"note"` field in the response: `"This is METADATA ONLY"`
- `catalog_purpose` and `notes` are optional metadata fields
- Duplicate catalog entry currently references missing `ErrorCode.ALREADY_EXISTS`, so that path surfaces as generic 500 until the enum/source is fixed

### List cataloged roles for a project

```bash
curl -X GET "http://localhost:8000/roles/projects/PROJ_HASH/catalog/roles" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Remove a role from a project's catalog

```bash
curl -X DELETE "http://localhost:8000/roles/projects/PROJ_HASH/catalog/roles/ROLE_HASH" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

- **Defect:** if the role is **not in the project catalog** (never added, or already removed), the handler references the missing `ErrorCode.NOT_FOUND`, so that branch surfaces as a generic 500 instead of the intended 404. See [troubleshooting.md](troubleshooting.md#removing-an-already-removed-linkcatalog-entry-returns-500-instead-of-404).

---

## Related Documentation

- **[Roles Overview](README.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**
- **[Permission Resolution](../permissions/resolution.md)** — The critical auth-vs-inspection gap
- **[Permissions Suite](../permissions/README.md)** — Permission groups, assignments, and extended resolution

---

**Last Updated**: June 2026  
**Document Version**: 1.1
