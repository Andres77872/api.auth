# Permission Assignments API

Complete documentation for the **Permission Assignment System** - manages permission group assignments to user groups and individual users.

**Base Path:** `/v1`

## 🔐 Authentication Required

All permission assignment endpoints require authentication:

```
Authorization: Bearer YOUR_SESSION_TOKEN
```

**Access Levels:**
- **Admin Required**: All permission assignment operations
- **Authenticated**: Viewing own permissions

---

## 🎯 Core Concepts

### Permission Assignment Model

The system supports two levels of permission assignments:

1. **PRIMARY: User Group Assignments** (Recommended)
   - Assign permission groups to user groups
   - All members inherit permissions
   - Organizational scale management

2. **SECONDARY: Direct User Assignments** (Special Cases)
   - Assign permission groups directly to users
   - Individual overrides and temporary access
   - Use sparingly for exceptions

### Permission Resolution

Users receive permissions from multiple sources:
1. **Role-based permissions** (from assigned global role)
2. **User group permissions** (from group memberships)
3. **Direct permissions** (from individual assignments)

---

## 👥 User Group Permission Assignments (PRIMARY)

### POST `/v1/admin/user-groups/{group_hash}/permission-groups`

Assign a permission group to a user group. All members inherit the permissions.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Request Body** (Form):
- `permission_group_hash` (required): Permission group hash to assign

**Example Request:**
```bash
curl -X POST "http://localhost:8000/v1/admin/user-groups/grp-abc123/permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=pgrp-xyz789"
```

**Response (200):**
```json
{
  "message": "Permission group assigned to user group successfully",
  "user_group": {
    "hash": "grp-abc123",
    "name": "developers"
  },
  "permission_group": {
    "hash": "pgrp-xyz789",
    "name": "content_management"
  }
}
```

---

### DELETE `/v1/admin/user-groups/{group_hash}/permission-groups/{pg_hash}`

Remove a permission group from a user group.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier
- `pg_hash`: Permission group identifier

**Example Request:**
```bash
curl -X DELETE "http://localhost:8000/v1/admin/user-groups/grp-abc123/permission-groups/pgrp-xyz789" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "message": "Permission group removed from user group successfully",
  "user_group": {
    "hash": "grp-abc123",
    "name": "developers"
  },
  "permission_group": {
    "hash": "pgrp-xyz789",
    "name": "content_management"
  }
}
```

---

### GET `/v1/admin/user-groups/{group_hash}/permission-groups`

Get all permission groups assigned to a user group.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/v1/admin/user-groups/grp-abc123/permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "user_group": {
    "hash": "grp-abc123",
    "name": "developers"
  },
  "permission_groups": [
    {
      "id": "pg_internal_id_1",
      "group_hash": "pgrp-xyz789",
      "group_name": "content_management",
      "group_display_name": "Content Management",
      "group_description": "Permissions for content management",
      "group_category": "content",
      "assigned_at": "2024-01-10T09:00:00Z",
      "assigned_by": "admin_user_id"
    },
    {
      "id": "pg_internal_id_2",
      "group_hash": "pgrp-def456",
      "group_name": "api_access",
      "group_display_name": "API Access",
      "group_description": "API access permissions",
      "group_category": "api",
      "assigned_at": "2024-01-12T10:00:00Z",
      "assigned_by": "admin_user_id"
    }
  ],
  "count": 2
}
```

---

### POST `/v1/admin/user-groups/{group_hash}/permission-groups/bulk`

Bulk assign multiple permission groups to a user group.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: User group identifier

**Request Body** (Form):
- `permission_group_hashes` (required): List of permission group hashes

**Example Request:**
```bash
curl -X POST "http://localhost:8000/v1/admin/user-groups/grp-abc123/permission-groups/bulk" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hashes=pgrp-xyz789&permission_group_hashes=pgrp-def456&permission_group_hashes=pgrp-ghi012"
```

**Response (200):**
```json
{
  "message": "Bulk assignment completed: 3/3 successful",
  "user_group": {
    "hash": "grp-abc123",
    "name": "developers"
  },
  "results": [
    {
      "permission_group_hash": "pgrp-xyz789",
      "permission_group_name": "content_management",
      "success": true
    },
    {
      "permission_group_hash": "pgrp-def456",
      "permission_group_name": "api_access",
      "success": true
    },
    {
      "permission_group_hash": "pgrp-ghi012",
      "permission_group_name": "data_export",
      "success": true
    }
  ],
  "success_count": 3,
  "total_count": 3
}
```

---

## 🔑 Direct User Permission Assignments (SECONDARY)

### POST `/v1/users/{user_hash}/permission-groups`

Assign a permission group directly to a user (for individual overrides).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `user_hash`: User identifier

**Request Body** (Form):
- `permission_group_hash` (required): Permission group hash to assign
- `notes` (optional): Reason for direct assignment

**Example Request:**
```bash
curl -X POST "http://localhost:8000/v1/users/usr-abc123/permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=pgrp-xyz789&notes=Temporary%20elevated%20access%20for%20project%20migration"
```

**Response (200):**
```json
{
  "message": "Permission group assigned to user successfully",
  "user": {
    "hash": "usr-abc123",
    "username": "john_doe"
  },
  "permission_group": {
    "hash": "pgrp-xyz789",
    "name": "content_management"
  },
  "notes": "Temporary elevated access for project migration"
}
```

---

### DELETE `/v1/users/{user_hash}/permission-groups/{pg_hash}`

Remove a permission group from a user.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `user_hash`: User identifier
- `pg_hash`: Permission group identifier

**Example Request:**
```bash
curl -X DELETE "http://localhost:8000/v1/users/usr-abc123/permission-groups/pgrp-xyz789" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "message": "Permission group removed from user successfully",
  "user": {
    "hash": "usr-abc123",
    "username": "john_doe"
  },
  "permission_group": {
    "hash": "pgrp-xyz789",
    "name": "content_management"
  }
}
```

---

### GET `/v1/users/{user_hash}/permission-groups`

Get permission groups directly assigned to a user.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `user_hash`: User identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/v1/users/usr-abc123/permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "user": {
    "hash": "usr-abc123",
    "username": "john_doe"
  },
  "direct_permission_groups": [
    {
      "id": "pg_internal_id_1",
      "group_hash": "pgrp-xyz789",
      "group_name": "content_management",
      "group_display_name": "Content Management",
      "group_description": "Permissions for content management",
      "group_category": "content",
      "assigned_at": "2024-01-15T10:30:00Z",
      "assigned_by": "admin_user_id",
      "notes": "Temporary elevated access"
    }
  ],
  "count": 1
}
```

---

## 🔍 Current User Permission Queries

### GET `/v1/users/me/permissions`

Get all permissions for the current user from all sources.

**Authentication:** Required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/v1/users/me/permissions" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "user": {
    "hash": "usr-abc123",
    "username": "john_doe"
  },
  "permissions": [
    "create_content",
    "edit_content",
    "publish_content",
    "manage_users",
    "view_analytics"
  ],
  "count": 5
}
```

---

### GET `/v1/users/me/permissions/check/{permission_name}`

Check if current user has a specific permission.

**Authentication:** Required

**Path Parameters:**
- `permission_name`: Permission name to check

**Example Request:**
```bash
curl -X GET "http://localhost:8000/v1/users/me/permissions/check/edit_content" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "user": {
    "hash": "usr-abc123",
    "username": "john_doe"
  },
  "permission": "edit_content",
  "has_permission": true
}
```

---

### GET `/v1/users/me/permission-groups`

Get permission groups directly assigned to current user.

**Authentication:** Required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/v1/users/me/permission-groups" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "user": {
    "hash": "usr-abc123",
    "username": "john_doe"
  },
  "direct_permission_groups": [
    {
      "id": "pg_internal_id_1",
      "group_hash": "pgrp-xyz789",
      "group_name": "content_management",
      "group_display_name": "Content Management",
      "group_description": "Permissions for content management",
      "group_category": "content",
      "assigned_at": "2024-01-15T10:30:00Z",
      "assigned_by": "admin_user_id",
      "notes": null
    }
  ],
  "count": 1
}
```

---

### GET `/v1/users/me/permission-sources`

Get detailed breakdown of where permissions come from.

**Authentication:** Required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/v1/users/me/permission-sources" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "user": {
    "hash": "usr-abc123",
    "username": "john_doe"
  },
  "sources": {
    "from_role": [
      {
        "source_type": "role",
        "role_name": "editor",
        "permission_group_name": "basic_editing",
        "permissions_count": 3
      }
    ],
    "from_user_groups": [
      {
        "source_type": "user_group",
        "user_group_name": "developers",
        "permission_group_name": "api_access",
        "permissions_count": 5
      }
    ],
    "from_direct_assignment": [
      {
        "source_type": "direct",
        "permission_group_name": "content_management",
        "permissions_count": 4,
        "notes": "Temporary elevated access"
      }
    ]
  },
  "summary": {
    "role_count": 1,
    "user_group_count": 1,
    "direct_count": 1,
    "total_permission_groups": 3
  }
}
```

---

## 📂 Project Catalog (METADATA ONLY)

The catalog system is for **UI suggestions and organization only** - it does NOT restrict permissions.

### POST `/v1/projects/{project_hash}/permission-group-catalog/{pg_hash}`

Add permission group to project catalog (metadata for UI).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Project identifier
- `pg_hash`: Permission group identifier

**Request Body** (Form):
- `catalog_purpose` (optional): Purpose description
- `notes` (optional): Additional notes

**Example Request:**
```bash
curl -X POST "http://localhost:8000/v1/projects/proj-abc123/permission-group-catalog/pgrp-xyz789" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "catalog_purpose=Recommended%20for%20content%20editors&notes=Provides%20standard%20content%20management%20capabilities"
```

**Response (200):**
```json
{
  "message": "Permission group added to project catalog successfully",
  "note": "This is METADATA ONLY - not used for authorization",
  "project": {
    "hash": "proj-abc123",
    "name": "My Project"
  },
  "permission_group": {
    "hash": "pgrp-xyz789",
    "name": "content_management"
  },
  "catalog_purpose": "Recommended for content editors"
}
```

---

### DELETE `/v1/projects/{project_hash}/permission-group-catalog/{pg_hash}`

Remove permission group from project catalog.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Project identifier
- `pg_hash`: Permission group identifier

**Example Request:**
```bash
curl -X DELETE "http://localhost:8000/v1/projects/proj-abc123/permission-group-catalog/pgrp-xyz789" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "message": "Permission group removed from project catalog successfully",
  "project": {
    "hash": "proj-abc123",
    "name": "My Project"
  },
  "permission_group": {
    "hash": "pgrp-xyz789",
    "name": "content_management"
  }
}
```

---

### GET `/v1/projects/{project_hash}/permission-group-catalog`

Get cataloged permission groups for a project (suggestions).

**Authentication:** Required

**Path Parameters:**
- `project_hash`: Project identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/v1/projects/proj-abc123/permission-group-catalog" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "project": {
    "hash": "proj-abc123",
    "name": "My Project"
  },
  "cataloged_permission_groups": [
    {
      "id": "pg_internal_id_1",
      "group_hash": "pgrp-xyz789",
      "group_name": "content_management",
      "group_display_name": "Content Management",
      "group_description": "Permissions for content management",
      "group_category": "content",
      "catalog_purpose": "Recommended for content editors",
      "notes": "Provides standard content management capabilities",
      "added_at": "2024-01-15T10:30:00Z",
      "added_by": "admin_user_id"
    }
  ],
  "count": 1,
  "note": "This is METADATA ONLY - any permission group can be used"
}
```

---

### GET `/v1/permissions/groups/{pg_hash}/project-catalog`

Get projects that catalog a specific permission group.

**Authentication:** Required

**Path Parameters:**
- `pg_hash`: Permission group identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/v1/permissions/groups/pgrp-xyz789/project-catalog" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "permission_group": {
    "hash": "pgrp-xyz789",
    "name": "content_management"
  },
  "cataloged_in_projects": [
    {
      "id": "proj_internal_id_1",
      "project_hash": "proj-abc123",
      "project_name": "My Project",
      "project_description": "Main project",
      "catalog_purpose": "Recommended for content editors",
      "notes": "Primary use case",
      "added_at": "2024-01-10T09:00:00Z",
      "added_by": "admin_user_id"
    },
    {
      "id": "proj_internal_id_2",
      "project_hash": "proj-def456",
      "project_name": "Blog Platform",
      "project_description": "Blog management system",
      "catalog_purpose": "Core editing permissions",
      "notes": "Standard blog operations",
      "added_at": "2024-01-12T10:00:00Z",
      "added_by": "admin_user_id"
    }
  ],
  "count": 2,
  "note": "This permission group works in ALL projects, not just cataloged ones"
}
```

---

## 📊 Usage Analytics

### GET `/v1/permissions/groups/{pg_hash}/user-groups`

Get user groups that have a permission group assigned.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `pg_hash`: Permission group identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/v1/permissions/groups/pgrp-xyz789/user-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "permission_group": {
    "hash": "pgrp-xyz789",
    "name": "content_management"
  },
  "user_groups": [
    {
      "id": "ug_internal_id_1",
      "group_hash": "grp-abc123",
      "group_name": "developers",
      "group_description": "Developer team members",
      "assigned_at": "2024-01-10T09:00:00Z",
      "assigned_by": "admin_user_id"
    },
    {
      "id": "ug_internal_id_2",
      "group_hash": "grp-def456",
      "group_name": "editors",
      "group_description": "Content editor team",
      "assigned_at": "2024-01-12T14:30:00Z",
      "assigned_by": "admin_user_id"
    }
  ],
  "count": 2
}
```

---

### GET `/v1/permissions/groups/{pg_hash}/users`

Get users with direct permission group assignments.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `pg_hash`: Permission group identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/v1/permissions/groups/pgrp-xyz789/users" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "permission_group": {
    "hash": "pgrp-xyz789",
    "name": "content_management"
  },
  "users_with_direct_assignment": [
    {
      "id": "user_internal_id_1",
      "user_hash": "usr-abc123",
      "username": "john_doe",
      "email": "john@example.com",
      "assigned_at": "2024-01-15T10:30:00Z",
      "assigned_by": "admin_user_id",
      "notes": "Temporary elevated access"
    }
  ],
  "count": 1
}
```

---

## 🧪 Testing Permission Assignments

### Complete Permission Assignment Flow

```bash
#!/bin/bash

# Get admin token
ADMIN_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=PROJECT_HASH" | \
  jq -r '.session_token')

echo "1. Assign permission group to user group..."
curl -X POST "http://localhost:8000/v1/admin/user-groups/GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=PERM_GROUP_HASH"

echo -e "\n2. Check user group permission groups..."
curl -X GET "http://localhost:8000/v1/admin/user-groups/GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n3. Assign permission group directly to user..."
curl -X POST "http://localhost:8000/v1/users/USER_HASH/permission-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=PERM_GROUP_HASH&notes=Temporary%20access"

echo -e "\n4. Check user permissions..."
curl -X GET "http://localhost:8000/v1/users/me/permissions" \
  -H "Authorization: Bearer $USER_TOKEN"

echo -e "\n5. Check permission sources..."
curl -X GET "http://localhost:8000/v1/users/me/permission-sources" \
  -H "Authorization: Bearer $USER_TOKEN"
```

---

## 🎯 Best Practices

### Assignment Strategy

1. **Use User Groups First** (PRIMARY)
   - Assign permission groups to user groups
   - Easier to manage at scale
   - Clear organizational structure

2. **Direct Assignments Sparingly** (SECONDARY)
   - Only for temporary or exceptional cases
   - Document the reason in `notes`
   - Review and remove when no longer needed

3. **Catalog for Organization**
   - Use project catalogs for UI suggestions
   - Does NOT restrict what can be used
   - Helps users find appropriate permissions

### Permission Auditing

- Review direct assignments regularly
- Check permission sources for users
- Monitor permission group usage
- Document permission group purposes

---

**Next:** Explore [Global Roles API](global_roles.md) for role management or [Admin API](admin.md) for user group administration.
