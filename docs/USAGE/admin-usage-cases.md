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

> **Note**: The activity feed (`/admin/activity`) and activity types (`/admin/activity/types`) are documented here for quick reference. For comprehensive audit log coverage including API audit logs, security events, export functionality, audit statistics, and detailed filtering, see [Audit Logs Usage Guide](audit_logs/usage.md).

For full endpoint documentation, query parameters, response shapes, and examples, see the canonical source: **[Audit Logs Usage → Activity Feed](audit_logs/usage.md#activity-feed-dashboard)**.

---

## System Health & Metrics

### Public System Info

**Scenario**: Check basic system information (no auth required).

```bash
curl -X GET "http://localhost:8000/system/info"
```

**Response:**
```json
{
  "success": true,
  "system": {
    "name": "Group-Based Multi-Project Authentication API",
    "version": "2.2.0",
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

### System Health Check

**Scenario**: Check detailed system health status (no auth required).

```bash
curl -X GET "http://localhost:8000/system/health"
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
    }
  }
}
```

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

---

## Cache Management

### Get Cache Statistics

**Scenario**: View cache performance metrics.

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

> **WARNING**: This endpoint is **currently broken** due to a parameter mismatch between the route and the utility function. It returns errors for every assignment. Do not use it in production.
>
> **Workaround**: Assign roles individually via `PUT /roles/users/{user_hash}/role`.
> See [Roles Troubleshooting → Bulk role assignment](roles/troubleshooting.md#bulk-role-assignment-always-fails) for details.

---

## Common Scenarios

### Scenario 1: Daily System Health Check

**Goal**: Morning routine check of system health and overnight activity.

```bash
# Step 1: Check overall system health
curl -X GET "http://localhost:8000/system/health"

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
| System info | `/system/info` | GET | No |
| Health check | `/system/health` | GET | No |
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

**Last Updated**: April 2026
**API Version**: 2.2.0
