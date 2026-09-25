# Roles architecture

Components, storage, invariants, and design decisions behind the `/roles` API. How the stored data
becomes effective permissions is in [Permission resolution](../permissions/resolution.md).

## Components

| Layer | Location |
| --- | --- |
| Routes (prefix `/roles`, OpenAPI tag "Global Role System") | `src/routes/global_roles.py` |
| Database access | `src/Util/db/db_global_roles.py` |
| Stored procedures | `schemas/stored_procedures/05_global_roles.sql` |
| Tables and foreign keys | `schemas/tables/02_create_tables.sql`, `schemas/tables/04_add_constraints.sql` |
| Reserved permission names | `src/Util/admin_scope.py` |
| Activity triggers | `schemas/triggers/02_permission_activity_triggers.sql` |
| Bulk role assignment | `src/routes/bulk_operations.py`, `src/Util/bulk_operations.py` |

## Tables

| Table | Unique keys | Notes |
| --- | --- | --- |
| `roles` | `role_hash`, `role_name` | `role_name` `VARCHAR(100)`, `role_display_name` `VARCHAR(255)`, `role_description` `TEXT`, `role_priority` `INT` default `50`, `is_system_role`, `is_active`, `created_at`, `updated_at`, `created_by` |
| `global_permission_groups` | `group_hash`, `group_name` | `group_category` `VARCHAR(50)` default `general` |
| `global_permissions` | `permission_hash`, `permission_name` | `permission_category` `VARCHAR(50)` default `general` |
| `role_permission_groups` | `(role_id, permission_group_id)` | Link with `assigned_*`, `removed_*`, `is_active` |
| `global_permission_group_permissions` | `(permission_group_id, permission_id)` | Link with `granted_*`, `removed_*`, `is_active` |
| `role_project_catalog` | `(role_id, project_id)` | `catalog_purpose` `VARCHAR(255)`, `notes`, `added_*`, `removed_*`, `is_active` |
| `users.role_id` | — | Nullable; foreign key to `roles.id` with `ON DELETE SET NULL` (never fired, since nothing hard-deletes roles) |

All tables use `utf8mb4_unicode_ci`, so the unique names are case- and accent-insensitive. Internal
IDs are a prefix (`role_`, `pg_`, `perm_`, `rpg_`, `pgp_`, `rpc_`) plus 16 hex characters; public hashes
are 32 hex characters of a SHA-256 over the name and a timestamp. No roles, groups, or permissions are
seeded by the schema.

`schemas/docs/permissions.md` is the schema-level reference for these tables and procedures.

## Procedures and direct SQL

| Operation | Implementation |
| --- | --- |
| Create, read, list, update roles, groups, permissions | `sp_global_create_*`, `sp_global_get_*_by_hash`, `sp_global_list_*`, `sp_global_update_*` |
| Delete role | `sp_global_delete_role` |
| Delete permission group, delete permission | Direct `UPDATE ... SET is_active = 0` on the object row only |
| Link group to role, permission to group | `sp_global_assign_permission_group_to_role`, `sp_global_assign_permission_to_group` (upserts) |
| Unlink | Direct `UPDATE ... SET is_active = 0, removed_at = NOW()` on the active link |
| Read links | `sp_global_get_role_permission_groups`, `sp_global_get_permission_group_permissions` |
| Assign, read role | `sp_global_assign_role_to_user`, `sp_global_get_user_role` |
| Remove role | Direct `UPDATE users SET role_id = NULL` |
| Catalog | `sp_global_add_role_to_project_catalog`, `sp_global_get_project_cataloged_roles`, `sp_global_remove_role_from_project_catalog` |
| Auth-time resolver, `/roles` guard | `sp_global_get_user_permissions`, `sp_global_check_user_has_permission` |
| Bulk role lookup | Direct `SELECT` by `role_name` on active roles |

Defined but not called: `sp_global_delete_permission_group` and `sp_global_delete_permission` (both
would also deactivate group memberships), `sp_global_remove_permission_from_group`,
`sp_global_remove_permission_group_from_role`, `sp_global_remove_role_from_user`.

## Invariants

- **Soft delete everywhere.** Roles, groups, permissions, links, and catalog entries are only ever
  flagged inactive. Names stay unique across active and inactive rows, so a deleted name cannot be
  reused.
- **Lookups see active rows only.** Every by-hash lookup and every list filters on `is_active`, so a
  soft-deleted object answers `404` and cannot be restored or unlinked through the API.
- **Deletes do not cascade.** Deleting a role leaves `users.role_id`, its group links, and catalog rows
  in place. Deleting a group leaves its role links and memberships active. Deleting a permission leaves
  its memberships active. The effect of each on resolution is in
  [Soft-delete effects](../permissions/resolution.md#soft-delete-effects).
- **One role per user.** `users.role_id` is a single column; assignment overwrites it.
- **Links are upserts.** Linking twice re-activates the same row and refreshes `assigned_at`/`granted_at`;
  it never fails as a duplicate.
- **Nothing is cached here.** Writes do not invalidate sessions. Consumer permissions are recomputed on
  every token validation and served from a `session_full` entry that lives `VALIDATE_CACHE_TTL`
  seconds (default `30`).
- **Trigger logging is partial.** Triggers write `activity_logs` rows for inserts and updates of roles,
  groups, and permissions, and for inserts of links. Link re-activation and soft removal are updates
  on the link tables, which have no update trigger, so they are not logged there.

## Reserved permission names

Routers and middleware trust some names when they appear in session permissions: `admin` opens
`verify_admin_access` and most admin guards, `manage_users` opens user-group administration, and so
on. A consumer's session permissions come from its role, so anyone who could put such a name into a
role could grant it, including to themselves. The `/roles` router therefore lets only root create,
edit, move, or hand out these names, and forbids non-root callers from changing their own role. The
list and the exact root-only operations are in
[Roles reference](reference.md#reserved-permission-names).

Names are compared with `collation_key`, which mirrors `utf8mb4_unicode_ci` (case, accents, width,
surrounding spaces), so a look-alike such as `Ádmin` is caught.

The checks read only active groups and permissions, through the same flags as the role-derived
resolver (`sp_global_get_user_permissions`), so a role can never grant a reserved name the check does
not see. A soft-deleted permission group grants nothing, even while still linked. The `/permissions`
assignment routes apply the same root-only rule to permission groups, because a user-group or direct
grant of `manage_roles` opens that router.

## Design decisions

- **Global, not per project.** Roles, groups, and permissions have no project column; a permission such
  as `manage_users` means the same everywhere. Which projects a user can enter is decided by user and
  project groups ([groups](../groups/README.md)).
- **Delegation through `manage_roles`.** `require_admin` lets a consumer whose role grants
  `manage_roles` manage roles. The check is live and role-only, so user-group and direct grants do not
  count. Managing user groups needs `manage_users` instead; the route code calls this intentional
  least privilege.
- **`role_priority` is ordering metadata.** It sorts role listings and the project role catalog and
  plays no part in resolution.
- **Catalogs are metadata.** The project role catalog drives UI suggestions; no guard or resolver reads
  it.
- **System roles.** `is_system_role` can only be set in the database. The API refuses to delete such a
  role but lets it be edited.
