-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Table Creation Script (Restructured for Group-Based Access)
-- MySQL Database

USE magic_auth;

-- =================== USERS TABLE ===================
-- Supports 3-tier user types: root, admin, consumer
-- NO direct project assignments - ALL access through groups
CREATE TABLE IF NOT EXISTS users (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_hash VARCHAR(255) NOT NULL,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    password_hash VARCHAR(255) NOT NULL,
    user_type ENUM('root', 'admin', 'consumer') NOT NULL DEFAULT 'consumer',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_hash (user_hash),
    UNIQUE KEY uk_username (username),
    INDEX idx_email (email),
    INDEX idx_user_type (user_type),
    INDEX idx_active_users (is_active, user_type),
    INDEX idx_users_type_active (user_type, is_active),
    INDEX idx_users_username_password (username, password_hash, is_active),
    INDEX idx_users_email_password (email, password_hash, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PROJECTS TABLE ===================
-- Applications/systems in the multi-project architecture
CREATE TABLE IF NOT EXISTS projects (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    project_hash VARCHAR(255) NOT NULL,
    project_name VARCHAR(100) NOT NULL,
    project_description TEXT,
    project_created DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    archived BOOLEAN DEFAULT FALSE,
    owner_id INT UNSIGNED,
    archived_at TIMESTAMP NULL,
    archived_by INT UNSIGNED NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_project_hash (project_hash),
    INDEX idx_project_name (project_name),
    INDEX idx_active_projects (is_active),
    INDEX idx_projects_archived (archived),
    INDEX idx_projects_owner (owner_id),
    INDEX idx_projects_created_at (project_created)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_GROUPS TABLE ===================
-- Global user groups that can span multiple projects
-- Can have hierarchical structure (parent-child relationships)
CREATE TABLE IF NOT EXISTS user_groups (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    group_hash VARCHAR(255) NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_description TEXT,
    parent_group_id INT UNSIGNED NULL, -- For hierarchical groups
    group_level INT NOT NULL DEFAULT 0, -- Hierarchy level (0 = root level)
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_group_hash (group_hash),
    UNIQUE KEY uk_group_name (group_name), -- Global unique group names
    INDEX idx_group_name (group_name),
    INDEX idx_parent_group (parent_group_id),
    INDEX idx_group_level (group_level),
    INDEX idx_active_groups (is_active),
    INDEX idx_hierarchical_lookup (parent_group_id, group_level, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_GROUP_MEMBERS TABLE ===================
-- Links users to user groups (many-to-many)
CREATE TABLE IF NOT EXISTS user_group_members (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    user_group_id INT UNSIGNED NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT UNSIGNED,
    removed_at DATETIME,
    removed_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_group_member (user_id, user_group_id),
    INDEX idx_user_groups (user_id, is_active),
    INDEX idx_group_users (user_group_id, is_active),
    INDEX idx_user_group_members_user (user_id, is_active),
    INDEX idx_user_group_members_group (user_group_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_GROUP_PROJECTS TABLE ===================
-- Links user groups to projects they have access to (many-to-many)
-- This is how users get access to projects - through their groups
CREATE TABLE IF NOT EXISTS user_group_projects (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_group_id INT UNSIGNED NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by INT UNSIGNED,
    revoked_at DATETIME,
    revoked_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_group_project (user_group_id, project_id),
    INDEX idx_group_projects (user_group_id, is_active),
    INDEX idx_project_groups (project_id, is_active),
    INDEX idx_user_group_projects_access (user_group_id, project_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSIONS TABLE ===================
-- Project-specific permission catalog
-- Each project has its own set of permissions
CREATE TABLE IF NOT EXISTS permissions (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    permission_hash VARCHAR(255) NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    permission_name VARCHAR(100) NOT NULL,
    permission_display_name VARCHAR(255) NOT NULL,
    permission_description TEXT,
    permission_category VARCHAR(50) NOT NULL DEFAULT 'general',
    parent_permission_id INT UNSIGNED NULL, -- For hierarchical permissions
    permission_level INT NOT NULL DEFAULT 0, -- Hierarchy level
    is_system_permission BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_permission_hash (permission_hash),
    UNIQUE KEY uk_project_permission (project_id, permission_name),
    INDEX idx_project_permissions (project_id, is_active),
    INDEX idx_permission_category (permission_category),
    INDEX idx_system_permissions (is_system_permission),
    INDEX idx_parent_permission (parent_permission_id),
    INDEX idx_permission_level (permission_level),
    INDEX idx_user_permission_check (project_id, permission_name, is_active),
    INDEX idx_hierarchical_perms (project_id, parent_permission_id, permission_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSION_GROUPS TABLE ===================
-- Project-specific permission groups (roles)
-- CANNOT span multiple projects - each is tied to ONE project
-- Can have hierarchical structure within the project
CREATE TABLE IF NOT EXISTS permission_groups (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    group_hash VARCHAR(255) NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_display_name VARCHAR(255) NOT NULL,
    group_description TEXT,
    parent_permission_group_id INT UNSIGNED NULL, -- For hierarchical permission groups
    group_level INT NOT NULL DEFAULT 0, -- Hierarchy level
    group_priority INT NOT NULL DEFAULT 0,
    is_system_role BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    created_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_permission_group_hash (group_hash),
    UNIQUE KEY uk_project_role (project_id, group_name),
    INDEX idx_project_roles (project_id, is_active),
    INDEX idx_role_priority (group_priority DESC),
    INDEX idx_system_roles (is_system_role),
    INDEX idx_parent_permission_group (parent_permission_group_id),
    INDEX idx_permission_group_level (group_level),
    INDEX idx_permission_groups_lookup (project_id, group_name, is_active),
    INDEX idx_hierarchical_perm_groups (project_id, parent_permission_group_id, group_level)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSION_GROUP_PERMISSIONS TABLE ===================
-- Links permissions to permission groups within the same project
CREATE TABLE IF NOT EXISTS permission_group_permissions (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    permission_group_id INT UNSIGNED NOT NULL,
    permission_id INT UNSIGNED NOT NULL,
    granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by INT UNSIGNED,
    revoked_at DATETIME,
    revoked_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_group_permission (permission_group_id, permission_id),
    INDEX idx_group_permissions (permission_group_id, is_active),
    INDEX idx_permission_groups (permission_id, is_active),
    INDEX idx_perm_group_permissions_active (permission_group_id, permission_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_GROUP_PERMISSION_GROUPS TABLE ===================
-- Links user groups to permission groups within projects
-- This is how users get permissions - through their user groups being assigned permission groups
CREATE TABLE IF NOT EXISTS user_group_permission_groups (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_group_id INT UNSIGNED NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    permission_group_id INT UNSIGNED NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT UNSIGNED,
    removed_at DATETIME,
    removed_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_group_project_perm_group (user_group_id, project_id, permission_group_id),
    INDEX idx_user_group_perms (user_group_id, project_id, is_active),
    INDEX idx_project_user_group_perms (project_id, user_group_id, is_active),
    INDEX idx_perm_group_assignments (permission_group_id, is_active),
    INDEX idx_full_permission_lookup (user_group_id, project_id, permission_group_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_SESSIONS TABLE ===================
-- Session management - simplified to work with user groups
CREATE TABLE IF NOT EXISTS user_sessions (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    session_token VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_session_token (session_token),
    INDEX idx_user_sessions (user_id, project_id, is_active),
    INDEX idx_active_sessions (is_active, expires_at),
    INDEX idx_user_sessions_token_expires (session_token, is_active, expires_at),
    INDEX idx_sessions_token_active (session_token, is_active, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSION_AUDIT_LOG TABLE ===================
-- Audit trail for permission-related actions
CREATE TABLE IF NOT EXISTS permission_audit_log (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    action_type VARCHAR(50) NOT NULL,
    project_id INT UNSIGNED,
    target_user_id INT UNSIGNED,
    user_group_id INT UNSIGNED,
    permission_id INT UNSIGNED,
    permission_group_id INT UNSIGNED,
    performed_by INT UNSIGNED,
    old_values JSON,
    new_values JSON,
    action_timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent TEXT,
    table_name VARCHAR(100),
    record_id INT UNSIGNED,
    PRIMARY KEY (id),
    INDEX idx_audit_timestamp (action_timestamp DESC),
    INDEX idx_audit_project (project_id, action_timestamp DESC),
    INDEX idx_audit_user (target_user_id, action_timestamp DESC),
    INDEX idx_audit_performer (performed_by, action_timestamp DESC),
    INDEX idx_audit_action (action_type),
    INDEX idx_audit_user_group (user_group_id, action_timestamp DESC),
    INDEX idx_audit_log_project_time (project_id, action_timestamp),
    INDEX idx_audit_log_user_time (target_user_id, action_timestamp),
    INDEX idx_audit_log_action_type (action_type, action_timestamp)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ACTIVITY_LOGS TABLE ===================
-- Activity logging for user and system activities
CREATE TABLE IF NOT EXISTS activity_logs (
    id BIGINT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED,
    activity_type VARCHAR(50) NOT NULL,
    details TEXT,
    project_id INT UNSIGNED,
    user_group_id INT UNSIGNED,
    target_user_id INT UNSIGNED,
    ip_address VARCHAR(45),
    user_agent TEXT,
    metadata JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_activity_user_id (user_id),
    INDEX idx_activity_type (activity_type),
    INDEX idx_activity_project_id (project_id),
    INDEX idx_activity_created_at (created_at DESC),
    INDEX idx_activity_target_user_id (target_user_id),
    INDEX idx_activity_user_group_id (user_group_id),
    INDEX idx_activity_ip_address (ip_address),
    INDEX idx_activity_compound (user_id, project_id, activity_type),
    INDEX idx_activity_recent (created_at DESC, activity_type),
    INDEX idx_activity_log_user_type_time (user_id, activity_type, created_at),
    INDEX idx_activity_log_project_time (project_id, created_at),
    INDEX idx_activity_log_target_user_time (target_user_id, created_at),
    INDEX idx_activity_log_type_time (activity_type, created_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ADDITIONAL ENHANCEMENT TABLES ===================

-- =================== USER_PASSWORD_RESETS TABLE ===================
CREATE TABLE IF NOT EXISTS user_password_resets (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    reset_token VARCHAR(255) NOT NULL,
    temporary_password_hash VARCHAR(255) NOT NULL,
    expires_at TIMESTAMP NOT NULL,
    used_at TIMESTAMP NULL,
    created_by INT UNSIGNED NOT NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_user_password_resets_user_id (user_id),
    INDEX idx_user_password_resets_token (reset_token),
    INDEX idx_user_password_resets_expires (expires_at),
    INDEX idx_user_password_resets_user_expires (user_id, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ROLE_ASSIGNMENT_HISTORY TABLE ===================
CREATE TABLE IF NOT EXISTS role_assignment_history (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    user_group_id INT UNSIGNED NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    permission_group_id INT UNSIGNED NOT NULL,
    action ENUM('assigned', 'removed', 'modified') NOT NULL,
    performed_by INT UNSIGNED NOT NULL,
    performed_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    details TEXT NULL,
    is_active BOOLEAN DEFAULT TRUE,
    PRIMARY KEY (id),
    INDEX idx_role_history_user_project (user_id, project_id),
    INDEX idx_role_history_user_group (user_group_id),
    INDEX idx_role_history_performed_at (performed_at),
    INDEX idx_role_history_action (action),
    INDEX idx_role_history_user_performed (user_id, performed_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== SYSTEM_METRICS TABLE ===================
CREATE TABLE IF NOT EXISTS system_metrics (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    metric_name VARCHAR(100) NOT NULL,
    metric_value DECIMAL(15,4) NOT NULL,
    metric_unit VARCHAR(20) NULL,
    collected_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_system_metrics_name_time (metric_name, collected_at),
    INDEX idx_system_metrics_collected_at (collected_at),
    INDEX idx_system_metrics_name_collected (metric_name, collected_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== BULK_OPERATIONS_LOG TABLE ===================
CREATE TABLE IF NOT EXISTS bulk_operations_log (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    operation_type ENUM('bulk_update_users', 'bulk_delete_users', 'bulk_assign_roles', 'bulk_assign_groups') NOT NULL,
    performed_by INT UNSIGNED NOT NULL,
    target_count INT NOT NULL,
    success_count INT NOT NULL,
    error_count INT NOT NULL,
    operation_details JSON NULL,
    started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    completed_at TIMESTAMP NULL,
    status ENUM('running', 'completed', 'failed') DEFAULT 'running',
    PRIMARY KEY (id),
    INDEX idx_bulk_ops_performer (performed_by),
    INDEX idx_bulk_ops_type_time (operation_type, started_at),
    INDEX idx_bulk_ops_status (status),
    INDEX idx_bulk_ops_performer_started (performed_by, started_at DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERFORMANCE OPTIMIZATION TABLES ===================

-- Table for caching expensive permission calculations
CREATE TABLE IF NOT EXISTS permission_cache (
    user_id INT UNSIGNED NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    permission_name VARCHAR(100) NOT NULL,
    has_permission BOOLEAN NOT NULL,
    cached_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, project_id, permission_name),
    INDEX idx_expires (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Table for query performance tracking
CREATE TABLE IF NOT EXISTS query_performance_log (
    id BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY,
    query_hash VARCHAR(64),
    query_type VARCHAR(50),
    execution_time_ms INT,
    rows_examined INT,
    rows_returned INT,
    logged_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_query_hash (query_hash),
    INDEX idx_logged_at (logged_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci; 