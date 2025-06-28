# API Reference

Complete API documentation for the Enhanced Multi-Project Authentication system.

## 🔐 Authentication

All authenticated endpoints require a session token in the Authorization header:

```
Authorization: Bearer YOUR_SESSION_TOKEN
```

## 📡 Endpoints

### Authentication & User Management

#### POST `/user/login`

Login to a specific project and get a session token.

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
    "user_project_id": 1,
    "user_project_hash": "jkl012..."
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "project_id": 1,
    "project_description": "Project description"
  },
  "access": {
    "groups": ["admin"],
    "permissions": ["admin", "read", "write", "delete", "manage_users", "manage_groups"]
  },
  "available_projects": [
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
  "error": "Invalid credentials or no access to project"
}
```

---

#### POST `/user/register`

Register a new user or grant existing user access to a project.

**Request Body** (form-data):
- `username` (required): Desired username
- `password` (required): User's password
- `project_hash` (required): Project hash to register for
- `email` (optional): User's email address

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user/register" \
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
    "user_id": 2,
    "user_project_id": 2,
    "user_project_hash": "user_project_hash..."
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "project_id": 1
  }
}
```

**Error Response (400):**
```json
{
  "success": false,
  "error": "Username already exists or invalid project"
}
```

---

#### POST `/user/check-availability`

Check if username or email is available.

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

Get current user profile and project information.

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
    "username": "john_doe",
    "email": "john@example.com",
    "created_at": "2024-01-01T00:00:00Z"
  },
  "current_project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "project_description": "Project description",
    "user_project_hash": "jkl012..."
  },
  "access": {
    "groups": ["user"],
    "permissions": ["read", "write"]
  },
  "available_projects": [
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

Switch to a different project the user has access to.

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
  "message": "Switched to project successfully",
  "session_token": "new_session_token...",
  "project": {
    "project_hash": "xyz789...",
    "project_name": "New Project",
    "project_id": 2
  },
  "access": {
    "groups": ["admin"],
    "permissions": ["admin", "read", "write", "delete", "manage_users"]
  }
}
```

---

#### GET `/user/validate`

Validate current session token.

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
    "user_project_id": 1
  },
  "project": {
    "project_hash": "abc123...",
    "project_name": "My Project",
    "project_id": 1
  },
  "permissions": ["read", "write", "admin"]
}
```

---

### Project Management

#### POST `/user/create-project`

Create a new project (requires admin permission).

**Authentication:** Required (admin permission)

**Request Body** (form-data):
- `project_name` (required): Name of the new project
- `project_description` (optional): Description of the project

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user/create-project" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_name=New Project&project_description=A new project for testing"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Project created successfully",
  "project": {
    "project_hash": "new_project_hash...",
    "project_name": "New Project",
    "project_description": "A new project for testing",
    "project_id": 3,
    "created_at": "2024-01-01T00:00:00Z"
  },
  "default_groups": [
    {"group_name": "admin", "permissions": ["admin", "read", "write", "delete", "manage_users", "manage_groups"]},
    {"group_name": "user", "permissions": ["read", "write"]},
    {"group_name": "readonly", "permissions": ["read"]}
  ]
}
```

---

#### GET `/user/projects`

List all projects with pagination and search (requires admin permission).

**Authentication:** Required (admin permission)

**Query Parameters:**
- `limit` (optional, default: 10): Number of projects to return
- `offset` (optional, default: 0): Number of projects to skip
- `search` (optional): Search term for project name or description

**Example Requests:**
```bash
# List first 10 projects
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
      "project_id": 1,
      "created_at": "2024-01-01T00:00:00Z",
      "user_count": 15,
      "group_count": 3
    }
  ],
  "pagination": {
    "total": 25,
    "limit": 10,
    "offset": 0,
    "has_more": true
  }
}
```

---

#### GET `/user/projects/{project_hash}`

Get detailed information about a specific project.

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
    "project_hash": "abc123...",
    "project_name": "Main Project",
    "project_description": "Main application project",
    "project_id": 1,
    "created_at": "2024-01-01T00:00:00Z",
    "updated_at": "2024-01-01T00:00:00Z",
    "is_active": true
  },
  "groups": [
    {
      "group_name": "admin",
      "group_description": "Project administrators",
      "permissions": ["admin", "read", "write", "delete", "manage_users", "manage_groups"],
      "user_count": 2
    },
    {
      "group_name": "user",
      "group_description": "Regular users",
      "permissions": ["read", "write"],
      "user_count": 10
    }
  ],
  "user_access": {
    "groups": ["admin"],
    "permissions": ["admin", "read", "write", "delete", "manage_users", "manage_groups"]
  }
}
```

---

#### PUT `/user/projects/{project_hash}`

Update project name and/or description (requires admin permission for the specific project).

**Authentication:** Required (project admin permission)

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
    "project_hash": "abc123...",
    "project_name": "Updated Project Name",
    "project_description": "Updated description",
    "project_id": 1,
    "updated_at": "2024-01-01T12:00:00Z"
  }
}
```

---

#### DELETE `/user/projects/{project_hash}`

Delete a project and revoke all user access (requires admin permission for the specific project).

**Authentication:** Required (project admin permission)

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
  "message": "Project deleted successfully",
  "affected_users": 15,
  "deleted_sessions": 8
}
```

---

#### GET `/user/projects/{project_hash}/stats`

Get project statistics and analytics (requires admin permission for the specific project).

**Authentication:** Required (project admin permission)

**Path Parameters:**
- `project_hash`: Hash of the project to get stats for

**Example Request:**
```bash
curl -X GET "http://localhost:8000/user/projects/abc123.../stats" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "project": {
    "project_hash": "abc123...",
    "project_name": "Main Project",
    "project_id": 1
  },
  "statistics": {
    "total_users": 15,
    "active_users": 12,
    "total_groups": 3,
    "active_sessions": 8,
    "user_distribution": {
      "admin": 2,
      "user": 10,
      "readonly": 3
    },
    "recent_activity": {
      "logins_last_24h": 25,
      "registrations_last_7d": 3,
      "last_login": "2024-01-01T11:30:00Z"
    }
  }
}
```

---

#### POST `/user/grant-access`

Grant user access to a project (requires admin permission).

**Authentication:** Required (admin permission)

**Request Body** (form-data):
- `username` (required): Username to grant access to
- `target_project_hash` (required): Project hash to grant access to
- `group_name` (optional, default: "user"): Group to assign user to

**Example Request:**
```bash
curl -X POST "http://localhost:8000/user/grant-access" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john_doe&target_project_hash=xyz789...&group_name=user"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Access granted successfully",
  "user": {
    "username": "john_doe",
    "user_hash": "user_hash..."
  },
  "project": {
    "project_name": "Target Project",
    "project_hash": "xyz789..."
  },
  "access": {
    "groups": ["user"],
    "permissions": ["read", "write"]
  }
}
```

---

### Access Control

#### HEAD `/access`

Validate session token and check permissions (used for access control middleware).

**Authentication:** Required

**Example Request:**
```bash
curl -X HEAD "http://localhost:8000/access" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response:**
- **200**: Token is valid
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

## 🔒 Security Notes

1. **Session Tokens**: Expire after 3 days by default
2. **Password Hashing**: Uses SHA256 for compatibility
3. **Rate Limiting**: Implement rate limiting in production
4. **HTTPS**: Always use HTTPS in production
5. **CORS**: Configure CORS settings for your domain

## 📚 SDKs and Integration

### Python SDK Example

```python
import requests

class AuthAPI:
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

# Usage
api = AuthAPI("http://localhost:8000")
login_result = api.login("admin", "admin123", "project_hash")
profile = api.get_profile()
```

### JavaScript SDK Example

```javascript
class AuthAPI {
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
}

// Usage
const api = new AuthAPI('http://localhost:8000');
const loginResult = await api.login('admin', 'admin123', 'project_hash');
const profile = await api.getProfile();
```

---

**📖 For more detailed examples and use cases, see the other documentation files in the `docs/` folder.** 