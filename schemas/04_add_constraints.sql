-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Foreign Keys and Constraints Script (Updated for Group-Based Access)
-- MySQL Database

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

USE magic_auth;

-- =================== USERS TABLE CONSTRAINTS ===================
ALTER TABLE users
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
    ADD CONSTRAINT fk_user_groups_parent FOREIGN KEY (parent_group_id) 
        REFERENCES user_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_groups_created_by FOREIGN KEY (created_by) 
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

-- =================== PERMISSIONS TABLE CONSTRAINTS ===================
ALTER TABLE permissions
    ADD CONSTRAINT fk_permissions_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_permissions_parent FOREIGN KEY (parent_permission_id) 
        REFERENCES permissions(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_permissions_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== PERMISSION_GROUPS TABLE CONSTRAINTS ===================
ALTER TABLE permission_groups
    ADD CONSTRAINT fk_permission_groups_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_permission_groups_parent FOREIGN KEY (parent_permission_group_id) 
        REFERENCES permission_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
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

-- =================== USER_GROUP_PERMISSION_GROUPS TABLE CONSTRAINTS ===================
ALTER TABLE user_group_permission_groups
    ADD CONSTRAINT fk_ugpg_user_group FOREIGN KEY (user_group_id) 
        REFERENCES user_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpg_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpg_permission_group FOREIGN KEY (permission_group_id) 
        REFERENCES permission_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpg_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpg_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- =================== USER_SESSIONS TABLE CONSTRAINTS ===================
ALTER TABLE user_sessions
    ADD CONSTRAINT fk_user_sessions_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_sessions_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- =================== PERMISSION_AUDIT_LOG TABLE CONSTRAINTS ===================
ALTER TABLE permission_audit_log
    ADD CONSTRAINT fk_audit_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_audit_target_user FOREIGN KEY (target_user_id) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_audit_user_group FOREIGN KEY (user_group_id) 
        REFERENCES user_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
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
    ADD CONSTRAINT fk_activity_logs_user_group FOREIGN KEY (user_group_id) 
        REFERENCES user_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
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
    ADD CONSTRAINT fk_role_history_user_group FOREIGN KEY (user_group_id) 
        REFERENCES user_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
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

-- Ensure hierarchical user groups don't create cycles
DELIMITER $$
CREATE TRIGGER tr_validate_user_group_hierarchy
BEFORE INSERT ON user_groups
FOR EACH ROW
BEGIN
    DECLARE hierarchy_depth INT DEFAULT 0;
    DECLARE current_parent_id VARCHAR(64);
    
    SET current_parent_id = NEW.parent_group_id;
    
    -- Check for cycles and depth limit
    WHILE current_parent_id IS NOT NULL AND hierarchy_depth < 10 DO
        SET hierarchy_depth = hierarchy_depth + 1;
        
        -- Check if we're creating a cycle
        IF current_parent_id = NEW.id THEN
            SIGNAL SQLSTATE '45000' 
            SET MESSAGE_TEXT = 'Circular reference detected in user group hierarchy';
        END IF;
        
        -- Get next parent
        SELECT parent_group_id INTO current_parent_id 
        FROM user_groups 
        WHERE id = current_parent_id;
    END WHILE;
    
    -- Set the correct level
    SET NEW.group_level = hierarchy_depth;
    
    -- Enforce maximum hierarchy depth
    IF hierarchy_depth >= 10 THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'User group hierarchy depth cannot exceed 10 levels';
    END IF;
END$$

-- Trigger to automatically update updated_at field for users table
CREATE TRIGGER tr_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
BEGIN
    SET NEW.updated_at = NOW();
END$$

-- Trigger to automatically update updated_at field for projects table
CREATE TRIGGER tr_projects_updated_at
BEFORE UPDATE ON projects
FOR EACH ROW
BEGIN
    SET NEW.updated_at = NOW();
END$$

-- Trigger to automatically update updated_at field for user_groups table
CREATE TRIGGER tr_user_groups_updated_at
BEFORE UPDATE ON user_groups
FOR EACH ROW
BEGIN
    SET NEW.updated_at = NOW();
END$$

-- Trigger to automatically update updated_at field for permissions table
CREATE TRIGGER tr_permissions_updated_at
BEFORE UPDATE ON permissions
FOR EACH ROW
BEGIN
    SET NEW.updated_at = NOW();
END$$

-- Trigger to automatically update updated_at field for permission_groups table
CREATE TRIGGER tr_permission_groups_updated_at
BEFORE UPDATE ON permission_groups
FOR EACH ROW
BEGIN
    SET NEW.updated_at = NOW();
END$$

-- Ensure hierarchical permission groups don't create cycles
DELIMITER $$
CREATE TRIGGER tr_validate_permission_group_hierarchy
BEFORE INSERT ON permission_groups
FOR EACH ROW
BEGIN
    DECLARE hierarchy_depth INT DEFAULT 0;
    DECLARE current_parent_id VARCHAR(64);
    
    SET current_parent_id = NEW.parent_permission_group_id;
    
    -- Check for cycles and depth limit
    WHILE current_parent_id IS NOT NULL AND hierarchy_depth < 10 DO
        SET hierarchy_depth = hierarchy_depth + 1;
        
        -- Check if we're creating a cycle
        IF current_parent_id = NEW.id THEN
            SIGNAL SQLSTATE '45000' 
            SET MESSAGE_TEXT = 'Circular reference detected in permission group hierarchy';
        END IF;
        
        -- Get next parent and verify same project
        SELECT parent_permission_group_id, project_id INTO current_parent_id, @parent_project_id
        FROM permission_groups 
        WHERE id = current_parent_id;
        
        -- Ensure parent is in same project
        IF @parent_project_id != NEW.project_id THEN
            SIGNAL SQLSTATE '45000' 
            SET MESSAGE_TEXT = 'Permission group hierarchy must be within the same project';
        END IF;
    END WHILE;
    
    -- Set the correct level
    SET NEW.group_level = hierarchy_depth;
    
    -- Enforce maximum hierarchy depth
    IF hierarchy_depth >= 10 THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Permission group hierarchy depth cannot exceed 10 levels';
    END IF;
END$$

-- Ensure hierarchical permissions don't create cycles
DELIMITER $$
CREATE TRIGGER tr_validate_permission_hierarchy
BEFORE INSERT ON permissions
FOR EACH ROW
BEGIN
    DECLARE hierarchy_depth INT DEFAULT 0;
    DECLARE current_parent_id VARCHAR(64);
    
    SET current_parent_id = NEW.parent_permission_id;
    
    -- Check for cycles and depth limit
    WHILE current_parent_id IS NOT NULL AND hierarchy_depth < 10 DO
        SET hierarchy_depth = hierarchy_depth + 1;
        
        -- Check if we're creating a cycle
        IF current_parent_id = NEW.id THEN
            SIGNAL SQLSTATE '45000' 
            SET MESSAGE_TEXT = 'Circular reference detected in permission hierarchy';
        END IF;
        
        -- Get next parent and verify same project
        SELECT parent_permission_id, project_id INTO current_parent_id, @parent_project_id
        FROM permissions 
        WHERE id = current_parent_id;
        
        -- Ensure parent is in same project
        IF @parent_project_id != NEW.project_id THEN
            SIGNAL SQLSTATE '45000' 
            SET MESSAGE_TEXT = 'Permission hierarchy must be within the same project';
        END IF;
    END WHILE;
    
    -- Set the correct level
    SET NEW.permission_level = hierarchy_depth;
    
    -- Enforce maximum hierarchy depth
    IF hierarchy_depth >= 10 THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Permission hierarchy depth cannot exceed 10 levels';
    END IF;
END$$

-- Ensure permission group and permission belong to same project
DELIMITER $$
CREATE TRIGGER tr_validate_permission_group_permissions_project
BEFORE INSERT ON permission_group_permissions
FOR EACH ROW
BEGIN
    DECLARE perm_project_id VARCHAR(64);
    DECLARE group_project_id VARCHAR(64);
    
    -- Get project IDs
    SELECT project_id INTO perm_project_id
    FROM permissions 
    WHERE id = NEW.permission_id AND is_active = 1;
    
    SELECT project_id INTO group_project_id
    FROM permission_groups 
    WHERE id = NEW.permission_group_id AND is_active = 1;
    
    -- Verify they belong to the same project
    IF perm_project_id IS NULL OR group_project_id IS NULL THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Invalid permission or permission group ID';
    END IF;
    
    IF perm_project_id != group_project_id THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Permission and permission group must belong to the same project';
    END IF;
END$$
DELIMITER ;

-- Ensure user group permission assignments are valid
DELIMITER $$
CREATE TRIGGER tr_validate_user_group_permission_groups
BEFORE INSERT ON user_group_permission_groups
FOR EACH ROW
BEGIN
    DECLARE group_project_id VARCHAR(64);
    
    -- Verify permission group belongs to the specified project
    SELECT project_id INTO group_project_id
    FROM permission_groups 
    WHERE id = NEW.permission_group_id AND is_active = 1;
    
    IF group_project_id IS NULL THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Invalid permission group ID';
    END IF;
    
    IF group_project_id != NEW.project_id THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Permission group must belong to the specified project';
    END IF;
    
    -- Verify user group exists and is active
    IF NOT EXISTS (SELECT 1 FROM user_groups WHERE id = NEW.user_group_id AND is_active = 1) THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Invalid or inactive user group ID';
    END IF;
    
    -- Verify project exists and is active
    IF NOT EXISTS (SELECT 1 FROM projects WHERE id = NEW.project_id AND is_active = 1) THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Invalid or inactive project ID';
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