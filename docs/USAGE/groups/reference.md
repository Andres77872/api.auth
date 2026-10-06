# Groups reference

The contract for `/admin/user-groups` and `/admin/project-groups`. Suite-wide rules (permissions,
the `admin_` guard, soft deletes) are in [README.md](README.md#rules-and-caveats).

## Authorization

Every route takes an access token (`Authorization: Bearer <access JWT>` or the `access_token`
cookie). The dependency reads the permission names in the validated session.

| Prefix | Dependency | Session must carry | Extra rule |
| --- | --- | --- | --- |
| `/admin/user-groups` | `require_admin` in `src/routes/admin_user_groups.py` | `admin` or `manage_users` | Writes to a group named `admin_...` need a root caller |
| `/admin/project-groups` | `require_admin` in `src/routes/admin_project_groups.py` | `admin` or `manage_roles` | None |

A missing or invalid token returns `401` `AUTH_1003`. A missing permission returns `403`
`AUTHZ_2002` ("Admin or manage_users permission required" or "Admin or manage_roles permission
required"). A non-root write to an `admin_...` group returns `403` `AUTHZ_2002` ("Only root users
may change project admin groups").

## User group endpoints

The "`admin_` guard" column marks routes that refuse non-root callers when the group's current
name (or, for create and rename, the new name) starts with `admin_`.

| Path | Method | Input | `admin_` guard | Purpose |
| --- | --- | --- | --- | --- |
| `/admin/user-groups` | GET | Query: [list parameters](#list-parameters) | No | List active user groups with member counts |
| `/admin/user-groups` | POST | Form: `group_name`, `description` | Yes | Create a user group |
| `/admin/user-groups/{group_hash}` | GET | Path only | No | Group, members, granted project groups, reachable projects |
| `/admin/user-groups/{group_hash}` | PUT | Form: `group_name`, `description` | Yes | Rename and/or change the description |
| `/admin/user-groups/{group_hash}` | DELETE | No body | Yes | Soft-delete the group, its memberships and its grants; revokes sessions |
| `/admin/user-groups/{group_hash}/members` | GET | Query: `limit` (1-100, default `50`), `offset` | No | Page through active members |
| `/admin/user-groups/{group_hash}/members` | POST | Form: `user_hash` | Yes | Add or reactivate one member |
| `/admin/user-groups/{group_hash}/members/bulk` | POST | JSON: `{"user_hashes": [...]}` (1-100) | Yes | Add up to 100 members |
| `/admin/user-groups/{group_hash}/members/{user_hash}` | DELETE | No body | Yes | Remove one member; no session revocation |
| `/admin/user-groups/{group_hash}/project-groups` | GET | Path only | No | List active grants |
| `/admin/user-groups/{group_hash}/project-groups` | POST | Form: `project_group_hash` | Yes | Grant (or re-grant) a project group |
| `/admin/user-groups/{group_hash}/project-groups/{project_group_hash}` | DELETE | No body | Yes | Revoke a grant; revokes sessions |
| `/admin/user-groups/users/{user_hash}/groups` | GET | Path only | No | List the active groups one user belongs to |

## Project group endpoints

| Path | Method | Input | Purpose |
| --- | --- | --- | --- |
| `/admin/project-groups` | GET | Query: [list parameters](#list-parameters) | List active project groups with project counts |
| `/admin/project-groups` | POST | Form: `group_name`, `description` | Create an empty project group |
| `/admin/project-groups/{group_hash}` | GET | Path only | Group and its assigned projects |
| `/admin/project-groups/{group_hash}` | PUT | Form: `group_name`, `description` | Rename and/or change the description |
| `/admin/project-groups/{group_hash}` | DELETE | No body | Soft-delete the group, its project assignments and every grant to it; revokes sessions |
| `/admin/project-groups/{group_hash}/projects` | POST | Form: `project_hash` | Add or reactivate a project in the group |
| `/admin/project-groups/{group_hash}/projects/{project_hash}` | DELETE | No body | Remove a project from the group; revokes sessions |

There is no route that lists a project group's projects on its own. Read `assigned_projects` from
`GET /admin/project-groups/{group_hash}`.

## Request fields

Form bodies accept `application/x-www-form-urlencoded` or `multipart/form-data`. An empty form
value counts as omitted.

| Field | Routes | Required | Rules |
| --- | --- | --- | --- |
| `group_name` | `POST` on either prefix | Yes | Up to 100 characters. Unique among all groups of that kind, deleted ones included, ignoring case |
| `group_name` | `PUT` on either prefix | No | Omitted keeps the current name |
| `description` | `POST`, `PUT` on either prefix | No | Omitted keeps the current value; it cannot be cleared |
| `user_hash` | `POST /admin/user-groups/{group_hash}/members` | Yes | Hash of an active user |
| `user_hashes` | `POST /admin/user-groups/{group_hash}/members/bulk` | Yes | JSON array of 1 to 100 user hashes |
| `project_group_hash` | `POST /admin/user-groups/{group_hash}/project-groups` | Yes | Hash of an active project group |
| `project_hash` | `POST /admin/project-groups/{group_hash}/projects` | Yes | Hash of an active project; archived projects are accepted but grant nothing |

Both `PUT` routes need at least one of `group_name` and `description`. With neither,
`PUT /admin/user-groups/{group_hash}` returns `400` `VAL_3002` but
`PUT /admin/project-groups/{group_hash}` returns `500` `INT_7001`.

## List parameters

`GET /admin/user-groups` and `GET /admin/project-groups` take the same query parameters.

| Parameter | Type | Default | Range | Notes |
| --- | --- | --- | --- | --- |
| `limit` | int | `50` | 1-1000 | Page size |
| `offset` | int | `0` | 0 or more | Rows to skip |
| `sort_by` | string | `group_name` | `group_name`, `created_at`, `updated_at` | Any other value sorts by `group_name` |
| `sort_order` | string | `asc` / `ASC` | `desc` (any case) for descending | Anything else sorts ascending |
| `search` | string | none | | Case-insensitive substring of the group name |

Pagination differs between the two lists:

- `GET /admin/user-groups`: `pagination.total` counts all active user groups and ignores `search`.
  `has_more` is `null`.
- `GET /admin/project-groups`: `pagination.total` respects `search` and `has_more` is set. The list
  includes each project's `default_<project_id>` group.

## Response shapes

Every success body has `success: true` and usually a `message`. Fields typed by a shared model are
always present and may be `null` (for example `member_count` outside the list route).

### User group objects

| Route | Top-level fields |
| --- | --- |
| `GET /admin/user-groups` | `user_groups[]` (`group_hash`, `group_name`, `description`, `member_count`, `created_at`), `pagination` |
| `POST /admin/user-groups`, `PUT /admin/user-groups/{group_hash}` | `user_group` |
| `GET /admin/user-groups/{group_hash}` | `user_group`, `members[]` (`user_hash`, `username`, `email`), `accessible_projects[]` (`project_hash`, `project_name`), `accessible_project_groups[]`, `derived_projects` (always `[]`), `statistics` |
| `DELETE /admin/user-groups/{group_hash}` | `message`, `warning` |
| `GET /admin/user-groups/{group_hash}/members` | `user_group`, `members[]`, `pagination` (with `has_more`), `statistics` (`total_members`, `members_shown`), `generated_at` |
| `POST /admin/user-groups/{group_hash}/members` | `assignment` (`user`, `group`, `assigned_by` username) |
| `POST /admin/user-groups/{group_hash}/members/bulk` | `user_group`, `summary`, `results[]`, `errors[]`, `performed_by`, `performed_at` |
| `DELETE /admin/user-groups/{group_hash}/members/{user_hash}` | `message` |
| `GET /admin/user-groups/{group_hash}/project-groups` | `user_group`, `project_groups[]`, `total_project_groups`, `total_derived_projects` (always `0`) |
| `POST /admin/user-groups/{group_hash}/project-groups` | `access_details`, `user_group`, `project_group` |
| `DELETE /admin/user-groups/{group_hash}/project-groups/{project_group_hash}` | `message` |
| `GET /admin/user-groups/users/{user_hash}/groups` | `user` (`user_hash`, `username`, `email`, `user_type`), `groups[]`, `statistics.total_groups`, `generated_at` |

Details of the nested items:

- `accessible_projects[]` on the details route lists active, non-archived projects reached through
  the group's grants. `statistics` holds `total_members`, `total_projects`,
  `total_project_groups` and `total_derived_projects` (always `0`).
- `accessible_project_groups[]` and `project_groups[]` items have `group_id` (internal ID),
  `group_hash`, `group_name`, `group_description`, `created_at`, `is_active`, `granted_at` and
  `granted_by` (internal user ID), sorted by name.
- `members[]` on the members route have `user_hash`, `username`, `email`, `user_type`,
  `is_active` and `joined_at`, sorted by username. Inactive users are excluded.
- `joined_at` (members route and reverse lookup) is when the membership was last activated.
  Re-adding a current member resets it.
- `access_details` holds `access_id`, `user_group_id`, `project_group_id`, `granted_by` and
  `granted_at`. On a re-grant `access_id` is newly generated and does not match the stored row.
- Bulk `summary` holds `total_requested`, `success_count` and `error_count`. Each `results[]` item
  has `user_hash`, `username`, `status` (`success` or `error`) and `message`. Unknown or inactive
  users appear only as strings in `errors[]` (`"User not found: <hash>"`).

```json
{
  "success": true,
  "message": "Bulk assignment completed: 2 succeeded, 1 failed",
  "user_group": {"group_hash": "5C1E0F2A", "group_name": "qa_team"},
  "summary": {"total_requested": 3, "success_count": 2, "error_count": 1},
  "results": [
    {"user_hash": "usr-a1", "username": "ana", "status": "success", "message": "Added to group successfully"},
    {"user_hash": "usr-b2", "username": "ben", "status": "success", "message": "Added to group successfully"}
  ],
  "errors": ["User not found: usr-zz"],
  "performed_by": "root",
  "performed_at": "2026-09-24T10:30:00.000000Z"
}
```

### Project group objects

| Route | Top-level fields |
| --- | --- |
| `GET /admin/project-groups` | `project_groups[]` (`group_hash`, `group_name`, `description`, `project_count`, `created_at`), `pagination` |
| `POST /admin/project-groups` | `project_group` (`project_count: 0`) |
| `GET /admin/project-groups/{group_hash}` | `project_group`, `assigned_projects[]` (`project_hash`, `project_name`, `project_description`), `statistics.total_projects` |
| `PUT /admin/project-groups/{group_hash}` | `project_group` |
| `DELETE /admin/project-groups/{group_hash}` | `message`, `warning` |
| `POST /admin/project-groups/{group_hash}/projects` | `assignment` (`project`, `group`, `assigned_by` username) |
| `DELETE /admin/project-groups/{group_hash}/projects/{project_hash}` | `message` |

`project_count`, `assigned_projects` and `statistics.total_projects` include only active,
non-archived projects.

## Idempotency

| Operation | Repeat behavior |
| --- | --- |
| Add a member (single or bulk) | Reactivates the row and returns `200`; `joined_at` is reset |
| Grant a project group | Reactivates the grant and returns `200`; `granted_at` is reset |
| Add a project to a project group | Reactivates the assignment and returns `200` |
| Remove a member | `200` even when the user was not a member |
| Remove a project from a project group | `200` even when the project was not in the group |
| Revoke a grant | `500` `INT_7001` when no active grant exists |
| Delete a group | `404` once the group is deleted |

## Session revocation

These routes snapshot the affected users and projects, perform the change, then call
`revoke_project_sessions_losing_access()` with a reason. Sessions of users who still reach the
project through another chain are kept. How it works:
[architecture](architecture.md#session-revocation).

| Route | Reason |
| --- | --- |
| `DELETE /admin/user-groups/{group_hash}` | `user_group_deleted` |
| `DELETE /admin/user-groups/{group_hash}/project-groups/{project_group_hash}` | `user_group_project_group_access_revoked` |
| `DELETE /admin/project-groups/{group_hash}` | `project_group_deleted` |
| `DELETE /admin/project-groups/{group_hash}/projects/{project_hash}` | `project_removed_from_group` |

Adding members, granting access, renaming and
`DELETE /admin/user-groups/{group_hash}/members/{user_hash}` revoke nothing.

## Error codes

Envelope and catalog: [errors.md](../errors.md).

| Status | Code | When |
| --- | --- | --- |
| `400` | `VAL_3001` | Missing or empty required form field, malformed bulk body, empty or oversized `user_hashes`, query value out of range |
| `400` | `VAL_3002` | `PUT /admin/user-groups/{group_hash}` with nothing to update |
| `401` | `AUTH_1003` | Missing, invalid or expired access token |
| `403` | `AUTHZ_2002` | Missing permission, or a non-root write to an `admin_...` user group |
| `404` | `NF_4003` | User group unknown or deleted |
| `404` | `NF_4004` | Project group unknown or deleted; unknown project on the `/admin/project-groups/{group_hash}/projects` routes |
| `404` | `NF_4001` | User unknown or inactive (single add, remove, reverse lookup) |
| `409` | `CONF_5004` | Group name already in use |
| `500` | `INT_7001` | Revoking a grant that is not active; `PUT /admin/project-groups/{group_hash}` with no values |

## Related routes

Permission groups attached to a user group are managed under
`/permissions/admin/user-groups/{group_hash}/permission-groups`; their contract is in the
[permissions reference](../permissions/reference.md). Project-side views of the same data
(`GET /projects/{project_hash}/groups`, `GET /projects/{project_hash}/members`) are in the
[projects reference](../projects/reference.md).
