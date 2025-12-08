# User Management

Complete documentation for user management in the Magic Auth system.

---

## Table of Contents

1. [Overview](#overview)
2. [User Types](#user-types)
3. [Tables](#tables)
4. [Stored Procedures](#stored-procedures)
5. [User Group Membership](#user-group-membership)
6. [Password Management](#password-management)
7. [Session Management](#session-management)
8. [Common Operations](#common-operations)

---

## Overview

The user management system supports a **3-tier user type hierarchy** with group-based access control. Users do not have direct project access - all access flows through user groups.

### Key Principles

- **No Direct Project Access**: Users access projects via User Groups → Project Groups
- **One Global Role**: Each user can have one assigned global role
- **Group Membership**: Users can belong to multiple user groups
- **Soft Deletes**: User deletion is soft (is_active = FALSE)

---

## User Types

| Type | Priority | Description | Project Access |
|------|----------|-------------|----------------|
| `root` | Highest | Super administrator | All projects (automatic) |
| `admin` | Medium | Project administrator | Via group membership |
| `consumer` | Standard | Regular user | Via group membership |

### Root Users

- Have automatic access to ALL active, non-archived projects
- Bypass all permission checks
- Can perform any operation
- Should be limited in production

### Admin Users

- Typically manage specific projects or project groups
- Access determined by user group memberships
- Can have elevated permissions via roles

### Consumer Users

- Standard end users
- Access strictly controlled by group membership
- Most restrictive by default

---

## Tables

### Primary Table: `users`

```sql
CREATE TABLE users (
    id VARCHAR(64) NOT NULL,                    -- Internal ID (UUID format)
    user_hash VARCHAR(255) NOT NULL,            -- Public identifier
    username VARCHAR(100) NOT NULL,             -- Unique username
    email VARCHAR(255),                         -- Email address
    password_hash VARCHAR(255) NOT NULL,        -- Hashed password
    user_type ENUM('root', 'admin', 'consumer') NOT NULL DEFAULT 'consumer',
    role_id VARCHAR(64) NULL,                   -- Global role assignment
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login DATETIME NULL,                   -- Last login timestamp
    updated_at DATETIME,                        -- Last update timestamp
    created_by VARCHAR(64),                     -- Creator user ID
    is_active BOOLEAN NOT NULL DEFAULT TRUE,    -- Soft delete flag
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_hash (user_hash),
    UNIQUE KEY uk_username (username)
);
```

### Related Tables

| Table | Purpose |
|-------|---------|
| `user_group_members` | User → User Group membership |
| `user_sessions` | Active user sessions |
| `user_password_resets` | Password reset tokens |
| `user_permission_groups` | Direct permission assignments (exceptions) |

---

## Stored Procedures

### Authentication

| Procedure | Parameters | Description |
|-----------|------------|-------------|
| `sp_user_login` | `p_username_email` | Authenticate by username or email |
| `sp_update_last_login` | `p_user_id` | Update last login timestamp |

**Login Example:**
```sql
CALL sp_user_login('john.doe');
-- Returns: id, user_hash, username, email, password_hash, user_type, role_id, created_at, last_login, is_active
```

### User Retrieval

| Procedure | Parameters | Description |
|-----------|------------|-------------|
| `sp_get_user_by_id` | `p_user_id` | Get user by internal ID |
| `sp_get_user_by_hash` | `p_user_hash, p_include_inactive` | Get user by public hash |
| `sp_get_user_type` | `p_user_id` | Get user's type only |
| `sp_get_user_status` | `p_user_id` | Get user's active status |

**Get User Example:**
```sql
CALL sp_get_user_by_hash('usr-abc123', 0);  -- Active only
CALL sp_get_user_by_hash('usr-abc123', 1);  -- Include inactive
```

### User Creation

| Procedure | Parameters | Description |
|-----------|------------|-------------|
| `sp_create_consumer_user` | `id, hash, username, email, password_hash, created_by` | Create consumer |
| `sp_create_admin_user` | `id, hash, username, email, password_hash, created_by` | Create admin |
| `sp_create_root_user` | `id, hash, username, email, password_hash, created_by` | Create root |
| `sp_check_username_email_available` | `p_username_or_email` | Check availability |

**Create User Example:**
```sql
-- Check availability first
CALL sp_check_username_email_available('newuser');
-- Returns: count (0 = available)

-- Create consumer user
CALL sp_create_consumer_user(
    'usr-uuid-here',
    'usr-hash-here',
    'newuser',
    'newuser@example.com',
    'hashed_password_here',
    'creator-user-id'
);
```

### User Updates

| Procedure | Parameters | Description |
|-----------|------------|-------------|
| `sp_update_user` | `id, username, email, password_hash, user_type` | Update profile (NULL = keep) |
| `sp_update_user_type` | `id, new_user_type` | Change user type |
| `sp_update_password_hash` | `id, new_password_hash` | Update password |
| `sp_set_user_status` | `id, is_active` | Activate/deactivate |

**Update Example:**
```sql
-- Update only email (other fields NULL = unchanged)
CALL sp_update_user('user-id', NULL, 'newemail@example.com', NULL, NULL);

-- Change user type to admin
CALL sp_update_user_type('user-id', 'admin');

-- Deactivate user
CALL sp_set_user_status('user-id', FALSE);
```

### User Deletion

| Procedure | Parameters | Description |
|-----------|------------|-------------|
| `sp_delete_user` | `p_user_id` | Soft-delete user and memberships |

**Delete Example:**
```sql
CALL sp_delete_user('user-id');
-- Sets is_active = FALSE on user
-- Sets is_active = FALSE on all group memberships
```

### User Listing & Search

| Procedure | Parameters | Description |
|-----------|------------|-------------|
| `sp_list_users` | `limit, offset, sort_by, sort_order, search, user_type_filter, group_filter, project_filter, include_inactive` | List with filters |
| `sp_list_users_with_access` | Same as above | List with group/project JSON |
| `sp_count_users` | `user_type, include_inactive` | Count users |
| `sp_search_users` | `search_term, user_type, limit` | Quick search |
| `sp_get_recent_users_count` | `days` | Count recent registrations |

**List Examples:**
```sql
-- List first 20 active users, sorted by username
CALL sp_list_users(20, 0, 'username', 'asc', NULL, NULL, NULL, NULL, FALSE);

-- Search admins named "john"
CALL sp_list_users(20, 0, 'username', 'asc', 'john', 'admin', NULL, NULL, FALSE);

-- List users in specific group
CALL sp_list_users(20, 0, 'username', 'asc', NULL, NULL, 'Developers', NULL, FALSE);

-- List with full access details (groups and projects as JSON)
CALL sp_list_users_with_access(20, 0, 'username', 'asc', NULL, NULL, NULL, NULL, FALSE);

-- Count all active consumers
CALL sp_count_users('consumer', FALSE);

-- Quick search
CALL sp_search_users('john', NULL, 10);

-- Users created in last 7 days
CALL sp_get_recent_users_count(7);
```

---

## User Group Membership

Users access projects through group membership. See [permissions.md](permissions.md) for full details.

### Group Membership Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_assign_user_to_group` | Add user to user group |
| `sp_remove_user_from_group` | Remove user from user group |
| `sp_get_users_in_group` | Get all users in a group |
| `sp_get_user_groups_for_user` | Get all groups a user belongs to |
| `sp_check_user_in_group` | Check if user is member |

**Membership Examples:**
```sql
-- Add user to group
CALL sp_assign_user_to_group('member-id', 'user-id', 'group-id', 'assigned-by-id');

-- Remove user from group
CALL sp_remove_user_from_group('user-id', 'group-id', 'removed-by-id');

-- Get user's groups
CALL sp_get_user_groups_for_user('user-id');

-- Check membership
CALL sp_check_user_in_group('user-id', 'group-id');
-- Returns: is_member (1 or 0)
```

---

## Password Management

### Password Reset Table

```sql
CREATE TABLE user_password_resets (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    reset_token VARCHAR(255) NOT NULL,
    temporary_password_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP NULL,
    created_by VARCHAR(64) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);
```

### Password Update

```sql
-- Update password directly
CALL sp_update_password_hash('user-id', 'new_hashed_password');
```

---

## Session Management

### Sessions Table

```sql
CREATE TABLE user_sessions (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,          -- Session is project-specific
    session_token VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_session_token (session_token)
);
```

### Session Validation Trigger

The `tr_validate_session_expiry` trigger automatically validates:
1. Session expiry is in the future
2. User exists and is active
3. Project exists and is active
4. User has access to the project (root users bypass, others via groups)

### Session Cleanup

```sql
-- Clean expired sessions
CALL sp_cleanup_expired_sessions();
```

---

## Common Operations

### Create New User Flow

```sql
-- 1. Check username/email availability
CALL sp_check_username_email_available('newuser');
CALL sp_check_username_email_available('newuser@example.com');

-- 2. Create user (application generates ID, hash, and password hash)
CALL sp_create_consumer_user(
    'usr-550e8400-e29b-41d4-a716-446655440001',
    'usr-hash-generated',
    'newuser',
    'newuser@example.com',
    'bcrypt_hashed_password',
    'creator-user-id'
);

-- 3. Assign to user group for project access
CALL sp_assign_user_to_group(
    'member-uuid',
    'usr-550e8400-e29b-41d4-a716-446655440001',
    'default-user-group-id',
    'creator-user-id'
);

-- 4. Optionally assign a global role
CALL sp_global_assign_role_to_user(
    'usr-550e8400-e29b-41d4-a716-446655440001',
    'standard-user-role-id'
);
```

### Get User With Full Context

```sql
-- Get user basic info
CALL sp_get_user_by_hash('usr-hash');

-- Get user's groups
CALL sp_get_user_groups_for_user('user-id');

-- Get user's accessible projects
CALL sp_get_user_accessible_projects('user-id');

-- Get user's role
CALL sp_global_get_user_role('user-id');

-- Get user's all permissions (from all sources)
CALL sp_get_user_all_permissions('user-id');

-- Get permission sources breakdown
CALL sp_get_user_permission_sources('user-id');
```

### Check User Project Access

```sql
-- Simple access check
CALL sp_check_user_project_access('user-id', 'project-id');
-- Returns: has_access (1 or 0)

-- Get the access path (which groups grant access)
CALL sp_get_user_access_path_to_project('user-id', 'project-id');
-- Returns: user_group, project_group, granted_at
```

### User Activity Summary

```sql
-- Get user's activity summary (last 30 days)
CALL sp_get_user_activity_summary('user-id', 30);
```

---

## Indexes

Key indexes for user queries:

| Index | Columns | Purpose |
|-------|---------|---------|
| `uk_user_hash` | `user_hash` | Unique public identifier |
| `uk_username` | `username` | Unique username |
| `idx_email` | `email` | Email lookups |
| `idx_user_type` | `user_type` | Filter by type |
| `idx_active_users` | `is_active, user_type` | Active user queries |
| `idx_users_username_password` | `username, password_hash, is_active` | Login |
| `idx_users_email_password` | `email, password_hash, is_active` | Login by email |
| `idx_users_role_active` | `role_id, is_active` | Role queries |
| `idx_permission_check` | `id, role_id, is_active` | Permission resolution |

---

## Activity Logging

All user operations are automatically logged via triggers:

| Operation | Activity Type | Severity |
|-----------|---------------|----------|
| User created | `user_registration` | INFO |
| User updated | `user_update` | INFO |
| User type changed | `user_type_changed` | CRITICAL |
| Status changed | `user_status_change` | WARNING |
| Password reset | `user_password_reset` | WARNING |
| User deleted | `user_deleted` | WARNING |
| Added to group | `user_group_assign` | INFO |
| Removed from group | `user_group_remove` | WARNING |
| Session created | `session_created` | INFO |
| Session ended | `user_logout` | INFO |

See [audit.md](audit.md) for complete audit logging documentation.
