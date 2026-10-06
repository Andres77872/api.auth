# Users reference

The contract for the `/users`, `/user-types` and `/admin/users/bulk-*` routes: endpoints, caller
rules, request fields, response fields, errors and settings. Task walkthroughs are in
[usage.md](usage.md); the email and bulk routes have their detailed contracts in
[email-management.md](email-management.md) and [bulk-operations.md](bulk-operations.md).

Every route takes an access token (`Authorization: Bearer <access JWT>` or the `access_token`
cookie). A missing, invalid or expired token returns `401`. Write routes read form fields
(`application/x-www-form-urlencoded` or `multipart/form-data`); `POST /users/me/emails` also accepts
a JSON body. The error envelope and code catalog are in [errors.md](../errors.md).

## Endpoints

### `/users` routes

| Path | Method | Caller | Input | Purpose |
| --- | --- | --- | --- | --- |
| `/users/profile` | `GET` | Any user | - | Own account, type info, groups, projects |
| `/users/profile` | `PUT` | Any user | Form | Change own `username` |
| `/users/access-summary` | `GET` | Any user | - | Own groups, reachable projects and effective permissions |
| `/users/list` | `GET` | Root, admin (overlap) | Query | Filtered, paginated user list |
| `/users/search/query` | `GET` | Root, admin (scope) | Query | Quick username/email search |
| `/users/me/emails` | `GET` | Any user | - | Own email addresses |
| `/users/me/emails` | `POST` | Any user | Form or JSON | Add an address and send an activation link (`202`) |
| `/users/me/emails/{email_id}/resend` | `POST` | Any user | - | Resend activation for an own pending address (`202`) |
| `/users/me/emails/{email_id}` | `DELETE` | Any user | - | Remove an own address |
| `/users/me/emails/{email_id}/primary` | `POST` | Any user | - | Make an own activated address primary |
| `/users/{user_hash}/emails` | `GET` | Root, admin (scope) | - | A user's addresses, masked |
| `/users/{user_hash}/emails/{email_id}/resend` | `POST` | Root, admin (scope) | - | Resend activation for a user's pending address (`202`) |
| `/users/{user_hash}` | `GET` | Self, root, admin (overlap) | Query | Account detail with groups and projects |
| `/users/{user_hash}` | `PUT` | Root, admin (overlap) | Form | Change `username`; root also `user_type` |
| `/users/{user_hash}/status` | `PUT` | Root, admin (overlap) | Query `is_active` | Deactivate a user |
| `/users/{user_hash}/reset-password` | `POST` | Root, admin (scope) | - | Queue a password-reset link email |
| `/users/{user_hash}` | `DELETE` | Root, admin (overlap) | - | Soft delete |
| `/users/{user_hash}/hard` | `DELETE` | Root | - | Permanent delete |
| `/users/{user_hash}/type` | `PATCH` | Root | Form | Change `user_type` without assigning a project |

### `/user-types` routes

| Path | Method | Caller | Input | Purpose |
| --- | --- | --- | --- | --- |
| `/user-types/root` | `POST` | Root | Form | Create a root user |
| `/user-types/admin` | `POST` | Root | Form | Create an admin user assigned to one or more projects |
| `/user-types/{user_hash}/info` | `GET` | Root, admin (scope) | - | Type, capabilities and admin assignments |
| `/user-types/{user_hash}/type` | `PUT` | Root | Form | Change `user_type`; `admin` requires a project |
| `/user-types/users/{user_type}` | `GET` | Root, admin (scope) | Query | Active users of one type |
| `/user-types/stats` | `GET` | Root, admin | - | Active user counts per type |
| `/user-types/admin/{user_hash}/projects` | `GET` | Root | - | Projects an admin administers |
| `/user-types/admin/{user_hash}/projects` | `PUT` | Root | Form | Replace an admin's project set |
| `/user-types/admin/{user_hash}/projects/add` | `POST` | Root | Form | Add one project to an admin |
| `/user-types/admin/{user_hash}/projects/{project_id}` | `DELETE` | Root | - | Remove one project from an admin |

### Bulk routes

| Path | Method | Caller | Input | Purpose |
| --- | --- | --- | --- | --- |
| `/admin/users/bulk-update` | `POST` | Root, admin (scope, per target) with session permission `admin` or `manage_users` | Form | Set `is_active` and/or `user_type` on up to 100 users |
| `/admin/users/bulk-delete` | `POST` | Root, admin (scope, per target) with session permission `admin` or `manage_users` | Form | Soft-delete up to 50 users |

Fields, limits and result shapes for the bulk routes: [bulk-operations.md](bulk-operations.md).

## Caller rules

| Rule | Meaning | Routes |
| --- | --- | --- |
| Any user | Any active user type; acts on the caller's own account | `/users/profile`, `/users/access-summary`, `/users/me/emails*` |
| Admin (overlap) | Root: any user. Admin: non-root users sharing at least one project with the admin's *accessible* projects (every project the admin reaches through any user group); the list always includes the admin. Consumers get `403`, except that anyone may read their own detail | list, detail, `PUT /users/{user_hash}`, status, soft delete |
| Admin (scope) | Root: any user. Admin: themselves plus non-root users who reach one of the admin's *assigned* projects (membership of that project's `admin_<project_id>` group, read live). Consumers get `403` | search, reset-password, admin email routes, `/user-types/{user_hash}/info`, `/user-types/users/{user_type}`, bulk update and delete (per target) |
| Root | Root user only; others get `403` | hard delete, type changes, root/admin creation, admin project assignment |

Root users reach every active project, but both admin rules exclude them: an admin gets `403` on a
root target (or, in bulk, a failed entry) and never sees root users in lists or search.

Every route that takes a `{user_hash}` returns `404` for an unknown or inactive user, except
`DELETE /users/{user_hash}/hard`, which also finds inactive users.

## Query parameters

### `GET /users/list`

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `limit` | int | `100` | Page size before admin filtering; not capped |
| `offset` | int | `0` | Rows to skip |
| `sort_by` | string | `username` | `username`, `created_at`, `email`, `user_type`, `last_login`; other values sort by username |
| `sort_order` | string | `asc` | `desc`; other values sort ascending |
| `search` | string | - | Substring of `username` or the activated primary email |
| `user_type_filter` | string | - | `root`, `admin`, `consumer`; not validated (an unknown value matches nothing) |
| `group_filter` | string | - | User group name or hash; active memberships only |
| `project_filter` | string | - | Project name or hash; users reaching it through user groups |
| `include_inactive` | bool | `false` | Include deactivated users |
| `include_group_info` | bool | `true` | Fill each user's `groups` |
| `include_project_access` | bool | `true` | Fill each user's `projects` with `permissions` |

`pagination.total` counts only by `user_type_filter` and `include_inactive`. It ignores `search`,
`group_filter`, `project_filter` and admin scoping, and admin scoping runs after the page is fetched,
so an admin's page can hold fewer than `limit` users. `has_more` is `offset + len(users) < total`.

### `GET /users/search/query`

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `q` | string | required | Substring of `username` or the activated primary email |
| `user_type_filter` | string | - | `root`, `admin`, `consumer`; anything else returns `400` |
| `limit` | int | `50` | Values above `100` become `100`; values below `1` become `50` |

Only active users are searched, ordered by username. The admin scope filter runs after `limit`, so an
admin can get fewer than `limit` results; `total_results` is the number returned.

### `GET /users/{user_hash}`

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `include_group_hierarchy` | bool | `true` | Add `projects_count` to each group |
| `include_permission_details` | bool | `true` | Add `effective_permissions` and `access_groups` to each project |

### `PUT /users/{user_hash}/status`

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `is_active` | bool | required | Missing returns `422`. `false` deactivates the account (group memberships are kept) and revokes its sessions. Inactive users return `404`, so `true` cannot reactivate anyone |

### `GET /user-types/users/{user_type}`

| Parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `user_type` | path | required | `root`, `admin`, `consumer`; anything else returns `400` (`VAL_3012`) |
| `limit` | int | `50` | Values above `100` become `100` |
| `offset` | int | `0` | Rows to skip |

## Form fields

### `PUT /users/profile`

| Field | Required | Notes |
| --- | --- | --- |
| `username` | Yes | New unique username; a taken name returns `409` (`CONF_5004`) |

Email edits use `/users/me/emails`. Sending `email` to profile or admin edits returns `400`.

Sending `password`, `current_password`, `new_password`, `password_confirmation` or `password_hash`
returns `400` (`VAL_3001`) with `details.use_endpoint: "/auth/password/change"`.

### `PUT /users/{user_hash}`

| Field | Required | Notes |
| --- | --- | --- |
| `username` | At least one field | New unique username |
| `user_type` | At least one field | Root callers only (admin gets `403`, `AUTHZ_2002`). Sets the type without assigning a project; a changed type signs the user out everywhere |

### `PATCH /users/{user_hash}/type`

| Field | Required | Notes |
| --- | --- | --- |
| `user_type` | Yes | `root`, `admin`, `consumer`; anything else returns `400` (`VAL_3012`). A changed type signs the user out everywhere |

### `POST /user-types/root`

| Field | Required | Notes |
| --- | --- | --- |
| `username` | Yes | Unique; a taken name returns `409` (`CONF_5004`) |
| `password` | Yes | Must pass the shared password policy (`400`, `VAL_3007`, with `reason_codes`) |

### `POST /user-types/admin`

| Field | Required | Notes |
| --- | --- | --- |
| `username`, `password` | As for root | Same rules as `POST /user-types/root` |
| `assigned_project_ids` | Yes | Internal project IDs (`proj-...`, the project's `id`, not its hash); repeat the field per project. A project without an admin group is skipped and listed in `skipped_projects` |

### `PUT /user-types/{user_hash}/type`

| Field | Required | Notes |
| --- | --- | --- |
| `user_type` | Yes | `root`, `admin`, `consumer` (`400`, `VAL_3012`, otherwise) |
| `assigned_project_ids` | When `user_type=admin` | Internal project IDs; repeat the field. Missing returns `400` (`VAL_3002`), unknown returns `404` (`NF_4002`), a project without an admin group returns `404` (`NF_4003`). Nothing changes on these errors |

### `PUT /user-types/admin/{user_hash}/projects`

| Field | Required | Notes |
| --- | --- | --- |
| `assigned_project_ids` | Yes | The complete new set of internal project IDs; repeat the field. Every ID is checked before anything changes |

### `POST /user-types/admin/{user_hash}/projects/add`

| Field | Required | Notes |
| --- | --- | --- |
| `project_id` | Yes | Internal project ID. Adding a project the admin already has succeeds without change |

## Responses

All success bodies carry `success` and usually `message`. Timestamps are ISO 8601.

### Account and access

| Endpoint | Fields |
| --- | --- |
| `GET /users/profile` | `user_hash`, `username`, `email` (activated primary address), `user_type`, `user_type_info`, `created_at`, `updated_at`, `last_login`, `is_active`, `groups[]` (`group_hash`, `group_name`, `group_description`, `assigned_at`, `assigned_by`), `projects[]` (`project_hash`, `project_name`, `project_description`, `created_at`, `updated_at`, `permissions`: the caller's effective permissions in that project) |
| `PUT /users/profile` | `user` (`user_hash`, `username`, `email`, `user_type`, `created_at`, `updated_at`) |
| `GET /users/access-summary` | `access_summary.user` (`user_hash`, `username`, `user_type`, `user_type_details`, `email`), `user_groups[]` (as profile plus `projects_count`), `accessible_projects[]` (`project_hash`, `project_name`, `project_description`, `access_groups[]`, `effective_permissions[]`), `current_session` (only `project_hash` is filled), `summary` (`total_groups`, `total_projects`, `is_admin`, always `false`) |
| `GET /users/list` | `users[]` (`user_hash`, `username`, `email`, `user_type`, `user_type_info`, `created_at`, `last_login`, `is_active`, `groups[]`, `projects[]` with `project_group` and `permissions`), `pagination` (`total`, `limit`, `offset`, `has_more`), `filters` |
| `GET /users/search/query` | `users[]` (`user_hash`, `username`, `email`, `user_type`, `created_at`, `last_login`, `is_active`), `search_term`, `total_results`, `filters` (`user_type_filter`, `limit`) |
| `GET /users/{user_hash}` | `user` (profile fields plus `groups[].projects_count` and `projects[].effective_permissions` / `access_groups` when requested). The top-level `permissions`, `groups`, `accessible_projects` and `statistics` are always empty or `null` |
| `PUT /users/{user_hash}` | `user` (as `PUT /users/profile`), `updated_at` |

`user_type_info` holds `user_id`, `user_hash`, `username`, `user_type`, `capabilities` and, per type,
`accessible_projects` (project IDs; empty for root), `user_groups` (names), `assigned_project_ids`
(admin) or `accessible_projects_details` (consumer).

### Lifecycle

| Endpoint | Fields |
| --- | --- |
| `PUT /users/{user_hash}/status` | `user_hash`, `is_active`, `message` |
| `POST /users/{user_hash}/reset-password` | `user` (`user_hash`, `username`), `reset_data` (`expires_at`, `delivery_status: "accepted"`, `has_delivery_target`), `instructions`. The response never contains the token, the link or the address |
| `DELETE /users/{user_hash}` | `user_hash`, `username`, `deleted_at` |
| `DELETE /users/{user_hash}/hard` | `user_hash`, `username`, `removed` (`mode: "hard"`, `user_type`, `emails_unlinked`, `owned_content: "cascade_deleted"`, `shared_resources: "preserved (ownership cleared)"`), `deleted_at` |
| `PATCH /users/{user_hash}/type` | `user_hash`, `previous_type`, `new_type` |

### User types

| Endpoint | Fields |
| --- | --- |
| `POST /user-types/root` | `user` (`user_hash`, `username`, `email`, `user_type: "root"`, `created_at`) |
| `POST /user-types/admin` | `user` (`user_hash`, `username`, `email`, `user_type`, `assigned_project_ids` and `assigned_projects[]` (`project_id`, `project_hash`, `project_name`) for the projects actually assigned, `skipped_projects[]` (same fields plus `reason: "no_admin_group"`), `created_at`, `created_by`); `message` counts the assigned projects |
| `GET /user-types/{user_hash}/info` | `user_type_info` (`user_id`, `user_hash`, `username`, `user_type`, `capabilities`, `assigned_projects`, `total_assigned_projects`); the assignment fields are `null` for non-admins |
| `PUT /user-types/{user_hash}/type` | `user_type_info` as above, for the new type |
| `GET /user-types/users/{user_type}` | `users[]` (`user_hash`, `username`, `email`, `user_type`, `created_at`, `is_active`; admins with an assignment add `assigned_project` (`project_id`, `project_hash`, `project_name`), their first assigned project), `pagination`, `filter` (`user_type`, `project_filter`: the admin's assigned project hashes, `null` for root) |
| `GET /user-types/stats` | `statistics` (`total_users`, `user_types.{root,admin,consumer}.{count,percentage}`, `system_info`, `scope`) |
| `GET /user-types/admin/{user_hash}/projects` | `user_hash`, `assigned_projects[]` (`project_id`, `project_hash`, `project_name`, `project_description`, `assigned_at`, `assigned_by`) |
| `PUT /user-types/admin/{user_hash}/projects` | `user_hash`, `assigned_projects[]`, `total_projects`; `success: false` with the failed IDs in `message` when some steps failed |
| `POST /user-types/admin/{user_hash}/projects/add` | `user_hash`, `project_id`, `project_hash`, `project_name` |
| `DELETE /user-types/admin/{user_hash}/projects/{project_id}` | `user_hash`, `project_id` |

In the admin project list, `assigned_at` and `assigned_by` describe when the project's admin group
was granted the project, not when this admin joined the group.

## Enums

| Name | Values |
| --- | --- |
| `user_type` | `root`, `admin`, `consumer` |
| Root `capabilities` | `unrestricted_access`, `global_admin`, `create_root_users`, `manage_all_projects`, `manage_all_users` |
| Admin `capabilities` | `project_admin`, `manage_project_users`, `manage_project_groups`, `manage_project_permissions` |
| Consumer `capabilities` | `global_role_permissions`, `group_based_access`, `project_access_via_groups` |
| Email `status` | `pending`, `activated`, `removed`, `suppressed` ([email-management.md](email-management.md#address-lifecycle)) |

## Errors

| Status | Code | When |
| --- | --- | --- |
| `400` | `VAL_3001` | No field to update; self-deactivation or self-delete; reset-password on a root user; password field sent to `PUT /users/profile`; target of an admin-project route is not an admin; malformed email |
| `400` | `VAL_3002` | Missing `assigned_project_ids(s)` on admin creation or promotion; empty `username` or `password` |
| `400` | `VAL_3007` | Password rejected by the shared policy (`details.reason_codes`) |
| `400` | `VAL_3012` | Invalid `user_type` |
| `403` | `AUTHZ_2001` | Caller is not root/admin on a `/users` admin route; target outside the admin's overlap or scope, including any root target of an admin; non-root caller on hard delete |
| `403` | `AUTHZ_2002` | Non-root caller on a root-only `/user-types` route or `PATCH /users/{user_hash}/type`; consumer on a root-or-admin `/user-types` route or a bulk user route; admin sending `user_type`; admin listing root users |
| `404` | `NF_4004` | Unknown or inactive `user_hash` on `/users` routes; unknown own `email_id` on `DELETE /users/me/emails/{email_id}` |
| `404` | `NF_4001` | Unknown or inactive `user_hash` on `/user-types` routes |
| `404` | `NF_4002` | Unknown internal project ID |
| `404` | `NF_4003` | The project has no admin group (`POST .../projects/add`, `PUT /user-types/{user_hash}/type` with `admin`); the admin is not assigned to the project (`DELETE /user-types/admin/{user_hash}/projects/{project_id}`) |
| `409` | `CONF_5004` | Username already taken |
| `409` | `CONF_5005` | `POST /users/me/emails/{email_id}/primary` on an address that is not an own activated address |
| `422` | `VAL_3001` | A required query or form field is missing (for example `is_active`, `user_type`) |
| `429` | `INT_7005` | Email send rate limit or resend cooldown; `Retry-After` is set |

## Settings

The email routes and `POST /users/{user_hash}/reset-password` use the shared email limiter. Values
below are the `.env.example` defaults.

```env
# Minimum gap between activation resends for one address
EMAIL_RESEND_COOLDOWN_SECONDS=60
# Sends per recipient key per hour / per day
EMAIL_SEND_RECIPIENT_HOURLY_LIMIT=3
EMAIL_SEND_RECIPIENT_DAILY_LIMIT=10
# Sends per calling user per hour, and per client IP per hour
EMAIL_SEND_USER_HOURLY_LIMIT=5
EMAIL_SEND_IP_HOURLY_LIMIT=20
# Link lifetimes: activation, and admin password reset
EMAIL_ACTIVATION_TOKEN_TTL_SECONDS=86400
EMAIL_PASSWORD_RESET_TOKEN_TTL_SECONDS=3600  # a lifetime, not a token value
# Idempotency-Key replay window
EMAIL_IDEMPOTENCY_TTL_SECONDS=86400
```

Buckets are counted per purpose (`email_activation`, `admin_password_reset`). The limiter fails closed:
if Redis is unavailable, send routes return `429`. The full email configuration is in the
[email reference](../email/reference.md).
