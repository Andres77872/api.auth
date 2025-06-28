# Database Schema

Complete database documentation for the Enhanced Multi-Project Authentication system.

## 🏗️ Overview

The enhanced authentication system provides multi-project user isolation with the ability to share users across projects and manage group-based permissions. The system supports:

1. **Project Isolation**: Users registered to one project are isolated by default
2. **Cross-Project Access**: Same user can be granted access to multiple projects
3. **Project Fusion**: When projects are linked, users can access both with their existing accounts
4. **Group-Based Permissions**: Apps/projects are defined by groups with specific permissions
5. **Global User Identity**: Users have a global identity that can be mapped to multiple projects

## 📊 Database Structure

The system uses **6 main tables** in the `magic_auth_enhanced` database:

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│     users       │    │  user_projects  │    │    projects     │
│                 │    │                 │    │                 │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • id (PK)       │◄──┐│ • user_id (FK)  │┌──►│ • id (PK)       │
│ • user_hash     │   ││ • project_id(FK)││   │ • project_hash  │
│ • username      │   │└─────────────────┘│   │ • project_name  │
│ • email         │   │                   │   │ • description   │
│ • password_hash │   │                   │   └─────────────────┘
└─────────────────┘   │                   │
                      │                   │
┌─────────────────┐   │ ┌─────────────────┐   │
│  user_groups    │◄──┼─┤user_project_grps│◄──┘
│                 │   │ │                 │
├─────────────────┤   │ ├─────────────────┤
│ • id (PK)       │   │ │ • user_proj_id  │
│ • project_id    │   │ │ • group_id (FK) │
│ • group_name    │   │ └─────────────────┘
│ • permissions   │   │
└─────────────────┘   │ ┌─────────────────┐
                      └─┤ user_sessions   │
                        │                 │
                        ├─────────────────┤
                        │ • user_proj_id  │
                        │ • session_token │
                        │ • expires_at    │
                        └─────────────────┘
```

## 🗄️ Table Definitions

### 1. `users` - Global User Identity

Stores global user accounts that can access multiple projects.

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
COMMENT='Global user accounts';
```

**Key Features:**
- **Global Identity**: Each user has a unique `user_hash` for cross-project identification
- **Unique Constraints**: Username and email are globally unique
- **Password Security**: SHA256 hashed passwords
- **Soft Deletes**: Uses `is_active` flag for data integrity

---

### 2. `projects` - Project/Application Registry

Stores project/application definitions.

```sql
CREATE TABLE projects (
    id INT PRIMARY KEY AUTO_INCREMENT,
    project_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Project identifier',
    project_name VARCHAR(255) NOT NULL,
    project_description TEXT,
    project_created TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    
    INDEX idx_project_hash (project_hash),
    INDEX idx_project_name (project_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Project/Application registry';
```

**Key Features:**
- **Unique Project Hash**: Each project has a unique identifier
- **Flexible Metadata**: Name and description for project management
- **Soft Deletes**: Maintains project history even when deactivated

---

### 3. `user_projects` - User-Project Access Mapping

Links users to projects they have access to.

```sql
CREATE TABLE user_projects (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    project_id INT NOT NULL,
    user_project_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Unique identifier for this relationship',
    granted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    granted_by INT COMMENT 'User ID who granted access',
    revoked_at TIMESTAMP NULL,
    revoked_by INT COMMENT 'User ID who revoked access',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (granted_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (revoked_by) REFERENCES users(id) ON DELETE SET NULL,
    
    UNIQUE KEY unique_user_project (user_id, project_id),
    INDEX idx_user_id (user_id),
    INDEX idx_project_id (project_id),
    INDEX idx_user_project_hash (user_project_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='User access to projects';
```

**Key Features:**
- **Cross-Project Access**: One user can have multiple project relationships
- **Audit Trail**: Tracks who granted/revoked access and when
- **Unique Relationship Hash**: Each user-project relationship has unique identifier
- **Referential Integrity**: Proper foreign key constraints

---

### 4. `user_groups` - Project-Specific Groups

Defines groups within each project with associated permissions.

```sql
CREATE TABLE user_groups (
    id INT PRIMARY KEY AUTO_INCREMENT,
    project_id INT NOT NULL,
    group_name VARCHAR(255) NOT NULL,
    group_description TEXT,
    permissions JSON COMMENT 'Array of permission strings',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    
    UNIQUE KEY unique_group_per_project (project_id, group_name),
    INDEX idx_project_id (project_id),
    INDEX idx_group_name (group_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='Groups within projects';
```

**Key Features:**
- **Project-Specific**: Each project defines its own groups
- **Flexible Permissions**: JSON array stores customizable permissions
- **Default Groups**: System creates admin, user, readonly groups automatically

---

### 5. `user_project_groups` - User Group Membership

Links users to groups within projects.

```sql
CREATE TABLE user_project_groups (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_project_id INT NOT NULL,
    group_id INT NOT NULL,
    assigned_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT COMMENT 'User ID who made the assignment',
    removed_at TIMESTAMP NULL,
    removed_by INT COMMENT 'User ID who removed the assignment',
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (user_project_id) REFERENCES user_projects(id) ON DELETE CASCADE,
    FOREIGN KEY (group_id) REFERENCES user_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(id) ON DELETE SET NULL,
    
    UNIQUE KEY unique_user_group (user_project_id, group_id),
    INDEX idx_user_project_id (user_project_id),
    INDEX idx_group_id (group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='User membership in project groups';
```

**Key Features:**
- **Multi-Group Support**: Users can belong to multiple groups per project
- **Assignment Tracking**: Records who assigned/removed group membership
- **Cascade Deletes**: Automatically cleans up when users or groups are removed

---

### 6. `user_sessions` - Session Management

Tracks active user sessions (complemented by Redis for performance).

```sql
CREATE TABLE user_sessions (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_project_id INT NOT NULL,
    session_token VARCHAR(64) UNIQUE NOT NULL,
    session_key VARCHAR(255) COMMENT 'Legacy compatibility',
    session_value TEXT COMMENT 'Legacy compatibility',
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    expires_at TIMESTAMP NOT NULL,
    last_activity TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent TEXT,
    is_active BOOLEAN DEFAULT TRUE,
    
    FOREIGN KEY (user_project_id) REFERENCES user_projects(id) ON DELETE CASCADE,
    
    INDEX idx_session_token (session_token),
    INDEX idx_user_project_id (user_project_id),
    INDEX idx_expires_at (expires_at),
    INDEX idx_last_activity (last_activity)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci 
COMMENT='User session tracking';
```

**Key Features:**
- **Session Security**: Secure token-based session management
- **Project Context**: Each session is tied to a specific user-project relationship
- **Activity Tracking**: Records IP address, user agent, and last activity
- **Expiration Management**: Automatic session expiration handling

## 🔑 Default Groups and Permissions

When a new project is created, the following default groups are automatically created:

### Admin Group
```json
{
  "group_name": "admin",
  "group_description": "Project administrators",
  "permissions": [
    "admin",
    "read", 
    "write", 
    "delete", 
    "manage_users", 
    "manage_groups"
  ]
}
```

### User Group
```json
{
  "group_name": "user",
  "group_description": "Regular users",
  "permissions": [
    "read",
    "write"
  ]
}
```

### Readonly Group
```json
{
  "group_name": "readonly",
  "group_description": "Read-only users",
  "permissions": [
    "read"
  ]
}
```

## 🔐 Permission System

The permission system uses JSON arrays to store permissions for each group. Common permissions include:

| Permission | Description |
|------------|-------------|
| `read` | Can read/view content |
| `write` | Can create/edit content |
| `delete` | Can delete content |
| `admin` | Full administrative access |
| `manage_users` | Can grant/revoke user access |
| `manage_groups` | Can manage group memberships |
| `create_projects` | Can create new projects |

### Custom Permissions

Projects can define custom permissions based on their specific needs:

```json
{
  "permissions": [
    "read",
    "write", 
    "export_data",
    "manage_billing",
    "api_access"
  ]
}
```

## 📈 Key Features Implementation

### 1. User Isolation by Project

Users are isolated by default through the `user_projects` table. A user can only access a project if they have an active record linking them to that project.

```sql
-- Check if user has access to project
SELECT up.* FROM user_projects up
JOIN users u ON u.id = up.user_id
JOIN projects p ON p.id = up.project_id
WHERE u.user_hash = ? AND p.project_hash = ? AND up.is_active = 1;
```

### 2. Cross-Project User Access

The same global user can have multiple entries in `user_projects`, giving them access to multiple projects with potentially different permissions in each.

```sql
-- Get all projects user has access to
SELECT p.project_hash, p.project_name, up.user_project_hash
FROM user_projects up
JOIN projects p ON p.id = up.project_id
WHERE up.user_id = ? AND up.is_active = 1 AND p.is_active = 1;
```

### 3. Permission Resolution

User permissions are resolved by combining all permissions from their groups within a project:

```sql
-- Get all permissions for user in project
SELECT DISTINCT JSON_UNQUOTE(JSON_EXTRACT(ug.permissions, '$[*]')) as permission
FROM user_projects up
JOIN user_project_groups upg ON up.id = upg.user_project_id
JOIN user_groups ug ON upg.group_id = ug.id
WHERE up.user_id = ? AND up.project_id = ?
AND up.is_active = 1 AND upg.is_active = 1 AND ug.is_active = 1;
```

## 🔧 Modular Database Structure

The database operations are organized into specialized modules:

### **Module Organization**

```
src/Util/db/
├── __init__.py         # Main interface - imports and re-exports all functions
├── db_enhanced.py      # Core authentication functions
├── db_users.py         # User management operations  
└── db_projects.py      # Project management operations
```

### **Function Distribution**

#### User Operations (`db_users.py`)
- **User CRUD**: `create_user()`, `get_user_by_*()`, `update_user()`, `delete_user()`
- **Authentication**: `get_user_by_credentials()`, `check_username_email_available()`
- **User-Project Access**: `grant_user_project_access()`, `get_user_projects()`
- **Group Management**: `get_user_groups_in_project()`, `assign_user_to_group()`
- **Session Management**: `create_session()`, `invalidate_session()`

#### Project Operations (`db_projects.py`)
- **Project CRUD**: `create_project()`, `get_project_by_*()`, `update_project()`, `delete_project()`
- **Statistics**: `get_project_stats()`, `count_projects()`, `search_projects()`
- **Group Management**: `get_project_groups()`, `create_project_group()`, `create_default_groups()`

#### Authentication (`db_enhanced.py`)
- **Enhanced Functions**: `enhanced_login()`, `enhanced_register()`, `validate_session()`
- **Legacy Compatibility**: `db_login()`, `db_register()`, `db_username_or_email_available()`

## 📊 Usage Examples

### 1. User Registration Flow

```sql
-- 1. Create global user
INSERT INTO users (user_hash, username, email, password_hash)
VALUES ('ABC123...', 'john_doe', 'john@example.com', 'HASH...');

-- 2. Grant access to project
INSERT INTO user_projects (user_id, project_id, user_project_hash)
VALUES (1, 1, 'DEF456...');

-- 3. Assign to default 'user' group
INSERT INTO user_project_groups (user_project_id, group_id)
VALUES (1, 2); -- Assuming group_id 2 is the 'user' group
```

### 2. Grant Cross-Project Access

```sql
-- User with ID 1 already exists, grant access to project 2
INSERT INTO user_projects (user_id, project_id, user_project_hash, granted_by)
VALUES (1, 2, 'GHI789...', 3); -- Granted by user 3

-- Assign to appropriate group in the new project
INSERT INTO user_project_groups (user_project_id, group_id, assigned_by)
VALUES (2, 5, 3); -- Assign to group 5, assigned by user 3
```

### 3. Project Fusion Example

```sql
-- Scenario: Merge two projects and give existing users access to both

-- Get all users from source project
SELECT DISTINCT user_id FROM user_projects 
WHERE project_id = 1 AND is_active = 1;

-- Grant access to target project for each user
INSERT INTO user_projects (user_id, project_id, user_project_hash, granted_by)
SELECT user_id, 2, CONCAT('fusion_', UUID()), NULL
FROM user_projects 
WHERE project_id = 1 AND is_active = 1;
```

## 🔒 Security Considerations

1. **Password Hashing**: Uses SHA256 for consistency with legacy system
2. **Session Management**: Combines database tracking with Redis for performance
3. **Access Control**: Multi-layered through user-project-group relationships
4. **Audit Trail**: Tracks who granted/revoked access and when
5. **Soft Deletes**: Uses `is_active` flags to maintain audit history
6. **Foreign Keys**: Proper referential integrity constraints

## ⚡ Performance Optimizations

1. **Strategic Indexing**: Indexes on frequently queried columns (`user_hash`, `project_hash`, `session_token`)
2. **Redis Caching**: Session data cached in Redis for fast access
3. **Composite Keys**: Unique constraints prevent duplicate relationships
4. **Cascading Operations**: Automatic cleanup of related records
5. **Query Optimization**: Efficient joins and filtering

## 🔄 Backup and Maintenance

### Daily Maintenance

```sql
-- Clean up expired sessions
DELETE FROM user_sessions 
WHERE expires_at < NOW() AND is_active = 0;

-- Update session activity
UPDATE user_sessions 
SET is_active = 0 
WHERE last_activity < DATE_SUB(NOW(), INTERVAL 30 DAY);
```

### Weekly Reports

```sql
-- Project activity summary
SELECT 
    p.project_name,
    COUNT(DISTINCT up.user_id) as active_users,
    COUNT(us.id) as active_sessions,
    MAX(us.last_activity) as last_activity
FROM projects p
LEFT JOIN user_projects up ON p.id = up.project_id AND up.is_active = 1
LEFT JOIN user_sessions us ON up.id = us.user_project_id AND us.is_active = 1
WHERE p.is_active = 1
GROUP BY p.id, p.project_name
ORDER BY active_users DESC;
```

### Database Backup

```bash
# Create full backup
mysqldump -u root -p magic_auth_enhanced > backup_$(date +%Y%m%d_%H%M%S).sql

# Backup specific tables
mysqldump -u root -p magic_auth_enhanced users projects user_projects > critical_backup.sql
```

## 📚 Integration with Application

The database schema integrates seamlessly with the modular application structure:

1. **Database Layer**: Modular functions in `src/Util/db/`
2. **API Layer**: RESTful endpoints in `src/routes/`
3. **Security Layer**: Token validation in `src/Util/Seccurity.py`
4. **Session Layer**: Redis caching for performance

---

**This database schema provides a robust foundation for multi-project authentication while maintaining backward compatibility and supporting all the requested features for user isolation, cross-project access, and group-based permissions.** 