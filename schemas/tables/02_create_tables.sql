-- ===================================================================================
-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Table Creation Script (Restructured for Group-Based Access)
-- ===================================================================================
-- This script creates all tables needed for the authentication system
-- MySQL Database
-- ===================================================================================

USE magic_auth;

-- =================== USERS TABLE ===================
-- Supports 3-tier user types: root, admin, consumer
-- NO direct project assignments - ALL access through groups
CREATE TABLE IF NOT EXISTS users (
    id VARCHAR(64) NOT NULL,
    user_hash VARCHAR(255) NOT NULL,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    password_hash VARCHAR(255) NOT NULL,
    user_type ENUM('root', 'admin', 'consumer') NOT NULL DEFAULT 'consumer',
    role_id VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    last_login DATETIME NULL,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_hash (user_hash),
    UNIQUE KEY uk_username (username),
    INDEX idx_user_role (role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PROJECTS TABLE ===================
-- Applications/systems in the multi-project architecture
CREATE TABLE IF NOT EXISTS projects (
    id VARCHAR(64) NOT NULL,
    project_hash VARCHAR(255) NOT NULL,
    project_name VARCHAR(100) NOT NULL,
    project_description TEXT,
    project_created DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    archived BOOLEAN DEFAULT FALSE,
    owner_id VARCHAR(64),
    archived_at TIMESTAMP NULL,
    archived_by VARCHAR(64) NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_project_hash (project_hash)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_GROUPS TABLE ===================
-- Global user groups that can span multiple projects
-- Can have hierarchical structure (parent-child relationships)
CREATE TABLE IF NOT EXISTS user_groups (
    id VARCHAR(64) NOT NULL,
    group_hash VARCHAR(255) NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_description TEXT,
    parent_group_id VARCHAR(64) NULL, -- For hierarchical groups
    group_level INT NOT NULL DEFAULT 0, -- Hierarchy level (0 = root level)
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_group_hash (group_hash),
    UNIQUE KEY uk_group_name (group_name) -- Global unique group names
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_GROUP_MEMBERS TABLE ===================
-- Links users to user groups (many-to-many)
CREATE TABLE IF NOT EXISTS user_group_members (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    user_group_id VARCHAR(64) NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_group_member (user_id, user_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_GROUP_PROJECTS TABLE ===================
-- Links user groups to projects they have access to (many-to-many)
-- This is how users get access to projects - through their groups
CREATE TABLE IF NOT EXISTS user_group_projects (
    id VARCHAR(64) NOT NULL,
    user_group_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by VARCHAR(64),
    revoked_at DATETIME,
    revoked_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_group_project (user_group_id, project_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PROJECT_GROUPS TABLE ===================
-- Project groups that define sets of permissions
-- Used for organizing projects with similar permission sets
CREATE TABLE IF NOT EXISTS project_groups (
    id VARCHAR(64) NOT NULL,
    group_hash VARCHAR(255) NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_description TEXT,
    permissions JSON,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_project_group_hash (group_hash),
    UNIQUE KEY uk_project_group_name (group_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PROJECT_GROUP_MEMBERS TABLE ===================
-- Links projects to project groups (many-to-many)
-- Projects can belong to multiple groups to inherit different permission sets
CREATE TABLE IF NOT EXISTS project_group_members (
    id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    project_group_id VARCHAR(64) NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_project_group_member (project_id, project_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_SESSIONS TABLE ===================
-- Session management - simplified to work with user groups
CREATE TABLE IF NOT EXISTS user_sessions (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    session_token VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_session_token (session_token)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== API AUDIT LOG TABLE ===================
-- Comprehensive API request/response audit logging
-- Captures all API calls with complete request and response context
CREATE TABLE IF NOT EXISTS api_audit_log (
    id VARCHAR(64) NOT NULL,
    
    -- Request identification
    request_id VARCHAR(64),                    -- Unique request ID for tracing
    
    -- Endpoint information
    http_method VARCHAR(10) NOT NULL,          -- GET, POST, PUT, DELETE, PATCH
    endpoint_path VARCHAR(512) NOT NULL,       -- /api/v1/users/{hash}
    route_pattern VARCHAR(512),                -- Matched route pattern
    
    -- User context
    user_id VARCHAR(64),                       -- Authenticated user (NULL if unauthenticated)
    user_type ENUM('root', 'admin', 'consumer'),  -- User type at time of request
    session_id VARCHAR(256),                    -- Session identifier
    
    -- Request details
    request_headers JSON,                      -- Request headers (filtered, no sensitive data)
    request_body JSON,                         -- Request body (filtered, no passwords)
    request_query JSON,                        -- Query parameters
    request_size_bytes INT,                    -- Request payload size
    
    -- Response details
    response_status INT NOT NULL,              -- HTTP status code (200, 404, 500, etc.)
    response_body JSON,                        -- Response body (filtered, no sensitive data)
    response_headers JSON,                     -- Response headers (filtered)
    response_size_bytes INT,                   -- Response payload size
    
    -- Timing and performance
    request_timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    response_timestamp DATETIME,
    duration_ms INT,                           -- Request processing time in milliseconds
    
    -- Network information
    client_ip VARCHAR(45),                     -- Client IP address
    user_agent TEXT,                           -- User agent string
    referer VARCHAR(512),                      -- HTTP referer
    
    -- Result classification
    is_success BOOLEAN,                        -- TRUE if 2xx status, FALSE otherwise
    error_code VARCHAR(50),                    -- Application error code if failed
    error_message TEXT,                        -- Error message if failed
    
    -- Context
    project_id VARCHAR(64),                    -- Project context if applicable
    target_resource_type VARCHAR(50),          -- Resource type (user, project, group, etc.)
    target_resource_id VARCHAR(64),            -- Resource ID being accessed/modified
    
    -- Metadata
    metadata JSON,                             -- Additional context-specific data
    tags JSON,                                 -- Searchable tags (e.g., ["admin_action", "critical"])
    
    -- Security flags
    requires_audit BOOLEAN DEFAULT TRUE,       -- Mark for compliance auditing
    security_event BOOLEAN DEFAULT FALSE,      -- Flag security-related events
    
    PRIMARY KEY (id),
    INDEX idx_timestamp (request_timestamp DESC),
    INDEX idx_user_time (user_id, request_timestamp DESC),
    INDEX idx_endpoint (endpoint_path, http_method),
    INDEX idx_status (response_status, request_timestamp DESC),
    INDEX idx_user_endpoint (user_id, endpoint_path),
    INDEX idx_success (is_success, request_timestamp DESC),
    INDEX idx_project (project_id, request_timestamp DESC),
    INDEX idx_request_id (request_id),
    INDEX idx_security (security_event, request_timestamp DESC),
    INDEX idx_audit_required (requires_audit, request_timestamp DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_PASSWORD_RESETS TABLE ===================
CREATE TABLE IF NOT EXISTS user_password_resets (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    reset_token VARCHAR(255) NOT NULL,
    temporary_password_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP NULL,
    created_by VARCHAR(64) NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ROLE_ASSIGNMENT_HISTORY TABLE ===================
CREATE TABLE IF NOT EXISTS role_assignment_history (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    user_group_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    permission_group_id VARCHAR(64) NOT NULL,
    action ENUM('assigned', 'removed', 'modified') NOT NULL,
    performed_by VARCHAR(64) NOT NULL,
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details TEXT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== SYSTEM_METRICS TABLE ===================
CREATE TABLE IF NOT EXISTS system_metrics (
    id VARCHAR(64) NOT NULL,
    metric_name VARCHAR(100) NOT NULL,
    metric_value DECIMAL(15,4) NOT NULL,
    metric_unit VARCHAR(20) NULL,
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== BULK_OPERATIONS_LOG TABLE ===================
CREATE TABLE IF NOT EXISTS bulk_operations_log (
    id VARCHAR(64) NOT NULL,
    operation_type ENUM('bulk_update_users', 'bulk_delete_users', 'bulk_assign_roles', 'bulk_assign_groups') NOT NULL,
    performed_by VARCHAR(64) NOT NULL,
    target_count INT NOT NULL,
    success_count INT NOT NULL,
    error_count INT NOT NULL,
    operation_details JSON NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    status ENUM('running', 'completed', 'failed') DEFAULT 'running',
    PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERFORMANCE OPTIMIZATION TABLES ===================

-- Table for caching expensive permission calculations
CREATE TABLE IF NOT EXISTS permission_cache (
    user_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    permission_name VARCHAR(100) NOT NULL,
    has_permission BOOLEAN NOT NULL,
    cached_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, project_id, permission_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table for query performance tracking
CREATE TABLE IF NOT EXISTS query_performance_log (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    query_hash VARCHAR(64),
    query_type VARCHAR(50),
    execution_time_ms INT,
    rows_examined INT,
    rows_returned INT,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== GLOBAL ROLE SYSTEM TABLES ===================
-- Global roles, permissions, and permission groups that work across all projects
-- ==================================================================================

-- =================== GLOBAL ROLES TABLE ===================
-- Global roles - each user has ONE role that works everywhere
CREATE TABLE IF NOT EXISTS roles (
    id VARCHAR(64) NOT NULL,
    role_hash VARCHAR(255) NOT NULL,
    role_name VARCHAR(100) NOT NULL,
    role_display_name VARCHAR(255) NOT NULL,
    role_description TEXT,
    role_priority INT NOT NULL DEFAULT 50,
    is_system_role BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_role_hash (role_hash),
    UNIQUE KEY uk_role_name (role_name),
    INDEX idx_role_priority (role_priority),
    INDEX idx_role_name (role_name, is_active),
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== GLOBAL PERMISSION GROUPS TABLE ===================
-- Global permission groups - reusable containers of permissions
CREATE TABLE IF NOT EXISTS global_permission_groups (
    id VARCHAR(64) NOT NULL,
    group_hash VARCHAR(255) NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_display_name VARCHAR(255) NOT NULL,
    group_description TEXT,
    group_category VARCHAR(50) NOT NULL DEFAULT 'general',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_perm_group_hash (group_hash),
    UNIQUE KEY uk_perm_group_name (group_name),
    INDEX idx_category (group_category),
    INDEX idx_group_name (group_name, is_active),
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== GLOBAL PERMISSIONS TABLE ===================
-- Global permission definitions - defined once, used everywhere
CREATE TABLE IF NOT EXISTS global_permissions (
    id VARCHAR(64) NOT NULL,
    permission_hash VARCHAR(255) NOT NULL,
    permission_name VARCHAR(100) NOT NULL,
    permission_display_name VARCHAR(255) NOT NULL,
    permission_description TEXT,
    permission_category VARCHAR(50) NOT NULL DEFAULT 'general',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_permission_hash (permission_hash),
    UNIQUE KEY uk_permission_name (permission_name),
    INDEX idx_category (permission_category),
    INDEX idx_permission_name (permission_name, is_active),
    FOREIGN KEY (created_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ROLE PERMISSION GROUPS LINK TABLE ===================
-- Links roles to permission groups - defines role composition
CREATE TABLE IF NOT EXISTS role_permission_groups (
    id VARCHAR(64) NOT NULL,
    role_id VARCHAR(64) NOT NULL,
    permission_group_id VARCHAR(64) NOT NULL,
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    assigned_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_role_perm_group (role_id, permission_group_id),
    INDEX idx_role (role_id),
    INDEX idx_perm_group (permission_group_id),
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
    FOREIGN KEY (permission_group_id) REFERENCES global_permission_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSION GROUP PERMISSIONS LINK TABLE ===================
-- Links permission groups to permissions - defines permission group content
CREATE TABLE IF NOT EXISTS global_permission_group_permissions (
    id VARCHAR(64) NOT NULL,
    permission_group_id VARCHAR(64) NOT NULL,
    permission_id VARCHAR(64) NOT NULL,
    granted_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    granted_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_group_permission (permission_group_id, permission_id),
    INDEX idx_perm_group (permission_group_id),
    INDEX idx_permission (permission_id),
    FOREIGN KEY (permission_group_id) REFERENCES global_permission_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (permission_id) REFERENCES global_permissions(id) ON DELETE CASCADE,
    FOREIGN KEY (granted_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ROLE PROJECT CATALOG TABLE (METADATA ONLY) ===================
-- METADATA ONLY - Suggests which roles are relevant to projects (NOT used for authorization)
CREATE TABLE IF NOT EXISTS role_project_catalog (
    id VARCHAR(64) NOT NULL,
    role_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    catalog_purpose VARCHAR(255),
    notes TEXT,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    added_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_role_project (role_id, project_id),
    INDEX idx_project_roles (project_id),
    INDEX idx_role_projects (role_id),
    FOREIGN KEY (role_id) REFERENCES roles(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (added_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSION PROJECT CATALOG TABLE (METADATA ONLY) ===================
-- METADATA ONLY - Shows which permissions are relevant to projects (NOT used for authorization)
CREATE TABLE IF NOT EXISTS permission_project_catalog (
    id VARCHAR(64) NOT NULL,
    permission_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    catalog_purpose VARCHAR(255),
    notes TEXT,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    added_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_permission_project (permission_id, project_id),
    INDEX idx_project_permissions (project_id),
    INDEX idx_permission_projects (permission_id),
    FOREIGN KEY (permission_id) REFERENCES global_permissions(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (added_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== REV2: PERMISSION ASSIGNMENT SYSTEM TABLES ===================
-- Direct assignment of permission groups to users and user groups
-- ==================================================================================

-- =================== USER GROUP PERMISSION GROUPS TABLE ===================
-- Links user groups to permission groups (many-to-many) - PRIMARY assignment model
-- This allows entire user groups to receive permission groups
CREATE TABLE IF NOT EXISTS user_group_permission_groups (
    id VARCHAR(64) NOT NULL,
    user_group_id VARCHAR(64) NOT NULL,
    permission_group_id VARCHAR(64) NOT NULL,
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    assigned_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_usergroup_permgroup (user_group_id, permission_group_id),
    INDEX idx_user_group (user_group_id),
    INDEX idx_perm_group (permission_group_id),
    FOREIGN KEY (user_group_id) REFERENCES user_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (permission_group_id) REFERENCES global_permission_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER PERMISSION GROUPS TABLE ===================
-- Links users directly to permission groups (many-to-many) - SECONDARY assignment model
-- This allows individual users to receive specific permission groups
CREATE TABLE IF NOT EXISTS user_permission_groups (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    permission_group_id VARCHAR(64) NOT NULL,
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    assigned_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN DEFAULT TRUE,
    notes TEXT,  -- Why this user needs direct assignment
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_permgroup (user_id, permission_group_id),
    INDEX idx_user (user_id),
    INDEX idx_perm_group (permission_group_id),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (permission_group_id) REFERENCES global_permission_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (assigned_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSION GROUP PROJECT CATALOG TABLE ===================
-- METADATA ONLY - Organizational metadata for UI suggestions
-- NEVER used for permission validation or authorization logic
CREATE TABLE IF NOT EXISTS permission_group_project_catalog (
    id VARCHAR(64) NOT NULL,
    permission_group_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    catalog_purpose VARCHAR(255),  -- Why this group is relevant to this project
    notes TEXT,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    added_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_permgroup_project (permission_group_id, project_id),
    INDEX idx_project_permgroups (project_id),
    INDEX idx_permgroup_projects (permission_group_id),
    FOREIGN KEY (permission_group_id) REFERENCES global_permission_groups(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY (added_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (removed_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== TABLE CREATION COMPLETE ===================
SELECT 'All tables created successfully!' as status, 
       '39 tables created for complete authentication system' as details;
-- NOTE: Error logging tables are in 07_error_logs.sql

