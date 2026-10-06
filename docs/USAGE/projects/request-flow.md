# Projects request flow

What happens to a request on `/projects`, and how a project's state affects sessions that are
scoped to it.

## Common steps

```text
request
  -> platform middleware (CORS, request validation, API audit, auth context)
  -> HTTPBearerOrCookie: bearer header or access_token cookie        (401 if absent)
  -> FastAPI query/form validation                                     (400 VAL_3001)
  -> handler: validate_session()                                       (401)
  -> admin routes: caller must be a root or admin user                 (403 AUTHZ_2002)
  -> project lookup: sp_get_project_by_hash, active rows only          (404 NF_4002)
  -> admin scope over the project, or group reach on read routes      (403 AUTHZ_2003)
  -> DB helper -> stored procedure
  -> response model
```

1. `validate_session()` runs the canonical access-token validation, which re-checks the caller's
   own session project on every request
   ([groups request flow](../groups/request-flow.md#access-re-check-on-every-request)).
2. `resolve_admin_scope()` in `src/Util/admin_scope.py` reads the caller's `user_type` from the
   database and, for admin users, their assigned project IDs from
   `sp_get_admin_assigned_projects`. Session permission names are not consulted.
3. `sp_get_project_by_hash` returns projects with `is_active = 1`, archived ones included. Archive
   filtering happens in the reach and scope checks, not in the lookup.

The target project in the path is independent of the project the caller's session is scoped to.

## Route-specific flows

### List projects

`GET /projects` branches on the caller:

| Caller | Source | Paging |
| --- | --- | --- |
| Root without `search` | `sp_list_all_projects` (active, non-archived, newest first) | In SQL; `total` is the page size |
| Root with `search` | `sp_search_projects` (name or description, by name, `LIMIT limit`) | `offset` ignored |
| Admin user | `sp_get_admin_project_assignments_with_details`, filtered by `search` in Python | Sliced in Python; `total` is the full count |
| Anyone else | `sp_get_user_accessible_projects` | Sliced in Python; `total` is the full count |

Each row is labelled `admin_access` (root and admin users) or `group_access`.

### Create a project

1. Validate the session; refuse any caller whose `user_type` is not `root` (`403` `AUTHZ_2002`).
2. `create_project()` generates `proj-<uuid>` and a 64-character hex `project_hash`, then calls
   `sp_create_project` with the caller as creator and owner.
3. `create_default_groups()` inserts the default project group, the project assignment, the three
   user groups and their grants with raw SQL
   ([default groups](architecture.md#default-group-bootstrap)).
4. Return `CreateProjectResponse`.

### Read one project

`GET /projects/{project_hash}`, `/activity` and `/stats`:

1. Validate the session and look up the project (`404` if unknown or deleted).
2. If the caller has admin scope over the project (`AdminScope.allows_project()`), continue.
3. Otherwise load `sp_get_user_accessible_projects` for the caller and require the project in it
   (`403` `AUTHZ_2003`). This list never contains archived projects.
4. Details: load `statistics` (`sp_get_project_statistics`), the caller's user groups and the
   project's project groups. Activity: query the activity log with the filters and count the
   total. Stats: load `statistics` only.

### Administer one project

`PUT`, `DELETE`, `/members`, `/groups`, `/owner`, `/archive`:

1. Validate the session.
2. `_require_admin_caller()`: `user_type` must be `root` or `admin` (`403` `AUTHZ_2002`).
3. Look up the project (`404`).
4. `require_project_in_scope()`: root passes; an admin user needs the project among their
   assignments (`403` `AUTHZ_2003`). Assignments never include archived projects.
5. Run the operation:
   - `PUT`: `sp_update_project` (`COALESCE` keeps omitted fields).
   - `DELETE`: `sp_delete_project` deactivates the project, its `project_group_members` rows and
     its project-group memberships.
   - `/members`: `sp_get_project_members_paginated` over `v_user_project_access`, then each
     consumer's user groups.
   - `/groups`: `sp_get_user_groups_for_project`, sliced in Python.
   - `/owner`: look up `new_owner_hash` (`404` `NF_4001`), then raise `501`.
   - `/archive`: raise `501`.

## Sessions and project state

Login and `POST /auth/switch-project` bind a session to one project
([authentication](../authentication-usage-cases.md)). On every later request the session's project
is looked up again:

| Project state | Effect on sessions scoped to it |
| --- | --- |
| Deleted (`is_active = 0`) | Lookup fails; the refresh family is revoked (reason `missing_project`) and the request gets `401` |
| Archived | Same, with reason `project_inactive_or_archived`; applies to root sessions too |
| Removed from the user's reach | Consumer: no group leads to it. Admin user: no longer assigned. Family revoked (`project_access_denied`), `401` |

Login and switch-project refuse an archived target project with `403` `AUTHZ_2003`; a deleted one
is not found. API-key validation (`sp_validate_api_key` in
`schemas/stored_procedures/13_api_keys.sql`) applies the same project checks, behind a
`60`-second result cache.
