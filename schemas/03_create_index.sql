-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Index Creation Script (Consolidated from all tables)
-- MySQL Database

USE magic_auth;

-- =================== USERS TABLE INDEXES ===================
CREATE INDEX idx_email ON users (email);
CREATE INDEX idx_user_type ON users (user_type);
CREATE INDEX idx_active_users ON users (is_active, user_type);
CREATE INDEX idx_users_type_active ON users (user_type, is_active);
CREATE INDEX idx_users_username_password ON users (username, password_hash, is_active);
CREATE INDEX idx_users_email_password ON users (email, password_hash, is_active);

-- =================== PROJECTS TABLE INDEXES ===================
CREATE INDEX idx_project_name ON projects (project_name);
CREATE INDEX idx_active_projects ON projects (is_active);
CREATE INDEX idx_projects_archived ON projects (archived);
CREATE INDEX idx_projects_owner ON projects (owner_id);
CREATE INDEX idx_projects_created_at ON projects (project_created);

-- =================== USER_GROUPS TABLE INDEXES ===================
CREATE INDEX idx_group_name ON user_groups (group_name);
CREATE INDEX idx_parent_group ON user_groups (parent_group_id);
CREATE INDEX idx_group_level ON user_groups (group_level);
CREATE INDEX idx_active_groups ON user_groups (is_active);
CREATE INDEX idx_hierarchical_lookup ON user_groups (parent_group_id, group_level, is_active);

-- =================== USER_GROUP_MEMBERS TABLE INDEXES ===================
CREATE INDEX idx_user_groups ON user_group_members (user_id, is_active);
CREATE INDEX idx_group_users ON user_group_members (user_group_id, is_active);
CREATE INDEX idx_user_group_members_user ON user_group_members (user_id, is_active);
CREATE INDEX idx_user_group_members_group ON user_group_members (user_group_id, is_active);

-- =================== USER_GROUP_PROJECTS TABLE INDEXES ===================
CREATE INDEX idx_group_projects ON user_group_projects (user_group_id, is_active);
CREATE INDEX idx_project_groups ON user_group_projects (project_id, is_active);
CREATE INDEX idx_user_group_projects_access ON user_group_projects (user_group_id, project_id, is_active);

-- =================== PROJECT_GROUPS TABLE INDEXES ===================
CREATE INDEX idx_project_group_name ON project_groups (group_name);
CREATE INDEX idx_active_project_groups ON project_groups (is_active);
CREATE INDEX idx_project_groups_lookup ON project_groups (group_name, is_active);

-- =================== PROJECT_GROUP_MEMBERS TABLE INDEXES ===================
CREATE INDEX idx_project_in_groups ON project_group_members (project_id, is_active);
CREATE INDEX idx_group_projects_list ON project_group_members (project_group_id, is_active);
CREATE INDEX idx_project_group_members_access ON project_group_members (project_id, project_group_id, is_active);

-- =================== PERMISSIONS TABLE INDEXES ===================
CREATE INDEX idx_project_permissions ON permissions (project_id, is_active);
CREATE INDEX idx_permission_category ON permissions (permission_category);
CREATE INDEX idx_system_permissions ON permissions (is_system_permission);
CREATE INDEX idx_parent_permission ON permissions (parent_permission_id);
CREATE INDEX idx_permission_level ON permissions (permission_level);
CREATE INDEX idx_user_permission_check ON permissions (project_id, permission_name, is_active);
CREATE INDEX idx_hierarchical_perms ON permissions (project_id, parent_permission_id, permission_level);

-- =================== PERMISSION_GROUPS TABLE INDEXES ===================
CREATE INDEX idx_project_roles ON permission_groups (project_id, is_active);
CREATE INDEX idx_role_priority ON permission_groups (group_priority DESC);
CREATE INDEX idx_system_roles ON permission_groups (is_system_role);
CREATE INDEX idx_parent_permission_group ON permission_groups (parent_permission_group_id);
CREATE INDEX idx_permission_group_level ON permission_groups (group_level);
CREATE INDEX idx_permission_groups_lookup ON permission_groups (project_id, group_name, is_active);
CREATE INDEX idx_hierarchical_perm_groups ON permission_groups (project_id, parent_permission_group_id, group_level);

-- =================== PERMISSION_GROUP_PERMISSIONS TABLE INDEXES ===================
CREATE INDEX idx_group_permissions ON permission_group_permissions (permission_group_id, is_active);
CREATE INDEX idx_permission_groups ON permission_group_permissions (permission_id, is_active);
CREATE INDEX idx_perm_group_permissions_active ON permission_group_permissions (permission_group_id, permission_id, is_active);

-- =================== USER_GROUP_PERMISSION_GROUPS TABLE INDEXES ===================
CREATE INDEX idx_user_group_perms ON user_group_permission_groups (user_group_id, project_id, is_active);
CREATE INDEX idx_project_user_group_perms ON user_group_permission_groups (project_id, user_group_id, is_active);
CREATE INDEX idx_perm_group_assignments ON user_group_permission_groups (permission_group_id, is_active);
CREATE INDEX idx_full_permission_lookup ON user_group_permission_groups (user_group_id, project_id, permission_group_id, is_active);

-- =================== USER_SESSIONS TABLE INDEXES ===================
CREATE INDEX idx_user_sessions ON user_sessions (user_id, project_id, is_active);
CREATE INDEX idx_active_sessions ON user_sessions (is_active, expires_at);
CREATE INDEX idx_user_sessions_token_expires ON user_sessions (session_token, is_active, expires_at);
CREATE INDEX idx_sessions_token_active ON user_sessions (session_token, is_active, expires_at);

-- =================== PERMISSION_AUDIT_LOG TABLE INDEXES ===================
CREATE INDEX idx_audit_timestamp ON permission_audit_log (action_timestamp DESC);
CREATE INDEX idx_audit_project ON permission_audit_log (project_id, action_timestamp DESC);
CREATE INDEX idx_audit_user ON permission_audit_log (target_user_id, action_timestamp DESC);
CREATE INDEX idx_audit_performer ON permission_audit_log (performed_by, action_timestamp DESC);
CREATE INDEX idx_audit_action ON permission_audit_log (action_type);
CREATE INDEX idx_audit_user_group ON permission_audit_log (user_group_id, action_timestamp DESC);
CREATE INDEX idx_audit_log_project_time ON permission_audit_log (project_id, action_timestamp);
CREATE INDEX idx_audit_log_user_time ON permission_audit_log (target_user_id, action_timestamp);
CREATE INDEX idx_audit_log_action_type ON permission_audit_log (action_type, action_timestamp);

-- =================== ACTIVITY_CATALOG TABLE INDEXES ===================
CREATE INDEX idx_activity_catalog_code ON activity_catalog (activity_code);
CREATE INDEX idx_activity_catalog_category ON activity_catalog (activity_category);
CREATE INDEX idx_activity_catalog_active ON activity_catalog (is_active);
CREATE INDEX idx_activity_catalog_severity ON activity_catalog (severity_level);

-- =================== ACTIVITY_LOGS TABLE INDEXES ===================
CREATE INDEX idx_activity_user_id ON activity_logs (user_id);
CREATE INDEX idx_activity_type ON activity_logs (activity_type);
CREATE INDEX idx_activity_project_id ON activity_logs (project_id);
CREATE INDEX idx_activity_created_at ON activity_logs (created_at DESC);
CREATE INDEX idx_activity_target_user_id ON activity_logs (target_user_id);
CREATE INDEX idx_activity_user_group_id ON activity_logs (user_group_id);
CREATE INDEX idx_activity_ip_address ON activity_logs (ip_address);
CREATE INDEX idx_activity_severity ON activity_logs (severity_level);
CREATE INDEX idx_activity_compound ON activity_logs (user_id, project_id, activity_type);
CREATE INDEX idx_activity_recent ON activity_logs (created_at DESC, activity_type);
CREATE INDEX idx_activity_log_user_type_time ON activity_logs (user_id, activity_type, created_at);
CREATE INDEX idx_activity_log_project_time ON activity_logs (project_id, created_at);
CREATE INDEX idx_activity_log_target_user_time ON activity_logs (target_user_id, created_at);
CREATE INDEX idx_activity_log_type_time ON activity_logs (activity_type, created_at);

-- =================== USER_PASSWORD_RESETS TABLE INDEXES ===================
CREATE INDEX idx_user_password_resets_user_id ON user_password_resets (user_id);
CREATE INDEX idx_user_password_resets_token ON user_password_resets (reset_token);
CREATE INDEX idx_user_password_resets_expires ON user_password_resets (expires_at);
CREATE INDEX idx_user_password_resets_user_expires ON user_password_resets (user_id, expires_at);

-- =================== ROLE_ASSIGNMENT_HISTORY TABLE INDEXES ===================
CREATE INDEX idx_role_history_user_project ON role_assignment_history (user_id, project_id);
CREATE INDEX idx_role_history_user_group ON role_assignment_history (user_group_id);
CREATE INDEX idx_role_history_performed_at ON role_assignment_history (performed_at);
CREATE INDEX idx_role_history_action ON role_assignment_history (action);
CREATE INDEX idx_role_history_user_performed ON role_assignment_history (user_id, performed_at DESC);

-- =================== SYSTEM_METRICS TABLE INDEXES ===================
CREATE INDEX idx_system_metrics_name_time ON system_metrics (metric_name, collected_at);
CREATE INDEX idx_system_metrics_collected_at ON system_metrics (collected_at);
CREATE INDEX idx_system_metrics_name_collected ON system_metrics (metric_name, collected_at DESC);

-- =================== BULK_OPERATIONS_LOG TABLE INDEXES ===================
CREATE INDEX idx_bulk_ops_performer ON bulk_operations_log (performed_by);
CREATE INDEX idx_bulk_ops_type_time ON bulk_operations_log (operation_type, started_at);
CREATE INDEX idx_bulk_ops_status ON bulk_operations_log (status);
CREATE INDEX idx_bulk_ops_performer_started ON bulk_operations_log (performed_by, started_at DESC);

-- =================== PERMISSION_CACHE TABLE INDEXES ===================
CREATE INDEX idx_expires ON permission_cache (expires_at);

-- =================== QUERY_PERFORMANCE_LOG TABLE INDEXES ===================
CREATE INDEX idx_query_hash ON query_performance_log (query_hash);
CREATE INDEX idx_logged_at ON query_performance_log (logged_at);

-- =================== ADDITIONAL PERFORMANCE INDEXES ===================
-- Enhanced indexes for group hierarchy performance
CREATE INDEX idx_user_groups_hierarchy_lookup ON user_groups (parent_group_id, group_level, group_name);
CREATE INDEX idx_permissions_hierarchy_lookup ON permissions (project_id, parent_permission_id, permission_level);
CREATE INDEX idx_permission_groups_hierarchy_lookup ON permission_groups (project_id, parent_permission_group_id, group_level);

-- Composite indexes for complex group-based queries
CREATE INDEX idx_user_group_members_active_lookup ON user_group_members (user_id, user_group_id, is_active);
CREATE INDEX idx_user_group_projects_active_lookup ON user_group_projects (user_group_id, project_id, is_active);
CREATE INDEX idx_user_group_permission_groups_full ON user_group_permission_groups (user_group_id, project_id, permission_group_id, is_active);

-- Indexes for permission checking performance
CREATE INDEX idx_permission_group_permissions_lookup ON permission_group_permissions (permission_group_id, permission_id, is_active);
CREATE INDEX idx_permissions_project_name_lookup ON permissions (project_id, permission_name, is_active);

-- =================== INDEX CREATION COMPLETE ===================
SELECT 'All indexes created successfully!' as status;
