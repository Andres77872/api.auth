# Projects usage

One section per task. `$ROOT_TOKEN` is a root access token; `$TOKEN` is any access token allowed
for the route (see the [authorization matrix](reference.md#authorization-matrix)). Field rules and
full response shapes are in [reference.md](reference.md).

## Create a project

`POST /projects` (root only) — form fields `project_name` (required) and `project_description`:

```bash
curl -X POST "http://localhost:8000/projects" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  --data-urlencode "project_name=Customer API v2" \
  --data-urlencode "project_description=Customer management API"
```

```json
{
  "success": true,
  "message": "Project \"Customer API v2\" created successfully",
  "project": {
    "project_hash": "7D41C09E5A2B8F36",
    "project_name": "Customer API v2",
    "project_description": "Customer management API",
    "created_at": "2026-09-24T10:30:00",
    "updated_at": null
  }
}
```

The caller becomes creator and owner. The project is created with an empty default project group
and three empty user groups (`admin_<project_id>`, `user_<project_id>`, `readonly_<project_id>`),
so nobody except root can reach it yet. Next steps are in
[Set up a new project](scenarios.md#set-up-a-new-project).

## List projects

`GET /projects` — query `limit` (default `10`, max `500`), `offset`, `search`:

```bash
curl "http://localhost:8000/projects?limit=50&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

What comes back depends on the caller: root sees every active, non-archived project, an admin
user sees their assigned projects, and everyone else sees the projects they reach through groups.
`search` filters by name or description for root and admin users only.

For root callers `pagination.total` is the page size and `has_more` is always `false`. Page until
a page returns fewer than `limit` rows.

## Get a project

```bash
curl "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Returns the project, the caller's `user_access`, `statistics` and the `project_groups` that contain
the project. Callers without admin scope need group reach, or they get `403` `AUTHZ_2003`.
`statistics` holds group-based access counts
([project statistics](reference.md#project-statistics)).

## Update a project

`PUT /projects/{project_hash}` — form fields `project_name` and/or `project_description`:

```bash
curl -X PUT "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "project_description=Customer platform backend"
```

Root, or an admin user assigned to the project. Omitted fields keep their value, and a description
cannot be cleared. Metadata changes do not affect access.

## See who can access a project

Users, paginated (`limit` 1-100) and optionally filtered by `user_type`:

```bash
curl "http://localhost:8000/projects/$PROJECT_HASH/members?limit=100&user_type=consumer" \
  -H "Authorization: Bearer $TOKEN"
```

User groups that reach the project through its project groups:

```bash
curl "http://localhost:8000/projects/$PROJECT_HASH/groups" \
  -H "Authorization: Bearer $TOKEN"
```

Both need admin scope over the project. The member list includes every active root user.

## Read the activity feed

```bash
curl "http://localhost:8000/projects/$PROJECT_HASH/activity?days=7&activity_type=user_login&limit=100" \
  -H "Authorization: Bearer $TOKEN"
```

Entries are newest first; `days` is 1-365 (default `30`). Same access rule as reading the project.
Activity types are listed in the [audit logs reference](../audit_logs/reference.md).

## Read project statistics

```bash
curl "http://localhost:8000/projects/$PROJECT_HASH/stats" \
  -H "Authorization: Bearer $TOKEN"
```

Returns the project summary, the same `statistics` object as the details route (`total_users`,
`active_sessions`, `total_groups`, `total_project_groups`, `group_distribution`) and
`generated_at`. `active_sessions` is always `null`. For a count that includes root users, use
`pagination.total` from the members route.

## Give users access to a project

Access is managed from the groups side; no `/projects` route adds a user. The three steps, all
documented in [groups usage](../groups/usage.md):

1. Put the project in a project group: `POST /admin/project-groups/{group_hash}/projects`.
2. Grant a user group that project group: `POST /admin/user-groups/{group_hash}/project-groups`.
3. Add users to the user group: `POST /admin/user-groups/{group_hash}/members`.

A new project's default groups already satisfy steps 1 and 2, so adding a user to
`user_<project_id>` is enough ([example](../groups/scenarios.md#use-a-projects-default-groups)).

## Delete a project

```bash
curl -X DELETE "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Root, or an admin user assigned to the project. The soft delete:

- sets `projects.is_active = 0`, after which the project returns `404` on every route;
- deactivates the project's rows in `project_group_members`, so no group reaches it;
- access tokens scoped to it fail with `401` on their next
  use.

The default project group and user groups are kept. There is no undelete route.

## Transfer ownership or archive (not implemented)

Both routes validate the request and then return `501` `INT_7006`:

```bash
curl -X PATCH "http://localhost:8000/projects/$PROJECT_HASH/owner" \
  -H "Authorization: Bearer $TOKEN" \
  -d "new_owner_hash=$USER_HASH"

curl -X PATCH "http://localhost:8000/projects/$PROJECT_HASH/archive" \
  -H "Authorization: Bearer $TOKEN" \
  -d "archived=true"
```

Before the `501` they still return `400` for a missing field, `403` for a caller without admin
scope and `404` for an unknown project or new owner. Nothing is changed. Archive state is enforced
everywhere else; see [archive state](architecture.md#archive-state).
