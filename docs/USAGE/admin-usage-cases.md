# Administration and operations

Day-to-day operator work for root and admin users: dashboard counts, the activity feed, service
health, the authentication cache, and bulk user operations. Error codes are explained in the
[Error reference](errors.md); request conventions (User-Agent, body size, form encoding) are in the
[platform-wide contracts](README.md#platform-wide-contracts).

Authenticated routes here take the access token as `Authorization: Bearer <access JWT>` or the
`session_token` cookie. The admin gate is not the same across route families:

| Route family | Who may call | Otherwise |
| --- | --- | --- |
| `/admin/dashboard/stats`, `/admin/activity*`, `/admin/health`, `/admin/users/statistics`, `/admin/projects/statistics`, `/admin/system/overview` | Root, or a user whose `user_type` is `admin` | `403` `AUTHZ_2001` |
| `POST /system/cache/clear`, `POST /system/cache/invalidate/*` | Root, or `user_type` `admin` | `403` `AUTHZ_2001` |
| `GET /system/info`, `GET /system/health`, `GET /system/cache/stats` | Any valid access session | `401` `AUTH_1003` |
| `POST /admin/users/bulk-update`, `POST /admin/users/bulk-delete` | Root, or `user_type` `admin`, and session permissions include `admin` or `manage_users`; each target is then checked (see [Bulk operations](#bulk-operations)) | `403` `AUTHZ_2002` |
| `POST /admin/projects/{project_hash}/bulk-assign-roles`, `POST /admin/user-groups/bulk-assign` | Session permissions include `admin` | `403` `AUTHZ_2002` |

Root and admin sessions carry the `admin` and `manage_users` permissions by default.

## Admin dashboard

### Dashboard counts

`GET /admin/dashboard/stats` returns headline counts. It takes no parameters.

```bash
curl "$BASE_URL/admin/dashboard/stats" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

```json
{
  "totals": {
    "users": 1250,
    "projects": 45,
    "user_groups": 28,
    "project_groups": 12,
    "active_sessions": 342,
    "recent_activities": 1580
  },
  "recent_activity": {
    "new_users_7d": 35,
    "new_projects_7d": 3,
    "total_activities_7d": 1580
  },
  "user_breakdown": {
    "root_users": 2,
    "admin_users": 15,
    "consumer_users": 1233
  },
  "groups_summary": {
    "total_user_groups": 28,
    "total_project_groups": 12,
    "avg_users_per_group": 44.64,
    "avg_projects_per_group": 3.75
  },
  "growth": {
    "user_growth_7d": 35,
    "project_growth_7d": 3
  },
  "system_health": {
    "database": {"status": "healthy", "message": "Database accessible", "timestamp": "2026-03-25T10:30:00Z"},
    "redis": {"status": "healthy", "message": "Redis accessible", "timestamp": "2026-03-25T10:30:00Z"},
    "overall_status": "healthy"
  },
  "generated_at": "2026-03-25T10:30:00Z"
}
```

| Field | Meaning |
| --- | --- |
| `totals.active_sessions` | Live access sessions (`session:*` keys in Redis). |
| `totals.recent_activities`, `recent_activity.*`, `growth.*` | Counts for the last `7` days. `growth` repeats the new-user and new-project counts; it is not a percentage. |
| `groups_summary.avg_*` | `total / max(groups, 1)`, rounded to 2 decimals, so zero groups never divides by zero. |
| `totals.project_groups` | Same count as `statistics.total_project_groups` on `GET /system/info`. |
| `system_health.overall_status` | `healthy` only when both database and Redis are `healthy`, otherwise `degraded`. |

### User statistics

`GET /admin/users/statistics?days=30` — `days` is `1`–`365` (default `30`).

```json
{
  "success": true,
  "statistics": {
    "total_users": 1180,
    "user_types": {"root": 2, "admin": 15, "consumer": 1163},
    "new_users": 120,
    "active_users": 640,
    "growth_rate": 11.32,
    "date_range_days": 30,
    "activity_rate": 54.24
  },
  "generated_at": "2026-03-25T10:30:00Z"
}
```

`total_users` and `user_types` count active users only. `new_users` were created in the window and
are still active; `active_users` are distinct users with activity-log entries in the window.
`growth_rate` is `new / (total - new) × 100` and `activity_rate` is `active / total × 100`. If the
query fails the route still answers `200`, with `statistics` holding only an `error` string.

### Project statistics

`GET /admin/projects/statistics?days=30` — same `days` range.

```json
{
  "success": true,
  "statistics": {
    "total_projects": 42,
    "new_projects": 3,
    "active_projects": 30,
    "avg_members_per_project": 27.5,
    "date_range_days": 30,
    "utilization_rate": 71.43
  },
  "generated_at": "2026-03-25T10:30:00Z"
}
```

`total_projects` counts active projects. `active_projects` are distinct projects with activity-log
entries in the window, and `utilization_rate` is `active / total × 100`.
`avg_members_per_project` averages active user-project memberships. Failures answer `200` with
`statistics.error`, as above.

## Activity feed

These routes read the activity log. The [audit logs suite](audit_logs/README.md) covers API audit
logs, security events, per-user activity and export.

### List activity

`GET /admin/activity` returns entries newest first.

| Query parameter | Type | Default | Notes |
| --- | --- | --- | --- |
| `limit` | int | `50` | `1`–`500`. |
| `offset` | int | `0` | `>= 0`. |
| `activity_type_filter` | string | none | Exact activity type; see `GET /admin/activity/types`. |
| `user_id` | string | none | Acting user's **internal** ID (`usr-...`), not the public `user_hash`. |
| `project_id` | string | none | Internal project ID (`proj-...`), not the `project_hash`. |
| `days` | int | `30` | `1`–`365`. |
| `search` | string | none | Substring match on `activity_type`, `details` and `username`; an empty value is ignored. |

```bash
curl "$BASE_URL/admin/activity?days=1&activity_type_filter=user_login&search=AUTH_1001" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Each item in `activities` has `id`, `activity_type`, `details`, `created_at`, `ip_address`, and
`user`, `project` and `target_user` objects (`user` and `target_user`: `id`, `username`,
`user_hash`; `project`: `id`, `name`, `hash`), each `null` when absent. The response also has
`pagination` (`total`, `limit`, `offset`, `has_more`, `next_offset`), the echoed `filters`, and
`generated_at`. Out-of-range query values answer `400` `VAL_3001`.

### Activity types

`GET /admin/activity/types` returns `activity_types`, every value of the server's `ActivityType`
enum (whether or not it has been logged), plus `generated_at`. Use these values for
`activity_type_filter`.

### Activity detail

`GET /admin/activity/{activity_id}` returns one entry under `activity`, with `generated_at`.

```bash
curl "$BASE_URL/admin/activity/act-0123456789abcdef0123456789abcdef" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

- `activity_id` must be `act-` followed by exactly 32 hex characters; anything else answers `400`
  `VAL_3001`. A well-formed ID with no entry answers `404` `NF_4004`.
- `activity` has the feed fields plus `severity_level`, `user_agent`, `metadata`, and the catalog's
  `activity_name`, `activity_category` and `activity_description`.

## System health & metrics

Pick the probe by what you need:

| Path | Method | Auth | Checks | Result |
| --- | --- | --- | --- | --- |
| `/ping` | `GET` | Public | Nothing | `204`, no body |
| `/system/ping` | `GET` | Public | Nothing | `200` JSON with `timestamp` |
| `/system/info` | `GET` | Any access session | Aggregate counts | `200` |
| `/system/health` | `GET` | Any access session | Database, Redis, groups, email, Patreon, billing | `200`, `status` `healthy` or `degraded` |
| `/admin/health` | `GET` | Root or admin | Database, Redis | `200`, score and `healthy`/`degraded`/`unhealthy` |
| `/admin/system/overview` | `GET` | Root or admin | Host CPU, memory, disk; database; Redis; app metrics; Patreon; billing | `200`, score and status |

Load balancers and container health checks should use `/ping` or `/system/ping`: they touch no
database, Redis or provider, and need no credentials. Every request still needs a `User-Agent`.

### Liveness probes

```bash
curl -i "$BASE_URL/ping"
curl "$BASE_URL/system/ping"
```

`/system/ping` answers:

```json
{
  "success": true,
  "message": "Group-based authentication API is running",
  "timestamp": "2026-03-25T10:30:00Z"
}
```

### System info

`GET /system/info` returns service identity and aggregate counts.

```bash
curl "$BASE_URL/system/info" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

```json
{
  "success": true,
  "message": null,
  "system": {
    "name": "Group-Based Multi-Project Authentication API",
    "version": "1.0.0",
    "architecture": "hierarchical-group-based",
    "status": "operational"
  },
  "statistics": {
    "total_users": 1250,
    "total_projects": 45,
    "total_user_groups": 28,
    "total_project_groups": 12,
    "authentication_type": "group-based-jwt"
  },
  "features": [
    "hierarchical-group-access-control",
    "global-user-groups",
    "project-permission-groups",
    "multi-project-support",
    "session-management-with-group-context",
    "comprehensive-audit-trail",
    "restful-admin-api"
  ]
}
```

`system.version` is a fixed string in `src/routes/system.py`; it is not the OpenAPI version
(`2.2.0`). Each count falls back to `0` if its query fails.

### Component health

`GET /system/health` reports every component and an overall `status`.

```bash
curl "$BASE_URL/system/health" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

```jsonc
{
  "success": true,
  "message": null,
  "status": "healthy",
  "timestamp": "2026-03-25T10:30:00Z",
  "components": {
    "database": { "status": "healthy", "message": "Database accessible" },
    "redis": { "status": "healthy", "message": "Redis accessible" },
    "group_system": { "status": "healthy", "message": "Group system operational: 28 user groups, 12 project groups" },
    "email_provider": { "status": "disabled", "provider": "fake", "delivery_enabled": false, "ready": false },
    "email_outbox": { "status": "healthy", "queue_depth": 0, "dlq_depth": 0, "success_ratio": null },
    "email_worker": { "status": "disabled", "heartbeat_count": 0, "latest_heartbeat": null },
    "patreon": { "status": "disabled" },                  // plus readiness, token, webhook, sync details
    "billing": { "status": "disabled" },                  // plus readiness, webhooks, snapshots, sync, retention
    "billing_provider_stripe": { "status": "disabled" },
    "billing_webhooks": { "status": "disabled" },
    "billing_sync": { "status": "disabled" }
  }
}
```

The HTTP status is always `200` once the caller is authenticated; component problems change only
`status`, which becomes `degraded` (never `unhealthy`) when any of these holds:

- `database`, `redis` or `group_system` reports `unhealthy`;
- email delivery is enabled (`email_provider.delivery_enabled`) and the provider is not `ready`, the
  outbox is not `healthy` or `disabled`, or `email_worker` is not `healthy` (no worker heartbeat);
- `patreon` reports `degraded`, `stale`, `retrying`, `unhealthy`, `not_ready` or `unknown`;
- billing is enabled and `billing`, `billing_provider_stripe`, `billing_webhooks` or `billing_sync`
  reports one of those statuses.

Disabled email, Patreon or billing never degrade the result. Authenticating the caller needs Redis
and the database, so an outage of either usually fails the request during authentication, before
any component is checked.

### Admin health score

`GET /admin/health` checks only the database and Redis and scores them.

```json
{
  "overall_status": "healthy",
  "health_score": 100,
  "components": {
    "database": {"status": "healthy", "message": "Database accessible", "timestamp": "2026-03-25T10:30:00Z"},
    "redis": {"status": "healthy", "message": "Redis accessible", "timestamp": "2026-03-25T10:30:00Z"}
  },
  "metrics": {
    "total_users": 1250,
    "total_projects": 45,
    "active_sessions": 342
  },
  "checked_at": "2026-03-25T10:30:00Z"
}
```

The score starts at `100`, minus `50` if the database is not `healthy` and `30` if Redis is not.
`overall_status` is `healthy` at `100`, `degraded` at `70` or more (Redis down), otherwise
`unhealthy` (database down). A failing component reports `status` `unhealthy` with an error
`message`.

### System overview

`GET /admin/system/overview` adds host metrics. CPU usage is sampled over `1` second, so the call
takes at least that long.

```jsonc
{
  "success": true,
  "system_overview": {
    "timestamp": "2026-03-25T10:30:00Z",
    "health_score": 100,
    "status": "healthy",
    "system": { "cpu_usage": 12.5, "memory_usage": 41.0, "memory_available": 9350, "disk_usage": 55.2, "disk_free": 120, "uptime": "12d 4h 7m" },
    "database": { "status": "healthy", "response_time_ms": 3.1, "connections": "12", "size_mb": 84.5, "table_count": 61 },
    "redis": { "status": "healthy", "response_time_ms": 0.8, "memory_used": "3.2M", "connected_clients": 9 },
    "application": { "entities": { }, "activity": { }, "performance": { } },
    "patreon": { "status": "disabled" },
    "billing": { "status": "disabled" }
  },
  "generated_at": "2026-03-25T10:30:00Z"
}
```

`memory_available` is in MB and `disk_free` in GB. The score starts at `100` and loses `10`/`20` for
CPU above `60`/`80` %, `10`/`20` for memory above `75`/`90` %, `30` if the database is not healthy
(or `10` if it answers in over `1000` ms), and `20` if Redis is not healthy (or `5` over `500` ms).
`status` is `healthy` at `80` or more, `degraded` at `60` or more, otherwise `unhealthy`. If the
overview itself fails, `system_overview` is `{"status": "error", "health_score": 0, ...}` with an
`error` message.

## Cache management

Redis holds access sessions and short-lived authorization caches. These routes inspect and drop
them; refresh families, rate-limit counters and API-key validation entries are never touched.

### Cache statistics

`GET /system/cache/stats` — any valid access session.

```bash
curl "$BASE_URL/system/cache/stats" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

```json
{
  "success": true,
  "message": null,
  "cache_statistics": {
    "sessions": 342,
    "access_checks": 120,
    "permission_checks": 85,
    "user_types": 60,
    "role_checks": 14,
    "api_keys": 5,
    "total_keys": 1540
  },
  "cache_configuration": {
    "session_ttl": "3600 seconds (1 hour)",
    "access_check_ttl": "1800 seconds (30 minutes)",
    "rbac_check_ttl": "1800 seconds (30 minutes)",
    "user_info_ttl": "3600 seconds (1 hour)"
  },
  "timestamp": "2026-03-25T10:30:00Z"
}
```

`cache_statistics` counts keys by prefix (`session:`, `access:`, `permission:`, `user_type:`,
`role:`, `apikey:`) and `total_keys` counts every key in the Redis database. It is `{}` if Redis
cannot be read. No hit-rate metrics are collected, and `cache_configuration` is fixed text, not
read from runtime settings.

### Clear the whole cache

`POST /system/cache/clear` — root or admin. Deletes every `session:*`, `access:*`, `role:*`,
`permission:*`, `user_info:*` and `user_type:*` key.

```bash
curl -X POST "$BASE_URL/system/cache/clear" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

```json
{
  "success": true,
  "message": "Entire authentication cache has been cleared",
  "cleared_by": "usr-[550e]...[0000]",
  "timestamp": "2026-03-25T10:30:00Z",
  "warning": "All users will need to re-authenticate or may experience slower response times"
}
```

> [!WARNING]
> Deleting `session:*` revokes every live access session, including the caller's. Every client must
> refresh or sign in again. Prefer per-user invalidation.

A failed Redis deletion answers `500` `INT_7001`.

### Invalidate one user

`POST /system/cache/invalidate/user/{user_hash}` — root or admin. Drops the user's `access:*`,
`permission:*`, `user_type:*` and `user_info:*` entries and their access sessions, so their current
access tokens stop working until they refresh. Refresh families are kept.

```bash
curl -X POST "$BASE_URL/system/cache/invalidate/user/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

```json
{
  "success": true,
  "message": "Cache invalidated for user: usr-[7f3c]...[9a21]",
  "invalidated_by": "usr-[550e]...[0000]",
  "timestamp": "2026-03-25T10:30:00Z"
}
```

An unknown or inactive `user_hash` answers `404` `NF_4004`; a Redis failure answers `500` `INT_7001`.

### Invalidate one project

`POST /system/cache/invalidate/project/{project_id}` — root or admin. Takes the project ID
(`proj-...`), drops `access:*`, `permission:*` and `role:*` entries whose keys reference it, and
answers `200` even when nothing matched (the project is not looked up).

`project_id` may contain only letters, digits, `-` and `_` (at most 128 characters), so it cannot
widen the key pattern; anything else answers `400` `VAL_3001` (`validation_errors[].field` =
`path.project_id`).

## User types and admin project assignments

Creating root and admin users, reading and changing a user's type, listing users by type, type
statistics, and assigning projects to admins are all under `/user-types/*`
(`src/routes/user_types_auth.py`). They are documented in
[Users: user types and admin assignment](users/user-types.md). Project and project-group management
is in the [projects suite](projects/README.md) and the [groups suite](groups/README.md).

## Bulk operations

Four routes change many users in one request. All take form fields
(`application/x-www-form-urlencoded` or `multipart/form-data`); list fields repeat the key
(`user_hashes=a&user_hashes=b`).

| Path | Method | Auth | Max `user_hashes` | Other fields |
| --- | --- | --- | --- | --- |
| `/admin/users/bulk-update` | `POST` | Root or admin user with `admin` or `manage_users` | `100` | `is_active` and/or `user_type` (at least one); `user_type` needs root |
| `/admin/users/bulk-delete` | `POST` | Root or admin user with `admin` or `manage_users` | `50` | `confirm_deletion=true` required |
| `/admin/projects/{project_hash}/bulk-assign-roles` | `POST` | `admin` | `100` | `role_names` (role names, repeatable) |
| `/admin/user-groups/bulk-assign` | `POST` | `admin` | `100` | `group_names` (user-group names, repeatable) |

### Request rejections

These reject the whole request before anything is written:

| Condition | Response |
| --- | --- |
| Required list or field missing | `400` `VAL_3001` with `validation_errors` |
| Too many `user_hashes` | `400` `VAL_3010` |
| Bulk update: invalid `user_type` / no update field | `400` `VAL_3012` / `400` `VAL_3002` |
| Bulk update: `force_password_reset` sent | `400` `VAL_3001`; it is not supported (use reset-link recovery) |
| Bulk update or delete: caller is not a root or admin user (a consumer holding `admin` or `manage_users` included) | `403` `AUTHZ_2002` |
| Bulk update: `user_type` by a non-root caller | `403` `AUTHZ_2002` |
| Bulk delete: `confirm_deletion` not `true` | `400` `VAL_3001` |
| Role assignment: unknown project | `404` `NF_4004` |
| Role assignment: any unknown or inactive role name | `404` `NF_4007` |
| Role assignment by non-root: a role grants a reserved permission (`admin`, `manage_users`, ...) | `403` `AUTHZ_2002` |
| Role assignment by non-root: caller lists themselves | `403` `AUTHZ_2009` |
| Group assignment: any unknown or inactive group name | `404` `NF_4003` |

### Partial failures

Once a request passes those checks, items are processed one at a time and the route answers `200`
even if some items fail. Items are not rolled back as a group: a failure does not undo earlier
successes. Always read the counts:

| Field | Content |
| --- | --- |
| `summary` | `total_requested` (number of `user_hashes`), `success_count`, `error_count`; plus `skipped_count` (always `0`) on update and `protected_count` (root users skipped) on delete. |
| `results[]` | One entry per item: `user_hash`, `success`, `error` on failure; `user_id` (internal ID) on update, `role_name` on role assignment, `group_name` on group assignment. Role and group assignments have one entry per user per role or group. |
| `errors[]` | `{"user": "<user_hash>", "error": "..."}` per failed item, or `{"operation": "...", "error": "..."}` when the whole batch stopped. |
| `warnings[]` | Bulk delete only: `{"user": "<user_hash>", "warning": "..."}` for a user deleted whose session revocation failed. |
| `performed_by`, `performed_at` | Caller username and UTC time. |

Typical item errors: `User not found`, `Cannot bulk delete root users`,
`Cannot deactivate your own account`, `Cannot delete your own account`,
`Root users are outside your administrative scope`, `User not in your administrative scope`,
`Update failed`, `Delete failed`, `Auth revocation failed`, `Role assignment failed`,
`Group assignment failed`.

Route-specific behavior:

- **Bulk update and delete** check each target like the single-user routes: nobody may deactivate
  or delete their own account, and an admin may only touch non-root users who reach one of the
  projects the admin is assigned to. A refused user fails in `results` and is left unchanged.
- **Bulk update** also returns `updates_applied`. Setting `is_active=false` revokes each
  deactivated user's access sessions and refresh families, and so does a `user_type` change.
- **Bulk delete** never deletes root users; they count in `protected_count` and appear in `errors`.
  Each deleted user's access sessions and refresh families are revoked; `warnings` names any user
  whose revocation failed (their tokens are still refused because the account is inactive).
- **Bulk role assignment** uses the global role system; the project is used for validation and the
  audit trail. A user holds one global role, so with several `role_names` each user ends up with the
  last one. Send one role per request. The response adds `project` and `roles_assigned`.
- **Bulk group assignment** adds every user to every group and adds `groups_assigned`.

```bash
curl -X POST "$BASE_URL/admin/users/bulk-update" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hashes=$USER_A&user_hashes=$USER_B&is_active=false"
```

```json
{
  "success": true,
  "message": "Bulk update completed: 1 succeeded, 1 failed",
  "summary": {"total_requested": 2, "success_count": 1, "error_count": 1, "skipped_count": 0},
  "updates_applied": {"is_active": false},
  "results": [
    {"user_hash": "usr-7f3c...", "success": true, "user_id": "usr-0b12..."},
    {"user_hash": "usr-9d44...", "success": false, "error": "User not found"}
  ],
  "errors": [{"user": "usr-9d44...", "error": "User not found"}],
  "performed_by": "ops-admin",
  "performed_at": "2026-03-25T10:30:00Z"
}
```

User-lifecycle details for bulk update and delete are in
[Users: bulk operations](users/bulk-operations.md); role behavior is in the
[roles suite](roles/README.md).

## Admin email operations

Admin email work is documented with its owning suite:

| Task | Route | Guide |
| --- | --- | --- |
| List a user's addresses (masked) | `GET /users/{user_hash}/emails` | [User email management](users/email-management.md) |
| Resend an activation link | `POST /users/{user_hash}/emails/{email_id}/resend` | [User email management](users/email-management.md) |
| Send a password-reset link | `POST /users/{user_hash}/reset-password` | [Users usage](users/usage.md) |
| Inspect delivery logs | `GET /admin/email/logs` | [Audit logs usage](audit_logs/usage.md) |
| Manage templates (root only) | `/admin/email-templates/*` | [Email suite](email/README.md) |

The per-user routes are root or admin only, and admins are limited to users who reach one of their
assigned projects; delivery logs need root or admin, and templates need root. The per-user routes
and delivery logs never return a password, a reset link, a full address or a message body.

## Operational scenarios

### Daily health check

```bash
# 1. Overall status and any component that is not healthy
curl -s "$BASE_URL/system/health" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  | jq '{status, unhealthy: (.components | with_entries(select(.value.status != "healthy")))}'

# 2. Headline counts and database/Redis status
curl -s "$BASE_URL/admin/dashboard/stats" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 3. Failed password logins in the last day
curl -s "$BASE_URL/admin/activity?days=1&activity_type_filter=user_login&search=AUTH_1001&limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Components reporting `disabled` in step 1 are expected when that integration is off. The
`user_login` activity type is shared with platform login, validate, refresh and switch-project;
`search=AUTH_1001` narrows it to failed password logins, whose `details` carry the error code.

### Incident lockout

To shut out compromised accounts:

1. Deactivate them. This also revokes their access sessions and refresh families.

   ```bash
   curl -X POST "$BASE_URL/admin/users/bulk-update" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d "user_hashes=$USER_A&user_hashes=$USER_B&is_active=false"
   ```

2. Check `summary.error_count`; retry any user listed in `errors`.
3. API keys of a deactivated owner fail validation once the `60`-second validation cache expires.
   To revoke them permanently, list them with `GET /api-keys/users/{user_hash}` and revoke each
   (see the [API keys suite](api-keys/README.md); revocation needs a recent sign-in).
4. Review what the accounts did, using the internal IDs from `results[].user_id`:

   ```bash
   curl "$BASE_URL/admin/activity?user_id=$INTERNAL_USER_ID&days=7" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

Per-user cache invalidation is not needed after deactivation, and answers `404` for an inactive user.

### Access review

1. Look at activity and growth over the review window:

   ```bash
   curl "$BASE_URL/admin/users/statistics?days=90" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

2. List deactivated users and users who never signed in:

   ```bash
   curl -s "$BASE_URL/users/list?include_inactive=true&limit=500" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     | jq '.users | map(select(.is_active == false or .last_login == null)) | map({user_hash, username, is_active, last_login})'
   ```

   Admins see only non-root users who share a project with them; run this as root for the full
   list.
3. Review who holds elevated types with `GET /user-types/users/admin` and
   `GET /user-types/users/root` (listing `root` is root-only; see
   [Users: user types](users/user-types.md)).
4. Deactivate stale accounts with bulk update after manual review.

## Best practices

- Probe liveness with `/ping` or `/system/ping`; alert on `/system/health` `status` and read
  `components` for the cause.
- Prefer `POST /system/cache/invalidate/user/{user_hash}` over a full clear; the full clear signs
  everyone out.
- Treat every bulk `200` as possibly partial: check `summary.error_count` and `errors`.
- Keep bulk role assignments to one role name per request.
- Test a bulk change on a couple of users before running it on a hundred.
- Keep the number of root and admin users small, and review admin activity in the
  [audit logs suite](audit_logs/README.md).

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `/system/health` `status` is `degraded` | A component listed under [Component health](#component-health) is failing. | Find the component whose `status` is not `healthy` or `disabled`. |
| Load balancer gets `401` from `/system/health` | The route needs an access session. | Probe `/ping` or `/system/ping`. |
| `403` `AUTHZ_2001` on dashboard, activity or cache write routes | Caller's `user_type` is not root or `admin`; permissions do not count here. | Use a root or admin account. |
| `403` `AUTHZ_2002` on bulk routes | Session lacks the `admin` (or `manage_users`) permission, or `user_type` change by non-root. | Grant the permission or use root. |
| Everyone was signed out | `POST /system/cache/clear` deleted all access sessions. | Expected; clients refresh or sign in. |
| `400` on `/system/cache/invalidate/project/...` | `project_id` holds a character other than letters, digits, `-` or `_`, or is longer than 128. | Send the plain project ID (`proj-...`). |
| `404` from per-user cache invalidation | User unknown or inactive. | Deactivation already revoked the user's sessions. |
| Bulk request `200` but `error_count > 0` | Per-item failures. | Read `results[]` and `errors[]`; retry the failed items. |
| Only one role remains after bulk role assignment | A user has one global role; the last name wins. | Send one role per request. |
| `statistics` contains only `error` | The statistics query failed. | Check database health. |
| `/admin/activity?user_id=usr-...` returns nothing | A `user_hash` was sent instead of the internal ID. | Use `user.id` from the feed or `results[].user_id` from bulk update. |
| `400` on `/admin/activity/{activity_id}` | ID is not `act-` plus 32 hex characters. | Copy `id` from the feed. |
| `/admin/system/overview` is slow | CPU is sampled for `1` second. | Expected. |

## Quick reference

| Path | Method | Auth | Purpose |
| --- | --- | --- | --- |
| `/admin/dashboard/stats` | `GET` | Root or admin | Headline counts and database/Redis status |
| `/admin/users/statistics` | `GET` | Root or admin | User counts, growth and activity rate (`days`) |
| `/admin/projects/statistics` | `GET` | Root or admin | Project counts and utilization (`days`) |
| `/admin/activity` | `GET` | Root or admin | Activity feed with filters |
| `/admin/activity/types` | `GET` | Root or admin | Valid `activity_type_filter` values |
| `/admin/activity/{activity_id}` | `GET` | Root or admin | One activity entry |
| `/admin/health` | `GET` | Root or admin | Database/Redis health score |
| `/admin/system/overview` | `GET` | Root or admin | Host, database, Redis, app, Patreon, billing |
| `/ping` | `GET` | Public | Liveness (`204`) |
| `/system/ping` | `GET` | Public | Liveness (`200` JSON) |
| `/system/info` | `GET` | Any access session | Service identity and counts |
| `/system/health` | `GET` | Any access session | Component health |
| `/system/cache/stats` | `GET` | Any access session | Cache key counts |
| `/system/cache/clear` | `POST` | Root or admin | Delete all auth cache and access sessions |
| `/system/cache/invalidate/user/{user_hash}` | `POST` | Root or admin | Drop one user's cache and access sessions |
| `/system/cache/invalidate/project/{project_id}` | `POST` | Root or admin | Drop project cache entries |
| `/admin/users/bulk-update` | `POST` | `admin` or `manage_users` permission | Activate, deactivate or retype up to `100` users |
| `/admin/users/bulk-delete` | `POST` | `admin` or `manage_users` permission | Delete up to `50` users |
| `/admin/projects/{project_hash}/bulk-assign-roles` | `POST` | `admin` permission | Assign a global role to up to `100` users |
| `/admin/user-groups/bulk-assign` | `POST` | `admin` permission | Add up to `100` users to user groups |

## Related

- [Error reference](errors.md)
- [Audit logs suite](audit_logs/README.md)
- [Users suite](users/README.md)
- [Groups suite](groups/README.md)
- [Projects suite](projects/README.md)
- [Permissions suite](permissions/README.md)
