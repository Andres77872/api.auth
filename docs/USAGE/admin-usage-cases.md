# Admin & System Management Usage Guide

Complete practical guide for admin dashboard operations, system monitoring, bulk operations, and cache management.

> For activity logs and audit details, see [Audit Logs Documentation Suite](audit_logs/README.md).
> For error codes, see [Error Reference](errors.md).

> **Important**: Every request MUST include a `User-Agent` header. Missing it returns `422`.

---

## 📖 Table of Contents

- [Admin Dashboard](#admin-dashboard)
- [Activity Monitoring](#activity-monitoring)
- [System Health & Metrics](#system-health--metrics)
- [Admin Email Operations](#admin-email-operations)
- [Cache Management](#cache-management)
- [User Type Management](#user-type-management)
- [Admin Project Management](#admin-project-management)
- [Bulk Operations](#bulk-operations)
- [Common Scenarios](#common-scenarios)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Admin Dashboard

### Get Dashboard Statistics

**Scenario**: View comprehensive system statistics for the admin dashboard.

```bash
curl -X GET "http://localhost:8000/admin/dashboard/stats" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
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
    "database": {"status": "healthy", "latency_ms": 5},
    "redis": {"status": "healthy", "latency_ms": 2},
    "overall_status": "healthy"
  },
  "generated_at": "2024-03-25T10:30:00Z"
}
```

**Derived fields and notes:**

- `groups_summary.avg_users_per_group` is `round(total_users / max(total_user_groups, 1), 2)` and `avg_projects_per_group` is `round(total_projects / max(total_project_groups, 1), 2)`. The `max(..., 1)` guard means these never divide by zero — with zero groups the denominator is `1`, so the average equals the raw total.
- `totals.project_groups` (and `groups_summary.total_project_groups`) come from `count_project_groups()` (project-group containers), which is **not** the same source as `/system/info` `total_project_groups` (`count_project_permission_groups()`). See [Project groups vs. permission groups](#project-groups-vs-permission-groups).
- The `system_health.database` / `system_health.redis` blocks are produced verbatim by `check_database_health()` / `check_redis_health()`. The `latency_ms` fields above are **illustrative**; the exact keys returned depend on those health-check helpers and are not guaranteed. `overall_status` is `"healthy"` only when both database and redis report `"healthy"`, otherwise `"degraded"`.

#### Project groups vs. permission groups

The system counts two distinct group concepts, and they surface in different endpoints:

| Field | Endpoint | Source helper | Meaning |
|-------|----------|---------------|---------|
| `project_groups` | `/admin/dashboard/stats` | `count_project_groups()` | Project-group containers (groups-of-groups architecture) |
| `total_project_groups` | `/system/info` | `count_project_permission_groups()` | Project **permission** groups |

These count different things and can legitimately differ. Do not assume the two values match.

### Get User Statistics

**Scenario**: Get detailed user statistics with growth rates.

```bash
# Default (30 days)
curl -X GET "http://localhost:8000/admin/users/statistics" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Custom time range
curl -X GET "http://localhost:8000/admin/users/statistics?days=90" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "statistics": {
    "total_users": 1250,
    "active_users": 1180,
    "inactive_users": 70,
    "new_users_period": 120,
    "growth_rate_percentage": 10.6,
    "user_type_breakdown": {
      "root": 2,
      "admin": 15,
      "consumer": 1233
    },
    "top_groups": [
      {"group_name": "developers", "member_count": 450},
      {"group_name": "qa_team", "member_count": 280}
    ]
  },
  "generated_at": "2024-03-25T10:30:00Z"
}
```

### Get Project Statistics

**Scenario**: Get detailed project statistics and health metrics.

```bash
curl -X GET "http://localhost:8000/admin/projects/statistics?days=30" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "statistics": {
    "total_projects": 45,
    "active_projects": 42,
    "new_projects_period": 3,
    "average_members_per_project": 28,
    "most_active_projects": [
      {"project_name": "API v2", "activity_count": 580},
      {"project_name": "Mobile App", "activity_count": 450}
    ]
  },
  "generated_at": "2024-03-25T10:30:00Z"
}
```

### Get System Overview

**Scenario**: Get comprehensive system health and performance overview.

```bash
curl -X GET "http://localhost:8000/admin/system/overview" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "system_overview": {
    "health_score": 100,
    "uptime": "99.9%",
    "database_status": "healthy",
    "cache_status": "healthy",
    "api_metrics": {
      "requests_today": 15420,
      "avg_response_time_ms": 45,
      "error_rate": 0.02
    }
  },
  "generated_at": "2024-03-25T10:30:00Z"
}
```

---

## Activity Monitoring

> **Note**: The activity feed (`/admin/activity`), activity detail (`/admin/activity/{activity_id}`), and activity types (`/admin/activity/types`) are documented here for quick reference. For comprehensive audit log coverage including API audit logs, security events, export functionality, audit statistics, and detailed filtering, see [Audit Logs Usage Guide](audit_logs/usage.md).

For full feed documentation, response shapes, and examples, see the canonical source: **[Audit Logs Usage → Activity Feed](audit_logs/usage.md#activity-feed-dashboard)**.

All three endpoints require **Admin/Root** (`user_type == 'admin'` or root); non-admins get `403 ACCESS_DENIED`.

### Activity Feed Query Parameters

`GET /admin/activity` accepts the following query parameters (all optional):

| Parameter | Type | Default | Range / Notes |
|-----------|------|---------|---------------|
| `limit` | int | `50` | `1`–`500` |
| `offset` | int | `0` | `>= 0` |
| `activity_type_filter` | string | none | Filter by a single activity type (see `/admin/activity/types`) |
| `user_id` | string | none | Filter by user ID |
| `project_id` | string | none | Filter by project ID |
| `days` | int | `30` | `1`–`365`, look-back window |
| `search` | string | none | Free-text search across `activity_type`, `details`, and `username`. An empty string is treated as no filter. |

The response includes `activities[]`, a `pagination` block (`total`, `limit`, `offset`, `has_more`, `next_offset`), the echoed `filters`, and `generated_at`. Canonical feed shape lives in [Audit Logs Usage → Activity Feed](audit_logs/usage.md#activity-feed-dashboard).

### Activity Detail

**Scenario**: Inspect a single activity-log entry with full enriched metadata.

```bash
curl -X GET "http://localhost:8000/admin/activity/act-0123456789abcdef0123456789abcdef" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

**Input contract:**

- `activity_id` (path) must match the regex `^act-[0-9a-fA-F]{32}$` — the literal prefix `act-` followed by exactly 32 hexadecimal characters.
- An empty or malformed `activity_id` returns `400 INVALID_INPUT`.
- A well-formed id that does not exist returns `404 RESOURCE_NOT_FOUND`.

The detail response wraps the entry under `activity` and includes enriched fields beyond the feed shape: `severity_level`, `user_agent`, `metadata`, `activity_name`, `activity_category`, and `activity_description` — in addition to the standard `id`, `activity_type`, `details`, `created_at`, `user`, `project`, `target_user`, and `ip_address`. A `generated_at` timestamp is included at the top level.

**Response (abridged):**
```json
{
  "activity": {
    "id": "act-0123456789abcdef0123456789abcdef",
    "activity_type": "user_login",
    "details": "User logged in",
    "severity_level": "info",
    "created_at": "2024-03-25T10:30:00Z",
    "user": {"id": 42, "username": "alice", "user_hash": "usr-..."},
    "project": null,
    "target_user": null,
    "ip_address": "203.0.113.10",
    "user_agent": "my-client/1.0",
    "metadata": {},
    "activity_name": "User Login",
    "activity_category": "authentication",
    "activity_description": "A user authenticated successfully"
  },
  "generated_at": "2024-03-25T10:30:00Z"
}
```

### Activity Types

`GET /admin/activity/types` returns `activity_types[]` enumerated from the `ActivityType` enum (the full catalog of valid values for `activity_type_filter`), plus `generated_at`. Admin/Root only.

---

## System Health & Metrics

### Authenticated System Info

**Scenario**: Check aggregate system information with any valid access session.

```bash
curl -X GET "http://localhost:8000/system/info" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

**Response:**
```json
{
  "success": true,
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

> **Note**: `system.version` is a build/code version hardcoded in `src/routes/system.py` (currently `1.0.0`) and is independent of the documentation/API version label (`2.2.0`) in this guide's footer — the two values may legitimately differ.
>
> **Note**: `statistics.total_project_groups` here is sourced from `count_project_permission_groups()` — i.e. project **permission** groups, not the project-group containers counted by `/admin/dashboard/stats`. The two numbers can legitimately differ; see [Project groups vs. permission groups](#project-groups-vs-permission-groups).

### System Health Check

**Scenario**: Check detailed system health with any valid access session.

```bash
curl -X GET "http://localhost:8000/system/health" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

**Response:**
```json
{
  "success": true,
  "status": "healthy",
  "timestamp": "2024-03-25T10:30:00Z",
  "components": {
    "database": {
      "status": "healthy",
      "message": "Database accessible"
    },
    "redis": {
      "status": "healthy",
      "message": "Redis accessible"
    },
    "group_system": {
      "status": "healthy",
      "message": "Group system operational: 28 user groups, 12 project groups"
    },
    "email_provider": {
      "status": "disabled",
      "provider": "fake",
      "delivery_enabled": false
    },
    "email_outbox": {
      "status": "healthy",
      "queue_depth": 0,
      "dlq_depth": 0,
      "success_ratio": null
    },
    "email_worker": {
      "status": "disabled",
      "heartbeat_count": 0,
      "latest_heartbeat": null
    }
  }
}
```

**Degradation rule**: the top-level `status` starts at `"healthy"` and degrades to `"degraded"` if the database, Redis, or group-system check fails. This endpoint never returns `"unhealthy"` — its worst top-level status is `"degraded"`. Email components (`email_provider`, `email_outbox`, `email_worker`) are **additive**: they only contribute to degradation when email delivery is enabled (`email_provider.delivery_enabled == true`) and the provider is `not_ready` or the outbox status is not `healthy`/`disabled`. When email delivery is disabled, these components report disabled/not-ready states safely and never make unrelated authentication health fail.

### Admin Email Operations

Admin/root email operations expose operational state without leaking PII:

```bash
curl -X GET "http://localhost:8000/users/usr-target.../emails" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"

curl -X POST "http://localhost:8000/users/usr-target.../emails/uem-123/resend" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"

curl -X GET "http://localhost:8000/admin/email/logs?limit=50" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

Admin email logs return recipient hash + masked email only. They do not expose full recipient email, subject/body, template variables, tokens, reset/activation links, raw idempotency keys, or provider payloads.

Admin password reset is reset-link based:

```bash
curl -X POST "http://localhost:8000/users/usr-target.../reset-password" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Idempotency-Key: admin-reset-001" \
  -H "User-Agent: my-client/1.0"
```

The response does not contain a plaintext password, reset token, reset link, full recipient email, subject/body, or provider payload. If the target has a primary activated email, the route enqueues a reset-link email through the outbox. If not, the public/admin posture remains generic and operators must use redacted audit/email logs for troubleshooting.

### Simple Ping

**Scenario**: Quick health check endpoint.

```bash
curl -X GET "http://localhost:8000/system/ping"
```

**Response:**
```json
{
  "success": true,
  "message": "Group-based authentication API is running",
  "timestamp": "2024-03-25T10:30:00Z"
}
```

### Admin Health Check

**Scenario**: Detailed health check for admins with metrics.

```bash
curl -X GET "http://localhost:8000/admin/health" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "overall_status": "healthy",
  "health_score": 100,
  "components": {
    "database": {"status": "healthy", "latency_ms": 5},
    "redis": {"status": "healthy", "latency_ms": 2}
  },
  "metrics": {
    "total_users": 1250,
    "total_projects": 45,
    "active_sessions": 342
  },
  "checked_at": "2024-03-25T10:30:00Z"
}
```

**Health scoring rule** (`/admin/health`): the score starts at `100`, with `-50` when the database is not `"healthy"` and `-30` when Redis is not `"healthy"`. The resulting `overall_status` is:

| `health_score` | `overall_status` |
|----------------|------------------|
| `>= 100` | `healthy` |
| `>= 70` | `degraded` |
| otherwise | `unhealthy` |

> **Note**: the `components.database` / `components.redis` blocks are produced verbatim by `check_database_health()` / `check_redis_health()`. The `latency_ms` field shown above is **illustrative** — the exact keys depend on those helpers and are not guaranteed. `/system/health` accepts any valid access session; this endpoint requires **Admin/Root** auth and can return `"unhealthy"`.

---

## Cache Management

> **Auth note**: `GET /system/cache/stats` requires only a **valid session** (any user type) — it is **not** admin-only. By contrast, `POST /system/cache/clear` and both invalidate endpoints require **Admin/Root** and return `403 ACCESS_DENIED` otherwise. The invalidate-on-failure paths return `500 INTERNAL_ERROR` if the cache operation fails.

### Get Cache Statistics

**Scenario**: View cache performance metrics. Requires only a valid session (any user type), so `YOUR_TOKEN` below need not be an admin token.

```bash
curl -X GET "http://localhost:8000/system/cache/stats" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "cache_statistics": {
    "total_keys": 1540,
    "memory_used_mb": 45.2,
    "hit_rate": 0.92,
    "miss_rate": 0.08
  },
  "cache_configuration": {
    "session_ttl": "3600 seconds (1 hour)",
    "access_check_ttl": "1800 seconds (30 minutes)",
    "rbac_check_ttl": "1800 seconds (30 minutes)",
    "user_info_ttl": "3600 seconds (1 hour)"
  },
  "timestamp": "2024-03-25T10:30:00Z"
}
```

### Clear All Cache

**Scenario**: Admin clears entire authentication cache.

```bash
curl -X POST "http://localhost:8000/system/cache/clear" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Entire authentication cache has been cleared",
  "cleared_by": "usr-adm***...",
  "timestamp": "2024-03-25T10:30:00Z",
  "warning": "All users will need to re-authenticate or may experience slower response times"
}
```

### Invalidate User Cache

**Scenario**: Clear cache for a specific user.

```bash
curl -X POST "http://localhost:8000/system/cache/invalidate/user/usr-target123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Cache invalidated for user: usr-tar***...",
  "invalidated_by": "usr-adm***...",
  "timestamp": "2024-03-25T10:30:00Z"
}
```

### Invalidate Project Cache

**Scenario**: Clear cache for a specific project.

> The `{project_id}` path parameter is an **integer** project ID (e.g. `456`), **not** a project hash. The user-cache endpoint above, by contrast, takes a `{user_hash}` and returns `404` if the user is not found.

```bash
curl -X POST "http://localhost:8000/system/cache/invalidate/project/456" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Cache invalidated for project: 456",
  "invalidated_by": "usr-adm***...",
  "timestamp": "2024-03-25T10:30:00Z"
}
```

---

## User Type Management

User-type lifecycle is now documented in the dedicated users suite.

Use it for:

- root/admin user creation
- type inspection and type changes
- list-by-type and stats
- caveats about overlapping `/users/{hash}/type` vs `/user-types/{hash}/type`

Start here:

- **[Users - User Types](users/user-types.md)**

---

## Admin Project Management

Admin-project assignment is now documented as part of the users suite because it is a user-type lifecycle concern, not a generic dashboard concern.

Use it for:

- listing assigned projects for an admin user
- replacing the full assignment set
- adding/removing one project at a time
- understanding that assignments are implemented through admin-group membership

Start here:

- **[Users - User Types](users/user-types.md#admin-project-assignment-lifecycle)**

---

## Bulk Operations

User bulk update/delete is now documented in the users suite.

Use it for:

- route limits (`100` update / `50` delete)
- confirmation requirements for delete
- partial-failure handling
- current implementation caveats on bulk update

Start here:

- **[Users - Bulk Operations](users/bulk-operations.md)**

### Bulk Assign Roles in Project

> **WARNING**: This endpoint is **currently broken** and returns `500 INTERNAL_ERROR`. Do not use it in production. The route (`src/routes/bulk_operations.py`) builds assignments keyed by `role_name`, but the utility (`src/Util/bulk_operations.py`) reads `role_id`; the utility then returns result keys `successful`/`failed`, while the route reads `result['success_count']`/`result['error_count']`. The missing keys raise a `KeyError`, which surfaces as a `500` rather than a clean per-assignment error list.
>
> **Workaround**: Assign roles individually via `PUT /roles/users/{user_hash}/role`.
> See [Roles Troubleshooting → Bulk role assignment](roles/troubleshooting.md#bulk-role-assignment-always-fails) for details.

---

## Common Scenarios

### Scenario 1: Daily System Health Check

**Goal**: Morning routine check of system health and overnight activity.

```bash
# Step 1: Check overall system health
curl -X GET "http://localhost:8000/system/health" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: Get dashboard stats
curl -X GET "http://localhost:8000/admin/dashboard/stats" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 3: Check overnight activity (last 12 hours)
curl -X GET "http://localhost:8000/admin/activity?days=1&limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 4: Check for failed logins
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=user_login&days=1" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Scenario 2: Troubleshooting Slow Performance

**Goal**: Investigate and resolve performance issues.

```bash
# Step 1: Check system health for degraded components
curl -X GET "http://localhost:8000/admin/health" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: Check cache statistics
curl -X GET "http://localhost:8000/system/cache/stats" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 3: If cache hit rate is low, consider clearing stale data
curl -X POST "http://localhost:8000/system/cache/clear" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Scenario 3: Bulk Onboarding New Team

**Goal**: Add multiple new employees to appropriate groups.

```bash
# Step 1: Create users (or have them self-register)
# ... user registration ...

# Step 2: Bulk assign all new users to required groups
curl -X POST "http://localhost:8000/admin/user-groups/bulk-assign" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-new1...&user_hashes=usr-new2...&user_hashes=usr-new3...&group_names=developers&group_names=mobile_team"

# Step 3: Verify assignments
curl -X GET "http://localhost:8000/users/list?group_filter=mobile_team" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Scenario 4: Emergency Account Lockout

**Goal**: Quickly disable multiple compromised accounts.

```bash
# Step 1: Bulk deactivate suspected accounts
curl -X POST "http://localhost:8000/admin/users/bulk-update" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-compromised1...&user_hashes=usr-compromised2...&is_active=false"

# Step 2: Invalidate their caches (ends active sessions)
for hash in usr-compromised1 usr-compromised2; do
  curl -X POST "http://localhost:8000/system/cache/invalidate/user/$hash..." \
    -H "Authorization: Bearer $ADMIN_TOKEN"
done

# Step 3: Check activity for these users
curl -X GET "http://localhost:8000/admin/activity?user_id=<compromised_user_id>&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Scenario 5: Monthly Access Review

**Goal**: Review user access patterns and clean up inactive accounts.

```bash
# Step 1: Get user statistics
curl -X GET "http://localhost:8000/admin/users/statistics?days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: List inactive users
curl -X GET "http://localhost:8000/users/list?include_inactive=true" \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.users | map(select(.last_login == null or .last_login < "2024-01-01"))'

# Step 3: Review and optionally deactivate long-inactive users
# (Manual review recommended before bulk operations)
```

---

## Best Practices

### Monitoring

1. **Regular health checks** - Automate daily health checks
2. **Monitor cache hit rates** - Low hit rates indicate potential issues
3. **Track activity spikes** - Unusual activity may indicate problems
4. **Set up alerts** - Configure alerts for degraded health status

### Bulk Operations

1. **Start small** - Test with few users before large bulk operations
2. **Confirm critical operations** - Always use confirm_deletion=true
3. **Document changes** - Keep records of bulk operations
4. **Schedule wisely** - Run bulk operations during low-usage periods

### Cache Management

1. **Avoid frequent clears** - Only clear cache when necessary
2. **Prefer targeted invalidation** - Invalidate specific users/projects
3. **Monitor after clearing** - Watch for performance impact
4. **Understand TTLs** - Know when cached data expires naturally

### Security

1. **Audit admin actions** - Review admin activity regularly
2. **Limit admin access** - Minimize number of admin users
3. **Rotate credentials** - Change admin passwords periodically
4. **Use principle of least privilege** - Grant minimal necessary access

---

## Troubleshooting

### Degraded System Status

**Error**: System health shows "degraded"

**Solutions**:
1. Check individual component status in health response
2. Verify database connectivity
3. Check Redis is running and accessible
4. Review recent system changes

### Cache Clear Had No Effect

**Issue**: Performance still slow after clearing cache

**Solutions**:
1. Check database performance separately
2. Verify Redis is properly configured
3. Check for network latency issues
4. Review application logs for errors

### Bulk Operation Partial Failure

**Issue**: Some operations in bulk request failed

**Solutions**:
1. Check the errors array in response
2. Verify all user hashes are valid
3. Check permissions for each target user
4. Retry failed operations individually

---

## Quick Reference

### Admin Dashboard Endpoints

| Operation | Endpoint | Method | Permission |
|-----------|----------|--------|------------|
| Dashboard stats | `/admin/dashboard/stats` | GET | Admin/Root |
| User statistics | `/admin/users/statistics` | GET | Admin/Root |
| Project statistics | `/admin/projects/statistics` | GET | Admin/Root |
| System overview | `/admin/system/overview` | GET | Admin/Root |
| Activity feed | `/admin/activity` | GET | Admin/Root |
| Activity detail | `/admin/activity/{activity_id}` | GET | Admin/Root |
| Activity types | `/admin/activity/types` | GET | Admin/Root |
| Admin health | `/admin/health` | GET | Admin/Root |

### System Endpoints

| Operation | Endpoint | Method | Auth Required |
|-----------|----------|--------|---------------|
| System info | `/system/info` | GET | Valid session |
| Health check | `/system/health` | GET | Valid session |
| Ping | `/system/ping` | GET | No |
| Cache stats | `/system/cache/stats` | GET | Yes |
| Clear cache | `/system/cache/clear` | POST | Admin/Root |
| Invalidate user cache | `/system/cache/invalidate/user/{hash}` | POST | Admin/Root |
| Invalidate project cache | `/system/cache/invalidate/project/{id}` | POST | Admin/Root |

### Bulk Operation Endpoints

| Operation | Endpoint | Method | Permission |
|-----------|----------|--------|------------|
| Bulk update users | `/admin/users/bulk-update` | POST | Admin / `manage_users` |
| Bulk delete users | `/admin/users/bulk-delete` | POST | Admin / `manage_users` |
| Bulk assign roles | `/admin/projects/{hash}/bulk-assign-roles` | POST | Admin |
| Bulk assign groups | `/admin/user-groups/bulk-assign` | POST | Admin |

See detailed behavior in **[Users - Bulk Operations](users/bulk-operations.md)**.

### Bulk Operation Limits

| Operation | Max Items | Confirmation Required |
|-----------|-----------|----------------------|
| Bulk update | 100 users | No |
| Bulk delete | 50 users | Yes |
| Bulk role assign | 100 users | No |
| Bulk group assign | 100 users | No |

### Cross-Reference Links

| Topic | Canonical Doc |
|-------|--------------|
| User type lifecycle | [Users - User Types](users/user-types.md) |
| Admin project assignment | [Users - User Types](users/user-types.md#admin-project-assignment-lifecycle) |
| Activity feed & API audit logs | [Audit Logs Suite](audit_logs/README.md) |
| Role catalog (metadata only) | [Roles - Usage](roles/usage.md) |

---

## Related Documentation

- **[Audit Logs Documentation Suite](audit_logs/README.md)** — Activity feed, API audit logs, security events, export, and audit statistics
- **[Error Reference](errors.md)** — Error codes and troubleshooting
- **[Getting Started](getting-started.md)** — Platform setup and first steps
- **[Authentication Usage Cases](authentication-usage-cases.md)** - Login, sessions
- **[Users Documentation Suite](users/README.md)** - User management, user types, bulk user operations
- **[Groups Documentation Suite](groups/README.md)** - Group management, flow, and troubleshooting
- **[Projects Documentation Suite](projects/README.md)** - Project management and access control
- **[Permissions Documentation Suite](permissions/README.md)** - Permission management

---

**API Version**: 2.2.0
