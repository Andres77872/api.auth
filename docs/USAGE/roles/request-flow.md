# Roles request flow

What happens to a `/roles` request, check by check. Token validation is shared with the permissions
suite and described in
[Permissions request flow](../permissions/request-flow.md#authenticating-the-request).

```text
request ─► middleware ─► HTTPBearerOrCookie ─► validate_session ─► require_valid_session | require_admin
        ─► form/query validation ─► target lookups (active rows only) ─► reserved-name / own-role checks
        ─► stored procedure or SQL ─► JSON (success: true)
```

FastAPI runs the guard dependency before it validates form and query fields, so an unauthorized
caller gets `401`/`403` rather than `400`.

## Read routes

`require_valid_session` accepts any valid access token. The handler looks the object up through a
procedure that filters on `is_active` (`sp_global_get_role_by_hash`,
`sp_global_get_permission_group_by_hash`, `sp_global_get_permission_by_hash`), so a soft-deleted object
answers `404`. Nested lists (`sp_global_get_role_permission_groups`,
`sp_global_get_permission_group_permissions`) also skip inactive links and inactive objects.

## Admin guard

`require_admin` in `src/routes/global_roles.py`:

1. `validate_session`; failure: `401` `AUTH_1003`.
2. Load the caller including inactive rows. Missing: `404` `NF_4001`; inactive: `403` `AUTH_1005`
   (token validation normally rejects inactive users first).
3. User type `root` or `admin`: pass.
4. Otherwise `db_global_roles.check_user_has_permission(user_id, "manage_roles")` runs
   `sp_global_check_user_has_permission`: a live, role-only lookup that does not use the session
   cache. `false` or a failed lookup: `403` `AUTHZ_2002`.

## Reserved-name and own-role checks

After the target objects are loaded, write routes call `_require_root_for_reserved`:

1. `is_root_user(caller)` (live user type): root skips the check.
2. Otherwise the route's predicate runs: the permission's name is reserved, the group contains a
   reserved permission, or one of the role's groups does (`src/Util/admin_scope.py`). Only active
   groups and permissions are inspected, the same rows the role-derived resolver grants from.
3. True: `403` `AUTHZ_2002` "Only root users may ...".

`PUT` and `DELETE /roles/users/{user_hash}/role` also call `_require_not_own_role`: a non-root caller
targeting itself gets `403` `AUTHZ_2009`.

## Creating a role, group, or permission

Example: `POST /roles/roles`.

1. Admin guard, then form validation (`400` `VAL_3001` for a missing field or `role_priority` outside
   `0`–`100`). `POST /roles/permissions` runs the reserved-name check on `permission_name` here.
2. Generate an internal ID (`role_` plus 16 hex characters) and a 32-character `role_hash` from a
   SHA-256 of the name and timestamp.
3. `sp_global_create_role` inserts the row (`is_system_role = FALSE`, `is_active = TRUE`) and selects
   it back.
4. A duplicate name raises MySQL error 1062: `409` `CONF_5004`.
5. `201` with the row.

Groups (`pg_` IDs, `sp_global_create_permission_group`) and permissions (`perm_` IDs,
`sp_global_create_permission`) follow the same steps.

## Linking and unlinking

`POST /roles/roles/{role_hash}/permission-groups/{group_hash}`:

1. Admin guard.
2. Role lookup (`404` `NF_4007`), group lookup (`404` `NF_4011`).
3. Reserved check on the group.
4. `sp_global_assign_permission_group_to_role` inserts into `role_permission_groups` or re-activates the
   row on its unique key `(role_id, permission_group_id)`.
5. `200`. Nothing is invalidated: holders see the change on their next validation after the
   `session_full` cache entry expires (`VALIDATE_CACHE_TTL`, default `30` seconds).

`DELETE` on the same path runs an `UPDATE ... SET is_active = 0, removed_at = NOW()` on the active row.
Zero rows changed: `404` `NF_4004`. Group-to-permission links
(`/roles/permission-groups/{group_hash}/permissions/{permission_hash}`) work the same way against
`global_permission_group_permissions`, with the reserved check on the permission.

## Assigning a role

`PUT /roles/users/{user_hash}/role`, in order:

1. Admin guard.
2. Target user, including inactive rows. Missing: `404` `NF_4001`; inactive: `403` `AUTH_1005`.
3. Role by `role_hash` (active only): `404` `NF_4007`.
4. Own-role check: `403` `AUTHZ_2009`.
5. Reserved check on the new role **and** on the user's current role: `403` `AUTHZ_2002`.
6. `sp_global_assign_role_to_user` sets `users.role_id`.
7. `200` with short `user` and `role` objects. No session is revoked; consumer permissions follow on
   the next uncached validation.

`DELETE /roles/users/{user_hash}/role` runs steps 1, 2, and 4, reads the current role with
`sp_global_get_user_role` (`null` when soft-deleted), checks it for reserved names, then runs
`UPDATE users SET role_id = NULL`. Zero rows changed, which happens when the user had no role, is
reported as `500` `INT_7001`.

## Deleting

| Route | Checks after the lookup | Write |
| --- | --- | --- |
| `DELETE /roles/roles/{role_hash}` | Reserved (role's groups), then system role (`403` `AUTHZ_2009`) | `sp_global_delete_role`: `roles.is_active = FALSE` |
| `DELETE /roles/permission-groups/{group_hash}` | Reserved (group's permissions) | `UPDATE global_permission_groups SET is_active = 0` only |
| `DELETE /roles/permissions/{permission_hash}` | Reserved (name) | `UPDATE global_permissions SET is_active = 0` only |

The group and permission deletes do not use `sp_global_delete_permission_group` or
`sp_global_delete_permission`, which would also deactivate the group's memberships. Links, user
references, and catalog rows are left as they are. Every resolver checks the role's, group's, and
permission's own flag, so the rows left behind grant nothing; see
[Soft-delete effects](../permissions/resolution.md#soft-delete-effects).

## Catalog

`POST /roles/projects/{project_hash}/catalog/roles/{role_hash}`: admin guard, project lookup (active;
archived projects pass; `404` `NF_4002`), role lookup (`404` `NF_4007`), then
`sp_global_add_role_to_project_catalog`, an upsert that keeps stored `catalog_purpose`/`notes` when the
new value is `NULL`. No reserved-name check applies. `DELETE` runs
`sp_global_remove_role_from_project_catalog`; zero rows affected: `404` `NF_4004`.

## Bulk role assignment

`POST /admin/projects/{project_hash}/bulk-assign-roles` (`src/routes/bulk_operations.py`):

1. FastAPI requires a token (`401`) and both form lists (`400` `VAL_3001`). There is no guard
   dependency, so these come before any permission check.
2. Validate the token inside the handler (`401`) and require `admin` in the session permissions
   (`403` `AUTHZ_2002`).
3. At most 100 users (`400` `VAL_3010`).
4. Project by hash (`404` `NF_4004`).
5. Resolve every distinct role name with an active-only lookup. Any unknown: `404` `NF_4007`, nothing
   written.
6. Non-root caller, the same rules as `PUT`, before anything is written: any role granting a
   reserved name (`403` `AUTHZ_2002`), the caller's own hash in `user_hashes` (`403` `AUTHZ_2009`),
   or a listed user whose current role grants a reserved name (`403` `AUTHZ_2002`, the users in
   `details.user_hashes`). Unknown or inactive users are skipped here and fail per item in step 7.
7. For every user, for every role name in order: look up the active user, then set `users.role_id`.
   Failures are recorded per item; the last role wins.
8. Log a bulk-assignment activity and return `200` with `summary`, `results`, and `errors`.
