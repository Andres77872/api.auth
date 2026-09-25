# Permissions troubleshooting

Symptom, cause, fix. The rules behind most of these are in [Permission resolution](resolution.md).

## Access denied

### A permission shows in `/permissions/users/me/permissions` but the route still returns 403

**Cause.** That list is the inspection view: role, user groups, and direct assignments together.
Route guards use the auth-time set, which for a consumer comes only from the global role. A
permission reached through a user group or a direct assignment is honored by one guard only, the
`/permissions` admin fallback for `manage_roles`.

**Fix.** Check `GET /permissions/users/me/permission-sources`. If the group is not under
`from_role`, link it to the user's role or give the user a role that has it
([Roles usage](../roles/usage.md)). If it is under `from_role`, see
[Changes take up to 30 seconds to apply](#changes-take-up-to-30-seconds-to-apply). If it still fails,
the route has another condition (project access, admin scope, root only); check that route's suite.

### A consumer can use the `/permissions` admin routes but not `/roles`

**Cause.** The two admin guards differ. `/permissions` accepts `manage_roles` from any source;
`/roles` accepts it only from the caller's role, and session-based guards such as
`/admin/project-groups` read the role-derived set too.

**Fix.** For `/roles` access, the permission must come from the role. `manage_roles` is a reserved
name, so only root can put it into a role's groups or assign such a role, and only root can assign or
remove a group containing it through `/permissions`. Review who holds the delegating group with
`GET /permissions/permissions/groups/{pg_hash}/users` and `.../user-groups`.

### A `root` or `admin` user gets `has_permission: false`

**Cause.** The inspection endpoints have no user-type bypass and never include the built-in session
permissions of `root` and `admin`.

**Fix.** None needed. Guards admit `root` and `admin` by user type; the check endpoint answers only
from assignments.

## Stale or unexpected results

### Changes take up to 30 seconds to apply

**Cause.** Access-token validation returns a cached context (`session_full:{access_jti}`) for
`VALIDATE_CACHE_TTL` seconds (default `30`). API-key validation is cached for `60` seconds.

**Fix.** Wait, or refresh the token (`POST /auth/refresh`), which mints a new cache key. A new login
is not required. The `/permissions/users/me/...` endpoints are never cached.

### `/me/permissions` lists a permission that `/me/permission-sources` does not explain

**Cause.** The three procedures resolve the same permission groups with the same `is_active` checks,
so on current procedures they agree. A mismatch means the database still runs resolver procedures from
older schema files, which ignored soft-deleted roles, permission groups, and user groups.

**Fix.** Re-apply the procedures (see the next entry). See
[Soft-delete effects](resolution.md#soft-delete-effects).

### A deleted permission group still grants its permissions

**Cause.** The database still runs resolver procedures from older schema files. Current procedures
check the permission group's own flag in every resolver, so a deleted group grants nothing, at auth
time or in the inspection endpoints, even while role links and assignments to it remain.

**Fix.** Re-create the procedures with `python scripts/schema_sync.py --apply` (it re-runs
`schemas/stored_procedures/05_global_roles.sql` and `06_permission_assignments.sql`, which only drop
and re-create procedures). Existing sessions pick the change up within `VALIDATE_CACHE_TTL` seconds.

## Request errors

### `404` `NF_4011` for a permission group that exists

**Cause.** The group is soft-deleted. Every lookup by hash filters on `is_active`, and a deleted
group's name stays taken.

**Fix.** Create a new group with a different `group_name` (`POST /roles/permission-groups`).

### `404` `NF_4001` or `NF_4003` for the target

**Cause.** The target user or user group does not exist or is inactive. These routes look up active
rows only.

**Fix.** Use the hash of an active user or user group; see the [users](../users/README.md) and
[groups](../groups/README.md) suites.

### `400` `VAL_3001` "Request validation failed" on a write

**Cause.** A required form field is missing. A JSON body is not parsed at all, so every field reads
as missing.

**Fix.** Send `application/x-www-form-urlencoded` or `multipart/form-data`. For bulk assignment,
repeat `permission_group_hashes` once per hash.

### Bulk assignment returns 200 but some groups were not assigned

**Cause.** Items are processed one by one; failures are reported per item, not as an HTTP error.

**Fix.** Compare `success_count` with `total_count` and read `results[].error`. An unknown or
deleted hash reports `"Permission group not found"`.

### A removal returns 200 but the user still has the group

**Cause.** Removals are idempotent and only touch their own path. Removing a direct assignment does
not affect the same group arriving through the role or a user group.

**Fix.** Check `GET /permissions/users/me/permission-sources` as the user, then remove the link on
the path it actually comes from.
