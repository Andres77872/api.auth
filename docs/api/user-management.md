# User Management API

Complete user management documentation for retrieving and updating user profiles, and viewing access summaries.

## 🔐 Authentication Required

All endpoints require authentication:

```
Authorization: Bearer YOUR_SESSION_TOKEN
```

---

## 👤 User Profile

### GET `/users/profile`

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
    "user_hash": "USER123...",
    "username": "john_doe",
    "email": "john.doe@example.com",
    "created_at": "2024-01-01T12:00:00Z",
    "user_groups": ["developers", "api_users"]
  },
  "accessible_projects": [
    {
      "project_hash": "PROJ123...",
      "project_name": "API Project",
      "project_description": "Main API Project",
      "project_group_name": "api-access",
      "permissions": ["read", "write"]
    }
  ],
  "current_project": {
    "project_hash": "PROJ123...",
    "project_name": "API Project",
    "permissions": ["read", "write"]
  }
}
```

---

### PUT `/users/profile`

Update current user's profile information.

**Authentication:** Required

**Request Body** (JSON):
```json
{
  "username": "john_doe_updated",
  "email": "john.doe.new@example.com",
  "password": "new_secure_password"
}
```

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "username": "john_doe_updated",
    "email": "john.doe.new@example.com",
    "password": "new_secure_password"
  }'
```

**Response (200):**
```json
{
  "success": true,
  "message": "Profile updated successfully",
  "user": {
    "user_hash": "USER123...",
    "username": "john_doe_updated",
    "email": "john.doe.new@example.com",
    "updated_at": "2024-01-02T10:00:00Z"
  }
}
```

---

## 📊 User Access Summary

### GET `/users/access-summary`

Get a summary of the current user's group memberships and project access.

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
      "user_hash": "USER123...",
      "username": "john_doe",
      "email": "john.doe@example.com"
    },
    "user_groups": [
      {
        "group_name": "developers",
        "description": "Software development team"
      }
    ],
    "accessible_projects": [
      {
        "project_hash": "PROJ123...",
        "project_name": "API Project",
        "project_description": "Main API Project",
        "project_group_name": "api-access",
        "permissions": ["read", "write"]
      }
    ],
    "current_session": {
      "project_hash": "PROJ123...",
      "project_name": "API Project",
      "permissions": ["read", "write"],
      "expires_at": "2024-01-04T12:00:00Z"
    },
    "summary": {
      "total_groups": 1,
      "total_projects": 1,
      "is_admin": false
    }
  }
}
```

---

**Next:** Explore the [Authentication API](./authentication.md) or [Project Management API](./project-management.md). 