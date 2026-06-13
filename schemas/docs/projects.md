# Project Management

Complete documentation for project management in the Magic Auth system.

---

## Table of Contents

1. [Overview](#overview)
2. [Tables](#tables)
3. [Stored Procedures](#stored-procedures)
4. [Project Groups](#project-groups)
5. [Project Access](#project-access)
6. [Project Statistics](#project-statistics)
7. [Archiving](#archiving)
8. [Common Operations](#common-operations)

---

## Overview

Projects represent applications or systems in the multi-project authentication architecture. Users access projects through the **Groups of Groups** model.

### Key Principles

- **No Direct User Assignment**: Users access projects via User Groups → Project Groups
- **Root Access**: Root users automatically have access to all active, non-archived projects
- **Soft Deletes**: Project deletion is soft (`is_active = FALSE`)
- **Archiving**: Projects can be archived (excluded from root access)
- **Ownership**: Projects have an owner user

---

## Tables

### Primary Table: `projects`

```sql
CREATE TABLE projects (
    id VARCHAR(64) NOT NULL,                    -- Internal ID (UUID format)
    project_hash VARCHAR(255) NOT NULL,         -- Public identifier
    project_name VARCHAR(100) NOT NULL,         -- Project name
    project_description TEXT,                   -- Description
    project_created DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by VARCHAR(64),                     -- Creator user ID
    is_active BOOLEAN NOT NULL DEFAULT TRUE,    -- Soft delete flag
    archived BOOLEAN DEFAULT FALSE,             -- Archive flag
    owner_id VARCHAR(64),                       -- Project owner
    archived_at TIMESTAMP NULL,                 -- Archive timestamp
    archived_by VARCHAR(64) NULL,               -- Who archived
    PRIMARY KEY (id),
    UNIQUE KEY uk_project_hash (project_hash)
);
```

### Related Tables

| Table | Purpose |
|-------|---------|
| `project_groups` | Project group definitions |
| `project_group_members` | Project → Project Group memberships |
| `user_group_project_groups` | User Group → Project Group access links |
| `user_sessions` | User sessions per project |

---

## Stored Procedures

### Project CRUD

| Procedure | Parameters | Description |
|-----------|------------|-------------|
| `sp_create_project` | `id, hash, name, description, created_by, owner_id` | Create project |
| `sp_get_project_by_id` | `project_id` | Get by internal ID |
| `sp_get_project_by_hash` | `project_hash` | Get by public hash |
| `sp_update_project` | `id, name, description` | Update project (NULL = keep) |
| `sp_delete_project` | `id, deleted_by` | Soft-delete project |

**Create Example:**
```sql
CALL sp_create_project(
    'proj-550e8400-e29b-41d4-a716-446655440001',
    'proj-hash-generated',
    'My Application',
    'A sample application project',
    'creator-user-id',
    'owner-user-id'
);
```

**Update Example:**
```sql
-- Update only name (NULL = keep existing value)
CALL sp_update_project('proj-id', 'New Name', NULL);

-- Update only description
CALL sp_update_project('proj-id', NULL, 'New description');

-- Update both
CALL sp_update_project('proj-id', 'New Name', 'New description');
```

**Delete Example:**
```sql
CALL sp_delete_project('proj-id', 'deleted-by-user-id');
-- Sets is_active = FALSE on project
-- Sets is_active = FALSE on all project group memberships
-- Sets is_active = FALSE on all active sessions
```

### Project Listing & Search

| Procedure | Parameters | Description |
|-----------|------------|-------------|
| `sp_list_all_projects` | `limit, offset, sort_by, sort_order, search, include_archived` | List with filters |
| `sp_count_projects` | `include_archived` | Count projects |
| `sp_search_projects` | `search_term, limit` | Quick search |
| `sp_get_recent_projects_count` | `days` | Count recent projects |

**List Examples:**
```sql
-- List first 20 active, non-archived projects
CALL sp_list_all_projects(20, 0, 'project_name', 'asc', NULL, FALSE);

-- Search projects containing "api"
CALL sp_list_all_projects(20, 0, 'project_name', 'asc', 'api', FALSE);

-- Include archived projects
CALL sp_list_all_projects(20, 0, 'project_created', 'desc', NULL, TRUE);

-- Sort options: project_name, project_created, updated_at

-- Quick search
CALL sp_search_projects('mobile', 10);

-- Count all active projects
CALL sp_count_projects(FALSE);

-- Projects created in last 30 days
CALL sp_get_recent_projects_count(30);
```

---

## Project Groups

Project groups organize projects together. See [permissions.md](permissions.md) for full details.

### Project Group Table: `project_groups`

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
| `sp_delete_project_group` | Soft-delete group |
| `sp_list_all_project_groups` | List with pagination |
| `sp_count_project_groups` | Count groups |

### Project ↔ Project Group Membership

| Procedure | Description |
|-----------|-------------|
| `sp_assign_project_to_group` | Add project to group |
| `sp_remove_project_from_group` | Remove project from group |
| `sp_get_project_groups_for_project` | Get project's groups |
| `sp_get_projects_in_project_group` | Get projects in group |
| `sp_check_project_in_group` | Check membership |

**Examples:**
```sql
-- Create project group
CALL sp_create_project_group(
    'pg-uuid',
    'pg-hash',
    'Production Apps',
    'All production applications',
    'creator-id'
);

-- Add project to group
CALL sp_assign_project_to_group('member-id', 'project-id', 'pg-uuid', 'admin-id');

-- Get project's groups
CALL sp_get_project_groups_for_project('project-id');

-- Get all projects in a group
CALL sp_get_projects_in_project_group('pg-uuid');

-- Check if project is in group
CALL sp_check_project_in_group('project-id', 'pg-uuid');
-- Returns: is_member (1 or 0)

-- Remove project from group
CALL sp_remove_project_from_group('project-id', 'pg-uuid', 'admin-id');
```

---

## Project Access

### Access Flow

```
User → User Group → Project Group → Project
```

The login contract uses direct active rows only: active user membership, active `user_group_project_groups` authorization, active project-group membership, and an active non-archived project. Parent group hierarchy is schema infrastructure; it is not traversed for project login authorization.

### Root User Access

Root users automatically have access to ALL active, non-archived projects. This is enforced by:
1. The `v_user_project_access` view
2. The `sp_get_user_accessible_projects` procedure
3. Session validation triggers

### Access Check Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_check_user_project_access` | Check if user has access |
| `sp_get_user_access_path_to_project` | Get access chain details |
| `sp_get_user_accessible_projects` | Get all accessible projects |
| `sp_get_user_groups_in_project` | Get user's groups for project |
| `sp_get_user_groups_for_project` | Get all user groups with access |

**Examples:**
```sql
-- Check access
CALL sp_check_user_project_access('user-id', 'project-id');
-- Returns: has_access (1 or 0)

-- Get the access path
CALL sp_get_user_access_path_to_project('user-id', 'project-id');
-- Returns: user_group, project_group, granted_at (for each path)

-- Get all projects user can access
CALL sp_get_user_accessible_projects('user-id');
-- For root: all active non-archived projects with access_type = 'root_access'
-- For others: distinct active non-archived projects via direct groups-of-groups links

-- Get user's groups that give access to this project
CALL sp_get_user_groups_in_project('user-id', 'project-id');
```

### Project Members

| Procedure | Description |
|-----------|-------------|
| `sp_get_project_members` | Get all users with access |
| `sp_get_admin_assigned_projects` | Get admin's accessible projects |
| `sp_check_admin_multi_project_access` | Check admin project access |
| `sp_get_admin_project_assignments_with_details` | Get admin assignments with path |

**Examples:**
```sql
-- Get all users with project access
CALL sp_get_project_members('project-id');
-- Returns: user info, granted_at, user_group, project_group, access_type
-- Root users shown with access_type = 'root_access'
-- Others shown with access_type = 'group_access'

-- Get admin's accessible projects
CALL sp_get_admin_assigned_projects('admin-user-id');

-- Check if admin has access to specific project
CALL sp_check_admin_multi_project_access('admin-user-id', 'project-id');
-- Returns: has_access (1 or 0)

-- Get detailed assignments for admin
CALL sp_get_admin_project_assignments_with_details('admin-user-id');
-- Returns: project info, assigned_at, assigned_by, access_through_user_group, access_through_project_group
```

---

## Project Statistics

### Statistics Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_get_project_stats` | Basic statistics |
| `sp_get_project_statistics` | Detailed statistics |
| `sp_get_project_group_stats` | Project group statistics |

**Examples:**
```sql
-- Basic stats
CALL sp_get_project_stats('project-id');
-- Returns 4 result sets:
--   1. total_users (with access)
--   2. active_sessions
--   3. project_group_count
--   4. user_group_count (with access)

-- Detailed statistics
CALL sp_get_project_statistics('project-id');
-- Returns 3 result sets:
--   1. Project info
--   2. Access statistics (total_users, user_groups, project_groups)
--   3. User group distribution (group_name, user_count)

-- Project group stats
CALL sp_get_project_group_stats('project-group-id');
-- Returns: project_count, user_group_count, total_users
```

---

## Archiving

Archived projects are excluded from authentication access for root, admin, and consumer users.

### Archive Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_archive_project` | Archive project |
| `sp_unarchive_project` | Unarchive project |

**Examples:**
```sql
-- Archive project
CALL sp_archive_project('project-id', 'archived-by-user-id');
-- Sets: archived = TRUE, archived_at = NOW(), archived_by = user_id

-- Unarchive project
CALL sp_unarchive_project('project-id');
-- Sets: archived = FALSE, archived_at = NULL, archived_by = NULL
```

### Archive Behavior

1. Archived projects are NOT accessible by root users (unlike active non-archived projects)
2. Group-based consumer login and accessible-project lookups exclude archived projects
3. Project switching and session validation deny archived project contexts
4. API-key project-access validation treats archived projects as no project access
5. List/management procedures can still expose archived projects where they accept `include_archived` or perform direct project lookup for administration
6. Archiving does not hard-delete memberships, but auth surfaces fail closed until the project is unarchived

Rollback caveat: sessions or refresh families eagerly revoked while an archive/access hardening rollout is active are not restored automatically by rollback. Affected users must re-authenticate if policy later permits access again.

---

## Common Operations

### Create Project with Access Setup

```sql
-- 1. Create the project
CALL sp_create_project(
    'proj-uuid',
    'proj-hash',
    'New Application',
    'A new application',
    'creator-id',
    'owner-id'
);

-- 2. Create or identify project group
CALL sp_create_project_group(
    'pg-uuid',
    'pg-hash',
    'New App Projects',
    'Group for new app',
    'creator-id'
);

-- 3. Add project to project group
CALL sp_assign_project_to_group('m1', 'proj-uuid', 'pg-uuid', 'admin-id');

-- 4. Create or identify user group
CALL sp_create_user_group(
    'ug-uuid',
    'ug-hash',
    'New App Team',
    'Team for new app',
    NULL,
    'creator-id'
);

-- 5. Link user group to project group
CALL sp_grant_user_group_project_group_access('a1', 'ug-uuid', 'pg-uuid', 'admin-id');

-- 6. Add users to user group
CALL sp_assign_user_to_group('m2', 'user-id', 'ug-uuid', 'admin-id');

-- Now users in the group have access to the project!
```

### Get Full Project Context

```sql
-- Get project info
CALL sp_get_project_by_hash('proj-hash');

-- Get project's groups
CALL sp_get_project_groups_for_project('proj-id');

-- Get statistics
CALL sp_get_project_statistics('proj-id');

-- Get all members
CALL sp_get_project_members('proj-id');

-- Get user groups with access
CALL sp_get_user_groups_for_project('proj-id');
```

### Check and Grant Access

```sql
-- Check if user has access
CALL sp_check_user_project_access('user-id', 'project-id');

-- If not, find or create appropriate groups and link them
-- (See permissions.md for group management details)

-- Verify access path
CALL sp_get_user_access_path_to_project('user-id', 'project-id');
```

---

## Indexes

Key indexes for project queries:

| Index | Columns | Purpose |
|-------|---------|---------|
| `uk_project_hash` | `project_hash` | Unique public identifier |
| `idx_project_name` | `project_name` | Name searches |
| `idx_active_projects` | `is_active` | Active project queries |
| `idx_projects_archived` | `archived` | Archive filtering |
| `idx_projects_owner` | `owner_id` | Owner lookups |
| `idx_projects_created_at` | `project_created` | Date sorting |

---

## Activity Logging

All project operations are automatically logged via triggers:

| Operation | Activity Type | Severity |
|-----------|---------------|----------|
| Project created | `project_creation` | INFO |
| Project updated | `project_update` | INFO |
| Project archived | `project_archived` | WARNING |
| Project unarchived | `project_unarchived` | INFO |
| Ownership transferred | `project_ownership_transferred` | CRITICAL |
| Project deleted | `project_delete` | WARNING |
| Added to group | `project_group_assign` | INFO |
| Removed from group | `project_group_remove` | WARNING |
| Project group created | `project_group_creation` | INFO |
| Project group updated | `project_group_update` | INFO |
| Project group deleted | `project_group_delete` | WARNING |

See [audit.md](audit.md) for complete audit logging documentation.

---

## Views

| View | Description |
|------|-------------|
| `v_user_project_access` | Complete user → project access paths |
| `v_user_project_access_summary` | User access counts |
| `project_health_view` | Project monitoring and activity levels |
| `v_project_group_hierarchy` | Project group tree with depth |
| `v_project_group_summary` | Project group statistics |
| `v_access_chain` | Full access path visualization |
