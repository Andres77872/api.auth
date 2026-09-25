# Roles troubleshooting

Symptom, cause, fix. Error codes are listed in [Roles reference](reference.md#errors); how roles turn
into permissions is in [Permission resolution](../permissions/resolution.md).

## Access denied

### `403` "Admin permission required" for a consumer that has `manage_roles`

**Cause.** The `/roles` guard checks `manage_roles` through the caller's **role** only, live from the
database. A grant through a user group or a direct assignment shows up in
`GET /permissions/users/me/permissions` and opens the `/permissions` admin routes, but not `/roles`.

**Fix.** Put `manage_roles` in a group linked to the caller's role. It is a reserved name, so root has
to do it; see [Delegate role management to a consumer](scenarios.md#delegate-role-management-to-a-consumer).

### `403` "Only root users may ..."

**Cause.** The change involves a [reserved permission name](reference.md#reserved-permission-names):
creating or editing one, moving it into or out of a group, linking or unlinking a group that contains
one, editing or deleting a role that grants one, assigning, replacing, or removing such a role (also
in bulk), or assigning or removing a permission group that contains one through `/permissions`.
`admin` users are not root and are blocked too.

**Fix.** Have a `root` user make the change.

### `403` `AUTHZ_2009` "You cannot change your own role"

**Cause.** Non-root callers cannot `PUT` or `DELETE` their own role, or list themselves in a bulk
assignment.

**Fix.** Ask another administrator or a root user.

### `403` `AUTHZ_2009` "Cannot delete system roles"

**Cause.** The role has `is_system_role = 1`, which can only be set in the database.

**Fix.** Leave it, or change the flag in the database if it should be deletable. System roles can
still be edited with `PUT`.

### A role change does not show up in the user's session

**Cause.** Validated sessions are cached for `VALIDATE_CACHE_TTL` seconds (default `30`); see
[When changes take effect](../permissions/resolution.md#when-changes-take-effect). For `root` and
`admin` users the role never affects session permissions.

**Fix.** Wait, or have the user call `POST /auth/refresh`; a new login is not required. The user can
confirm the role side under `sources.from_role` in `GET /permissions/users/me/permission-sources`.

## Unexpected results

### A deleted role, group, or permission returns `404`, and recreating it returns `409`

**Cause.** Deletes are soft. Lookups by hash see active rows only, while the unique name constraint
covers deleted rows too, compared case- and accent-insensitively.

**Fix.** Pick a new name. Restoring a deleted object is a database operation.

### A user whose role was deleted still shows it in `users.role_id`

**Cause.** Deleting a role does not clear `users.role_id`. The role grants nothing (at auth time or in
`/permissions/users/me/permissions`) and `GET /roles/users/{user_hash}/role` returns `role: null`,
but the reference stays.

**Fix.** Assign another role, or clear it with `DELETE /roles/users/{user_hash}/role` (this works
because `role_id` is still set).

### A deleted permission group still grants its permissions

**Cause.** The database still runs resolver procedures from before this was fixed: every resolver now
checks the group's own flag, so a deleted group grants nothing through any source.

**Fix.** See [A deleted permission group still grants its permissions](../permissions/troubleshooting.md#a-deleted-permission-group-still-grants-its-permissions).

### `PUT` returns `200` but nothing changed

**Cause.** Either the body was JSON, which these routes do not read (every optional field is then
omitted), or the fields were empty strings, which count as omitted. Omitted fields keep their values,
so a description cannot be cleared.

**Fix.** Send form fields with non-empty values. Names cannot be changed at all; see
[Rename a role](scenarios.md#rename-a-role).

### `404` `NF_4004` when unlinking or removing from a catalog

**Cause.** The group is not linked to the role, the permission is not in the group, or the role is not
in the project catalog (never added, or already removed). The objects themselves exist; a missing
object returns its own code (`NF_4007`, `NF_4011`, `NF_4005`, `NF_4002`).

**Fix.** Nothing to undo. Adding is idempotent if you need the link back.

### `500` `INT_7001` when removing a user's role

**Cause.** The user has no role. The removal updates zero rows and the route reports that as a
failure (known defect).

**Fix.** Check `GET /roles/users/{user_hash}/role` first; a `null` role on an active user whose role was
never deleted means there is nothing to remove.

### List results stop early or `pagination.total` looks wrong

**Cause.** `pagination.total` is the number of items in the current page, not the overall count.
`limit` is capped at `100`.

**Fix.** Page with `offset` until a page returns fewer than `limit` items.

### The project role catalog did not restrict anything

**Cause.** The catalog is metadata for UIs. Any active role can be assigned to any active user.

**Fix.** Enforce the restriction in your client, or control access through roles and groups.

### Bulk role assignment returns 404 or leaves only one role

**Cause.** `POST /admin/projects/{project_hash}/bulk-assign-roles` takes role **names**, and resolves
every one before writing: an unknown or inactive name (or a role hash sent by mistake) returns `404`
`NF_4007` and nothing is assigned. A user holds one global role, so with several `role_names` each user
ends up with the last one. An unknown project returns `404` `NF_4004`.

**Fix.** Send one active role name per request. Per-user failures (for example `"User not found"` for an
unknown or inactive user) come back in `results` and `errors` of the `200` response.
