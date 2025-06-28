# Database Schema

Complete database documentation for the Group-Based Multi-Project Authentication system.

## 🏗️ Overview

The group-based authentication system provides a clean hierarchical access control model where:

1. **Users** belong to **User Groups** (global)
2. **User Groups** define which **Projects** users can access
3. **Projects** belong to **Project Groups** that define permissions
4. **Sessions** maintain context for both user and project groups

This design enables:
- **Centralized user management** through global user groups
- **Flexible project permissions** through project groups
- **Scalable access control** for thousands of users and projects
- **Clean audit trail** of all group assignments and access changes

## 📊 Database Structure

The system uses **6 main tables** in the `magic_auth_groups` database:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     users       │    │  user_groups    │    │    projects     │
│                 │    │                 │    │                 │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • id (PK)       │    │ • id (PK)       │    │ • id (PK)       │
│ • user_hash     │    │ • group_name    │    │ • project_hash  │
│ • username      │    │ • description   │    │ • project_name  │
│ • email         │    │ • permissions   │    │ • created_at    │
│ • password_hash │    │ • created_at    │    │ • created_at    │
└─────────────────┘    └─────────────────┘    └─────────────────┘
          │                       │                       │
          ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│user_group_members│   │user_group_projects│   │project_groups   │
│                 │    │                 │    │                 │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • user_id (FK)  │    │ • user_group_id │    │ • id (PK)       │
│ • user_group_id │    │ • project_id    │    │ • group_name    │
│ • assigned_at   │    │ • granted_at    │    │ • permissions   │
│ • assigned_by   │    │ • granted_by    │    │ • description   │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                                        │
                                                        ▼
                                           ┌─────────────────┐
                                           │project_group_   │
                                           │    members      │
                                           ├─────────────────┤
                                           │ • project_id    │
                                           │ • proj_group_id │
                                           │ • assigned_at   │
                                           │ • assigned_by   │
                                           └─────────────────┘
```

## 🗄️ Table Definitions

### 1. `users` - Global User Registry

Stores global user accounts that can be assigned to multiple user groups.

```sql
CREATE TABLE users (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Global user identifier',
    username VARCHAR(255) UNIQUE NOT NULL,
    email VARCHAR(255) UNIQUE,
    password_hash VARCHAR(64) NOT NULL COMMENT 'SHA256 hash of password',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    
    INDEX idx_user_hash (user_hash),
    INDEX idx_username (username),
    INDEX idx_email (email)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Global user registry';
```

**Key Features:**
- **Global Identity**: Each user has a unique `user_hash` for system-wide identification
- **Unique Constraints**: Username and email are globally unique
- **Clean Design**: Users exist independently of groups and projects

---

### 2. `user_groups` - Global User Groups

Defines global user groups that determine project access for their members.

```sql
CREATE TABLE user_groups (
    id INT PRIMARY KEY AUTO_INCREMENT,
    group_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Global group identifier',
    group_name VARCHAR(255) UNIQUE NOT NULL,
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT COMMENT 'User ID who created this group',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    
    INDEX idx_group_hash (group_hash),
    INDEX idx_group_name (group_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Global user groups for access control';
```

**Default User Groups:**
- `administrators`: Full system access across all projects
- `users`: Standard access to assigned projects  
- `guests`: Limited read-only access

---

### 3. `user_group_members` - User Group Membership

Links users to their user groups with assignment tracking.

```sql
CREATE TABLE user_group_members (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    user_group_id INT NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT COMMENT 'User ID who made the assignment',
    removed_at TIMESTAMP NULL,
    removed_by INT COMMENT 'User ID who removed the assignment',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (user_group_id) REFERENCES user_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(id) ON DELETE SET NULL,
    
    UNIQUE KEY unique_user_group (user_id, user_group_id),
    INDEX idx_user_id (user_id),
    INDEX idx_user_group_id (user_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='User membership in user groups';
```

**Key Features:**
- **Multi-Group Support**: Users can belong to multiple groups
- **Assignment Tracking**: Records who assigned/removed group membership
- **Audit Trail**: Complete history of group assignments

---

### 4. `projects` - Project Registry

Stores project/application definitions that can be assigned to project groups.

```sql
CREATE TABLE projects (
    id INT PRIMARY KEY AUTO_INCREMENT,
    project_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Project identifier',
    project_name VARCHAR(255) NOT NULL,
    project_description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT COMMENT 'User ID who created this project',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    
    INDEX idx_project_hash (project_hash),
    INDEX idx_project_name (project_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Project/Application registry';
```

**Key Features:**
- **Unique Project Hash**: Each project has a unique identifier
- **Creator Tracking**: Records who created the project
- **Clean Design**: Projects exist independently of groups

---

### 5. `user_group_projects` - Group Project Access

Defines which projects each user group can access.

```sql
CREATE TABLE user_group_projects (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_group_id INT NOT NULL,
    project_id INT NOT NULL,
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    granted_by INT COMMENT 'User ID who granted access',
    revoked_at TIMESTAMP NULL,
    revoked_by INT COMMENT 'User ID who revoked access',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (user_group_id) REFERENCES user_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (granted_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (revoked_by) REFERENCES users(id) ON DELETE SET NULL,
    
    UNIQUE KEY unique_group_project (user_group_id, project_id),
    INDEX idx_user_group_id (user_group_id),
    INDEX idx_project_id (project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='User group access to projects';
```

**Key Features:**
- **Group-Based Access**: All users in a group get project access
- **Grant/Revoke Tracking**: Records who granted/revoked access and when
- **Centralized Management**: Manage project access through groups

---

### 6. `project_groups` - Permission Groups for Projects

Defines permission groups that projects can be assigned to.

```sql
CREATE TABLE project_groups (
    id INT PRIMARY KEY AUTO_INCREMENT,
    group_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Project group identifier',
    group_name VARCHAR(255) UNIQUE NOT NULL,
    permissions JSON COMMENT 'Array of permission strings',
    description TEXT,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    created_by INT COMMENT 'User ID who created this group',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL,
    
    INDEX idx_group_hash (group_hash),
    INDEX idx_group_name (group_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Permission groups for projects';
```

**Default Project Groups:**
- `full-access`: Complete project control (admin, read, write, delete)
- `read-write`: Standard user permissions (read, write, create)
- `read-only`: View-only access (read, view)

---

### 7. `project_group_members` - Project Group Assignments

Links projects to their permission groups.

```sql
CREATE TABLE project_group_members (
    id INT PRIMARY KEY AUTO_INCREMENT,
    project_id INT NOT NULL,
    project_group_id INT NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT COMMENT 'User ID who made the assignment',
    removed_at TIMESTAMP NULL,
    removed_by INT COMMENT 'User ID who removed the assignment',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (project_group_id) REFERENCES project_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(id) ON DELETE SET NULL,
    
    UNIQUE KEY unique_project_group (project_id, project_group_id),
    INDEX idx_project_id (project_id),
    INDEX idx_project_group_id (project_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Project assignments to permission groups';
```

**Key Features:**
- **Flexible Permissions**: Projects inherit permissions from their groups
- **Assignment Tracking**: Records who assigned projects to groups
- **Multiple Assignments**: Projects can belong to multiple permission groups

---

### 8. `user_sessions` - Group-Aware Session Management

Tracks active user sessions with group context.

```sql
CREATE TABLE user_sessions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    session_token VARCHAR(64) UNIQUE NOT NULL,
    user_id INT NOT NULL,
    user_group_id INT COMMENT 'Primary user group for this session',
    project_id INT COMMENT 'Current project context',
    project_group_id INT COMMENT 'Project group providing permissions',
    session_data JSON COMMENT 'Additional session context',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (user_group_id) REFERENCES user_groups(id) ON DELETE SET NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL,
    FOREIGN KEY (project_group_id) REFERENCES project_groups(id) ON DELETE SET NULL,
    
    INDEX idx_session_token (session_token),
    INDEX idx_user_id (user_id),
    INDEX idx_user_group_id (user_group_id),
    INDEX idx_project_id (project_id),
    INDEX idx_expires_at (expires_at),
    INDEX idx_last_activity (last_activity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Group-aware user session tracking';
```

**Key Features:**
- **Group Context**: Sessions include both user group and project group information
- **Project Context**: Each session is tied to a specific project
- **Permission Resolution**: Fast access to user's permissions through groups
- **Activity Tracking**: Records IP address, user agent, and last activity

---

## 🔑 Group-Based Permissions

### User Groups and Their Default Permissions

#### Administrators Group
```json
{
  "group_name": "administrators",
  "description": "System administrators with full access",
  "default_project_access": "all_projects",
  "management_permissions": [
    "create_projects",
    "manage_user_groups", 
    "manage_project_groups",
    "grant_project_access",
    "view_system_stats"
  ]
}
```

#### Users Group
```json
{
  "group_name": "users",
  "description": "Standard users with assigned project access",
  "default_project_access": "assigned_projects_only",
  "management_permissions": [
    "view_assigned_projects",
    "switch_between_projects"
  ]
}
```

#### Guests Group
```json
{
  "group_name": "guests",
  "description": "Limited access users",
  "default_project_access": "read_only_projects",
  "management_permissions": [
    "view_public_projects"
  ]
}
```

### Project Groups and Their Permissions

#### Full-Access Group
```json
{
  "group_name": "full-access",
  "description": "Complete project control",
  "permissions": [
    "admin",
    "read", 
    "write", 
    "delete",
    "manage_users",
    "manage_settings",
    "view_statistics"
  ]
}
```

#### Read-Write Group
```json
{
  "group_name": "read-write",
  "description": "Standard user permissions",
  "permissions": [
    "read",
    "write",
    "create"
  ]
}
```

#### Read-Only Group
```json
{
  "group_name": "read-only",
  "description": "View-only access",
  "permissions": [
    "read",
    "view"
  ]
}
```

## 📈 Key Features Implementation

### 1. Hierarchical Group-Based Access Control

The system implements a clean hierarchy:

```sql
-- Get user's project access through their groups
SELECT DISTINCT p.project_hash, p.project_name, pg.permissions
FROM users u
JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
JOIN user_group_projects ugp ON ug.id = ugp.user_group_id AND ugp.is_active = 1
JOIN projects p ON ugp.project_id = p.id AND p.is_active = 1
JOIN project_group_members pgm ON p.id = pgm.project_id AND pgm.is_active = 1
JOIN project_groups pg ON pgm.project_group_id = pg.id AND pg.is_active = 1
WHERE u.user_hash = ? AND u.is_active = 1;
```

### 2. Permission Resolution

User permissions are resolved by combining their user group access with project group permissions:

```sql
-- Get user's effective permissions for a specific project
SELECT JSON_UNQUOTE(JSON_EXTRACT(pg.permissions, '$[*]')) as permission
FROM users u
JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
JOIN user_group_projects ugp ON ug.id = ugp.user_group_id AND ugp.is_active = 1
JOIN projects p ON ugp.project_id = p.id AND p.is_active = 1
JOIN project_group_members pgm ON p.id = pgm.project_id AND pgm.is_active = 1
JOIN project_groups pg ON pgm.project_group_id = pg.id AND pg.is_active = 1
WHERE u.user_hash = ? AND p.project_hash = ?
AND u.is_active = 1;
```

### 3. Group Management Operations

The system provides comprehensive CRUD operations for group management:

```python
# Example group operations using the CRUD modules
from group_based_crud_operations import (
    UserGroupCRUD, ProjectGroupCRUD, UserGroupMembershipCRUD,
    ProjectAccessCRUD, ProjectGroupMembershipCRUD, PermissionUtils
)

# Create user group
admin_group = UserGroupCRUD.create(
    "developers", 
    "Software development team",
    created_by=admin_user_id
)

# Create project group with permissions
api_permissions = ProjectGroupCRUD.create(
    "api-access",
    ["read", "write", "api_access"],
    "API access permissions",
    created_by=admin_user_id
)

# Assign user to group
UserGroupMembershipCRUD.assign_user_to_group(
    user_id, admin_group.id, assigned_by=admin_user_id
)

# Grant group access to project
ProjectAccessCRUD.grant_group_project_access(
    admin_group.id, project_id, granted_by=admin_user_id
)

# Assign project to permission group
ProjectGroupMembershipCRUD.assign_project_to_group(
    project_id, api_permissions.id, assigned_by=admin_user_id
)
```

## 📊 Usage Examples

### 1. User Registration and Group Assignment Flow

```sql
-- 1. Create global user
INSERT INTO users (user_hash, username, email, password_hash)
VALUES ('USER_HASH_123', 'john_doe', 'john@example.com', 'HASHED_PASSWORD');

-- 2. Assign user to 'users' group
INSERT INTO user_group_members (user_id, user_group_id, assigned_by)
SELECT u.id, ug.id, 1
FROM users u, user_groups ug
WHERE u.user_hash = 'USER_HASH_123' AND ug.group_name = 'users';

-- 3. Grant 'users' group access to a project (done by admin)
INSERT INTO user_group_projects (user_group_id, project_id, granted_by)
SELECT ug.id, p.id, 1
FROM user_groups ug, projects p
WHERE ug.group_name = 'users' AND p.project_hash = 'PROJECT_HASH_456';
```

### 2. Project Creation and Group Assignment

```sql
-- 1. Create project
INSERT INTO projects (project_hash, project_name, project_description, created_by)
VALUES ('PROJECT_HASH_789', 'New API Project', 'RESTful API service', 1);

-- 2. Assign project to 'full-access' permission group
INSERT INTO project_group_members (project_id, project_group_id, assigned_by)
SELECT p.id, pg.id, 1
FROM projects p, project_groups pg
WHERE p.project_hash = 'PROJECT_HASH_789' AND pg.group_name = 'full-access';

-- 3. Grant user group access to the new project
INSERT INTO user_group_projects (user_group_id, project_id, granted_by)
SELECT ug.id, p.id, 1
FROM user_groups ug, projects p
WHERE ug.group_name = 'administrators' AND p.project_hash = 'PROJECT_HASH_789';
```

### 3. Permission Check Example

```sql
-- Check if user has 'admin' permission for a project
SELECT COUNT(*) > 0 as has_permission
FROM users u
JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
JOIN user_group_projects ugp ON ug.id = ugp.user_group_id AND ugp.is_active = 1
JOIN projects p ON ugp.project_id = p.id AND p.is_active = 1
JOIN project_group_members pgm ON p.id = pgm.project_id AND pgm.is_active = 1
JOIN project_groups pg ON pgm.project_group_id = pg.id AND pg.is_active = 1
WHERE u.user_hash = 'USER_HASH_123' 
AND p.project_hash = 'PROJECT_HASH_456'
AND JSON_CONTAINS(pg.permissions, '"admin"')
AND u.is_active = 1;
```

## 🔒 Security Considerations

1. **Group-Based Access Control**: All access is managed through group membership
2. **Audit Trail**: Complete tracking of all group assignments and changes
3. **Session Security**: Group context included in session tokens
4. **Permission Isolation**: Users only see projects their groups can access
5. **Hierarchical Permissions**: Clear permission inheritance through groups
6. **Soft Deletes**: Uses `is_active` flags to maintain audit history

## ⚡ Performance Optimizations

1. **Strategic Indexing**: Indexes on all group relationship foreign keys
2. **Redis Caching**: Group context and permissions cached for fast access
3. **Composite Keys**: Unique constraints prevent duplicate relationships
4. **Optimized Queries**: Efficient joins for group-based permission resolution
5. **Cascading Operations**: Automatic cleanup of related records

## 🔄 Backup and Maintenance

### Daily Maintenance

```sql
-- Clean up expired sessions
DELETE FROM user_sessions 
WHERE expires_at < NOW() AND is_active = 0;

-- Update session activity tracking
UPDATE user_sessions 
SET is_active = 0 
WHERE last_activity < DATE_SUB(NOW(), INTERVAL 30 DAY);
```

### Weekly Group Reports

```sql
-- Group membership summary
SELECT 
    ug.group_name,
    COUNT(DISTINCT ugm.user_id) as member_count,
    COUNT(DISTINCT ugp.project_id) as project_access_count,
    MAX(ugm.assigned_at) as last_member_added
FROM user_groups ug
LEFT JOIN user_group_members ugm ON ug.id = ugm.user_group_id AND ugm.is_active = 1
LEFT JOIN user_group_projects ugp ON ug.id = ugp.user_group_id AND ugp.is_active = 1
WHERE ug.is_active = 1
GROUP BY ug.id, ug.group_name
ORDER BY member_count DESC;
```

### Database Backup

```bash
# Create full backup
mysqldump -u root -p magic_auth_groups > backup_groups_$(date +%Y%m%d_%H%M%S).sql

# Backup group-related tables
mysqldump -u root -p magic_auth_groups \
  users user_groups user_group_members \
  projects project_groups project_group_members \
  user_group_projects user_sessions \
  > group_backup.sql
```

## 📚 Integration with Application

The database schema integrates seamlessly with the group-based application structure:

1. **Database Layer**: Group-based CRUD operations in `group_based_crud_operations.py`
2. **API Layer**: RESTful endpoints organized by function:
   - `src/routes/auth.py` - Authentication endpoints
   - `src/routes/users.py` - User management  
   - `src/routes/projects.py` - Project management
   - `src/routes/admin_user_groups.py` - User group administration
   - `src/routes/admin_project_groups.py` - Project group administration
   - `src/routes/system.py` - System information
3. **Security Layer**: Group-aware token validation
4. **Session Layer**: Redis caching with group context

### Example Integration

```python
# Application integration example
from group_based_crud_operations import PermissionUtils

# Check user permission for action
def check_user_permission(user_id, project_id, required_permission):
    return PermissionUtils.check_user_permission(
        user_id, project_id, required_permission
    )

# Get user's accessible projects
def get_user_projects(user_id):
    return PermissionUtils.get_user_accessible_projects(user_id)

# Get user's effective permissions for project
def get_user_permissions(user_id, project_id):
    return PermissionUtils.get_user_project_permissions(user_id, project_id)
```

---

**This group-based database schema provides a robust foundation for hierarchical access control while maintaining clean separation between user groups (who can access what) and project groups (what permissions they have). The design supports thousands of users and projects while keeping management simple and audit trails complete.** 