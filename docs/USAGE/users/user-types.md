# User types

Every account has a `user_type` of `root`, `admin` or `consumer`. The type decides which operator
routes a user may call; project reach still comes from user-group membership. This page covers the
`/user-types` routes and the other ways a type changes. Field and response tables are in the
[reference](reference.md#user-types-routes).

## The three types

| Type | Reach | Created by | Can |
| --- | --- | --- | --- |
| `root` | Every active project | `POST /user-types/root` (root), or the bootstrap in [Getting started](../getting-started.md) | Everything, including hard delete, type changes and admin assignment |
| `admin` | Projects whose admin group they belong to, plus any normal group reach | `POST /user-types/admin` (root) or a type change | Manage non-root users in their scope: list, read, update, deactivate, soft-delete (singly or in bulk), send reset links, list their addresses and resend activation |
| `consumer` | Projects reached through their user groups | `POST /auth/register` or a type change | Their own profile, access summary and email addresses |

`capabilities` in type-info responses are fixed per type (see [Enums](reference.md#enums)); they are
descriptive and are not checked by the routes.

## How admin assignment works

An admin "administers" a project by being a member of that project's `admin_<project_id>` user group.
`POST /projects` creates that group (with `user_` and `readonly_` groups) and grants it the project,
but adds nobody. The admin assignment routes below only add or remove that membership.

- Assignments are read live on each request, so removing an assignment or demoting an admin takes
  effect on the next call, and the admin's session for that project stops validating.
- The routes take the internal project ID (`proj-...`, the project's `id`), not the `project_hash`.
  It appears as `project_id` in `GET /user-types/admin/{user_hash}/projects` and in the `user_type_info`
  of users who reach the project (`accessible_projects`, or `accessible_projects_details` for
  consumers, in `GET /users/{user_hash}`).
- Some routes scope an admin by *assigned* projects and others by every project the admin can
  *reach*; see [Caller rules](reference.md#caller-rules).

## Create a root user

`POST /user-types/root` (root only)

```bash
curl -X POST "http://localhost:8000/user-types/root" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  --data-urlencode "username=new_root" \
  --data-urlencode "password=$INITIAL_PASSWORD" \
  --data-urlencode "email=root@example.com"
```

The password must pass the shared policy (`400`, `VAL_3007`). `email` is optional and only fills the
legacy `users.email` column; no activation email is sent. The new user needs no project or group.

## Create an admin user

`POST /user-types/admin` (root only)

```bash
curl -X POST "http://localhost:8000/user-types/admin" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  --data-urlencode "username=ops_admin" \
  --data-urlencode "password=$INITIAL_PASSWORD" \
  -d "assigned_project_ids=$PROJECT_ID_1&assigned_project_ids=$PROJECT_ID_2"
```

- Send `assigned_project_ids` (repeated) or a single `assigned_project_id`; at least one is required
  (`400`, `VAL_3002`). Every ID must exist (`404`, `NF_4002`) before the user is created.
- The user is added to each project's admin group. A project without an admin group is skipped: the
  response's `assigned_project_ids` and `assigned_projects` list only the projects actually assigned,
  and `skipped_projects` lists the others with `reason: "no_admin_group"`. The user is created either
  way.
- `primary_project_id` is the first assigned project (`null` if every project was skipped); it is
  informational only.

## Inspect a user's type

`GET /user-types/{user_hash}/info` (root, or an admin for users in their scope)

```bash
curl "http://localhost:8000/user-types/$USER_HASH/info" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Returns `user_type`, `capabilities` and, for admin targets, `assigned_projects`,
`total_assigned_projects` and `assigned_project_id` (the first assigned project by name). Root users
are outside every admin's scope (`403`). Use `GET /users/{user_hash}` for groups and effective
permissions.

## Change a user's type

Three routes change `user_type`. Only one of them assigns an admin project.

| Route | Caller | Assigns an admin project | Notes |
| --- | --- | --- | --- |
| `PUT /user-types/{user_hash}/type` | Root | Yes, `assigned_project_id` is required for `admin` | Preferred for promotions |
| `PATCH /users/{user_hash}/type` | Root | No | Returns `previous_type` and `new_type` |
| `PUT /users/{user_hash}` with `user_type` | Root | No | Can change username and legacy email in the same call |

When the type actually changes, each of them (and bulk update with `user_type`) signs the user out
everywhere: their access sessions and refresh tokens are revoked, because a session carries the type
it was issued for. The user signs in again to get a session of the new type. Setting the type a user
already has keeps their sessions.

### Promote a user to admin

```bash
curl -X PUT "http://localhost:8000/user-types/$USER_HASH/type" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -d "user_type=admin&assigned_project_id=$PROJECT_ID"
```

The response's `user_type_info` lists the new admin's `assigned_projects`. A project without an admin
group returns `404` (`NF_4003`) before anything changes. Add more projects afterwards with
[`POST .../projects/add`](#add-one-project).

> [!CAUTION]
> Promoting with `PATCH /users/{user_hash}/type`, `PUT /users/{user_hash}` or bulk update creates an
> admin with no assigned project. Until you add one, that admin cannot sign in to any project (platform
> login still works) and the scope-based routes show them nobody but themselves.

### Demote an admin

Remove the admin's projects **before** changing the type. The assignment routes answer `400` for a
user who is no longer an admin, and the `admin_<project_id>` memberships stay in place after a
demotion, so the demoted user keeps consumer reach to those projects.

```bash
# 1. See what the admin has
curl "http://localhost:8000/user-types/admin/$ADMIN_HASH/projects" \
  -H "Authorization: Bearer $ROOT_TOKEN"

# 2. Remove each project
curl -X DELETE "http://localhost:8000/user-types/admin/$ADMIN_HASH/projects/$PROJECT_ID" \
  -H "Authorization: Bearer $ROOT_TOKEN"

# 3. Change the type
curl -X PUT "http://localhost:8000/user-types/$ADMIN_HASH/type" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -d "user_type=consumer"
```

If the type was already changed, remove the leftover membership with
`DELETE /admin/user-groups/{group_hash}/members/{user_hash}` (see the [groups suite](../groups/README.md)).

## List users by type

`GET /user-types/users/{user_type}` (root or admin)

```bash
curl "http://localhost:8000/user-types/users/consumer?limit=50&offset=0" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

- Only active users are listed. `limit` defaults to `50` and is capped at `100`.
- Root sees every user of the type; `pagination.total` is the global count.
- Admins get `403` (`AUTHZ_2002`) for `root`. For `admin` and `consumer` they see only users who reach
  one of their assigned projects, sorted by username, and `filter.project_filter` lists those project
  hashes. An admin with no assignment sees nobody.
- Admin items carry `assigned_project` (their first assigned project) when they have one; use the
  admin projects route for the full set.

## User type statistics

`GET /user-types/stats` (root or admin)

```bash
curl "http://localhost:8000/user-types/stats" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Returns `total_users` and a `count` and `percentage` per type, counting active users only. The counts
are system-wide for every caller. For an admin, `scope` is `{"type": "project_admin", ...}` naming
their first assigned project by name; for root it is `{"type": "global_root", "access": "unrestricted"}`.

## Admin project assignment lifecycle

All four routes are root-only, take an admin's `user_hash`, and return `400` (`VAL_3001`) when the
target is not currently an `admin`.

### List an admin's projects

```bash
curl "http://localhost:8000/user-types/admin/$ADMIN_HASH/projects" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

`assigned_at` and `assigned_by` describe when the project's admin group was granted the project, not
when this admin joined it.

### Replace all projects

```bash
curl -X PUT "http://localhost:8000/user-types/admin/$ADMIN_HASH/projects" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -d "assigned_project_ids=$PROJECT_ID_1&assigned_project_ids=$PROJECT_ID_3"
```

Every ID is checked first (`404`, `NF_4002`, and nothing changes). Then projects missing from the list
are removed and new ones added. If some steps fail, the status is still `200` but `success` is `false`
and `message` lists the failed project IDs; `assigned_projects` shows the resulting set. The field is
required, so this route cannot clear every assignment; remove the last project with the delete
route.

### Add one project

```bash
curl -X POST "http://localhost:8000/user-types/admin/$ADMIN_HASH/projects/add" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -d "project_id=$PROJECT_ID"
```

Adding a project the admin already has succeeds without change. A project with no admin group returns
`404` (`NF_4003`).

### Remove one project

```bash
curl -X DELETE "http://localhost:8000/user-types/admin/$ADMIN_HASH/projects/$PROJECT_ID" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

Removes the admin from every admin group of that project. If the admin is not assigned to it, the
route returns `404` (`NF_4003`).
