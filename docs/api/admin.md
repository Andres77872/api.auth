 # Admin API

Complete admin endpoint documentation for dashboard statistics, user group management, and project group management. Requires administrator privileges.

## 🔐 Admin Authentication Required

All admin endpoints require authentication with admin privileges:

```
Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN
```

---

## 📊 Admin Dashboard Endpoints

### GET `/admin/dashboard/stats`

Get comprehensive dashboard statistics including user counts, project metrics, and system health.

**Authentication:** Required (admin permission)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/dashboard/stats" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Success Response (200):**
```json
{
  "totals": {
    "users": 150,
    "projects": 25,
    "active_sessions": 42,
    "recent_activities": 327
  },
  "recent_activity": {
    "new_users_7d": 12,
    "new_projects_7d": 3,
    "total_activities_7d": 327
  },
  "user_breakdown": {
    "root_users": 2,
    "admin_users": 8,
    "consumer_users": 140
  },
  "growth": {
    "user_growth_7d": 12,
    "project_growth_7d": 3
  },
  "system_health": {
    "database": {
      "status": "healthy",
      "response_time_ms": 15
    },
    "redis": {
      "status": "healthy",
      "response_time_ms": 3
    },
    "overall_status": "healthy"
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

### GET `/admin/activity`

Get paginated activity feed with filtering options for the admin dashboard.

**Authentication:** Required (admin permission)

**Query Parameters:**
- `limit` (optional, default: 50, max: 100): Number of activities to return
- `offset` (optional, default: 0): Number of activities to skip
- `activity_type_filter` (optional): Filter by activity type
- `user_id` (optional): Filter by user ID
- `project_id` (optional): Filter by project ID
- `days` (optional, default: 30, max: 365): Days to look back

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/activity?limit=20&days=7&activity_type_filter=user_login" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Success Response (200):**
```json
{
  "activities": [
    {
      "id": 1523,
      "activity_type": "user_login",
      "details": "User logged in successfully",
      "created_at": "2024-01-15T10:25:00Z",
      "user": {
        "id": 42,
        "username": "john_doe",
        "user_hash": "user_abc123"
      },
      "project": {
        "id": 5,
        "name": "Main Project",
        "hash": "proj_xyz789"
      },
      "target_user": null,
      "ip_address": "192.168.1.100"
    },
    {
      "id": 1522,
      "activity_type": "user_created",
      "details": "New user registered",
      "created_at": "2024-01-15T09:15:00Z",
      "user": null,
      "project": {
        "id": 5,
        "name": "Main Project",
        "hash": "proj_xyz789"
      },
      "target_user": {
        "id": 150,
        "username": "new_user",
        "user_hash": "user_def456"
      },
      "ip_address": "192.168.1.101"
    }
  ],
  "pagination": {
    "total": 327,
    "limit": 20,
    "offset": 0,
    "has_more": true,
    "next_offset": 20
  },
  "filters": {
    "activity_type": "user_login",
    "user_id": null,
    "project_id": null,
    "days": 7
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

### GET `/admin/health`

Get detailed system health information including database, Redis, and performance metrics.

**Authentication:** Required (admin permission)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/health" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Success Response (200):**
```json
{
  "overall_status": "healthy",
  "health_score": 100,
  "components": {
    "database": {
      "status": "healthy",
      "response_time_ms": 15,
      "connections": {
        "active": 5,
        "idle": 10
      }
    },
    "redis": {
      "status": "healthy",
      "response_time_ms": 3,
      "memory_usage_mb": 45.2,
      "connected_clients": 8
    }
  },
  "metrics": {
    "total_users": 150,
    "total_projects": 25,
    "active_sessions": 42
  },
  "checked_at": "2024-01-15T10:30:00Z"
}
```

**Health Scores:**
- **100**: All systems healthy
- **70-99**: Degraded (some components have issues)
- **<70**: Unhealthy (critical issues detected)

---

### GET `/admin/activity/types`

Get list of available activity types for filtering.

**Authentication:** Required (admin permission)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/activity/types" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Success Response (200):**
```json
{
  "activity_types": [
    "user_login",
    "user_logout",
    "user_created",
    "user_updated",
    "user_deleted",
    "user_activated",
    "user_deactivated",
    "user_password_reset",
    "project_created",
    "project_updated",
    "project_deleted",
    "project_member_added",
    "project_member_removed",
    "group_created",
    "group_updated",
    "group_deleted",
    "user_assigned_to_group",
    "user_removed_from_group",
    "permission_granted",
    "permission_revoked",
    "role_assigned",
    "role_revoked",
    "bulk_user_update",
    "bulk_user_delete",
    "bulk_role_assignment",
    "bulk_group_assignment"
  ],
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

### GET `/admin/users/statistics`

Get detailed user statistics with breakdown and growth rates.

**Authentication:** Required (admin permission)

**Query Parameters:**
- `days` (optional, default: 30, max: 365): Days to look back for statistics

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/users/statistics?days=30" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Success Response (200):**
```json
{
  "success": true,
  "statistics": {
    "total_users": 150,
    "active_users": 142,
    "inactive_users": 8,
    "new_users_period": 12,
    "user_type_breakdown": {
      "root": 2,
      "admin": 8,
      "consumer": 140
    },
    "growth_rate": 8.7,
    "avg_users_per_day": 0.4,
    "most_active_day": "2024-01-10",
    "registration_trend": [
      {"date": "2024-01-08", "count": 2},
      {"date": "2024-01-09", "count": 1},
      {"date": "2024-01-10", "count": 5},
      {"date": "2024-01-11", "count": 0},
      {"date": "2024-01-12", "count": 3},
      {"date": "2024-01-13", "count": 1},
      {"date": "2024-01-14", "count": 0}
    ]
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

### GET `/admin/projects/statistics`

Get detailed project statistics and health metrics.

**Authentication:** Required (admin permission)

**Query Parameters:**
- `days` (optional, default: 30, max: 365): Days to look back for analytics

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/projects/statistics?days=30" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Success Response (200):**
```json
{
  "success": true,
  "statistics": {
    "total_projects": 25,
    "active_projects": 23,
    "new_projects_period": 3,
    "avg_members_per_project": 6.2,
    "total_project_members": 155,
    "project_growth_rate": 13.6,
    "most_active_projects": [
      {
        "project_hash": "proj_xyz789",
        "project_name": "Main Project",
        "member_count": 45,
        "activity_count": 523
      },
      {
        "project_hash": "proj_abc123",
        "project_name": "Mobile App",
        "member_count": 28,
        "activity_count": 412
      },
      {
        "project_hash": "proj_def456",
        "project_name": "Analytics Dashboard",
        "member_count": 15,
        "activity_count": 287
      }
    ],
    "creation_trend": [
      {"date": "2024-01-05", "count": 1},
      {"date": "2024-01-12", "count": 2}
    ]
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

### GET `/admin/system/overview`

Get comprehensive system health and performance overview.

**Authentication:** Required (admin permission)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/system/overview" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Success Response (200):**
```json
{
  "success": true,
  "system_overview": {
    "uptime": "15 days, 3 hours, 42 minutes",
    "version": "1.0.0",
    "environment": "production",
    "health_status": "healthy",
    "performance": {
      "avg_response_time_ms": 125,
      "requests_per_minute": 450,
      "error_rate": 0.02
    },
    "database": {
      "status": "healthy",
      "total_connections": 15,
      "slow_queries": 0,
      "database_size_mb": 2048
    },
    "cache": {
      "status": "healthy",
      "hit_rate": 94.5,
      "memory_usage_mb": 256,
      "keys_count": 15420
    },
    "resources": {
      "cpu_usage_percent": 35,
      "memory_usage_percent": 62,
      "disk_usage_percent": 45
    }
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

## 👥 User Group Management

User groups define which projects users can access globally.

### GET `/admin/user-groups`

List all global user groups with member counts and statistics.

**Authentication:** Required (admin permission)

**Query Parameters:**
- `limit` (optional, default: 50, max: 100): Number of groups to return
- `offset` (optional, default: 0): Number of groups to skip
- `sort_by` (optional, default: 'group_name'): Field to sort by (group_name, created_at, updated_at, id)
- `sort_order` (optional, default: 'asc'): Sort direction (asc or desc)
- `search` (optional): Search term to filter group names

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/user-groups?limit=50&offset=0&sort_by=group_name&sort_order=asc&search=dev" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user_groups": [
    {
      "group_hash": "group123...",
      "group_name": "administrators",
      "description": "System administrators with full access",
      "member_count": 2,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 3
  }
}
```

---

### POST `/admin/user-groups`

Create a new global user group.

**Authentication:** Required (admin permission)

**Request Body** (Form):
- `group_name` (required): Name of the user group
- `description` (optional): Description of the user group

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=developers&description=Software development team"
```

**Response (200):**
```json
{
  "success": true,
  "message": "User group \"developers\" created successfully",
  "user_group": {
    "group_hash": "newgroup123...",
    "group_name": "developers",
    "description": "Software development team",
    "created_at": "2024-01-01T12:00:00Z"
  }
}
```

---

### GET `/admin/user-groups/{group_hash}`

Get detailed user group information including members and accessible projects.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/user-groups/group123..." \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user_group": {
    "group_hash": "group123...",
    "group_name": "administrators",
    "description": "System administrators with full access",
    "created_at": "2024-01-01T00:00:00Z"
  },
  "members": [
    {
      "user_hash": "user123...",
      "username": "admin",
      "email": "admin@example.com"
    }
  ],
  "accessible_projects": [
    {
      "project_hash": "proj123...",
      "project_name": "Main Project"
    }
  ],
  "statistics": {
    "total_members": 2,
    "total_projects": 5
  }
}
```

---

### PUT `/admin/user-groups/{group_hash}`

Update a user group's name or description.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Request Body** (Form):
- `group_name` (optional): Updated name of the user group
- `description` (optional): Updated description of the user group

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/admin/user-groups/group123..." \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=updated_developers&description=Updated software development team"
```

**Response (200):**
```json
{
  "success": true,
  "message": "User group updated successfully",
  "user_group": {
    "group_hash": "group123...",
    "group_name": "updated_developers",
    "description": "Updated software development team"
  }
}
```

---

### DELETE `/admin/user-groups/{group_hash}`

Delete a user group. This will also remove all user memberships and project access grants for this group.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Response (200):**
```json
{
  "success": true,
  "message": "User group \"developers\" deleted successfully",
  "warning": "All user memberships and project access have been revoked"
}
```

---

### POST `/admin/user-groups/{group_hash}/members`

Assign a user to a user group.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Request Body** (form-data or JSON):
- `user_hash` (required): User hash to assign

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/group123.../members" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hash=user456..."
```

**Response (200):**
```json
{
  "success": true,
  "message": "User \"john_doe\" assigned to group \"developers\"",
  "assignment": {
    "user": {
      "user_hash": "user456...",
      "username": "john_doe"
    },
    "group": {
      "group_hash": "group123...",
      "group_name": "developers"
    },
    "assigned_by": "admin"
  }
}
```

---

### DELETE `/admin/user-groups/{group_hash}/members/{user_hash}`

Remove a user from a user group.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier
- `user_hash`: User hash to remove

**Response (200):**
```json
{
  "success": true,
  "message": "User \"john_doe\" removed from group \"developers\""
}
```

---

### GET `/admin/user-groups/{group_hash}/members`

Get paginated list of members in a user group.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Query Parameters:**
- `limit` (optional, default: 50, max: 100): Number of members to return
- `offset` (optional, default: 0): Number of members to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/user-groups/group123.../members?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user_group": {
    "group_hash": "group123...",
    "group_name": "developers",
    "description": "Software development team"
  },
  "members": [
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "email": "john@example.com",
      "user_type": "consumer",
      "joined_group_at": "2024-01-10T12:00:00Z",
      "is_active": true
    },
    {
      "user_hash": "usr-def456",
      "username": "jane_smith",
      "email": "jane@example.com",
      "user_type": "consumer",
      "joined_group_at": "2024-01-11T14:30:00Z",
      "is_active": true
    }
  ],
  "pagination": {
    "total": 15,
    "limit": 50,
    "offset": 0,
    "has_more": false
  },
  "statistics": {
    "total_members": 15,
    "members_shown": 2
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

### POST `/admin/user-groups/{group_hash}/members/bulk`

Bulk add multiple users to a user group.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Request Body** (Form):
- `user_hashes` (required): List of user hashes to add

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/group123.../members/bulk" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-abc123&user_hashes=usr-def456&user_hashes=usr-ghi789"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Bulk assignment completed: 3 succeeded, 0 failed",
  "user_group": {
    "group_hash": "group123...",
    "group_name": "developers"
  },
  "summary": {
    "total_requested": 3,
    "success_count": 3,
    "error_count": 0
  },
  "results": [
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "status": "success",
      "message": "Added to group successfully"
    },
    {
      "user_hash": "usr-def456",
      "username": "jane_smith",
      "status": "success",
      "message": "Added to group successfully"
    },
    {
      "user_hash": "usr-ghi789",
      "username": "bob_johnson",
      "status": "success",
      "message": "Added to group successfully"
    }
  ],
  "errors": [],
  "performed_by": "admin",
  "performed_at": "2024-01-15T10:30:00Z"
}
```

---

### GET `/admin/user-groups/users/{user_hash}/groups`

Get all user groups that a specific user belongs to.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `user_hash`: User identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/user-groups/users/usr-abc123/groups" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user": {
    "user_hash": "usr-abc123",
    "username": "john_doe",
    "email": "john@example.com",
    "user_type": "consumer"
  },
  "groups": [
    {
      "group_hash": "group123...",
      "group_name": "developers",
      "description": "Software development team",
      "joined_at": "2024-01-10T12:00:00Z"
    },
    {
      "group_hash": "group456...",
      "group_name": "api_users",
      "description": "API access users",
      "joined_at": "2024-01-12T09:00:00Z"
    }
  ],
  "statistics": {
    "total_groups": 2
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

### POST `/admin/user-groups/{group_hash}/projects`

Grant a user group access to a project.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Request Body** (form-data or JSON):
- `project_hash` (required): Project hash to grant access to

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/group123.../projects" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj456..."
```

**Response (200):**
```json
{
  "success": true,
  "message": "User group \"developers\" granted access to project \"API Project\"",
  "access_details": {
    "user_group": {
      "group_hash": "group123...",
      "group_name": "developers"
    },
    "project": {
      "project_hash": "proj456...",
      "project_name": "API Project"
    },
    "granted_by": "admin"
  }
}
```

---

### DELETE `/admin/user-groups/{group_hash}/projects/{project_hash}`

Revoke a user group's access to a project.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier
- `project_hash`: Project hash to revoke access from

**Response (200):**
```json
{
  "success": true,
  "message": "User group \"developers\" access to project \"API Project\" revoked"
}
```

---

## 🎭 Project Group Management

Project groups define permission sets that can be applied to projects.

### GET `/admin/project-groups`

List all project permission groups with their permission sets.

**Authentication:** Required (admin permission)

**Query Parameters:**
- `limit` (optional, default: 50): Number of groups to return
- `offset` (optional, default: 0): Number of groups to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/project-groups?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "project_groups": [
    {
      "group_hash": "projgroup123...",
      "group_name": "full-access",
      "description": "Complete project control",
      "permissions": ["admin", "read", "write", "delete", "manage_users"],
      "project_count": 3,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 3
  }
}
```

---

### GET `/admin/project-groups/{group_hash}`

Get detailed project group information.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: Project group identifier

**Response (200):**
```json
{
  "success": true,
  "project_group": {
    "group_hash": "projgroup123...",
    "group_name": "full-access",
    "description": "Complete project control",
    "permissions": ["admin", "read", "write", "delete", "manage_users"],
    "created_at": "2024-01-01T00:00:00Z"
  },
  "assigned_projects": [
      {
          "project_hash": "proj123...",
          "project_name": "Main Project",
          "project_description": "Main project description"
      }
  ],
  "statistics": {
      "total_projects": 1,
      "total_permissions": 5
  }
}
```

---

### POST `/admin/project-groups`

Create a new project permission group with specific permissions.

**Authentication:** Required (admin permission)

**Request Body** (Form):
- `group_name` (required): Name of the project group
- `permissions` (optional): List of permissions to assign to the group
- `description` (optional): Description of the project group

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=api-access&permissions=read&permissions=write&permissions=api_access&description=API access permissions"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Project group \"api-access\" created successfully",
  "project_group": {
    "group_hash": "newprojgroup123...",
    "group_name": "api-access",
    "description": "API access permissions",
    "permissions": ["read", "write", "api_access"],
    "created_at": "2024-01-01T12:00:00Z"
  }
}
```

---

### PUT `/admin/project-groups/{group_hash}`

Update a project group's information.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: Project group identifier

**Request Body** (Form):
- `group_name` (optional): Updated name of the project group
- `permissions` (optional): Updated list of permissions
- `description` (optional): Updated description

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/admin/project-groups/projgroup123..." \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=api-access-updated&permissions=read&permissions=write&permissions=api_access&permissions=export_data&description=Updated API access permissions"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Project group updated successfully",
  "project_group": {
    "group_hash": "newprojgroup123...",
    "group_name": "api-access-updated",
    "description": "Updated API access permissions",
    "permissions": ["read", "write", "api_access", "export_data"]
  }
}
```

---

### DELETE `/admin/project-groups/{group_hash}`

Delete a project permission group.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: Project group identifier

**Response (200):**
```json
{
    "success": true,
    "message": "Project group \"api-access\" deleted successfully",
    "warning": "All project assignments have been removed"
}
```

---

### POST `/admin/project-groups/{group_hash}/projects`

Assign a project to a project group, giving it the group's permission set.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: Project group identifier

**Request Body** (form-data or JSON):
- `project_hash` (required): Project hash to assign

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/project-groups/projgroup123.../projects" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj789..."
```

**Response (200):**
```json
{
  "success": true,
  "message": "Project \"New API\" assigned to group \"api-access\"",
  "assignment": {
    "project": {
      "project_hash": "proj789...",
      "project_name": "New API"
    },
    "group": {
      "group_hash": "projgroup123...",
      "group_name": "api-access",
      "permissions": ["read", "write", "api_access"]
    },
    "assigned_by": "admin"
  }
}
```

---

### DELETE `/admin/project-groups/{group_hash}/projects/{project_hash}`

Remove a project from a project group.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: Project group identifier
- `project_hash`: Project hash to remove assignment from

**Response (200):**
```json
{
    "success": true,
    "message": "Project \"New API\" removed from group \"api-access\""
}
```

---

## 🏗️ Group Management Workflow

### Complete Group Setup Process

```mermaid
graph TD
    A[Create User Group] --> B[Create Project Group]
    B --> C[Create Project]
    C --> D[Assign Project to Project Group]
    D --> E[Grant User Group Access to Project]
    E --> F[Add Users to User Group]
    F --> G[Users Can Access Project with Permissions]
```

### Permission Resolution Flow

```mermaid
graph TD
    A[User Request] --> B[Check User Groups]
    B --> C[Check Project Access via User Groups]
    C --> D[Get Project's Project Group]
    D --> E[Resolve Permissions from Project Group]
    E --> F[Authorize Request]
```

---

## 🧪 Testing Admin Operations

### Complete Group Setup Test

```bash
#!/bin/bash

# Get admin token
ADMIN_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=EXISTING_PROJECT_HASH" | \
  jq -r '.session_token')

echo "1. Creating user group..."
USER_GROUP_RESPONSE=$(curl -s -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=test_developers&description=Test development team")

USER_GROUP_HASH=$(echo $USER_GROUP_RESPONSE | jq -r '.user_group.group_hash')

echo "2. Creating project group..."
PROJECT_GROUP_RESPONSE=$(curl -s -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=test_api_access&permissions=read&permissions=write&permissions=api_access&description=Test API access")

PROJECT_GROUP_HASH=$(echo $PROJECT_GROUP_RESPONSE | jq -r '.project_group.group_hash')

echo "3. Creating project..."
PROJECT_RESPONSE=$(curl -s -X POST "http://localhost:8000/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_name=Test API Project&project_description=Test project for API access")

PROJECT_HASH=$(echo $PROJECT_RESPONSE | jq -r '.project.project_hash')

echo "4. Assigning project to project group..."
curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$PROJECT_HASH"

echo "5. Granting user group access to project..."
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$PROJECT_HASH"

echo "6. Getting user group details..."
curl -X GET "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## 🛡️ Admin Security Considerations

### Access Control
- **Admin-only endpoints**: All admin operations require admin privileges
- **Group isolation**: User groups and project groups are separate concerns
- **Audit logging**: All admin operations are logged with full context
- **Permission validation**: Admin permissions verified on every request

### Best Practices
- **Least privilege**: Create specific groups rather than broad permissions
- **Regular audits**: Review group memberships and permissions regularly
- **Documentation**: Document the purpose of each group clearly
- **Testing**: Test group configurations before production deployment

### Security Warnings
- **Admin token protection**: Admin session tokens have elevated privileges
- **Group deletion**: Deleting groups affects all members immediately
- **Project assignment**: Assigning project to group gives all group members access
- **Permission inheritance**: Users inherit all permissions from their groups

---

## 🚀 Related Documentation

For efficient batch operations and analytics:

- **[Bulk Operations API](bulk-operations.md)** - Manage multiple users, roles, and groups simultaneously
- **[Analytics API](analytics.md)** - Monitor system usage, user activity, and project metrics

---

**Next:** Explore [Bulk Operations API](bulk-operations.md) for batch management, [Analytics API](analytics.md) for insights, [System API](system.md) for health checks, or [Error Handling](errors-and-responses.md) for error reference.