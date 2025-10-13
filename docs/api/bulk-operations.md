# Bulk Operations API

Complete bulk operations documentation for efficiently managing multiple users, roles, and group assignments simultaneously.

## 🔐 Authentication Required

All bulk endpoints require admin authentication:

```
Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN
```

---

## 📋 Bulk User Operations

### POST `/admin/users/bulk-update`

Update multiple users at once (status, user type, etc.).

**Authentication:** Required (admin or manage_users permission)

**Limits:** Maximum 100 users per request

**Request Body** (Form):
- `user_hashes` (required): List of user hashes to update
- `is_active` (optional): Set active status (true/false)
- `user_type` (optional): Update user type. Valid values: `root`, `admin`, `consumer`
- `force_password_reset` (optional): Force password reset on next login (true/false)

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/users/bulk-update" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-abc123&user_hashes=usr-def456&is_active=true"
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Bulk update completed: 2 succeeded, 0 failed",
  "summary": {
    "total_requested": 2,
    "success_count": 2,
    "error_count": 0,
    "skipped_count": 0
  },
  "updates_applied": {
    "is_active": true
  },
  "results": [
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "status": "success",
      "message": "User updated successfully"
    },
    {
      "user_hash": "usr-def456",
      "username": "jane_smith",
      "status": "success",
      "message": "User updated successfully"
    }
  ],
  "errors": [],
  "performed_by": "admin",
  "performed_at": "2024-01-15T10:30:00Z"
}
```

**Error Responses:**

- **401 Unauthorized**: Invalid or missing session token
- **403 Forbidden**: Requires admin or manage_users permission
- **400 Bad Request**: 
  - Missing user_hashes or no update fields provided
  - Exceeded maximum user limit (100)
  - Invalid user_type value (must be root, admin, or consumer)
- **500 Internal Server Error**: Bulk update failed

---

### POST `/admin/users/bulk-delete`

Soft delete multiple users at once.

**Authentication:** Required (admin or manage_users permission)

**Limits:** Maximum 50 users per request

**Request Body** (Form):
- `user_hashes` (required): List of user hashes to delete
- `confirm_deletion` (required): Must be `true` to confirm deletion

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/users/bulk-delete" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-abc123&user_hashes=usr-def456&confirm_deletion=true"
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Bulk deletion completed: 2 deleted, 0 failed",
  "summary": {
    "total_requested": 2,
    "success_count": 2,
    "error_count": 0,
    "protected_count": 0
  },
  "results": [
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "status": "success",
      "message": "User deleted successfully"
    },
    {
      "user_hash": "usr-def456",
      "username": "jane_smith",
      "status": "success",
      "message": "User deleted successfully"
    }
  ],
  "errors": [],
  "warnings": [],
  "performed_by": "admin",
  "performed_at": "2024-01-15T10:30:00Z"
}
```

**Error Responses:**

- **401 Unauthorized**: Invalid or missing session token
- **403 Forbidden**: Requires admin or manage_users permission
- **400 Bad Request**: 
  - Missing user_hashes
  - `confirm_deletion` not set to true
  - Exceeded maximum user limit (50)
- **500 Internal Server Error**: Bulk deletion failed

---

## 🎭 Bulk Role Assignments

### POST `/admin/projects/{project_hash}/bulk-assign-roles`

Bulk assign roles to users in a specific project.

**Authentication:** Required (admin permission)

**Limits:** Maximum 100 users per request

**Path Parameters:**
- `project_hash` (required): Project identifier

**Request Body** (Form):
- `user_hashes` (required): List of user hashes to assign roles to
- `role_names` (required): List of role names to assign

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/projects/proj-abc123/bulk-assign-roles" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-abc123&user_hashes=usr-def456&role_names=editor&role_names=viewer"
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Bulk role assignment completed: 4 succeeded, 0 failed",
  "project": {
    "project_hash": "proj-abc123",
    "project_name": "My Project"
  },
  "roles_assigned": ["editor", "viewer"],
  "summary": {
    "total_requested": 2,
    "success_count": 4,
    "error_count": 0
  },
  "results": [
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "role": "editor",
      "status": "success",
      "message": "Role assigned successfully"
    },
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "role": "viewer",
      "status": "success",
      "message": "Role assigned successfully"
    },
    {
      "user_hash": "usr-def456",
      "username": "jane_smith",
      "role": "editor",
      "status": "success",
      "message": "Role assigned successfully"
    },
    {
      "user_hash": "usr-def456",
      "username": "jane_smith",
      "role": "viewer",
      "status": "success",
      "message": "Role assigned successfully"
    }
  ],
  "errors": [],
  "performed_by": "admin",
  "performed_at": "2024-01-15T10:30:00Z"
}
```

**Error Responses:**

- **401 Unauthorized**: Invalid or missing session token
- **403 Forbidden**: Requires admin permission
- **404 Not Found**: Project not found
- **400 Bad Request**: 
  - Missing required fields
  - Exceeded maximum user limit (100)
  - Invalid role names
- **500 Internal Server Error**: Bulk role assignment failed

---

## 👥 Bulk Group Assignments

### POST `/admin/user-groups/bulk-assign`

Assign multiple users to multiple user groups at once.

**Authentication:** Required (admin permission)

**Limits:** Maximum 100 users per request

**Request Body** (Form):
- `user_hashes` (required): List of user hashes
- `group_names` (required): List of group names

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/user-groups/bulk-assign" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-abc123&user_hashes=usr-def456&group_names=developers&group_names=api_users"
```

**Success Response (200):**
```json
{
  "success": true,
  "message": "Bulk group assignment completed: 4 succeeded, 0 failed",
  "groups_assigned": ["developers", "api_users"],
  "summary": {
    "total_requested": 2,
    "success_count": 4,
    "error_count": 0
  },
  "results": [
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "group": "developers",
      "status": "success",
      "message": "User assigned to group successfully"
    },
    {
      "user_hash": "usr-def456",
      "username": "jane_smith",
      "group": "developers",
      "status": "success",
      "message": "User assigned to group successfully"
    },
    {
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "group": "api_users",
      "status": "success",
      "message": "User assigned to group successfully"
    },
    {
      "user_hash": "usr-def456",
      "username": "jane_smith",
      "group": "api_users",
      "status": "success",
      "message": "User assigned to group successfully"
    }
  ],
  "errors": [],
  "performed_by": "admin",
  "performed_at": "2024-01-15T10:30:00Z"
}
```

**Error Responses:**

- **401 Unauthorized**: Invalid or missing session token
- **403 Forbidden**: Requires admin permission
- **400 Bad Request**: 
  - Missing user_hashes or group_names
  - Exceeded maximum user limit (100)
  - Invalid group names
- **500 Internal Server Error**: Bulk group assignment failed

---

## 🧪 Testing Bulk Operations

### Complete Bulk Operations Test

```bash
#!/bin/bash

# Get admin token
ADMIN_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=PROJECT_HASH" | \
  jq -r '.session_token')

echo "1. Bulk update users..."
curl -X POST "http://localhost:8000/admin/users/bulk-update" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=USER_HASH_1&user_hashes=USER_HASH_2&is_active=true"

echo -e "\n2. Bulk assign roles to users in a project..."
curl -X POST "http://localhost:8000/admin/projects/PROJECT_HASH/bulk-assign-roles" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=USER_HASH_1&user_hashes=USER_HASH_2&role_names=editor&role_names=viewer"

echo -e "\n3. Bulk assign users to groups..."
curl -X POST "http://localhost:8000/admin/user-groups/bulk-assign" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=USER_HASH_1&user_hashes=USER_HASH_2&group_names=developers"
```

---

## 🎯 Best Practices

### Performance Optimization
- **Batch Size Limits**:
  - User updates: Maximum 100 users per request
  - User deletions: Maximum 50 users per request  
  - Role assignments: Maximum 100 users per request
  - Group assignments: Maximum 100 users per request
- **Progress Tracking**: Monitor `error_count` in responses
- **Error Handling**: Check `errors` array for specific failures

### Safety Guidelines
1. **Always confirm deletions**: Set `confirm_deletion=true`
2. **Test with small batches**: Verify operations with 1-2 users first
3. **Backup before bulk delete**: Ensure you can restore if needed
4. **Monitor audit logs**: Track all bulk operations

### Use Cases
- **Onboarding**: Bulk assign new employees to groups
- **Role Changes**: Update permissions for department changes
- **Cleanup**: Deactivate multiple inactive users
- **Project Setup**: Assign team members to project roles

---

**Next:** Explore [Analytics API](analytics.md) for system insights or [Admin API](admin.md) for management operations.
