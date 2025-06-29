# Database Schema - 3-Tier User Types Enhanced

Complete database documentation for the **3-Tier User Types** Group-Based Multi-Project Authentication system.

## 🏗️ Overview

The enhanced authentication system provides a **3-tier hierarchical user type model**:

1. **Root Users**: Super administrators with unrestricted access to everything
2. **Admin Users**: Project-specific administrators limited to their assigned project  
3. **Consumer Users**: End users with RBAC-based permissions through groups

### User Type Hierarchy
```
ROOT USER (Global Super Admin)
├── Can manage everything across all projects
├── Can create/modify/delete any resource
├── Can create other root users and admin users
└── Bypasses all permission checks

ADMIN USER (Project-Scoped Admin) 
├── Limited to specific assigned project
├── Full admin rights within their project only
├── Can manage users, groups, permissions in their project
└── Cannot access other projects

CONSUMER USER (End User)
├── Subject to RBAC permissions
├── Access through user groups and project groups
├── Standard authentication and permission flow
└── Can only access what their groups allow
```

## 📊 Enhanced Database Structure

The system uses **12 main tables** in the `magic-auth` database with **user type enhancements**:

### Core Tables (Enhanced)

#### 1. `users` - Enhanced with User Types

```sql
CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Global user identifier',
    username VARCHAR(100) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE COMMENT 'User email address',
    password_hash VARCHAR(255) NOT NULL COMMENT 'Hashed password',
    
    -- NEW: User Type System
    user_type ENUM('root', 'admin', 'consumer') NOT NULL DEFAULT 'consumer' COMMENT 'User type: root=global admin, admin=project admin, consumer=end user',
    assigned_project_id INT NULL COMMENT 'For admin users: their assigned project (NULL for root and consumer)',
    
    -- Metadata
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT COMMENT 'User ID who created this user',
    is_active BOOLEAN DEFAULT TRUE,
    
    -- Foreign Keys
    FOREIGN KEY (assigned_project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    
    -- Indexes
    INDEX idx_user_hash (user_hash),
    INDEX idx_username (username),
    INDEX idx_email (email),
    INDEX idx_user_type (user_type),
    INDEX idx_assigned_project (assigned_project_id),
    
    -- Constraints
    CONSTRAINT chk_admin_project CHECK (
        (user_type = 'admin' AND assigned_project_id IS NOT NULL) OR
        (user_type IN ('root', 'consumer') AND assigned_project_id IS NULL)
    )
);
```

**User Type Constraints:**
- **Root users**: `user_type='root'`, `assigned_project_id=NULL`
- **Admin users**: `user_type='admin'`, `assigned_project_id` must be set
- **Consumer users**: `user_type='consumer'`, `assigned_project_id=NULL`

#### 2. `projects` - No changes needed

```sql
CREATE TABLE projects (
    id INT PRIMARY KEY AUTO_INCREMENT,
    project_hash VARCHAR(64) UNIQUE NOT NULL,
    project_name VARCHAR(255) NOT NULL,
    project_description TEXT,
    project_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT COMMENT 'User ID who created this project',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    INDEX idx_project_hash (project_hash),
    INDEX idx_project_name (project_name)
);
```

### Permission & RBAC Tables (No changes needed)

All existing RBAC tables remain the same:
- `permissions` - Project-specific permissions catalog
- `permission_groups` - Project-specific roles
- `permission_group_permissions` - Role-permission assignments
- `user_project_permission_groups` - User role assignments per project
- `permission_audit_log` - Complete audit trail

### Group Management Tables (No changes needed)

All existing group tables remain the same:
- `user_groups` - Global user groups
- `user_group_members` - User group memberships
- `user_group_projects` - Group project access
- `project_groups` - Project permission groups (legacy)
- `project_group_members` - Project group assignments (legacy)

## 🔐 User Type Permission Matrix

### Root User Capabilities
| Operation | Access Level | Restrictions |
|-----------|--------------|--------------|
| **Project Management** | All projects | None - can create, modify, delete any project |
| **User Management** | All users | Can create root, admin, consumer users |
| **Group Management** | All groups | Can modify any user/project group |
| **Permission Management** | All permissions | Can modify any permission/role in any project |
| **System Administration** | Full access | Can access all admin endpoints |

### Admin User Capabilities  
| Operation | Access Level | Restrictions |
|-----------|--------------|--------------|
| **Project Management** | Assigned project only | Can only modify their assigned project |
| **User Management** | Project users only | Can manage users in their project |
| **Group Management** | Project groups only | Can manage groups related to their project |
| **Permission Management** | Project permissions only | Can modify permissions/roles in their project |
| **System Administration** | Project-scoped only | No global system access |

### Consumer User Capabilities
| Operation | Access Level | Restrictions |
|-----------|--------------|--------------|
| **Project Access** | RBAC-controlled | Only projects their groups have access to |
| **User Management** | Profile only | Can only update their own profile |
| **Group Management** | View only | Can view their group memberships |
| **Permission Management** | None | Cannot modify permissions or roles |
| **System Administration** | None | No admin access |

## 🔄 Permission Resolution Flow

### Root User Flow
```
1. Check user_type = 'root'
2. If root: ALLOW ALL operations
3. Bypass all permission checks
4. Log operation with root context
```

### Admin User Flow  
```
1. Check user_type = 'admin'
2. Get assigned_project_id
3. Check if operation is within assigned project
4. If within project: ALLOW admin operations
5. If outside project: DENY
6. Log operation with project context
```

### Consumer User Flow
```
1. Check user_type = 'consumer'  
2. Use existing RBAC flow:
   - Get user groups
   - Check project access via groups
   - Get project permissions via roles
   - Authorize based on required permission
3. Log operation with user/group context
```

## 🛡️ Enhanced Security Features

### User Type Isolation
- **Root users**: No restrictions, full audit logging
- **Admin users**: Project boundary enforcement at database level
- **Consumer users**: RBAC permission enforcement

### Database Constraints
```sql
-- Ensure admin users have assigned projects
CONSTRAINT chk_admin_project CHECK (
    (user_type = 'admin' AND assigned_project_id IS NOT NULL) OR
    (user_type IN ('root', 'consumer') AND assigned_project_id IS NULL)
)

-- Ensure only root users can create root users
-- (Enforced at application level)
```

### Audit Trail Enhancements
- All operations include user_type in audit logs
- Root operations specially flagged for security review
- Admin operations include project scope
- Consumer operations include group context

## 📝 Usage Examples

### Creating Different User Types

```sql
-- Create root user (only root users can do this)
INSERT INTO users (user_hash, username, email, password_hash, user_type, created_by)
VALUES ('ROOT123...', 'root_admin', 'root@company.com', 'HASH...', 'root', 1);

-- Create admin user for specific project
INSERT INTO users (user_hash, username, email, password_hash, user_type, assigned_project_id, created_by)
VALUES ('ADMIN123...', 'project_admin', 'admin@company.com', 'HASH...', 'admin', 5, 1);

-- Create consumer user (normal registration)
INSERT INTO users (user_hash, username, email, password_hash, user_type, created_by)
VALUES ('USER123...', 'john_doe', 'john@company.com', 'HASH...', 'consumer', NULL);
```

### Permission Checking Queries

```sql
-- Check if user is root (unlimited access)
SELECT user_type = 'root' as is_root 
FROM users 
WHERE id = ?;

-- Check if admin user can access project
SELECT assigned_project_id = ? as can_access_project
FROM users 
WHERE id = ? AND user_type = 'admin';

-- Consumer user permission check (existing RBAC flow)
SELECT COUNT(*) > 0 as has_permission
FROM users u
JOIN user_project_permission_groups uppg ON u.id = uppg.user_id
JOIN permission_groups pg ON uppg.permission_group_id = pg.id
JOIN permission_group_permissions pgp ON pg.id = pgp.permission_group_id
JOIN permissions p ON pgp.permission_id = p.id
WHERE u.id = ? AND u.user_type = 'consumer' AND uppg.project_id = ? AND p.permission_name = ?;
```

## 🎯 API Impact Summary

### Authentication Changes
- Login response includes `user_type`
- Session tokens include user type and project scope for admin users
- Different permission checking middleware for each user type

### Route Protection Changes
- Root routes: Only accessible by root users
- Admin routes: Accessible by root users or project-scoped admin users  
- Consumer routes: Standard RBAC permission checking

### New Endpoint Categories
- `/root/*` - Root user exclusive operations
- `/admin/*` - Project-scoped admin operations (existing, enhanced)
- `/user/*` - Consumer user operations (existing)

---

**This enhanced 3-tier user type system provides clear separation of privileges while maintaining the existing RBAC system for consumer users and adding powerful administration capabilities for root and admin users.** 