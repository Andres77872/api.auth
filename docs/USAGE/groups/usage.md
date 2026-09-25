# Groups usage

One section per task. Examples use `$TOKEN` for an access token whose session carries `admin` or
`manage_users` (user-group routes) or `admin` or `manage_roles` (project-group routes). Field
rules and full response shapes are in [reference.md](reference.md).

## Create a user group

`POST /admin/user-groups` — form fields `group_name` (required) and `description`:

```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "group_name=platform_team" \
  --data-urlencode "description=Platform engineering team"
```

```json
{
  "success": true,
  "message": "User group \"platform_team\" created successfully",
  "user_group": {
    "group_hash": "9F2C4A7E1B3D5F60",
    "group_name": "platform_team",
    "description": "Platform engineering team",
    "member_count": null,
    "created_at": "2026-09-24T10:30:00",
    "updated_at": null
  }
}
```

The group starts with no members and no grants. A name already used by any user group, including
a deleted one, returns `409`. Names starting with `admin_` need a root caller.

## List and search user groups

`GET /admin/user-groups` — query `limit` (default `50`, max `1000`), `offset`, `sort_by`,
`sort_order`, `search`:

```bash
curl "http://localhost:8000/admin/user-groups?search=platform&sort_by=created_at&sort_order=desc" \
  -H "Authorization: Bearer $TOKEN"
```

Each item has `member_count` (active users). `pagination.total` ignores `search`.

## Inspect a user group

`GET /admin/user-groups/{group_hash}` returns the members, the granted project groups and the
projects they reach:

```bash
curl "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Read `accessible_project_groups` for the grants and `accessible_projects` for the active,
non-archived projects behind them. For a paginated member list use the members route below.

## Rename or describe a user group

`PUT /admin/user-groups/{group_hash}` — form fields `group_name` and/or `description`; omitted
fields keep their value:

```bash
curl -X PUT "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "description=Platform engineering and shared services"
```

A description cannot be cleared. Renaming does not change access.

## Add members

### Add one user

`POST /admin/user-groups/{group_hash}/members` — form field `user_hash`:

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/members" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hash=$USER_HASH"
```

The user immediately reaches every project behind the group's grants. Adding a current or former
member reactivates the membership and returns `200`.

### Add up to 100 users

`POST /admin/user-groups/{group_hash}/members/bulk` takes a JSON body, unlike the other group
routes:

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_hashes": ["'"$USER_A"'", "'"$USER_B"'"]}'
```

The status is `200` whenever the group exists, even if every user failed. Check
`summary.error_count` and `errors[]`.

## List members and memberships

Members of one group, sorted by username (`limit` 1-100, default `50`):

```bash
curl "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/members?limit=100&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

Groups one user belongs to:

```bash
curl "http://localhost:8000/admin/user-groups/users/$USER_HASH/groups" \
  -H "Authorization: Bearer $TOKEN"
```

Both return `joined_at`, the time the membership was last activated.

## Remove a member

```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/members/$USER_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `200` even if the user was not a member. The user's sessions are not revoked by this call;
an access token for a project the user no longer reaches fails with `401` on its next use.

## Create a project group and add projects

`POST /admin/project-groups` — form fields `group_name` (required) and `description`:

```bash
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "group_name=backend_services" \
  --data-urlencode "description=Backend APIs"
```

`POST /admin/project-groups/{group_hash}/projects` — form field `project_hash`:

```bash
curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$PROJECT_HASH"
```

Members of every user group already granted this project group gain the project at once.

## Inspect a project group

```bash
curl "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

`assigned_projects` lists the active, non-archived projects in the group. There is no separate
list route for a project group's projects.

## Rename or describe a project group

`PUT /admin/project-groups/{group_hash}` — form fields `group_name` and/or `description`; omitted
fields keep their value:

```bash
curl -X PUT "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "group_name=backend_platform"
```

Sending neither field returns `500` rather than `400`. Renaming does not change access.

## Remove a project from a project group

```bash
curl -X DELETE "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Users who reached the project only through this group lose it, and their sessions scoped to that
project are revoked.

## Grant a user group access to a project group

`POST /admin/user-groups/{group_hash}/project-groups` — form field `project_group_hash`:

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_group_hash=$PROJECT_GROUP_HASH"
```

This is the only way to give a user group project access. Re-granting reactivates the existing
grant. List a group's grants with:

```bash
curl "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN"
```

## Revoke a grant

```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Members lose the project group's projects unless another grant still covers them, and their
sessions for the lost projects (with the refresh-token families) are revoked. Revoking a grant
that is not active returns `500`.

## Attach a permission group to a user group

Permission groups are managed by the permissions suite and do not affect project reach:

```bash
curl -X POST "http://localhost:8000/permissions/admin/user-groups/$USER_GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "permission_group_hash=$PERMISSION_GROUP_HASH"
```

> [!IMPORTANT]
> This assignment appears in the permission inspection endpoints but is not part of the
> permission set used for authorization, which comes from global roles. See
> [Permission resolution](../permissions/resolution.md).

## Delete a group

User group:

```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Project group:

```bash
curl -X DELETE "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Both are soft deletes. A user-group delete deactivates its memberships and grants; a project-group
delete deactivates its project assignments and every grant to it. Projects and users are
untouched. Affected users' project sessions are revoked, and the group name stays reserved.

> [!CAUTION]
> To take one project away from a team, revoke the grant or remove the project from the project
> group. Deleting the whole user group also removes every membership and every other grant.
