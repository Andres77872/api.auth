# RBAC Management API

Complete RBAC (Role-Based Access Control) management documentation for project-specific permissions, roles, and user assignments.

## 🔐 Authentication Required

All RBAC endpoints require authentication with appropriate permissions:

```
Authorization: Bearer YOUR_SESSION_TOKEN
```

**Access Levels:**
- **Admin Required**: Most RBAC management operations
- **Project Admin**: Admin users limited to their assigned project
- **User Access**: Some endpoints allow users to view their own permissions

---

## 📋 Permission Management

### GET `/rbac/projects/{project_hash}/permissions`

List all permissions for a specific project.

**Authentication:** Required

**Path Parameters:**
- `project_hash`: Project identifier

**Query Parameters:**
- `category` (optional): Filter by permission category
- `limit` (optional, default: 50): Maximum number of results
- `offset` (optional, default: 0): Number of results to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/rbac/projects/abc123.../permissions?category=admin&limit=20" \
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
  "permissions": [
    {
      "id": 1,
      "permission_name": "admin",
      "category": "admin",
      "description": "Full administrative access",
      "created_at": "2024-01-01T12:00:00Z"
    },
    {
      "id": 2,
      "permission_name": "manage_users",
      "category": "admin", 
      "description": "Can manage user accounts and roles",
      "created_at": "2024-01-01T12:00:00Z"
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total": 13,
    "filtered_by_category": "admin"
  }
}
```

---

### POST `/rbac/projects/{project_hash}/permissions`

Create a new permission for a project.

**Authentication:** Required (project admin)

**Path Parameters:**
- `project_hash`: Project identifier

**Request Body** (JSON or Form):
```json
{
  "permission_name": "export_reports",
  "category": "data",
  "description": "Can export system reports"
}
```

**Example Request:**
```bash
curl -X POST "http://localhost:8000/rbac/projects/abc123.../permissions" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "permission_name": "export_reports",
    "category": "data", 
    "description": "Can export system reports"
  }'
```

**Response (200):**
```json
{
  "success": true,
  "message": "Permission 'export_reports' created successfully",
  "permission": {
    "id": 15,
    "permission_name": "export_reports",
    "category": "data",
    "description": "Can export system reports",
    "project_hash": "abc123...",
    "created_at": "2024-01-01T12:00:00Z"
  }
}
```

---

## 🎭 Role Management

### GET `/rbac/projects/{project_hash}/roles`

List all permission groups (roles) for a specific project.

**Authentication:** Required

**Path Parameters:**
- `project_hash`: Project identifier

**Query Parameters:**
- `limit` (optional, default: 50): Maximum number of results
- `offset` (optional, default: 0): Number of results to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/rbac/projects/abc123.../roles" \
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
  "roles": [
    {
      "id": 1,
      "group_name": "admin",
      "priority": 100,
      "description": "Full administrative access to all features",
      "created_at": "2024-01-01T00:00:00Z",
      "is_active": true
    },
    {
      "id": 2,
      "group_name": "editor",
      "priority": 60,
      "description": "Content editing and management access",
      "created_at": "2024-01-01T00:00:00Z", 
      "is_active": true
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 6
  }
}
```

---

### POST `/rbac/projects/{project_hash}/roles`

Create a new role for a project.

**Authentication:** Required (project admin)

**Path Parameters:**
- `project_hash`: Project identifier

**Request Body** (JSON or Form):
```json
{
  "group_name": "content_manager",
  "priority": 70,
  "description": "Content management and moderation",
  "permissions": ["read", "write", "moderate_content"]
}
```

**Example Request:**
```bash
curl -X POST "http://localhost:8000/rbac/projects/abc123.../roles" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "group_name": "content_manager",
    "priority": 70,
    "description": "Content management and moderation",
    "permissions": ["read", "write", "moderate_content"]
  }'
```

**Response (200):**
```json
{
  "success": true,
  "message": "Role 'content_manager' created successfully",
  "role": {
    "id": 7,
    "group_name": "content_manager",
    "priority": 70,
    "description": "Content management and moderation",
    "project_hash": "abc123...",
    "assigned_permissions": ["read", "write", "moderate_content"],
    "created_at": "2024-01-01T12:00:00Z"
  }
}
```

---

## 👥 User Role Assignments

### POST `/rbac/users/{user_hash}/projects/{project_hash}/roles`

Assign a user to a role in a specific project.

**Authentication:** Required (project admin)

**Path Parameters:**
- `user_hash`: User identifier
- `project_hash`: Project identifier

**Request Body** (Form):
- `role_id`: Permission group (role) ID

**Example Request:**
```bash
curl -X POST "http://localhost:8000/rbac/users/user123.../projects/abc123.../roles" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_id=5"
```

**Response (200):**
```json
{
  "success": true,
  "message": "User 'john_doe' assigned to role in project 'My Project'",
  "assignment": {
    "user_hash": "user123...",
    "project_hash": "abc123...",
    "role_id": 5,
    "assigned_by": "admin",
    "assigned_at": "2024-01-01T12:00:00Z"
  }
}
```

---

### GET `/rbac/users/{user_hash}/projects/{project_hash}/roles`

List all roles assigned to a user in a specific project.

**Authentication:** Required (user can view own roles, admins can view any)

**Path Parameters:**
- `user_hash`: User identifier
- `project_hash`: Project identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/rbac/users/user123.../projects/abc123.../roles" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user": {
    "user_hash": "user123...",
    "username": "john_doe"
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project"
  },
  "roles": [
    {
      "id": 3,
      "group_name": "editor",
      "priority": 60,
      "description": "Content editing and management access",
      "assigned_at": "2024-01-01T10:00:00Z"
    }
  ]
}
```

---

## 🔍 Permission Checking

### GET `/rbac/users/{user_hash}/projects/{project_hash}/permissions`

Get all effective permissions for a user in a specific project.

**Authentication:** Required (user can view own permissions, admins can view any)

**Path Parameters:**
- `user_hash`: User identifier
- `project_hash`: Project identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/rbac/users/user123.../projects/abc123.../permissions" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user": {
    "user_hash": "user123...",
    "username": "john_doe"
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project"
  },
  "effective_permissions": [
    {
      "permission_name": "read",
      "category": "general",
      "description": "Can view content and data",
      "granted_through_role": "editor"
    },
    {
      "permission_name": "write", 
      "category": "general",
      "description": "Can create and modify content",
      "granted_through_role": "editor"
    }
  ],
  "summary": {
    "total_permissions": 5,
    "categories": ["general", "content"]
  }
}
```

---

### GET `/rbac/users/{user_hash}/projects/{project_hash}/check/{permission_name}`

Check if a user has a specific permission in a project.

**Authentication:** Required

**Path Parameters:**
- `user_hash`: User identifier
- `project_hash`: Project identifier
- `permission_name`: Name of the permission to check

**Example Request:**
```bash
curl -X GET "http://localhost:8000/rbac/users/user123.../projects/abc123.../check/admin" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user": {
    "user_hash": "user123...",
    "username": "john_doe"
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project"
  },
  "permission_check": {
    "permission_name": "admin",
    "has_permission": false,
    "checked_at": "2024-01-01T12:00:00Z"
  }
}
```

---

## 🚀 RBAC Initialization

### POST `/rbac/projects/{project_hash}/initialize`

Initialize RBAC system for a project with default permissions and roles.

**Authentication:** Required (project admin)

**Path Parameters:**
- `project_hash`: Project identifier

**Query Parameters:**
- `create_default_permissions` (optional, default: true): Whether to create default permissions
- `create_default_roles` (optional, default: true): Whether to create default roles

**Example Request:**
```bash
curl -X POST "http://localhost:8000/rbac/projects/abc123.../initialize?create_default_permissions=true&create_default_roles=true" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "RBAC system initialized for project 'My Project'",
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project"
  },
  "initialization_summary": {
    "permissions_created": 13,
    "roles_created": 6,
    "default_permissions": true,
    "default_roles": true,
    "initialized_by": "admin",
    "initialized_at": "2024-01-01T12:00:00Z"
  },
  "created_permissions": [
    "read", "write", "delete", "create", "update", "admin", 
    "manage_users", "manage_roles", "view_audit", "export_data", 
    "import_data", "api_access", "full_access"
  ],
  "created_roles": [
    "admin", "manager", "editor", "contributor", "api_user", "viewer"
  ]
}
```

---

## 📋 Audit and Reporting

### GET `/rbac/projects/{project_hash}/audit`

Get audit log for RBAC operations in a project.

**Authentication:** Required (project admin)

**Path Parameters:**
- `project_hash`: Project identifier

**Query Parameters:**
- `limit` (optional, default: 50): Maximum number of results
- `offset` (optional, default: 0): Number of results to skip
- `action_type` (optional): Filter by action type

**Example Request:**
```bash
curl -X GET "http://localhost:8000/rbac/projects/abc123.../audit?action_type=ASSIGN_ROLE&limit=20" \
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
  "audit_log": [
    {
      "id": 45,
      "action_type": "ASSIGN_ROLE",
      "performed_by": 1,
      "target_user_id": 5,
      "permission_group_id": 3,
      "action_timestamp": "2024-01-01T11:30:00Z",
      "ip_address": "192.168.1.100",
      "user_agent": "curl/7.68.0"
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "filtered_by_action": "ASSIGN_ROLE"
  }
}
```

---

### GET `/rbac/projects/{project_hash}/summary`

Get comprehensive RBAC summary for a project.

**Authentication:** Required

**Path Parameters:**
- `project_hash`: Project identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/rbac/projects/abc123.../summary" \
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
  "rbac_summary": {
    "total_permissions": 13,
    "total_roles": 6,
    "total_user_assignments": 25,
    "permissions_by_category": {
      "general": ["read", "write", "create", "update", "delete"],
      "admin": ["admin", "manage_users", "manage_roles", "view_audit", "full_access"],
      "data": ["export_data", "import_data"],
      "api": ["api_access"]
    },
    "roles_by_priority": [
      {
        "group_name": "admin",
        "priority": 100,
        "is_active": true
      },
      {
        "group_name": "manager", 
        "priority": 80,
        "is_active": true
      },
      {
        "group_name": "editor",
        "priority": 60,
        "is_active": true
      }
    ],
    "active_roles": 6,
    "categories": ["general", "admin", "data", "api"]
  }
}
```

---

**Next:** Explore [System API](system.md) for monitoring and health checks, or [User Type Management](user-type-management.md) for hierarchical access control. 