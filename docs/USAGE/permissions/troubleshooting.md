# Permissions Troubleshooting, Caveats, and Best Practices

Things that commonly confuse operators working with the permissions system in `api.auth`.

---

## Troubleshooting

### User does not have the permission you expected

Check the full chain, not just one table in your head.

1. Check the user's effective permissions:
   ```bash
   curl -X GET "http://localhost:8000/permissions/users/me/permissions" \
     -H "Authorization: Bearer $USER_TOKEN"
   ```
2. Check where those permissions come from:
   ```bash
   curl -X GET "http://localhost:8000/permissions/users/me/permission-sources" \
     -H "Authorization: Bearer $USER_TOKEN"
   ```
3. If you expect a direct assignment, inspect it explicitly:
   ```bash
   curl -X GET "http://localhost:8000/permissions/users/$USER_HASH/permission-groups" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```
4. If you expect a team assignment, inspect the user group:
   ```bash
   curl -X GET "http://localhost:8000/permissions/admin/user-groups/$GROUP_HASH/permission-groups" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```
5. If you expect a role baseline, inspect the assigned role:
   ```bash
   curl -X GET "http://localhost:8000/roles/users/$USER_HASH/role" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

If the permission is absent from all three sources, the API is correct and your assumption is wrong.

---

### User has the permission in `/permissions/users/me/...` but still gets 403

This usually means you hit a **guard mismatch**, not a missing permission.

Common causes:

1. the target route is guarded by **role-only** `manage_roles`
2. the target route reads **session permissions** instead of the extended union
3. the target route also needs **project access**
4. the user changed role/group state and is still operating with older session context

Check the guard matrix in [architecture.md](architecture.md#admin-guard-matrix).

---

### Changes do not show up immediately

Common causes:

- `/auth/validate` returns login-time session context like cached `user_group_names`
- session cache has not been reconciled yet
- the user changed project context but is still using an older token

Practical fix order:

1. verify the assignment write actually succeeded
2. use `/permissions/users/me/permissions` to verify effective DB resolution
3. run `/auth/refresh`
4. if project-sensitive, run `/auth/switch-project`
5. if needed, re-login completely

---

### Admin route works in `/permissions` but not in `/roles`

That is possible in this repo.

Why:

- `/permissions` admin routes use **extended** `manage_roles`
- `/roles` admin routes use **role-only** `manage_roles`

So a consumer who gains `manage_roles` via user-group or direct assignment may pass one suite and fail the other.

That is not a documentation bug. That's the current implementation.

---

### User-group or project-group admin routes deny access unexpectedly

Those routes are guarded differently again:

- `/admin/user-groups` wants `admin` or `manage_users` in session permissions
- `/admin/project-groups` wants `admin` or `manage_roles` in session permissions

For consumer sessions, those session permissions are rebuilt from the **role-derived** resolver path. So team/direct permission-group assignments are not the safe way to unlock those admin suites.

If you need predictable access there, use an appropriate role baseline or an actual admin user type.

---

### Catalog entry exists but access did not change

Good. That's exactly what the code says should happen.

Catalog routes are metadata only. They organize recommendations; they do not touch the live authorization graph.

If access must change, use:

- role assignment routes
- permission-group-to-role routes
- permission-group-to-user-group routes
- direct permission-group-to-user routes

---

## Current Caveats

### The public route layer is global, but the repo still has scoped permission artifacts

Models, views, and tables still contain project-scoped permission concepts. The active `/roles` and `/permissions` APIs documented here operate on the global permission system.

Treat scoped artifacts as implementation background, not as public operational contracts unless a route actually exposes them.

### `require_permission()` exists but is not the active route pattern here

The middleware helper exists, but current repo search does not show routes using it. Do not write operator expectations around that decorator unless the route you care about actually imports it.

### Duplicate-looking `/permissions/permissions/...` paths are real

Yes, they look ugly. Yes, they are still real route paths.

---

## AUTHZ Error Context

| Code | When you usually see it here |
|------|------------------------------|
| `AUTHZ_2001` | Insufficient permissions on the target endpoint |
| `AUTHZ_2002` | Access denied to project |
| `AUTHZ_2003` | Admin is scoped to assigned projects only |
| `AUTHZ_2004` | Group-scoped access failure |
| `AUTHZ_2005` | Route/resource-specific access failure |
| `AUTHZ_2006` | Role assignment operation denied |
| `AUTHZ_2007` | Permission-specific denial |

Also watch auth-layer codes when debugging session problems:

- `AUTH_1002` — session expired
- `AUTH_1003` — invalid session
- `AUTH_1005` — inactive account

---

## Best Practices

### 1. Use roles for baselines

A role is the cleanest way to express a stable job-function baseline.

### 2. Use user-group assignments for scale

If a whole team needs the same capability, assign the permission group to the user group.

### 3. Use direct assignments for exceptions only

Temporary access, VIP users, migration work, one-off overrides. Nothing more.

### 4. Verify with self-query endpoints

The most trustworthy operator checks are:

- `/permissions/users/me/permissions`
- `/permissions/users/me/permission-sources`
- `/permissions/users/me/permissions/check/{name}`

### 5. Treat catalogs as metadata

If you use catalogs as if they were authorization, you are lying to yourself and to your operators.

### 6. Plan for session refresh after material changes

After role changes, team reassignment, or project-context changes, refresh or re-login before concluding the system is wrong.

---

## Related Documentation

- **[Permissions Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
