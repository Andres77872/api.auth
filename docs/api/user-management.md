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
  "user_hash": "USER123...",
  "username": "john_doe",
  "email": "john.doe@example.com",
  "user_type": "consumer",
  "user_type_info": {
    "user_type": "consumer",
    "capabilities": ["rbac_permissions", "group_based_access"],
    "accessible_projects": [5, 10]
  },
  "created_at": "2024-01-01T12:00:00Z",
  "updated_at": "2024-01-10T08:00:00Z",
  "last_login": "2024-01-15T08:30:00Z",
  "is_active": true,
  "groups": [
    {
      "group_hash": "grp-xyz789",
      "group_name": "developers",
      "group_description": "Software development team",
      "assigned_at": "2024-01-01T14:00:00Z",
      "assigned_by": "admin"
    }
  ],
  "projects": [
    {
      "project_hash": "PROJ123...",
      "project_name": "API Project",
      "project_description": "Main API Project",
      "project_group": "api-access",
      "permissions": ["read", "write", "api_access"]
    }
  ]
}
```

---

### PUT `/users/profile`

Update current user's profile information.

**Authentication:** Required

**Request Body** (Form):
- `username` (optional): Updated username
- `email` (optional): Updated email address
- `password` (optional): Updated password

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john_doe_updated&email=john.doe.new@example.com&password=new_secure_password"
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
    "user_type": "consumer",
    "created_at": "2024-01-01T12:00:00Z",
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
      "user_type": "consumer",
      "user_type_details": {
        "user_type": "consumer",
        "capabilities": ["rbac_permissions", "group_based_access"],
        "accessible_projects": [5, 10]
      },
      "email": "john.doe@example.com"
    },
    "user_groups": [
      {
        "group_hash": "grp-xyz789",
        "group_name": "developers",
        "group_description": "Software development team",
        "assigned_at": "2024-01-01T14:00:00Z",
        "assigned_by": "admin",
        "projects_count": 3
      }
    ],
    "accessible_projects": [
      {
        "project_hash": "PROJ123...",
        "project_name": "API Project",
        "project_description": "Main API Project",
        "access_groups": [
          {
            "group_hash": "grp-xyz789",
            "group_name": "developers",
            "permissions": ["read", "write", "api_access"]
          }
        ],
        "effective_permissions": ["read", "write", "api_access"]
      }
    ],
    "current_session": {
      "project_hash": "PROJ123...",
      "project_name": "API Project",
      "permissions": ["read", "write", "api_access"],
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

## 👥 User Listing and Management

### GET `/users/list`

List all users with advanced filtering, sorting, and pagination options. Admin only.

**Authentication:** Required (admin permission)

**Query Parameters:**
- `limit` (optional, default: 100): Maximum number of results
- `offset` (optional, default: 0): Number of results to skip
- `sort_by` (optional, default: 'username'): Field to sort by
- `sort_order` (optional, default: 'asc'): Sort order ('asc' or 'desc')
- `search` (optional): Search term for username or email
- `user_type_filter` (optional): Filter by user type ('root', 'admin', 'consumer')
- `group_filter` (optional): Filter by user group (hash or name)
- `project_filter` (optional): Filter by project access (hash or name)
- `include_inactive` (optional, default: false): Include inactive users
- `include_group_info` (optional, default: true): Include group membership
- `include_project_access` (optional, default: true): Include project access info

**Example Request:**
```bash
curl -X GET "http://localhost:8000/users/list?limit=50&user_type_filter=consumer&search=john" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "users": [
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "email": "john@example.com",
      "user_type": "consumer",
      "user_type_info": {
        "user_type": "consumer",
        "capabilities": ["rbac_permissions", "group_based_access"],
        "accessible_projects": [5, 10]
      },
      "created_at": "2024-01-01T12:00:00Z",
      "last_login": "2024-01-15T08:30:00Z",
      "is_active": true,
      "groups": [
        {
          "group_hash": "grp-xyz789",
          "group_name": "developers",
          "description": "Development team"
        }
      ],
      "projects": [
        {
          "project_hash": "proj-def456",
          "project_name": "Main API",
          "permissions": ["read", "write", "api_access"]
        }
      ]
    }
  ],
  "pagination": {
    "total": 145,
    "limit": 50,
    "offset": 0,
    "has_more": true
  },
  "filters": {
    "user_type_filter": "consumer",
    "group_filter": null,
    "project_filter": null,
    "search": "john",
    "include_inactive": false
  }
}
```

---

### GET `/users/{user_hash}`

Get detailed information about a specific user including hierarchical group memberships and permissions.

**Authentication:** Required (admin for others, users can view themselves)

**Path Parameters:**
- `user_hash`: User identifier

**Query Parameters:**
- `include_group_hierarchy` (optional, default: true): Include group hierarchy
- `include_permission_details` (optional, default: true): Include permission details

**Example Request:**
```bash
curl -X GET "http://localhost:8000/users/usr-abc123" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user": {
    "user_hash": "usr-abc123",
    "username": "john_doe",
    "email": "john@example.com",
    "user_type": "consumer",
    "user_type_info": {
      "user_type": "consumer",
      "capabilities": ["rbac_permissions", "group_based_access"],
      "accessible_projects": [5, 10]
    },
    "created_at": "2024-01-01T12:00:00Z",
    "updated_at": "2024-01-10T08:00:00Z",
    "last_login": "2024-01-15T08:30:00Z",
    "is_active": true,
    "groups": [
      {
        "group_hash": "grp-xyz789",
        "group_name": "developers",
        "group_description": "Development team",
        "assigned_at": "2024-01-01T14:00:00Z",
        "assigned_by": "admin",
        "projects_count": 3
      }
    ],
    "projects": [
      {
        "project_hash": "proj-def456",
        "project_name": "Main API",
        "project_description": "Primary API service",
        "access_groups": [
          {
            "group_hash": "grp-xyz789",
            "group_name": "developers",
            "permissions": ["read", "write", "api_access"]
          }
        ],
        "effective_permissions": ["read", "write", "api_access"]
      }
    ]
  }
}
```

---

### PUT `/users/{user_hash}/status`

Update a user's active status (activate/deactivate user).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `user_hash`: User identifier

**Query Parameters:**
- `is_active` (required): Boolean to set user active status (true or false)

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/users/usr-abc123/status?is_active=false" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "User john_doe has been deactivated",
  "user_hash": "usr-abc123",
  "is_active": false
}
```

---

### POST `/users/{user_hash}/reset-password`

Reset a user's password (admin only).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `user_hash`: User identifier

**Example Request:**
```bash
curl -X POST "http://localhost:8000/users/usr-abc123/reset-password" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Password reset successfully",
  "user": {
    "user_hash": "usr-abc123",
    "username": "john_doe",
    "email": "john@example.com"
  },
  "reset_data": {
    "temporary_password": "Temp@Pass2024!",
    "expires_at": "2024-01-16T10:30:00Z",
    "must_change_on_login": true
  },
  "instructions": "User must change password on next login"
}
```

---

### PATCH `/users/{user_hash}/type`

Change a user's type (root, admin, or consumer). Root users only.

**Authentication:** Required (root user only)

**Path Parameters:**
- `user_hash`: User identifier

**Request Body** (Form):
- `user_type` (required): New user type ('root', 'admin', or 'consumer')
- `project_hash` (optional): Required when changing to 'admin' type

**Example Request:**
```bash
curl -X PATCH "http://localhost:8000/users/usr-abc123/type" \
  -H "Authorization: Bearer YOUR_ROOT_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_type=admin&project_hash=proj_xyz789abc"
```

**Response (200):**
```json
{
  "success": true,
  "message": "User type changed to admin successfully",
  "user_hash": "usr-abc123",
  "username": "john_doe",
  "email": "john@example.com",
  "user_type": "admin",
  "user_type_info": {
    "user_type": "admin",
    "capabilities": ["project_admin", "manage_project_users"],
    "accessible_projects": [5]
  },
  "affected_groups": [
    {
      "group_hash": "grp-xyz789",
      "group_name": "project_admins",
      "action": "added"
    }
  ],
  "affected_projects": [
    {
      "project_hash": "proj-abc123",
      "project_name": "Main Project",
      "action": "assigned"
    }
  ],
  "previous_type": "consumer",
  "changed_by": "root_admin",
  "changed_at": "2024-01-15T10:30:00Z"
}
```

---

## 🧪 Testing User Management

### Complete User Management Test

```bash
#!/bin/bash

# Get admin token
ADMIN_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=PROJECT_HASH" | \
  jq -r '.session_token')

echo "1. Getting user profile..."
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n2. Listing users with filters..."
curl -X GET "http://localhost:8000/users/list?limit=10&user_type_filter=consumer" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n3. Getting user details..."
curl -X GET "http://localhost:8000/users/USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n4. Updating user profile..."
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=new.email@example.com"

echo -e "\n5. Getting access summary..."
curl -X GET "http://localhost:8000/users/access-summary" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

**Next:** Explore the [Authentication API](./authentication.md), [RBAC Management](./rbac-management.md), or [User Type Management](./user-type-management.md). 