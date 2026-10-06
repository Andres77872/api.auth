# Projects reference

The contract for `/projects`. Suite-wide rules are in [README.md](README.md#rules-and-caveats).
The routes that give users access to a project (`/admin/project-groups`, `/admin/user-groups`) are
in the [groups reference](../groups/reference.md).

## Endpoints

Every route takes an access token (`Authorization: Bearer <access JWT>` or the `access_token`
cookie). "Admin scope" means root, or an admin user assigned to administer the project.

| Path | Method | Who | Input | Purpose |
| --- | --- | --- | --- | --- |
| `/projects` | GET | Any user type | Query: `limit`, `offset`, `search` | List the projects the caller can see |
| `/projects` | POST | Root | Form: `project_name`, `project_description` | Create a project and its default groups |
| `/projects/{project_hash}` | GET | Admin scope or group reach | Path only | Project, caller's access, statistics, project groups |
| `/projects/{project_hash}` | PUT | Admin scope | Form: `project_name`, `project_description` | Change name and/or description |
| `/projects/{project_hash}` | DELETE | Admin scope | No body | Soft-delete the project |
| `/projects/{project_hash}/members` | GET | Admin scope | Query: `limit`, `offset`, `user_type` | Users who can access the project |
| `/projects/{project_hash}/groups` | GET | Admin scope | Query: `limit`, `offset` | User groups that reach the project |
| `/projects/{project_hash}/activity` | GET | Admin scope or group reach | Query: `limit`, `offset`, `activity_type`, `days` | Activity-log feed for the project |
| `/projects/{project_hash}/stats` | GET | Admin scope or group reach | Path only | Project summary and `statistics` |
| `/projects/{project_hash}/owner` | PATCH | Admin scope | Form: `new_owner_hash` | Not implemented: always `501` after validation |
| `/projects/{project_hash}/archive` | PATCH | Admin scope | Form: `archived` | Not implemented: always `501` after validation |

There are no routes that add or remove a user on a project directly.

## Authorization matrix

The caller's user type and admin assignments are read from the database on each request
(`resolve_admin_scope()` in `src/Util/admin_scope.py`). Session permission names are ignored.

| Caller | `GET /projects` | Read one project (details, activity, stats) | Administer one project | `POST /projects` |
| --- | --- | --- | --- | --- |
| Root | Every active, non-archived project, newest first | Any active project, archived included | Any active project, archived included | Yes |
| Admin user | Assigned projects, by name | Assigned projects; other projects only through group reach | Assigned projects (never archived ones) | `403` `AUTHZ_2002` |
| Consumer, whatever its session permissions | Projects reached through groups, by name | Projects reached through groups | `403` `AUTHZ_2002` | `403` `AUTHZ_2002` |

An admin user acting on a project outside their assignments gets `403` `AUTHZ_2003`. Group reach
never includes archived projects.

## Query parameters

| Route | Parameter | Type | Default | Range | Notes |
| --- | --- | --- | --- | --- | --- |
| `GET /projects` | `limit` | int | `10` | 1-500 | Page size |
| `GET /projects` | `offset` | int | `0` | 0 or more | Ignored for root when `search` is set |
| `GET /projects` | `search` | string | none | | Root and admin callers only: substring of name or description, sorted by name. Whitespace-only returns `400`. Ignored for consumers |
| `GET /projects/{project_hash}/members` | `limit` | int | `50` | 1-100 | Page size |
| `GET /projects/{project_hash}/members` | `offset` | int | `0` | 0 or more | |
| `GET /projects/{project_hash}/members` | `user_type` | string | none | `root`, `admin`, `consumer` | Exact match |
| `GET /projects/{project_hash}/groups` | `limit` | int | `100` | 1-500 | Page size |
| `GET /projects/{project_hash}/groups` | `offset` | int | `0` | 0 or more | |
| `GET /projects/{project_hash}/activity` | `limit` | int | `50` | 1-100 | Page size |
| `GET /projects/{project_hash}/activity` | `offset` | int | `0` | 0 or more | |
| `GET /projects/{project_hash}/activity` | `activity_type` | string | none | | Exact activity type code, for example `user_login` |
| `GET /projects/{project_hash}/activity` | `days` | int | `30` | 1-365 | Look-back window |

## Form fields

Form bodies accept `application/x-www-form-urlencoded` or `multipart/form-data`. An empty value
counts as omitted.

| Field | Route | Required | Rules |
| --- | --- | --- | --- |
| `project_name` | `POST /projects` | Yes | Up to 100 characters; does not have to be unique |
| `project_description` | `POST /projects` | No | Free text |
| `project_name` | `PUT /projects/{project_hash}` | No | Omitted keeps the current name |
| `project_description` | `PUT /projects/{project_hash}` | No | Omitted keeps the current value; it cannot be cleared |
| `new_owner_hash` | `PATCH /projects/{project_hash}/owner` | Yes | Hash of an active user; nothing changes |
| `archived` | `PATCH /projects/{project_hash}/archive` | Yes | Boolean; nothing changes |

`PUT /projects/{project_hash}` needs at least one of the two fields (`400` `VAL_3001` otherwise).

## Response shapes

Every success body has `success: true`. Fields typed by a shared model are always present and may
be `null`.

| Route | Top-level fields |
| --- | --- |
| `GET /projects` | `projects[]`, `pagination`, `user_access_level` (`"admin"` for root and admin users, `"user"` otherwise) |
| `POST /projects` | `message`, `project` (`project_hash`, `project_name`, `project_description`, `created_at`) |
| `GET /projects/{project_hash}` | `project`, `user_access`, `statistics`, `project_groups[]` (`group_hash`, `group_name`, `description`) |
| `PUT /projects/{project_hash}` | `message`, `project` |
| `DELETE /projects/{project_hash}` | `message`, `deleted_project`, `warning` |
| `GET /projects/{project_hash}/members` | `project`, `members[]`, `pagination`, `statistics` |
| `GET /projects/{project_hash}/groups` | `user_groups[]` (`group_hash`, `group_name`, `description`, `member_count`, `created_at`, `updated_at`), `pagination` |
| `GET /projects/{project_hash}/activity` | `project` (`project_hash`, `project_name`), `activities[]`, `pagination`, `filters` (`activity_type`, `days`), `generated_at` |
| `GET /projects/{project_hash}/stats` | `project` (`project_hash`, `project_name`, `project_description`), `statistics`, `generated_at` |

### Project list items

| Caller | `access_level` | `access_through` |
| --- | --- | --- |
| Root or admin user | `admin_access` | `admin_access` |
| Anyone else | `group_access` | `user_group` |

Each item also has `project_hash`, `project_name` and `project_description`.

Pagination: for admin users and consumers `pagination.total` is the full count and `has_more` is
correct. For root, `total` is the number of rows on the page, so `has_more` is always `false`; keep
paging until a page has fewer than `limit` rows.

### Project details

| Field | Content |
| --- | --- |
| `user_access.access_level` | `admin_access` when the caller has admin scope over the project, else `group_access` |
| `user_access.permissions` | The caller's session permissions with admin scope, else `[]` |
| `user_access.user_groups` | Names of all the caller's user groups, not only those that reach this project |
| `project_groups[]` | Active project groups containing the project, including `default_<project_id>` |
| `statistics` | Group-based access counts, see [project statistics](#project-statistics) |

### Project statistics

`statistics` in `GET /projects/{project_hash}` and `GET /projects/{project_hash}/stats` comes from
`sp_get_project_statistics` and has the same shape in both:

| Field | Content |
| --- | --- |
| `total_users` | Distinct users with an active membership in a user group that holds an active grant to a project group containing the project. Root users count only if they are such members |
| `total_groups` | User groups with an active grant to a project group containing the project |
| `total_project_groups` | Project groups the project is actively assigned to |
| `group_distribution` | Object mapping each such user group's name to its active member count, largest first; groups with no members appear with `0` |

```json
{
  "total_users": 12,
  "total_groups": 3,
  "total_project_groups": 2,
  "group_distribution": {"qa_team": 8, "user_proj-5f0c": 4, "admin_proj-5f0c": 1}
}
```

The member list (`GET /projects/{project_hash}/members`) is the complete view: it also lists every
active root user and leaves out inactive users.

### Project members

Members are active users who reach the project through the group chain, plus every active root
user, ordered by user type then username. Archived projects return no members.

| Field | Content |
| --- | --- |
| `user_hash`, `username`, `email`, `user_type`, `is_active`, `created_at` | From the user record |
| `access_level` | `root_access`, `admin_access` or `group_access`, from `user_type` |
| `groups` | Consumers only: names of all their user groups; `[]` for root and admin users |
| `joined_at` | Earliest active grant that reaches the project; project creation time for root users |
| `granted_by` | Always `null` |

`statistics.total_members` is the full count. `root_users`, `admin_users`, `consumer_users` and
`active_members` count only the current page.

### Activity entries

Entries are newest first and include `activity_type`, `activity_name`, `activity_category`,
`details`, `metadata`, `severity_level`, `created_at`, the acting user (`user_id`, `username`,
`user_hash`), any target user, `ip_address` and `user_agent`. `pagination.total` is the filtered
count.

### Not implemented (501)

Both stubs answer with the error envelope:

```json
{
  "status": "error",
  "error": {
    "code": "INT_7006",
    "category": "internal",
    "message": "Project archive/unarchive is not yet implemented"
  }
}
```

The ownership stub's message is `Project ownership transfer is not yet implemented`.

## Error codes

Envelope and catalog: [errors.md](../errors.md).

| Status | Code | When |
| --- | --- | --- |
| `400` | `VAL_3001` | Missing or empty required form field; non-boolean `archived`; `PUT` with nothing to update; query value out of range |
| `400` | `VAL_3002` | Whitespace-only `search` from a root or admin caller |
| `401` | `AUTH_1003` | Missing, invalid or expired access token |
| `403` | `AUTHZ_2002` | Create by a non-root caller; admin route called by a consumer |
| `403` | `AUTHZ_2003` | Admin user outside their assignments; read route without admin scope or group reach |
| `404` | `NF_4002` | Unknown or deleted `project_hash` |
| `404` | `NF_4001` | Unknown or inactive `new_owner_hash`; caller's own user record missing on `GET /projects` |
| `500` | `INT_7001` | The database layer returned no result on create, update or delete |
| `501` | `INT_7006` | `PATCH /projects/{project_hash}/owner` and `PATCH /projects/{project_hash}/archive` after validation passes |
