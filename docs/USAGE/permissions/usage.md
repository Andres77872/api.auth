# Permissions usage

One task per section for the `/permissions` API. Examples assume the API at
`http://localhost:8000` and an access token in `$TOKEN`; "admin" routes need a `root` or `admin`
user, or a consumer holding `manage_roles` from any source. Field rules and response shapes are in
[Permissions reference](reference.md). To create permission groups or change a user's role, use
[Roles usage](../roles/usage.md).

> [!IMPORTANT]
> Assignments made here appear in the inspection endpoints but do not change what route guards
> allow a consumer, except the `manage_roles` fallback of these `/permissions` admin routes. To change
> a consumer's auth-time permissions, change the permission groups of their role. See
> [Permission resolution](resolution.md).

Only root may assign or remove a permission group that contains a
[reserved permission name](../roles/reference.md#reserved-permission-names) (`admin`,
`manage_roles`, ...); for anyone else these routes answer `403` `AUTHZ_2002` and write nothing.

## Assign permission groups to a user group

### Assign one group

`POST /permissions/admin/user-groups/{group_hash}/permission-groups` — admin, form field
`permission_group_hash`:

```bash
curl -X POST "http://localhost:8000/permissions/admin/user-groups/$USER_GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "permission_group_hash=$PG_HASH"
```

Returns `user_group` and `permission_group` (`hash`, `name`). Re-assigning a group that was removed
re-activates the same link. Only direct members of the user group are affected; child or parent
groups are not.

### Assign several groups at once

`POST /permissions/admin/user-groups/{group_hash}/permission-groups/bulk` — repeat
`permission_group_hashes` once per hash:

```bash
curl -X POST "http://localhost:8000/permissions/admin/user-groups/$USER_GROUP_HASH/permission-groups/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -d "permission_group_hashes=$PG_A" \
  -d "permission_group_hashes=$PG_B"
```

The response is `200` even if items fail. Compare `success_count` with `total_count` and read the
per-hash `results[].error`. The one exception is a reserved-name group listed by a non-root caller:
the whole request fails with `403` (`details.permission_group_hashes`) and nothing is assigned.

### List a user group's permission groups

```bash
curl "http://localhost:8000/permissions/admin/user-groups/$USER_GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `permission_groups` (active links to active groups, with `assigned_at`) and `count`.

### Remove a group from a user group

```bash
curl -X DELETE "http://localhost:8000/permissions/admin/user-groups/$USER_GROUP_HASH/permission-groups/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `200` whether or not the group was assigned.

## Assign permission groups directly to a user

### Assign a group to a user

`POST /permissions/users/{user_hash}/permission-groups` — admin, form fields
`permission_group_hash` and optional `notes`:

```bash
curl -X POST "http://localhost:8000/permissions/users/$USER_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "permission_group_hash=$PG_HASH" \
  --data-urlencode "notes=Temporary Q3 reporting access"
```

Returns `user`, `permission_group`, and `notes`. Re-assigning overwrites `notes`, and omitting
`notes` clears them. The target user must be active.

### List a user's direct groups

```bash
curl "http://localhost:8000/permissions/users/$USER_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `direct_permission_groups` (with `notes`) and `count`. Groups the user gets through their
role or user groups are not included.

### Remove a direct assignment

```bash
curl -X DELETE "http://localhost:8000/permissions/users/$USER_HASH/permission-groups/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `200` whether or not the group was directly assigned. Role and user-group paths are not
touched.

## Inspect your own permissions

These routes accept any access token and always answer for the caller.

### List your permissions from all sources

```bash
curl "http://localhost:8000/permissions/users/me/permissions" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `permissions` (distinct names from role, user groups, and direct assignments) and `count`.
This is not the list route guards use, and it omits the built-in permissions of `root`/`admin`.

### Check one permission

```bash
curl "http://localhost:8000/permissions/users/me/permissions/check/manage_roles" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `permission` and `has_permission`, from the same three sources. `true` for `manage_roles`
means the caller can use the `/permissions` admin routes; it says nothing about `/roles`.

### See where your permission groups come from

```bash
curl "http://localhost:8000/permissions/users/me/permission-sources" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `sources.from_role`, `sources.from_user_groups`, `sources.from_direct_assignment`, and
`summary` counts. Only `from_role` feeds the auth-time set.

### List your direct permission groups

```bash
curl "http://localhost:8000/permissions/users/me/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

Direct assignments only. Your role is at `GET /roles/users/me/role`.

## Find where a permission group is used

### User groups that have it

```bash
curl "http://localhost:8000/permissions/permissions/groups/$PG_HASH/user-groups" \
  -H "Authorization: Bearer $TOKEN"
```

Admin. Returns active user groups with an active assignment of the group.

### Users with a direct assignment

```bash
curl "http://localhost:8000/permissions/permissions/groups/$PG_HASH/users" \
  -H "Authorization: Bearer $TOKEN"
```

Admin. Returns `users_with_direct_assignment` (including `email`, `user_type`, and `notes`). Users
who get the group through a role or user group are not listed. No endpoint lists the roles that link
a group; walk `GET /roles/roles` and `GET /roles/roles/{role_hash}/permission-groups` instead.

## Catalog permission groups for a project

Catalog entries are suggestions for UIs. They do not grant or restrict anything.

### Add a group to a project catalog

`POST /permissions/projects/{project_hash}/permission-group-catalog/{pg_hash}` — admin, optional form
fields `catalog_purpose` and `notes`:

```bash
curl -X POST "http://localhost:8000/permissions/projects/$PROJECT_HASH/permission-group-catalog/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "catalog_purpose=Recommended for editorial teams"
```

Re-adding re-activates the entry; omitted fields keep their stored values. Any active project can be
used, not only the caller's.

### List a project's catalog

```bash
curl "http://localhost:8000/permissions/projects/$PROJECT_HASH/permission-group-catalog" \
  -H "Authorization: Bearer $TOKEN"
```

Any access token; there is no project-membership check.

### List the projects that catalog a group

```bash
curl "http://localhost:8000/permissions/permissions/groups/$PG_HASH/project-catalog" \
  -H "Authorization: Bearer $TOKEN"
```

### Remove a group from a project catalog

```bash
curl -X DELETE "http://localhost:8000/permissions/projects/$PROJECT_HASH/permission-group-catalog/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `200` whether or not the group was cataloged.
