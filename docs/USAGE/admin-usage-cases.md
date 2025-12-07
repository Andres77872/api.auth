# Admin & System Management Usage Guide

Complete practical guide for admin dashboard operations, system monitoring, bulk operations, and cache management.

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

### Get Activity Feed

**Scenario**: View recent system activities with filtering.

```bash
# Basic activity feed
curl -X GET "http://localhost:8000/admin/activity" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# With pagination
curl -X GET "http://localhost:8000/admin/activity?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Filter by activity type
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=user_login" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Filter by user
curl -X GET "http://localhost:8000/admin/activity?user_id=123" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Filter by project
curl -X GET "http://localhost:8000/admin/activity?project_id=456" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Custom time range
curl -X GET "http://localhost:8000/admin/activity?days=7" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "activities": [
    {
      "id": 12345,
      "activity_type": "user_login",
      "details": {"message": "User logged in successfully"},
      "created_at": "2024-03-25T10:25:00Z",
      "user": {
        "id": 123,
        "username": "john_doe",
        "user_hash": "usr-abc123..."
      },
      "project": {
        "id": 456,
        "name": "API v2",
        "hash": "proj-xyz789..."
      },
      "target_user": null,
      "ip_address": "192.168.1.100"
    }
  ],
  "pagination": {
    "total": 1580,
    "limit": 50,
    "offset": 0,
    "has_more": true,
    "next_offset": 50
  },
  "filters": {
    "activity_type": null,
    "user_id": null,
    "project_id": null,
    "days": 30
  },
  "generated_at": "2024-03-25T10:30:00Z"
}
```

### Get Activity Types

**Scenario**: Get list of available activity types for filtering.

```bash
curl -X GET "http://localhost:8000/admin/activity/types" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "activity_types": [
    "user_login",
    "user_logout",
    "user_registration",
    "user_update",
    "admin_action",
    "permission_change",
    "group_membership_change",
    "project_access_change"
  ],
  "generated_at": "2024-03-25T10:30:00Z"
}
```

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

### Create ROOT User

**Scenario**: Create a new root (super admin) user.

```bash
curl -X POST "http://localhost:8000/user-types/root" \
  -H "Authorization: Bearer YOUR_ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_root&password=SecurePassword123!&email=root@example.com"
```

**Response:**
```json
{
  "success": true,
  "message": "Root user 'new_root' created successfully",
  "user": {
    "user_hash": "usr-xxx...",
    "username": "new_root",
    "email": "root@example.com",
    "user_type": "root",
    "created_at": "2024-03-25T10:30:00Z"
  }
}
```

### Create ADMIN User

**Scenario**: Create a new admin user with project assignment.

```bash
# Assign to single project
curl -X POST "http://localhost:8000/user-types/admin" \
  -H "Authorization: Bearer YOUR_ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_admin&password=SecurePassword123!&email=admin@example.com&assigned_project_id=1"

# Assign to multiple projects
curl -X POST "http://localhost:8000/user-types/admin" \
  -H "Authorization: Bearer YOUR_ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_admin&password=SecurePassword123!&email=admin@example.com&assigned_project_ids=1&assigned_project_ids=2&assigned_project_ids=3"
```

**Response:**
```json
{
  "success": true,
  "message": "Admin user 'new_admin' created and assigned to 3 project(s)",
  "user": {
    "user_hash": "usr-xxx...",
    "username": "new_admin",
    "email": "admin@example.com",
    "user_type": "admin",
    "assigned_project_ids": ["1", "2", "3"],
    "assigned_projects": [
      {"project_id": 1, "project_hash": "proj-xxx...", "project_name": "Project A"},
      {"project_id": 2, "project_hash": "proj-yyy...", "project_name": "Project B"},
      {"project_id": 3, "project_hash": "proj-zzz...", "project_name": "Project C"}
    ],
    "primary_project_id": "1",
    "created_at": "2024-03-25T10:30:00Z",
    "created_by": "root_admin"
  }
}
```

### Get Users by Type

**Scenario**: List all users of a specific type.

```bash
# List all admin users
curl -X GET "http://localhost:8000/user-types/users/admin?limit=100&offset=0" \
  -H "Authorization: Bearer YOUR_ROOT_TOKEN"

# List all root users
curl -X GET "http://localhost:8000/user-types/users/root?limit=100&offset=0" \
  -H "Authorization: Bearer YOUR_ROOT_TOKEN"

# List all consumer users
curl -X GET "http://localhost:8000/user-types/users/consumer?limit=100&offset=0" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "users": [
    {
      "user_hash": "usr-xxx...",
      "username": "admin_user",
      "email": "admin@example.com",
      "user_type": "admin",
      "created_at": "2024-01-15T10:30:00Z",
      "is_active": true,
      "assigned_project": {
        "project_id": 1,
        "project_hash": "proj-xxx...",
        "project_name": "Project A"
      }
    }
  ],
  "pagination": {
    "limit": 100,
    "offset": 0,
    "total": 15,
    "has_more": false
  },
  "filter": {
    "user_type": "admin",
    "project_filter": null
  }
}
```

### Get User Type Statistics

**Scenario**: View breakdown of users by type.

```bash
curl -X GET "http://localhost:8000/user-types/stats" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "statistics": {
    "total_users": 1250,
    "user_types": {
      "root": {"count": 2, "percentage": 0.16},
      "admin": {"count": 15, "percentage": 1.2},
      "consumer": {"count": 1233, "percentage": 98.64}
    },
    "system_info": {
      "user_type_system": "3-tier (root, admin, consumer)",
      "access_model": "hierarchical",
      "features": ["global-root-access", "project-scoped-admin", "rbac-consumer-users"]
    },
    "scope": {
      "type": "global_root",
      "access": "unrestricted"
    }
  }
}
```

---

## Admin Project Management

### Get Admin User's Projects

**Scenario**: View all projects assigned to an admin user.

```bash
curl -X GET "http://localhost:8000/user-types/admin/usr-admin123.../projects" \
  -H "Authorization: Bearer YOUR_ROOT_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "user_hash": "usr-admin123...",
  "assigned_projects": [
    {
      "project_id": "1",
      "project_hash": "proj-xxx...",
      "project_name": "Project A",
      "project_description": "Main project",
      "assigned_at": "2024-01-15T10:30:00Z",
      "assigned_by": "root_admin"
    },
    {
      "project_id": "2",
      "project_hash": "proj-yyy...",
      "project_name": "Project B",
      "project_description": "Secondary project",
      "assigned_at": "2024-02-01T14:00:00Z",
      "assigned_by": "root_admin"
    }
  ]
}
```

### Update Admin User's Projects (Replace All)

**Scenario**: Replace all project assignments for an admin user.

```bash
curl -X PUT "http://localhost:8000/user-types/admin/usr-admin123.../projects" \
  -H "Authorization: Bearer YOUR_ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "assigned_project_ids=1&assigned_project_ids=3&assigned_project_ids=5"
```

**Response:**
```json
{
  "success": true,
  "message": "Admin projects updated",
  "user_hash": "usr-admin123...",
  "assigned_projects": [
    {"project_id": "1", "project_hash": "proj-xxx...", "project_name": "Project A", ...},
    {"project_id": "3", "project_hash": "proj-zzz...", "project_name": "Project C", ...},
    {"project_id": "5", "project_hash": "proj-vvv...", "project_name": "Project E", ...}
  ],
  "total_projects": 3
}
```

### Add Admin to Project

**Scenario**: Add an admin user to an additional project.

```bash
curl -X POST "http://localhost:8000/user-types/admin/usr-admin123.../projects/add" \
  -H "Authorization: Bearer YOUR_ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_id=4"
```

**Response:**
```json
{
  "success": true,
  "message": "Admin added to project",
  "user_hash": "usr-admin123...",
  "project_id": "4",
  "project_hash": "proj-www...",
  "project_name": "Project D"
}
```

### Remove Admin from Project

**Scenario**: Remove an admin user from a specific project.

```bash
curl -X DELETE "http://localhost:8000/user-types/admin/usr-admin123.../projects/4" \
  -H "Authorization: Bearer YOUR_ROOT_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Admin removed from project",
  "user_hash": "usr-admin123...",
  "project_id": "4"
}
```

---

## Bulk Operations

### Bulk Update Users

**Scenario**: Update multiple users at once.

```bash
curl -X POST "http://localhost:8000/admin/users/bulk-update" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-abc123...&user_hashes=usr-def456...&user_hashes=usr-ghi789...&is_active=true&user_type=consumer"
```

**Response:**
```json
{
  "success": true,
  "message": "Bulk update completed: 3 succeeded, 0 failed",
  "summary": {
    "total_requested": 3,
    "success_count": 3,
    "error_count": 0,
    "skipped_count": 0
  },
  "updates_applied": {
    "is_active": true,
    "user_type": "consumer"
  },
  "results": [
    {"user_hash": "usr-abc123...", "status": "updated"},
    {"user_hash": "usr-def456...", "status": "updated"},
    {"user_hash": "usr-ghi789...", "status": "updated"}
  ],
  "errors": [],
  "performed_by": "admin_user",
  "performed_at": "2024-03-25T10:30:00Z"
}
```

### Bulk Delete Users

**Scenario**: Delete multiple users at once.

```bash
curl -X POST "http://localhost:8000/admin/users/bulk-delete" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-abc123...&user_hashes=usr-def456...&confirm_deletion=true"
```

**Response:**
```json
{
  "success": true,
  "message": "Bulk deletion completed: 2 deleted, 0 failed",
  "summary": {
    "total_requested": 2,
    "success_count": 2,
    "error_count": 0,
    "protected_count": 0
  },
  "results": [
    {"user_hash": "usr-abc123...", "status": "deleted"},
    {"user_hash": "usr-def456...", "status": "deleted"}
  ],
  "errors": [],
  "warnings": [],
  "performed_by": "admin_user",
  "performed_at": "2024-03-25T10:30:00Z"
}
```

### Bulk Assign Roles in Project

**Scenario**: Assign roles to multiple users in a project.

```bash
curl -X POST "http://localhost:8000/admin/projects/proj-xyz789.../bulk-assign-roles" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-abc123...&user_hashes=usr-def456...&role_names=developer&role_names=reviewer"
```

**Response:**
```json
{
  "success": true,
  "message": "Bulk role assignment completed: 4 succeeded, 0 failed",
  "project": {
    "project_hash": "proj-xyz789...",
    "project_name": "API v2"
  },
  "roles_assigned": ["developer", "reviewer"],
  "summary": {
    "total_requested": 2,
    "success_count": 4,
    "error_count": 0
  },
  "results": [...],
  "errors": [],
  "performed_by": "admin_user",
  "performed_at": "2024-03-25T10:30:00Z"
}
```

### Bulk Assign Users to Groups

**Scenario**: Assign multiple users to multiple groups.

```bash
curl -X POST "http://localhost:8000/admin/user-groups/bulk-assign" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-abc123...&user_hashes=usr-def456...&group_names=developers&group_names=qa_team"
```

**Response:**
```json
{
  "success": true,
  "message": "Bulk group assignment completed: 4 succeeded, 0 failed",
  "groups_assigned": ["developers", "qa_team"],
  "summary": {
    "total_requested": 2,
    "success_count": 4,
    "error_count": 0
  },
  "results": [...],
  "errors": [],
  "performed_by": "admin_user",
  "performed_at": "2024-03-25T10:30:00Z"
}
```

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

### User Type Management Endpoints

| Operation | Endpoint | Method | Permission |
|-----------|----------|--------|------------|
| Create ROOT user | `/user-types/root` | POST | Root only |
| Create ADMIN user | `/user-types/admin` | POST | Root only |
| Get user type info | `/user-types/{user_hash}/info` | GET | Admin/Root |
| Update user type | `/user-types/{user_hash}/type` | PUT | Root only |
| List users by type | `/user-types/users/{type}` | GET | Admin/Root |
| User type stats | `/user-types/stats` | GET | Admin/Root |

### Admin Project Management Endpoints

| Operation | Endpoint | Method | Permission |
|-----------|----------|--------|------------|
| Get admin projects | `/user-types/admin/{user_hash}/projects` | GET | Root only |
| Update admin projects | `/user-types/admin/{user_hash}/projects` | PUT | Root only |
| Add admin to project | `/user-types/admin/{user_hash}/projects/add` | POST | Root only |
| Remove from project | `/user-types/admin/{user_hash}/projects/{project_id}` | DELETE | Root only |

### Admin Dashboard Endpoints

| Operation | Endpoint | Method | Permission |
|-----------|----------|--------|------------|
| Dashboard stats | `/admin/dashboard/stats` | GET | Admin/Root |
| User statistics | `/admin/users/statistics` | GET | Admin/Root |
| Project statistics | `/admin/projects/statistics` | GET | Admin/Root |
| System overview | `/admin/system/overview` | GET | Admin/Root |
| Activity feed | `/admin/activity` | GET | Admin/Root |
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
| Bulk update users | `/admin/users/bulk-update` | POST | Admin |
| Bulk delete users | `/admin/users/bulk-delete` | POST | Admin |
| Bulk assign roles | `/admin/projects/{hash}/bulk-assign-roles` | POST | Admin |
| Bulk assign groups | `/admin/user-groups/bulk-assign` | POST | Admin |

### Bulk Operation Limits

| Operation | Max Items | Confirmation Required |
|-----------|-----------|----------------------|
| Bulk update | 100 users | No |
| Bulk delete | 50 users | Yes |
| Bulk role assign | 100 users | No |
| Bulk group assign | 100 users | No |

### Role Catalog Endpoints (Metadata Only)

| Operation | Endpoint | Method | Permission |
|-----------|----------|--------|------------|
| Add role to project catalog | `/roles/projects/{hash}/catalog/roles/{role_hash}` | POST | Admin/Root |
| Get project cataloged roles | `/roles/projects/{hash}/catalog/roles` | GET | Authenticated |
| Remove role from catalog | `/roles/projects/{hash}/catalog/roles/{role_hash}` | DELETE | Admin/Root |

---

## Related Documentation

- **[Authentication Usage Cases](authentication-usage-cases.md)** - Login, sessions
- **[Users Usage Cases](users-usage-cases.md)** - User management
- **[Groups Usage Cases](groups-usage-cases.md)** - Group management
- **[Permissions Usage Cases](permissions-usage-cases.md)** - Permission management
- **[Audit Log Usage Cases](audit-log-usage-cases.md)** - Event logs, security events

---

**Last Updated**: December 2024
**Document Version**: 1.0
