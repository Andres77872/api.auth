# Permissions request flow

What happens to a `/permissions` request, from the token to the stored procedure. What the resolved
permissions mean is in [Permission resolution](resolution.md).

## Authenticating the request

Every route in the suite starts the same way.

1. The app middleware runs first (request validation, API audit logging, auth context). The
   auth-context middleware only records the caller on `request.state`; it never rejects.
2. `HTTPBearerOrCookie` takes the token from `Authorization: Bearer ...`, else from the
   `access_token` cookie. No token: `401`. `X-API-Key` is not read.
3. `validate_session(token)` hands a JWT to `validate_access_session`:
   1. decode the access token (signature, expiry, `type`, required claims);
   2. load `session:{access_jti}` from Redis and match it against the claims;
   3. require the refresh family to be active;
   4. `reconstruct_auth_context`: user still exists and is active, session project still active and
      not archived, and for a consumer, still reaches that project through a user group; consumer
      permissions are recomputed from the role;
   5. return `session_full:{access_jti}` if cached (`VALIDATE_CACHE_TTL`, default `30` seconds),
      otherwise build and cache it.

   Any failure: `401` `AUTH_1003`.

```text
request ─► middleware ─► HTTPBearerOrCookie ─► validate_session
                                                 └─ validate_access_session
                                                      ├─ JWT checks
                                                      ├─ Redis session + refresh family
                                                      ├─ reconstruct_auth_context (DB)
                                                      └─ session_full:{jti} cache (30 s)
        ─► require_valid_session | require_admin ─► handler ─► stored procedure ─► JSON
```

## Admin guard

`require_admin` in `src/routes/permission_assignments.py` runs after validation:

1. Load the caller with `get_user_by_hash`.
2. User type `root` or `admin`: pass. There is no project-scope check.
3. Otherwise call `check_user_has_permission_extended(user_id, "manage_roles")`, which runs
   `sp_check_user_has_permission_extended` over role, direct user-group membership, and direct
   assignments, following only active roles, user groups, permission groups, links, and permissions.
   `false`, or an error during the check: `403` `AUTHZ_2002`.

The guard is a FastAPI dependency, so it runs before any path lookup.

## Assigning a permission group

Example: `POST /permissions/admin/user-groups/{group_hash}/permission-groups`.

1. Guard as above.
2. `get_user_group_by_hash` (`sp_get_user_group_by_hash`, active groups only). Missing: `404`
   `NF_4003`.
3. `db_global_roles.get_permission_group_by_hash` (`sp_global_get_permission_group_by_hash`, active
   groups only). Missing: `404` `NF_4011`.
4. `_require_root_for_reserved`: unless `is_root_user(caller)` (live user type), a group containing a
   reserved permission name (active permissions only, `src/Util/admin_scope.py`) gives `403`
   `AUTHZ_2002`. The removal routes run the same check.
5. `sp_assign_permission_group_to_user_group` inserts into `user_group_permission_groups`, or on the
   unique key `(user_group_id, permission_group_id)` re-activates the row and resets
   `assigned_at`/`assigned_by`.
6. On a first insert, trigger `trg_after_ugpermg_insert` writes an `activity_logs` row.
7. `200` with the user group and permission group.

No cache is invalidated: the assignment is not part of any auth-time set.

The direct-user variant resolves the target with `get_user_by_hash` (active users only, `404`
`NF_4001`) and calls `sp_assign_permission_group_to_user`, which also overwrites `notes`. Removals call
`sp_remove_permission_group_from_user_group` or `sp_remove_permission_group_from_user`, which set
`is_active = FALSE`, `removed_at`, and `removed_by` on an active row; the route answers `200` whether
or not a row matched.

## Bulk assignment

`POST /permissions/admin/user-groups/{group_hash}/permission-groups/bulk`:

1. Guard, then resolve the user group (`404` `NF_4003` stops the request).
2. Look up every distinct hash. Non-root caller and any group containing a reserved permission name:
   `403` `AUTHZ_2002` with `details.permission_group_hashes`, nothing written.
3. For each `permission_group_hashes` value, in order: if the group was not found, record
   `success: false`; otherwise run the single-assignment procedure. An exception is caught and
   recorded as that item's `error`.
4. `200` with `results`, `success_count`, and `total_count`. Items are committed one by one; there
   is no rollback.

## Inspecting your own permissions

| Route | Path through the code |
| --- | --- |
| `GET /permissions/users/me/permissions` | `require_valid_session` → `get_user_all_permissions` → `sp_get_user_all_permissions` |
| `GET /permissions/users/me/permissions/check/{permission_name}` | `require_valid_session` → `check_user_has_permission_extended` → `sp_check_user_has_permission_extended` |
| `GET /permissions/users/me/permission-sources` | `require_valid_session` → `get_user_permission_sources` → `sp_get_user_permission_sources`, then grouped by `source_type` in Python |
| `GET /permissions/users/me/permission-groups` | `require_valid_session` → `get_user_permission_groups` → `sp_get_user_permission_groups` |

Each reads the database directly for the caller's `user_hash`; nothing is cached.

## Catalog writes

`POST /permissions/projects/{project_hash}/permission-group-catalog/{pg_hash}`:

1. Guard.
2. `get_project_by_hash` (active projects only; archived projects pass). Missing: `404` `NF_4002`.
3. Permission-group lookup. Missing: `404` `NF_4011`.
4. `sp_add_permission_group_to_project_catalog` inserts into `permission_group_project_catalog`, or
   re-activates the row, keeping stored `catalog_purpose`/`notes` where the new value is `NULL`.
5. `200` with a `note` that the catalog is metadata only.

`DELETE` runs `sp_remove_permission_group_from_project_catalog` and always answers `200`. No
assignment table is touched by either.
