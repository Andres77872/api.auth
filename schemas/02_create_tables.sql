-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Table Creation Script (without foreign keys)
-- MySQL Database

USE magic_auth;

-- =================== USERS TABLE ===================
-- Supports 3-tier user types: root, admin, consumer
CREATE TABLE IF NOT EXISTS users (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_hash VARCHAR(255) NOT NULL,
    username VARCHAR(100) NOT NULL,
    email VARCHAR(255),
    password_hash VARCHAR(255) NOT NULL,
    user_type ENUM('root', 'admin', 'consumer') NOT NULL DEFAULT 'consumer',
    assigned_project_id INT UNSIGNED, -- For single project assignment (legacy)
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
    PRIMARY KEY (id),
    UNIQUE KEY uk_project_hash (project_hash),
    INDEX idx_project_name (project_name),
    INDEX idx_active_projects (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_GROUPS TABLE ===================
-- Global user groups for organizing users
CREATE TABLE IF NOT EXISTS user_groups (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    group_hash VARCHAR(255) NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_description TEXT,
    project_id INT UNSIGNED, -- For legacy project-specific groups
    permissions JSON, -- For legacy permission storage
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_group_hash (group_hash),
    INDEX idx_group_name (group_name),
    INDEX idx_project_groups (project_id, is_active),
    INDEX idx_active_groups (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PROJECT_GROUPS TABLE ===================
-- Permission groups at the project level
CREATE TABLE IF NOT EXISTS project_groups (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    group_hash VARCHAR(255) NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_description TEXT,
    permissions JSON NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_project_group_hash (group_hash),
    INDEX idx_project_group_name (group_name),
    INDEX idx_active_project_groups (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_PROJECTS TABLE ===================
-- Links consumer users to projects they can access
CREATE TABLE IF NOT EXISTS user_projects (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    user_project_hash VARCHAR(255) NOT NULL,
    granted_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    granted_by INT UNSIGNED,
    revoked_at DATETIME,
    revoked_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_project_hash (user_project_hash),
    UNIQUE KEY uk_user_project (user_id, project_id),
    INDEX idx_user_projects (user_id, is_active),
    INDEX idx_project_users (project_id, is_active),
    INDEX idx_user_projects_user_project (user_id, project_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_GROUP_MEMBERS TABLE ===================
-- Links users to user groups
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
-- Links user groups to projects they can access
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

-- =================== PROJECT_GROUP_MEMBERS TABLE ===================
-- Links projects to project groups
CREATE TABLE IF NOT EXISTS project_group_members (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    project_id INT UNSIGNED NOT NULL,
    project_group_id INT UNSIGNED NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT UNSIGNED,
    removed_at DATETIME,
    removed_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_project_group_member (project_id, project_group_id),
    INDEX idx_project_groups (project_id, is_active),
    INDEX idx_group_projects (project_group_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSIONS TABLE ===================
-- Available permissions in the system (project-specific)
CREATE TABLE IF NOT EXISTS permissions (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    permission_hash VARCHAR(255) NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    permission_name VARCHAR(100) NOT NULL,
    permission_display_name VARCHAR(255) NOT NULL,
    permission_description TEXT,
    permission_category VARCHAR(50) NOT NULL DEFAULT 'general',
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
    INDEX idx_user_permission_check (project_id, permission_name, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSION_GROUPS TABLE ===================
-- Role definitions (groups of permissions) - project-specific
CREATE TABLE IF NOT EXISTS permission_groups (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    group_hash VARCHAR(255) NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    group_name VARCHAR(100) NOT NULL,
    group_display_name VARCHAR(255) NOT NULL,
    group_description TEXT,
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
    INDEX idx_permission_groups_lookup (project_id, group_name, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSION_GROUP_PERMISSIONS TABLE ===================
-- Links permissions to permission groups
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

-- =================== USER_PROJECT_PERMISSION_GROUPS TABLE ===================
-- Assigns users to permission groups within projects
CREATE TABLE IF NOT EXISTS user_project_permission_groups (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    permission_group_id INT UNSIGNED NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT UNSIGNED,
    removed_at DATETIME,
    removed_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_project_role (user_id, project_id, permission_group_id),
    INDEX idx_user_roles (user_id, project_id, is_active),
    INDEX idx_project_user_roles (project_id, user_id, is_active),
    INDEX idx_role_users (permission_group_id, is_active),
    INDEX idx_user_proj_perm_all (user_id, project_id, permission_group_id, is_active),
    INDEX idx_user_proj_perm_groups_lookup (user_id, project_id, permission_group_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_SESSIONS TABLE ===================
-- Session management
CREATE TABLE IF NOT EXISTS user_sessions (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_project_id INT UNSIGNED NOT NULL,
    session_token VARCHAR(255) NOT NULL,
    expires_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_session_token (session_token),
    INDEX idx_user_sessions (user_project_id, is_active),
    INDEX idx_active_sessions (is_active, expires_at),
    INDEX idx_user_sessions_token_expires (session_token, is_active, expires_at),
    INDEX idx_sessions_token_active (session_token, is_active, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_PROJECT_GROUPS TABLE ===================
-- Legacy table linking user_projects to groups
CREATE TABLE IF NOT EXISTS user_project_groups (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_project_id INT UNSIGNED NOT NULL,
    group_id INT UNSIGNED NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT UNSIGNED,
    removed_at DATETIME,
    removed_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_user_project_group (user_project_id, group_id),
    INDEX idx_user_project_groups (user_project_id, is_active),
    INDEX idx_group_user_projects (group_id, is_active),
    INDEX idx_user_project_groups_lookup (user_project_id, group_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ADMIN_PROJECT_ASSIGNMENTS TABLE ===================
-- Multi-project assignments for admin users
CREATE TABLE IF NOT EXISTS admin_project_assignments (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    user_id INT UNSIGNED NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    assigned_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    assigned_by INT UNSIGNED,
    removed_at DATETIME,
    removed_by INT UNSIGNED,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    PRIMARY KEY (id),
    UNIQUE KEY uk_admin_project (user_id, project_id),
    INDEX idx_admin_projects (user_id, is_active),
    INDEX idx_project_admins (project_id, is_active),
    INDEX idx_admin_assignments_user_project_active (user_id, project_id, is_active),
    INDEX idx_admin_projects_user_active (user_id, is_active),
    INDEX idx_admin_projects_project_user (project_id, user_id, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSION_AUDIT_LOG TABLE ===================
-- Audit trail for permission-related actions
CREATE TABLE IF NOT EXISTS permission_audit_log (
    id INT UNSIGNED NOT NULL AUTO_INCREMENT,
    action_type VARCHAR(50) NOT NULL,
    project_id INT UNSIGNED,
    target_user_id INT UNSIGNED,
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
    target_user_id INT UNSIGNED,
    ip_address VARCHAR(45),
    user_agent TEXT,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_activity_user_id (user_id),
    INDEX idx_activity_type (activity_type),
    INDEX idx_activity_project_id (project_id),
    INDEX idx_activity_created_at (created_at DESC),
    INDEX idx_activity_target_user_id (target_user_id),
    INDEX idx_activity_compound (user_id, project_id, activity_type),
    INDEX idx_activity_recent (created_at DESC, activity_type),
    INDEX idx_activity_log_user_type_time (user_id, activity_type, created_at),
    INDEX idx_activity_log_project_time (project_id, created_at),
    INDEX idx_activity_log_target_user_time (target_user_id, created_at),
    INDEX idx_activity_log_type_time (activity_type, created_at)
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