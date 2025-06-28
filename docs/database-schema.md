# Database Schema - RBAC Enhanced

Complete database documentation for the **RBAC (Role-Based Access Control) Enhanced** Group-Based Multi-Project Authentication system.

## 🏗️ Overview

The RBAC-enhanced authentication system provides a comprehensive hierarchical access control model where:

1. **Users** belong to **User Groups** (global)
2. **User Groups** define which **Projects** users can access
3. **Projects** have **Project-Specific Permissions** (RBAC catalog)
4. **Permission Groups (Roles)** are **Project-Specific** and define what users can do
5. **Users** are assigned **Roles within Projects** for granular control
6. **Sessions** maintain context for user, project, and role information

## 🆕 RBAC Key Features

### ✅ Requirements Satisfied
- **✅ Each project has its own permission catalog**
- **✅ Single permissions table with project isolation**
- **✅ Permission groups are project-specific**
- **✅ Cannot assign permissions outside project scope** (enforced by database constraints)
- **✅ Proper role-based access control structure**
- **✅ Complete audit trail for all permission changes**

### 🔒 RBAC Constraints Enforced
- **Project Isolation**: Permissions can only be assigned within their project
- **Role Boundaries**: Permission groups only contain permissions from the same project
- **Database Constraints**: CHECK constraints prevent cross-project assignments
- **Audit Trail**: Every permission change is logged with full context

## 📊 Enhanced Database Structure

The system now uses **11 main tables** in the `magic_auth_enhanced_v2` database:

### Core Tables (Existing)
```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     users       │    │  user_groups    │    │    projects     │
│                 │    │                 │    │                 │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • id (PK)       │    │ • id (PK)       │    │ • id (PK)       │
│ • user_hash     │    │ • group_name    │    │ • project_hash  │
│ • username      │    │ • description   │    │ • project_name  │
│ • email         │    │ • created_at    │    │ • created_by    │
│ • password_hash │    │ • created_at    │    │ • created_at    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
          │                       │                       │
          ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐               │
│user_group_members│   │user_group_projects│              │
│                 │    │                 │               │
├─────────────────┤    ├─────────────────┤               │
│ • user_id (FK)  │    │ • user_group_id │               │
│ • user_group_id │    │ • project_id    │               │
│ • assigned_at   │    │ • granted_at    │               │
│ • assigned_by   │    │ • granted_by    │               │
└─────────────────┘    └─────────────────┘               │
                                                         ▼
```

### NEW: RBAC Tables
```
          ┌─────────────────┐    ┌─────────────────┐
          │   permissions   │    │ permission_groups│
          │  (project-specific) │ (project-specific) │
          ├─────────────────┤    ├─────────────────┤
          │ • id (PK)       │    │ • id (PK)       │
          │ • project_id(FK)│    │ • project_id(FK)│
          │ • permission_name│    │ • group_name    │
          │ • display_name  │    │ • group_priority│
          │ • category      │    │ • permissions   │
          └─────────────────┘    └─────────────────┘
                    │                       │
                    ▼                       ▼
          ┌─────────────────┐    ┌─────────────────┐
          │permission_group_│    │user_project_    │
          │   permissions   │    │permission_groups│
          ├─────────────────┤    ├─────────────────┤
          │ • group_id (FK) │    │ • user_id (FK)  │
          │ • permission_id │    │ • project_id(FK)│
          │ • granted_by    │    │ • perm_group_id │
          │ • granted_at    │    │ • assigned_by   │
          └─────────────────┘    └─────────────────┘
                                          │
                                          ▼
                                ┌─────────────────┐
                                │permission_audit_│
                                │      log        │
                                ├─────────────────┤
                                │ • action_type   │
                                │ • project_id    │
                                │ • performed_by  │
                                │ • old_values    │
                                │ • new_values    │
                                └─────────────────┘
```

## 🗄️ NEW RBAC Table Definitions

### 1. `permissions` - Project-Specific Permission Catalog

**✅ RBAC Requirement: Each project has its own permission catalog**

```sql
CREATE TABLE permissions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    permission_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Global permission identifier',
    project_id INT NOT NULL COMMENT 'Project this permission belongs to',
    permission_name VARCHAR(100) NOT NULL COMMENT 'Permission name within project',
    permission_display_name VARCHAR(255) NOT NULL COMMENT 'Human-readable permission name',
    permission_description TEXT COMMENT 'Detailed description of what this permission allows',
    permission_category VARCHAR(50) DEFAULT 'general' COMMENT 'Category: general, admin, api, data',
    is_system_permission BOOLEAN DEFAULT FALSE COMMENT 'Whether this is system-defined',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT COMMENT 'User ID who created this permission',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    
    -- ✅ Ensure permission names are unique per project
    UNIQUE KEY unique_permission_per_project (project_id, permission_name),
    
    INDEX idx_permission_hash (permission_hash),
    INDEX idx_project_id (project_id),
    INDEX idx_permission_name (permission_name),
    INDEX idx_permission_category (permission_category)
);
```

**Default Permissions Per Project:**
- **General**: read, write, delete, create, update
- **Admin**: admin, manage_users, manage_roles, view_audit
- **Data**: export_data, import_data
- **API**: api_access, full_access

---

### 2. `permission_groups` - Project-Specific Permission Groups (Roles)

**✅ RBAC Requirement: Permission groups are project-specific**

```sql
CREATE TABLE permission_groups (
    id INT PRIMARY KEY AUTO_INCREMENT,
    group_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Global permission group identifier',
    project_id INT NOT NULL COMMENT 'Project this permission group belongs to',
    group_name VARCHAR(100) NOT NULL COMMENT 'Role name within project',
    group_display_name VARCHAR(255) NOT NULL COMMENT 'Human-readable role name',
    group_description TEXT COMMENT 'Description of this role and its purpose',
    group_priority INT DEFAULT 0 COMMENT 'Priority for role hierarchy (higher = more permissions)',
    is_system_role BOOLEAN DEFAULT FALSE COMMENT 'Whether this is system-defined',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT COMMENT 'User ID who created this permission group',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    
    -- ✅ Ensure permission group names are unique per project
    UNIQUE KEY unique_group_per_project (project_id, group_name),
    
    INDEX idx_group_hash (group_hash),
    INDEX idx_project_id (project_id),
    INDEX idx_group_name (group_name),
    INDEX idx_group_priority (group_priority)
);
```

**Default Roles Per Project:**
- **admin** (Priority 100): Full administrative access
- **manager** (Priority 80): Management access with user/role management
- **editor** (Priority 60): Content editing and management
- **contributor** (Priority 40): Can create and edit own content
- **viewer** (Priority 20): Read-only access
- **api_user** (Priority 30): API access for integrations

---

### 3. `permission_group_permissions` - Links Permission Groups to Permissions

**✅ RBAC Requirement: Cannot assign permissions outside project scope**

```sql
CREATE TABLE permission_group_permissions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    permission_group_id INT NOT NULL,
    permission_id INT NOT NULL,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    granted_by INT COMMENT 'User ID who granted this permission',
    revoked_at TIMESTAMP NULL,
    revoked_by INT COMMENT 'User ID who revoked this permission',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (permission_group_id) REFERENCES permission_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE CASCADE,
    FOREIGN KEY (granted_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (revoked_by) REFERENCES users(id) ON DELETE SET NULL,
    
    -- ✅ Ensure no duplicate permission assignments
    UNIQUE KEY unique_group_permission (permission_group_id, permission_id),
    
    -- ✅ RBAC CONSTRAINT: Permission and group must belong to same project
    CONSTRAINT chk_same_project CHECK (
        (SELECT p.project_id FROM permissions p WHERE p.id = permission_id) = 
        (SELECT pg.project_id FROM permission_groups pg WHERE pg.id = permission_group_id)
    ),
    
    INDEX idx_permission_group_id (permission_group_id),
    INDEX idx_permission_id (permission_id)
);
```

---

### 4. `user_project_permission_groups` - User Role Assignments per Project

**✅ RBAC Requirement: User role assignments are project-specific**

```sql
CREATE TABLE user_project_permission_groups (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    project_id INT NOT NULL,
    permission_group_id INT NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT COMMENT 'User ID who made the assignment',
    removed_at TIMESTAMP NULL,
    removed_by INT COMMENT 'User ID who removed the assignment',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (permission_group_id) REFERENCES permission_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(id) ON DELETE SET NULL,
    
    -- ✅ RBAC CONSTRAINT: Permission group must belong to the same project
    CONSTRAINT chk_permission_group_project CHECK (
        (SELECT pg.project_id FROM permission_groups pg WHERE pg.id = permission_group_id) = project_id
    ),
    
    -- ✅ Prevent duplicate assignments
    UNIQUE KEY unique_user_project_permission_group (user_id, project_id, permission_group_id),
    
    INDEX idx_user_id (user_id),
    INDEX idx_project_id (project_id),
    INDEX idx_permission_group_id (permission_group_id)
);
```

---

### 5. `permission_audit_log` - Complete Audit Trail

**✅ RBAC Requirement: Complete audit trail for all permission changes**

```sql
CREATE TABLE permission_audit_log (
    id INT PRIMARY KEY AUTO_INCREMENT,
    action_type ENUM('CREATE_PERMISSION', 'UPDATE_PERMISSION', 'DELETE_PERMISSION', 
                     'CREATE_ROLE', 'UPDATE_ROLE', 'DELETE_ROLE',
                     'GRANT_PERMISSION', 'REVOKE_PERMISSION',
                     'ASSIGN_ROLE', 'REMOVE_ROLE') NOT NULL,
    project_id INT NOT NULL,
    target_user_id INT COMMENT 'User affected by the action',
    permission_id INT COMMENT 'Permission involved in the action',
    permission_group_id INT COMMENT 'Permission group involved in the action',
    performed_by INT NOT NULL COMMENT 'User who performed the action',
    old_values JSON COMMENT 'Previous values before change',
    new_values JSON COMMENT 'New values after change',
    action_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45) COMMENT 'IP address of the user',
    user_agent TEXT COMMENT 'User agent of the user',
    
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (target_user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (permission_id) REFERENCES permissions(id) ON DELETE SET NULL,
    FOREIGN KEY (permission_group_id) REFERENCES permission_groups(id) ON DELETE SET NULL,
    FOREIGN KEY (performed_by) REFERENCES users(id) ON DELETE CASCADE,
    
    INDEX idx_action_type (action_type),
    INDEX idx_project_id (project_id),
    INDEX idx_performed_by (performed_by),
    INDEX idx_action_timestamp (action_timestamp)
);
```

## 🔄 RBAC Migration Strategy

### From Legacy to RBAC

**Current State (Legacy):**
```
project_groups.permissions = ["admin", "read", "write"]  // JSON array
```

**New RBAC State:**
```
Project 1:
├── Permissions: admin, read, write (individual records)
├── Role "full-access": [admin, read, write]
└── User assignments: user_id → role_id within project_id
```

### Migration Script Usage

```bash
# Check if RBAC tables exist
python rbac_migration_script.py --check-tables

# Create RBAC tables
python rbac_migration_script.py --create-tables

# See what would be migrated (no changes)
python rbac_migration_script.py --migrate-all --dry-run

# Migrate all existing projects
python rbac_migration_script.py --migrate-all

# Migrate specific project
python rbac_migration_script.py --migrate-project 1
```

## 📊 RBAC Permission Resolution

### Permission Check Query
```sql
-- Check if user has specific permission in project
SELECT COUNT(*) > 0 as has_permission
FROM users u
JOIN user_project_permission_groups uppg ON u.id = uppg.user_id
JOIN permission_groups pg ON uppg.permission_group_id = pg.id
JOIN permission_group_permissions pgp ON pg.id = pgp.permission_group_id
JOIN permissions p ON pgp.permission_id = p.id
WHERE u.id = ? 
AND uppg.project_id = ? 
AND p.permission_name = ?
AND u.is_active = 1 
AND uppg.is_active = 1 
AND pg.is_active = 1 
AND pgp.is_active = 1 
AND p.is_active = 1;
```

### User Effective Permissions Query
```sql
-- Get all permissions user has in a project
SELECT DISTINCT 
    p.permission_name,
    p.permission_display_name,
    p.permission_category,
    pg.group_name as role_name,
    pg.group_priority
FROM permissions p
JOIN permission_group_permissions pgp ON p.id = pgp.permission_id
JOIN permission_groups pg ON pgp.permission_group_id = pg.id
JOIN user_project_permission_groups uppg ON pg.id = uppg.permission_group_id
WHERE uppg.user_id = ? 
AND uppg.project_id = ?
AND p.is_active = 1 
AND pgp.is_active = 1 
AND pg.is_active = 1 
AND uppg.is_active = 1
ORDER BY pg.group_priority DESC, p.permission_category, p.permission_name;
```

## 🎯 RBAC Usage Examples

### 1. Initialize RBAC for New Project

```python
from src.Util.db import initialize_project_rbac

# When creating a new project
result = initialize_project_rbac(project_id=1, created_by=admin_user_id)
print(result)
# Output: {
#   'success': True,
#   'permissions_created': 13,
#   'roles_created': 6,
#   'permissions': ['read', 'write', 'admin', ...],
#   'roles': ['admin', 'manager', 'editor', ...]
# }
```

### 2. Assign User to Role in Project

```python
from src.Util.db import assign_user_to_permission_group

# Assign user to 'editor' role in project
success = assign_user_to_permission_group(
    user_id=user_id,
    project_id=project_id, 
    permission_group_id=editor_role_id,
    assigned_by=admin_user_id
)
```

### 3. Check User Permission

```python
from src.Util.db import check_user_permission

# Check if user can delete in project
can_delete = check_user_permission(
    user_id=user_id,
    project_id=project_id,
    permission_name='delete'
)
```

### 4. Create Custom Permission

```python
from src.Util.db import create_permission

# Create project-specific permission
permission = create_permission(
    project_id=project_id,
    permission_name='custom_feature_access',
    permission_display_name='Custom Feature Access',
    permission_description='Access to custom project features',
    permission_category='custom',
    created_by=admin_user_id
)
```

## 🔒 RBAC Security Benefits

### 1. **Project Isolation**
- Each project has completely separate permission catalog
- No cross-project permission pollution
- Database constraints enforce boundaries

### 2. **Granular Control**
- Individual permissions per project
- Role-based assignment for easier management
- Priority-based role hierarchy

### 3. **Complete Audit Trail**
- Every permission change logged
- Full context: who, what, when, from/to values
- IP address and user agent tracking

### 4. **Scalable Architecture**
- Supports thousands of projects with individual permissions
- Efficient queries with proper indexing
- Clean separation of concerns

## 🚀 Next Steps

### For Existing Systems
1. Run `rbac_migration_script.py --check-tables` to verify readiness
2. Use `--dry-run` to preview migration changes
3. Execute migration: `--migrate-all`
4. Update application code to use new RBAC functions

### For New Projects
- RBAC is automatically initialized when creating projects
- Use the new permission checking functions
- Create custom permissions as needed per project

---

**This RBAC-enhanced database schema provides a robust, scalable foundation for project-specific role-based access control while maintaining backward compatibility and providing comprehensive migration tools.** 