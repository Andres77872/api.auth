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

### Authentication & User Management

#### POST `/user/login`

Group-based login to a specific project.

**Request Body** (form-data):
- `username` (required): User's username
- `password` (required): User's password
- `project_hash` (required): Project hash to login to

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=abc123..."
```

**Success Response (200):**
```json
{
  "success": true,
  "session_token": "def456...",
  "user": {
    "user_hash": "ghi789...",
    "user_id": 1,
    "user_group": {
      "name": "administrators",
      "id": 1
    }
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "project_id": 1,
    "project_group": "full-access",
    "permissions": ["admin", "read", "write", "delete", "manage_users"]
  },
  "accessible_projects": [
    {
      "project_hash": "abc123...",
      "project_name": "My Project",
      "project_description": "Project description"
    }
  ]
}
```

**Error Response (401):**
```json
{
  "success": false,
  "error": "Invalid credentials or user group does not have access to this project"
}
```

---

#### POST `/user/register`

Register a new user and assign them to a user group.

**Request Body** (form-data):
- `username` (required): Desired username
- `password` (required): User's password
- `project_hash` (required): Project hash to register for
- `email` (optional): User's email address
- `user_group` (optional, default: "users"): User group to assign to

**User Groups:**
- `administrators`: Full system access
- `users`: Standard user access (default)
- `guests`: Limited read-only access

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user/register" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john_doe&password=password123&email=john@example.com&project_hash=abc123...&user_group=users"
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "User registered and assigned to user group successfully",
  "session_token": "new_session_token...",
  "user": {
    "user_hash": "new_user_hash...",
    "user_id": 2,
    "user_group": {
      "name": "users",
      "assigned_at": "now"
    }
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "project_id": 1,
    "access_granted_through": "users group"
  }
}
```

---

#### POST `/user/check-availability`

Check if username or email is available globally.

**Request Body** (form-data):
- `username` (optional): Username to check
- `email` (optional): Email to check

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user/check-availability" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_user&email=new@example.com"
```

**Response (200):**
```json
{
  "username_available": true,
  "email_available": false,
  "message": "Username is available, email is already taken"
}
```

---

#### GET `/user/profile`

Get comprehensive user profile with group information.

**Authentication:** Required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/user/profile" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "user": {
    "user_hash": "ghi789...",
    "user_id": 1,
    "user_groups": ["administrators"]
  },
  "current_project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "project_id": 1,
    "permissions": ["admin", "read", "write", "delete"],
    "access_level": "admin"
  },
  "accessible_projects": [
    {
      "project_hash": "abc123...",
      "project_name": "My Project",
      "project_description": "Project description"
    }
  ]
}
```

---

#### POST `/user/switch-project`

Switch to a different project the user's group has access to.

**Authentication:** Required

**Request Body** (form-data):
- `project_hash` (required): Hash of the project to switch to

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user/switch-project" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=xyz789..."
```

**Response (200):**
```json
{
  "success": true,
  "session_token": "new_session_token...",
  "project": {
    "project_hash": "xyz789...",
    "project_name": "New Project",
    "project_id": 2,
    "permissions": ["read", "write"]
  },
  "user_groups": ["users"],
  "message": "Successfully switched to project: New Project"
}
```

---

#### GET `/user/validate`

Validate current session token and return context.

**Authentication:** Required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/user/validate" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "valid": true,
  "user": {
    "user_hash": "ghi789...",
    "user_id": 1,
    "user_groups": ["administrators"]
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "project_id": 1
  },
  "permissions": ["admin", "read", "write", "delete"],
  "session_info": {
    "token_valid": true,
    "access_level": "admin"
  }
}
```

---

### Project Management

#### POST `/user/create-project`

Create a new project and assign it to a project group.

**Authentication:** Required (admin permission)

**Request Body** (form-data):
- `project_name` (required): Name of the new project
- `project_description` (optional): Description of the project
- `project_group` (optional, default: "full-access"): Project group for permissions

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user/create-project" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_name=New Project&project_description=A new project&project_group=full-access"
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
    "project_id": 3,
    "project_group": "full-access",
    "creator_permissions": ["admin", "read", "write", "delete"]
  }
}
```

---

#### GET `/user/projects`

List projects based on user's access level.

**Authentication:** Required

**Query Parameters:**
- `limit` (optional, default: 10): Number of projects to return
- `offset` (optional, default: 0): Number of projects to skip
- `search` (optional): Search term for project name or description

**Access Levels:**
- **Admin users**: See all projects in the system
- **Regular users**: See only projects their user group has access to

**Example Requests:**
```bash
# List projects (admin sees all, users see accessible only)
curl -X GET "http://localhost:8000/user/projects?limit=10&offset=0" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"

# Search projects
curl -X GET "http://localhost:8000/user/projects?search=api&limit=5" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
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

#### GET `/user/projects/{project_hash}`

Get detailed project information with user's access context.

**Authentication:** Required (must have access to the project)

**Path Parameters:**
- `project_hash`: Hash of the project to retrieve

**Example Request:**
```bash
curl -X GET "http://localhost:8000/user/projects/abc123..." \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
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
    "total_groups": 3,
    "description": "Project usage and access statistics"
  }
}
```

---

#### PUT `/user/projects/{project_hash}`

Update project information (admin only).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Hash of the project to update

**Request Body** (form-data):
- `project_name` (optional): New project name
- `project_description` (optional): New project description

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/user/projects/abc123..." \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_name=Updated Project Name&project_description=Updated description"
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

#### DELETE `/user/projects/{project_hash}`

Delete a project and revoke all user group access (admin only).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Hash of the project to delete

**Example Request:**
```bash
curl -X DELETE "http://localhost:8000/user/projects/abc123..." \
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

### Access Management

#### POST `/user/grant-access`

Grant a user group access to a project (admin only).

**Authentication:** Required (admin permission)

**Request Body** (form-data):
- `user_group_name` (required): Name of user group to grant access
- `project_hash` (required): Project hash to grant access to

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user/grant-access" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_group_name=developers&project_hash=xyz789..."
```

**Response (200):**
```json
{
  "success": true,
  "message": "User group \"developers\" granted access to project \"Target Project\"",
  "access_details": {
    "user_group": "developers",
    "project": {
      "project_hash": "xyz789...",
      "project_name": "Target Project"
    },
    "granted_by": 1
  }
}
```

---

#### GET `/user/access-summary`

Get comprehensive access summary for the current user.

**Authentication:** Required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/user/access-summary" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "user_info": {
    "user_hash": "ghi789...",
    "user_id": 1,
    "user_groups": ["administrators"]
  },
  "current_session": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "permissions": ["admin", "read", "write", "delete"]
  },
  "accessible_projects": [
    {
      "project_hash": "abc123...",
      "project_name": "My Project",
      "project_description": "Project description"
    }
  ],
  "access_summary": {
    "total_projects": 5,
    "admin_access": true,
    "primary_user_group": "administrators"
  }
}
```

---

### Access Control

#### HEAD `/access`

Validate session token and check permissions (middleware endpoint).

**Authentication:** Required

**Example Request:**
```bash
curl -X HEAD "http://localhost:8000/access" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response:**
- **200**: Token is valid and has required permissions
- **401**: Token is invalid or expired
- **403**: Token valid but insufficient permissions

---

## 🔧 Error Responses

### Common Error Codes

- **400 Bad Request**: Invalid request parameters
- **401 Unauthorized**: Invalid or missing authentication token
- **403 Forbidden**: Valid token but insufficient permissions
- **404 Not Found**: Resource not found
- **422 Unprocessable Entity**: Invalid request format
- **500 Internal Server Error**: Server error

### Error Response Format

```json
{
  "success": false,
  "error": "Error description",
  "details": "Additional error details (optional)",
  "code": "ERROR_CODE (optional)"
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
        response = requests.post(f"{self.base_url}/user/login", data={
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
            f"{self.base_url}/user/profile",
            headers={"Authorization": f"Bearer {self.session_token}"}
        )
        
        return response.json()
    
    def switch_project(self, project_hash):
        if not self.session_token:
            raise Exception("Not authenticated")
        
        response = requests.post(
            f"{self.base_url}/user/switch-project",
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
        const response = await fetch(`${this.baseUrl}/user/login`, {
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
        
        const response = await fetch(`${this.baseUrl}/user/profile`, {
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
        
        const response = await fetch(`${this.baseUrl}/user/access-summary`, {
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