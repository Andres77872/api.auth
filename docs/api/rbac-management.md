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

## 📚 SDK Examples

### Python RBAC SDK

```python
import requests

class RBACAPI:
    def __init__(self, base_url, session_token):
        self.base_url = base_url
        self.session_token = session_token
        self.headers = {"Authorization": f"Bearer {session_token}"}
    
    # Permission Management
    def list_project_permissions(self, project_hash, category=None, limit=50, offset=0):
        """List permissions for a project"""
        params = {"limit": limit, "offset": offset}
        if category:
            params["category"] = category
        
        response = requests.get(
            f"{self.base_url}/rbac/projects/{project_hash}/permissions",
            headers=self.headers,
            params=params
        )
        return response.json()
    
    def create_permission(self, project_hash, permission_name, category="general", description=None):
        """Create a new permission"""
        response = requests.post(
            f"{self.base_url}/rbac/projects/{project_hash}/permissions",
            headers={**self.headers, "Content-Type": "application/json"},
            json={
                "permission_name": permission_name,
                "category": category,
                "description": description
            }
        )
        return response.json()
    
    # Role Management
    def list_project_roles(self, project_hash, limit=50, offset=0):
        """List roles for a project"""
        response = requests.get(
            f"{self.base_url}/rbac/projects/{project_hash}/roles",
            headers=self.headers,
            params={"limit": limit, "offset": offset}
        )
        return response.json()
    
    def create_role(self, project_hash, group_name, priority=50, description=None, permissions=None):
        """Create a new role"""
        response = requests.post(
            f"{self.base_url}/rbac/projects/{project_hash}/roles",
            headers={**self.headers, "Content-Type": "application/json"},
            json={
                "group_name": group_name,
                "priority": priority,
                "description": description,
                "permissions": permissions or []
            }
        )
        return response.json()
    
    # User Role Assignments
    def assign_user_to_role(self, user_hash, project_hash, role_id):
        """Assign user to role"""
        response = requests.post(
            f"{self.base_url}/rbac/users/{user_hash}/projects/{project_hash}/roles",
            headers=self.headers,
            data={"role_id": role_id}
        )
        return response.json()
    
    def get_user_roles(self, user_hash, project_hash):
        """Get user's roles in project"""
        response = requests.get(
            f"{self.base_url}/rbac/users/{user_hash}/projects/{project_hash}/roles",
            headers=self.headers
        )
        return response.json()
    
    def get_user_permissions(self, user_hash, project_hash):
        """Get user's effective permissions"""
        response = requests.get(
            f"{self.base_url}/rbac/users/{user_hash}/projects/{project_hash}/permissions",
            headers=self.headers
        )
        return response.json()
    
    def check_user_permission(self, user_hash, project_hash, permission_name):
        """Check specific permission"""
        response = requests.get(
            f"{self.base_url}/rbac/users/{user_hash}/projects/{project_hash}/check/{permission_name}",
            headers=self.headers
        )
        return response.json()
    
    # RBAC Administration
    def initialize_rbac(self, project_hash, create_defaults=True, create_roles=True):
        """Initialize RBAC for project"""
        response = requests.post(
            f"{self.base_url}/rbac/projects/{project_hash}/initialize",
            headers=self.headers,
            params={
                "create_default_permissions": create_defaults,
                "create_default_roles": create_roles
            }
        )
        return response.json()
    
    def get_audit_log(self, project_hash, action_type=None, limit=50, offset=0):
        """Get audit log"""
        params = {"limit": limit, "offset": offset}
        if action_type:
            params["action_type"] = action_type
        
        response = requests.get(
            f"{self.base_url}/rbac/projects/{project_hash}/audit",
            headers=self.headers,
            params=params
        )
        return response.json()
    
    def get_rbac_summary(self, project_hash):
        """Get RBAC summary"""
        response = requests.get(
            f"{self.base_url}/rbac/projects/{project_hash}/summary",
            headers=self.headers
        )
        return response.json()

# Usage
rbac_api = RBACAPI("http://localhost:8000", "session_token")

# Initialize RBAC for a project
init_result = rbac_api.initialize_rbac("project_hash")

# Create custom permission
permission = rbac_api.create_permission(
    "project_hash", 
    "export_reports", 
    "data", 
    "Can export system reports"
)

# Create custom role
role = rbac_api.create_role(
    "project_hash",
    "report_manager",
    70,
    "Report management role",
    ["read", "export_reports"]
)

# Assign user to role
assignment = rbac_api.assign_user_to_role("user_hash", "project_hash", role["role"]["id"])

# Check permissions
permissions = rbac_api.get_user_permissions("user_hash", "project_hash")
```

### JavaScript RBAC SDK

```javascript
class RBACAPI {
    constructor(baseUrl, sessionToken) {
        this.baseUrl = baseUrl;
        this.sessionToken = sessionToken;
        this.headers = {
            'Authorization': `Bearer ${sessionToken}`
        };
    }
    
    // Permission Management
    async listProjectPermissions(projectHash, category = null, limit = 50, offset = 0) {
        const params = new URLSearchParams({ limit, offset });
        if (category) params.append('category', category);
        
        const response = await fetch(`${this.baseUrl}/rbac/projects/${projectHash}/permissions?${params}`, {
            headers: this.headers
        });
        return await response.json();
    }
    
    async createPermission(projectHash, permissionName, category = 'general', description = null) {
        const response = await fetch(`${this.baseUrl}/rbac/projects/${projectHash}/permissions`, {
            method: 'POST',
            headers: {
                ...this.headers,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                permission_name: permissionName,
                category: category,
                description: description
            })
        });
        return await response.json();
    }
    
    // Role Management
    async listProjectRoles(projectHash, limit = 50, offset = 0) {
        const params = new URLSearchParams({ limit, offset });
        const response = await fetch(`${this.baseUrl}/rbac/projects/${projectHash}/roles?${params}`, {
            headers: this.headers
        });
        return await response.json();
    }
    
    async createRole(projectHash, groupName, priority = 50, description = null, permissions = []) {
        const response = await fetch(`${this.baseUrl}/rbac/projects/${projectHash}/roles`, {
            method: 'POST',
            headers: {
                ...this.headers,
                'Content-Type': 'application/json'
            },
            body: JSON.stringify({
                group_name: groupName,
                priority: priority,
                description: description,
                permissions: permissions
            })
        });
        return await response.json();
    }
    
    // User Role Assignments
    async assignUserToRole(userHash, projectHash, roleId) {
        const response = await fetch(`${this.baseUrl}/rbac/users/${userHash}/projects/${projectHash}/roles`, {
            method: 'POST',
            headers: {
                ...this.headers,
                'Content-Type': 'application/x-www-form-urlencoded'
            },
            body: new URLSearchParams({ role_id: roleId })
        });
        return await response.json();
    }
    
    async getUserRoles(userHash, projectHash) {
        const response = await fetch(`${this.baseUrl}/rbac/users/${userHash}/projects/${projectHash}/roles`, {
            headers: this.headers
        });
        return await response.json();
    }
    
    async getUserPermissions(userHash, projectHash) {
        const response = await fetch(`${this.baseUrl}/rbac/users/${userHash}/projects/${projectHash}/permissions`, {
            headers: this.headers
        });
        return await response.json();
    }
    
    async checkUserPermission(userHash, projectHash, permissionName) {
        const response = await fetch(`${this.baseUrl}/rbac/users/${userHash}/projects/${projectHash}/check/${permissionName}`, {
            headers: this.headers
        });
        return await response.json();
    }
    
    // RBAC Administration
    async initializeRBAC(projectHash, createDefaults = true, createRoles = true) {
        const params = new URLSearchParams({
            create_default_permissions: createDefaults,
            create_default_roles: createRoles
        });
        
        const response = await fetch(`${this.baseUrl}/rbac/projects/${projectHash}/initialize?${params}`, {
            method: 'POST',
            headers: this.headers
        });
        return await response.json();
    }
    
    async getAuditLog(projectHash, actionType = null, limit = 50, offset = 0) {
        const params = new URLSearchParams({ limit, offset });
        if (actionType) params.append('action_type', actionType);
        
        const response = await fetch(`${this.baseUrl}/rbac/projects/${projectHash}/audit?${params}`, {
            headers: this.headers
        });
        return await response.json();
    }
    
    async getRBACSummary(projectHash) {
        const response = await fetch(`${this.baseUrl}/rbac/projects/${projectHash}/summary`, {
            headers: this.headers
        });
        return await response.json();
    }
}

// Usage
const rbacAPI = new RBACAPI('http://localhost:8000', 'session_token');

// Initialize RBAC for a project
const initResult = await rbacAPI.initializeRBAC('project_hash');

// Create custom permission
const permission = await rbacAPI.createPermission(
    'project_hash',
    'export_reports',
    'data',
    'Can export system reports'
);

// Create custom role
const role = await rbacAPI.createRole(
    'project_hash',
    'report_manager',
    70,
    'Report management role',
    ['read', 'export_reports']
);

// Assign user to role
const assignment = await rbacAPI.assignUserToRole('user_hash', 'project_hash', role.role.id);

// Check permissions
const permissions = await rbacAPI.getUserPermissions('user_hash', 'project_hash');
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