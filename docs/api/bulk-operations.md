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

**Authentication:** Required (admin permission)

**Request Body** (Form):
- `user_hashes` (required): List of user hashes to update
- `is_active` (optional): Set active status (true/false)
- `user_type` (optional): Update user type (root/admin/consumer)
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

---

### POST `/admin/users/bulk-delete`

Soft delete multiple users at once.

**Authentication:** Required (admin permission)

**Request Body** (Form):
- `user_hashes` (required): List of user hashes to delete
- `confirm_deletion` (required): Must be `true` to confirm

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

---

## 🎭 Bulk Role Assignments

### POST `/admin/projects/{project_hash}/bulk-assign-roles`

Assign roles to multiple users within a project.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Project identifier

**Request Body** (Form):
- `user_hashes` (required): List of user hashes
- `role_names` (required): List of role names to assign

**Example Request:**
```bash
curl -X POST "http://localhost:8000/admin/projects/proj_xyz789.../bulk-assign-roles" \
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
    "project_hash": "proj_xyz789...",
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

---

## 👥 Bulk Group Assignments

### POST `/admin/user-groups/bulk-assign`

Assign multiple users to multiple user groups at once.

**Authentication:** Required (admin permission)

**Request Body** (Form):
- `user_hashes` (required): List of user hashes
- `group_names` (required): List of group names or hashes

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

echo -e "\n2. Bulk assign users to groups..."
curl -X POST "http://localhost:8000/admin/user-groups/bulk-assign" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=USER_HASH_1&user_hashes=USER_HASH_2&group_names=developers"

echo -e "\n3. Bulk assign roles in project..."
curl -X POST "http://localhost:8000/admin/projects/PROJECT_HASH/bulk-assign-roles" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=USER_HASH_1&user_hashes=USER_HASH_2&role_names=editor"
```

---

## 🎯 Best Practices

### Performance Optimization
- **Batch Size**: Keep batches under 100 users for optimal performance
- **Progress Tracking**: Monitor `failed_count` in responses
- **Error Handling**: Check `failed_users` array for specific failures

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
