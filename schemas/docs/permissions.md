# Permission System

Complete documentation for the permission and authorization system in Magic Auth.

---

## Table of Contents

1. [Overview](#overview)
2. [Architecture](#architecture)
3. [User Groups](#user-groups)
4. [Project Groups](#project-groups)
5. [Groups of Groups](#groups-of-groups)
6. [Global Role System](#global-role-system)
7. [Permission Resolution](#permission-resolution)
8. [Scoped Permissions](#scoped-permissions)
9. [Tables Reference](#tables-reference)
10. [Stored Procedures Reference](#stored-procedures-reference)
11. [Common Operations](#common-operations)

---

## Overview

The Magic Auth permission system implements a sophisticated **hierarchical access control** model with multiple permission sources and scoped grant/deny capabilities.

### Key Concepts

| Concept | Description |
|---------|-------------|
| **User Groups** | Collections of users with hierarchical structure |
| **Project Groups** | Collections of projects with hierarchical structure |
| **Groups of Groups** | User Groups linked to Project Groups for access |
| **Global Roles** | System-wide roles with permission groups |
| **Permission Groups** | Reusable collections of permissions |
| **Scoped Permissions** | Project-group-specific permissions with grant/deny |

---

## Architecture

### Access Flow

```
┌─────────┐     ┌─────────────┐     ┌───────────────┐     ┌──────────┐
│  User   │ ──► │ User Group  │ ──► │ Project Group │ ──► │ Project  │
└─────────┘     └─────────────┘     └───────────────┘     └──────────┘
```

### Permission Flow

Users can obtain permissions through multiple paths:

```
                              ┌──────────────────────┐
                              │        USER          │
                              └──────────┬───────────┘
                                         │
         ┌───────────────────────────────┼───────────────────────────────┐
         │                               │                               │
         ▼                               ▼                               ▼
┌─────────────────┐           ┌─────────────────┐           ┌─────────────────┐
│   Global Role   │           │   User Groups   │           │ Direct Assign   │
│   (One per      │           │   (Multiple)    │           │ (Exceptions)    │
│    user)        │           │                 │           │                 │
└────────┬────────┘           └────────┬────────┘           └────────┬────────┘
         │                             │                             │
         ▼                             ▼                             ▼
┌─────────────────┐           ┌─────────────────┐           ┌─────────────────┐
│   Permission    │           │   Permission    │           │   Permission    │
│   Groups        │           │   Groups        │           │   Groups        │
└────────┬────────┘           └────────┬────────┘           └────────┬────────┘
         │                             │                             │
         └─────────────────────────────┼─────────────────────────────┘
                                       │
                                       ▼
                              ┌─────────────────┐
                              │   PERMISSIONS   │
                              └─────────────────┘
```

### Scoped Permissions (Additional Layer)

```
User Group ──► Project Group ──► Permission Group (with Grant/Deny + Priority)
```

---

## User Groups

User groups are hierarchical collections of users.

### Table: `user_groups`

```sql
CREATE TABLE user_groups (
    id VARCHAR(64) NOT NULL,
    group_hash VARCHAR(255) NOT NULL,           -- Public identifier
    group_name VARCHAR(100) NOT NULL,           -- Unique name
    group_description TEXT,
    parent_group_id VARCHAR(64) NULL,           -- NULL = root group
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_group_hash (group_hash),
    UNIQUE KEY uk_group_name (group_name)
);
```

### Hierarchy Rules

- **Root Groups**: `parent_group_id IS NULL`
- **Maximum Depth**: 10 levels (enforced by triggers)
- **Circular Reference Prevention**: Triggers prevent cycles
- **Depth Calculation**: Dynamic via recursive queries (no stored level)

### User Group Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_create_user_group` | Create group with optional parent |
| `sp_get_user_group_by_id` | Get by internal ID |
| `sp_get_user_group_by_hash` | Get by public hash |
| `sp_get_user_group_by_name` | Get by name |
| `sp_update_user_group` | Update name/description |
| `sp_delete_user_group` | Soft-delete with cascade |
| `sp_list_all_user_groups` | List with pagination |
| `sp_count_user_groups` | Count active groups |

### Membership Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_assign_user_to_group` | Add user to group |
| `sp_remove_user_from_group` | Remove user from group |
| `sp_get_users_in_group` | Get all users in group |
| `sp_get_user_groups_for_user` | Get user's groups |
| `sp_check_user_in_group` | Check membership |

**Examples:**
```sql
-- Create root user group
CALL sp_create_user_group(
    'grp-uuid',
    'grp-hash',
    'Developers',
    'Development team',
    NULL,           -- NULL parent = root group
    'creator-id'
);

-- Create child group
CALL sp_create_user_group(
    'grp-uuid-2',
    'grp-hash-2',
    'Frontend Developers',
    'Frontend team',
    'grp-uuid',     -- Parent = Developers
    'creator-id'
);

-- Add user to group
CALL sp_assign_user_to_group('member-id', 'user-id', 'grp-uuid', 'admin-id');

-- Get hierarchy view
SELECT * FROM v_user_group_hierarchy;
```

---

## Project Groups

Project groups are hierarchical collections of projects.

### Table: `project_groups`

```sql
CREATE TABLE project_groups (
    id VARCHAR(64) NOT NULL,
    group_hash VARCHAR(255) NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_description TEXT,
    parent_group_id VARCHAR(64) NULL,           -- NULL = root group
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_project_group_hash (group_hash),
    UNIQUE KEY uk_project_group_name (group_name)
);
```

### Project Group Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_create_project_group` | Create project group |
| `sp_get_project_group_by_id` | Get by ID |
| `sp_get_project_group_by_hash` | Get by hash |
| `sp_get_project_group_by_name` | Get by name |
| `sp_update_project_group` | Update group |
| `sp_delete_project_group` | Soft-delete with cascade |
| `sp_list_all_project_groups` | List with pagination |
| `sp_count_project_groups` | Count groups |

### Project Membership Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_assign_project_to_group` | Add project to group |
| `sp_remove_project_from_group` | Remove project from group |
| `sp_get_project_groups_for_project` | Get project's groups |
| `sp_get_projects_in_project_group` | Get projects in group |
| `sp_check_project_in_group` | Check membership |
| `sp_get_project_group_stats` | Get group statistics |
| `sp_get_users_with_access_to_project_group` | Get users with access |

**Examples:**
```sql
-- Create project group
CALL sp_create_project_group(
    'pg-uuid',
    'pg-hash',
    'Production Apps',
    'Production applications',
    'creator-id'
);

-- Add project to group
CALL sp_assign_project_to_group('member-id', 'project-id', 'pg-uuid', 'admin-id');

-- Get hierarchy view
SELECT * FROM v_project_group_hierarchy;
```

---

## Groups of Groups

The **key link** between users and projects is the User Group → Project Group connection.

### Table: `user_group_project_groups`

```sql
CREATE TABLE user_group_project_groups (
    id VARCHAR(64) NOT NULL,
    user_group_id VARCHAR(64) NOT NULL,
    project_group_id VARCHAR(64) NOT NULL,
    granted_at DATETIME NOT NULL,
    granted_by VARCHAR(64),
    revoked_at DATETIME,
    revoked_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_usergroup_projectgroup (user_group_id, project_group_id)
);
```

### Access Grant Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_grant_user_group_project_group_access` | Link user group to project group |
| `sp_revoke_user_group_project_group_access` | Unlink user group from project group |
| `sp_get_project_groups_for_user_group` | Get accessible project groups |
| `sp_get_user_groups_for_project_group` | Get user groups with access |
| `sp_check_user_group_project_group_access` | Check if link exists |

### User Access Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_get_user_accessible_projects` | Get all projects user can access |
| `sp_check_user_project_access` | Check if user can access project |
| `sp_get_user_access_path_to_project` | Get the access chain |
| `sp_get_user_groups_in_project` | Get user's groups for specific project |
| `sp_get_user_groups_for_project` | Get all user groups with project access |
| `sp_get_projects_for_user_group` | Get all projects accessible by group |

**Examples:**
```sql
-- Grant user group access to project group
CALL sp_grant_user_group_project_group_access(
    'access-id',
    'user-group-id',
    'project-group-id',
    'admin-id'
);

-- Check user's project access
CALL sp_check_user_project_access('user-id', 'project-id');
-- Returns: has_access (1 or 0)

-- Get access path
CALL sp_get_user_access_path_to_project('user-id', 'project-id');
-- Returns: user_group, project_group, granted_at

-- Get all accessible projects for user
CALL sp_get_user_accessible_projects('user-id');
```

---

## Global Role System

### Roles

Roles are system-wide and can be assigned one-per-user.

#### Table: `roles`

```sql
CREATE TABLE roles (
    id VARCHAR(64) NOT NULL,
    role_hash VARCHAR(255) NOT NULL,
    role_name VARCHAR(100) NOT NULL,            -- Unique identifier
    role_display_name VARCHAR(255) NOT NULL,    -- Human-readable name
    role_description TEXT,
    role_priority INT NOT NULL DEFAULT 50,      -- Higher = more important
    is_system_role BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_role_hash (role_hash),
    UNIQUE KEY uk_role_name (role_name)
);
```

### Permission Groups

Permission groups are reusable collections of permissions.

#### Table: `global_permission_groups`

```sql
CREATE TABLE global_permission_groups (
    id VARCHAR(64) NOT NULL,
    group_hash VARCHAR(255) NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_display_name VARCHAR(255) NOT NULL,
    group_description TEXT,
    group_category VARCHAR(50) NOT NULL DEFAULT 'general',
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_perm_group_hash (group_hash),
    UNIQUE KEY uk_perm_group_name (group_name)
);
```

### Permissions

Individual permission definitions.

#### Table: `global_permissions`

```sql
CREATE TABLE global_permissions (
    id VARCHAR(64) NOT NULL,
    permission_hash VARCHAR(255) NOT NULL,
    permission_name VARCHAR(100) NOT NULL,      -- e.g., 'users.create'
    permission_display_name VARCHAR(255) NOT NULL,
    permission_description TEXT,
    permission_category VARCHAR(50) NOT NULL DEFAULT 'general',
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_permission_hash (permission_hash),
    UNIQUE KEY uk_permission_name (permission_name)
);
```

### Role System Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_global_create_role` | Create role |
| `sp_global_get_role_by_hash` | Get role |
| `sp_global_list_roles` | List roles |
| `sp_global_update_role` | Update role |
| `sp_global_delete_role` | Soft-delete role |
| `sp_global_create_permission_group` | Create permission group |
| `sp_global_get_permission_group_by_hash` | Get permission group |
| `sp_global_list_permission_groups` | List permission groups |
| `sp_global_update_permission_group` | Update permission group |
| `sp_global_delete_permission_group` | Soft-delete permission group |
| `sp_global_create_permission` | Create permission |
| `sp_global_get_permission_by_hash` | Get permission |
| `sp_global_list_permissions` | List permissions |
| `sp_global_update_permission` | Update permission |
| `sp_global_delete_permission` | Soft-delete permission |

### Assignment Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_global_assign_permission_group_to_role` | Link permission group to role |
| `sp_global_remove_permission_group_from_role` | Unlink from role |
| `sp_global_get_role_permission_groups` | Get role's permission groups |
| `sp_global_assign_permission_to_group` | Add permission to group |
| `sp_global_remove_permission_from_group` | Remove permission from group |
| `sp_global_get_permission_group_permissions` | Get group's permissions |
| `sp_global_assign_role_to_user` | Assign role to user |
| `sp_global_remove_role_from_user` | Remove role from user |
| `sp_global_get_user_role` | Get user's role |

**Examples:**
```sql
-- Create a role
CALL sp_global_create_role(
    'role-uuid',
    'role-hash',
    'project_manager',
    'Project Manager',
    'Can manage projects and team members',
    75,             -- priority
    FALSE,          -- not system role
    'creator-id'
);

-- Create permission group
CALL sp_global_create_permission_group(
    'pg-uuid',
    'pg-hash',
    'project_management',
    'Project Management',
    'Permissions for managing projects',
    'projects',     -- category
    'creator-id'
);

-- Create permission
CALL sp_global_create_permission(
    'perm-uuid',
    'perm-hash',
    'projects.create',
    'Create Projects',
    'Can create new projects',
    'projects',
    'creator-id'
);

-- Add permission to group
CALL sp_global_assign_permission_to_group('link-id', 'pg-uuid', 'perm-uuid', 'admin-id');

-- Add permission group to role
CALL sp_global_assign_permission_group_to_role('link-id', 'role-uuid', 'pg-uuid', 'admin-id');

-- Assign role to user
CALL sp_global_assign_role_to_user('user-id', 'role-uuid');
```

---

## Permission Resolution

### Resolution Order

When checking permissions, the system checks in this order:

1. **Root Bypass**: Root users automatically have all permissions
2. **Scoped Deny**: Check for deny rules at project-group level (highest priority deny wins)
3. **Scoped Grant**: Check for grant rules at project-group level
4. **Global Permissions**:
   - User's assigned role → permission groups → permissions
   - User's group memberships → permission groups → permissions
   - User's direct permission group assignments → permissions

### Permission Check Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_global_check_user_has_permission` | Check via role only |
| `sp_check_user_has_permission_extended` | Check all sources (role + groups + direct) |
| `sp_check_user_permission_for_project_with_deny` | Check with scoped grant/deny support |
| `sp_get_user_all_permissions` | Get ALL permissions from all sources |
| `sp_global_get_user_permissions` | Get permissions via role only |
| `sp_get_user_permission_sources` | Get breakdown by source |

**Examples:**
```sql
-- Simple check (role-based only)
CALL sp_global_check_user_has_permission('user-id', 'projects.create');
-- Returns: has_permission (1 or 0)

-- Extended check (all sources)
CALL sp_check_user_has_permission_extended('user-id', 'projects.create');
-- Returns: has_permission (1 or 0)

-- Project-scoped with deny support
CALL sp_check_user_permission_for_project_with_deny('user-id', 'project-id', 'projects.delete');
-- Returns: has_permission, source (root_bypass|scoped_deny|scoped_grant|global)

-- Get all permissions
CALL sp_get_user_all_permissions('user-id');
-- Returns: permission_name for each permission

-- Get permission sources
CALL sp_get_user_permission_sources('user-id');
-- Returns: source_type (role|user_group|direct), source_name, permission_group_name, permission_group_hash, notes
```

---

## Scoped Permissions

Scoped permissions allow different permissions per project-group context with grant/deny and priority.

### Table: `user_group_project_group_permissions`

```sql
CREATE TABLE user_group_project_group_permissions (
    id VARCHAR(64) NOT NULL,
    user_group_id VARCHAR(64) NOT NULL,
    project_group_id VARCHAR(64) NOT NULL,
    permission_group_id VARCHAR(64) NOT NULL,
    permission_type ENUM('grant', 'deny') NOT NULL DEFAULT 'grant',
    priority INT NOT NULL DEFAULT 0,            -- Higher = more important
    assigned_at DATETIME NOT NULL,
    assigned_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ug_pg_permg (user_group_id, project_group_id, permission_group_id)
);
```

### Scoped Roles

Users can have different roles per project-group context.

### Table: `user_group_project_group_roles`

```sql
CREATE TABLE user_group_project_group_roles (
    id VARCHAR(64) NOT NULL,
    user_group_id VARCHAR(64) NOT NULL,
    project_group_id VARCHAR(64) NOT NULL,
    role_id VARCHAR(64) NOT NULL,
    assigned_at DATETIME NOT NULL,
    assigned_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ug_pg_role (user_group_id, project_group_id, role_id)
);
```

### Grant/Deny Resolution

When both grant and deny exist for the same permission:

1. Compare priorities
2. If deny priority ≥ grant priority → **DENIED**
3. If grant priority > deny priority → **GRANTED**

### Scoped Permission Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_assign_scoped_permission_group` | Assign scoped permission with type/priority |
| `sp_assign_scoped_role_to_user_group` | Assign scoped role |
| `sp_remove_scoped_role_from_user_group` | Remove scoped role |
| `sp_get_user_scoped_roles` | Get user's scoped roles |
| `sp_get_user_role_for_project` | Get effective role for project |

**Examples:**
```sql
-- Grant permissions for specific project group
CALL sp_assign_scoped_permission_group(
    'link-id',
    'user-group-id',
    'project-group-id',
    'permission-group-id',
    'grant',        -- permission_type
    10,             -- priority
    'admin-id'
);

-- Deny permissions (overrides grant if same or higher priority)
CALL sp_assign_scoped_permission_group(
    'link-id-2',
    'user-group-id',
    'project-group-id',
    'dangerous-perm-group-id',
    'deny',
    20,             -- higher priority = wins
    'admin-id'
);

-- Assign scoped role
CALL sp_assign_scoped_role_to_user_group(
    'link-id',
    'user-group-id',
    'project-group-id',
    'role-id',
    'admin-id'
);

-- Get user's effective role for a project
CALL sp_get_user_role_for_project('user-id', 'project-id');
-- Returns: role_id, role_hash, role_name, role_display_name, role_priority, role_scope (scoped|global), project_group_name
```

---

## Tables Reference

### Assignment Tables Summary

| Table | Purpose |
|-------|---------|
| `user_group_members` | User → User Group |
| `project_group_members` | Project → Project Group |
| `user_group_project_groups` | User Group → Project Group (access) |
| `role_permission_groups` | Role → Permission Group |
| `global_permission_group_permissions` | Permission Group → Permission |
| `user_group_permission_groups` | User Group → Permission Group (global) |
| `user_permission_groups` | User → Permission Group (direct) |
| `user_group_project_group_permissions` | Scoped permissions with grant/deny |
| `user_group_project_group_roles` | Scoped roles per project group |

### Catalog Tables (Metadata Only)

| Table | Purpose |
|-------|---------|
| `role_project_catalog` | Roles relevant to projects (UI hints) |
| `permission_project_catalog` | Permissions relevant to projects |
| `permission_group_project_catalog` | Permission groups for projects |

---

## Stored Procedures Reference

### Permission Assignment Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_assign_permission_group_to_user_group` | Global permission to user group |
| `sp_remove_permission_group_from_user_group` | Remove from user group |
| `sp_get_user_group_permission_groups` | Get user group's permission groups |
| `sp_get_user_groups_with_permission_group` | Find groups with permission |
| `sp_assign_permission_group_to_user` | Direct permission to user |
| `sp_remove_permission_group_from_user` | Remove direct permission |
| `sp_get_user_permission_groups` | Get user's direct permissions |
| `sp_get_users_with_permission_group` | Find users with permission |

### Group Inheritance

| Procedure | Description |
|-----------|-------------|
| `sp_get_user_all_groups_with_inheritance` | Get user groups including inherited via hierarchy |

---

## Common Operations

### Setup Permission Structure

```sql
-- 1. Create permissions
CALL sp_global_create_permission('p1', 'hash1', 'users.view', 'View Users', 'Can view users', 'users', 'admin');
CALL sp_global_create_permission('p2', 'hash2', 'users.create', 'Create Users', 'Can create users', 'users', 'admin');
CALL sp_global_create_permission('p3', 'hash3', 'users.edit', 'Edit Users', 'Can edit users', 'users', 'admin');
CALL sp_global_create_permission('p4', 'hash4', 'users.delete', 'Delete Users', 'Can delete users', 'users', 'admin');

-- 2. Create permission group
CALL sp_global_create_permission_group('pg1', 'pghash1', 'user_management', 'User Management', 'All user permissions', 'users', 'admin');

-- 3. Add permissions to group
CALL sp_global_assign_permission_to_group('l1', 'pg1', 'p1', 'admin');
CALL sp_global_assign_permission_to_group('l2', 'pg1', 'p2', 'admin');
CALL sp_global_assign_permission_to_group('l3', 'pg1', 'p3', 'admin');
CALL sp_global_assign_permission_to_group('l4', 'pg1', 'p4', 'admin');

-- 4. Create role
CALL sp_global_create_role('r1', 'rhash1', 'admin', 'Administrator', 'Full admin access', 100, FALSE, 'admin');

-- 5. Add permission group to role
CALL sp_global_assign_permission_group_to_role('rl1', 'r1', 'pg1', 'admin');

-- 6. Assign role to user
CALL sp_global_assign_role_to_user('user-id', 'r1');
```

### Setup Access Chain

```sql
-- 1. Create user group
CALL sp_create_user_group('ug1', 'ughash1', 'Developers', 'Dev team', NULL, 'admin');

-- 2. Create project group
CALL sp_create_project_group('pg1', 'pghash1', 'Dev Projects', 'Development projects', 'admin');

-- 3. Add project to project group
CALL sp_assign_project_to_group('m1', 'project-id', 'pg1', 'admin');

-- 4. Link user group to project group
CALL sp_grant_user_group_project_group_access('a1', 'ug1', 'pg1', 'admin');

-- 5. Add user to user group
CALL sp_assign_user_to_group('m2', 'user-id', 'ug1', 'admin');

-- Now user has access to project!
CALL sp_check_user_project_access('user-id', 'project-id');
```

### Project login access contract

Project-scoped consumer login uses a direct four-hop chain:

```
users
  → user_group_members (active direct membership)
  → user_groups (active)
  → user_group_project_groups (active direct authorization)
  → project_groups (active)
  → project_group_members (active direct project membership)
  → projects (active and non-archived)
```

The accessible-project result has set semantics: a project appears at most once even if multiple direct chains reach it. The login and switch-project responses may expose the selected project, accessible projects, and user groups, but they must not expose the granting `user_group → project_group` chain or access-path diagnostics.

Non-goals and denials:

- No direct `projects → user_groups` authorization shortcut participates in login.
- `user_groups.parent_group_id` and `project_groups.parent_group_id` are not traversed for login authorization.
- Archived projects are denied for consumer login, root login, project switching, accessible-project lookup, session validation, and API-key project-access validation.
- Admin users use assigned-project checks; consumer group-chain access is not an admin assignment substitute.

### Check Complete Access

```sql
-- Check if user can access project
CALL sp_check_user_project_access('user-id', 'project-id');

-- Check if user has specific permission
CALL sp_check_user_has_permission_extended('user-id', 'users.delete');

-- Check scoped permission with deny support
CALL sp_check_user_permission_for_project_with_deny('user-id', 'project-id', 'users.delete');

-- Get all user permissions
CALL sp_get_user_all_permissions('user-id');

-- Get permission breakdown
CALL sp_get_user_permission_sources('user-id');
```

---

## Views

| View | Description |
|------|-------------|
| `v_user_group_hierarchy` | User group tree with depth |
| `v_project_group_hierarchy` | Project group tree with depth |
| `v_user_project_access` | Direct active, non-archived user → project access set |
| `v_user_project_access_summary` | User access counts |
| `v_user_all_groups` | User groups including inherited |
| `v_user_scoped_permissions` | Scoped permissions with grant/deny |
| `v_user_project_scoped_roles` | Roles per project context |
| `v_access_chain` | Full access path visualization |
| `v_project_group_summary` | Project group statistics |
