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

**Request Body** (Form):
- `permission_name` (required): Name of the permission
- `category` (optional, default: "general"): Permission category
- `description` (optional): Description of the permission

**Example Request:**
```bash
curl -X POST "http://localhost:8000/rbac/projects/abc123.../permissions" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_name=export_reports&category=data&description=Can export system reports"
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

**Request Body** (Form):
- `group_name` (required): Name of the role
- `priority` (optional, default: 50): Role priority (higher priority = more privileges)
- `description` (optional): Description of the role
- `permissions` (optional): List of permission names to assign to this role

**Example Request:**
```bash
curl -X POST "http://localhost:8000/rbac/projects/abc123.../roles" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=content_manager&priority=70&description=Content management and moderation&permissions=read&permissions=write&permissions=moderate_content"
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

### DELETE `/rbac/users/{user_hash}/projects/{project_hash}/roles/{role_id}`

Remove a user from a specific role in a project.

**Authentication:** Required (project admin)

**Path Parameters:**
- `user_hash`: User identifier
- `project_hash`: Project identifier
- `role_id`: Permission group (role) ID to remove

**Example Request:**
```bash
curl -X DELETE "http://localhost:8000/rbac/users/user123.../projects/abc123.../roles/5" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "User 'john_doe' removed from role 'editor' in project 'My Project'",
  "removal": {
    "user_hash": "user123...",
    "username": "john_doe",
    "project_hash": "abc123...",
    "role_id": 5,
    "role_name": "editor",
    "removed_at": "2024-01-01T12:00:00Z",
    "removed_by": "admin"
  }
}
```

---

### POST `/rbac/projects/{project_hash}/bulk-assign`

Bulk assign multiple users to multiple roles in a project.

**Authentication:** Required (project admin)

**Path Parameters:**
- `project_hash`: Project identifier

**Request Body** (Form):
- `user_hashes` (required): List of user hashes
- `role_ids` (required): List of permission group (role) IDs to assign

**Example Request:**
```bash
curl -X POST "http://localhost:8000/rbac/projects/abc123.../bulk-assign" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-abc123&user_hashes=usr-def456&role_ids=3&role_ids=5"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Bulk role assignment completed: 2 users succeeded, 0 failed",
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project"
  },
  "roles_assigned": [3, 5],
  "summary": {
    "total_users": 2,
    "success_count": 2,
    "error_count": 0
  },
  "results": [
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "roles_assigned": 2,
      "roles_failed": 0,
      "errors": [],
      "status": "success"
    },
    {
      "user_hash": "usr-def456",
      "username": "jane_smith",
      "roles_assigned": 2,
      "roles_failed": 0,
      "errors": [],
      "status": "success"
    }
  ],
  "errors": [],
  "performed_by": "admin",
  "performed_at": "2024-01-15T10:30:00Z"
}
```

---

### GET `/rbac/projects/{project_hash}/matrix`

Get permission matrix showing all users, roles, and their permissions in a project.

**Authentication:** Required (project admin)

**Path Parameters:**
- `project_hash`: Project identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/rbac/projects/abc123.../matrix" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "matrix": {
    "project": {
      "project_hash": "abc123...",
      "project_name": "My Project"
    },
    "permissions": [
      {
        "id": 1,
        "name": "read",
        "category": "general",
        "description": "Can view content and data"
      },
      {
        "id": 2,
        "name": "write",
        "category": "general",
        "description": "Can create and modify content"
      }
    ],
    "roles": [
      {
        "id": 3,
        "name": "editor",
        "description": "Content editing and management access",
        "priority": 60,
        "permissions": [
          {
            "id": 1,
            "name": "read",
            "category": "general"
          },
          {
            "id": 2,
            "name": "write",
            "category": "general"
          }
        ],
        "users": [
          {
            "user_hash": "usr-abc123",
            "username": "john_doe",
            "email": "john@example.com"
          }
        ]
      }
    ],
    "users": [
      {
        "user_hash": "usr-abc123",
        "username": "john_doe",
        "email": "john@example.com",
        "user_type": "consumer",
        "roles": [
          {
            "id": 3,
            "name": "editor",
            "assigned_at": "2024-01-10T12:00:00Z"
          }
        ],
        "permissions": [
          {
            "id": 1,
            "name": "read",
            "category": "general"
          },
          {
            "id": 2,
            "name": "write",
            "category": "general"
          }
        ]
      }
    ]
  },
  "statistics": {
    "total_permissions": 13,
    "total_roles": 6,
    "total_users": 15
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

### GET `/rbac/users/{user_hash}/projects/{project_hash}/history`

Get role assignment history for a user in a project.

**Authentication:** Required (project admin or self)

**Path Parameters:**
- `user_hash`: User identifier
- `project_hash`: Project identifier

**Query Parameters:**
- `limit` (optional, default: 50): Number of history records to return
- `offset` (optional, default: 0): Number of records to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/rbac/users/user123.../projects/abc123.../history?limit=20" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user": {
    "user_hash": "user123...",
    "username": "john_doe",
    "email": "john@example.com"
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project"
  },
  "history": [
    {
      "id": 152,
      "action": "assigned",
      "role": {
        "id": 3,
        "name": "editor",
        "description": "Content editing and management access"
      },
      "performed_by": {
        "user_hash": "usr-admin",
        "username": "admin"
      },
      "performed_at": "2024-01-10T12:00:00Z",
      "details": "User assigned to editor role",
      "is_active": true
    },
    {
      "id": 145,
      "action": "removed",
      "role": {
        "id": 6,
        "name": "viewer",
        "description": "View-only access"
      },
      "performed_by": {
        "user_hash": "usr-admin",
        "username": "admin"
      },
      "performed_at": "2024-01-09T15:30:00Z",
      "details": "User removed from viewer role",
      "is_active": false
    }
  ],
  "pagination": {
    "total": 5,
    "limit": 20,
    "offset": 0,
    "has_more": false,
    "next_offset": null
  },
  "generated_at": "2024-01-15T10:30:00Z"
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

## 🧪 Testing RBAC Operations

### Complete RBAC Setup Test

```bash
#!/bin/bash

# Get admin session token
ADMIN_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=PROJECT_HASH" | \
  jq -r '.session_token')

PROJECT_HASH="YOUR_PROJECT_HASH"

echo "1. Initializing RBAC for project..."
curl -X POST "http://localhost:8000/rbac/projects/$PROJECT_HASH/initialize" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n2. Creating custom permission..."
curl -X POST "http://localhost:8000/rbac/projects/$PROJECT_HASH/permissions" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"permission_name": "custom_action", "category": "custom", "description": "Custom permission"}'

echo -e "\n3. Creating custom role..."
curl -X POST "http://localhost:8000/rbac/projects/$PROJECT_HASH/roles" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"group_name": "custom_role", "priority": 50, "description": "Custom role", "permissions": ["read", "custom_action"]}'

echo -e "\n4. Assigning user to role..."
curl -X POST "http://localhost:8000/rbac/users/USER_HASH/projects/$PROJECT_HASH/roles" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_id=ROLE_ID"

echo -e "\n5. Checking user permissions..."
curl -X GET "http://localhost:8000/rbac/users/USER_HASH/projects/$PROJECT_HASH/permissions" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n6. Getting RBAC summary..."
curl -X GET "http://localhost:8000/rbac/projects/$PROJECT_HASH/summary" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## 🔒 Security Considerations

### Access Control
- **Project Scoping**: All RBAC operations are scoped to specific projects
- **Admin Permission Required**: Most RBAC management requires admin privileges
- **User Context**: Users can view their own permissions, admins can view any
- **Audit Trail**: All RBAC operations are logged for security review

### Best Practices
- **Least Privilege**: Grant minimum required permissions
- **Role Hierarchy**: Use priority levels to establish clear role hierarchy
- **Regular Audits**: Review role assignments and permissions regularly
- **Permission Granularity**: Create specific permissions rather than broad ones

### Security Warnings
- **Admin Role**: Admin role should be assigned carefully
- **Permission Inheritance**: Users inherit all permissions from assigned roles
- **Role Priority**: Higher priority roles can override lower priority ones
- **Audit Monitoring**: Monitor audit logs for suspicious RBAC changes

---

**Next:** Explore [System API](system.md) for monitoring and health checks, or [User Type Management](user-type-management.md) for hierarchical access control. 