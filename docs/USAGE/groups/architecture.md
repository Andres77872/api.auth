# Groups architecture

How the groups-of-groups access model is stored, resolved and enforced, and why it is built this
way.

## Components

| Layer | User groups | Project groups |
| --- | --- | --- |
| Routes | `src/routes/admin_user_groups.py` | `src/routes/admin_project_groups.py` |
| DB helpers | `src/Util/db/db_user_groups.py` | `src/Util/db/db_project_groups.py` |
| Stored procedures | `schemas/stored_procedures/02_user_groups.sql` | `schemas/stored_procedures/04_project_groups.sql` |
| Tables | `schemas/tables/02_create_tables.sql` | same |

Shared pieces: `src/Util/admin_scope.py` (the `admin_` name check and admin scope),
`src/Util/auth_lifecycle.py` (session validation and revocation) and the view
`v_user_project_access` in `schemas/tables/06_create_views.sql`.

## Tables

| Table | Holds | Uniqueness | Soft-delete columns |
| --- | --- | --- | --- |
| `user_groups` | Global user groups | `group_hash`; `group_name` (case-insensitive collation) | `is_active` |
| `user_group_members` | User to user group | (`user_id`, `user_group_id`) | `is_active`, `removed_at`, `removed_by` |
| `project_groups` | Project containers | `group_hash`; `group_name` | `is_active` |
| `project_group_members` | Project to project group | (`project_id`, `project_group_id`) | `is_active`, `removed_at`, `removed_by` |
| `user_group_project_groups` | Grant: user group to project group | (`user_group_id`, `project_group_id`) | `is_active`, `revoked_at`, `revoked_by` |
| `user_group_permission_groups` | Permission groups attached to a user group | | Owned by the [permissions suite](../permissions/architecture.md) |

Because each link has a unique pair key, "add" procedures use `INSERT ... ON DUPLICATE KEY UPDATE`
and reactivate the existing row. A pair is therefore never duplicated, and re-adding resets the
timestamp (`assigned_at` or `granted_at`).

## Access resolution

All procedures below require every link to be active and the project to be active and not archived.

| Object | Answers | Used by |
| --- | --- | --- |
| `sp_get_user_accessible_projects` | Projects a user reaches. Root: every active, non-archived project. Everyone else: the group chain | Consumer login and switch-project, `GET /projects` for consumers, group-access checks on `/projects/{project_hash}` routes |
| `sp_check_user_project_access` | Does this user reach this project | Session revocation re-check |
| `sp_get_user_groups_in_project_by_hash` | Which of the user's groups lead to this project | Consumer access-token validation |
| `sp_get_admin_assigned_projects` | Projects an admin user administers | Admin login, validation, admin scope |
| `v_user_project_access` | User-project pairs: `group_access` rows plus `root_access` rows | `GET /projects/{project_hash}/members` |
| `sp_get_projects_for_user_group` | Projects one user group reaches | `GET /admin/user-groups/{group_hash}` |

The chain, as joined by these procedures:

```text
user_group_members (user_id, is_active)
  -> user_groups (is_active)
  -> user_group_project_groups (is_active)
  -> project_groups (is_active)
  -> project_group_members (is_active)
  -> projects (is_active, archived = false)
```

`parent_group_id` on `user_groups` and `project_groups` is never followed. The schema has
hierarchy views, cycle-prevention triggers and `sp_get_user_all_groups_with_inheritance`, but no
route writes `parent_group_id` (the create helpers pass `NULL`) and no access procedure reads it.

## Project administrators

An admin user administers a project when all of these hold:

- the user's `user_type` is `admin`;
- the user is an active member of the user group named `admin_<project_id>`;
- that group is granted a project group that contains the project;
- the project is active and not archived.

`sp_get_admin_assigned_projects` encodes this. Because the group name is the whole assignment,
`_require_root_for_admin_group()` lets only root create, rename, delete or change members and
grants of any user group whose name starts with `admin_`. The comparison uses
`collation_key()` in `src/Util/admin_scope.py`, which ignores case, accents and width the way
`utf8mb4_unicode_ci` does, so look-alike names cannot slip past it. Root normally assigns admins
through `/user-types/admin/{user_hash}/projects` rather than these routes.

## Session revocation

`revoke_project_sessions_losing_access()` in `src/Util/auth_lifecycle.py` runs after a teardown
route has changed the database:

1. For each affected user, read the session index `user_sessions:{user_id}` in Redis.
2. Skip sessions whose `project_id` is not one of the affected projects.
3. Re-check access with `sp_check_user_project_access`. Keep the session if another chain still
   grants the project (root always passes while the project is active).
4. Otherwise revoke the refresh family (`refresh_family:{family_id}` marked revoked with the
   reason) and delete `session:{access_jti}` and `session_full:{access_jti}`.

Revocation reasons are listed in the [reference](reference.md#session-revocation). Removing a
single member skips this step; the next validation of that user's token fails instead
([request flow](request-flow.md#access-re-check-on-every-request)).

## Caching

Group routes invalidate nothing, and nothing needs invalidating for sessions:

- No Redis cache holds access decisions for sessions. Every access-token validation re-reads the
  chain from MySQL.
- `session_full:{access_jti}` caches the validated login object for `VALIDATE_CACHE_TTL` (default
  `30` seconds). It is read only after the live access check passes, so it can show stale group
  names but cannot grant access.
- API-key validation results are cached as `apikey:{public_id}` for `60` seconds. Group changes do
  not clear that entry, so a user-owned API key can keep validating for up to `60` seconds after
  its owner loses the project. Revoking the key clears it at once.

## Design decisions

- **Access only through groups.** Direct user-to-project assignment was removed from
  `src/routes/projects.py`. Every grant is a user group to project group link, so team access is
  added and removed in one place and audited from either side.
- **Separate permissions for the two prefixes.** User groups sit behind `manage_users` and project
  groups behind `manage_roles`, so a delegated consumer can manage team membership without being
  able to change which projects a container holds, or the reverse.
- **Soft deletes.** Rows are deactivated, not removed, which keeps `removed_by` / `revoked_by`
  history and keeps deleted names reserved.
- **Permission groups are separate.** Project reach and capabilities are resolved independently.
  Permission groups attached to a user group appear in inspection endpoints only; authorization
  uses global-role permissions ([permission resolution](../permissions/resolution.md)).

## Known defects

- `PUT /admin/project-groups/{group_hash}` with neither `group_name` nor `description` returns
  `500` `INT_7001` instead of `400`; the user-group equivalent returns `400` `VAL_3002`.
- `GET /admin/user-groups/{group_hash}` always returns `derived_projects: []` and
  `statistics.total_derived_projects: 0`; `GET /admin/user-groups/{group_hash}/project-groups`
  always returns `total_derived_projects: 0`. Use `accessible_projects` for the reachable projects.
- Revoking a grant that is not active returns `500` `INT_7001` rather than `404`.
- `GET /admin/user-groups` does not set `pagination.has_more`, and its `pagination.total` ignores
  `search`.
