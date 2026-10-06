# Projects architecture

How projects are stored, bootstrapped, authorized and archived, and where the implementation
currently falls short. The access chain that connects users to projects is described once, in
[groups architecture](../groups/architecture.md#access-resolution).

## Components

| Layer | Location |
| --- | --- |
| Routes | `src/routes/projects.py` (prefix `/projects`, 11 operations) |
| Admin scope | `src/Util/admin_scope.py` |
| DB helpers | `src/Util/db/db_projects.py`; reach queries in `src/Util/db/db_user_groups.py` |
| Stored procedures | `schemas/stored_procedures/03_projects.sql` |
| Table | `projects` in `schemas/tables/02_create_tables.sql` |
| View | `v_user_project_access` in `schemas/tables/06_create_views.sql` |
| Activity feed | `src/Util/activity_logger.py` |

## The projects table

| Column | Meaning |
| --- | --- |
| `id` | Internal ID, `proj-<uuid>`. Not returned by project routes |
| `project_hash` | Public identifier, 64 upper-case hex characters, unique |
| `project_name` | Up to 100 characters, not unique |
| `project_description` | Free text |
| `created_by`, `owner_id` | Both set to the creating root user. No route changes or returns them |
| `is_active` | `0` after `DELETE /projects/{project_hash}` |
| `archived`, `archived_at`, `archived_by` | Archive state. No route changes or returns it |
| `project_created`, `updated_at` | Timestamps |

## Stored procedures used by the routes

| Procedure | Route |
| --- | --- |
| `sp_create_project` | `POST /projects` |
| `sp_get_project_by_hash` | Every route with `{project_hash}`: active projects, archived included |
| `sp_list_all_projects`, `sp_search_projects` | `GET /projects` for root |
| `sp_get_admin_project_assignments_with_details` | `GET /projects` for admin users |
| `sp_get_user_accessible_projects` | `GET /projects` for other callers; group-reach checks |
| `sp_update_project` | `PUT /projects/{project_hash}` |
| `sp_delete_project` | `DELETE /projects/{project_hash}` |
| `sp_get_project_members_paginated` | `GET /projects/{project_hash}/members` |
| `sp_get_user_groups_for_project` | `GET /projects/{project_hash}/groups` |
| `sp_get_project_statistics` | `statistics` on details and `/stats`: project row, access counts, then per-group member counts |
| `sp_get_project_groups_for_project` | `project_groups` on details |

`sp_archive_project` and `sp_unarchive_project` exist but no code calls them. There is no
ownership-transfer procedure.

## Default group bootstrap

`create_project()` commits the `projects` row, then calls `create_default_groups()`, which writes
with raw SQL rather than stored procedures:

| Row | Table | ID | Name / hash |
| --- | --- | --- | --- |
| Default project group | `project_groups` | `pg-default-<project_id>` | `default_<project_id>`, hash `PG-` + 32 hex |
| Project in that group | `project_group_members` | `pgm-default-<project_id>` | |
| Three user groups | `user_groups` | `ug-default-{admin,user,readonly}-<project_id>` | `admin_<project_id>`, `user_<project_id>`, `readonly_<project_id>`, hash `UG-` + 32 hex |
| Three grants | `user_group_project_groups` | `ugpg-default-{admin,user,readonly}-<project_id>` | |

The IDs are deterministic and every insert is `INSERT ... ON DUPLICATE KEY UPDATE is_active = 1`,
so a re-run repairs the scaffolding instead of duplicating it. No users are added. The
`admin_<project_id>` group is what makes an admin user an administrator of the project; root fills
it through `/user-types/admin/{user_hash}/projects` ([user types](../users/user-types.md)).

## Admin scope

`resolve_admin_scope()` reads the caller's `user_type` (`sp_get_user_type`) and, for admin users,
their assignments (`sp_get_admin_assigned_projects`) from the database on every request.
`AdminScope.allows_project()` is `true` for root on any project and for an admin user on an
assigned one.

Why: session permission names are not a safe basis for project administration. A consumer's
session permissions come from a global role, so a role that includes `admin` or `manage_users`
would otherwise turn a consumer into an administrator of every project. Reading live state also
makes a demotion or unassignment effective on the next request instead of at token expiry.

## Soft delete

`sp_delete_project` sets `projects.is_active = 0`, deactivates the project's
`project_group_members` rows. Redis sessions
are not touched directly: the next validation of an access token scoped to the project cannot find
the project, revokes the refresh family and returns `401`. The default groups and any other groups
that contained the project stay as they are.

## Archive state

The archive flag has no API writer, but it is enforced wherever a project is resolved for access:

| Place | Effect of `archived = true` |
| --- | --- |
| `sp_get_user_accessible_projects`, `sp_check_user_project_access`, `sp_get_user_groups_in_project_by_hash` | Project excluded from group reach, root included |
| `sp_get_admin_assigned_projects` and related admin procedures | Excluded from admin assignments |
| `v_user_project_access` | No rows, so `GET /projects/{project_hash}/members` is empty |
| `sp_list_all_projects`, `sp_search_projects`, `sp_get_projects_in_project_group`, `sp_get_projects_for_user_group` | Excluded from listings and counts |
| Login and `POST /auth/switch-project` | `403` `AUTHZ_2003` |
| Access-token validation (`reconstruct_auth_context()` in `src/Util/auth_lifecycle.py`) | `401`, refresh family revoked |
| `sp_validate_api_key` | Key rejected |
| OAuth sign-in pipeline | Denied (`project_inactive_or_archived`) |
| `sp_get_project_by_hash` | Not filtered: root can still read, update and delete the project by hash |

## Design decisions

- **No direct user-to-project assignment.** The former `POST /projects/{project_hash}/members` and
  `DELETE /projects/{project_hash}/members/{user_hash}` routes were removed so that all reach goes
  through groups and can be revoked in one place.
- **Creation is root-only.** A project is a tenant boundary; admin users administer only the
  projects root assigns them.
- **Path-based access labels.** `access_level` says how the caller or member reaches the project
  (`admin_access`, `group_access`, `root_access`), not which permissions they hold. Global-role
  permissions are not project-scoped, so deriving a per-project label from them would mislead.

## Known defects

- **No session count.** `statistics.active_sessions` is always `null`; `sp_get_project_statistics`
  reports group-based access only.
- **Root pagination.** For root, `GET /projects` reports `pagination.total` as the page size and
  `has_more` as `false`.
- **Python-side paging.** For admin users and consumers `GET /projects` loads every reachable
  project and slices in Python; `GET /projects/{project_hash}/groups` does the same.
- **Stubs.** `PATCH /projects/{project_hash}/owner` and `/archive` always end in `501` `INT_7006`.
- **Partial create.** The `projects` row is committed before `create_default_groups()` runs. If the
  bootstrap fails, the request fails but the project exists without its default groups.
