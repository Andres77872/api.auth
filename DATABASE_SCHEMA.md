# Enhanced Multi-Project Authentication Database Schema

## Overview

This enhanced authentication system provides multi-project user isolation with the ability to share users across projects and manage group-based permissions. The system supports the following key requirements:

1. **Project Isolation**: Users registered to one project are isolated by default
2. **Cross-Project Access**: Same user can be granted access to multiple projects
3. **Project Fusion**: When projects are linked, users can access both with their existing accounts
4. **Group-Based Permissions**: Apps/projects are defined by groups with specific permissions
5. **Global User Identity**: Users have a global identity that can be mapped to multiple projects

## Database Structure

### Core Tables

#### 1. `users` - Global User Identity
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Global user accounts';
```

#### 2. `projects` - Project/Application Registry
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Project/Application registry';
```

#### 3. `user_projects` - User-Project Access Mapping
Links users to projects they have access to.

```sql
CREATE TABLE user_projects (
    id INT PRIMARY KEY AUTO_INCREMENT,
    user_id INT NOT NULL,
    project_id INT NOT NULL,
    user_project_hash VARCHAR(64) UNIQUE NOT NULL COMMENT 'Unique identifier for this user-project relationship',
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User access to projects';
```

#### 4. `user_groups` - Project-Specific Groups
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='Groups within projects';
```

#### 5. `user_project_groups` - User Group Membership
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User membership in project groups';
```

#### 6. `user_sessions` - Session Management
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
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci COMMENT='User session tracking';
```

### Default Groups and Permissions

When a new project is created, the following default groups are automatically created:

```sql
-- Default groups inserted for each new project
INSERT INTO user_groups (project_id, group_name, group_description, permissions) VALUES
(?, 'admin', 'Project administrators', '["admin", "read", "write", "delete", "manage_users", "manage_groups"]'),
(?, 'user', 'Regular users', '["read", "write"]'),
(?, 'readonly', 'Read-only users', '["read"]');
```

### Permission System

The permission system uses JSON arrays to store permissions for each group. Common permissions include:

- `read` - Can read/view content
- `write` - Can create/edit content
- `delete` - Can delete content
- `admin` - Full administrative access
- `manage_users` - Can grant/revoke user access
- `manage_groups` - Can manage group memberships
- `create_projects` - Can create new projects

## Key Features Implementation

### 1. User Isolation by Project

Users are isolated by default through the `user_projects` table. A user can only access a project if they have a record in this table linking them to that project.

### 2. Cross-Project User Access

The same global user (from `users` table) can have multiple entries in `user_projects`, giving them access to multiple projects with potentially different permissions in each.

### 3. Project Fusion Support

When two projects need to be "fused" or linked:

1. Identify users who should have access to both projects
2. Create `user_projects` entries for the target project
3. Assign appropriate groups based on business logic
4. Users can then switch between projects using the same credentials

### 4. Group-Based App Definition

Projects are defined by their groups and permissions:
- Different projects can have different group structures
- Permissions are flexible and can be customized per project
- Users get the combined permissions of all groups they belong to

## Migration Strategy

### From Legacy System

The enhanced system includes legacy compatibility functions:

1. `db_login()` - Maps to `enhanced_login()`
2. `db_register()` - Maps to `enhanced_register()`
3. `db_username_or_email_available()` - Maps to global availability check

### Migration Steps

1. **Create Enhanced Tables**: Run the table creation scripts
2. **Migrate Existing Data**:
   ```sql
   -- Migrate collections to projects
   INSERT INTO projects (project_hash, project_name, project_created)
   SELECT collection_hash, 'Legacy Project', NOW()
   FROM tb_collection;
   
   -- Create global users from existing collection users
   INSERT INTO users (user_hash, username, email, password_hash, created_at)
   SELECT DISTINCT user_hash, user_name, user_email, user_password, user_creation
   FROM tb_collection_user;
   
   -- Create user-project relationships
   INSERT INTO user_projects (user_id, project_id, user_project_hash, granted_at)
   SELECT u.id, p.id, tcu.user_hash, tcu.user_creation
   FROM tb_collection_user tcu
   JOIN users u ON u.user_hash = tcu.user_hash
   JOIN projects p ON p.project_hash = (
       SELECT collection_hash 
       FROM tb_collection 
       WHERE id_collection = tcu.id_collection
   );
   ```

## Usage Examples

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

### 3. Query User Permissions

```sql
-- Get all permissions for a user in a specific project
SELECT DISTINCT JSON_UNQUOTE(JSON_EXTRACT(ug.permissions, '$[*]')) as permission
FROM user_projects up
JOIN user_project_groups upg ON up.id = upg.user_project_id
JOIN user_groups ug ON upg.group_id = ug.id
WHERE up.user_id = ? AND up.project_id = ?
AND up.is_active = 1 AND upg.is_active = 1 AND ug.is_active = 1;
```

## Security Considerations

1. **Password Hashing**: Uses SHA256 for consistency with legacy system
2. **Session Management**: Combines database tracking with Redis for performance
3. **Access Control**: Multi-layered through user-project-group relationships
4. **Audit Trail**: Tracks who granted/revoked access and when
5. **Soft Deletes**: Uses `is_active` flags to maintain audit history

## Performance Optimizations

1. **Indexing**: Strategic indexes on frequently queried columns
2. **Redis Sessions**: Session data cached in Redis for fast access
3. **Composite Keys**: Unique constraints prevent duplicate relationships
4. **Cascading Deletes**: Automatic cleanup of related records

## Backup and Maintenance

```sql
-- Clean up expired sessions
DELETE FROM user_sessions 
WHERE expires_at < NOW() AND is_active = 0;

-- Archive revoked access records older than 1 year
-- (Implementation depends on specific archival strategy)

-- Update last activity for session cleanup
UPDATE user_sessions 
SET is_active = 0 
WHERE last_activity < DATE_SUB(NOW(), INTERVAL 30 DAY);
```

This schema provides a robust foundation for multi-project authentication while maintaining backward compatibility and supporting all the requested features for user isolation, cross-project access, and group-based permissions. 