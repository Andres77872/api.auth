# Permissions architecture

Components, storage, and design decisions behind the `/permissions` API. How the stored data turns
into effective permissions is in [Permission resolution](resolution.md).

## Components

| Layer | Location |
| --- | --- |
| Routes (prefix `/permissions`, OpenAPI tag "Permission Assignments") | `src/routes/permission_assignments.py` |
| Database access | `src/Util/db/db_permission_assignments.py`; permission-group lookups use `src/Util/db/db_global_roles.py` |
| Stored procedures | `schemas/stored_procedures/06_permission_assignments.sql` |
| Tables | `schemas/tables/02_create_tables.sql` |
| Activity triggers | `schemas/triggers/02_permission_activity_triggers.sql` |
| Token validation | `HTTPBearerOrCookie` in `src/Util/Seccurity.py`, `validate_session` in `src/Util/db/db_enhanced.py`, `src/Util/auth_lifecycle.py` |

## Tables

| Table | Unique key | Holds |
| --- | --- | --- |
| `user_group_permission_groups` | `(user_group_id, permission_group_id)` | User-group assignments: `assigned_at`, `assigned_by`, `removed_at`, `removed_by`, `is_active` |
| `user_permission_groups` | `(user_id, permission_group_id)` | Direct assignments, same columns plus `notes` |
| `permission_group_project_catalog` | `(permission_group_id, project_id)` | Catalog entries: `catalog_purpose` (255 characters), `notes`, `added_*`, `removed_*`, `is_active` |

The suite also reads `user_group_members`, `user_groups`, `users`, and `projects` (groups, users, and
projects suites) and the role and permission tables owned by the [roles suite](../roles/architecture.md).

## Stored procedures

| Procedure | Called for |
| --- | --- |
| `sp_assign_permission_group_to_user_group`, `sp_remove_permission_group_from_user_group` | User-group assign and remove (single and bulk) |
| `sp_get_user_group_permission_groups` | A user group's permission groups |
| `sp_get_user_groups_with_permission_group` | Usage query: user groups |
| `sp_assign_permission_group_to_user`, `sp_remove_permission_group_from_user` | Direct assign and remove |
| `sp_get_user_permission_groups` | Direct groups of a user or of the caller |
| `sp_get_users_with_permission_group` | Usage query: users |
| `sp_get_user_all_permissions` | `GET /permissions/users/me/permissions` |
| `sp_check_user_has_permission_extended` | `GET /permissions/users/me/permissions/check/{permission_name}` and the admin guard |
| `sp_get_user_permission_sources` | `GET /permissions/users/me/permission-sources` |
| `sp_add_permission_group_to_project_catalog`, `sp_remove_permission_group_from_project_catalog` | Catalog add and remove |
| `sp_get_project_cataloged_permission_groups`, `sp_get_permission_group_cataloged_projects` | Catalog reads |

The same file also defines project-scoped role and grant/deny procedures and
`sp_get_user_all_groups_with_inheritance`; no Python code calls them (see
[What does not affect resolution](resolution.md#what-does-not-affect-resolution)).

## Invariants

- **Every assignment is an upsert.** The unique keys plus `ON DUPLICATE KEY UPDATE` mean assigning
  twice never fails and never duplicates; it re-activates the row and resets `assigned_at` and
  `assigned_by` (and, for direct assignments, `notes`).
- **Soft delete only.** Removals set `is_active = FALSE`, `removed_at`, and `removed_by`. No route
  deletes a row, so the tables keep assignment history.
- **Removals are idempotent.** The remove procedures update only active rows and return nothing; the
  routes answer `200` either way.
- **Trigger logging is partial.** Triggers write `activity_logs` rows on `INSERT` and `DELETE`. A first
  assignment is logged; re-activation (an update) and soft removal are not. The requests themselves
  go through the API audit middleware ([audit logs](../audit_logs/README.md)).
- **No cache.** Reads go straight to MySQL and writes invalidate nothing, because no assignment in
  this suite feeds the cached auth-time set.
- **Group state is not copied.** Assignment rows reference permission groups by ID. Deactivating a
  group leaves them active, but listings hide the group and every resolver checks the group's own
  flag, so the rows grant nothing (see [Soft-delete effects](resolution.md#soft-delete-effects)).

## Design decisions

- **Assignments stay out of the auth-time set.** Route guards trust reserved names such as `admin`
  and `manage_users` in session permissions, so user-group and direct assignments are kept out of the
  auth-time set. This router still makes reserved names root-only, because its own guard trusts
  `manage_roles` from an assignment: without that rule any delegate could hand the delegation on.
- **The admin guard is wider than the `/roles` guard.** It accepts `manage_roles` from any source, so
  assignment work can be delegated through a user group or a direct assignment without granting
  `/roles` access. Only root can delegate or withdraw it; see
  [Permissions scenarios](scenarios.md#delegate-the-permissions-admin-routes-to-a-team).
- **Catalogs are metadata.** Both project catalogs exist to drive UI suggestions. No resolver or guard
  reads them.
- **Envelope.** Responses omit the `success` field that `/roles` responses carry; clients should rely
  on the HTTP status.
