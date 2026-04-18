# Roles Troubleshooting, Caveats, and Best Practices

Things that commonly confuse operators working with the global roles system in `api.auth`.

---

## Troubleshooting

### User has permissions visible via `/permissions/me` but they don't work during auth

This is the most critical caveat in the system.

The auth/session flow uses **ROLE-ONLY** permission resolution:

```
users → roles → role_permission_groups → global_permission_group_permissions → global_permissions
```

The inspection endpoint `GET /permissions/users/me/permissions` uses **COMPREHENSIVE** resolution:

```
UNION of:
  1. role → permissions
  2. user-group → permissions
  3. direct user → permissions
```

If a user has permissions from user-group or direct assignment, those show up in `/permissions/me` but are **NOT** recognized during login, session validation, or route authorization.

**Fix:** assign the needed permissions through the user's role instead. Or use the inspection endpoints for audit purposes only.

See [../permissions/resolution.md](../permissions/resolution.md) for the full explanation.

---

### Bulk role assignment always fails

The endpoint `POST /admin/projects/{hash}/bulk-assign-roles` has a parameter mismatch:

- The route passes `role_name` to the utility function
- The utility function expects `role_id`
- The utility does `assignment.get('role_id')` which returns `None`
- Every assignment fails with "Missing user_hash or role_id"

**Workaround:** assign roles individually via `PUT /roles/users/{user_hash}/role`.

---

### Pagination total is wrong

List endpoints for roles, permission groups, and permissions return:

```json
{
  "total": 10,
  "limit": 50,
  "offset": 0
}
```

The `total` value is `len(results)` — the number of items in the current page, NOT the total count in the database. If you request 10 items and get 10, `total` is 10 even if there are 500 roles in the DB.

**Impact:** clients cannot calculate total pages or know if more data exists beyond the current page.

**Workaround:** paginate with increasing offsets until you get fewer results than your limit.

---

### Deleted role still shows in user's data

When you soft-delete a role:

- `users.role_id` is **NOT** cleared — the FK reference persists
- `GET /roles/users/me/role` returns `null` because the stored procedure checks `is_active = TRUE`
- But the DB row still points to the deleted role

**Fix:** manually clear the user's `role_id` after deleting their role:

```bash
curl -X DELETE "http://localhost:8000/roles/users/usr-abc123/role" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### Admin route works in `/permissions` but not in `/roles`

The two modules use different permission check functions:

- `/roles` uses `check_user_has_permission()` → role-only resolver
- `/permissions` uses `check_user_has_permission_extended()` → three-source resolver

If a consumer user has `manage_roles` via user-group assignment:
- They **CAN** access `/permissions/admin/...` endpoints
- They **CANNOT** access `/roles/roles` write endpoints

**Fix:** ensure the consumer's assigned role (not user-group) includes `manage_roles` if they need to operate the `/roles` API.

---

### Cannot change a role's name

The UPDATE stored procedure does not include `role_name`. Once a role is created, its machine-readable name is permanent.

**Workaround:** create a new role with the desired name, migrate users to it, then soft-delete the old role.

---

### Cannot create system roles via API

The `is_system_role` field is not exposed in the create endpoint. All user-created roles have `is_system_role = FALSE`.

**Workaround:** system roles must be created via direct database access.

---

### Category accepts any string

The API documentation says `group_category` should be one of `general`, `admin`, `api`, `data`. But the DB does not enforce this — any string is accepted.

**Best practice:** stick to the documented categories for consistency.

---

## Current Caveats

### Role priority is ordering only

`role_priority` (0-100, default 50) is used only for `ORDER BY role_priority DESC, role_name ASC` in list queries. It does NOT affect:

- Permission resolution precedence
- Auth-time behavior
- Which permissions take effect

### One role per user

The `users` table has a single `role_id` column. Users cannot have multiple roles. Assigning a new role replaces the previous one.

### No cascade on role deletion

Deleting a role does NOT:
- Clear `users.role_id` for affected users
- Remove rows from `role_permission_groups`
- Remove rows from `role_project_catalog`

### Session staleness after role changes

After changing a user's role:
- `GET /permissions/users/me/permissions` reflects the change immediately (fresh DB query)
- The session payload still contains permissions from the previous role
- Route authorization based on session permissions may not reflect the change

**Fix:** have the user re-login, refresh, or switch project context.

---

## Best Practices

### 1. Build roles from the bottom up

Always follow the chain: permission → permission group → attach to role → assign to user. Skipping steps creates roles with no effective permissions.

### 2. Use meaningful role names

Role names are immutable. Choose carefully:
- `content_editor` not `role1`
- `data_analyst` not `temp_role`

### 3. Use `role_priority` for UI ordering, not security

Higher priority roles appear first in list queries. Use this for display ordering, not for permission precedence.

### 4. Audit with `/permissions/users/me/permission-sources`

When debugging "why does this user have that permission?", this endpoint breaks down the source of each permission into role, user-group, and direct assignment.

### 5. Plan for session refresh after role changes

After assigning or changing a user's role, communicate that they need to re-login or refresh for the change to take effect in their session.

### 6. Do not rely on bulk role assignment

The endpoint is broken. Use individual assignment or build your own bulk logic.

### 7. Catalog roles for organization, not enforcement

Project role catalogs are useful for UI suggestions and documentation. Do not assume they restrict anything.

### 8. Verify soft deletes did not orphan users

After deleting a role, check if any users still reference it:

```bash
# This returns null for users with soft-deleted roles
curl -X GET "http://localhost:8000/roles/users/usr-abc123/role" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

If it returns null but you know the user had a role, their role was likely soft-deleted. Clear their `role_id` explicitly.

---

## Related Documentation

- **[Roles Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Permission Resolution](../permissions/resolution.md)** — The critical auth-vs-inspection gap
- **[Error Reference](../errors.md)** — All error codes and response shapes

---

**Last Updated**: April 2026  
**Document Version**: 1.0
