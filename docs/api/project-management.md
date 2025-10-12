# Project Management API

Complete project management documentation for creating, reading, updating, and deleting projects with group-based access control.

## 🔐 Authentication Required

All endpoints require authentication:

```
Authorization: Bearer YOUR_SESSION_TOKEN
```

---

## 📋 Project CRUD Operations

### GET `/projects`

List projects based on user's access level and group memberships.

**Authentication:** Required

**Query Parameters:**
- `limit` (optional, default: 10): Number of projects to return
- `offset` (optional, default: 0): Number of projects to skip
- `search` (optional): Search term for project name or description

**Example Request:**
```bash
curl -X GET "http://localhost:8000/projects?limit=10&offset=0" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "projects": [
    {
      "project_hash": "abc123...",
      "project_name": "Main Project",
      "project_description": "Main application project",
      "access_level": "admin",
      "access_through": "user_group"
    }
  ],
  "pagination": {
    "limit": 10,
    "offset": 0,
    "total_count": 25,
    "has_more": true
  },
  "user_access_level": "admin"
}
```

---

### POST `/projects`

Create new project and assign it to default project group.

**Authentication:** Required (admin permission)

**Request Body** (Form):
- `project_name` (required): Name of the project
- `project_description` (optional): Description of the project

**Example Request:**
```bash
curl -X POST "http://localhost:8000/projects" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_name=New Project&project_description=A new project"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Project \"New Project\" created successfully",
  "project": {
    "project_hash": "new_project_hash...",
    "project_name": "New Project",
    "project_description": "A new project",
    "created_at": "2024-01-01T12:00:00Z"
  }
}
```

---

### GET `/projects/{project_hash}`

Get detailed project information with user's access context.

**Authentication:** Required (must have access to the project)

**Path Parameters:**
- `project_hash`: Hash of the project to retrieve

**Example Request:**
```bash
curl -X GET "http://localhost:8000/projects/abc123..." \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "project": {
    "project_id": 1,
    "project_hash": "abc123...",
    "project_name": "Main Project",
    "project_description": "Main application project",
    "created_at": "2024-01-01T00:00:00Z",
    "is_active": true
  },
  "user_access": {
    "permissions": ["admin", "read", "write", "delete"],
    "access_level": "admin",
    "user_groups": ["administrators"]
  },
  "statistics": {
    "total_users": 15,
    "active_sessions": 8,
    "total_groups": 3
  }
}
```

---

### PUT `/projects/{project_hash}`

Update project information (admin only).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Hash of the project to update

**Request Body** (Form):
- `project_name` (optional): Updated name of the project
- `project_description` (optional): Updated description of the project

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/projects/abc123..." \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_name=Updated Project Name"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Project updated successfully",
  "project": {
    "project_id": 1,
    "project_hash": "abc123...",
    "project_name": "Updated Project Name",
    "project_description": "Updated description",
    "updated_by": 1
  }
}
```

---

### DELETE `/projects/{project_hash}`

Delete a project and revoke all user group access (admin only).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Hash of the project to delete

**Example Request:**
```bash
curl -X DELETE "http://localhost:8000/projects/abc123..." \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Project \"My Project\" deleted successfully",
  "deleted_project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "deleted_by": 1
  },
  "warning": "All user group access to this project has been revoked"
}
```

---

### PATCH `/projects/{project_hash}/owner`

Transfer project ownership to another user.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Hash of the project

**Request Body** (Form):
- `new_owner_hash` (required): User hash of the new owner

**Example Request:**
```bash
curl -X PATCH "http://localhost:8000/projects/abc123.../owner" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "new_owner_hash=usr-def456"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Project ownership transferred to new_owner",
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project"
  },
  "new_owner": {
    "user_hash": "usr-def456",
    "username": "new_owner",
    "email": "newowner@example.com"
  },
  "transferred_by": {
    "user_hash": "usr-abc123",
    "username": "admin"
  },
  "transferred_at": "2024-01-15T10:30:00Z"
}
```

---

### PATCH `/projects/{project_hash}/archive`

Archive or unarchive a project.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Hash of the project

**Request Body** (Form):
- `archived` (required): `true` to archive, `false` to unarchive

**Example Request - Archive:**
```bash
curl -X PATCH "http://localhost:8000/projects/abc123.../archive" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "archived=true"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Project My Project archived successfully",
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "archived": true
  },
  "action_details": {
    "action": "archive",
    "performed_by": "admin",
    "performed_at": "2024-01-15T10:30:00Z"
  }
}
```

**Example Request - Unarchive:**
```bash
curl -X PATCH "http://localhost:8000/projects/abc123.../archive" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "archived=false"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Project My Project unarchived successfully",
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "archived": false
  },
  "action_details": {
    "action": "unarchive",
    "performed_by": "admin",
    "performed_at": "2024-01-15T10:35:00Z"
  }
}
```

---

### GET `/projects/{project_hash}/activity`

Get recent activity log for a project.

**Authentication:** Required (project access)

**Path Parameters:**
- `project_hash`: Project identifier

**Query Parameters:**
- `limit` (optional, default: 50, max: 100): Number of activities to return
- `offset` (optional, default: 0): Number of activities to skip
- `activity_type` (optional): Filter by activity type
- `days` (optional, default: 30, max: 365): Days to look back

**Example Request:**
```bash
curl -X GET "http://localhost:8000/projects/abc123.../activity?limit=20&days=7" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project"
  },
  "activities": [
    {
      "id": 1523,
      "activity_type": "member_added",
      "details": "User 'john_doe' added to project",
      "performed_by": {
        "user_hash": "usr-admin",
        "username": "admin"
      },
      "target_user": {
        "user_hash": "usr-john",
        "username": "john_doe"
      },
      "created_at": "2024-01-15T10:25:00Z",
      "ip_address": "192.168.1.100"
    },
    {
      "id": 1522,
      "activity_type": "project_updated",
      "details": "Project name updated",
      "performed_by": {
        "user_hash": "usr-admin",
        "username": "admin"
      },
      "created_at": "2024-01-15T09:15:00Z",
      "ip_address": "192.168.1.100"
    }
  ],
  "pagination": {
    "total": 145,
    "limit": 20,
    "offset": 0
  },
  "filters": {
    "activity_type": null,
    "days": 7
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

### GET `/projects/{project_hash}/stats`

Get detailed statistics for a project.

**Authentication:** Required (project access)

**Path Parameters:**
- `project_hash`: Project identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/projects/abc123.../stats" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "project_description": "Main application project"
  },
  "statistics": {
    "members": {
      "total": 15,
      "active": 12,
      "by_role": {
        "admin": 2,
        "editor": 5,
        "viewer": 8
      }
    },
    "activity": {
      "total_sessions_30d": 523,
      "total_activities_30d": 1247,
      "avg_sessions_per_user": 34.8,
      "most_active_user": {
        "user_hash": "usr-john",
        "username": "john_doe",
        "session_count": 85
      }
    },
    "groups": {
      "user_groups_with_access": 3,
      "permission_groups": 2
    },
    "health": {
      "status": "healthy",
      "last_activity": "2024-01-15T10:25:00Z",
      "activity_score": 92.5
    }
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

### GET `/projects/{project_hash}/members`

Get paginated list of project members with their roles and permissions.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Project identifier

**Query Parameters:**
- `limit` (optional, default: 50, max: 100): Number of members to return
- `offset` (optional, default: 0): Number of members to skip
- `user_type` (optional): Filter by user type (admin, consumer)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/projects/abc123.../members?limit=50&offset=0&user_type=consumer" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "project_description": "Main application project"
  },
  "members": [
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "email": "john@example.com",
      "user_type": "consumer",
      "is_active": true,
      "permissions": ["read", "write"],
      "groups": ["developers"],
      "access_level": "read-write",
      "joined_at": "2024-01-10T12:00:00Z",
      "granted_by": null,
      "created_at": "2024-01-01T08:00:00Z"
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
    "root_users": 1,
    "admin_users": 2,
    "consumer_users": 12,
    "active_members": 14
  }
}
```

---

### POST `/projects/{project_hash}/members`

Add a user as a member to a project.

**Authentication:** Required (project admin)

**Path Parameters:**
- `project_hash`: Project identifier

**Request Body** (Form):
- `user_hash` (required): Hash of the user to add
- `role` (optional, default: "consumer"): Role to assign ("consumer" or "admin")

**Example Request:**
```bash
curl -X POST "http://localhost:8000/projects/abc123.../members" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hash=usr-def456&role=consumer"
```

**Response (200):**
```json
{
  "success": true,
  "message": "User 'jane_smith' added to project 'My Project' as consumer",
  "member": {
    "user_hash": "usr-def456",
    "username": "jane_smith",
    "email": "jane@example.com",
    "user_type": "consumer",
    "role": "consumer",
    "permissions": ["read", "write"],
    "groups": ["developers"],
    "access_type": "consumer_access",
    "added_by": "admin",
    "added_at": "2024-01-15T10:30:00Z"
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "project_description": "Main application project"
  }
}
```

---

### DELETE `/projects/{project_hash}/members/{user_hash}`

Remove a user from a project.

**Authentication:** Required (project admin)

**Path Parameters:**
- `project_hash`: Project identifier
- `user_hash`: Hash of the user to remove

**Example Request:**
```bash
curl -X DELETE "http://localhost:8000/projects/abc123.../members/usr-def456" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "User jane_smith removed from project My Project",
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project"
  },
  "removed_member": {
    "user_hash": "usr-def456",
    "username": "jane_smith",
    "email": "jane@example.com"
  }
}
```

---

### GET `/projects/{project_hash}/groups`

List all user groups that have access to a project.

**Authentication:** Required (project access)

**Path Parameters:**
- `project_hash`: Project identifier

**Query Parameters:**
- `limit` (optional, default: 100, max: 500): Number of groups to return
- `offset` (optional, default: 0): Number of groups to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/projects/abc123.../groups" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user_groups": [
    {
      "group_hash": "grp-xyz789",
      "group_name": "developers",
      "description": "Development team",
      "created_at": "2024-01-01T12:00:00Z"
    }
  ],
  "pagination": {
    "total": 3,
    "limit": 100,
    "offset": 0,
    "has_more": false
  }
}
```

---

### POST `/projects/{project_hash}/groups`

Grant a user group access to a project.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Project identifier

**Request Body** (Form):
- `group_hash` (required): User group hash

**Example Request:**
```bash
curl -X POST "http://localhost:8000/projects/abc123.../groups" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_hash=grp-xyz789"
```

**Response (200):**
```json
{
  "success": true,
  "message": "User group 'developers' granted access to project 'My Project'",
  "access_details": {
    "group_hash": "grp-xyz789",
    "group_name": "developers",
    "project_hash": "abc123...",
    "project_name": "My Project",
    "granted_by": "admin",
    "granted_at": "2024-01-15T10:30:00Z"
  }
}
```

---

## 🏗️ Group-Based Project Access

### Understanding Project Access Control

Projects in this system use hierarchical group-based access:

```
User Groups → Define which projects users can access
Project Groups → Define what permissions users have in projects
```

### Access Levels

| Access Level | Description | Typical Groups |
|-------------|-------------|----------------|
| **admin** | Full project control | administrators |
| **write** | Can modify project data | users, contributors |
| **read** | View-only access | guests, viewers |

### Project Creation Flow

```mermaid
graph TD
    A[Create Project] --> B[Assign to Default Project Group]
    B --> C[Grant User Group Access]
    C --> D[Users Can Access via Groups]
    D --> E[Permissions from Project Group]
```

---

## 🧪 Testing Project Management

### Test Project CRUD Operations

```bash
#!/bin/bash

# Get admin session token
ADMIN_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=EXISTING_PROJECT_HASH" | \
  jq -r '.session_token')

echo "1. Creating new project..."
CREATE_RESPONSE=$(curl -s -X POST "http://localhost:8000/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_name=Test Project&project_description=A test project")

echo "Create Response: $CREATE_RESPONSE"

# Extract project hash
PROJECT_HASH=$(echo $CREATE_RESPONSE | jq -r '.project.project_hash')

echo -e "\n2. Getting project details..."
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n3. Updating project..."
curl -X PUT "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_name=Updated Test Project"

echo -e "\n4. Listing all projects..."
curl -X GET "http://localhost:8000/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n5. Deleting project..."
curl -X DELETE "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Test Project Access Control

```bash
#!/bin/bash

# Test access control for different user types
echo "1. Admin access to projects..."
ADMIN_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=PROJECT_HASH" | \
  jq -r '.session_token')

curl -X GET "http://localhost:8000/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n2. Regular user access to projects..."
USER_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=user&password=userpass&project_hash=PROJECT_HASH" | \
  jq -r '.session_token')

curl -X GET "http://localhost:8000/projects" \
  -H "Authorization: Bearer $USER_TOKEN"

echo -e "\n3. Testing unauthorized project creation..."
curl -X POST "http://localhost:8000/projects" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_name": "Unauthorized Project"}'
```

---

## 🛡️ Security and Access Control

### Project Access Security
- **Group-based access**: Only users whose groups have access can see projects
- **Permission validation**: Each operation checks specific permissions
- **Audit trail**: All project changes are logged with user context
- **Automatic cleanup**: Deleted projects remove all group access

### Permission Hierarchy
```
admin > write > read
```

### Access Control Matrix

| Permission | List Projects | View Project | Create Project | Update Project | Delete Project |
|------------|---------------|--------------|----------------|----------------|----------------|
| **admin** | ✅ All | ✅ Full Details | ✅ Yes | ✅ Yes | ✅ Yes |
| **write** | ✅ Accessible | ✅ Basic Details | ❌ No | ✅ Limited | ❌ No |
| **read** | ✅ Accessible | ✅ Basic Details | ❌ No | ❌ No | ❌ No |

### Group-Based Project Access
- **User groups** determine which projects a user can access
- **Project groups** determine what permissions the user has
- **Dynamic access**: Adding/removing group access immediately affects user access
- **Cross-project access**: Users can switch between accessible projects

---

**Next:** Learn about [Admin API](admin.md) for group management or [System API](system.md) for monitoring.