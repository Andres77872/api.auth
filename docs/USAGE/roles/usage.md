# Roles usage

One task per section for the `/roles` API. Examples assume the API at `http://localhost:8000`, an
access token in `$TOKEN`, and form-encoded bodies (curl `-d` sends
`application/x-www-form-urlencoded`). Writes need a `root` or `admin` user, or a consumer whose role
grants `manage_roles`; anything touching a [reserved permission name](reference.md#reserved-permission-names)
needs root. Fields, limits, and response shapes are in [Roles reference](reference.md).

Build in this order: permissions, then permission groups, then roles, then assignments. A role grants
nothing until it has groups, and a group grants nothing until it has permissions and is linked to a
role.

## Manage permissions

### Create a permission

```bash
curl -X POST "http://localhost:8000/roles/permissions" \
  -H "Authorization: Bearer $TOKEN" \
  -d "permission_name=publish_content" \
  -d "permission_display_name=Publish content" \
  -d "permission_category=content"
```

`201` with `permission` (keep `permission_hash`). `permission_name` is the string guards match on and
cannot be changed. A taken name, including one of a deleted permission, returns `409` `CONF_5004`.

### List and read permissions

```bash
curl "http://localhost:8000/roles/permissions?category=content&limit=50&offset=0" \
  -H "Authorization: Bearer $TOKEN"
curl "http://localhost:8000/roles/permissions/$PERMISSION_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Any access token. Active permissions only, ordered by name. `pagination.total` is the size of this
page, not the overall count.

### Update a permission

```bash
curl -X PUT "http://localhost:8000/roles/permissions/$PERMISSION_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  -d "permission_description=Allows publishing and release"
```

Only `permission_display_name`, `permission_description`, and `permission_category` can change.
Omitted fields keep their values.

### Delete a permission

```bash
curl -X DELETE "http://localhost:8000/roles/permissions/$PERMISSION_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Soft delete. The permission stops counting everywhere within about 30 seconds, and its name stays
taken.

## Manage permission groups

### Create a permission group

```bash
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "group_name=editorial" \
  -d "group_display_name=Editorial" \
  -d "group_category=content"
```

`201` with `permission_group` (keep `group_hash`). `group_category` defaults to `general` and is a
free-form label.

### List and read permission groups

```bash
curl "http://localhost:8000/roles/permission-groups?category=content" \
  -H "Authorization: Bearer $TOKEN"
curl "http://localhost:8000/roles/permission-groups/$GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

The single-group read also returns the group's active `permissions`;
`GET /roles/permission-groups/{group_hash}/permissions` returns the same list with a short
`permission_group` object.

### Add a permission to a group

```bash
curl -X POST "http://localhost:8000/roles/permission-groups/$GROUP_HASH/permissions/$PERMISSION_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

No body. Adding again re-activates the membership. Role holders get the permission within about 30
seconds.

### Remove a permission from a group

```bash
curl -X DELETE "http://localhost:8000/roles/permission-groups/$GROUP_HASH/permissions/$PERMISSION_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

`404` `NF_4004` if the permission is not currently in the group.

### Update a permission group

```bash
curl -X PUT "http://localhost:8000/roles/permission-groups/$GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  -d "group_display_name=Editorial team"
```

Only `group_display_name`, `group_description`, and `group_category` can change.

### Delete a permission group

```bash
curl -X DELETE "http://localhost:8000/roles/permission-groups/$GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Deleting a group revokes its permissions from every role, user group, and user it is linked to;
consumers' existing tokens drop them within about 30 seconds. The links themselves stay in place as
history, and a deleted group cannot be restored or unlinked through the API. See
[Retire a permission group cleanly](../permissions/scenarios.md#retire-a-permission-group-cleanly).

## Manage roles

### Create a role

```bash
curl -X POST "http://localhost:8000/roles" \
  -H "Authorization: Bearer $TOKEN" \
  -d "role_name=content_editor" \
  -d "role_display_name=Content editor" \
  -d "role_priority=60"
```

`201` with `role` (keep `role_hash`). `role_priority` (`0`–`100`, default `50`) only orders listings.
New roles are never system roles.

### List and read roles

```bash
curl "http://localhost:8000/roles?limit=50&offset=0" \
  -H "Authorization: Bearer $TOKEN"
curl "http://localhost:8000/roles/$ROLE_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Any access token. Listings are ordered by `role_priority` (highest first), then `role_name`. The
single-role read also returns the linked, active `permission_groups`. A soft-deleted role answers
`404` `NF_4007`.

### Link a permission group to a role

```bash
curl -X POST "http://localhost:8000/roles/$ROLE_HASH/permission-groups/$GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

No body; idempotent. Consumers holding the role get the group's permissions within about 30 seconds,
without a new login. List a role's groups with `GET /roles/{role_hash}/permission-groups`.

### Unlink a permission group from a role

```bash
curl -X DELETE "http://localhost:8000/roles/$ROLE_HASH/permission-groups/$GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

`404` `NF_4004` if the group is not currently linked. Holders lose the permissions unless another
linked group grants them.

### Update a role

```bash
curl -X PUT "http://localhost:8000/roles/$ROLE_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  -d "role_display_name=Senior editor" \
  -d "role_priority=70"
```

Only `role_display_name`, `role_description`, and `role_priority` can change. System roles can be
updated.

### Delete a role

```bash
curl -X DELETE "http://localhost:8000/roles/$ROLE_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Soft delete; `403` `AUTHZ_2009` for a system role. Users keep the reference in `users.role_id`, but
the role grants them nothing, at auth time or in the `/permissions` inspection endpoints, and role
lookups return `null`. Reassign or clear those users afterwards; no endpoint lists a role's holders.

## Assign roles to users

A user holds at most one global role. For consumers it is the only source of auth-time permissions;
for `root` and `admin` users it changes nothing.

### Assign a role

```bash
curl -X PUT "http://localhost:8000/roles/users/$USER_HASH/role" \
  -H "Authorization: Bearer $TOKEN" \
  -d "role_hash=$ROLE_HASH"
```

Replaces any current role. The target must be active (`403` `AUTH_1005` otherwise). A non-root caller
cannot target itself, and needs root if either the new or the current role grants a reserved name.
Bulk assignment (`POST /admin/projects/{project_hash}/bulk-assign-roles`) applies the same rules to
every listed user.
The change reaches the user's existing tokens within about 30 seconds.

### Look up a role

```bash
curl "http://localhost:8000/roles/users/me/role" -H "Authorization: Bearer $TOKEN"
curl "http://localhost:8000/roles/users/$USER_HASH/role" -H "Authorization: Bearer $TOKEN"
```

Any access token can look up any active user. `role` is `null` when the user has no role or the role
is soft-deleted.

### Remove a user's role

```bash
curl -X DELETE "http://localhost:8000/roles/users/$USER_HASH/role" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `previous_role` (`null` if it was soft-deleted). A user with no role at all gets `500`
`INT_7001` instead of a no-op; check with a lookup first.

### Assign one role to many users

`POST /admin/projects/{project_hash}/bulk-assign-roles` takes role **names**:

```bash
curl -X POST "http://localhost:8000/admin/projects/$PROJECT_HASH/bulk-assign-roles" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hashes=$USER_A" \
  -d "user_hashes=$USER_B" \
  -d "role_names=content_editor"
```

- Needs `admin` in the caller's session permissions (every `root` and `admin` session has it).
- Up to 100 `user_hashes`. Every role name must be an active role, otherwise `404` `NF_4007` and
  nothing is assigned.
- The role is global; the project is used only for validation and the audit trail.
- Send one role name. With several, each user ends up with the last one.
- Returns `200` with per-user `results` and `errors`; see
  [Bulk role assignment returns 404 or leaves only one role](troubleshooting.md#bulk-role-assignment-returns-404-or-leaves-only-one-role).

## Manage a project role catalog

A catalog entry suggests a role for a project in UIs. It does not restrict which roles can be
assigned and grants nothing.

### Add a role to a project catalog

```bash
curl -X POST "http://localhost:8000/roles/projects/$PROJECT_HASH/catalog/roles/$ROLE_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "catalog_purpose=Recommended for editors"
```

Idempotent: re-adding re-activates the entry and keeps stored `catalog_purpose`/`notes` you omit. Any
active project can be used, not only the caller's.

### List a project's cataloged roles

```bash
curl "http://localhost:8000/roles/projects/$PROJECT_HASH/catalog/roles" \
  -H "Authorization: Bearer $TOKEN"
```

Any access token; no project-membership check. Ordered by `role_priority`, then name.

### Remove a role from a project catalog

```bash
curl -X DELETE "http://localhost:8000/roles/projects/$PROJECT_HASH/catalog/roles/$ROLE_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

`404` `NF_4004` if the role is not in the catalog. No user's role changes.
