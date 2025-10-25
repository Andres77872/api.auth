# Global Roles System API

Complete documentation for the **Global Roles System** - a global role-based access control system where:
- **Roles are GLOBAL** (not project-specific)
- **Permissions are GLOBAL** (work everywhere)
- **Each user has ONE role** assigned globally
- **Catalog system** for project-role suggestions (metadata only)

**Base Path:** `/roles`

## 🔐 Authentication Required

All role system endpoints require authentication:

```
Authorization: Bearer YOUR_SESSION_TOKEN
```

**Access Levels:**
- **Admin Required**: Role/permission management operations
- **Authenticated**: Viewing roles and checking permissions

---

## 🎭 Role Management

### POST `/roles/roles`

Create a new global role.

**Authentication:** Required (admin permission)

**Request Body** (Form Data):
- `role_name` (required): Unique role name
- `role_display_name` (required): Display name
- `role_description` (optional): Description
- `role_priority` (optional, default: 50): Priority (0-100)

**Example Request:**
```bash
curl -X POST "http://localhost:8000/roles/roles" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -F "role_name=content_editor" \
  -F "role_display_name=Content Editor" \
  -F "role_description=Can edit and publish content" \
  -F "role_priority=60"
```

**Response (201):**
```json
{
  "success": true,
  "message": "Role 'content_editor' created successfully",
  "role": {
    "id": 5,
    "role_hash": "role_abc123...",
    "role_name": "content_editor",
    "role_display_name": "Content Editor",
    "role_description": "Can edit and publish content",
    "role_priority": 60,
    "is_system_role": false,
    "created_at": "2024-01-01T12:00:00Z"
  }
}
```

---

### GET `/roles/roles`

List all global roles.

**Authentication:** Required

**Query Parameters:**
- `limit` (optional, default: 50, max: 100): Number of roles to return
- `offset` (optional, default: 0): Number of roles to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/roles?limit=20&offset=0" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "roles": [
    {
      "id": 1,
      "role_hash": "role_admin123",
      "role_name": "admin",
      "role_display_name": "Administrator",
      "role_description": "Full system access",
      "role_priority": 100,
      "is_system_role": true,
      "created_at": "2024-01-01T00:00:00Z"
    },
    {
      "id": 2,
      "role_hash": "role_editor456",
      "role_name": "editor",
      "role_display_name": "Editor",
      "role_description": "Content management access",
      "role_priority": 60,
      "is_system_role": false,
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total": 2
  }
}
```

---

### GET `/roles/roles/{role_hash}`

Get detailed information about a specific role.

**Authentication:** Required

**Path Parameters:**
- `role_hash`: Role identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/roles/role_abc123..." \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "role": {
    "id": 5,
    "role_hash": "role_abc123...",
    "role_name": "content_editor",
    "role_display_name": "Content Editor",
    "role_description": "Can edit and publish content",
    "role_priority": 60,
    "is_system_role": false
  },
  "permission_groups": [
    {
      "group_hash": "pgrp_xyz789",
      "group_name": "content_management",
      "group_display_name": "Content Management"
    }
  ]
}
```

---

### PUT `/roles/roles/{role_hash}`

Update a role's information.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `role_hash`: Role identifier

**Request Body** (Form Data):
- `role_display_name` (optional): Updated display name
- `role_description` (optional): Updated description
- `role_priority` (optional): Updated priority (0-100)

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/roles/roles/role_abc123..." \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -F "role_display_name=Senior Content Editor" \
  -F "role_priority=70"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Role updated successfully",
  "role": {
    "role_hash": "role_abc123...",
    "role_name": "content_editor",
    "role_display_name": "Senior Content Editor",
    "role_priority": 70
  }
}
```

---

### DELETE `/roles/roles/{role_hash}`

Soft delete a role (system roles cannot be deleted).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `role_hash`: Role identifier

**Example Request:**
```bash
curl -X DELETE "http://localhost:8000/roles/roles/role_abc123..." \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Role deleted successfully"
}
```

---

## 📦 Permission Group Management

Permission groups are collections of permissions that can be assigned to roles.

### POST `/roles/permission-groups`

Create a new global permission group.

**Authentication:** Required (admin permission)

**Request Body** (Form Data):
- `group_name` (required): Unique group name
- `group_display_name` (required): Display name
- `group_description` (optional): Description
- `group_category` (optional, default: "general"): Category (general, admin, api, data)

**Example Request:**
```bash
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -F "group_name=content_management" \
  -F "group_display_name=Content Management" \
  -F "group_description=Permissions for managing content" \
  -F "group_category=general"
```

**Response (201):**
```json
{
  "success": true,
  "message": "Permission group 'content_management' created successfully",
  "permission_group": {
    "id": 10,
    "group_hash": "pgrp_xyz789",
    "group_name": "content_management",
    "group_display_name": "Content Management",
    "group_description": "Permissions for managing content",
    "group_category": "general",
    "created_at": "2024-01-01T12:00:00Z"
  }
}
```

---

### GET `/roles/permission-groups`

List all global permission groups.

**Authentication:** Required

**Query Parameters:**
- `category` (optional): Filter by category
- `limit` (optional, default: 50, max: 100): Number of groups to return
- `offset` (optional, default: 0): Number of groups to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/permission-groups?category=admin&limit=20" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "permission_groups": [
    {
      "id": 1,
      "group_hash": "pgrp_admin123",
      "group_name": "admin_permissions",
      "group_display_name": "Admin Permissions",
      "group_description": "Administrative permissions",
      "group_category": "admin",
      "created_at": "2024-01-01T00:00:00Z"
    },
    {
      "id": 2,
      "group_hash": "pgrp_content456",
      "group_name": "content_management",
      "group_display_name": "Content Management",
      "group_description": "Content management permissions",
      "group_category": "general",
      "created_at": "2024-01-01T00:00:00Z"
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total": 2
  }
}
```

---

### GET `/roles/permission-groups/{group_hash}`

Get detailed information about a permission group.

**Authentication:** Required

**Path Parameters:**
- `group_hash`: Permission group identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/permission-groups/pgrp_xyz789" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "permission_group": {
    "id": 10,
    "group_hash": "pgrp_xyz789",
    "group_name": "content_management",
    "group_display_name": "Content Management",
    "group_description": "Permissions for managing content",
    "group_category": "general"
  },
  "permissions": [
    {
      "permission_hash": "perm_abc123",
      "permission_name": "create_content",
      "permission_display_name": "Create Content"
    },
    {
      "permission_hash": "perm_def456",
      "permission_name": "edit_content",
      "permission_display_name": "Edit Content"
    }
  ]
}
```

---

## 🔗 Role-Permission Group Assignment

### POST `/roles/roles/{role_hash}/permission-groups/{group_hash}`

Assign a permission group to a role.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `role_hash`: Role identifier
- `group_hash`: Permission group identifier

**Example Request:**
```bash
curl -X POST "http://localhost:8000/roles/roles/role_abc123.../permission-groups/pgrp_xyz789" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Permission group 'content_management' assigned to role 'content_editor'"
}
```

---

### GET `/roles/roles/{role_hash}/permission-groups`

Get all permission groups assigned to a role.

**Authentication:** Required

**Path Parameters:**
- `role_hash`: Role identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/roles/role_abc123.../permission-groups" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "role": {
    "role_hash": "role_abc123...",
    "role_name": "content_editor"
  },
  "permission_groups": [
    {
      "group_hash": "pgrp_xyz789",
      "group_name": "content_management",
      "group_display_name": "Content Management",
      "permissions_count": 5
    }
  ]
}
```

---

## 🔑 Permission Management

### POST `/roles/permissions`

Create a new global permission.

**Authentication:** Required (admin permission)

**Request Body** (Form Data):
- `permission_name` (required): Unique permission name
- `permission_display_name` (required): Display name
- `permission_description` (optional): Description
- `permission_category` (optional, default: "general"): Category

**Example Request:**
```bash
curl -X POST "http://localhost:8000/roles/permissions" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -F "permission_name=publish_content" \
  -F "permission_display_name=Publish Content" \
  -F "permission_description=Can publish content to live site" \
  -F "permission_category=general"
```

**Response (201):**
```json
{
  "success": true,
  "message": "Permission 'publish_content' created successfully",
  "permission": {
    "id": 25,
    "permission_hash": "perm_pub123",
    "permission_name": "publish_content",
    "permission_display_name": "Publish Content",
    "permission_description": "Can publish content to live site",
    "permission_category": "general",
    "created_at": "2024-01-01T12:00:00Z"
  }
}
```

---

### GET `/roles/permissions`

List all global permissions.

**Authentication:** Required

**Query Parameters:**
- `category` (optional): Filter by category
- `limit` (optional, default: 50, max: 100): Number of permissions to return
- `offset` (optional, default: 0): Number of permissions to skip

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/permissions?category=admin&limit=20" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "permissions": [
    {
      "permission_hash": "perm_admin1",
      "permission_name": "manage_users",
      "permission_display_name": "Manage Users",
      "permission_category": "admin"
    },
    {
      "permission_hash": "perm_admin2",
      "permission_name": "manage_roles",
      "permission_display_name": "Manage Roles",
      "permission_category": "admin"
    }
  ],
  "pagination": {
    "limit": 20,
    "offset": 0,
    "total": 2
  }
}
```

---

### GET `/roles/permissions/{permission_hash}`

Get detailed information about a specific permission.

**Authentication:** Required

**Path Parameters:**
- `permission_hash`: Permission identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/permissions/perm_pub123" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "permission": {
    "permission_hash": "perm_pub123",
    "permission_name": "publish_content",
    "permission_display_name": "Publish Content",
    "permission_description": "Can publish content to live site",
    "permission_category": "general",
    "created_at": "2024-01-01T12:00:00Z"
  }
}
```

---

### POST `/roles/permission-groups/{group_hash}/permissions/{permission_hash}`

Assign a permission to a permission group.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `group_hash`: Permission group identifier
- `permission_hash`: Permission identifier

**Example Request:**
```bash
curl -X POST "http://localhost:8000/roles/permission-groups/pgrp_xyz789/permissions/perm_pub123" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Permission 'publish_content' assigned to group 'content_management'"
}
```

---

### GET `/roles/permission-groups/{group_hash}/permissions`

Get all permissions in a permission group.

**Authentication:** Required

**Path Parameters:**
- `group_hash`: Permission group identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/permission-groups/pgrp_xyz789/permissions" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "permission_group": {
    "group_hash": "pgrp_xyz789",
    "group_name": "content_management"
  },
  "permissions": [
    {
      "permission_hash": "perm_abc123",
      "permission_name": "create_content",
      "permission_display_name": "Create Content"
    },
    {
      "permission_hash": "perm_def456",
      "permission_name": "edit_content",
      "permission_display_name": "Edit Content"
    },
    {
      "permission_hash": "perm_pub123",
      "permission_name": "publish_content",
      "permission_display_name": "Publish Content"
    }
  ]
}
```

---

## 👥 User Role Assignment

### PUT `/roles/users/{user_hash}/role`

Assign a role to a user (replaces any existing role).

**Authentication:** Required (admin permission)

**Path Parameters:**
- `user_hash`: User identifier

**Request Body** (Form Data):
- `role_hash` (required): Role hash to assign

**Example Request:**
```bash
curl -X PUT "http://localhost:8000/roles/users/user123.../role" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -F "role_hash=role_abc123..."
```

**Response (200):**
```json
{
  "success": true,
  "message": "Role 'content_editor' assigned to user 'john_doe'",
  "user": {
    "user_hash": "user123...",
    "username": "john_doe"
  },
  "role": {
    "role_hash": "role_abc123...",
    "role_name": "content_editor"
  }
}
```

---

### GET `/roles/users/{user_hash}/role`

Get a user's assigned role.

**Authentication:** Required

**Path Parameters:**
- `user_hash`: User identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/users/user123.../role" \
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
  "role": {
    "role_hash": "role_abc123...",
    "role_name": "content_editor",
    "role_display_name": "Content Editor",
    "role_priority": 60
  }
}
```

---

### GET `/roles/users/me/role`

Get current user's assigned role.

**Authentication:** Required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/users/me/role" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user": {
    "user_hash": "usr-current",
    "username": "john_doe"
  },
  "role": {
    "role_hash": "role_abc123...",
    "role_name": "content_editor",
    "role_display_name": "Content Editor"
  }
}
```

---

## 🔍 Permission Checking

### GET `/roles/users/me/permissions`

Get all permissions for the current user (GLOBAL - works everywhere).

**Authentication:** Required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/users/me/permissions" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "user": {
    "user_hash": "usr-current",
    "username": "john_doe"
  },
  "permissions": [
    "create_content",
    "edit_content",
    "publish_content",
    "view_analytics"
  ],
  "total": 4
}
```

**Response (200) - Root User:**
```json
{
  "success": true,
  "user": {
    "user_hash": "usr-root",
    "username": "root_admin"
  },
  "permissions": ["*"],
  "note": "Root user has all permissions"
}
```

---

### GET `/roles/users/me/permissions/check/{permission_name}`

Check if current user has a specific permission.

**Authentication:** Required

**Path Parameters:**
- `permission_name`: Name of the permission to check

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/users/me/permissions/check/publish_content" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "permission": "publish_content",
  "has_permission": true,
  "checked_at": "2024-01-01T12:00:00Z"
}
```

**Response (200) - Permission Not Granted:**
```json
{
  "success": true,
  "permission": "delete_users",
  "has_permission": false,
  "checked_at": "2024-01-01T12:00:00Z"
}
```

**Response (200) - Root User:**
```json
{
  "success": true,
  "permission": "any_permission",
  "has_permission": true,
  "reason": "Root user",
  "checked_at": "2024-01-01T12:00:00Z"
}
```

---

## 📁 Project Catalog (Metadata Only)

The catalog system allows associating roles with projects for UI suggestions. This is **metadata only** and does not affect permissions.

### POST `/roles/projects/{project_hash}/catalog/roles/{role_hash}`

Add a role to a project's catalog for UI suggestions.

**Authentication:** Required (admin permission)

**Path Parameters:**
- `project_hash`: Project identifier
- `role_hash`: Role identifier

**Request Body** (Form Data):
- `catalog_purpose` (optional): Purpose of this catalog entry
- `notes` (optional): Additional notes

**Example Request:**
```bash
curl -X POST "http://localhost:8000/roles/projects/proj_abc123/catalog/roles/role_xyz789" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN" \
  -F "catalog_purpose=Suggested role for content team" \
  -F "notes=Use for content editors in this project"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Role 'content_editor' added to project catalog",
  "note": "This is METADATA ONLY - does not affect permissions"
}
```

---

### GET `/roles/projects/{project_hash}/catalog/roles`

Get roles cataloged for a project (metadata for UI suggestions).

**Authentication:** Required

**Path Parameters:**
- `project_hash`: Project identifier

**Example Request:**
```bash
curl -X GET "http://localhost:8000/roles/projects/proj_abc123/catalog/roles" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "project": {
    "project_hash": "proj_abc123",
    "project_name": "Main Website"
  },
  "cataloged_roles": [
    {
      "role_hash": "role_xyz789",
      "role_name": "content_editor",
      "role_display_name": "Content Editor",
      "catalog_purpose": "Suggested role for content team",
      "notes": "Use for content editors in this project",
      "added_at": "2024-01-01T12:00:00Z"
    }
  ],
  "note": "These are suggestions only - any role can be used with this project"
}
```

---

## 🧪 Testing Global Roles System

### Complete Role System Test Script

```bash
#!/bin/bash

# Get admin session token
ADMIN_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=PROJECT_HASH" | \
  jq -r '.session_token')

echo "1. Creating a new role..."
curl -X POST "http://localhost:8000/roles/roles" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "role_name=content_moderator" \
  -F "role_display_name=Content Moderator" \
  -F "role_description=Moderate and approve content" \
  -F "role_priority=55"

echo -e "\n\n2. Creating a permission group..."
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "group_name=moderation" \
  -F "group_display_name=Moderation Permissions" \
  -F "group_description=Permissions for content moderation" \
  -F "group_category=general"

echo -e "\n\n3. Creating permissions..."
curl -X POST "http://localhost:8000/roles/permissions" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "permission_name=moderate_content" \
  -F "permission_display_name=Moderate Content" \
  -F "permission_category=general"

echo -e "\n\n4. Assigning permission to group..."
curl -X POST "http://localhost:8000/roles/permission-groups/GROUP_HASH/permissions/PERM_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n\n5. Assigning permission group to role..."
curl -X POST "http://localhost:8000/roles/roles/ROLE_HASH/permission-groups/GROUP_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n\n6. Assigning role to user..."
curl -X PUT "http://localhost:8000/roles/users/USER_HASH/role" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -F "role_hash=ROLE_HASH"

echo -e "\n\n7. Checking user permissions..."
curl -X GET "http://localhost:8000/roles/users/me/permissions" \
  -H "Authorization: Bearer $USER_TOKEN"

echo -e "\n\n8. Checking specific permission..."
curl -X GET "http://localhost:8000/roles/users/me/permissions/check/moderate_content" \
  -H "Authorization: Bearer $USER_TOKEN"
```

---

## 🔒 Security Considerations

### Global vs Project-Specific
- **Roles are GLOBAL**: A user's role applies everywhere in the system
- **No Project Boundaries**: Unlike the old system, permissions are not project-scoped
- **Catalog is Metadata**: Project catalogs are UI suggestions only

### Best Practices
- **Least Privilege**: Assign minimum required permissions through permission groups
- **Role Hierarchy**: Use priority levels (0-100) to establish clear role hierarchy
- **Regular Audits**: Review role assignments and permissions regularly
- **Permission Granularity**: Create specific permissions rather than broad ones

### Access Control Matrix

| Operation | Root Users | Admin Users | Regular Users |
|-----------|------------|-------------|---------------|
| **Create/Edit Roles** | ✅ Yes | ✅ Yes (with manage_roles permission) | ❌ No |
| **Create/Edit Permissions** | ✅ Yes | ✅ Yes (with manage_roles permission) | ❌ No |
| **Assign Roles to Users** | ✅ Yes | ✅ Yes (with manage_users permission) | ❌ No |
| **View Own Role/Permissions** | ✅ Yes | ✅ Yes | ✅ Yes |
| **View Other Users' Roles** | ✅ Yes | ✅ Yes | ❌ No |

### Security Warnings
- **Root Users**: Have ALL permissions automatically (`*` wildcard)
- **System Roles**: Cannot be deleted (flagged as `is_system_role: true`)
- **Permission Inheritance**: Users inherit all permissions from their role's permission groups
- **One Role Per User**: Each user can only have ONE role at a time (new assignment replaces old)

---

## 🆚 Differences from Old RBAC System

### Key Changes
1. **Global vs Project-Specific**
   - Old: Roles and permissions were project-specific (`/rbac/projects/{project_hash}/...`)
   - New: Roles and permissions are global (`/roles/...`)

2. **User Assignment**
   - Old: Users could have different roles in different projects
   - New: Each user has ONE global role that applies everywhere

3. **Permission Groups**
   - Old: Permissions were directly assigned to roles
   - New: Permissions are organized into permission groups, which are then assigned to roles

4. **Catalog System**
   - Old: Not available
   - New: Projects can catalog suggested roles for UI convenience (metadata only)

### Migration Notes
If you have the old RBAC system in place, you'll need to:
1. Map old project-specific roles to new global roles
2. Consolidate user assignments across projects into single global roles
3. Update authorization checks to use new global permission system
4. Use catalog system if you need project-specific role suggestions

---

**Next:** Explore [User Type Management](user-type-management.md) for hierarchical access control or [Admin API](admin.md) for group management. 