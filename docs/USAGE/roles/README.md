# Roles Documentation

Detailed, repo-specific documentation for the global roles system used in `api.auth`.

---

## Overview

This documentation set covers the **global roles model** implemented in this repository:

```
USER → ROLE → PERMISSION_GROUP → PERMISSION
              ↘
                PROJECT_CATALOG (metadata only)
```

The roles system is the **baseline authorization layer** for this API. What matters operationally:

- **One role per user** — the `users` table has a single `role_id` column
- **Roles are global**, not project-scoped
- **Permission resolution during auth is ROLE-ONLY** — user-group and direct permission assignments are NOT included in session-time permission checks
- **Catalog endpoints are metadata only** — they do not restrict which roles can be assigned
- **All write endpoints use `multipart/form-data`**, not JSON
- **Soft deletes** (`is_active = FALSE`) are used, not hard removals

---

## Documents in This Suite

| Document | Focus |
|----------|-------|
| [usage.md](usage.md) | Day-to-day role CRUD, permission-group linking, user assignment, and catalog operations |
| [architecture.md](architecture.md) | Data model, tables, route organization, auth guards, entity relationships |
| [request-flow.md](request-flow.md) | End-to-end runtime flows: create role, attach groups, assign to user, inspect, remove, catalog |
| [scenarios.md](scenarios.md) | Concrete admin/user workflows with curl examples |
| [reference.md](reference.md) | Endpoint tables and operational notes for all `/roles` endpoints |
| [troubleshooting.md](troubleshooting.md) | Common failures, broken endpoints, caveats, and diagnostics |

---

## Core Model in This Repo

### Roles

- Managed under `/roles/roles`
- Stored in `roles` table
- Fields: `role_name` (unique, immutable), `role_display_name`, `role_description`, `role_priority` (0-100, ordering only), `is_system_role` (protected from deletion), `is_active`
- Linked to permission groups through `role_permission_groups`
- Assigned directly to users via `users.role_id`

### Permission Groups (within roles context)

- Managed under `/roles/permission-groups`
- Stored in `global_permission_groups`
- Categories: `general`, `admin`, `api`, `data` (documented, not DB-enforced)
- Filled with permissions through `global_permission_group_permissions`
- Attached to roles through `role_permission_groups`

### Permissions

- Managed under `/roles/permissions`
- Stored in `global_permissions`
- Individual capability tokens (e.g., `read_data`, `manage_users`)

### User Role Assignment

- Each user has **one** global role via `users.role_id` (nullable)
- Assignment replaces the previous role — no stacking
- Assignment is blocked for inactive users

### Project Role Catalog

- Managed under `/roles/projects/{hash}/catalog/roles`
- Stored in `role_project_catalog`
- **METADATA ONLY** — does not restrict role assignment or authorization

---

## Recommended Reading Order

1. Start with [usage.md](usage.md)
2. Then read [architecture.md](architecture.md)
3. Use [request-flow.md](request-flow.md) for runtime behavior
4. Keep [reference.md](reference.md) open while operating the API
5. Use [scenarios.md](scenarios.md) and [troubleshooting.md](troubleshooting.md) when applying it to real workflows

---

## Scope and Caveats

- This suite documents the **active public route layer** under `src/routes/global_roles.py` (1066 lines)
- The **auth/session flow uses ROLE-ONLY permission resolution** — this is the most important caveat. See [permissions/resolution.md](../permissions/resolution.md) for the full explanation of the auth-vs-inspection gap
- **Bulk role assignment is broken** — see [troubleshooting.md](troubleshooting.md)
- **Pagination `total` is incorrect** — returns page count, not DB total
- **Soft delete leaves orphans** — deleting a role does not clear `users.role_id`
- **`is_system_role` is not settable via API** — system roles must be created via direct DB access
- **`role_name` is immutable** — cannot be changed after creation
- Guard behavior differs between `/roles` (role-only check) and `/permissions` (extended check); see [architecture.md](architecture.md)

---

## Related Documentation

- **[Usage Documentation Home](../README.md)** - Complete usage index
- **[Permissions Documentation Suite](../permissions/README.md)** - Permission groups, assignments, dual-path authorization model
- **[Permission Resolution](../permissions/resolution.md)** - The critical auth-vs-inspection gap explained
- **[Groups Documentation Suite](../groups/README.md)** - User groups, project groups, and group-based permission assignments
- **[Projects Documentation Suite](../projects/README.md)** - Project access model separate from capability management
- **[Users Documentation Suite](../users/README.md)** - User profile, access summary, and lifecycle operations
- **[Authentication Usage Cases](../authentication-usage-cases.md)** - Login, session management, project switching
- **[Error Reference](../errors.md)** - Error codes, response shapes, and troubleshooting
- **[Database Schema](../../../schemas/)** - SQL tables, views, and stored procedures

---

**Last Updated**: April 2026  
**Document Version**: 1.0
