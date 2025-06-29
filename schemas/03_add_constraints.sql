-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Foreign Keys and Constraints Script
-- MySQL Database

USE magic_auth;

-- =================== USERS TABLE CONSTRAINTS ===================
ALTER TABLE users
    ADD CONSTRAINT fk_users_assigned_project FOREIGN KEY (assigned_project_id) 
        REFERENCES projects(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_users_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== PROJECTS TABLE CONSTRAINTS ===================
ALTER TABLE projects
    ADD CONSTRAINT fk_projects_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_projects_owner FOREIGN KEY (owner_id) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_projects_archived_by FOREIGN KEY (archived_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== USER_GROUPS TABLE CONSTRAINTS ===================
ALTER TABLE user_groups
    ADD CONSTRAINT fk_user_groups_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- =================== USER_PROJECTS TABLE CONSTRAINTS ===================
ALTER TABLE user_projects
    ADD CONSTRAINT fk_user_projects_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_projects_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_projects_granted_by FOREIGN KEY (granted_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_projects_revoked_by FOREIGN KEY (revoked_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== USER_GROUP_MEMBERS TABLE CONSTRAINTS ===================
ALTER TABLE user_group_members
    ADD CONSTRAINT fk_user_group_members_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_group_members_group FOREIGN KEY (user_group_id) 
        REFERENCES user_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_group_members_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_group_members_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== USER_GROUP_PROJECTS TABLE CONSTRAINTS ===================
ALTER TABLE user_group_projects
    ADD CONSTRAINT fk_user_group_projects_group FOREIGN KEY (user_group_id) 
        REFERENCES user_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_group_projects_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_group_projects_granted_by FOREIGN KEY (granted_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_group_projects_revoked_by FOREIGN KEY (revoked_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== PROJECT_GROUP_MEMBERS TABLE CONSTRAINTS ===================
ALTER TABLE project_group_members
    ADD CONSTRAINT fk_project_group_members_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_project_group_members_group FOREIGN KEY (project_group_id) 
        REFERENCES project_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_project_group_members_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_project_group_members_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== PERMISSIONS TABLE CONSTRAINTS ===================
ALTER TABLE permissions
    ADD CONSTRAINT fk_permissions_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_permissions_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== PERMISSION_GROUPS TABLE CONSTRAINTS ===================
ALTER TABLE permission_groups
    ADD CONSTRAINT fk_permission_groups_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_permission_groups_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== PERMISSION_GROUP_PERMISSIONS TABLE CONSTRAINTS ===================
ALTER TABLE permission_group_permissions
    ADD CONSTRAINT fk_pgp_permission_group FOREIGN KEY (permission_group_id) 
        REFERENCES permission_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_pgp_permission FOREIGN KEY (permission_id) 
        REFERENCES permissions(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_pgp_granted_by FOREIGN KEY (granted_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_pgp_revoked_by FOREIGN KEY (revoked_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== USER_PROJECT_PERMISSION_GROUPS TABLE CONSTRAINTS ===================
ALTER TABLE user_project_permission_groups
    ADD CONSTRAINT fk_uppg_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_uppg_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_uppg_permission_group FOREIGN KEY (permission_group_id) 
        REFERENCES permission_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_uppg_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_uppg_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== USER_SESSIONS TABLE CONSTRAINTS ===================
ALTER TABLE user_sessions
    ADD CONSTRAINT fk_user_sessions_user_project FOREIGN KEY (user_project_id) 
        REFERENCES user_projects(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- =================== USER_PROJECT_GROUPS TABLE CONSTRAINTS ===================
ALTER TABLE user_project_groups
    ADD CONSTRAINT fk_user_project_groups_user_project FOREIGN KEY (user_project_id) 
        REFERENCES user_projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_project_groups_group FOREIGN KEY (group_id) 
        REFERENCES user_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_project_groups_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_project_groups_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== ADMIN_PROJECT_ASSIGNMENTS TABLE CONSTRAINTS ===================
ALTER TABLE admin_project_assignments
    ADD CONSTRAINT fk_admin_assignments_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_admin_assignments_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_admin_assignments_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_admin_assignments_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== PERMISSION_AUDIT_LOG TABLE CONSTRAINTS ===================
ALTER TABLE permission_audit_log
    ADD CONSTRAINT fk_audit_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_audit_target_user FOREIGN KEY (target_user_id) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_audit_permission FOREIGN KEY (permission_id) 
        REFERENCES permissions(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_audit_permission_group FOREIGN KEY (permission_group_id) 
        REFERENCES permission_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_audit_performed_by FOREIGN KEY (performed_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== ACTIVITY_LOGS TABLE CONSTRAINTS ===================
ALTER TABLE activity_logs
    ADD CONSTRAINT fk_activity_logs_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_activity_logs_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_activity_logs_target_user FOREIGN KEY (target_user_id) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== PERFORMANCE OPTIMIZATION TABLE CONSTRAINTS ===================
ALTER TABLE permission_cache
    ADD CONSTRAINT fk_permission_cache_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_permission_cache_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- =================== ADDITIONAL TABLE CONSTRAINTS ===================

-- =================== USER_PASSWORD_RESETS TABLE CONSTRAINTS ===================
ALTER TABLE user_password_resets
    ADD CONSTRAINT fk_user_password_resets_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_password_resets_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- =================== ROLE_ASSIGNMENT_HISTORY TABLE CONSTRAINTS ===================
ALTER TABLE role_assignment_history
    ADD CONSTRAINT fk_role_history_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_role_history_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_role_history_permission_group FOREIGN KEY (permission_group_id) 
        REFERENCES permission_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_role_history_performed_by FOREIGN KEY (performed_by) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- =================== BULK_OPERATIONS_LOG TABLE CONSTRAINTS ===================
ALTER TABLE bulk_operations_log
    ADD CONSTRAINT fk_bulk_ops_performed_by FOREIGN KEY (performed_by) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- =================== DATA INTEGRITY CONSTRAINTS ===================

-- Ensure admin users have at least one project assignment
DELIMITER $$
CREATE TRIGGER tr_validate_admin_project_assignment
BEFORE UPDATE ON users
FOR EACH ROW
BEGIN
    IF NEW.user_type = 'admin' AND NEW.assigned_project_id IS NULL THEN
        -- Check if user has any active project assignments in admin_project_assignments
        IF NOT EXISTS (
            SELECT 1 FROM admin_project_assignments 
            WHERE user_id = NEW.id AND is_active = 1
        ) THEN
            SIGNAL SQLSTATE '45000' 
            SET MESSAGE_TEXT = 'Admin users must have at least one project assignment';
        END IF;
    END IF;
END$$
DELIMITER ;

-- Ensure session tokens expire in the future when created
DELIMITER $$
CREATE TRIGGER tr_validate_session_expiry
BEFORE INSERT ON user_sessions
FOR EACH ROW
BEGIN
    IF NEW.expires_at <= NOW() THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Session expiry must be in the future';
    END IF;
END$$
DELIMITER ;

-- Ensure permission cache entries expire in the future
DELIMITER $$
CREATE TRIGGER tr_validate_permission_cache_expiry
BEFORE INSERT ON permission_cache
FOR EACH ROW
BEGIN
    IF NEW.expires_at <= NOW() THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Permission cache expiry must be in the future';
    END IF;
END$$
DELIMITER ;

-- Ensure password reset tokens expire in the future when created
DELIMITER $$
CREATE TRIGGER tr_validate_password_reset_expiry
BEFORE INSERT ON user_password_resets
FOR EACH ROW
BEGIN
    IF NEW.expires_at <= NOW() THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Password reset expiry must be in the future';
    END IF;
END$$
DELIMITER ;

-- Ensure bulk operations have valid counts
DELIMITER $$
CREATE TRIGGER tr_validate_bulk_operation_counts
BEFORE INSERT ON bulk_operations_log
FOR EACH ROW
BEGIN
    IF NEW.target_count < 0 OR NEW.success_count < 0 OR NEW.error_count < 0 THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Bulk operation counts must be non-negative';
    END IF;
    IF NEW.success_count + NEW.error_count > NEW.target_count THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Sum of success and error counts cannot exceed target count';
    END IF;
END$$
DELIMITER ;

-- Ensure bulk operations completion time is after start time
DELIMITER $$
CREATE TRIGGER tr_validate_bulk_operation_completion
BEFORE UPDATE ON bulk_operations_log
FOR EACH ROW
BEGIN
    IF NEW.completed_at IS NOT NULL AND NEW.completed_at < NEW.started_at THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Bulk operation completion time must be after start time';
    END IF;
END$$
DELIMITER ; 