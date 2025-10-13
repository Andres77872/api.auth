-- Additional Stored Procedures for Complete SQL Query Conversion
-- MySQL Database

USE magic_auth;

-- Force collation for stored procedure creation in MySQL 8/9
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- =====================================================
-- USER MANAGEMENT PROCEDURES
-- =====================================================

-- Get user type
DROP PROCEDURE IF EXISTS sp_get_user_type$$
CREATE PROCEDURE sp_get_user_type(
    IN p_user_id VARCHAR(64)
)
BEGIN
    SELECT user_type
    FROM users
    WHERE id = p_user_id
      AND is_active = 1;
END$$

-- Get user by ID
DROP PROCEDURE IF EXISTS sp_get_user_by_id$$
CREATE PROCEDURE sp_get_user_by_id(
    IN p_user_id VARCHAR(64)
)
BEGIN
    SELECT id, user_hash, username, email, password_hash, user_type, created_at, is_active
    FROM users
    WHERE id = p_user_id
      AND is_active = 1;
END$$

-- Get user by hash
DROP PROCEDURE IF EXISTS sp_get_user_by_hash$$
CREATE PROCEDURE sp_get_user_by_hash(
    IN p_user_hash VARCHAR(255)
)
BEGIN
    SELECT id, user_hash, username, email, password_hash, user_type, created_at, is_active
    FROM users
    WHERE user_hash = p_user_hash
      AND is_active = 1;
END$$

-- Check username/email availability
DROP PROCEDURE IF EXISTS sp_check_username_email_available$$
CREATE PROCEDURE sp_check_username_email_available(
    IN p_username_or_email VARCHAR(255)
)
BEGIN
    SELECT COUNT(*) as count
    FROM users
    WHERE (username = p_username_or_email OR email = p_username_or_email)
      AND is_active = 1;
END$$

-- Create root user
DROP PROCEDURE IF EXISTS sp_create_root_user$$
CREATE PROCEDURE sp_create_root_user(
    IN p_user_hash VARCHAR(255),
    IN p_username VARCHAR(100),
    IN p_email VARCHAR(255),
    IN p_password_hash VARCHAR(255),
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO users (user_hash, username, email, password_hash, user_type, created_by, created_at)
    VALUES (p_user_hash, p_username, p_email, p_password_hash, 'root', p_created_by, NOW());
    
    SELECT LAST_INSERT_ID() as user_id;
END$$

-- Create consumer user
DROP PROCEDURE IF EXISTS sp_create_consumer_user$$
CREATE PROCEDURE sp_create_consumer_user(
    IN p_user_id VARCHAR(64),
    IN p_user_hash VARCHAR(255),
    IN p_username VARCHAR(100),
    IN p_email VARCHAR(255),
    IN p_password_hash VARCHAR(255),
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO users (id, user_hash, username, email, password_hash, user_type, created_by, created_at)
    VALUES (p_user_id, p_user_hash, p_username, p_email, p_password_hash, 'consumer', p_created_by, NOW());
END$$

-- Create admin user
DROP PROCEDURE IF EXISTS sp_create_admin_user$$
CREATE PROCEDURE sp_create_admin_user(
    IN p_user_hash VARCHAR(255),
    IN p_username VARCHAR(100),
    IN p_email VARCHAR(255),
    IN p_password_hash VARCHAR(255),
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO users (user_hash, username, email, password_hash, user_type, created_by, created_at)
    VALUES (p_user_hash, p_username, p_email, p_password_hash, 'admin', p_created_by, NOW());
    
    SELECT LAST_INSERT_ID() as user_id;
END$$

-- Update user type
DROP PROCEDURE IF EXISTS sp_update_user_type$$
CREATE PROCEDURE sp_update_user_type(
    IN p_user_id VARCHAR(64),
    IN p_new_user_type VARCHAR(20)
)
BEGIN
    UPDATE users
    SET user_type = p_new_user_type,
        updated_at = NOW()
    WHERE id = p_user_id
      AND is_active = 1;
      
    SELECT ROW_COUNT() as rows_affected;
END$$

-- Update password hash
DROP PROCEDURE IF EXISTS sp_update_password_hash$$
CREATE PROCEDURE sp_update_password_hash(
    IN p_user_id VARCHAR(64),
    IN p_new_password_hash VARCHAR(255)
)
BEGIN
    UPDATE users
    SET password_hash = p_new_password_hash,
        updated_at = NOW()
    WHERE id = p_user_id;
      
    SELECT ROW_COUNT() as rows_affected;
END$$

-- Delete user (soft delete)
DROP PROCEDURE IF EXISTS sp_delete_user$$
CREATE PROCEDURE sp_delete_user(
    IN p_user_id VARCHAR(64)
)
BEGIN
    UPDATE users
    SET is_active = 0,
        updated_at = NOW()
    WHERE id = p_user_id
      AND is_active = 1;
      
    SELECT ROW_COUNT() as rows_affected;
END$$

-- Count users
DROP PROCEDURE IF EXISTS sp_count_users$$
CREATE PROCEDURE sp_count_users(
    IN p_user_type VARCHAR(20),
    IN p_include_inactive BOOLEAN
)
BEGIN
    IF p_user_type IS NOT NULL THEN
        IF p_include_inactive THEN
            SELECT COUNT(*) as count FROM users WHERE user_type = p_user_type;
        ELSE
            SELECT COUNT(*) as count FROM users WHERE user_type = p_user_type AND is_active = 1;
        END IF;
    ELSE
        IF p_include_inactive THEN
            SELECT COUNT(*) as count FROM users;
        ELSE
            SELECT COUNT(*) as count FROM users WHERE is_active = 1;
        END IF;
    END IF;
END$$

-- =====================================================
-- USER GROUP MANAGEMENT PROCEDURES
-- =====================================================

-- Create user group
DROP PROCEDURE IF EXISTS sp_create_user_group$$
CREATE PROCEDURE sp_create_user_group(
    IN p_group_id VARCHAR(64),
    IN p_group_hash VARCHAR(255),
    IN p_group_name VARCHAR(100),
    IN p_group_description TEXT
)
BEGIN
    INSERT INTO user_groups (id, group_hash, group_name, group_description, created_at)
    VALUES (p_group_id, p_group_hash, p_group_name, p_group_description, NOW());
END$$

-- Get user group by ID
DROP PROCEDURE IF EXISTS sp_get_user_group_by_id$$
CREATE PROCEDURE sp_get_user_group_by_id(
    IN p_group_id VARCHAR(64)
)
BEGIN
    SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active
    FROM user_groups
    WHERE id = p_group_id
      AND is_active = 1;
END$$

-- Get user group by hash
DROP PROCEDURE IF EXISTS sp_get_user_group_by_hash$$
CREATE PROCEDURE sp_get_user_group_by_hash(
    IN p_group_hash VARCHAR(255)
)
BEGIN
    SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active
    FROM user_groups
    WHERE group_hash = p_group_hash
      AND is_active = 1;
END$$

-- Get user group by name
DROP PROCEDURE IF EXISTS sp_get_user_group_by_name$$
CREATE PROCEDURE sp_get_user_group_by_name(
    IN p_group_name VARCHAR(100)
)
BEGIN
    SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active
    FROM user_groups
    WHERE group_name = p_group_name
      AND is_active = 1;
END$$

-- Delete user group (soft delete)
DROP PROCEDURE IF EXISTS sp_delete_user_group$$
CREATE PROCEDURE sp_delete_user_group(
    IN p_group_id VARCHAR(64),
    IN p_deleted_by VARCHAR(64)
)
BEGIN
    -- Soft delete the user group
    UPDATE user_groups
    SET is_active = 0,
        updated_at = NOW()
    WHERE id = p_group_id
      AND is_active = 1;
    
    -- Soft delete all user memberships
    UPDATE user_group_members
    SET is_active = 0,
        removed_at = NOW(),
        removed_by = p_deleted_by
    WHERE user_group_id = p_group_id
      AND is_active = 1;
    
    -- Soft delete all project access grants
    UPDATE user_group_projects
    SET is_active = 0,
        revoked_at = NOW(),
        revoked_by = p_deleted_by
    WHERE user_group_id = p_group_id
      AND is_active = 1;
      
    SELECT ROW_COUNT() as rows_affected;
END$$

-- Assign user to group
DROP PROCEDURE IF EXISTS sp_assign_user_to_group$$
CREATE PROCEDURE sp_assign_user_to_group(
    IN p_member_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64),
    IN p_assigned_by VARCHAR(64)
)
BEGIN
    INSERT INTO user_group_members (id, user_id, user_group_id, assigned_at, assigned_by)
    VALUES (p_member_id, p_user_id, p_user_group_id, NOW(), p_assigned_by);
END$$

-- Remove user from group
DROP PROCEDURE IF EXISTS sp_remove_user_from_group$$
CREATE PROCEDURE sp_remove_user_from_group(
    IN p_user_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64),
    IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE user_group_members
    SET is_active = 0,
        removed_at = NOW(),
        removed_by = p_removed_by
    WHERE user_id = p_user_id
      AND user_group_id = p_user_group_id
      AND is_active = 1;
      
    SELECT ROW_COUNT() as rows_affected;
END$$

-- Get users in group
DROP PROCEDURE IF EXISTS sp_get_users_in_group$$
CREATE PROCEDURE sp_get_users_in_group(
    IN p_user_group_id VARCHAR(64)
)
BEGIN
    SELECT u.id, u.user_hash, u.username, u.email, u.password_hash, u.created_at, u.updated_at, u.is_active
    FROM users u
    INNER JOIN user_group_members ugm ON u.id = ugm.user_id
    WHERE ugm.user_group_id = p_user_group_id
      AND u.is_active = 1
      AND ugm.is_active = 1
    ORDER BY u.username ASC;
END$$

-- Get user groups for user
DROP PROCEDURE IF EXISTS sp_get_user_groups_for_user$$
CREATE PROCEDURE sp_get_user_groups_for_user(
    IN p_user_id VARCHAR(64)
)
BEGIN
    SELECT ug.id, ug.group_hash, ug.group_name, ug.group_description, ug.created_at, ug.updated_at, ug.is_active
    FROM user_groups ug
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    WHERE ugm.user_id = p_user_id
      AND ug.is_active = 1
      AND ugm.is_active = 1
    ORDER BY ug.group_name ASC;
END$$

-- Grant group project access
DROP PROCEDURE IF EXISTS sp_grant_group_project_access$$
CREATE PROCEDURE sp_grant_group_project_access(
    IN p_access_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_granted_by VARCHAR(64)
)
BEGIN
    INSERT INTO user_group_projects (id, user_group_id, project_id, granted_at, granted_by)
    VALUES (p_access_id, p_user_group_id, p_project_id, NOW(), p_granted_by);
END$$

-- Revoke group project access
DROP PROCEDURE IF EXISTS sp_revoke_group_project_access$$
CREATE PROCEDURE sp_revoke_group_project_access(
    IN p_user_group_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_revoked_by VARCHAR(64)
)
BEGIN
    UPDATE user_group_projects
    SET is_active = 0,
        revoked_at = NOW(),
        revoked_by = p_revoked_by
    WHERE user_group_id = p_user_group_id
      AND project_id = p_project_id
      AND is_active = 1;
      
    SELECT ROW_COUNT() as rows_affected;
END$$

-- Get projects for user group
DROP PROCEDURE IF EXISTS sp_get_projects_for_user_group$$
CREATE PROCEDURE sp_get_projects_for_user_group(
    IN p_user_group_id VARCHAR(64)
)
BEGIN
    SELECT p.id, p.project_hash, p.project_name, p.project_description
    FROM projects p
    INNER JOIN user_group_projects ugp ON p.id = ugp.project_id
    WHERE ugp.user_group_id = p_user_group_id
      AND p.is_active = 1
      AND ugp.is_active = 1
    ORDER BY p.project_name ASC;
END$$

-- Get user groups for project
DROP PROCEDURE IF EXISTS sp_get_user_groups_for_project$$
CREATE PROCEDURE sp_get_user_groups_for_project(
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT ug.id, ug.group_hash, ug.group_name, ug.group_description, ug.created_at, ug.updated_at, ug.is_active
    FROM user_groups ug
    INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
    WHERE ugp.project_id = p_project_id
      AND ug.is_active = 1
      AND ugp.is_active = 1
    ORDER BY ug.group_name ASC;
END$$

-- Get user groups in project (for specific user)
DROP PROCEDURE IF EXISTS sp_get_user_groups_in_project$$
CREATE PROCEDURE sp_get_user_groups_in_project(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT DISTINCT ug.id, ug.group_hash, ug.group_name, ug.group_description, ug.created_at, ug.updated_at, ug.is_active
    FROM user_groups ug
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
    WHERE ugm.user_id = p_user_id
      AND ugp.project_id = p_project_id
      AND ug.is_active = 1
      AND ugm.is_active = 1
      AND ugp.is_active = 1
    ORDER BY ug.group_name ASC;
END$$

-- Count user groups
DROP PROCEDURE IF EXISTS sp_count_user_groups$$
CREATE PROCEDURE sp_count_user_groups()
BEGIN
    SELECT COUNT(*) as count FROM user_groups WHERE is_active = 1;
END$$

-- =====================================================
-- PROJECT MANAGEMENT PROCEDURES
-- =====================================================

-- Create project
DROP PROCEDURE IF EXISTS sp_create_project$$
CREATE PROCEDURE sp_create_project(
    IN p_project_id VARCHAR(64),
    IN p_project_hash VARCHAR(255),
    IN p_project_name VARCHAR(100),
    IN p_project_description TEXT,
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO projects (id, project_hash, project_name, project_description, project_created, created_by)
    VALUES (p_project_id, p_project_hash, p_project_name, p_project_description, NOW(), p_created_by);
END$$

-- Get project by hash
DROP PROCEDURE IF EXISTS sp_get_project_by_hash$$
CREATE PROCEDURE sp_get_project_by_hash(
    IN p_project_hash VARCHAR(255)
)
BEGIN
    SELECT id, project_hash, project_name, project_description, project_created, is_active
    FROM projects
    WHERE project_hash = p_project_hash
      AND is_active = 1;
END$$

-- Get project by ID
DROP PROCEDURE IF EXISTS sp_get_project_by_id$$
CREATE PROCEDURE sp_get_project_by_id(
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT id, project_hash, project_name, project_description, project_created, is_active
    FROM projects
    WHERE id = p_project_id
      AND is_active = 1;
END$$

-- List all projects
DROP PROCEDURE IF EXISTS sp_list_all_projects$$
CREATE PROCEDURE sp_list_all_projects(
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    SELECT id, project_hash, project_name, project_description, project_created, is_active
    FROM projects
    WHERE is_active = 1
    ORDER BY project_created DESC
    LIMIT p_limit OFFSET p_offset;
END$$

-- Count projects
DROP PROCEDURE IF EXISTS sp_count_projects$$
CREATE PROCEDURE sp_count_projects()
BEGIN
    SELECT COUNT(*) as count FROM projects WHERE is_active = 1;
END$$

-- Search projects
DROP PROCEDURE IF EXISTS sp_search_projects$$
CREATE PROCEDURE sp_search_projects(
    IN p_search_term VARCHAR(255),
    IN p_limit INT
)
BEGIN
    SELECT id, project_hash, project_name, project_description, project_created, is_active
    FROM projects
    WHERE is_active = 1
      AND (project_name LIKE CONCAT('%', p_search_term, '%') OR project_description LIKE CONCAT('%', p_search_term, '%'))
    ORDER BY project_name ASC
    LIMIT p_limit;
END$$

-- Delete project (soft delete with cascading)
DROP PROCEDURE IF EXISTS sp_delete_project$$
CREATE PROCEDURE sp_delete_project(
    IN p_project_id VARCHAR(64),
    IN p_deleted_by VARCHAR(64)
)
BEGIN
    -- Soft delete the project
    UPDATE projects
    SET is_active = 0,
        updated_at = NOW()
    WHERE id = p_project_id
      AND is_active = 1;
    
    -- Soft delete all user group project access
    UPDATE user_group_projects
    SET is_active = 0,
        revoked_at = NOW(),
        revoked_by = p_deleted_by
    WHERE project_id = p_project_id
      AND is_active = 1;
    
    -- Soft delete all sessions
    UPDATE user_sessions
    SET is_active = 0
    WHERE project_id = p_project_id
      AND is_active = 1;
    
    -- Note: Deprecated tables removed (user_group_permission_groups, permission_groups, permissions)
    -- These were replaced by the global role system
      
    SELECT ROW_COUNT() as rows_affected;
END$$

-- =====================================================
-- USER PROJECT ACCESS PROCEDURES
-- =====================================================

-- Check user project access
DROP PROCEDURE IF EXISTS sp_check_user_project_access$$
CREATE PROCEDURE sp_check_user_project_access(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT COUNT(*) as has_access
    FROM user_group_members ugm
    INNER JOIN user_group_projects ugp ON ugm.user_group_id = ugp.user_group_id
    WHERE ugm.user_id = p_user_id
      AND ugp.project_id = p_project_id
      AND ugm.is_active = 1
      AND ugp.is_active = 1;
END$$

-- Get user projects
DROP PROCEDURE IF EXISTS sp_get_user_projects$$
CREATE PROCEDURE sp_get_user_projects(
    IN p_user_id VARCHAR(64)
)
BEGIN
    SELECT DISTINCT p.id, p.project_hash, p.project_name, p.project_description, p.project_created, p.is_active
    FROM projects p
    INNER JOIN user_group_projects ugp ON p.id = ugp.project_id
    INNER JOIN user_group_members ugm ON ugp.user_group_id = ugm.user_group_id
    WHERE ugm.user_id = p_user_id
      AND p.is_active = 1
      AND ugp.is_active = 1
      AND ugm.is_active = 1
    ORDER BY p.project_name;
END$$

-- Find default user group for project
DROP PROCEDURE IF EXISTS sp_find_default_user_group_for_project$$
CREATE PROCEDURE sp_find_default_user_group_for_project(
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT ug.id
    FROM user_groups ug
    INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
    WHERE ugp.project_id = p_project_id
      AND ug.group_name LIKE '%user%'
      AND ug.is_active = 1
      AND ugp.is_active = 1
    LIMIT 1;
END$$

-- Revoke user project access
DROP PROCEDURE IF EXISTS sp_revoke_user_project_access$$
CREATE PROCEDURE sp_revoke_user_project_access(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_revoked_by VARCHAR(64),
    OUT p_rows_affected INT
)
BEGIN
    DECLARE done INT DEFAULT FALSE;
    DECLARE v_group_id VARCHAR(64);
    DECLARE cur_groups CURSOR FOR
        SELECT DISTINCT ug.id
        FROM user_groups ug
        INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
        INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
        WHERE ugm.user_id = p_user_id
          AND ugp.project_id = p_project_id
          AND ugm.is_active = 1
          AND ugp.is_active = 1;
    DECLARE CONTINUE HANDLER FOR NOT FOUND SET done = TRUE;
    
    SET p_rows_affected = 0;
    
    OPEN cur_groups;
    
    read_loop: LOOP
        FETCH cur_groups INTO v_group_id;
        IF done THEN
            LEAVE read_loop;
        END IF;
        
        UPDATE user_group_members
        SET is_active = 0,
            removed_at = NOW(),
            removed_by = p_revoked_by
        WHERE user_id = p_user_id
          AND user_group_id = v_group_id
          AND is_active = 1;
        
        SET p_rows_affected = p_rows_affected + ROW_COUNT();
    END LOOP;
    
    CLOSE cur_groups;
END$$

-- =====================================================
-- ADMIN USER MANAGEMENT PROCEDURES
-- =====================================================

-- Get admin assigned projects
DROP PROCEDURE IF EXISTS sp_get_admin_assigned_projects$$
CREATE PROCEDURE sp_get_admin_assigned_projects(
    IN p_user_id VARCHAR(64)
)
BEGIN
    SELECT DISTINCT p.id
    FROM projects p
    INNER JOIN user_group_projects ugp ON p.id = ugp.project_id
    INNER JOIN user_groups ug ON ugp.user_group_id = ug.id
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    WHERE ugm.user_id = p_user_id
      AND p.is_active = 1
      AND ugp.is_active = 1
      AND ug.is_active = 1
      AND ugm.is_active = 1;
END$$

-- Find admin group for project
DROP PROCEDURE IF EXISTS sp_find_admin_group_for_project$$
CREATE PROCEDURE sp_find_admin_group_for_project(
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT ug.id
    FROM user_groups ug
    INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
    WHERE ugp.project_id = p_project_id
      AND ug.group_name LIKE '%admin%'
      AND ug.is_active = 1
      AND ugp.is_active = 1
    LIMIT 1;
END$$

-- Check if user is in group
DROP PROCEDURE IF EXISTS sp_check_user_in_group$$
CREATE PROCEDURE sp_check_user_in_group(
    IN p_user_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64)
)
BEGIN
    SELECT 1 as is_member
    FROM user_group_members ugm
    WHERE ugm.user_id = p_user_id
      AND ugm.user_group_id = p_user_group_id
      AND ugm.is_active = 1
    LIMIT 1;
END$$

-- Get admin project assignments with details
DROP PROCEDURE IF EXISTS sp_get_admin_project_assignments_with_details$$
CREATE PROCEDURE sp_get_admin_project_assignments_with_details(
    IN p_user_id VARCHAR(64)
)
BEGIN
    SELECT DISTINCT 
        p.id as project_id,
        p.project_hash,
        p.project_name,
        p.project_description,
        ugp.granted_at as assigned_at,
        ugp.granted_by as assigned_by,
        ug.group_name as access_through_group
    FROM projects p
    INNER JOIN user_group_projects ugp ON p.id = ugp.project_id
    INNER JOIN user_groups ug ON ugp.user_group_id = ug.id
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    WHERE ugm.user_id = p_user_id
      AND p.is_active = 1
      AND ugp.is_active = 1
      AND ug.is_active = 1
      AND ugm.is_active = 1
    ORDER BY p.project_name;
END$$

-- =====================================================
-- SESSION AND ANALYTICS PROCEDURES
-- =====================================================

-- Get project members
DROP PROCEDURE IF EXISTS sp_get_project_members$$
CREATE PROCEDURE sp_get_project_members(
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT DISTINCT 
        u.id,
        u.user_hash,
        u.username,
        u.email,
        u.user_type,
        u.is_active,
        u.created_at,
        ugp.granted_at,
        ugp.granted_by,
        ug.group_name
    FROM users u
    LEFT JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
    LEFT JOIN user_group_projects ugp ON ugm.user_group_id = ugp.user_group_id AND ugp.project_id = p_project_id AND ugp.is_active = 1
    LEFT JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
    WHERE u.is_active = 1
      AND (
        u.user_type = 'root' OR
        ugp.user_group_id IS NOT NULL
      )
    ORDER BY u.user_type, u.username;
END$$

-- Get recent users count
DROP PROCEDURE IF EXISTS sp_get_recent_users_count$$
CREATE PROCEDURE sp_get_recent_users_count(
    IN p_days INT
)
BEGIN
    SELECT COUNT(*) as count
    FROM users
    WHERE created_at >= DATE_SUB(NOW(), INTERVAL p_days DAY)
      AND is_active = 1;
END$$

-- Get recent projects count
DROP PROCEDURE IF EXISTS sp_get_recent_projects_count$$
CREATE PROCEDURE sp_get_recent_projects_count(
    IN p_days INT
)
BEGIN
    SELECT COUNT(*) as count
    FROM projects
    WHERE project_created >= DATE_SUB(NOW(), INTERVAL p_days DAY)
      AND is_active = 1;
END$$

DELIMITER ;

-- =====================================================
-- SUMMARY
-- =====================================================
SELECT 'Additional stored procedures created successfully!' as status;
