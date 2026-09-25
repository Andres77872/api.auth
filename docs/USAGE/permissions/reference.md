# Permissions reference

The contract of the 17 `/permissions` routes in `src/routes/permission_assignments.py`. Resolution
rules are in [Permission resolution](resolution.md); role, permission-group, and permission
definitions are in the [Roles reference](../roles/reference.md).

## Endpoints

"Admin" = user type `root` or `admin`, or a consumer holding `manage_roles` from its role, a user
group, or a direct assignment (`sp_check_user_has_permission_extended`). "Token" = any valid access
token. All routes answer `200` on success.

| Path | Method | Guard | Request | Returns |
| --- | --- | --- | --- | --- |
| `/permissions/admin/user-groups/{group_hash}/permission-groups` | POST | Admin | Form: `permission_group_hash` | `user_group`, `permission_group` |
| `/permissions/admin/user-groups/{group_hash}/permission-groups` | GET | Admin | — | `user_group`, `permission_groups`, `count` |
| `/permissions/admin/user-groups/{group_hash}/permission-groups/{pg_hash}` | DELETE | Admin | — | `user_group`, `permission_group` |
| `/permissions/admin/user-groups/{group_hash}/permission-groups/bulk` | POST | Admin | Form: `permission_group_hashes` (repeat) | `user_group`, `results`, `success_count`, `total_count` |
| `/permissions/users/{user_hash}/permission-groups` | POST | Admin | Form: `permission_group_hash`, `notes` | `user`, `permission_group`, `notes` |
| `/permissions/users/{user_hash}/permission-groups` | GET | Admin | — | `user`, `direct_permission_groups`, `count` |
| `/permissions/users/{user_hash}/permission-groups/{pg_hash}` | DELETE | Admin | — | `user`, `permission_group` |
| `/permissions/users/me/permission-groups` | GET | Token | — | `user`, `direct_permission_groups`, `count` |
| `/permissions/users/me/permissions` | GET | Token | — | `user`, `permissions`, `count` |
| `/permissions/users/me/permissions/check/{permission_name}` | GET | Token | — | `user`, `permission`, `has_permission` |
| `/permissions/users/me/permission-sources` | GET | Token | — | `user`, `sources`, `summary` |
| `/permissions/projects/{project_hash}/permission-group-catalog/{pg_hash}` | POST | Admin | Form: `catalog_purpose`, `notes` | `project`, `permission_group`, `catalog_purpose`, `note` |
| `/permissions/projects/{project_hash}/permission-group-catalog/{pg_hash}` | DELETE | Admin | — | `project`, `permission_group` |
| `/permissions/projects/{project_hash}/permission-group-catalog` | GET | Token | — | `project`, `cataloged_permission_groups`, `count`, `note` |
| `/permissions/permissions/groups/{pg_hash}/project-catalog` | GET | Token | — | `permission_group`, `cataloged_in_projects`, `count`, `note` |
| `/permissions/permissions/groups/{pg_hash}/user-groups` | GET | Admin | — | `permission_group`, `user_groups`, `count` |
| `/permissions/permissions/groups/{pg_hash}/users` | GET | Admin | — | `permission_group`, `users_with_direct_assignment`, `count` |

Every write response also has a `message` string. No response from this router has a `success`
field. Credentials: `Authorization: Bearer <access JWT>` or the `session_token` cookie; API keys are
rejected (`401`).

## Path parameters

| Parameter | Identifies | Lookup |
| --- | --- | --- |
| `group_hash` | User group | Active user groups only (`404` `NF_4003` otherwise) |
| `user_hash` | Target user | Active users only (`404` `NF_4001`) |
| `project_hash` | Project | Active projects only (`404` `NF_4002`); archived projects are accepted |
| `pg_hash` | Permission group | Active permission groups only (`404` `NF_4011`) |
| `permission_name` | Permission name to test | Not validated; an unknown name returns `has_permission: false` |

## Form fields

| Route | Field | Required | Behavior |
| --- | --- | --- | --- |
| `POST .../user-groups/{group_hash}/permission-groups` | `permission_group_hash` | Yes | Hash of an active permission group. Re-assigning re-activates the existing row. |
| `POST .../user-groups/{group_hash}/permission-groups/bulk` | `permission_group_hashes` | Yes, at least one | Repeat the field once per hash. No upper limit. Each hash is processed on its own. |
| `POST /permissions/users/{user_hash}/permission-groups` | `permission_group_hash` | Yes | Hash of an active permission group. |
| | `notes` | No | Free text. Re-assigning **replaces** the stored notes; omitting the field clears them. |
| `POST .../permission-group-catalog/{pg_hash}` | `catalog_purpose` | No | Stored in a 255-character column. On re-add, an omitted value keeps the stored one. |
| | `notes` | No | Free text. On re-add, an omitted value keeps the stored one. |

An empty form value is treated as omitted.

## Response shapes

Examples use placeholder values. `id` and `assigned_by`/`added_by` are internal IDs; timestamps are
ISO 8601 strings.

### Assignment writes

`POST` and `DELETE` on user-group assignments:

```json
{
  "message": "Permission group assigned to user group successfully",
  "user_group": {"hash": "USER_GROUP_HASH", "name": "qa_team"},
  "permission_group": {"hash": "PG_HASH", "name": "qa_testing"}
}
```

`POST /permissions/users/{user_hash}/permission-groups` (the `DELETE` has no `notes`):

```json
{
  "message": "Permission group assigned to user successfully",
  "user": {"hash": "USER_HASH", "username": "alice"},
  "permission_group": {"hash": "PG_HASH", "name": "reporting"},
  "notes": "Q3 reporting access"
}
```

Bulk assignment. `results` has one entry per submitted hash, in order; an unknown hash yields
`success: false` with `error: "Permission group not found"`. The status is `200` even when every
item fails.

```json
{
  "message": "Bulk assignment completed: 1/2 successful",
  "user_group": {"hash": "USER_GROUP_HASH", "name": "qa_team"},
  "results": [
    {"permission_group_hash": "PG_A", "permission_group_name": "qa_testing", "success": true},
    {"permission_group_hash": "PG_X", "success": false, "error": "Permission group not found"}
  ],
  "success_count": 1,
  "total_count": 2
}
```

### Assignment listings

| Array | Item fields |
| --- | --- |
| `permission_groups` (user group) | `id`, `group_hash`, `group_name`, `group_display_name`, `group_description`, `group_category`, `assigned_at`, `assigned_by` |
| `direct_permission_groups` | Same as above plus `notes` |
| `user_groups` (usage) | `id`, `group_hash`, `group_name`, `group_description`, `assigned_at`, `assigned_by` |
| `users_with_direct_assignment` (usage) | `id`, `user_hash`, `username`, `email`, `user_type`, `role_id`, `assigned_at`, `assigned_by`, `notes` |

Listings contain only active links to active permission groups, user groups, and users. The `user`
object on user listings is `{"hash", "username"}`; `user_group` and `permission_group` objects are
`{"hash", "name"}`.

### Self-inspection

`GET /permissions/users/me/permissions`:

```json
{
  "user": {"hash": "USER_HASH", "username": "bob"},
  "permissions": ["call_api", "read_data"],
  "count": 2
}
```

`GET /permissions/users/me/permissions/check/{permission_name}`:

```json
{
  "user": {"hash": "USER_HASH", "username": "bob"},
  "permission": "manage_roles",
  "has_permission": false
}
```

`GET /permissions/users/me/permission-sources`. Each entry has `source_type` (`role`,
`user_group`, `direct`), `source_name` (role name, user-group name, or `Direct Assignment`),
`permission_group_name`, `permission_group_hash`, and `notes` (direct assignments only). A group
reached through several sources appears once per source, so `total_permission_groups` counts entries.

```json
{
  "user": {"hash": "USER_HASH", "username": "bob"},
  "sources": {
    "from_role": [
      {"source_type": "role", "source_name": "viewer", "permission_group_name": "read_only", "permission_group_hash": "PG_R", "notes": null}
    ],
    "from_user_groups": [
      {"source_type": "user_group", "source_name": "developers", "permission_group_name": "api_access", "permission_group_hash": "PG_A", "notes": null}
    ],
    "from_direct_assignment": []
  },
  "summary": {"role_count": 1, "user_group_count": 1, "direct_count": 0, "total_permission_groups": 2}
}
```

### Catalog

`POST .../permission-group-catalog/{pg_hash}` returns `project` (`{"hash", "name"}`),
`permission_group`, the `catalog_purpose` **as sent** (`null` when omitted, even if a stored value was
kept), and `note: "This is METADATA ONLY - not used for authorization"`.

| Array | Item fields |
| --- | --- |
| `cataloged_permission_groups` | `id`, `group_hash`, `group_name`, `group_display_name`, `group_description`, `group_category`, `catalog_purpose`, `notes`, `added_at`, `added_by` |
| `cataloged_in_projects` | `id`, `project_hash`, `project_name`, `project_description`, `catalog_purpose`, `notes`, `added_at`, `added_by` |

## Errors

Envelope and full catalog: [error reference](../errors.md). `error.details` is returned only when
`DEBUG_MODE` is on, so rely on `error.code` and `error.message`.

| Status | Code | When |
| --- | --- | --- |
| `400` | `VAL_3001` | A required form field is missing, including when the body was sent as JSON |
| `401` | `AUTH_1003` | Missing, malformed, expired, or revoked access token; inactive caller; API key sent instead |
| `403` | `AUTHZ_2002` | Admin route and the caller is neither `root`/`admin` nor holds `manage_roles` from any source; or a non-root caller assigns or removes a permission group containing a [reserved permission name](../roles/reference.md#reserved-permission-names) ("Only root users may ...") |
| `404` | `NF_4003` | User group not found or inactive |
| `404` | `NF_4001` | Target user not found or inactive |
| `404` | `NF_4002` | Project not found or inactive |
| `404` | `NF_4011` | Permission group not found or soft-deleted |
| `500` | `INT_7001` | The write reported failure, or a database error |

The guard runs before any lookup, so a non-admin caller gets `403` even for unknown hashes. Removing
something that is not assigned or cataloged is **not** an error (`200`).
