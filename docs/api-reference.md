# API Reference

Complete API documentation for the Group-Based Multi-Project Authentication system.

## 🔐 Authentication

All authenticated endpoints require a session token in the Authorization header:

```
Authorization: Bearer YOUR_SESSION_TOKEN
```

## 🏗️ System Architecture

The system implements hierarchical group-based access control:

**User → User Group → Projects Access**  
**Project → Project Group → Permissions**

- **Users** belong to **User Groups** (global)
- **User Groups** define which projects users can access  
- **Projects** belong to **Project Groups**
- **Project Groups** define permissions

## 📡 Endpoints

### Authentication (/auth/*)

#### POST `/auth/login`

Group-based login to a specific project.

**Request Body** (form-data):
- `username` (required): User's username
- `password` (required): User's password
- `project_hash` (required): Project hash to login to

**Example Request:**
```bash
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=abc123..."
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Login successful",
  "session_token": "def456...",
  "user": {
    "user_hash": "ghi789...",
    "username": "admin",
    "email": "admin@example.com",
    "user_groups": ["administrators"]
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "permissions": ["admin", "read", "write", "delete", "manage_users"]
  },
  "accessible_projects": [
    {
      "project_hash": "abc123...",
      "project_name": "My Project",
      "project_description": "Project description"
    }
  ],
  "expires_at": "2024-01-04T12:00:00Z"
}
```

**Error Response (401):**
```json
{
  "success": false,
  "detail": "Invalid credentials"
}
```

---

#### POST `/auth/register`

Register a new user and assign them to a user group.

**Request Body** (form-data):
- `username` (required): Desired username
- `password` (required): User's password
- `email` (required): User's email address
- `project_hash` (required): Project hash to register for

**Example Request:**
```bash
curl -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john_doe&password=password123&email=john@example.com&project_hash=abc123..."
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "User registered successfully",
  "user": {
    "user_hash": "new_user_hash...",
    "username": "john_doe",
    "email": "john@example.com",
    "user_groups": []
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project"
  }
}
```

---

#### GET `/auth/validate`

Validate session token and return user information with group context.

**Authentication:** Required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/auth/validate" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "valid": true,
  "user": {
    "user_hash": "ghi789...",
    "username": "admin",
    "email": "admin@example.com",
    "user_groups": ["administrators"]
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "permissions": ["admin", "read", "write", "delete"]
  },
  "session": {
    "expires_at": "2024-01-04T12:00:00Z",
    "created_at": "2024-01-01T12:00:00Z"
  }
}
```

---

#### POST `/auth/logout`

Logout user and invalidate session.

**Authentication:** Required

**Example Request:**
```bash
curl -X POST "http://localhost:8000/auth/logout" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Logged out successfully"
}
```

---

#### POST `/auth/switch-project`

Switch to a different project that the user's group has access to.

**Authentication:** Required

**Request Body** (form-data):
- `project_hash` (required): Hash of the project to switch to

**Example Request:**
```bash
curl -X POST "http://localhost:8000/auth/switch-project" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=xyz789..."
```

**Response (200):**
```json
{
  "success": true,
  "message": "Successfully switched to project: New Project",
  "session_token": "new_session_token...",
  "project": {
    "project_hash": "xyz789...",
    "project_name": "New Project",
    "permissions": ["read", "write"]
  },
  "user_groups": ["users"]
}
```

---

#### POST `/auth/check-availability`

Check if username or email is available globally.

**Request Body** (form-data):
- `username` (optional): Username to check
- `email` (optional): Email to check

**Example Request:**
```bash
curl -X POST "http://localhost:8000/auth/check-availability" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_user&email=new@example.com"
```

**Response (200):**
```json
{
  "success": true,
  "username_available": true,
  "email_available": false
}
```

---

### User Management (/users/*)

#### GET `/users/profile`

Get current user's profile information including groups and project access.

**Authentication:** Required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user": {
    "user_hash": "ghi789...",
    "username": "admin",
    "email": "admin@example.com",
    "created_at": "2024-01-01T00:00:00Z",
    "user_groups": ["administrators"]
  },
  "accessible_projects": [
    {
      "project_hash": "abc123...",
      "project_name": "My Project",
      "project_description": "Project description"
    }
  ],
  "current_project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "permissions": ["admin", "read", "write", "delete"]
  }
}
```

---

#### PUT `/users/profile`

Update current user's profile information.

**Authentication:** Required

**Request Body** (JSON):
```json
{
  "username": "new_username",
  "email": "new_email@example.com",
  "password": "new_password"
}
```

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"username": "john_updated", "email": "john_new@example.com"}'
```

**Response (200):**
```json
{
  "success": true,
  "message": "Profile updated successfully",
  "user": {
    "user_hash": "ghi789...",
    "username": "john_updated",
    "email": "john_new@example.com",
    "updated_at": "2024-01-01T12:00:00Z"
  }
}
```

---

#### GET `/users/access-summary`

Get summary of user's group memberships and project access.

**Authentication:** Required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/users/access-summary" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "access_summary": {
    "user": {
      "user_hash": "ghi789...",
      "username": "admin",
      "email": "admin@example.com"
    },
    "user_groups": [
      {
        "group_name": "administrators",
        "description": "System administrators with full access"
      }
    ],
    "accessible_projects": [
      {
        "project_hash": "abc123...",
        "project_name": "My Project",
        "project_description": "Main project"
      }
    ],
    "current_session": {
      "project_hash": "abc123...",
      "project_name": "My Project",
      "permissions": ["admin", "read", "write", "delete"],
      "expires_at": "2024-01-04T12:00:00Z"
    },
    "summary": {
      "total_groups": 1,
      "total_projects": 5,
      "is_admin": true
    }
  }
}
```

---

### Project Management (/projects/*)

#### GET `/projects`

List projects based on user's access level.

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

#### POST `/projects`

Create new project and assign it to default project group.

**Authentication:** Required (admin permission)

**Request Body** (JSON):
```json
{
  "project_name": "New Project",
  "project_description": "A new project"
}
```

**Example Request:**
```bash
curl -X POST "http://localhost:8000/projects" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_name": "New Project", "project_description": "A new project"}'
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

#### GET `/projects/{project_hash}`

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

#### PUT `/projects/{project_hash}`

Update project information (admin only).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Hash of the project to update

**Request Body** (JSON):
```json
{
  "project_name": "Updated Project Name",
  "project_description": "Updated description"
}
```

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/projects/abc123..." \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_name": "Updated Project Name"}'
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

#### DELETE `/projects/{project_hash}`

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

### Admin - User Groups (/admin/user-groups/*)

#### GET `/admin/user-groups`

List all global user groups (admin only).

**Authentication:** Required (admin permission)

**Query Parameters:**
- `limit` (optional, default: 50): Number of groups to return
- `offset` (optional, default: 0): Number of groups to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/user-groups?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
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

#### POST `/admin/user-groups`

Create a new global user group (admin only).

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
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
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

#### GET `/admin/user-groups/{group_hash}`

Get detailed user group information (admin only).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/user-groups/group123..." \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
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

#### POST `/admin/user-groups/{group_hash}/members`

Assign a user to a user group (admin only).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Request Body** (form-data or JSON):
- `user_hash` (required): User hash to assign

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/group123.../members" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
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

#### POST `/admin/user-groups/{group_hash}/projects`

Grant a user group access to a project (admin only).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Request Body** (form-data or JSON):
- `project_hash` (required): Project hash to grant access to

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/group123.../projects" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
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

### Admin - Project Groups (/admin/project-groups/*)

#### GET `/admin/project-groups`

List all project permission groups (admin only).

**Authentication:** Required (admin permission)

**Query Parameters:**
- `limit` (optional, default: 50): Number of groups to return
- `offset` (optional, default: 0): Number of groups to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/admin/project-groups?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
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

#### POST `/admin/project-groups`

Create a new project permission group (admin only).

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
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
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

#### POST `/admin/project-groups/{group_hash}/projects`

Assign a project to a project group (admin only).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: Project group identifier

**Request Body** (form-data or JSON):
- `project_hash` (required): Project hash to assign

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/project-groups/projgroup123.../projects" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
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

### System Information (/system/*)

#### GET `/system/info`

Get system information and health status.

**Example Request:**
```bash
curl -X GET "http://localhost:8000/system/info"
```

**Response (200):**
```json
{
  "success": true,
  "system": {
    "name": "Group-Based Multi-Project Authentication API",
    "version": "2.0.0",
    "architecture": "hierarchical-group-based",
    "status": "operational"
  },
  "statistics": {
    "total_users": 150,
    "total_projects": 25,
    "total_user_groups": 10,
    "total_project_groups": 5,
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

---

#### GET `/system/health`

Comprehensive system health check.

**Example Request:**
```bash
curl -X GET "http://localhost:8000/system/health"
```

**Response (200):**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00Z",
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
      "message": "Group system operational: 10 user groups, 5 project groups"
    }
  }
}
```

---

#### GET `/system/ping`

Simple health check endpoint.

**Example Request:**
```bash
curl -X GET "http://localhost:8000/system/ping"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Group-based authentication API is running",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

---

### Access Control (/access)

#### HEAD `/access`

Validate session token and check permissions (middleware endpoint).

**Authentication:** Required

**Example Request:**
```bash
curl -X HEAD "http://localhost:8000/access" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response:**
- **204**: Token is valid and has required permissions
- **401**: Token is invalid or expired
- **403**: Token valid but insufficient permissions

---

## 🔧 Error Responses

### Common Error Codes

- **400 Bad Request**: Invalid request parameters
- **401 Unauthorized**: Invalid or missing authentication token
- **403 Forbidden**: Valid token but insufficient permissions
- **404 Not Found**: Resource not found
- **409 Conflict**: Resource already exists
- **422 Unprocessable Entity**: Invalid request format
- **500 Internal Server Error**: Server error

### Error Response Format

```json
{
  "detail": "Error description"
}
```

## 📊 Response Headers

All responses include:
- `X-Process-Time`: Request processing time in seconds
- `Access-Control-Allow-Origin`: CORS header
- `Content-Type`: Response content type

## 🏗️ Group-Based System Benefits

### User Groups (Global)
- **administrators**: Full system access across all projects
- **users**: Standard access to assigned projects
- **guests**: Limited read-only access

### Project Groups (Permission Sets)
- **full-access**: Complete project control (admin, read, write, delete)
- **read-write**: Standard user permissions (read, write, create)
- **read-only**: View-only access (read, view)

### Access Flow
1. **User** logs in with global credentials
2. **User Group** determines which projects they can access
3. **Project Group** determines what permissions they have
4. **Session** maintains context for both user and project groups

## 🔒 Security Notes

1. **Session Tokens**: Expire after 3 days by default
2. **Group-Based Access**: Centralized permission management
3. **Project Isolation**: Users only see projects their groups access
4. **Audit Trail**: Complete tracking of group assignments and access
5. **HTTPS**: Always use HTTPS in production
6. **CORS**: Configure CORS settings for your domain

## 📚 SDKs and Integration

### Python SDK Example

```python
import requests

class GroupAuthAPI:
    def __init__(self, base_url):
        self.base_url = base_url
        self.session_token = None
    
    def login(self, username, password, project_hash):
        response = requests.post(f"{self.base_url}/auth/login", data={
            "username": username,
            "password": password,
            "project_hash": project_hash
        })
        
        if response.status_code == 200:
            data = response.json()
            self.session_token = data["session_token"]
            return data
        else:
            raise Exception(f"Login failed: {response.text}")
    
    def get_profile(self):
        if not self.session_token:
            raise Exception("Not authenticated")
        
        response = requests.get(
            f"{self.base_url}/users/profile",
            headers={"Authorization": f"Bearer {self.session_token}"}
        )
        
        return response.json()
    
    def switch_project(self, project_hash):
        if not self.session_token:
            raise Exception("Not authenticated")
        
        response = requests.post(
            f"{self.base_url}/auth/switch-project",
            headers={"Authorization": f"Bearer {self.session_token}"},
            data={"project_hash": project_hash}
        )
        
        if response.status_code == 200:
            data = response.json()
            self.session_token = data["session_token"]
            return data
        else:
            raise Exception(f"Project switch failed: {response.text}")

# Usage
api = GroupAuthAPI("http://localhost:8000")
login_result = api.login("admin", "admin123", "project_hash")
profile = api.get_profile()
api.switch_project("another_project_hash")
```

### JavaScript SDK Example

```javascript
class GroupAuthAPI {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
        this.sessionToken = null;
    }
    
    async login(username, password, projectHash) {
        const response = await fetch(`${this.baseUrl}/auth/login`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
            },
            body: new URLSearchParams({
                username,
                password,
                project_hash: projectHash
            })
        });
        
        if (response.ok) {
            const data = await response.json();
            this.sessionToken = data.session_token;
            return data;
        } else {
            throw new Error(`Login failed: ${await response.text()}`);
        }
    }
    
    async getProfile() {
        if (!this.sessionToken) {
            throw new Error('Not authenticated');
        }
        
        const response = await fetch(`${this.baseUrl}/users/profile`, {
            headers: {
                'Authorization': `Bearer ${this.sessionToken}`
            }
        });
        
        return await response.json();
    }
    
    async getAccessSummary() {
        if (!this.sessionToken) {
            throw new Error('Not authenticated');
        }
        
        const response = await fetch(`${this.baseUrl}/users/access-summary`, {
            headers: {
                'Authorization': `Bearer ${this.sessionToken}`
            }
        });
        
        return await response.json();
    }
}

// Usage
const api = new GroupAuthAPI('http://localhost:8000');
const loginResult = await api.login('admin', 'admin123', 'project_hash');
const profile = await api.getProfile();
const accessSummary = await api.getAccessSummary();
```

---

**📖 For implementation examples and system setup, see the other documentation files in the `docs/` folder.** 