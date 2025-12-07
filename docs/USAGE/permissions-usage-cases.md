# Permission Groups Usage Guide

Complete practical guide for managing permission groups and assigning them to user groups or individual users to control fine-grained access in the authentication system.

---

## 📖 Table of Contents

- [Understanding Permission Groups](#understanding-permission-groups)
- [Permission Groups Management](#permission-groups-management)
- [Permissions Management](#permissions-management)
- [User Group Assignments](#user-group-assignments)
- [Direct User Assignments](#direct-user-assignments)
- [Roles System](#roles-system)
- [Current User Queries](#current-user-queries)
- [Permission Group Catalog (Metadata)](#permission-group-catalog-metadata)
- [Role Catalog (Metadata)](#role-catalog-metadata)
- [Permission Group Usage Queries](#permission-group-usage-queries)
- [Common Scenarios](#common-scenarios)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Understanding Permission Groups

The permission group system provides **fine-grained permission management** that works with your existing user groups and project access.

### Core Concepts

**Permissions:**
- Individual actions a user can perform (e.g., `read`, `write`, `delete`, `manage_users`)
- Global scope - not project-specific
- Building blocks for permission groups

**Permission Groups:**
- Collections of related permissions
- Global, reusable - work everywhere
- Can be assigned to user groups or individual users
- Categories: general, admin, api, data, content, testing

**Roles:**
- Higher-level constructs that contain permission groups
- Each user can have one global role assigned
- Roles aggregate permission groups for common job functions

### Two Assignment Models

1. **User Groups → Permission Groups** (Primary - Organizational scale)
2. **Users → Permission Groups** (Secondary - Individual overrides)

### How They Work with Existing Systems

```
┌─────────────────────────────────────────────────────────────┐
│              PERMISSION ACCESS FLOW                          │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  USER ─┬─► ROLE ──────────────────► PERMISSION_GROUPS      │
│        │                                    ↓                │
│        ├─► USER_GROUPS ──► PERMISSION_GROUPS               │
│        │                          ↓                         │
│        └─► DIRECT ASSIGNMENT ──► PERMISSION_GROUPS         │
│                                      ↓                      │
│                              PERMISSIONS                    │
│                                                              │
│  Final Permissions = Role + User Group + Direct Permissions │
└─────────────────────────────────────────────────────────────┘
```

**Example Flow:**
1. User John has role "developer" which includes "content_management" permission group
2. John is also in "mobile_team" user group which has "api_access" permission group
3. John also has direct assignment of "advanced_analytics" permission group
4. **Result**: John has permissions from all three sources combined

---

## Permission Groups Management

### Creating a Permission Group

**Scenario**: Create a content management permission group.

```bash
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=content_management&group_display_name=Content Management&group_description=Full content creation and editing&group_category=content"
```

**Response:**
```json
{
  "success": true,
  "message": "Permission group 'content_management' created successfully",
  "permission_group": {
    "group_hash": "pg-content123...",
    "group_name": "content_management",
    "group_display_name": "Content Management",
    "group_description": "Full content creation and editing",
    "group_category": "content",
    "created_at": "2024-01-15T10:30:00Z"
  }
}
```

### Updating a Permission Group

**Scenario**: Update a permission group's display name and description.

```bash
curl -X PUT "http://localhost:8000/roles/permission-groups/pg-content123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_display_name=Content Management Pro&group_description=Enhanced content management&group_category=content"
```

**Response:**
```json
{
  "success": true,
  "message": "Permission group updated successfully",
  "permission_group": {
    "group_hash": "pg-content123...",
    "group_name": "content_management",
    "group_display_name": "Content Management Pro",
    "group_description": "Enhanced content management",
    "group_category": "content"
  }
}
```

### Deleting a Permission Group

**Scenario**: Delete an unused permission group.

```bash
curl -X DELETE "http://localhost:8000/roles/permission-groups/pg-content123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Permission group 'content_management' deleted successfully"
}
```

### Common Permission Group Templates

**Content Management:**
```bash
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=content_management&group_display_name=Content Management&group_category=content"
```

**API Access:**
```bash
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=api_access&group_display_name=API Access&group_category=api"
```

**Read Only:**
```bash
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=read_only_access&group_display_name=Read Only Access&group_category=data"
```

**Admin Operations:**
```bash
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=admin_operations&group_display_name=Administrative Operations&group_category=admin"
```

### Listing Permission Groups

```bash
curl -X GET "http://localhost:8000/roles/permission-groups?category=content&limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "permission_groups": [
    {
      "group_hash": "pg-content123...",
      "group_name": "content_management",
      "group_display_name": "Content Management",
      "group_category": "content",
      "created_at": "2024-01-15T10:30:00Z"
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 5
  }
}
```

### Viewing Permission Group Details

```bash
curl -X GET "http://localhost:8000/roles/permission-groups/pg-content123..." \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "permission_group": {
    "group_hash": "pg-content123...",
    "group_name": "content_management",
    "group_display_name": "Content Management",
    "group_description": "Full content creation and editing",
    "group_category": "content"
  },
  "permissions": [
    {
      "permission_hash": "perm-read123...",
      "permission_name": "read",
      "permission_display_name": "Read"
    },
    {
      "permission_hash": "perm-write456...",
      "permission_name": "write",
      "permission_display_name": "Write"
    }
  ]
}
```

### Adding Permissions to Permission Groups

```bash
# Add 'read' permission
curl -X POST "http://localhost:8000/roles/permission-groups/pg-content123.../permissions/perm-read456..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Permission 'read' assigned to group 'content_management'"
}
```

### Getting Permission Group Permissions

```bash
curl -X GET "http://localhost:8000/roles/permission-groups/pg-content123.../permissions" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "permission_group": {
    "group_hash": "pg-content123...",
    "group_name": "content_management"
  },
  "permissions": [
    {
      "permission_hash": "perm-read123...",
      "permission_name": "read",
      "permission_display_name": "Read"
    }
  ]
}
```

### Removing Permission from Permission Group

**Scenario**: Remove a permission from a permission group.

```bash
curl -X DELETE "http://localhost:8000/roles/permission-groups/pg-content123.../permissions/perm-read123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Permission 'read' removed from group 'content_management'"
}
```

---

## Permissions Management

### Creating a Permission

```bash
curl -X POST "http://localhost:8000/roles/permissions" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_name=publish_content&permission_display_name=Publish Content&permission_description=Ability to publish content&permission_category=content"
```

**Response:**
```json
{
  "success": true,
  "message": "Permission 'publish_content' created successfully",
  "permission": {
    "permission_hash": "perm-publish789...",
    "permission_name": "publish_content",
    "permission_display_name": "Publish Content",
    "permission_description": "Ability to publish content",
    "permission_category": "content"
  }
}
```

### Listing Permissions

```bash
curl -X GET "http://localhost:8000/roles/permissions?category=content&limit=50" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "permissions": [
    {
      "permission_hash": "perm-read123...",
      "permission_name": "read",
      "permission_display_name": "Read",
      "permission_category": "content"
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 10
  }
}
```

### Getting a Permission

```bash
curl -X GET "http://localhost:8000/roles/permissions/perm-read123..." \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Updating a Permission

**Scenario**: Update a permission's display name and description.

```bash
curl -X PUT "http://localhost:8000/roles/permissions/perm-read123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_display_name=Enhanced Read Access&permission_description=Allows reading all content&permission_category=data"
```

**Response:**
```json
{
  "success": true,
  "message": "Permission updated successfully",
  "permission": {
    "permission_hash": "perm-read123...",
    "permission_name": "read",
    "permission_display_name": "Enhanced Read Access",
    "permission_description": "Allows reading all content",
    "permission_category": "data"
  }
}
```

### Deleting a Permission

**Scenario**: Delete an unused permission.

```bash
curl -X DELETE "http://localhost:8000/roles/permissions/perm-read123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Permission 'read' deleted successfully"
}
```

---

## User Group Assignments

User group assignments allow you to grant permission groups to entire teams at once.

### Assigning Permission Group to User Group

**Scenario**: Give the "editors" user group content management permissions.

```bash
curl -X POST "http://localhost:8000/permissions/admin/user-groups/grp-editors123.../permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=pg-content123..."
```

**Response:**
```json
{
  "message": "Permission group assigned to user group successfully",
  "user_group": {
    "hash": "grp-editors123...",
    "name": "editors"
  },
  "permission_group": {
    "hash": "pg-content123...",
    "name": "content_management"
  }
}
```

**Result**: All users in the "editors" group now have content management permissions.

### Bulk Assigning Multiple Permission Groups to User Group

**Scenario**: Give developers content management, API access, and export permissions.

```bash
curl -X POST "http://localhost:8000/permissions/admin/user-groups/grp-developers456.../permission-groups/bulk" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hashes=pg-content123...&permission_group_hashes=pg-api789...&permission_group_hashes=pg-export012..."
```

**Response:**
```json
{
  "message": "Bulk assignment completed: 3/3 successful",
  "user_group": {
    "hash": "grp-developers456...",
    "name": "developers"
  },
  "results": [
    {
      "permission_group_hash": "pg-content123...",
      "permission_group_name": "content_management",
      "success": true
    },
    {
      "permission_group_hash": "pg-api789...",
      "permission_group_name": "api_access",
      "success": true
    }
  ],
  "success_count": 3,
  "total_count": 3
}
```

### Viewing User Group's Permission Groups

```bash
curl -X GET "http://localhost:8000/permissions/admin/user-groups/grp-developers456.../permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "user_group": {
    "hash": "grp-developers456...",
    "name": "developers"
  },
  "permission_groups": [
    {
      "group_hash": "pg-content123...",
      "group_name": "content_management"
    },
    {
      "group_hash": "pg-api789...",
      "group_name": "api_access"
    }
  ],
  "count": 2
}
```

### Removing Permission Group from User Group

```bash
curl -X DELETE "http://localhost:8000/permissions/admin/user-groups/grp-developers456.../permission-groups/pg-content123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "message": "Permission group removed from user group successfully",
  "user_group": {
    "hash": "grp-developers456...",
    "name": "developers"
  },
  "permission_group": {
    "hash": "pg-content123...",
    "name": "content_management"
  }
}
```

---

## Direct User Assignments

Direct assignments allow you to grant specific permission groups to individual users, bypassing user groups.

### Assigning Permission Group Directly to User

**Scenario**: Give John special analytics permissions beyond his team's permissions.

```bash
curl -X POST "http://localhost:8000/permissions/users/usr-john789.../permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=pg-analytics456...&notes=Special analytics access for Q1 report project"
```

**Response:**
```json
{
  "message": "Permission group assigned to user successfully",
  "user": {
    "hash": "usr-john789...",
    "username": "john_doe"
  },
  "permission_group": {
    "hash": "pg-analytics456...",
    "name": "advanced_analytics"
  },
  "notes": "Special analytics access for Q1 report project"
}
```

### Viewing User's Direct Permission Groups

```bash
curl -X GET "http://localhost:8000/permissions/users/usr-john789.../permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "user": {
    "hash": "usr-john789...",
    "username": "john_doe"
  },
  "direct_permission_groups": [
    {
      "group_hash": "pg-analytics456...",
      "group_name": "advanced_analytics",
      "assigned_at": "2024-01-15T10:30:00Z",
      "notes": "Special analytics access for Q1 report project"
    }
  ],
  "count": 1
}
```

### Removing Direct Assignment

```bash
curl -X DELETE "http://localhost:8000/permissions/users/usr-john789.../permission-groups/pg-analytics456..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

## Roles System

Roles provide a higher-level abstraction for assigning permission groups to users.

### Creating a Role

```bash
curl -X POST "http://localhost:8000/roles/roles" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_name=developer&role_display_name=Developer&role_description=Software developer role&role_priority=50"
```

**Response:**
```json
{
  "success": true,
  "message": "Role 'developer' created successfully",
  "role": {
    "role_hash": "role-dev123...",
    "role_name": "developer",
    "role_display_name": "Developer",
    "role_description": "Software developer role",
    "role_priority": 50
  }
}
```

### Listing Roles

```bash
curl -X GET "http://localhost:8000/roles/roles?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Getting Role Details

```bash
curl -X GET "http://localhost:8000/roles/roles/role-dev123..." \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "role": {
    "role_hash": "role-dev123...",
    "role_name": "developer",
    "role_display_name": "Developer",
    "role_description": "Software developer role",
    "role_priority": 50
  },
  "permission_groups": [
    {
      "group_hash": "pg-content123...",
      "group_name": "content_management"
    }
  ]
}
```

### Assigning Permission Group to Role

```bash
curl -X POST "http://localhost:8000/roles/roles/role-dev123.../permission-groups/pg-content123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Permission group 'content_management' assigned to role 'developer'"
}
```

### Getting Role's Permission Groups

```bash
curl -X GET "http://localhost:8000/roles/roles/role-dev123.../permission-groups" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Removing Permission Group from Role

**Scenario**: Remove a permission group from a role.

```bash
curl -X DELETE "http://localhost:8000/roles/roles/role-dev123.../permission-groups/pg-content123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Permission group 'content_management' removed from role 'developer'"
}
```

### Assigning Role to User

```bash
curl -X PUT "http://localhost:8000/roles/users/usr-john789.../role" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_hash=role-dev123..."
```

**Response:**
```json
{
  "success": true,
  "message": "Role 'developer' assigned to user 'john_doe'",
  "user": {
    "user_hash": "usr-john789...",
    "username": "john_doe"
  },
  "role": {
    "role_hash": "role-dev123...",
    "role_name": "developer"
  }
}
```

### Getting User's Role

```bash
curl -X GET "http://localhost:8000/roles/users/usr-john789.../role" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Removing Role from User

**Scenario**: Unassign a user's role.

```bash
curl -X DELETE "http://localhost:8000/roles/users/usr-john789.../role" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Role removed from user 'john_doe'",
  "user": {
    "user_hash": "usr-john789...",
    "username": "john_doe"
  },
  "previous_role": {
    "role_hash": "role-dev123...",
    "role_name": "developer"
  }
}
```

---

## Current User Queries

### Get My Role

```bash
curl -X GET "http://localhost:8000/roles/users/me/role" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "user": {
    "user_hash": "usr-john789...",
    "username": "john_doe"
  },
  "role": {
    "role_hash": "role-dev123...",
    "role_name": "developer",
    "role_display_name": "Developer"
  }
}
```

### Get My Permissions (All Sources)

```bash
curl -X GET "http://localhost:8000/permissions/users/me/permissions" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response:**
```json
{
  "user": {
    "hash": "usr-john789...",
    "username": "john_doe"
  },
  "permissions": [
    "read",
    "write",
    "create",
    "update",
    "api_access",
    "view_analytics",
    "export_reports"
  ],
  "count": 7
}
```

### Check Specific Permission

```bash
curl -X GET "http://localhost:8000/permissions/users/me/permissions/check/publish_content" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response:**
```json
{
  "user": {
    "hash": "usr-john789...",
    "username": "john_doe"
  },
  "permission": "publish_content",
  "has_permission": true
}
```

### Get My Permission Groups (Direct Only)

```bash
curl -X GET "http://localhost:8000/permissions/users/me/permission-groups" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response:**
```json
{
  "user": {
    "hash": "usr-john789...",
    "username": "john_doe"
  },
  "direct_permission_groups": [
    {
      "group_hash": "pg-analytics456...",
      "group_name": "advanced_analytics"
    }
  ],
  "count": 1
}
```

### Get Permission Sources Breakdown

```bash
curl -X GET "http://localhost:8000/permissions/users/me/permission-sources" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response:**
```json
{
  "user": {
    "hash": "usr-john789...",
    "username": "john_doe"
  },
  "sources": {
    "from_role": [
      {
        "source_type": "role",
        "role_name": "developer",
        "permission_group_name": "content_management"
      }
    ],
    "from_user_groups": [
      {
        "source_type": "user_group",
        "user_group_name": "mobile_team",
        "permission_group_name": "api_access"
      }
    ],
    "from_direct_assignment": [
      {
        "source_type": "direct",
        "permission_group_name": "advanced_analytics"
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

## Permission Group Catalog (Metadata)

The catalog system provides **metadata organization** - it helps you organize which permission groups are commonly used with which projects. **Important**: This does NOT restrict authorization - any permission group can be used with any project.

### Adding Permission Group to Project Catalog

**Scenario**: Associate a permission group with a project for organizational purposes.

```bash
curl -X POST "http://localhost:8000/permissions/projects/proj-xyz789.../permission-group-catalog/pg-content123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "catalog_purpose=Standard content team permissions&notes=Used by content department"
```

**Response:**
```json
{
  "message": "Permission group added to project catalog successfully",
  "note": "This is METADATA ONLY - not used for authorization",
  "project": {
    "hash": "proj-xyz789...",
    "name": "Content Platform"
  },
  "permission_group": {
    "hash": "pg-content123...",
    "name": "content_management"
  },
  "catalog_purpose": "Standard content team permissions"
}
```

### Viewing Project's Cataloged Permission Groups

**Scenario**: See which permission groups are cataloged for a project.

```bash
curl -X GET "http://localhost:8000/permissions/projects/proj-xyz789.../permission-group-catalog" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "project": {
    "hash": "proj-xyz789...",
    "name": "Content Platform"
  },
  "cataloged_permission_groups": [
    {
      "group_hash": "pg-content123...",
      "group_name": "content_management",
      "catalog_purpose": "Standard content team permissions",
      "added_at": "2024-01-15T10:30:00Z"
    },
    {
      "group_hash": "pg-api789...",
      "group_name": "api_access",
      "catalog_purpose": "API integration permissions",
      "added_at": "2024-01-16T14:00:00Z"
    }
  ],
  "count": 2,
  "note": "This is METADATA ONLY - any permission group can be used"
}
```

### Removing Permission Group from Project Catalog

```bash
curl -X DELETE "http://localhost:8000/permissions/projects/proj-xyz789.../permission-group-catalog/pg-content123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "message": "Permission group removed from project catalog successfully",
  "project": {
    "hash": "proj-xyz789...",
    "name": "Content Platform"
  },
  "permission_group": {
    "hash": "pg-content123...",
    "name": "content_management"
  }
}
```

### Viewing Permission Group's Cataloged Projects

**Scenario**: See which projects a permission group is cataloged in.

```bash
curl -X GET "http://localhost:8000/permissions/permissions/groups/pg-content123.../project-catalog" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "permission_group": {
    "hash": "pg-content123...",
    "name": "content_management"
  },
  "cataloged_in_projects": [
    {
      "project_hash": "proj-xyz789...",
      "project_name": "Content Platform",
      "catalog_purpose": "Standard content team permissions"
    },
    {
      "project_hash": "proj-abc456...",
      "project_name": "Blog System",
      "catalog_purpose": "Blog editors"
    }
  ],
  "count": 2,
  "note": "This permission group works in ALL projects, not just cataloged ones"
}
```

---

## Role Catalog (Metadata)

The Role Catalog system provides **metadata organization** for roles - it helps organize which global roles are commonly used or recommended for specific projects. **Important**: This does NOT affect authorization - any role can be assigned to any user.

### Adding Role to Project Catalog

**Scenario**: Associate a global role with a project for organizational purposes.

```bash
curl -X POST "http://localhost:8000/roles/projects/proj-xyz789.../catalog/roles/role-dev123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "catalog_purpose=Standard developer role&notes=Used by development team"
```

**Response:**
```json
{
  "success": true,
  "message": "Role added to project catalog successfully",
  "note": "This is METADATA ONLY - not used for authorization",
  "project": {
    "hash": "proj-xyz789...",
    "name": "Content Platform"
  },
  "role": {
    "role_hash": "role-dev123...",
    "role_name": "developer",
    "role_display_name": "Developer"
  },
  "catalog_purpose": "Standard developer role"
}
```

### Viewing Project's Cataloged Roles

**Scenario**: See which roles are suggested for a project.

```bash
curl -X GET "http://localhost:8000/roles/projects/proj-xyz789.../catalog/roles" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "project": {
    "hash": "proj-xyz789...",
    "name": "Content Platform"
  },
  "cataloged_roles": [
    {
      "role_hash": "role-dev123...",
      "role_name": "developer",
      "role_display_name": "Developer",
      "role_description": "Software developer role",
      "role_priority": 50,
      "is_system_role": false,
      "catalog_purpose": "Standard developer role",
      "notes": "Used by development team",
      "added_at": "2024-01-15T10:30:00Z",
      "added_by_username": "admin_user"
    }
  ],
  "count": 1,
  "note": "This is METADATA ONLY - any role can be assigned to users"
}
```

### Removing Role from Project Catalog

**Scenario**: Remove a role suggestion from a project.

```bash
curl -X DELETE "http://localhost:8000/roles/projects/proj-xyz789.../catalog/roles/role-dev123..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Role removed from project catalog successfully",
  "project": {
    "hash": "proj-xyz789...",
    "name": "Content Platform"
  },
  "role": {
    "role_hash": "role-dev123...",
    "role_name": "developer"
  }
}
```

---

## Permission Group Usage Queries

These endpoints help you understand where permission groups are being used.

### Get User Groups with Permission Group

**Scenario**: Find all user groups that have a specific permission group assigned.

```bash
curl -X GET "http://localhost:8000/permissions/permissions/groups/pg-content123.../user-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "permission_group": {
    "hash": "pg-content123...",
    "name": "content_management"
  },
  "user_groups": [
    {
      "group_hash": "grp-editors123...",
      "group_name": "editors",
      "assigned_at": "2024-01-15T10:30:00Z"
    },
    {
      "group_hash": "grp-content456...",
      "group_name": "content_team",
      "assigned_at": "2024-01-20T14:00:00Z"
    }
  ],
  "count": 2
}
```

### Get Users with Permission Group (Direct)

**Scenario**: Find all users that have a specific permission group directly assigned (not through user groups).

```bash
curl -X GET "http://localhost:8000/permissions/permissions/groups/pg-analytics456.../users" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "permission_group": {
    "hash": "pg-analytics456...",
    "name": "advanced_analytics"
  },
  "users": [
    {
      "user_hash": "usr-john789...",
      "username": "john_doe",
      "assigned_at": "2024-01-15T10:30:00Z",
      "notes": "Special analytics access for Q1 report"
    }
  ],
  "count": 1
}
```

---

## Common Scenarios

### Scenario 1: Setting Up a New Team with Permissions

**Goal**: Create a QA team with testing permissions.

```bash
# Step 1: Create Permission Group for QA
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=qa_testing&group_display_name=QA Testing Permissions&group_category=testing"

# Step 2: Add Permissions to Group
curl -X POST "http://localhost:8000/roles/permission-groups/$QA_GROUP_HASH/permissions/$READ_PERM_HASH" \
  -H "Authorization: Bearer $TOKEN"

curl -X POST "http://localhost:8000/roles/permission-groups/$QA_GROUP_HASH/permissions/$WRITE_PERM_HASH" \
  -H "Authorization: Bearer $TOKEN"

curl -X POST "http://localhost:8000/roles/permission-groups/$QA_GROUP_HASH/permissions/$BUG_REPORT_PERM_HASH" \
  -H "Authorization: Bearer $TOKEN"

# Step 3: Create User Group (if doesn't exist)
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=qa_team&description=Quality Assurance Team"

# Step 4: Assign Permission Group to User Group
curl -X POST "http://localhost:8000/permissions/admin/user-groups/$USER_GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=$QA_PERMISSION_GROUP_HASH"

# Step 5: Add Team Members
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_hashes": ["usr-qa1", "usr-qa2", "usr-qa3"]}'
```

### Scenario 2: Temporary Special Access for Individual User

**Goal**: Give a user temporary admin access for migration project.

```bash
# Step 1: Check Current Permissions
curl -X GET "http://localhost:8000/permissions/users/usr-john789.../permission-groups" \
  -H "Authorization: Bearer $TOKEN"

# Step 2: Assign Temporary Permission Group
curl -X POST "http://localhost:8000/permissions/users/usr-john789.../permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=pg-admin-ops-456...&notes=Temporary admin access for database migration - expires 2024-03-01"

# Step 3: After Project Completion - Remove Access
curl -X DELETE "http://localhost:8000/permissions/users/usr-john789.../permission-groups/pg-admin-ops-456..." \
  -H "Authorization: Bearer $TOKEN"
```

### Scenario 3: Departmental Permission Structure

**Goal**: Set up hierarchical permissions for engineering department.

**Permission Groups:**
- `engineering_basic` - Read/write code
- `engineering_deploy` - Deployment permissions
- `engineering_admin` - Full engineering admin

**User Groups:**
- `junior_engineers` → `engineering_basic`
- `senior_engineers` → `engineering_basic` + `engineering_deploy`
- `engineering_leads` → `engineering_basic` + `engineering_deploy` + `engineering_admin`

```bash
# Assign basic to junior engineers
curl -X POST "http://localhost:8000/permissions/admin/user-groups/grp-junior-eng.../permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=pg-eng-basic..."

# Assign basic + deploy to senior engineers
curl -X POST "http://localhost:8000/permissions/admin/user-groups/grp-senior-eng.../permission-groups/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hashes=pg-eng-basic...&permission_group_hashes=pg-eng-deploy..."

# Assign all three to engineering leads
curl -X POST "http://localhost:8000/permissions/admin/user-groups/grp-eng-leads.../permission-groups/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hashes=pg-eng-basic...&permission_group_hashes=pg-eng-deploy...&permission_group_hashes=pg-eng-admin..."
```

### Scenario 4: Role-Based Access Control

**Goal**: Use roles for standard job functions.

```bash
# Step 1: Create Role
curl -X POST "http://localhost:8000/roles/roles" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_name=content_editor&role_display_name=Content Editor&role_description=Editor role for content management&role_priority=40"

# Step 2: Assign Permission Groups to Role
curl -X POST "http://localhost:8000/roles/roles/$ROLE_HASH/permission-groups/$CONTENT_PG_HASH" \
  -H "Authorization: Bearer $TOKEN"

curl -X POST "http://localhost:8000/roles/roles/$ROLE_HASH/permission-groups/$PUBLISH_PG_HASH" \
  -H "Authorization: Bearer $TOKEN"

# Step 3: Assign Role to Users
curl -X PUT "http://localhost:8000/roles/users/usr-editor1.../role" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_hash=$ROLE_HASH"

curl -X PUT "http://localhost:8000/roles/users/usr-editor2.../role" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_hash=$ROLE_HASH"
```

---

## Best Practices

### Permission Group Design

**Good Permission Groups:**
- `content_management` - Clear, specific purpose
- `api_full_access` - Descriptive name
- `data_export_tools` - Indicates functionality
- `admin_user_management` - Scoped admin permissions

**Bad Permission Groups:**
- `group1` - Not descriptive
- `misc_perms` - Too vague
- `everything` - Too broad
- `temp` - Unclear purpose

### Naming Conventions

**Permission Groups:**
```
{function}_{level/type}

Examples:
- content_management
- api_access
- data_export
- admin_operations
- read_only_access
```

**Categories:**
- `admin` - Administrative functions
- `data` - Data operations
- `api` - API-related
- `content` - Content management
- `analytics` - Analytics and reporting
- `testing` - Testing and QA

### Assignment Strategy

**Primary Model (Recommended):**
```
Use user groups for team-based permissions
→ Scalable
→ Easy to manage
→ Consistent across team members
```

**Secondary Model (Special Cases Only):**
```
Use direct assignments for:
→ Temporary special access
→ Individual exceptions
→ VIP/special role users
→ Transition periods
```

**Role-Based Model (Job Functions):**
```
Use roles for:
→ Standard job functions
→ Consistent permission sets per job title
→ Easier onboarding
```

### Security Best Practices

1. **Least Privilege**
   - Start with minimum permissions
   - Add permissions as needed
   - Review and remove unused permissions

2. **Regular Audits**
   - Monthly: Review direct assignments
   - Quarterly: Review user group assignments
   - Annually: Review all permission groups

3. **Documentation**
   - Document why permission groups exist
   - Note special/temporary assignments
   - Track permission changes

4. **Separation of Duties**
   - Don't give everyone admin permissions
   - Create role-specific permission groups
   - Use multiple smaller groups vs one large group

---

## Troubleshooting

### User Doesn't Have Expected Permission

**Check Steps:**

1. **Check User's Direct Permission Groups**
```bash
curl -X GET "http://localhost:8000/permissions/users/$USER_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

2. **Check User's User Groups**
```bash
curl -X GET "http://localhost:8000/admin/user-groups/users/$USER_HASH/groups" \
  -H "Authorization: Bearer $TOKEN"
```

3. **Check User Group's Permission Groups**
```bash
curl -X GET "http://localhost:8000/permissions/admin/user-groups/$GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

4. **Check User's Role**
```bash
curl -X GET "http://localhost:8000/roles/users/$USER_HASH/role" \
  -H "Authorization: Bearer $TOKEN"
```

5. **Check Permission Group Contents**
```bash
curl -X GET "http://localhost:8000/roles/permission-groups/$PG_HASH/permissions" \
  -H "Authorization: Bearer $TOKEN"
```

### Permission Check Returns False

**Common Causes:**

1. **Permission doesn't exist in any assigned permission group**
   - Solution: Add permission to relevant permission group

2. **User not in user group that has the permission group**
   - Solution: Add user to correct user group

3. **Permission group not assigned to user or their groups**
   - Solution: Assign permission group

4. **User needs to re-login**
   - Solution: Sessions cache permissions, re-login refreshes

---

## Quick Reference

### Permission Group Operations

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Create permission group | `/roles/permission-groups` | POST |
| List permission groups | `/roles/permission-groups` | GET |
| Get permission group | `/roles/permission-groups/{hash}` | GET |
| Update permission group | `/roles/permission-groups/{hash}` | PUT |
| Delete permission group | `/roles/permission-groups/{hash}` | DELETE |
| Add permission to group | `/roles/permission-groups/{hash}/permissions/{perm_hash}` | POST |
| Remove permission from group | `/roles/permission-groups/{hash}/permissions/{perm_hash}` | DELETE |
| Get group permissions | `/roles/permission-groups/{hash}/permissions` | GET |

### Permission Operations

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Create permission | `/roles/permissions` | POST |
| List permissions | `/roles/permissions` | GET |
| Get permission | `/roles/permissions/{hash}` | GET |
| Update permission | `/roles/permissions/{hash}` | PUT |
| Delete permission | `/roles/permissions/{hash}` | DELETE |

### Role Operations

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Create role | `/roles/roles` | POST |
| List roles | `/roles/roles` | GET |
| Get role | `/roles/roles/{hash}` | GET |
| Update role | `/roles/roles/{hash}` | PUT |
| Delete role | `/roles/roles/{hash}` | DELETE |
| Assign permission group to role | `/roles/roles/{hash}/permission-groups/{pg_hash}` | POST |
| Remove permission group from role | `/roles/roles/{hash}/permission-groups/{pg_hash}` | DELETE |
| Get role permission groups | `/roles/roles/{hash}/permission-groups` | GET |
| Assign role to user | `/roles/users/{user_hash}/role` | PUT |
| Get user role | `/roles/users/{user_hash}/role` | GET |
| Remove role from user | `/roles/users/{user_hash}/role` | DELETE |

### User Group Assignment Operations

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Assign to user group | `/permissions/admin/user-groups/{hash}/permission-groups` | POST |
| Remove from user group | `/permissions/admin/user-groups/{hash}/permission-groups/{pg_hash}` | DELETE |
| List user group's groups | `/permissions/admin/user-groups/{hash}/permission-groups` | GET |
| Bulk assign | `/permissions/admin/user-groups/{hash}/permission-groups/bulk` | POST |

### Direct User Assignment Operations

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Assign to user | `/permissions/users/{user_hash}/permission-groups` | POST |
| Remove from user | `/permissions/users/{user_hash}/permission-groups/{pg_hash}` | DELETE |
| List user's groups | `/permissions/users/{user_hash}/permission-groups` | GET |

### Current User Query Operations

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Get my role | `/roles/users/me/role` | GET |
| Get my permissions | `/permissions/users/me/permissions` | GET |
| Check my permission | `/permissions/users/me/permissions/check/{permission}` | GET |
| Get my permission groups | `/permissions/users/me/permission-groups` | GET |
| Get my permission sources | `/permissions/users/me/permission-sources` | GET |

### Permission Group Catalog Operations (Metadata Only)

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Add to project catalog | `/permissions/projects/{hash}/permission-group-catalog/{pg_hash}` | POST |
| Remove from project catalog | `/permissions/projects/{hash}/permission-group-catalog/{pg_hash}` | DELETE |
| Get project's cataloged groups | `/permissions/projects/{hash}/permission-group-catalog` | GET |
| Get group's cataloged projects | `/permissions/permissions/groups/{pg_hash}/project-catalog` | GET |

### Permission Group Usage Queries

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Get user groups with permission group | `/permissions/permissions/groups/{pg_hash}/user-groups` | GET |
| Get users with permission group (direct) | `/permissions/permissions/groups/{pg_hash}/users` | GET |

### Role Catalog Operations (Metadata Only)

| Operation | Endpoint | Method |
|-----------|----------|--------|
| Add role to project catalog | `/roles/projects/{hash}/catalog/roles/{role_hash}` | POST |
| Remove role from project catalog | `/roles/projects/{hash}/catalog/roles/{role_hash}` | DELETE |
| Get project's cataloged roles | `/roles/projects/{hash}/catalog/roles` | GET |

---

## Related Documentation

- **[Groups Usage Cases](groups-usage-cases.md)** - User group and project group management
- **[Projects Usage Cases](projects-usage-cases.md)** - Project management scenarios

---

**Last Updated**: December 2024
**Document Version**: 2.1
