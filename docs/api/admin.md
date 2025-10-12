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
- `activity_type` (optional): Filter by activity type
- `user_id` (optional): Filter by user ID
- `project_id` (optional): Filter by project ID
- `days` (optional, default: 30, max: 365): Days to look back

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/activity?limit=20&days=7&activity_type=user_login" \
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
    "version": "2.0.0",
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
- `limit` (optional, default: 50): Number of groups to return
- `offset` (optional, default: 0): Number of groups to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/user-groups?limit=50&offset=0" \
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
      "created_at": "2024-01-01T00:00:00Z",
      "is_active": true
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

**Request Body** (JSON):
```json
{
  "group_name": "developers",
  "description": "Software development team"
}
```

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"group_name": "developers", "description": "Software development team"}'
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
    "created_at": "2024-01-01T00:00:00Z",
    "is_active": true
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
      "project_id": 1,
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

**Request Body** (JSON):
```json
{
  "group_name": "updated_developers",
  "description": "Updated software development team"
}
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
      "created_at": "2024-01-01T00:00:00Z",
      "is_active": true
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
    "created_at": "2024-01-01T00:00:00Z",
    "is_active": true
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

**Request Body** (JSON):
```json
{
  "group_name": "api-access",
  "permissions": ["read", "write", "api_access"],
  "description": "API access permissions"
}
```

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"group_name": "api-access", "permissions": ["read", "write", "api_access"], "description": "API access permissions"}'
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

**Request Body** (JSON):
```json
{
  "group_name": "api-access-updated",
  "permissions": ["read", "write", "api_access", "export_data"],
  "description": "Updated API access permissions"
}
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
  -H "Content-Type: application/json" \
  -d '{"group_name": "test_developers", "description": "Test development team"}')

USER_GROUP_HASH=$(echo $USER_GROUP_RESPONSE | jq -r '.user_group.group_hash')

echo "2. Creating project group..."
PROJECT_GROUP_RESPONSE=$(curl -s -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"group_name": "test_api_access", "permissions": ["read", "write", "api_access"], "description": "Test API access"}')

PROJECT_GROUP_HASH=$(echo $PROJECT_GROUP_RESPONSE | jq -r '.project_group.group_hash')

echo "3. Creating project..."
PROJECT_RESPONSE=$(curl -s -X POST "http://localhost:8000/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_name": "Test API Project", "project_description": "Test project for API access"}')

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

## 📚 SDK Examples

### Python Admin SDK

```python
import requests

class AdminAPI:
    def __init__(self, base_url, admin_session_token):
        self.base_url = base_url
        self.session_token = admin_session_token
        self.headers = {"Authorization": f"Bearer {admin_session_token}"}
    
    # User Group Management
    def list_user_groups(self, limit=50, offset=0):
        """List all user groups"""
        response = requests.get(
            f"{self.base_url}/admin/user-groups",
            headers=self.headers,
            params={"limit": limit, "offset": offset}
        )
        return response.json()
    
    def create_user_group(self, group_name, description):
        """Create a new user group"""
        response = requests.post(
            f"{self.base_url}/admin/user-groups",
            headers={**self.headers, "Content-Type": "application/json"},
            json={"group_name": group_name, "description": description}
        )
        return response.json()
    
    def get_user_group(self, group_hash):
        """Get detailed user group information"""
        response = requests.get(
            f"{self.base_url}/admin/user-groups/{group_hash}",
            headers=self.headers
        )
        return response.json()
    
    def assign_user_to_group(self, group_hash, user_hash):
        """Assign a user to a user group"""
        response = requests.post(
            f"{self.base_url}/admin/user-groups/{group_hash}/members",
            headers=self.headers,
            data={"user_hash": user_hash}
        )
        return response.json()
    
    def grant_group_project_access(self, group_hash, project_hash):
        """Grant user group access to a project"""
        response = requests.post(
            f"{self.base_url}/admin/user-groups/{group_hash}/projects",
            headers=self.headers,
            data={"project_hash": project_hash}
        )
        return response.json()
    
    # Project Group Management
    def list_project_groups(self, limit=50, offset=0):
        """List all project groups"""
        response = requests.get(
            f"{self.base_url}/admin/project-groups",
            headers=self.headers,
            params={"limit": limit, "offset": offset}
        )
        return response.json()
    
    def create_project_group(self, group_name, permissions, description):
        """Create a new project group"""
        response = requests.post(
            f"{self.base_url}/admin/project-groups",
            headers={**self.headers, "Content-Type": "application/json"},
            json={
                "group_name": group_name,
                "permissions": permissions,
                "description": description
            }
        )
        return response.json()
    
    def assign_project_to_group(self, group_hash, project_hash):
        """Assign a project to a project group"""
        response = requests.post(
            f"{self.base_url}/admin/project-groups/{group_hash}/projects",
            headers=self.headers,
            data={"project_hash": project_hash}
        )
        return response.json()

# Usage
admin_api = AdminAPI("http://localhost:8000", "admin_session_token")

# Create complete group setup
user_group = admin_api.create_user_group("api_users", "API access users")
project_group = admin_api.create_project_group(
    "api_permissions", 
    ["read", "write", "api_access"], 
    "Standard API permissions"
)

# Grant access
admin_api.grant_group_project_access(
    user_group["user_group"]["group_hash"],
    "project_hash"
)
```

### JavaScript Admin SDK

```javascript
class AdminAPI {
    constructor(baseUrl, adminSessionToken) {
        this.baseUrl = baseUrl;
        this.sessionToken = adminSessionToken;
        this.headers = {
            'Authorization': `Bearer ${adminSessionToken}`
        };
    }
    
    // User Group Management
    async listUserGroups(limit = 50, offset = 0) {
        const params = new URLSearchParams({ limit, offset });
        const response = await fetch(`${this.baseUrl}/admin/user-groups?${params}`, {
            headers: this.headers
        });
        return await response.json();
    }
    
    async createUserGroup(groupName, description) {
        const response = await fetch(`${this.baseUrl}/admin/user-groups`, {
            method: 'POST',
            headers: {
                ...this.headers,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                group_name: groupName,
                description: description
            })
        });
        return await response.json();
    }
    
    async getUserGroup(groupHash) {
        const response = await fetch(`${this.baseUrl}/admin/user-groups/${groupHash}`, {
            headers: this.headers
        });
        return await response.json();
    }
    
    async assignUserToGroup(groupHash, userHash) {
        const response = await fetch(`${this.baseUrl}/admin/user-groups/${groupHash}/members`, {
            method: 'POST',
            headers: {
                ...this.headers,
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: new URLSearchParams({ user_hash: userHash })
        });
        return await response.json();
    }
    
    async grantGroupProjectAccess(groupHash, projectHash) {
        const response = await fetch(`${this.baseUrl}/admin/user-groups/${groupHash}/projects`, {
            method: 'POST',
            headers: {
                ...this.headers,
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: new URLSearchParams({ project_hash: projectHash })
        });
        return await response.json();
    }
    
    // Project Group Management
    async listProjectGroups(limit = 50, offset = 0) {
        const params = new URLSearchParams({ limit, offset });
        const response = await fetch(`${this.baseUrl}/admin/project-groups?${params}`, {
            headers: this.headers
        });
        return await response.json();
    }
    
    async createProjectGroup(groupName, permissions, description) {
        const response = await fetch(`${this.baseUrl}/admin/project-groups`, {
            method: 'POST',
            headers: {
                ...this.headers,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                group_name: groupName,
                permissions: permissions,
                description: description
            })
        });
        return await response.json();
    }
    
    async assignProjectToGroup(groupHash, projectHash) {
        const response = await fetch(`${this.baseUrl}/admin/project-groups/${groupHash}/projects`, {
            method: 'POST',
            headers: {
                ...this.headers,
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: new URLSearchParams({ project_hash: projectHash })
        });
        return await response.json();
    }
}

// Usage
const adminAPI = new AdminAPI('http://localhost:8000', 'admin_session_token');

// Create complete group setup
const userGroup = await adminAPI.createUserGroup('api_users', 'API access users');
const projectGroup = await adminAPI.createProjectGroup(
    'api_permissions',
    ['read', 'write', 'api_access'],
    'Standard API permissions'
);

// Grant access
await adminAPI.grantGroupProjectAccess(
    userGroup.user_group.group_hash,
    'project_hash'
);
```

---

## 🔧 Common Admin Use Cases

### 1. Complete User Onboarding

```python
def onboard_new_user(admin_api, username, email, user_group_name, project_hashes):
    """Complete user onboarding process"""
    # This would typically involve:
    # 1. User registration (handled by auth endpoints)
    # 2. Group assignment (admin operation)
    # 3. Project access verification
    
    # Get user group
    user_groups = admin_api.list_user_groups()
    target_group = next(
        (g for g in user_groups["user_groups"] if g["group_name"] == user_group_name),
        None
    )
    
    if not target_group:
        return {"error": f"User group {user_group_name} not found"}
    
    # Note: User hash would come from user creation
    # admin_api.assign_user_to_group(target_group["group_hash"], user_hash)
    
    # Verify project access
    group_details = admin_api.get_user_group(target_group["group_hash"])
    accessible_projects = [p["project_hash"] for p in group_details["accessible_projects"]]
    
    return {
        "user_group": target_group["group_name"],
        "accessible_projects": accessible_projects,
        "missing_projects": [p for p in project_hashes if p not in accessible_projects]
    }
```

### 2. Permission Audit

```javascript
async function auditGroupPermissions(adminAPI) {
    const userGroups = await adminAPI.listUserGroups(100);
    const projectGroups = await adminAPI.listProjectGroups(100);
    
    const audit = {
        userGroups: [],
        projectGroups: [],
        recommendations: []
    };
    
    // Audit user groups
    for (const group of userGroups.user_groups) {
        const details = await adminAPI.getUserGroup(group.group_hash);
        audit.userGroups.push({
            name: group.group_name,
            members: details.statistics.total_members,
            projects: details.statistics.total_projects,
            lastActivity: group.created_at
        });
        
        // Flag groups with no members
        if (details.statistics.total_members === 0) {
            audit.recommendations.push(`User group "${group.group_name}" has no members`);
        }
    }
    
    // Audit project groups
    for (const group of projectGroups.project_groups) {
        audit.projectGroups.push({
            name: group.group_name,
            permissions: group.permissions,
            projects: group.project_count
        });
        
        // Flag groups with no projects
        if (group.project_count === 0) {
            audit.recommendations.push(`Project group "${group.group_name}" has no projects assigned`);
        }
    }
    
    return audit;
}
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

**Next:** Explore [System API](system.md) for monitoring and health checks, or [Error Handling](errors-and-responses.md) for comprehensive error reference.