# User Management Usage Guide

Complete practical guide for managing user profiles, accessing user information, and performing administrative user operations.

---

## 📖 Table of Contents

- [User Management Overview](#user-management-overview)
- [User Profile Operations](#user-profile-operations)
- [Access Summary](#access-summary)
- [Admin User Operations](#admin-user-operations)
- [User Search and Listing](#user-search-and-listing)
- [Common Scenarios](#common-scenarios)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## User Management Overview

The user management system provides endpoints for:
- **Self-service**: Users managing their own profiles
- **Admin operations**: Admins managing other users
- **Access queries**: Understanding hierarchical access through groups

### User Types

| Type | Description | Permissions |
|------|-------------|-------------|
| `root` | System administrators | Full access to all operations |
| `admin` | Project administrators | Manage users in their projects |
| `consumer` | Regular users | Self-service profile management |

---

## User Profile Operations

### Get Current User Profile

**Scenario**: View your own profile information with group memberships.

```bash
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "user_hash": "usr-abc123...",
  "username": "john_doe",
  "email": "john@example.com",
  "user_type": "consumer",
  "user_type_info": {
    "role_name": "Developer",
    "role_hash": "role-dev123...",
    "permission_groups": ["content_management", "basic_access"]
  },
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-03-20T14:45:00Z",
  "last_login": "2024-03-25T09:00:00Z",
  "is_active": true,
  "groups": [
    {
      "group_hash": "grp-dev123...",
      "group_name": "developers",
      "group_description": "Development team",
      "assigned_at": "2024-01-15T10:30:00Z",
      "assigned_by": "admin"
    }
  ],
  "projects": [
    {
      "project_hash": "proj-xyz789...",
      "project_name": "API v2",
      "project_description": "Main API project",
      "project_group": "backend-services",
      "permissions": ["read", "write", "manage_content"]
    }
  ]
}
```

### Update User Profile

**Scenario**: Update your username, email, or password.

```bash
# Update username
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_username"

# Update email
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=newemail@example.com"

# Update password
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "password=NewSecurePassword123!"

# Update multiple fields
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_username&email=newemail@example.com"
```

**Response:**
```json
{
  "success": true,
  "message": "Profile updated successfully",
  "user": {
    "user_hash": "usr-abc123...",
    "username": "new_username",
    "email": "newemail@example.com",
    "user_type": "consumer",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-03-25T10:00:00Z"
  }
}
```

---

## Access Summary

### Get Complete Access Summary

**Scenario**: View your complete hierarchical access including all groups, projects, and permissions.

```bash
curl -X GET "http://localhost:8000/users/access-summary" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "access_summary": {
    "user": {
      "user_hash": "usr-abc123...",
      "username": "john_doe",
      "user_type": "consumer",
      "user_type_details": {
        "role_name": "Developer",
        "role_hash": "role-dev123..."
      },
      "email": "john@example.com"
    },
    "user_groups": [
      {
        "group_hash": "grp-dev123...",
        "group_name": "developers",
        "group_description": "Development team",
        "assigned_at": "2024-01-15T10:30:00Z",
        "assigned_by": "admin",
        "projects_count": 3
      }
    ],
    "accessible_projects": [
      {
        "project_hash": "proj-xyz789...",
        "project_name": "API v2",
        "project_description": "Main API project",
        "access_groups": [
          {
            "group_hash": "grp-dev123...",
            "group_name": "developers",
            "permissions": ["read", "write"]
          }
        ],
        "effective_permissions": ["read", "write", "manage_content"]
      }
    ],
    "current_session": {
      "project_hash": "proj-xyz789...",
      "project_name": "API v2",
      "permissions": ["read", "write", "manage_content"],
      "expires_at": null
    },
    "summary": {
      "total_groups": 1,
      "total_projects": 3,
      "is_admin": false
    }
  }
}
```

---

## Admin User Operations

### Get User Details (Admin)

**Scenario**: Admin views detailed information about a specific user.

```bash
curl -X GET "http://localhost:8000/users/usr-target456..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# With additional details
curl -X GET "http://localhost:8000/users/usr-target456...?include_group_hierarchy=true&include_permission_details=true" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "user": {
    "user_hash": "usr-target456...",
    "username": "jane_doe",
    "email": "jane@example.com",
    "user_type": "consumer",
    "user_type_info": {
      "role_name": "Viewer",
      "role_hash": "role-view123..."
    },
    "created_at": "2024-02-01T10:00:00Z",
    "updated_at": "2024-03-15T14:30:00Z",
    "last_login": "2024-03-24T08:00:00Z",
    "is_active": true,
    "groups": [
      {
        "group_hash": "grp-qa123...",
        "group_name": "qa_team",
        "group_description": "QA Team",
        "assigned_at": "2024-02-01T10:00:00Z",
        "projects_count": 2
      }
    ],
    "projects": [
      {
        "project_hash": "proj-abc123...",
        "project_name": "Test Project",
        "effective_permissions": ["read", "test"],
        "access_groups": [
          {
            "group_hash": "grp-qa123...",
            "group_name": "qa_team"
          }
        ]
      }
    ]
  }
}
```

### Update User Status

**Scenario**: Activate or deactivate a user account.

```bash
# Deactivate user
curl -X PUT "http://localhost:8000/users/usr-target456.../status?is_active=false" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Activate user
curl -X PUT "http://localhost:8000/users/usr-target456.../status?is_active=true" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "User jane_doe has been deactivated",
  "user_hash": "usr-target456...",
  "is_active": false
}
```

### Reset User Password

**Scenario**: Admin resets a user's password.

```bash
curl -X POST "http://localhost:8000/users/usr-target456.../reset-password" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Password reset successfully",
  "user": {
    "user_hash": "usr-target456...",
    "username": "jane_doe",
    "email": "jane@example.com"
  },
  "reset_data": {
    "temporary_password": "TempPass#123456",
    "expires_at": "2024-03-26T10:00:00Z",
    "must_change_on_login": true
  },
  "instructions": "User must change password on next login"
}
```

### Delete User

**Scenario**: Admin deletes (soft-delete) a user.

```bash
curl -X DELETE "http://localhost:8000/users/usr-target456..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "User 'jane_doe' has been deleted",
  "user_hash": "usr-target456...",
  "username": "jane_doe",
  "deleted_at": "2024-03-25T10:30:00Z"
}
```

---

## User Search and Listing

### List All Users

**Scenario**: Admin lists users with filtering and pagination.

```bash
# Basic listing
curl -X GET "http://localhost:8000/users/list" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# With filters
curl -X GET "http://localhost:8000/users/list?limit=25&offset=0&sort_by=username&sort_order=asc&user_type_filter=consumer&include_inactive=false" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Filter by group
curl -X GET "http://localhost:8000/users/list?group_filter=developers" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Filter by project
curl -X GET "http://localhost:8000/users/list?project_filter=proj-xyz789..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Search by name/email
curl -X GET "http://localhost:8000/users/list?search=john" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "users": [
    {
      "user_hash": "usr-abc123...",
      "username": "john_doe",
      "email": "john@example.com",
      "user_type": "consumer",
      "user_type_info": {
        "role_name": "Developer"
      },
      "created_at": "2024-01-15T10:30:00Z",
      "last_login": "2024-03-25T09:00:00Z",
      "is_active": true,
      "groups": [
        {
          "group_hash": "grp-dev123...",
          "group_name": "developers"
        }
      ],
      "projects": [
        {
          "project_hash": "proj-xyz789...",
          "project_name": "API v2",
          "permissions": ["read", "write"]
        }
      ]
    }
  ],
  "pagination": {
    "total": 150,
    "limit": 25,
    "offset": 0,
    "has_more": true
  },
  "filters": {
    "user_type_filter": "consumer",
    "group_filter": null,
    "project_filter": null,
    "search": null,
    "include_inactive": false
  }
}
```

### Search Users

**Scenario**: Quick search for users by username or email.

```bash
curl -X GET "http://localhost:8000/users/search/query?q=john&limit=50" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# With user type filter
curl -X GET "http://localhost:8000/users/search/query?q=admin@&user_type_filter=admin" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "users": [
    {
      "user_hash": "usr-abc123...",
      "username": "john_doe",
      "email": "john@example.com",
      "user_type": "consumer",
      "created_at": "2024-01-15T10:30:00Z",
      "last_login": "2024-03-25T09:00:00Z",
      "is_active": true
    }
  ],
  "search_term": "john",
  "total_results": 1,
  "filters": {
    "user_type_filter": null,
    "limit": 50
  }
}
```

---

## Common Scenarios

### Scenario 1: User Self-Service Profile Management

**Goal**: User checks and updates their own profile.

```bash
# Step 1: Get current profile
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $TOKEN"

# Step 2: Update email
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=newemail@example.com"

# Step 3: Change password
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "password=NewSecurePassword123!"
```

### Scenario 2: Admin Onboarding New Employee

**Goal**: Admin sets up a new user with proper access.

```bash
# Step 1: Check if username is available
curl -X POST "http://localhost:8000/auth/check-availability" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_employee&email=new@company.com"

# Step 2: Create user via registration or admin API
# (Using registration endpoint with known group hash)

# Step 3: Verify user is set up correctly
curl -X GET "http://localhost:8000/users/usr-newemployee...?include_group_hierarchy=true" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 4: Add to additional groups if needed
curl -X POST "http://localhost:8000/admin/user-groups/grp-additional.../members" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hash=usr-newemployee..."
```

### Scenario 3: Admin Offboarding Employee

**Goal**: Admin revokes access for departing employee.

```bash
# Step 1: Check user's current access
curl -X GET "http://localhost:8000/users/usr-leaving..." \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: Deactivate the user (preferred over deletion)
curl -X PUT "http://localhost:8000/users/usr-leaving.../status?is_active=false" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Note: User is soft-deleted, preserving audit trail
# Their sessions are automatically invalidated
# Their cache is cleared
```

### Scenario 4: Finding Users in a Specific Project

**Goal**: Admin lists all users with access to a project.

```bash
# Method 1: Filter user list by project
curl -X GET "http://localhost:8000/users/list?project_filter=proj-target123..." \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Method 2: Get project members directly
curl -X GET "http://localhost:8000/projects/proj-target123.../members" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### Scenario 5: Audit User Access

**Goal**: Check what a specific user can access.

```bash
# Get complete access summary
curl -X GET "http://localhost:8000/users/usr-target456..." \
  -H "Authorization: Bearer $ADMIN_TOKEN" | jq '.user | {groups, projects}'
```

---

## Best Practices

### Profile Management

1. **Regular password changes** - Encourage users to update passwords periodically
2. **Use strong passwords** - Enforce password complexity requirements
3. **Monitor last_login** - Track inactive accounts

### Admin Operations

1. **Deactivate, don't delete** - Use deactivation to preserve audit trail
2. **Use groups for access** - Manage access through groups, not individual assignments
3. **Regular access reviews** - Periodically review user access

### Security

1. **Minimal privilege** - Assign only necessary permissions
2. **Password resets** - Force password change after reset
3. **Track changes** - Monitor user modifications in activity logs

---

## Troubleshooting

### Profile Update Fails

**Error**: "Failed to update user profile"

**Solutions**:
1. Check the field values are valid
2. Ensure username/email doesn't conflict with existing users
3. Verify you're updating your own profile (not another user's)

### Access Denied

**Error**: "Access denied: Admin privileges required"

**Solutions**:
1. Use an admin or root account
2. Check you have the correct permissions
3. Verify the target user is in your accessible projects (for admin users)

### User Not Found

**Error**: "User not found"

**Solutions**:
1. Verify the user_hash is correct
2. Check if the user has been deleted
3. Confirm the user exists in the system

---

## User Type Management

### Change User Type

**Scenario**: ROOT user promotes/demotes a user to a different type.

```bash
curl -X PATCH "http://localhost:8000/users/usr-target456.../type" \
  -H "Authorization: Bearer YOUR_ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_type=admin"
```

**Response:**
```json
{
  "success": true,
  "message": "User type changed successfully",
  "user_hash": "usr-target456...",
  "previous_type": "consumer",
  "new_type": "admin"
}
```

**Note**: This is a sensitive operation. Only ROOT users can change user types.

### Update User Details (Admin)

**Scenario**: Admin or ROOT user updates another user's details.

```bash
# Update username
curl -X PUT "http://localhost:8000/users/usr-target456..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_username"

# Update email
curl -X PUT "http://localhost:8000/users/usr-target456..." \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=newemail@example.com"

# Update multiple fields (ROOT only can change user_type)
curl -X PUT "http://localhost:8000/users/usr-target456..." \
  -H "Authorization: Bearer YOUR_ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=updated_user&email=updated@example.com&user_type=admin"
```

**Response:**
```json
{
  "success": true,
  "message": "User updated successfully",
  "user": {
    "user_hash": "usr-target456...",
    "username": "updated_user",
    "email": "updated@example.com",
    "user_type": "admin",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-03-25T10:30:00Z"
  },
  "updated_at": "2024-03-25T10:30:00Z"
}
```

---

## Quick Reference

### User Endpoints

| Operation | Endpoint | Method | Permission |
|-----------|----------|--------|------------|
| Get profile | `/users/profile` | GET | Any authenticated |
| Update profile | `/users/profile` | PUT | Any authenticated |
| Access summary | `/users/access-summary` | GET | Any authenticated |
| List users | `/users/list` | GET | Admin/Root |
| Search users | `/users/search/query` | GET | Admin/Root |
| Get user details | `/users/{user_hash}` | GET | Admin/Root (or own) |
| Update user details | `/users/{user_hash}` | PUT | Admin/Root |
| Change user type | `/users/{user_hash}/type` | PATCH | Root only |
| Update status | `/users/{user_hash}/status` | PUT | Admin/Root |
| Reset password | `/users/{user_hash}/reset-password` | POST | Admin/Root |
| Delete user | `/users/{user_hash}` | DELETE | Admin/Root |

### Query Parameters for Listing

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| limit | int | Max results per page | 100 |
| offset | int | Skip results for pagination | 0 |
| sort_by | string | Field to sort by | username |
| sort_order | string | asc or desc | asc |
| search | string | Search in username/email | null |
| user_type_filter | string | root, admin, consumer | null |
| group_filter | string | Filter by group hash/name | null |
| project_filter | string | Filter by project hash/name | null |
| include_inactive | bool | Include deactivated users | false |
| include_group_info | bool | Include group memberships | true |
| include_project_access | bool | Include project access info | true |

---

## Related Documentation

- **[Authentication Usage Cases](authentication-usage-cases.md)** - Login, logout, session management
- **[Groups Usage Cases](groups-usage-cases.md)** - User group management
- **[Permissions Usage Cases](permissions-usage-cases.md)** - Permission management

---

**Last Updated**: December 2024
**Document Version**: 1.0
