# Groups Architecture

Technical architecture of the groups system as it actually exists in `api.auth`.

---

## Core Access Model

The active runtime model is:

```
USER → USER_GROUP → PROJECT_GROUP → PROJECT
                 ↘
                   PERMISSION_GROUP → PERMISSIONS
```

This is the important distinction:

- **User groups** organize users globally
- **Project groups** collect projects into reusable access buckets
- **Permission groups** are attached independently and do not replace project-access wiring

---

## Real Tables Behind the Model

| Table | Purpose |
|------|---------|
| `user_groups` | Global team/organizational groups |
| `user_group_members` | User-to-user-group membership |
| `project_groups` | Project containers |
| `project_group_members` | Project-to-project-group membership |
| `user_group_project_groups` | The key access bridge from teams to project containers |
| `user_group_permission_groups` | Separate bridge from teams to permission templates |

If you forget `user_group_project_groups`, you miss the whole point of the implementation.

---

## Route and Layer Split

### User-group operations
- Route file: `src/routes/admin_user_groups.py`
- DB layer: `src/Util/db/db_user_groups.py`
- Stored procedures: `schemas/stored_procedures/02_user_groups.sql`

### Project-group operations
- Route file: `src/routes/admin_project_groups.py`
- DB layer: `src/Util/db/db_project_groups.py`
- Stored procedures: `schemas/stored_procedures/04_project_groups.sql`

### Session-aware access resolution
- Route file: `src/routes/auth.py`
- Shared DB exports: `src/Util/db/__init__.py`

---

## Authorization Split

The repo does not use one identical admin guard for all group operations.

| Area | Permission Gate |
|------|-----------------|
| `/admin/user-groups` | `admin` or `manage_users` |
| `/admin/project-groups` | `admin` or `manage_roles` |

That means user-group and project-group administration are related, but not authorized identically.

---

## Login and Session Architecture

During login, `src/Util/auth_lifecycle.py:_issue_token_pair()` builds the session payload and embeds the user's groups:

- `user_group_ids`
- `user_group_names`

This matters because group changes may not be reflected in an already-issued session until the user logs in again, refreshes, or switches project context depending on the workflow.

### Direct cross-group login contract

The public `/auth/login` route already authorizes consumers through the direct groups-of-groups chain and this behavior is now codified/hardened:

```
consumer user
  → active membership in user_group_b
  → active direct user_group_b → project_group_b authorization row
  → active project_group_b → project_a membership
  → active, non-archived project_a
```

So a consumer in `user_group_b` can log in with `project_a.project_hash` when `project_a` is a member of `project_group_b`. No direct `project_a → user_group_b` shortcut is required or supported.

Important constraints:

- `user_groups.parent_group_id` is **not** traversed for login authorization.
- `project_groups.parent_group_id` is **not** traversed for login authorization.
- Login/switch responses do **not** disclose which user-group/project-group chain granted access.
- Archived projects are denied for consumer login, root login, switching, accessible-project results, and session validation.

---

## Project Creation Side Effect: Default Groups

`src/Util/db/db_projects.py:create_default_groups()` creates default access scaffolding when a project is created.

Current behavior:

1. Create a default project group for the project
2. Add the project to that project group
3. Create default user groups based on the project id:
   - `admin_{project_id}`
   - `user_{project_id}`
   - `readonly_{project_id}`
4. Link those user groups to the default project group

So new projects come with group wiring baked in from day one.

---

## Soft Deletes

Group deletion is implemented as deactivation, not hard deletion.

- `is_active = 0` is used across core group tables
- membership and access links are also deactivated during user-group deletion
- active queries typically filter on `is_active = 1`

Operationally, this means historical records may still exist, but they should no longer participate in access resolution.

### Live session revocation on access teardown

Soft-deactivating rows is not the whole story. The destructive routes also reach into the session layer: `src/routes/admin_user_groups.py` and `src/routes/admin_project_groups.py` both import `revoke_project_sessions_losing_access` from `src/Util/auth_lifecycle.py` and call it after a successful teardown, so access removal extends to **live sessions**.

| Route | Reason passed |
|------|---------------|
| `DELETE /admin/user-groups/{hash}` | `user_group_deleted` |
| `DELETE /admin/user-groups/{hash}/project-groups/{project_group_hash}` | `user_group_project_group_access_revoked` |
| `DELETE /admin/project-groups/{hash}` | `project_group_deleted` |
| `DELETE /admin/project-groups/{hash}/projects/{project_hash}` | `project_removed_from_group` |

Before deleting/revoking, each route computes the impacted users and projects (user-group routes via `get_users_in_group` / `get_projects_for_user_group` / `get_projects_in_group`; project-group routes via `db_project_groups.get_users_with_access_to_project_group` and `get_projects_in_permission_group`) and passes those ids to the revocation helper. This is why affected users are forced to re-authenticate immediately rather than waiting for their sessions to expire.

---

## Important Current Caveats

### `parent_group_id` is not exposed by group CRUD routes

Both `user_groups` and `project_groups` have hierarchy columns, but the active group-management routes do not expose `parent_group_id` as a create/update parameter; the DB layer currently passes `NULL` through those public flows.

Do not confuse that route-layer reality with the SQL layer: schema views, cycle-prevention triggers, and a recursive permission CTE do reference `parent_group_id`. Treat hierarchy as SQL-level infrastructure, not as a public CRUD feature.

### Permission groups are attached separately

Permission groups are not children of project groups. They are attached to user groups or users through separate routes and tables.

### Legacy direct-project traces still exist in some responses

Some code paths still expose fields such as `accessible_projects`, but the real scalable access pattern is the group bridge:

`user_group_members → user_group_project_groups → project_group_members`

---

## Related Documentation

- **[Groups Overview](README.md)**
- **[Usage](usage.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: June 2026  
**Document Version**: 3.1
