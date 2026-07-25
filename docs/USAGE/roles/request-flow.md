# Roles Request and Data Flow

End-to-end runtime flows for the global roles system in `api.auth`.

---

## Flow 1: Create a Role

Auth gate details are covered in the canonical permissions flow: **[Flow 3: Writing Through the `/roles` API](../permissions/request-flow.md#flow-3-writing-through-the-roles-api)**.

After the guard passes:

1. Validate required fields: `role_name`, `role_display_name`
2. Validate optional `role_priority` is in range 0-100
3. Generate `role_hash` and `role_id`
4. Call `sp_global_create_role` → INSERT into `roles`
5. If `role_name` already exists → DB `IntegrityError` → wrapped to 409 `ConflictError`
6. Return 201 Created with role object

---

## Flow 2: Attach Permission Groups to a Role

This is a multi-step process that builds the permission chain:

```
Step 1: Create permission (if not exists)
  POST /roles/permissions
    └─► require_admin → sp_global_create_permission

Step 2: Create permission group (if not exists)
  POST /roles/permission-groups
    └─► require_admin → sp_global_create_permission_group

Step 3: Add permission to permission group
  POST /roles/permission-groups/PG_HASH/permissions/PERM_HASH
    └─► require_admin → sp_global_add_permission_to_group

Step 4: Attach permission group to role
  POST /roles/roles/ROLE_HASH/permission-groups/PG_HASH
    └─► require_admin → sp_global_assign_permission_group_to_role
          └─► INSERT INTO role_permission_groups (ON DUPLICATE KEY UPDATE — reactivates if soft-deleted)
```

**Removal caveat:** `DELETE /roles/roles/{role_hash}/permission-groups/{group_hash}` removes (soft-deletes) the junction row. If the group is **not currently assigned** to the role, the handler in `src/routes/global_roles.py` tries to raise `NotFoundError(error_code=ErrorCode.NOT_FOUND)`, but `NOT_FOUND` is **absent from the `ErrorCode` enum**, so that "not assigned" branch surfaces as a **500** instead of a clean **404**. See [troubleshooting.md](troubleshooting.md#removing-an-already-removed-linkcatalog-entry-returns-500-instead-of-404).

The full chain after all four steps:

```
ROLE → role_permission_groups → global_permission_groups → global_permission_group_permissions → global_permissions
```

---

## Flow 3: Assign a Role to a User

```
PUT /roles/users/{user_hash}/role
  └─► global_roles.require_admin
        └─► (same auth gate as Flow 1)
```

After the guard passes:

1. Validate target user exists (including inactive users)
2. **BLOCK** if user is inactive → 403 `ACCOUNT_INACTIVE`
3. Validate role exists via `role_hash`
4. Call `sp_global_assign_role_to_user` → `UPDATE users SET role_id = ? WHERE id = ?`
5. Return user info + assigned role info

**Important:** this replaces any existing role. Users have exactly one `role_id`.

### Session impact

- The user's current session still contains permissions from their **previous** role
- The new role's permissions take effect only after re-login, refresh, or project switch
- `GET /permissions/users/me/permissions` will reflect the new role immediately (fresh DB query)

---

## Flow 4: Inspect Current User's Role

```
GET /roles/users/me/role
  └─► require_valid_session (any authenticated user)
        └─► sp_global_get_user_role(user_id)
              └─► SELECT from roles WHERE id = users.role_id AND is_active = TRUE
```

- Returns `null` role if `users.role_id` is NULL
- Returns `null` role if the assigned role is soft-deleted (`is_active = FALSE`)
- Returns 403 if the requesting user is inactive

---

## Flow 5: Remove a User's Role

```
DELETE /roles/users/{user_hash}/role
  └─► global_roles.require_admin
        └─► (same auth gate as Flow 1)
```

After the guard passes:

1. Validate target user exists
2. **BLOCK** if user is inactive → 403 `ACCOUNT_INACTIVE`
3. Read current `role_id` (to return `previous_role` in response)
4. Call `sp_global_remove_role_from_user` → `UPDATE users SET role_id = NULL WHERE id = ?`
5. Return user info + `previous_role`

---

## Flow 6: Delete a Role

```
DELETE /roles/roles/{role_hash}
  └─► global_roles.require_admin
        └─► (same auth gate as Flow 1)
```

After the guard passes:

1. Look up role by hash
2. **INTENDED BLOCK** if `is_system_role = TRUE`; current code references missing `ErrorCode.OPERATION_NOT_ALLOWED`, so this path surfaces as generic 500 until the enum/source is fixed
3. Call `sp_global_delete_role` → `UPDATE roles SET is_active = FALSE WHERE id = ?`
4. Return success message

**What does NOT happen:**
- `users.role_id` is NOT cleared — users retain the FK reference
- `role_permission_groups` rows are NOT deleted — they remain as soft-deleted rows
- `role_project_catalog` rows are NOT deleted

---

## Flow 7: Project Catalog Operations

### Add role to project catalog

```
POST /roles/projects/{project_hash}/catalog/roles/{role_hash}
  └─► global_roles.require_admin
        └─► resolve project + role
              └─► INSERT INTO role_project_catalog
                    └─► duplicate → 500 (defect: see below)
```

**Defect caveat:** the duplicate-add branch in `src/routes/global_roles.py` raises `ConflictError(error_code=ErrorCode.ALREADY_EXISTS)`, but `ALREADY_EXISTS` is **absent from the `ErrorCode` enum**. Referencing it raises `AttributeError` before the `ConflictError` is built, so the request surfaces as a generic **500 INTERNAL_ERROR** rather than the intended **409 ConflictError**. This will become a clean 409 only once the enum member or handler is fixed. Mirrors the note in [usage.md](usage.md#project-role-catalog).

### List cataloged roles

```
GET /roles/projects/{project_hash}/catalog/roles
  └─► require_valid_session (any authenticated user)
        └─► SELECT from role_project_catalog JOIN roles
```

### Remove role from project catalog

```
DELETE /roles/projects/{project_hash}/catalog/roles/{role_hash}
  └─► global_roles.require_admin
        └─► DELETE from role_project_catalog
              └─► not in catalog → 500 (defect: see below)
```

**Removal caveat:** the "role is not in the project catalog" branch in `src/routes/global_roles.py` raises `NotFoundError(error_code=ErrorCode.NOT_FOUND)`, but `NOT_FOUND` is **absent from the `ErrorCode` enum**, so removing a role that was never cataloged (or already removed) surfaces as a **500** rather than the intended **404**. See [troubleshooting.md](troubleshooting.md#removing-an-already-removed-linkcatalog-entry-returns-500-instead-of-404).

**None of these flows affect authorization.** They are purely organizational metadata. See also the parallel permission-group catalog flow in **[Flow 8: Catalog Metadata Flow](../permissions/request-flow.md#flow-8-catalog-metadata-flow)**.

---

## Flow 8: Permission Source Breakdown

See the canonical cross-module flow: **[Flow 6: Permission Source Breakdown](../permissions/request-flow.md#flow-6-permission-source-breakdown)** in the permissions docs.

The role source rows returned by that endpoint trace through `users.role_id → roles → role_permission_groups → ...`.

---

## Flow 9: Session Refresh After Role Changes

See the canonical flow: **[Flow 7: Session Refresh / Re-login After Changes](../permissions/request-flow.md#flow-7-session-refresh--re-login-after-changes)** in the permissions docs.

Role assignment follows the same pattern: `GET /permissions/users/me/permissions` sees fresh state immediately, but the session payload needs a refresh/re-login to reflect the new role.

---

## Related Documentation

- **[Roles Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**
- **[Permission Resolution](../permissions/resolution.md)** — Auth vs inspection resolution paths

---

**Document Version**: 1.1
