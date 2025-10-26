# User Type Management API

Complete documentation for the **3-Tier User Type Management System** that provides hierarchical user administration capabilities.

## 🏗️ Overview

The 3-Tier User Type system provides clear separation of privileges and responsibilities:

1. **ROOT USERS**: Super administrators with unrestricted global access
2. **ADMIN USERS**: Project-specific administrators limited to their assigned project  
3. **CONSUMER USERS**: End users with RBAC-based permissions through groups

## 🔐 Authentication & Authorization

All endpoints require authentication with specific user type permissions:

```
Authorization: Bearer YOUR_SESSION_TOKEN
```

### Permission Levels
- **Root Only**: Only root users can access these endpoints
- **Root/Admin**: Root users or admin users (with project scope restrictions)
- **Authenticated**: Any authenticated user (with appropriate access controls)

---

## 👑 Root User Management

### POST `/user-types/root`

Create a new root (super admin) user.

**Authentication:** Root users only

**Request Body** (Form):
- `username` (required): Username for the root user
- `password` (required): Password for the root user
- `email` (optional): Email address for the root user

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user-types/root" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_root_admin&password=secure_password_123&email=root@company.com"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Root user 'new_root_admin' created successfully",
  "user": {
    "user_hash": "ROOT123...",
    "username": "new_root_admin",
    "email": "root@company.com",
    "user_type": "root",
    "created_at": "2024-01-01T12:00:00Z"
  }
}
```

**Error Responses:**
- **403**: Non-root user attempting to create root user
- **409**: Username or email already exists

---

## 🛡️ Admin User Management

### POST `/user-types/admin`

Create a new admin user assigned to one or multiple projects.

**Authentication:** Root users only

**Request Body** (Form):
- `username` (required): Username for the admin user
- `password` (required): Password for the admin user
- `email` (required): Email address for the admin user
- `assigned_project_id` (optional): Single project ID for backwards compatibility
- `assigned_project_ids` (optional): List of project IDs to assign (use this for multiple projects)

**Note:** Either `assigned_project_id` or `assigned_project_ids` must be provided.

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user-types/admin" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=project_admin&password=admin_password_123&email=admin@company.com&assigned_project_ids=5&assigned_project_ids=8"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Admin user 'project_admin' created and assigned to 2 project(s)",
  "user": {
    "user_hash": "ADMIN123...",
    "username": "project_admin",
    "email": "admin@company.com",
    "user_type": "admin",
    "assigned_project_ids": [5, 8],
    "assigned_projects": [
      {
        "project_id": 5,
        "project_hash": "PROJ123...",
        "project_name": "API Project"
      },
      {
        "project_id": 8,
        "project_hash": "PROJ456...",
        "project_name": "Mobile App"
      }
    ],
    "primary_project_id": 5,
    "created_at": "2024-01-01T12:00:00Z",
    "created_by": "root_admin"
  }
}
```

**Error Responses:**
- **403**: Non-root user attempting to create admin user
- **404**: Assigned project not found
- **409**: Username or email already exists

---

## 📊 User Type Information

### GET `/user-types/{user_hash}/info`

Get comprehensive user type information and capabilities.

**Authentication:** Root or Admin access (with access controls)

**Path Parameters:**
- `user_hash`: Hash of the user to get information for

**Example Request:**
```bash
curl -X GET "http://localhost:8000/user-types/USER123.../info" \
  -H "Authorization: Bearer SESSION_TOKEN"
```

**Response (200) - Root User:**
```json
{
  "success": true,
  "user_type_info": {
    "user_id": 1,
    "user_hash": "ROOT123...",
    "username": "root_admin",
    "user_type": "root",
    "capabilities": [
      "unrestricted_access",
      "global_admin",
      "create_root_users",
      "manage_all_projects",
      "manage_all_users"
    ]
  }
}
```

**Response (200) - Admin User:**
```json
{
  "success": true,
  "user_type_info": {
    "user_id": 2,
    "user_hash": "ADMIN123...",
    "username": "project_admin",
    "user_type": "admin",
    "assigned_projects": [
        {
            "project_id": 5,
            "project_hash": "PROJ123...",
            "project_name": "API Project",
            "assigned_at": "2024-01-01T12:00:00Z"
        },
        {
            "project_id": 8,
            "project_hash": "PROJ456...",
            "project_name": "Mobile App",
            "assigned_at": "2024-01-01T12:00:00Z"
        }
    ],
    "total_assigned_projects": 2,
    "capabilities": [
      "project_admin",
      "manage_project_users",
      "manage_project_groups",
      "manage_project_permissions"
    ]
  }
}
```

**Response (200) - Consumer User:**
```json
{
  "success": true,
  "user_type_info": {
    "user_id": 3,
    "user_hash": "USER123...",
    "username": "john_doe",
    "user_type": "consumer",
    "capabilities": [
      "rbac_permissions",
      "group_based_access",
      "project_access_via_groups"
    ]
  }
}
```

---

## 🔄 User Type Conversion

### PUT `/user-types/{user_hash}/type`

Update user type (promote/demote users).

**Authentication:** Root users only

**Path Parameters:**
- `user_hash`: Hash of the user to update

**Request Body** (Form):
- `user_type` (required): New user type ('root', 'admin', or 'consumer')
- `assigned_project_id` (optional): Project ID (required when changing to 'admin')

**Example Request - Promote to Admin:**
```bash
curl -X PUT "http://localhost:8000/user-types/USER123.../type" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_type=admin&assigned_project_id=5"
```

**Example Request - Demote to Consumer:**
```bash
curl -X PUT "http://localhost:8000/user-types/USER123.../type" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_type=consumer"
```

**Response (200):**
```json
{
  "success": true,
  "message": "User 'john_doe' type updated to 'admin'",
  "user_type_info": {
    "user_id": 3,
    "user_hash": "USER123...",
    "username": "john_doe",
    "user_type": "admin",
    "assigned_project_id": 5,
    "capabilities": [
      "project_admin",
      "manage_project_users",
      "manage_project_groups",
      "manage_project_permissions"
    ]
  }
}
```

**Validation Rules:**
- **Admin users**: Must have `assigned_project_id`
- **Root/Consumer users**: Cannot have `assigned_project_id`
- **Valid types**: `'root'`, `'admin'`, `'consumer'`

---

## 📂 Admin Multi-Project Management

Admin users can be assigned to multiple projects simultaneously. These endpoints manage multi-project assignments for admin users.

### GET `/user-types/admin/{user_hash}/projects`

Get all project assignments for an admin user.

**Authentication:** Root or Admin (admins can only view their own assignments)

**Path Parameters:**
- `user_hash`: Hash of the admin user

**Example Request:**
```bash
curl -X GET "http://localhost:8000/user-types/admin/ADMIN123.../projects" \
  -H "Authorization: Bearer ROOT_USER_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user": {
    "user_hash": "ADMIN123...",
    "username": "project_admin",
    "user_type": "admin"
  },
  "project_assignments": [
    {
      "project_id": 5,
      "project_hash": "PROJ123...",
      "project_name": "API Project",
      "assigned_at": "2024-01-01T12:00:00Z"
    },
    {
      "project_id": 8,
      "project_hash": "PROJ456...",
      "project_name": "Mobile App",
      "assigned_at": "2024-01-01T12:00:00Z"
    }
  ],
  "summary": {
    "total_projects": 2,
    "primary_project": {
      "project_id": 5,
      "project_hash": "PROJ123...",
      "project_name": "API Project",
      "assigned_at": "2024-01-01T12:00:00Z"
    }
  }
}
```

---

### PUT `/user-types/admin/{user_hash}/projects`

Set or replace all project assignments for an admin user.

**Authentication:** Root users only

**Path Parameters:**
- `user_hash`: Hash of the admin user

**Request Body** (Form):
- `assigned_project_ids` (required): List of project IDs to assign

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/user-types/admin/ADMIN123.../projects" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "assigned_project_ids=5&assigned_project_ids=10"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Admin user 'project_admin' reassigned to 2 project(s)",
  "assignment": {
    "user_hash": "ADMIN123...",
    "username": "project_admin",
    "previous_projects": ["API Project", "Mobile App"],
    "new_projects": [
      {"project_id": 5, "project_hash": "PROJ123...", "project_name": "API Project"},
      {"project_id": 10, "project_hash": "PROJ789...", "project_name": "Data Analytics"}
    ],
    "total_projects": 2,
    "assigned_by": "root_admin"
  }
}
```

---

### POST `/user-types/admin/{user_hash}/projects/add`

Add an admin user to an additional project without removing existing assignments.

**Authentication:** Root users only

**Path Parameters:**
- `user_hash`: Hash of the admin user

**Request Body** (Form):
- `project_id` (required): ID of the project to add

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user-types/admin/ADMIN123.../projects/add" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_id=12"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Admin user 'project_admin' added to project 'New Website'",
  "assignment": {
    "user_hash": "ADMIN123...",
    "username": "project_admin",
    "added_project": {
      "project_id": 12,
      "project_hash": "PROJABC...",
      "project_name": "New Website"
    },
    "total_projects": 3,
    "assigned_by": "root_admin"
  }
}
```

---

### DELETE `/user-types/admin/{user_hash}/projects/{project_id}`

Remove an admin user from a specific project.

**Authentication:** Root users only

**Path Parameters:**
- `user_hash`: Hash of the admin user
- `project_id`: ID of the project to remove assignment from

**Example Request:**
```bash
curl -X DELETE "http://localhost:8000/user-types/admin/ADMIN123.../projects/8" \
  -H "Authorization: Bearer ROOT_USER_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Admin user 'project_admin' removed from project 'Mobile App'",
  "removal": {
    "user_hash": "ADMIN123...",
    "username": "project_admin",
    "removed_project": {
      "project_id": 8,
      "project_hash": "PROJ456...",
      "project_name": "Mobile App"
    },
    "remaining_projects": 2,
    "removed_by": "root_admin"
  }
}
```

**Note:** An admin user must be assigned to at least one project. You cannot remove the last project assignment.

---

### GET `/user-types/stats`

Get user type statistics and distribution.

**Authentication:** Root or Admin access

**Example Request:**
```bash
curl -X GET "http://localhost:8000/user-types/stats" \
  -H "Authorization: Bearer SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "statistics": {
    "total_users": 150,
    "user_types": {
      "root": {
        "count": 3,
        "percentage": 2.0
      },
      "admin": {
        "count": 12,
        "percentage": 8.0
      },
      "consumer": {
        "count": 135,
        "percentage": 90.0
      }
    },
    "system_info": {
      "user_type_system": "3-tier (root, admin, consumer)",
      "access_model": "hierarchical",
      "features": [
        "global-root-access",
        "project-scoped-admin",
        "rbac-consumer-users"
      ]
    },
    "scope": {
      "type": "global_root",
      "access": "unrestricted"
    }
  }
}
```

---

## 👥 User Listing by Type

### GET `/user-types/users/{user_type}`

List users by user type with pagination.

**Authentication:** Root or Admin access

**Path Parameters:**
- `user_type`: Type of users to list (`'root'`, `'admin'`, `'consumer'`)

**Query Parameters:**
- `limit` (optional, default: 50): Number of users to return (max 100)
- `offset` (optional, default: 0): Number of users to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/user-types/users/admin?limit=20&offset=0" \
  -H "Authorization: Bearer SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "users": [
    {
      "user_hash": "ADMIN123...",
      "username": "project_admin_1",
      "email": "admin1@company.com",
      "user_type": "admin",
      "created_at": "2024-01-01T12:00:00Z",
      "is_active": true,
      "assigned_project": {
        "project_id": 5,
        "project_hash": "PROJ123...",
        "project_name": "API Project"
      }
    },
    {
      "user_hash": "ADMIN456...",
      "username": "project_admin_2",
      "email": "admin2@company.com",
      "user_type": "admin",
      "created_at": "2024-01-01T13:00:00Z",
      "is_active": true,
      "assigned_project": {
        "project_id": 8,
        "project_hash": "PROJ456...",
        "project_name": "Mobile App"
      }
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total": 5,
    "has_more": false
  },
  "filter": {
    "user_type": "admin",
    "project_filter": null
  }
}
```

**Access Control:**
- **Root users**: Can list all users of any type
- **Admin users**: Limited to users in their project scope
- **Consumer users**: Can list other consumer users

---

## 🧪 Testing User Type Management

### Complete User Type Flow Test

```bash
#!/bin/bash

# Get root user token (assumes root user exists)
ROOT_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=root_admin&password=root_password&project_hash=PROJECT_HASH" | \
  jq -r '.session_token')

echo "1. Creating admin user..."
ADMIN_RESPONSE=$(curl -s -X POST "http://localhost:8000/user-types/admin" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test_admin&password=admin123&email=test_admin@company.com&assigned_project_ids=1")

echo "Admin Creation Response: $ADMIN_RESPONSE"

ADMIN_HASH=$(echo $ADMIN_RESPONSE | jq -r '.user.user_hash')

echo "2. Getting user type info..."
curl -X GET "http://localhost:8000/user-types/$ADMIN_HASH/info" \
  -H "Authorization: Bearer $ROOT_TOKEN"

echo "3. Creating root user..."
curl -X POST "http://localhost:8000/user-types/root" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=test_root&password=root123&email=test_root@company.com"

echo "4. Listing admin users..."
curl -X GET "http://localhost:8000/user-types/users/admin" \
  -H "Authorization: Bearer $ROOT_TOKEN"

echo "5. Converting user type..."
curl -X PUT "http://localhost:8000/user-types/$ADMIN_HASH/type" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_type=consumer"
```

---
0
## 🛡️ Security Considerations

### Access Control Matrix

| Operation | Root Users | Admin Users | Consumer Users |
|-----------|------------|-------------|----------------|
| **Create Root User** | ✅ Yes | ❌ No | ❌ No |
| **Create Admin User** | ✅ Yes | ❌ No | ❌ No |
| **View Any User Type Info** | ✅ Yes | 🔒 Project Scope | 🔒 Self Only |
| **Update User Types** | ✅ Yes | ❌ No | ❌ No |
| **List Users by Type** | ✅ All | 🔒 Project Scope | 🔒 Limited |

### Security Features

1. **Hierarchical Access Control**: Clear privilege separation between user types
2. **Project Boundary Enforcement**: Admin users limited to their assigned project
3. **Root User Protection**: Only root users can create/modify other root users
4. **Input Validation**: Comprehensive validation of user type assignments
5. **Audit Trail**: All user type changes logged with full context

### Best Practices

1. **Minimal Root Users**: Create only necessary root users
2. **Project-Specific Admins**: Use admin users for project-level administration
3. **Regular Audits**: Review user type assignments periodically
4. **Strong Passwords**: Enforce strong passwords for privileged accounts
5. **Session Management**: Use short session timeouts for privileged users

---

**Next:** Learn about [Authentication API](authentication.md) or explore [Admin API](admin.md) for group management. 