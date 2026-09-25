# Groups request flow

What happens to a request on `/admin/user-groups` or `/admin/project-groups`, and how group state
is checked again on every later authenticated request.

## Common pipeline

```text
request
  -> platform middleware (CORS, request validation, API audit, auth context)
  -> HTTPBearerOrCookie: Authorization bearer or session_token cookie        (401 if absent)
  -> require_admin -> validate_session -> validate_access_session           (401 if invalid)
  -> permission check: admin | manage_users  or  admin | manage_roles        (403 AUTHZ_2002)
  -> handler: resolve hashes (active rows only)                              (404)
  -> admin_ guard on user-group writes                                       (403 AUTHZ_2002)
  -> DB helper -> stored procedure (MySQL)
  -> teardown routes only: revoke_project_sessions_losing_access (Redis)
  -> Pydantic response model
```

1. `HTTPBearerOrCookie` takes the token from `Authorization: Bearer` or the `session_token` cookie.
2. `require_admin` calls `validate_session()`, which for a JWT runs `validate_access_session()`:
   signature and claims, the Redis session `session:{access_jti}`, the refresh family, then a live
   rebuild of the auth context (see [access re-check](#access-re-check-on-every-request)).
3. The dependency reads `permissions` from the validated session. User-group routes accept `admin`
   or `manage_users`; project-group routes accept `admin` or `manage_roles`.
4. The handler looks up the group by hash through `sp_get_user_group_by_hash` or
   `sp_get_project_group_by_hash`, both of which return active rows only.
5. User-group writes call `_require_root_for_admin_group()` with the current name and, on rename,
   the new name. A name starting with `admin_` needs a root caller.
6. The handler looks up the caller (`get_user_by_hash`) to record who made the change, then calls
   the DB helper.

## Write operations

| Route | DB helper | Stored procedure | Notes |
| --- | --- | --- | --- |
| `POST /admin/user-groups` | `create_user_group` | `sp_create_user_group` | Hash is 64 upper-case hex characters |
| `PUT /admin/user-groups/{group_hash}` | `update_user_group` | `sp_update_user_group` | `COALESCE` keeps omitted values |
| `DELETE /admin/user-groups/{group_hash}` | `delete_user_group` | `sp_delete_user_group` | Group, memberships and grants deactivated |
| `POST /admin/user-groups/{group_hash}/members` and `/members/bulk` | `assign_user_to_group` | `sp_assign_user_to_group` | Upsert: reactivates an existing row |
| `DELETE /admin/user-groups/{group_hash}/members/{user_hash}` | `remove_user_from_group` | `sp_remove_user_from_group` | No session revocation |
| `POST /admin/user-groups/{group_hash}/project-groups` | `grant_user_group_project_group_access` | `sp_grant_user_group_project_group_access` | Upsert |
| `DELETE /admin/user-groups/{group_hash}/project-groups/{project_group_hash}` | `revoke_user_group_project_group_access` | `sp_revoke_user_group_project_group_access` | `false` when no row changed, which the route turns into `500` |
| `POST /admin/project-groups` | `create_project_group` | `sp_create_project_group` | Created empty |
| `PUT /admin/project-groups/{group_hash}` | `update_project_group` | `sp_update_project_group` | `COALESCE` keeps omitted values; with no values the helper returns nothing and the route answers `500` |
| `DELETE /admin/project-groups/{group_hash}` | `delete_project_group` | `sp_delete_project_group` | Group, project assignments and grants deactivated |
| `POST /admin/project-groups/{group_hash}/projects` | `assign_project_to_group` | `sp_assign_project_to_group` | Upsert |
| `DELETE /admin/project-groups/{group_hash}/projects/{project_hash}` | `remove_project_from_group` | `sp_remove_project_from_group` | |

The helpers live in `src/Util/db/db_user_groups.py` and `src/Util/db/db_project_groups.py`; the
procedures in `schemas/stored_procedures/02_user_groups.sql` and
`schemas/stored_procedures/04_project_groups.sql`.

The bulk route loops over `user_hashes`, looks up each user and calls the same helper as the
single add. It logs one `bulk_group_assignment` activity entry with the success count.

## Teardown with session revocation

The four teardown routes follow the same order:

```text
1. snapshot   affected user IDs and project IDs (before the change)
2. mutate     run the stored procedure
3. revoke     revoke_project_sessions_losing_access(user_ids, project_ids, reason)
```

| Route | Users snapshot | Projects snapshot |
| --- | --- | --- |
| `DELETE /admin/user-groups/{group_hash}` | `get_users_in_group` | `get_projects_for_user_group` |
| `DELETE /admin/user-groups/{group_hash}/project-groups/{project_group_hash}` | `get_users_in_group` | `get_projects_in_group` (the project group's projects) |
| `DELETE /admin/project-groups/{group_hash}` | `get_users_with_access_to_project_group` | `get_projects_in_group` |
| `DELETE /admin/project-groups/{group_hash}/projects/{project_hash}` | `get_users_with_access_to_project_group` | The removed project only |

The snapshot must come first: after the change the procedures that list users and projects no
longer return the deactivated links. The revocation step itself is described in
[architecture](architecture.md#session-revocation).

## Access re-check on every request

Group changes reach existing sessions through validation, not only through revocation. Every
request that carries an access token runs `reconstruct_auth_context()` in
`src/Util/auth_lifecycle.py` against the database:

```text
session:{access_jti} found and family active
  -> project from the session: must exist, be active and not archived
  -> root:      no further check
  -> admin:     project must be in sp_get_admin_assigned_projects
  -> consumer:  sp_get_user_groups_in_project_by_hash must return at least one group;
                permissions are re-read from the global role
  -> any failure: refresh family revoked (or the access session), request gets 401
```

So a user removed from a group loses the project on the next request even though
`DELETE /admin/user-groups/{group_hash}/members/{user_hash}` revokes nothing itself. New grants
work the other way: a consumer session stays bound to its project, and the user reaches a newly
granted project by logging in with its `project_hash` or calling `POST /auth/switch-project`
([authentication](../authentication-usage-cases.md)).

After the context passes, the validated login object may be served from `session_full:{access_jti}`
(`VALIDATE_CACHE_TTL`, default `30` seconds), so the group names attached to a session can lag
a change by that long. The access decision itself does not.
