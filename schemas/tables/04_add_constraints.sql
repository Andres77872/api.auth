-- ===================================================================================
-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Foreign Keys and Constraints Script - GROUPS OF GROUPS Architecture
-- ===================================================================================
-- This script adds all foreign key constraints and triggers for data integrity
-- MySQL Database
-- ===================================================================================

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

USE magic_auth;

-- ===================================================================================
-- USERS TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE users
    ADD CONSTRAINT fk_users_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_role FOREIGN KEY (role_id) 
        REFERENCES roles(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- ===================================================================================
-- PROJECTS TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE projects
    ADD CONSTRAINT fk_projects_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_projects_owner FOREIGN KEY (owner_id) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_projects_archived_by FOREIGN KEY (archived_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- ===================================================================================
-- USER_GROUPS TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE user_groups
    ADD CONSTRAINT fk_user_groups_parent FOREIGN KEY (parent_group_id) 
        REFERENCES user_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_groups_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- ===================================================================================
-- USER_GROUP_MEMBERS TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE user_group_members
    ADD CONSTRAINT fk_user_group_members_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_group_members_group FOREIGN KEY (user_group_id) 
        REFERENCES user_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_group_members_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_group_members_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- ===================================================================================
-- PROJECT_GROUPS TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE project_groups
    ADD CONSTRAINT fk_project_groups_parent FOREIGN KEY (parent_group_id) 
        REFERENCES project_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_project_groups_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- ===================================================================================
-- PROJECT_GROUP_MEMBERS TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE project_group_members
    ADD CONSTRAINT fk_project_group_members_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_project_group_members_group FOREIGN KEY (project_group_id) 
        REFERENCES project_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_project_group_members_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_project_group_members_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- ===================================================================================
-- USER_GROUP_PROJECT_GROUPS TABLE CONSTRAINTS (GROUPS OF GROUPS)
-- ===================================================================================
ALTER TABLE user_group_project_groups
    ADD CONSTRAINT fk_ugpg_user_group FOREIGN KEY (user_group_id) 
        REFERENCES user_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpg_project_group FOREIGN KEY (project_group_id) 
        REFERENCES project_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpg_granted_by FOREIGN KEY (granted_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpg_revoked_by FOREIGN KEY (revoked_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- ===================================================================================
-- USER_GROUP_PROJECT_GROUP_PERMISSIONS TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE user_group_project_group_permissions
    ADD CONSTRAINT fk_ugpgp_user_group FOREIGN KEY (user_group_id) 
        REFERENCES user_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpgp_project_group FOREIGN KEY (project_group_id) 
        REFERENCES project_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpgp_permission_group FOREIGN KEY (permission_group_id) 
        REFERENCES global_permission_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpgp_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpgp_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- ===================================================================================
-- USER_GROUP_PROJECT_GROUP_ROLES TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE user_group_project_group_roles
    ADD CONSTRAINT fk_ugpgr_user_group FOREIGN KEY (user_group_id) 
        REFERENCES user_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpgr_project_group FOREIGN KEY (project_group_id) 
        REFERENCES project_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpgr_role FOREIGN KEY (role_id) 
        REFERENCES roles(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpgr_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_ugpgr_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- ===================================================================================
-- USER_SESSIONS TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE user_sessions
    ADD CONSTRAINT fk_user_sessions_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_user_sessions_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- ===================================================================================
-- API_AUDIT_LOG TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE api_audit_log
    ADD CONSTRAINT fk_api_audit_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_api_audit_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE SET NULL ON UPDATE CASCADE;

-- ===================================================================================
-- PERMISSION_CACHE TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE permission_cache
    ADD CONSTRAINT fk_permission_cache_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    ADD CONSTRAINT fk_permission_cache_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- ===================================================================================
-- ROLE_ASSIGNMENT_HISTORY TABLE CONSTRAINTS
-- All FKs are nullable except performed_by to support different assignment types
-- ===================================================================================
ALTER TABLE role_assignment_history
    ADD CONSTRAINT fk_role_history_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_role_history_user_group FOREIGN KEY (user_group_id) 
        REFERENCES user_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_role_history_project_group FOREIGN KEY (project_group_id) 
        REFERENCES project_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_role_history_permission_group FOREIGN KEY (permission_group_id) 
        REFERENCES global_permission_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_role_history_role FOREIGN KEY (role_id) 
        REFERENCES roles(id) ON DELETE SET NULL ON UPDATE CASCADE,
    ADD CONSTRAINT fk_role_history_performed_by FOREIGN KEY (performed_by) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- ===================================================================================
-- BULK_OPERATIONS_LOG TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE bulk_operations_log
    ADD CONSTRAINT fk_bulk_ops_performed_by FOREIGN KEY (performed_by) 
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE;

-- ===================================================================================
-- GLOBAL ROLE SYSTEM CONSTRAINTS
-- ===================================================================================
ALTER TABLE roles
    ADD CONSTRAINT fk_roles_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE global_permission_groups
    ADD CONSTRAINT fk_gpg_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE global_permissions
    ADD CONSTRAINT fk_gp_created_by FOREIGN KEY (created_by) 
        REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE role_permission_groups
    ADD CONSTRAINT fk_rpg_role FOREIGN KEY (role_id) 
        REFERENCES roles(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_rpg_permission_group FOREIGN KEY (permission_group_id) 
        REFERENCES global_permission_groups(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_rpg_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_rpg_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE global_permission_group_permissions
    ADD CONSTRAINT fk_gpgp_permission_group FOREIGN KEY (permission_group_id) 
        REFERENCES global_permission_groups(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_gpgp_permission FOREIGN KEY (permission_id) 
        REFERENCES global_permissions(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_gpgp_granted_by FOREIGN KEY (granted_by) 
        REFERENCES users(id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_gpgp_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL;

-- ===================================================================================
-- PERMISSION ASSIGNMENT CONSTRAINTS
-- ===================================================================================
ALTER TABLE user_group_permission_groups
    ADD CONSTRAINT fk_ugpg2_user_group FOREIGN KEY (user_group_id) 
        REFERENCES user_groups(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_ugpg2_permission_group FOREIGN KEY (permission_group_id) 
        REFERENCES global_permission_groups(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_ugpg2_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_ugpg2_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE user_permission_groups
    ADD CONSTRAINT fk_upg_user FOREIGN KEY (user_id) 
        REFERENCES users(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_upg_permission_group FOREIGN KEY (permission_group_id) 
        REFERENCES global_permission_groups(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_upg_assigned_by FOREIGN KEY (assigned_by) 
        REFERENCES users(id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_upg_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL;

-- ===================================================================================
-- CATALOG TABLE CONSTRAINTS
-- ===================================================================================
ALTER TABLE role_project_catalog
    ADD CONSTRAINT fk_rpc_role FOREIGN KEY (role_id) 
        REFERENCES roles(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_rpc_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_rpc_added_by FOREIGN KEY (added_by) 
        REFERENCES users(id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_rpc_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE permission_project_catalog
    ADD CONSTRAINT fk_ppc_permission FOREIGN KEY (permission_id) 
        REFERENCES global_permissions(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_ppc_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_ppc_added_by FOREIGN KEY (added_by) 
        REFERENCES users(id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_ppc_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL;

ALTER TABLE permission_group_project_catalog
    ADD CONSTRAINT fk_pgpc_permission_group FOREIGN KEY (permission_group_id) 
        REFERENCES global_permission_groups(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_pgpc_project FOREIGN KEY (project_id) 
        REFERENCES projects(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_pgpc_added_by FOREIGN KEY (added_by) 
        REFERENCES users(id) ON DELETE SET NULL,
    ADD CONSTRAINT fk_pgpc_removed_by FOREIGN KEY (removed_by) 
        REFERENCES users(id) ON DELETE SET NULL;

-- ===================================================================================
-- DATA INTEGRITY TRIGGERS
-- ===================================================================================

DELIMITER $$

-- Ensure hierarchical user groups don't create cycles
-- NOTE: Root groups are identified by parent_group_id IS NULL
-- No group_level field - use recursive queries when depth is needed
CREATE TRIGGER tr_validate_user_group_hierarchy
BEFORE INSERT ON user_groups
FOR EACH ROW
BEGIN
    DECLARE v_depth INT DEFAULT 0;
    DECLARE v_current_parent_id VARCHAR(64);
    
    IF NEW.parent_group_id IS NOT NULL THEN
        SET v_current_parent_id = NEW.parent_group_id;
        
        -- Walk up the tree to detect cycles (max 10 iterations for safety)
        WHILE v_current_parent_id IS NOT NULL AND v_depth < 10 DO
            SET v_depth = v_depth + 1;
            
            IF v_current_parent_id = NEW.id THEN
                SIGNAL SQLSTATE '45000' 
                SET MESSAGE_TEXT = 'Circular reference detected in user group hierarchy';
            END IF;
            
            SELECT parent_group_id INTO v_current_parent_id 
            FROM user_groups 
            WHERE id = v_current_parent_id;
        END WHILE;
        
        IF v_depth >= 10 THEN
            SIGNAL SQLSTATE '45000' 
            SET MESSAGE_TEXT = 'User group hierarchy depth cannot exceed 10 levels';
        END IF;
    END IF;
END$$

-- Also validate on UPDATE to prevent cycles when parent changes
CREATE TRIGGER tr_validate_user_group_hierarchy_update
BEFORE UPDATE ON user_groups
FOR EACH ROW
BEGIN
    DECLARE v_depth INT DEFAULT 0;
    DECLARE v_current_parent_id VARCHAR(64);
    
    IF NEW.parent_group_id IS NOT NULL AND NEW.parent_group_id != COALESCE(OLD.parent_group_id, '') THEN
        -- Prevent setting parent to self
        IF NEW.parent_group_id = NEW.id THEN
            SIGNAL SQLSTATE '45000' 
            SET MESSAGE_TEXT = 'User group cannot be its own parent';
        END IF;
        
        SET v_current_parent_id = NEW.parent_group_id;
        
        WHILE v_current_parent_id IS NOT NULL AND v_depth < 10 DO
            SET v_depth = v_depth + 1;
            
            IF v_current_parent_id = NEW.id THEN
                SIGNAL SQLSTATE '45000' 
                SET MESSAGE_TEXT = 'Circular reference detected in user group hierarchy';
            END IF;
            
            SELECT parent_group_id INTO v_current_parent_id 
            FROM user_groups 
            WHERE id = v_current_parent_id;
        END WHILE;
        
        IF v_depth >= 10 THEN
            SIGNAL SQLSTATE '45000' 
            SET MESSAGE_TEXT = 'User group hierarchy depth cannot exceed 10 levels';
        END IF;
    END IF;
END$$

-- Auto-update timestamps
CREATE TRIGGER tr_users_updated_at
BEFORE UPDATE ON users
FOR EACH ROW
BEGIN
    SET NEW.updated_at = NOW();
END$$

CREATE TRIGGER tr_projects_updated_at
BEFORE UPDATE ON projects
FOR EACH ROW
BEGIN
    SET NEW.updated_at = NOW();
END$$

CREATE TRIGGER tr_user_groups_updated_at
BEFORE UPDATE ON user_groups
FOR EACH ROW
BEGIN
    SET NEW.updated_at = NOW();
END$$

CREATE TRIGGER tr_project_groups_updated_at
BEFORE UPDATE ON project_groups
FOR EACH ROW
BEGIN
    SET NEW.updated_at = NOW();
END$$

-- Ensure hierarchical project groups don't create cycles
-- NOTE: Root groups are identified by parent_group_id IS NULL
CREATE TRIGGER tr_validate_project_group_hierarchy
BEFORE INSERT ON project_groups
FOR EACH ROW
BEGIN
    DECLARE v_depth INT DEFAULT 0;
    DECLARE v_current_parent_id VARCHAR(64);
    
    IF NEW.parent_group_id IS NOT NULL THEN
        SET v_current_parent_id = NEW.parent_group_id;
        
        WHILE v_current_parent_id IS NOT NULL AND v_depth < 10 DO
            SET v_depth = v_depth + 1;
            
            IF v_current_parent_id = NEW.id THEN
                SIGNAL SQLSTATE '45000' 
                SET MESSAGE_TEXT = 'Circular reference detected in project group hierarchy';
            END IF;
            
            SELECT parent_group_id INTO v_current_parent_id 
            FROM project_groups 
            WHERE id = v_current_parent_id;
        END WHILE;
        
        IF v_depth >= 10 THEN
            SIGNAL SQLSTATE '45000' 
            SET MESSAGE_TEXT = 'Project group hierarchy depth cannot exceed 10 levels';
        END IF;
    END IF;
END$$

-- Also validate on UPDATE to prevent cycles when parent changes
CREATE TRIGGER tr_validate_project_group_hierarchy_update
BEFORE UPDATE ON project_groups
FOR EACH ROW
BEGIN
    DECLARE v_depth INT DEFAULT 0;
    DECLARE v_current_parent_id VARCHAR(64);
    
    IF NEW.parent_group_id IS NOT NULL AND NEW.parent_group_id != COALESCE(OLD.parent_group_id, '') THEN
        IF NEW.parent_group_id = NEW.id THEN
            SIGNAL SQLSTATE '45000' 
            SET MESSAGE_TEXT = 'Project group cannot be its own parent';
        END IF;
        
        SET v_current_parent_id = NEW.parent_group_id;
        
        WHILE v_current_parent_id IS NOT NULL AND v_depth < 10 DO
            SET v_depth = v_depth + 1;
            
            IF v_current_parent_id = NEW.id THEN
                SIGNAL SQLSTATE '45000' 
                SET MESSAGE_TEXT = 'Circular reference detected in project group hierarchy';
            END IF;
            
            SELECT parent_group_id INTO v_current_parent_id 
            FROM project_groups 
            WHERE id = v_current_parent_id;
        END WHILE;
        
        IF v_depth >= 10 THEN
            SIGNAL SQLSTATE '45000' 
            SET MESSAGE_TEXT = 'Project group hierarchy depth cannot exceed 10 levels';
        END IF;
    END IF;
END$$

CREATE TRIGGER tr_roles_updated_at
BEFORE UPDATE ON roles
FOR EACH ROW
BEGIN
    SET NEW.updated_at = NOW();
END$$

CREATE TRIGGER tr_global_permission_groups_updated_at
BEFORE UPDATE ON global_permission_groups
FOR EACH ROW
BEGIN
    SET NEW.updated_at = NOW();
END$$

CREATE TRIGGER tr_global_permissions_updated_at
BEFORE UPDATE ON global_permissions
FOR EACH ROW
BEGIN
    SET NEW.updated_at = NOW();
END$$

-- Validation triggers
CREATE TRIGGER tr_validate_session_expiry
BEFORE INSERT ON user_sessions
FOR EACH ROW
BEGIN
    DECLARE v_user_type VARCHAR(20);
    DECLARE v_has_access INT DEFAULT 0;
    
    -- Check session expiry
    IF NEW.expires_at <= NOW() THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Session expiry must be in the future';
    END IF;
    
    -- Get user type
    SELECT user_type INTO v_user_type 
    FROM users 
    WHERE id = NEW.user_id AND is_active = TRUE;
    
    -- Validate user exists and is active
    IF v_user_type IS NULL THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'User does not exist or is inactive';
    END IF;
    
    -- Validate project exists and is active
    IF NOT EXISTS (
        SELECT 1
        FROM projects
        WHERE id = NEW.project_id
          AND is_active = TRUE
          AND (archived = FALSE OR archived IS NULL)
    ) THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Project does not exist, is inactive, or is archived';
    END IF;
    
    -- Root users have access to all projects
    IF v_user_type = 'root' THEN
        SET v_has_access = 1;
    ELSE
        -- Check access via groups of groups: User → User Group → Project Group → Project
        SELECT COUNT(*) INTO v_has_access
        FROM user_group_members ugm
        JOIN user_groups ug ON ug.id = ugm.user_group_id AND ug.is_active = TRUE
        JOIN user_group_project_groups ugpg ON ug.id = ugpg.user_group_id AND ugpg.is_active = TRUE
        JOIN project_groups pg ON pg.id = ugpg.project_group_id AND pg.is_active = TRUE
        JOIN project_group_members pgm ON pg.id = pgm.project_group_id AND pgm.is_active = TRUE
        JOIN projects p ON p.id = pgm.project_id
            AND p.is_active = TRUE
            AND (p.archived = FALSE OR p.archived IS NULL)
        WHERE ugm.user_id = NEW.user_id
          AND ugm.is_active = TRUE
          AND pgm.project_id = NEW.project_id
        LIMIT 1;
    END IF;
    
    -- Reject session if no access
    IF v_has_access = 0 THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'User does not have access to this project';
    END IF;
END$$

CREATE TRIGGER tr_validate_permission_cache_expiry
BEFORE INSERT ON permission_cache
FOR EACH ROW
BEGIN
    IF NEW.expires_at <= NOW() THEN
        SIGNAL SQLSTATE '45000' 
        SET MESSAGE_TEXT = 'Permission cache expiry must be in the future';
    END IF;
END$$

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

-- ===================================================================================
-- CONSTRAINTS AND TRIGGERS COMPLETE
-- ===================================================================================
SELECT 'All constraints and triggers created successfully!' as status,
       'Groups of Groups architecture constraints applied' as details;
