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

-- =================== ADDITIONAL CONSTRAINTS ===================
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