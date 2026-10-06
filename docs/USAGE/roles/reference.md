# Roles reference

The contract of the 28 `/roles` routes in `src/routes/global_roles.py`, plus bulk role assignment in
`src/routes/bulk_operations.py`. How roles turn into effective permissions is in
[Permission resolution](../permissions/resolution.md).

## Endpoints

"Admin" = user type `root` or `admin`, or a consumer whose **role** grants `manage_roles` (live
`sp_global_check_user_has_permission`; user-group and direct assignments do not count). "Root if
reserved" = non-root callers get `403` when the change involves a
[reserved permission name](#reserved-permission-names). "Token" = any valid access token.

Credentials: `Authorization: Bearer <access JWT>` or the `access_token` cookie. API keys are
rejected (`401`). Every response carries `success: true`; writes add a `message`.

### Roles

| Path | Method | Guard | Request | Success |
| --- | --- | --- | --- | --- |
| `/roles` | POST | Admin | Form: `role_name`, `role_display_name`, `role_description`, `role_priority` | `201`, `role` |
| `/roles` | GET | Token | Query: `limit`, `offset` | `200`, `roles`, `pagination` |
| `/roles/{role_hash}` | GET | Token | — | `200`, `role`, `permission_groups` |
| `/roles/{role_hash}` | PUT | Admin, root if reserved | Form: `role_display_name`, `role_description`, `role_priority` | `200`, `role` |
| `/roles/{role_hash}` | DELETE | Admin, root if reserved | — | `200` |
| `/roles/{role_hash}/permission-groups/{group_hash}` | POST | Admin, root if reserved | — | `200` |
| `/roles/{role_hash}/permission-groups` | GET | Token | — | `200`, `role`, `permission_groups` |
| `/roles/{role_hash}/permission-groups/{group_hash}` | DELETE | Admin, root if reserved | — | `200` |

### Permission groups

| Path | Method | Guard | Request | Success |
| --- | --- | --- | --- | --- |
| `/roles/permission-groups` | POST | Admin | Form: `group_name`, `group_display_name`, `group_description`, `group_category` | `201`, `permission_group` |
| `/roles/permission-groups` | GET | Token | Query: `category`, `limit`, `offset` | `200`, `permission_groups`, `pagination` |
| `/roles/permission-groups/{group_hash}` | GET | Token | — | `200`, `permission_group`, `permissions` |
| `/roles/permission-groups/{group_hash}` | PUT | Admin, root if reserved | Form: `group_display_name`, `group_description`, `group_category` | `200`, `permission_group` |
| `/roles/permission-groups/{group_hash}` | DELETE | Admin, root if reserved | — | `200` |
| `/roles/permission-groups/{group_hash}/permissions/{permission_hash}` | POST | Admin, root if reserved | — | `200` |
| `/roles/permission-groups/{group_hash}/permissions` | GET | Token | — | `200`, `permission_group`, `permissions` |
| `/roles/permission-groups/{group_hash}/permissions/{permission_hash}` | DELETE | Admin, root if reserved | — | `200` |

### Permissions

| Path | Method | Guard | Request | Success |
| --- | --- | --- | --- | --- |
| `/roles/permissions` | POST | Admin, root if reserved | Form: `permission_name`, `permission_display_name`, `permission_description`, `permission_category` | `201`, `permission` |
| `/roles/permissions` | GET | Token | Query: `category`, `limit`, `offset` | `200`, `permissions`, `pagination` |
| `/roles/permissions/{permission_hash}` | GET | Token | — | `200`, `permission` |
| `/roles/permissions/{permission_hash}` | PUT | Admin, root if reserved | Form: `permission_display_name`, `permission_description`, `permission_category` | `200`, `permission` |
| `/roles/permissions/{permission_hash}` | DELETE | Admin, root if reserved | — | `200` |

### User role assignment

| Path | Method | Guard | Request | Success |
| --- | --- | --- | --- | --- |
| `/roles/users/me/role` | GET | Token | — | `200`, `user`, `role` |
| `/roles/users/{user_hash}/role` | PUT | Admin, root if reserved, not own role | Form: `role_hash` | `200`, `user`, `role` |
| `/roles/users/{user_hash}/role` | GET | Token | — | `200`, `user`, `role` |
| `/roles/users/{user_hash}/role` | DELETE | Admin, root if reserved, not own role | — | `200`, `user`, `previous_role` |
| `/admin/projects/{project_hash}/bulk-assign-roles` | POST | Session permissions include `admin`; root if reserved; caller not in list | Form: `user_hashes`, `role_names` | `200`, `summary`, `results`, `errors` |

### Project role catalog

| Path | Method | Guard | Request | Success |
| --- | --- | --- | --- | --- |
| `/roles/projects/{project_hash}/catalog/roles/{role_hash}` | POST | Admin | Form: `catalog_purpose`, `notes` | `200`, `project`, `role`, `catalog_purpose`, `note` |
| `/roles/projects/{project_hash}/catalog/roles` | GET | Token | — | `200`, `project`, `cataloged_roles`, `count`, `note` |
| `/roles/projects/{project_hash}/catalog/roles/{role_hash}` | DELETE | Admin | — | `200`, `project`, `role` |

## Query parameters

| Parameter | Routes | Default | Rule |
| --- | --- | --- | --- |
| `limit` | The three list routes | `50` | `1`–`100` |
| `offset` | The three list routes | `0` | `>= 0` |
| `category` | `GET /roles/permission-groups`, `GET /roles/permissions` | none | Exact match on `group_category` / `permission_category` (case-insensitive collation) |

`pagination` echoes `limit` and `offset`; its `total` is the number of items in **this page**, not
the overall count. Keep paging until a page returns fewer than `limit` items.

## Form fields

All writes take `application/x-www-form-urlencoded` or `multipart/form-data`. An empty value counts
as omitted. Lengths are database column sizes, not route validation.

### Create a role, group, or permission

| Field | Required | Default | Notes |
| --- | --- | --- | --- |
| `role_name` | Yes | — | Up to 100 characters. Unique across active and deleted roles, compared case- and accent-insensitively. Cannot be changed later. |
| `role_display_name` | Yes | — | Up to 255 characters. |
| `role_description` | No | `null` | Free text. |
| `role_priority` | No | `50` | Integer `0`–`100`. Orders listings only. |
| `group_name` | Yes | — | Up to 100 characters. Same uniqueness and immutability as `role_name`. |
| `group_display_name` | Yes | — | Up to 255 characters. |
| `group_description` | No | `null` | Free text. |
| `group_category` | No | `general` | Free-form label, up to 50 characters. Used only by the `category` filter. |
| `permission_name` | Yes | — | Up to 100 characters. The string guards match on. Same uniqueness and immutability. Reserved names need root. |
| `permission_display_name` | Yes | — | Up to 255 characters. |
| `permission_description` | No | `null` | Free text. |
| `permission_category` | No | `general` | Free-form label, up to 50 characters. |

`is_system_role` cannot be set through the API; new roles always have `0`.

### Update a role, group, or permission

`PUT` accepts only the display name, description, and priority or category fields above, all
optional. Omitted or empty fields keep their value, so a field cannot be cleared. Names and
`is_system_role` are not editable. Sending no fields changes nothing (a role's `updated_at` is still
refreshed). System roles can be updated.

### Assign a role

| Field | Required | Notes |
| --- | --- | --- |
| `role_hash` | Yes | Hash of an active role. Replaces the user's current role. |

### Catalog a role

| Field | Required | Notes |
| --- | --- | --- |
| `catalog_purpose` | No | Up to 255 characters. On re-add, an omitted value keeps the stored one. |
| `notes` | No | Free text. On re-add, an omitted value keeps the stored one. |

### Bulk role assignment

| Field | Required | Notes |
| --- | --- | --- |
| `user_hashes` | Yes | Repeat once per user, `1`–`100`. Unknown or inactive users fail per item. |
| `role_names` | Yes | Role **names**, not hashes. Repeat once per name. Every name must be an active role or nothing is assigned. |

## Reserved permission names

`admin`, `global_admin`, `project_admin`, `unrestricted_access`, `manage_users`, `manage_roles`,
`manage_permissions`, `manage_groups`, `manage_billing` (`RESERVED_PERMISSION_NAMES` in
`src/Util/admin_scope.py`). Names are compared the way the database compares them: ignoring case,
accents, character width, and surrounding spaces, so look-alikes are reserved too.

Only a `root` caller (checked live) may:

| Operation | Blocked for non-root when |
| --- | --- |
| `POST /roles/permissions` | `permission_name` is reserved |
| `PUT`, `DELETE /roles/permissions/{permission_hash}` | The permission is reserved |
| `POST`, `DELETE /roles/permission-groups/{group_hash}/permissions/{permission_hash}` | The permission is reserved |
| `PUT`, `DELETE /roles/permission-groups/{group_hash}` | The group contains a reserved permission |
| `POST`, `DELETE /roles/{role_hash}/permission-groups/{group_hash}` | The group contains a reserved permission |
| `PUT`, `DELETE /roles/{role_hash}` | A group linked to the role contains a reserved permission |
| `PUT /roles/users/{user_hash}/role` | The new role **or** the user's current role grants a reserved permission |
| `DELETE /roles/users/{user_hash}/role` | The user's current role grants a reserved permission |
| `POST /admin/projects/{project_hash}/bulk-assign-roles` | Any listed role grants a reserved permission, **or** a listed user's current role does |
| `POST`, `DELETE /permissions/admin/user-groups/{group_hash}/permission-groups` (and `.../bulk`) | The permission group contains a reserved permission |
| `POST`, `DELETE /permissions/users/{user_hash}/permission-groups` | The permission group contains a reserved permission |

The checks look only at **active** groups and permissions, which are exactly the rows the resolvers
grant from: a soft-deleted group or permission grants nothing, so the checks cannot miss it. See
[Permission resolution](../permissions/resolution.md#soft-delete-effects).

Non-root callers also cannot change their own role (`PUT` or `DELETE /roles/users/{user_hash}/role`
on themselves, or listing themselves in a bulk assignment).

## Response objects

Boolean columns (`is_system_role`, `is_active`) are returned as `0`/`1`. `id`, `created_by`, and
`added_by` are internal IDs. Timestamps are ISO 8601 strings.

| Object | Fields |
| --- | --- |
| Role (`role`, `roles[]`, `previous_role`) | `id`, `role_hash`, `role_name`, `role_display_name`, `role_description`, `role_priority`, `is_system_role`, `created_at`, `updated_at`, `created_by`, `is_active` |
| Permission group (`permission_group`, `permission_groups[]`) | `id`, `group_hash`, `group_name`, `group_display_name`, `group_description`, `group_category`, `created_at`, `updated_at`, `created_by`, `is_active` |
| Permission (`permission`, `permissions[]`) | `id`, `permission_hash`, `permission_name`, `permission_display_name`, `permission_description`, `permission_category`, `created_at`, `updated_at`, `created_by`, `is_active` |
| Cataloged role (`cataloged_roles[]`) | `id`, `role_hash`, `role_name`, `role_display_name`, `role_description`, `role_priority`, `is_system_role`, `catalog_purpose`, `notes`, `added_at`, `added_by`, `added_by_username` |

Some routes return short forms instead of full objects:

| Route | Short objects |
| --- | --- |
| `GET /roles/{role_hash}/permission-groups` | `role`: `role_hash`, `role_name` |
| `GET /roles/permission-groups/{group_hash}/permissions` | `permission_group`: `group_hash`, `group_name` |
| `PUT /roles/users/{user_hash}/role` | `user`: `user_hash`, `username`; `role`: `role_hash`, `role_name` |
| `GET` role lookups, `DELETE` role removal | `user`: `user_hash`, `username` |
| Catalog add | `project`: `hash`, `name`; `role`: `role_hash`, `role_name`, `role_display_name` |
| Catalog list, catalog remove | `project`: `hash`, `name`; remove adds `role`: `role_hash`, `role_name` |

Lists contain only active rows: active roles, groups, and permissions, and active links between
them. `role` in a user lookup is `null` when the user has no role or the role is soft-deleted.

`POST /roles`:

```json
{
  "success": true,
  "message": "Role 'content_editor' created successfully",
  "role": {
    "id": "role_0f3c9a1b2d4e5f60",
    "role_hash": "ROLE_HASH",
    "role_name": "content_editor",
    "role_display_name": "Content Editor",
    "role_description": null,
    "role_priority": 60,
    "is_system_role": 0,
    "created_at": "2026-09-24T10:00:00",
    "updated_at": null,
    "created_by": "USER_ID",
    "is_active": 1
  }
}
```

`PUT /roles/users/{user_hash}/role`:

```json
{
  "success": true,
  "message": "Role 'content_editor' assigned to user 'alice'",
  "user": {"user_hash": "USER_HASH", "username": "alice"},
  "role": {"role_hash": "ROLE_HASH", "role_name": "content_editor"}
}
```

`POST /roles/projects/{project_hash}/catalog/roles/{role_hash}` returns `catalog_purpose` **as
sent** (`null` when omitted, even if a stored value was kept) and
`note: "This is METADATA ONLY - not used for authorization"`.

Bulk role assignment:

```json
{
  "success": true,
  "message": "Bulk role assignment completed: 1 succeeded, 1 failed",
  "project": {"project_hash": "PROJECT_HASH", "project_name": "Main"},
  "roles_assigned": ["content_editor"],
  "summary": {"total_requested": 2, "success_count": 1, "error_count": 1},
  "results": [
    {"user_hash": "USER_A", "role_name": "content_editor", "success": true},
    {"user_hash": "USER_X", "role_name": "content_editor", "success": false, "error": "User not found"}
  ],
  "errors": [{"user": "USER_X", "error": "User not found"}],
  "performed_by": "admin",
  "performed_at": "2026-09-24T10:00:00Z"
}
```

`summary.total_requested` counts users; `success_count` and `error_count` count user-role pairs.

## Errors

Envelope and catalog: [error reference](../errors.md). `error.details` is returned only when
`DEBUG_MODE` is on, so rely on `error.code` and `error.message`.

| Status | Code | When |
| --- | --- | --- |
| `400` | `VAL_3001` | Missing required form field (a JSON body counts as missing), non-integer or out-of-range `role_priority`, `limit`, or `offset` |
| `400` | `VAL_3010` | Bulk: more than 100 `user_hashes` |
| `401` | `AUTH_1003` | Missing, malformed, expired, or revoked access token; inactive caller; API key sent instead |
| `403` | `AUTHZ_2002` | Not admin (message "Admin permission required"); non-root change involving a reserved name ("Only root users may ...") |
| `403` | `AUTHZ_2009` | Deleting a system role ("Cannot delete system roles"); non-root caller changing its own role ("You cannot change your own role") |
| `403` | `AUTH_1005` | Target user of `/roles/users/{user_hash}/role` is inactive |
| `404` | `NF_4007` | Role not found or soft-deleted; bulk: unknown or inactive role name |
| `404` | `NF_4011` | Permission group not found or soft-deleted |
| `404` | `NF_4005` | Permission not found or soft-deleted |
| `404` | `NF_4001` | User not found |
| `404` | `NF_4002` | Project not found or inactive (catalog routes) |
| `404` | `NF_4004` | Unlinking something that is not linked (group from role, permission from group, role from catalog); bulk: project not found |
| `409` | `CONF_5004` | `role_name`, `group_name`, or `permission_name` already taken (deleted names stay taken) |
| `500` | `INT_7001` | `DELETE /roles/users/{user_hash}/role` on a user who has no role (known defect); other write failures |

The guard runs before lookups, so a non-admin gets `403` even for unknown hashes. Adding a role that
is already cataloged is not an error.
