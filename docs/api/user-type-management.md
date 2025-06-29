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

**Request Body** (JSON):
```json
{
  "username": "new_root_admin",
  "password": "secure_password_123",
  "email": "root@company.com"
}
```

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user-types/root" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "new_root_admin",
    "password": "secure_password_123",
    "email": "root@company.com"
  }'
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

**Request Body** (JSON):
```json
{
  "username": "project_admin",
  "password": "admin_password_123",
  "email": "admin@company.com",
  "assigned_project_ids": [5, 8]
}
```

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user-types/admin" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "project_admin",
    "password": "admin_password_123", 
    "email": "admin@company.com",
    "assigned_project_ids": [5, 8]
  }'
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
    "created_at": "2024-01-01T12:00:00Z"
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

**Authentication:** Authenticated (with access controls)

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

**Request Body** (JSON):
```json
{
  "user_type": "admin",
  "assigned_project_id": 5
}
```

**Example Request - Promote to Admin:**
```bash
curl -X PUT "http://localhost:8000/user-types/USER123.../type" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_type": "admin",
    "assigned_project_id": 5
  }'
```

**Example Request - Demote to Consumer:**
```bash
curl -X PUT "http://localhost:8000/user-types/USER123.../type" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_type": "consumer"
  }'
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

### PUT `/user-types/admin/{user_hash}/project`

Update an admin user's primary project assignment. This is a legacy endpoint for single-project assignment. For multi-project assignments, use the `/user-types/admin/{user_hash}/projects` endpoint.

**Authentication:** Root users only

**Path Parameters:**
- `user_hash`: Hash of the admin user to update

**Request Body** (JSON):
```json
{
  "assigned_project_id": 10
}
```

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/user-types/admin/ADMIN123.../project" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"assigned_project_id": 10}'
```

**Response (200):**
```json
{
  "success": true,
  "message": "Admin user 'project_admin' reassigned to project 'New Project Name'",
  "assignment": {
    "user_hash": "ADMIN123...",
    "username": "project_admin",
    "previous_project": "Old Project Name",
    "new_project": "New Project Name",
    "new_project_id": 10,
    "new_project_hash": "PROJXYZ...",
    "assigned_by": "root_admin"
  }
}
```

---

## 📂 Admin Multi-Project Management

Manage project assignments for admin users.

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
    "total_projects": 2
  }
}
```

---

### PUT `/user-types/admin/{user_hash}/projects`

Set or replace all project assignments for an admin user.

**Authentication:** Root users only

**Path Parameters:**
- `user_hash`: Hash of the admin user

**Request Body** (JSON):
```json
{
  "assigned_project_ids": [5, 10]
}
```

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/user-types/admin/ADMIN123.../projects" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"assigned_project_ids": [5, 10]}'
```

**Response (200):**
```json
{
  "success": true,
  "message": "Admin user 'project_admin' reassigned to 2 project(s)",
  "assignment": {
    "user_hash": "ADMIN123...",
    "username": "project_admin",
    "new_projects": [
      {"project_id": 5, "project_hash": "PROJ123...", "project_name": "API Project"},
      {"project_id": 10, "project_hash": "PROJ789...", "project_name": "Data Analytics"}
    ],
    "total_projects": 2
  }
}
```

---

### POST `/user-types/admin/{user_hash}/projects/add`

Add an admin user to an additional project.

**Authentication:** Root users only

**Path Parameters:**
- `user_hash`: Hash of the admin user

**Request Body** (JSON):
```json
{
  "project_id": 12
}
```

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user-types/admin/ADMIN123.../projects/add" \
  -H "Authorization: Bearer ROOT_USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_id": 12}'
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
    "total_projects": 3
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
    "remaining_projects": 2
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

**Authentication:** Authenticated

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
  -H "Content-Type: application/json" \
  -d '{
    "username": "test_admin",
    "password": "admin123",
    "email": "test_admin@company.com",
    "assigned_project_ids": [1]
  }')

echo "Admin Creation Response: $ADMIN_RESPONSE"

ADMIN_HASH=$(echo $ADMIN_RESPONSE | jq -r '.user.user_hash')

echo "2. Getting user type info..."
curl -X GET "http://localhost:8000/user-types/$ADMIN_HASH/info" \
  -H "Authorization: Bearer $ROOT_TOKEN"

echo "3. Creating root user..."
curl -X POST "http://localhost:8000/user-types/root" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "test_root",
    "password": "root123", 
    "email": "test_root@company.com"
  }'

echo "4. Listing admin users..."
curl -X GET "http://localhost:8000/user-types/users/admin" \
  -H "Authorization: Bearer $ROOT_TOKEN"

echo "5. Converting user type..."
curl -X PUT "http://localhost:8000/user-types/$ADMIN_HASH/type" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_type": "consumer"
  }'
```

---

## 📚 SDK Examples

### Python SDK for User Type Management

```python
import requests

class UserTypeAPI:
    def __init__(self, base_url, root_session_token):
        self.base_url = base_url
        self.session_token = root_session_token
        self.headers = {"Authorization": f"Bearer {session_token}"}
    
    def create_root_user(self, username, password, email=None):
        """Create a new root user (root users only)"""
        response = requests.post(
            f"{self.base_url}/user-types/root",
            headers={**self.headers, "Content-Type": "application/json"},
            json={
                "username": username,
                "password": password,
                "email": email
            }
        )
        return response.json()
    
    def create_admin_user(self, username, password, email, assigned_project_ids):
        """Create a new admin user assigned to multiple projects (root users only)"""
        response = requests.post(
            f"{self.base_url}/user-types/admin",
            headers={**self.headers, "Content-Type": "application/json"},
            json={
                "username": username,
                "password": password,
                "email": email,
                "assigned_project_ids": assigned_project_ids
            }
        )
        return response.json()
    
    def get_user_type_info(self, user_hash):
        """Get comprehensive user type information"""
        response = requests.get(
            f"{self.base_url}/user-types/{user_hash}/info",
            headers=self.headers
        )
        return response.json()
    
    def update_user_type(self, user_hash, new_user_type, assigned_project_id=None):
        """Update user type (promote/demote users)"""
        payload = {"user_type": new_user_type}
        if assigned_project_id:
            payload["assigned_project_id"] = assigned_project_id
        
        response = requests.put(
            f"{self.base_url}/user-types/{user_hash}/type",
            headers={**self.headers, "Content-Type": "application/json"},
            json=payload
        )
        return response.json()
    
    def list_users_by_type(self, user_type, limit=50, offset=0):
        """List users by user type"""
        response = requests.get(
            f"{self.base_url}/user-types/users/{user_type}",
            headers=self.headers,
            params={"limit": limit, "offset": offset}
        )
        return response.json()

# Usage
user_type_api = UserTypeAPI("http://localhost:8000", "root_session_token")

# Create admin user
admin_user = user_type_api.create_admin_user(
    "project_admin",
    "secure_password",
    "admin@company.com",
    [5, 8]  # project_ids
)

# Get user type info
user_info = user_type_api.get_user_type_info(admin_user["user"]["user_hash"])

# Promote consumer to admin
user_type_api.update_user_type(
    "CONSUMER_USER_HASH",
    "admin",
    assigned_project_id=5
)

# List all admin users
admin_users = user_type_api.list_users_by_type("admin")
```

### JavaScript SDK for User Type Management

```javascript
class UserTypeAPI {
    constructor(baseUrl, rootSessionToken) {
        this.baseUrl = baseUrl;
        this.sessionToken = rootSessionToken;
        this.headers = {
            'Authorization': `Bearer ${rootSessionToken}`,
            'Content-Type': 'application/json'
        };
    }
    
    async createRootUser(username, password, email = null) {
        const response = await fetch(`${this.baseUrl}/user-types/root`, {
            method: 'POST',
            headers: this.headers,
            body: JSON.stringify({
                username,
                password,
                email
            })
        });
        return await response.json();
    }
    
    async createAdminUser(username, password, email, assignedProjectIds) {
        const response = await fetch(`${this.baseUrl}/user-types/admin`, {
            method: 'POST',
            headers: this.headers,
            body: JSON.stringify({
                username,
                password,
                email,
                assigned_project_ids: assignedProjectIds
            })
        });
        return await response.json();
    }
    
    async getUserTypeInfo(userHash) {
        const response = await fetch(`${this.baseUrl}/user-types/${userHash}/info`, {
            headers: this.headers
        });
        return await response.json();
    }
    
    async updateUserType(userHash, newUserType, assignedProjectId = null) {
        const payload = { user_type: newUserType };
        if (assignedProjectId) {
            payload.assigned_project_id = assignedProjectId;
        }
        
        const response = await fetch(`${this.baseUrl}/user-types/${userHash}/type`, {
            method: 'PUT',
            headers: this.headers,
            body: JSON.stringify(payload)
        });
        return await response.json();
    }
    
    async listUsersByType(userType, limit = 50, offset = 0) {
        const params = new URLSearchParams({ limit, offset });
        const response = await fetch(`${this.baseUrl}/user-types/users/${userType}?${params}`, {
            headers: this.headers
        });
        return await response.json();
    }
}

// Usage
const userTypeAPI = new UserTypeAPI('http://localhost:8000', 'root_session_token');

// Create admin user
const adminUser = await userTypeAPI.createAdminUser(
    'project_admin',
    'secure_password',
    'admin@company.com',
    [5, 8]  // project_ids
);

// Get user type info
const userInfo = await userTypeAPI.getUserTypeInfo(adminUser.user.user_hash);

// Promote consumer to admin
await userTypeAPI.updateUserType(
    'CONSUMER_USER_HASH',
    'admin',
    5  // assigned_project_id
);

// List all admin users
const adminUsers = await userTypeAPI.listUsersByType('admin');
```

---

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