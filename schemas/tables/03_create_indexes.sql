-- ===================================================================================
-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Index Creation Script - GROUPS OF GROUPS Architecture
-- ===================================================================================
-- This script creates all performance indexes for the authentication system
-- MySQL Database
-- ===================================================================================

USE magic_auth;

-- ===================================================================================
-- USERS TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_email ON users (email);
CREATE INDEX idx_user_type ON users (user_type);
CREATE INDEX idx_active_users ON users (is_active, user_type);
CREATE INDEX idx_users_type_active ON users (user_type, is_active);
CREATE INDEX idx_users_username_password ON users (username, password_hash, is_active);
CREATE INDEX idx_users_email_password ON users (email, password_hash, is_active);
CREATE INDEX idx_users_role_active ON users(role_id, is_active);
CREATE INDEX idx_permission_check ON users(id, role_id, is_active);

-- ===================================================================================
-- PROJECTS TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_project_name ON projects (project_name);
CREATE INDEX idx_active_projects ON projects (is_active);
CREATE INDEX idx_projects_archived ON projects (archived);
CREATE INDEX idx_projects_owner ON projects (owner_id);
CREATE INDEX idx_projects_created_at ON projects (project_created);

-- ===================================================================================
-- USER_GROUPS TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_group_name ON user_groups (group_name);
-- idx_parent_group already created in 02_create_tables.sql
CREATE INDEX idx_active_groups ON user_groups (is_active);
CREATE INDEX idx_user_groups_parent_active ON user_groups (parent_group_id, is_active);
-- Note: MySQL doesn't support partial indexes (WHERE clause), removing idx_user_groups_root

-- ===================================================================================
-- USER_GROUP_MEMBERS TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_user_groups ON user_group_members (user_id, is_active);
CREATE INDEX idx_group_users ON user_group_members (user_group_id, is_active);
CREATE INDEX idx_user_group_members_user ON user_group_members (user_id, is_active);
CREATE INDEX idx_user_group_members_group ON user_group_members (user_group_id, is_active);
CREATE INDEX idx_user_group_members_active_lookup ON user_group_members (user_id, user_group_id, is_active);

-- ===================================================================================
-- PROJECT_GROUPS TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_project_group_name ON project_groups (group_name);
CREATE INDEX idx_active_project_groups ON project_groups (is_active);
CREATE INDEX idx_project_groups_lookup ON project_groups (group_name, is_active);
CREATE INDEX idx_project_groups_parent ON project_groups (parent_group_id);
CREATE INDEX idx_project_groups_parent_active ON project_groups (parent_group_id, is_active);

-- ===================================================================================
-- PROJECT_GROUP_MEMBERS TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_project_in_groups ON project_group_members (project_id, is_active);
CREATE INDEX idx_group_projects_list ON project_group_members (project_group_id, is_active);
CREATE INDEX idx_project_group_members_access ON project_group_members (project_id, project_group_id, is_active);

-- ===================================================================================
-- USER_GROUP_PROJECT_GROUPS TABLE INDEXES (GROUPS OF GROUPS)
-- ===================================================================================
CREATE INDEX idx_ugpg_usergroup_active ON user_group_project_groups(user_group_id, is_active);
CREATE INDEX idx_ugpg_projectgroup_active ON user_group_project_groups(project_group_id, is_active);
CREATE INDEX idx_ugpg_access_lookup ON user_group_project_groups(user_group_id, project_group_id, is_active);

-- ===================================================================================
-- USER_GROUP_PROJECT_GROUP_PERMISSIONS TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_ugpgp_usergroup_active ON user_group_project_group_permissions(user_group_id, is_active);
CREATE INDEX idx_ugpgp_projectgroup_active ON user_group_project_group_permissions(project_group_id, is_active);
CREATE INDEX idx_ugpgp_permgroup_active ON user_group_project_group_permissions(permission_group_id, is_active);
CREATE INDEX idx_ugpgp_scoped_lookup ON user_group_project_group_permissions(user_group_id, project_group_id, permission_group_id, is_active);
CREATE INDEX idx_ugpgp_type_priority ON user_group_project_group_permissions(permission_type, priority DESC, is_active);
CREATE INDEX idx_ugpgp_full_resolution ON user_group_project_group_permissions(user_group_id, project_group_id, permission_type, priority DESC, is_active);

-- ===================================================================================
-- USER_GROUP_PROJECT_GROUP_ROLES TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_ugpgr_usergroup_active ON user_group_project_group_roles(user_group_id, is_active);
CREATE INDEX idx_ugpgr_projectgroup_active ON user_group_project_group_roles(project_group_id, is_active);
CREATE INDEX idx_ugpgr_role_active ON user_group_project_group_roles(role_id, is_active);
CREATE INDEX idx_ugpgr_scoped_lookup ON user_group_project_group_roles(user_group_id, project_group_id, role_id, is_active);
CREATE INDEX idx_ugpgr_full_lookup ON user_group_project_group_roles(user_group_id, project_group_id, is_active);

-- ===================================================================================
-- USER_SESSIONS TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_user_sessions ON user_sessions (user_id, project_id, is_active);
CREATE INDEX idx_active_sessions ON user_sessions (is_active, expires_at);
CREATE INDEX idx_user_sessions_token_expires ON user_sessions (session_token, is_active, expires_at);
CREATE INDEX idx_sessions_token_active ON user_sessions (session_token, is_active, expires_at);

-- ===================================================================================
-- USER_PASSWORD_RESETS TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_user_password_resets_user_id ON user_password_resets (user_id);
CREATE INDEX idx_user_password_resets_token ON user_password_resets (reset_token);
CREATE INDEX idx_user_password_resets_expires ON user_password_resets (expires_at);
CREATE INDEX idx_user_password_resets_user_expires ON user_password_resets (user_id, expires_at);

-- ===================================================================================
-- ROLE_ASSIGNMENT_HISTORY TABLE INDEXES
-- Supports queries by different assignment types and entities
-- ===================================================================================
CREATE INDEX idx_role_history_user ON role_assignment_history (user_id);
CREATE INDEX idx_role_history_user_group ON role_assignment_history (user_group_id);
CREATE INDEX idx_role_history_project_group ON role_assignment_history (project_group_id);
CREATE INDEX idx_role_history_permission_group ON role_assignment_history (permission_group_id);
CREATE INDEX idx_role_history_role ON role_assignment_history (role_id);
CREATE INDEX idx_role_history_action ON role_assignment_history (action);
CREATE INDEX idx_role_history_type_performed ON role_assignment_history (assignment_type, performed_at DESC);
CREATE INDEX idx_role_history_user_type ON role_assignment_history (user_id, assignment_type, performed_at DESC);
CREATE INDEX idx_role_history_group_type ON role_assignment_history (user_group_id, assignment_type, performed_at DESC);

-- ===================================================================================
-- SYSTEM_METRICS TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_system_metrics_name_time ON system_metrics (metric_name, collected_at);
CREATE INDEX idx_system_metrics_collected_at ON system_metrics (collected_at);
CREATE INDEX idx_system_metrics_name_collected ON system_metrics (metric_name, collected_at DESC);

-- ===================================================================================
-- BULK_OPERATIONS_LOG TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_bulk_ops_performer ON bulk_operations_log (performed_by);
CREATE INDEX idx_bulk_ops_type_time ON bulk_operations_log (operation_type, started_at);
CREATE INDEX idx_bulk_ops_status ON bulk_operations_log (status);
CREATE INDEX idx_bulk_ops_performer_started ON bulk_operations_log (performed_by, started_at DESC);

-- ===================================================================================
-- PERMISSION_CACHE TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_expires ON permission_cache (expires_at);

-- ===================================================================================
-- QUERY_PERFORMANCE_LOG TABLE INDEXES
-- ===================================================================================
CREATE INDEX idx_query_hash ON query_performance_log (query_hash);
CREATE INDEX idx_logged_at ON query_performance_log (logged_at);

-- ===================================================================================
-- GLOBAL ROLE SYSTEM INDEXES
-- ===================================================================================
CREATE INDEX idx_rpg_role_active ON role_permission_groups(role_id, is_active);
CREATE INDEX idx_rpg_pg_active ON role_permission_groups(permission_group_id, is_active);
CREATE INDEX idx_pgp_group_active ON global_permission_group_permissions(permission_group_id, is_active);
CREATE INDEX idx_pgp_perm_active ON global_permission_group_permissions(permission_id, is_active);
CREATE INDEX idx_role_catalog_active ON role_project_catalog(role_id, project_id, is_active);
CREATE INDEX idx_permission_catalog_active ON permission_project_catalog(permission_id, project_id, is_active);

-- ===================================================================================
-- PERMISSION ASSIGNMENT SYSTEM INDEXES
-- ===================================================================================
CREATE INDEX idx_user_permgroups ON user_permission_groups(user_id, is_active);
CREATE INDEX idx_permgroup_users ON user_permission_groups(permission_group_id, is_active);
CREATE INDEX idx_usergroup_permgroups ON user_group_permission_groups(user_group_id, is_active);
CREATE INDEX idx_permgroup_usergroups ON user_group_permission_groups(permission_group_id, is_active);
CREATE INDEX idx_project_catalog ON permission_group_project_catalog(project_id, is_active);
CREATE INDEX idx_permgroup_catalog ON permission_group_project_catalog(permission_group_id, is_active);

-- ===================================================================================
-- INDEX CREATION COMPLETE
-- ===================================================================================
SELECT 'All indexes created successfully!' as status,
       'Groups of Groups architecture indexes applied' as details;
