-- ===================================================================================
-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Table Creation Script - GROUPS OF GROUPS Architecture
-- ===================================================================================
-- This script creates all tables needed for the authentication system
-- PHILOSOPHY: Users → User Groups → Project Groups → Projects
-- NO direct user-to-project or user-group-to-project assignments
-- MySQL Database
-- ===================================================================================

USE magic_auth;

-- ===================================================================================
-- CORE ENTITY TABLES
-- ===================================================================================

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

-- ===================================================================================
-- USER GROUPS - Groups of Users (Hierarchical)
-- ===================================================================================

-- =================== USER_GROUPS TABLE ===================
-- Global user groups that can span multiple project groups
-- Can have hierarchical structure (parent-child relationships)
-- ROOT DETECTION: parent_group_id IS NULL means root group
CREATE TABLE IF NOT EXISTS user_groups (
    id VARCHAR(64) NOT NULL,
    group_hash VARCHAR(255) NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_description TEXT,
    parent_group_id VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_group_hash (group_hash),
    UNIQUE KEY uk_group_name (group_name),
    INDEX idx_parent_group (parent_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_GROUP_MEMBERS TABLE ===================
-- Links users to user groups (many-to-many)
-- User → User Group relationship
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

-- ===================================================================================
-- PROJECT GROUPS - Groups of Projects
-- ===================================================================================

-- =================== PROJECT_GROUPS TABLE ===================
-- Project groups organize projects together
-- User groups connect to project groups (NOT directly to projects)
-- Supports hierarchical structure (parent-child relationships)
-- ROOT DETECTION: parent_group_id IS NULL means root group
CREATE TABLE IF NOT EXISTS project_groups (
    id VARCHAR(64) NOT NULL,
    group_hash VARCHAR(255) NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_description TEXT,
    parent_group_id VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_project_group_hash (group_hash),
    UNIQUE KEY uk_project_group_name (group_name),
    INDEX idx_parent_project_group (parent_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PROJECT_GROUP_MEMBERS TABLE ===================
-- Links projects to project groups (many-to-many)
-- Project Group → Project relationship
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

-- ===================================================================================
-- GROUPS OF GROUPS - User Groups → Project Groups
-- This is the KEY table for "groups of groups" philosophy
-- ===================================================================================

-- =================== USER_GROUP_PROJECT_GROUPS TABLE ===================
-- Links user groups to project groups (many-to-many)
-- THIS IS HOW USERS GET ACCESS TO PROJECTS:
-- User → User Group → Project Group → Project
CREATE TABLE IF NOT EXISTS user_group_project_groups (
    id VARCHAR(64) NOT NULL,
    user_group_id VARCHAR(64) NOT NULL,
    project_group_id VARCHAR(64) NOT NULL,
    granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by VARCHAR(64),
    revoked_at DATETIME,
    revoked_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_usergroup_projectgroup (user_group_id, project_group_id),
    INDEX idx_user_group (user_group_id),
    INDEX idx_project_group (project_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===================================================================================
-- SESSION MANAGEMENT
-- ===================================================================================

-- =================== USER_SESSIONS TABLE ===================
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

-- ===================================================================================
-- AUDIT & LOGGING TABLES
-- ===================================================================================

-- =================== API AUDIT LOG TABLE ===================
CREATE TABLE IF NOT EXISTS api_audit_log (
    id VARCHAR(64) NOT NULL,
    request_id VARCHAR(64),
    http_method VARCHAR(10) NOT NULL,
    endpoint_path VARCHAR(512) NOT NULL,
    route_pattern VARCHAR(512),
    user_id VARCHAR(64),
    user_type ENUM('root', 'admin', 'consumer'),
    session_id VARCHAR(256),
    request_headers JSON,
    request_body JSON,
    request_query JSON,
    request_size_bytes INT,
    response_status INT NOT NULL,
    response_body JSON,
    response_headers JSON,
    response_size_bytes INT,
    request_timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    response_timestamp DATETIME,
    duration_ms INT,
    client_ip VARCHAR(45),
    user_agent TEXT,
    referer VARCHAR(512),
    is_success BOOLEAN,
    error_code VARCHAR(50),
    error_message TEXT,
    project_id VARCHAR(64),
    target_resource_type VARCHAR(50),
    target_resource_id VARCHAR(64),
    metadata JSON,
    tags JSON,
    requires_audit BOOLEAN DEFAULT TRUE,
    security_event BOOLEAN DEFAULT FALSE,
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
-- Flexible history table: supports role, permission group, and scoped assignments
-- Nullable FKs allow logging different assignment types:
--   - Role to user: only user_id and role_id filled
--   - Permission group to user group: user_group_id and permission_group_id filled
--   - Scoped permission: user_group_id, project_group_id, and permission_group_id filled
CREATE TABLE IF NOT EXISTS role_assignment_history (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NULL,
    user_group_id VARCHAR(64) NULL,
    project_group_id VARCHAR(64) NULL,
    permission_group_id VARCHAR(64) NULL,
    role_id VARCHAR(64) NULL,
    assignment_type ENUM('role_to_user', 'permission_group_to_user', 'permission_group_to_user_group', 'scoped_permission') NOT NULL,
    action ENUM('assigned', 'removed', 'modified') NOT NULL,
    performed_by VARCHAR(64) NOT NULL,
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details TEXT NULL,
    old_values JSON NULL,
    new_values JSON NULL,
    PRIMARY KEY (id),
    INDEX idx_assignment_type (assignment_type),
    INDEX idx_performed_at (performed_at DESC)
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

-- ===================================================================================
-- PERFORMANCE OPTIMIZATION TABLES
-- ===================================================================================

-- =================== PERMISSION_CACHE TABLE ===================
CREATE TABLE IF NOT EXISTS permission_cache (
    user_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    permission_name VARCHAR(100) NOT NULL,
    has_permission BOOLEAN NOT NULL,
    cached_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, project_id, permission_name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== QUERY_PERFORMANCE_LOG TABLE ===================
CREATE TABLE IF NOT EXISTS query_performance_log (
    id VARCHAR(64) NOT NULL PRIMARY KEY,
    query_hash VARCHAR(64),
    query_type VARCHAR(50),
    execution_time_ms INT,
    rows_examined INT,
    rows_returned INT,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===================================================================================
-- GLOBAL ROLE SYSTEM TABLES
-- ===================================================================================

-- =================== ROLES TABLE ===================
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
    INDEX idx_role_name (role_name, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== GLOBAL_PERMISSION_GROUPS TABLE ===================
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
    INDEX idx_group_name (group_name, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== GLOBAL_PERMISSIONS TABLE ===================
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
    INDEX idx_permission_name (permission_name, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ROLE_PERMISSION_GROUPS TABLE ===================
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
    INDEX idx_perm_group (permission_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== GLOBAL_PERMISSION_GROUP_PERMISSIONS TABLE ===================
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
    INDEX idx_permission (permission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===================================================================================
-- PERMISSION ASSIGNMENT TABLES
-- ===================================================================================

-- =================== USER_GROUP_PERMISSION_GROUPS TABLE ===================
-- Links user groups to permission groups (global permissions)
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
    INDEX idx_perm_group (permission_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_PERMISSION_GROUPS TABLE ===================
-- Direct user to permission group (for exceptions only)
CREATE TABLE IF NOT EXISTS user_permission_groups (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    permission_group_id VARCHAR(64) NOT NULL,
    assigned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    assigned_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN DEFAULT TRUE,
    notes TEXT,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_permgroup (user_id, permission_group_id),
    INDEX idx_user (user_id),
    INDEX idx_perm_group (permission_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_GROUP_PROJECT_GROUP_PERMISSIONS TABLE ===================
-- Scoped permissions: User Group gets Permission Group ONLY for specific Project Group
-- Supports grant/deny with priority for conflict resolution
CREATE TABLE IF NOT EXISTS user_group_project_group_permissions (
    id VARCHAR(64) NOT NULL,
    user_group_id VARCHAR(64) NOT NULL,
    project_group_id VARCHAR(64) NOT NULL,
    permission_group_id VARCHAR(64) NOT NULL,
    permission_type ENUM('grant', 'deny') NOT NULL DEFAULT 'grant',
    priority INT NOT NULL DEFAULT 0,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ug_pg_permg (user_group_id, project_group_id, permission_group_id),
    INDEX idx_user_group (user_group_id),
    INDEX idx_project_group (project_group_id),
    INDEX idx_permission_group (permission_group_id),
    INDEX idx_permission_type_priority (permission_type, priority DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_GROUP_PROJECT_GROUP_ROLES TABLE ===================
-- Project-scoped roles: User Group gets a Role ONLY for specific Project Group
-- This allows users to have different roles in different project contexts
CREATE TABLE IF NOT EXISTS user_group_project_group_roles (
    id VARCHAR(64) NOT NULL,
    user_group_id VARCHAR(64) NOT NULL,
    project_group_id VARCHAR(64) NOT NULL,
    role_id VARCHAR(64) NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_ug_pg_role (user_group_id, project_group_id, role_id),
    INDEX idx_ugpgr_user_group (user_group_id),
    INDEX idx_ugpgr_project_group (project_group_id),
    INDEX idx_ugpgr_role (role_id),
    INDEX idx_ugpgr_lookup (user_group_id, project_group_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===================================================================================
-- CATALOG TABLES (METADATA ONLY - NOT FOR AUTHORIZATION)
-- ===================================================================================

-- =================== ROLE_PROJECT_CATALOG TABLE ===================
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
    INDEX idx_role_projects (role_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSION_PROJECT_CATALOG TABLE ===================
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
    INDEX idx_permission_projects (permission_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSION_GROUP_PROJECT_CATALOG TABLE ===================
CREATE TABLE IF NOT EXISTS permission_group_project_catalog (
    id VARCHAR(64) NOT NULL,
    permission_group_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    catalog_purpose VARCHAR(255),
    notes TEXT,
    added_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    added_by VARCHAR(64),
    removed_at DATETIME,
    removed_by VARCHAR(64),
    is_active BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_permgroup_project (permission_group_id, project_id),
    INDEX idx_project_permgroups (project_id),
    INDEX idx_permgroup_projects (permission_group_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===================================================================================
-- TABLE CREATION COMPLETE
-- ===================================================================================
SELECT 'All tables created successfully!' as status, 
       'Groups of Groups architecture implemented' as details;
