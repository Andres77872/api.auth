-- 07_stored_procedures.sql
-- Stored Procedures for application logic (initial set)
-- MySQL Database

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

DELIMITER $$

-- =====================================================
-- sp_list_users
-- -----------------------------------------------------
-- Returns a paginated list of users with optional
-- filtering by search term, user type, group, project
-- and active status. This procedure is designed to
-- replace the dynamic SQL previously constructed in
-- the application layer.
-- =====================================================
DROP PROCEDURE IF EXISTS sp_list_users$$
CREATE PROCEDURE sp_list_users(
    IN p_limit INT,
    IN p_offset INT,
    IN p_sort_by VARCHAR(50),
    IN p_sort_order VARCHAR(4),
    IN p_search VARCHAR(255),
    IN p_user_type_filter VARCHAR(20),
    IN p_group_filter VARCHAR(255),
    IN p_project_filter VARCHAR(255),
    IN p_include_inactive BOOLEAN
)
BEGIN
    -- Validate / normalise sort column & direction --------------------------------------
    SET @sort_col := CASE LOWER(p_sort_by)
        WHEN 'created_at'  THEN 'u.created_at'
        WHEN 'email'       THEN 'u.email'
        WHEN 'user_type'   THEN 'u.user_type'
        ELSE 'u.username' END;

    SET @dir := IF(LOWER(p_sort_order) = 'desc', 'DESC', 'ASC');

    -- Base query ------------------------------------------------------------------------
    SET @sql := CONCAT('SELECT u.id,
                               u.user_hash,
                               u.username,
                               u.email,
                               u.password_hash,
                               u.user_type,
                               u.created_at,
                               u.is_active
                        FROM users u ');

    -- Conditional joins -----------------------------------------------------------------
    IF p_group_filter IS NOT NULL OR p_project_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql,
            'LEFT JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1\n',
            'LEFT JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1\n');
    END IF;

    IF p_project_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql,
            'LEFT JOIN user_group_projects ugp ON ug.id = ugp.user_group_id AND ugp.is_active = 1\n',
            'LEFT JOIN projects p ON ugp.project_id = p.id AND p.is_active = 1\n');
    END IF;

    -- WHERE clause ----------------------------------------------------------------------
    SET @sql := CONCAT(@sql, 'WHERE 1=1 ');

    IF p_include_inactive = FALSE THEN
        SET @sql := CONCAT(@sql, 'AND u.is_active = 1 ');
    END IF;

    IF p_search IS NOT NULL THEN
        SET @sql := CONCAT(@sql, 'AND (u.username LIKE ', QUOTE(CONCAT('%', p_search, '%')),
                                         ' OR u.email LIKE ', QUOTE(CONCAT('%', p_search, '%')), ') ');
    END IF;

    IF p_user_type_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql, 'AND u.user_type = ', QUOTE(p_user_type_filter), ' ');
    END IF;

    IF p_group_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql, 'AND (ug.group_name = ', QUOTE(p_group_filter),
                                         ' OR ug.group_hash = ', QUOTE(p_group_filter), ') ');
    END IF;

    IF p_project_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql, 'AND (p.project_name = ', QUOTE(p_project_filter),
                                         ' OR p.project_hash = ', QUOTE(p_project_filter), ') ');
    END IF;

    -- Final ordering & pagination -------------------------------------------------------
    SET @sql := CONCAT(@sql, 'GROUP BY u.id ORDER BY ', @sort_col, ' ', @dir,
                       ' LIMIT ', p_limit, ' OFFSET ', p_offset);

    -- Execute ---------------------------------------------------------------------------
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
END$$

-- =====================================================
-- sp_user_login
-- -----------------------------------------------------
-- Fetch a single active user by username OR email.
-- This lightweight procedure is used by the application
-- layer for authentication. It returns only the fields
-- required for login so that password verification and
-- any post-processing can be done in Python.
-- =====================================================
DROP PROCEDURE IF EXISTS sp_user_login$$
CREATE PROCEDURE sp_user_login(
    IN p_username_email VARCHAR(255)
)
BEGIN
    SELECT id,
           user_hash,
           username,
           email,
           password_hash,
           user_type,
           created_at,
           is_active
    FROM users
    WHERE is_active = 1
      AND (username = p_username_email OR email = p_username_email)
    LIMIT 1;
END$$

-- =====================================================
-- sp_get_user_accessible_projects
-- -----------------------------------------------------
-- Return list of projects the specified user can access
-- based on their user groups. Root users automatically
-- receive access to all active projects.
-- =====================================================
DROP PROCEDURE IF EXISTS sp_get_user_accessible_projects$$
CREATE PROCEDURE sp_get_user_accessible_projects(
    IN p_user_id VARCHAR(64)
)
BEGIN
    DECLARE v_user_type VARCHAR(20);

    -- Determine user type
    SELECT user_type
    INTO v_user_type
    FROM users
    WHERE id = p_user_id
      AND is_active = 1;

    -- Root users: all projects
    IF v_user_type = 'root' THEN
        SELECT p.id,
               p.project_hash,
               p.project_name,
               p.project_description
        FROM projects p
        WHERE p.is_active = 1
        ORDER BY p.project_name;
    ELSE
        -- Admin / consumer users: via group memberships
        SELECT DISTINCT p.id,
                        p.project_hash,
                        p.project_name,
                        p.project_description
        FROM user_group_members ugm
                 JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
                 JOIN user_group_projects ugp ON ug.id = ugp.user_group_id AND ugp.is_active = 1
                 JOIN projects p ON ugp.project_id = p.id AND p.is_active = 1
        WHERE ugm.user_id = p_user_id
          AND ugm.is_active = 1
        ORDER BY p.project_name;
    END IF;
END$$

-- =====================================================
-- sp_list_users_with_access
-- -----------------------------------------------------
-- Returns a paginated list of users together with aggregated
-- group memberships and accessible projects using JSON.
-- =====================================================
DROP PROCEDURE IF EXISTS sp_list_users_with_access$$
CREATE PROCEDURE sp_list_users_with_access(
    IN p_limit INT,
    IN p_offset INT,
    IN p_sort_by VARCHAR(50),
    IN p_sort_order VARCHAR(4),
    IN p_search VARCHAR(255),
    IN p_user_type_filter VARCHAR(20),
    IN p_group_filter VARCHAR(255),
    IN p_project_filter VARCHAR(255),
    IN p_include_inactive BOOLEAN
)
BEGIN
    -- Validate / normalise sort parameters ----------------------------------
    SET @sort_col := CASE LOWER(p_sort_by)
        WHEN 'created_at'   THEN 'u.created_at'
        WHEN 'email'        THEN 'u.email'
        WHEN 'user_type'    THEN 'u.user_type'
        ELSE 'u.username' END;

    SET @dir := IF(LOWER(p_sort_order) = 'desc', 'DESC', 'ASC');

    -- Base query ------------------------------------------------------------
    SET @sql := CONCAT('SELECT
                           u.id,
                           u.user_hash,
                           u.username,
                           u.email,
                           u.user_type,
                           u.created_at,
                           NULL AS last_login,
                           u.is_active,
                           IFNULL(CONCAT("[", GROUP_CONCAT(DISTINCT JSON_OBJECT(''group_hash'', COALESCE(ug.group_hash, ''''), ''group_name'', COALESCE(ug.group_name, ''''), ''group_description'', COALESCE(ug.group_description, '''')) SEPARATOR ","), "]"), "[]") AS groups_json,
                           IFNULL(CONCAT("[", GROUP_CONCAT(DISTINCT JSON_OBJECT(''project_hash'', COALESCE(p.project_hash, ''''), ''project_name'', COALESCE(p.project_name, '''')) SEPARATOR ","), "]"), "[]") AS projects_json
                       FROM users u
                       LEFT JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
                       LEFT JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
                       LEFT JOIN user_group_projects ugp ON ug.id = ugp.user_group_id AND ugp.is_active = 1
                       LEFT JOIN projects p ON ugp.project_id = p.id AND p.is_active = 1
                       WHERE 1=1 ');

    -- Conditional filters ---------------------------------------------------
    IF p_include_inactive = FALSE THEN
        SET @sql := CONCAT(@sql, 'AND u.is_active = 1 ');
    END IF;

    IF p_search IS NOT NULL THEN
        SET @sql := CONCAT(@sql,
            'AND (u.username LIKE ', QUOTE(CONCAT('%', p_search, '%')),
            ' OR u.email LIKE ', QUOTE(CONCAT('%', p_search, '%')), ') ');
    END IF;

    IF p_user_type_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql, 'AND u.user_type = ', QUOTE(p_user_type_filter), ' ');
    END IF;

    IF p_group_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql,
            'AND (ug.group_name = ', QUOTE(p_group_filter),
            ' OR ug.group_hash = ', QUOTE(p_group_filter), ') ');
    END IF;

    IF p_project_filter IS NOT NULL THEN
        SET @sql := CONCAT(@sql,
            'AND (p.project_name = ', QUOTE(p_project_filter),
            ' OR p.project_hash = ', QUOTE(p_project_filter), ') ');
    END IF;

    -- Final grouping, ordering, pagination ----------------------------------
    SET @sql := CONCAT(@sql,
        'GROUP BY u.id ORDER BY ', @sort_col, ' ', @dir,
        ' LIMIT ', p_limit, ' OFFSET ', p_offset);

    -- Execute ----------------------------------------------------------------
    PREPARE stmt FROM @sql;
    EXECUTE stmt;
    DEALLOCATE PREPARE stmt;
END$$

-- =====================================================
-- RBAC STORED PROCEDURES
-- =====================================================

-- =====================================================
-- sp_rbac_create_permission
-- -----------------------------------------------------
-- Create a new project-specific permission
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_create_permission$$
CREATE PROCEDURE sp_rbac_create_permission(
    IN p_permission_id VARCHAR(64),
    IN p_permission_hash VARCHAR(255),
    IN p_project_id VARCHAR(64),
    IN p_permission_name VARCHAR(100),
    IN p_permission_display_name VARCHAR(255),
    IN p_permission_description TEXT,
    IN p_permission_category VARCHAR(50),
    IN p_is_system_permission BOOLEAN,
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO permissions (
        id, permission_hash, project_id, permission_name, 
        permission_display_name, permission_description, 
        permission_category, is_system_permission, created_by
    ) VALUES (
        p_permission_id, p_permission_hash, p_project_id, p_permission_name,
        p_permission_display_name, p_permission_description,
        p_permission_category, p_is_system_permission, p_created_by
    );
    
    SELECT id, permission_hash, project_id, permission_name,
           permission_display_name, permission_description,
           permission_category, is_system_permission,
           created_at, updated_at, created_by, is_active
    FROM permissions
    WHERE id = p_permission_id;
END$$

-- =====================================================
-- sp_rbac_get_project_permissions
-- -----------------------------------------------------
-- Get all permissions for a project
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_get_project_permissions$$
CREATE PROCEDURE sp_rbac_get_project_permissions(
    IN p_project_id VARCHAR(64),
    IN p_category VARCHAR(50)
)
BEGIN
    IF p_category IS NOT NULL THEN
        SELECT id, permission_hash, project_id, permission_name,
               permission_display_name, permission_description,
               permission_category, is_system_permission,
               created_at, updated_at, created_by, is_active
        FROM permissions
        WHERE project_id = p_project_id
          AND permission_category = p_category
          AND is_active = 1
        ORDER BY permission_category, permission_name;
    ELSE
        SELECT id, permission_hash, project_id, permission_name,
               permission_display_name, permission_description,
               permission_category, is_system_permission,
               created_at, updated_at, created_by, is_active
        FROM permissions
        WHERE project_id = p_project_id
          AND is_active = 1
        ORDER BY permission_category, permission_name;
    END IF;
END$$

-- =====================================================
-- sp_rbac_check_user_permission
-- -----------------------------------------------------
-- Check if user has specific permission in project
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_check_user_permission$$
CREATE PROCEDURE sp_rbac_check_user_permission(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_permission_name VARCHAR(100)
)
BEGIN
    SELECT COUNT(*) > 0 as has_permission
    FROM permissions p
    JOIN permission_group_permissions pgp ON p.id = pgp.permission_id
    JOIN permission_groups pg ON pgp.permission_group_id = pg.id
    JOIN user_group_permission_groups ugpg ON pg.id = ugpg.permission_group_id
    JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id
    WHERE ugm.user_id = p_user_id
      AND ugpg.project_id = p_project_id
      AND p.permission_name = p_permission_name
      AND p.is_active = 1
      AND pgp.is_active = 1
      AND pg.is_active = 1
      AND ugpg.is_active = 1
      AND ugm.is_active = 1;
END$$

-- =====================================================
-- sp_rbac_create_permission_group
-- -----------------------------------------------------
-- Create a new permission group (role)
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_create_permission_group$$
CREATE PROCEDURE sp_rbac_create_permission_group(
    IN p_group_id VARCHAR(64),
    IN p_group_hash VARCHAR(255),
    IN p_project_id VARCHAR(64),
    IN p_group_name VARCHAR(100),
    IN p_group_display_name VARCHAR(255),
    IN p_group_description TEXT,
    IN p_group_priority INT,
    IN p_is_system_role BOOLEAN,
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO permission_groups (
        id, group_hash, project_id, group_name,
        group_display_name, group_description,
        group_priority, is_system_role, created_by
    ) VALUES (
        p_group_id, p_group_hash, p_project_id, p_group_name,
        p_group_display_name, p_group_description,
        p_group_priority, p_is_system_role, p_created_by
    );
    
    SELECT id, group_hash, project_id, group_name,
           group_display_name, group_description,
           group_priority, is_system_role,
           created_at, updated_at, created_by, is_active
    FROM permission_groups
    WHERE id = p_group_id;
END$$

-- =====================================================
-- sp_rbac_get_project_permission_groups
-- -----------------------------------------------------
-- Get all permission groups for a project
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_get_project_permission_groups$$
CREATE PROCEDURE sp_rbac_get_project_permission_groups(
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT id, group_hash, project_id, group_name,
           group_display_name, group_description,
           group_priority, is_system_role,
           created_at, updated_at, created_by, is_active
    FROM permission_groups
    WHERE project_id = p_project_id
      AND is_active = 1
    ORDER BY group_priority DESC, group_name;
END$$

-- =====================================================
-- sp_rbac_assign_permission_to_group
-- -----------------------------------------------------
-- Assign a permission to a permission group
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_assign_permission_to_group$$
CREATE PROCEDURE sp_rbac_assign_permission_to_group(
    IN p_link_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64),
    IN p_permission_id VARCHAR(64),
    IN p_assigned_by VARCHAR(64),
    OUT p_success BOOLEAN
)
BEGIN
    DECLARE v_pg_project_id VARCHAR(64);
    DECLARE v_perm_project_id VARCHAR(64);
    DECLARE CONTINUE HANDLER FOR SQLEXCEPTION SET p_success = FALSE;
    
    SET p_success = TRUE;
    
    -- Verify both belong to same project
    SELECT pg.project_id, p.project_id
    INTO v_pg_project_id, v_perm_project_id
    FROM permission_groups pg, permissions p
    WHERE pg.id = p_permission_group_id
      AND p.id = p_permission_id;
    
    IF v_pg_project_id != v_perm_project_id THEN
        SET p_success = FALSE;
    ELSE
        INSERT INTO permission_group_permissions (
            id, permission_group_id, permission_id, granted_by
        ) VALUES (
            p_link_id, p_permission_group_id, p_permission_id, p_assigned_by
        )
        ON DUPLICATE KEY UPDATE
            is_active = 1,
            revoked_at = NULL,
            revoked_by = NULL,
            granted_by = p_assigned_by;
    END IF;
END$$

-- =====================================================
-- sp_rbac_assign_user_to_permission_group
-- -----------------------------------------------------
-- Assign user to permission group through user groups
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_assign_user_to_permission_group$$
CREATE PROCEDURE sp_rbac_assign_user_to_permission_group(
    IN p_assignment_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64),
    IN p_assigned_by VARCHAR(64),
    OUT p_success BOOLEAN,
    OUT p_error_message VARCHAR(255)
)
BEGIN
    DECLARE v_pg_project_id VARCHAR(64);
    DECLARE v_user_group_id VARCHAR(64);
    DECLARE CONTINUE HANDLER FOR SQLEXCEPTION 
    BEGIN
        SET p_success = FALSE;
        SET p_error_message = 'Database error occurred';
    END;
    
    SET p_success = TRUE;
    SET p_error_message = NULL;
    
    -- Verify permission group belongs to project
    SELECT project_id INTO v_pg_project_id
    FROM permission_groups
    WHERE id = p_permission_group_id AND is_active = 1;
    
    IF v_pg_project_id IS NULL THEN
        SET p_success = FALSE;
        SET p_error_message = 'Permission group not found or inactive';
    ELSEIF v_pg_project_id != p_project_id THEN
        SET p_success = FALSE;
        SET p_error_message = 'Permission group does not belong to specified project';
    ELSE
        -- Get user's user group with project access
        SELECT ug.id INTO v_user_group_id
        FROM user_groups ug
        JOIN user_group_members ugm ON ug.id = ugm.user_group_id
        JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
        WHERE ugm.user_id = p_user_id
          AND ugp.project_id = p_project_id
          AND ugm.is_active = 1
          AND ug.is_active = 1
          AND ugp.is_active = 1
        LIMIT 1;
        
        IF v_user_group_id IS NULL THEN
            SET p_success = FALSE;
            SET p_error_message = 'User does not belong to any user group with access to this project';
        ELSE
            INSERT INTO user_group_permission_groups (
                id, user_group_id, project_id, permission_group_id, assigned_by
            ) VALUES (
                p_assignment_id, v_user_group_id, p_project_id, p_permission_group_id, p_assigned_by
            )
            ON DUPLICATE KEY UPDATE
                is_active = 1,
                removed_at = NULL,
                removed_by = NULL,
                assigned_by = p_assigned_by;
        END IF;
    END IF;
END$$

-- =====================================================
-- sp_rbac_remove_user_from_permission_group
-- -----------------------------------------------------
-- Remove user from permission group
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_remove_user_from_permission_group$$
CREATE PROCEDURE sp_rbac_remove_user_from_permission_group(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64),
    IN p_removed_by VARCHAR(64),
    OUT p_rows_affected INT
)
BEGIN
    UPDATE user_group_permission_groups ugpg
    JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id
    SET ugpg.is_active = 0,
        ugpg.removed_at = NOW(),
        ugpg.removed_by = p_removed_by
    WHERE ugm.user_id = p_user_id
      AND ugpg.project_id = p_project_id
      AND ugpg.permission_group_id = p_permission_group_id
      AND ugpg.is_active = 1
      AND ugm.is_active = 1;
    
    SET p_rows_affected = ROW_COUNT();
END$$

-- =====================================================
-- sp_rbac_get_user_permission_groups_in_project
-- -----------------------------------------------------
-- Get user's permission groups in a project
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_get_user_permission_groups_in_project$$
CREATE PROCEDURE sp_rbac_get_user_permission_groups_in_project(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT pg.id, pg.group_hash, pg.project_id, pg.group_name,
           pg.group_display_name, pg.group_description,
           pg.group_priority, pg.is_system_role,
           pg.created_at, pg.updated_at, pg.created_by, pg.is_active,
           ugpg.assigned_at
    FROM permission_groups pg
    JOIN user_group_permission_groups ugpg ON pg.id = ugpg.permission_group_id
    JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id
    WHERE ugm.user_id = p_user_id
      AND ugpg.project_id = p_project_id
      AND pg.is_active = 1
      AND ugpg.is_active = 1
      AND ugm.is_active = 1
    ORDER BY pg.group_priority DESC, pg.group_name;
END$$

-- =====================================================
-- sp_rbac_get_user_effective_permissions
-- -----------------------------------------------------
-- Get all effective permissions for user in project
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_get_user_effective_permissions$$
CREATE PROCEDURE sp_rbac_get_user_effective_permissions(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT DISTINCT p.id, p.permission_hash, p.project_id,
           p.permission_name, p.permission_display_name,
           p.permission_description, p.permission_category,
           p.is_system_permission, p.created_at, p.updated_at,
           p.created_by, p.is_active,
           pg.group_name as granted_through_role
    FROM permissions p
    JOIN permission_group_permissions pgp ON p.id = pgp.permission_id
    JOIN permission_groups pg ON pgp.permission_group_id = pg.id
    JOIN user_group_permission_groups ugpg ON pg.id = ugpg.permission_group_id
    JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id
    WHERE ugm.user_id = p_user_id
      AND ugpg.project_id = p_project_id
      AND p.is_active = 1
      AND pgp.is_active = 1
      AND pg.is_active = 1
      AND ugpg.is_active = 1
      AND ugm.is_active = 1
    ORDER BY p.permission_category, p.permission_name;
END$$

-- =====================================================
-- sp_rbac_get_group_permissions
-- -----------------------------------------------------
-- Get all permissions assigned to a role
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_get_group_permissions$$
CREATE PROCEDURE sp_rbac_get_group_permissions(
    IN p_permission_group_id VARCHAR(64)
)
BEGIN
    SELECT p.id, p.permission_hash, p.project_id,
           p.permission_name, p.permission_display_name,
           p.permission_description, p.permission_category,
           p.is_system_permission, p.created_at, p.updated_at,
           p.created_by, p.is_active
    FROM permissions p
    JOIN permission_group_permissions pgp ON p.id = pgp.permission_id
    WHERE pgp.permission_group_id = p_permission_group_id
      AND p.is_active = 1
      AND pgp.is_active = 1
    ORDER BY p.permission_category, p.permission_name;
END$$

-- =====================================================
-- sp_rbac_get_group_users
-- -----------------------------------------------------
-- Get all users assigned to a role
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_get_group_users$$
CREATE PROCEDURE sp_rbac_get_group_users(
    IN p_permission_group_id VARCHAR(64)
)
BEGIN
    SELECT DISTINCT u.id, u.user_hash, u.username, u.email, u.user_type,
           ug.group_name as user_group_name,
           ugpg.assigned_at
    FROM users u
    JOIN user_group_members ugm ON u.id = ugm.user_id
    JOIN user_groups ug ON ugm.user_group_id = ug.id
    JOIN user_group_permission_groups ugpg ON ug.id = ugpg.user_group_id
    WHERE ugpg.permission_group_id = p_permission_group_id
      AND u.is_active = 1
      AND ugm.is_active = 1
      AND ug.is_active = 1
      AND ugpg.is_active = 1
    ORDER BY u.username;
END$$

-- =====================================================
-- sp_rbac_get_project_users_with_permissions
-- -----------------------------------------------------
-- Get all users with permissions in a project
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_get_project_users_with_permissions$$
CREATE PROCEDURE sp_rbac_get_project_users_with_permissions(
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT DISTINCT u.id, u.user_hash, u.username, u.email, u.user_type,
           COUNT(DISTINCT p.id) as permission_count,
           COUNT(DISTINCT pg.id) as role_count,
           GROUP_CONCAT(DISTINCT pg.group_name ORDER BY pg.group_priority DESC SEPARATOR ', ') as roles
    FROM users u
    JOIN user_group_members ugm ON u.id = ugm.user_id
    JOIN user_groups ug ON ugm.user_group_id = ug.id
    JOIN user_group_permission_groups ugpg ON ug.id = ugpg.user_group_id
    JOIN permission_groups pg ON ugpg.permission_group_id = pg.id
    LEFT JOIN permission_group_permissions pgp ON pg.id = pgp.permission_group_id
    LEFT JOIN permissions p ON pgp.permission_id = p.id AND p.is_active = 1
    WHERE ugpg.project_id = p_project_id
      AND u.is_active = 1
      AND ugm.is_active = 1
      AND ug.is_active = 1
      AND ugpg.is_active = 1
      AND pg.is_active = 1
    GROUP BY u.id, u.user_hash, u.username, u.email, u.user_type
    ORDER BY u.username;
END$$

-- =====================================================
-- sp_rbac_get_project_audit_log
-- -----------------------------------------------------
-- Get audit log for a project
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_get_project_audit_log$$
CREATE PROCEDURE sp_rbac_get_project_audit_log(
    IN p_project_id VARCHAR(64),
    IN p_action_type VARCHAR(50),
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    IF p_action_type IS NOT NULL THEN
        SELECT id, action_type, table_name, record_id,
               old_values, new_values, performed_by,
               performed_at, ip_address, user_agent, project_id
        FROM permission_audit_log
        WHERE project_id = p_project_id
          AND action_type = p_action_type
        ORDER BY performed_at DESC
        LIMIT p_limit OFFSET p_offset;
    ELSE
        SELECT id, action_type, table_name, record_id,
               old_values, new_values, performed_by,
               performed_at, ip_address, user_agent, project_id
        FROM permission_audit_log
        WHERE project_id = p_project_id
        ORDER BY performed_at DESC
        LIMIT p_limit OFFSET p_offset;
    END IF;
END$$

-- =====================================================
-- sp_rbac_get_project_user_assignments
-- -----------------------------------------------------
-- Get user role assignment statistics for a project
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_get_project_user_assignments$$
CREATE PROCEDURE sp_rbac_get_project_user_assignments(
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT COUNT(DISTINCT ugm.user_id) as total_users,
           COUNT(*) as total_assignments
    FROM user_group_permission_groups ugpg
    JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id
    WHERE ugpg.project_id = p_project_id
      AND ugpg.is_active = 1
      AND ugm.is_active = 1;
END$$

-- =====================================================
-- sp_rbac_get_user_role_assignment_history
-- -----------------------------------------------------
-- Get role assignment history for a user
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_get_user_role_assignment_history$$
CREATE PROCEDURE sp_rbac_get_user_role_assignment_history(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    SELECT pal.id, pal.action_type, pal.permission_group_id,
           pg.group_name, pg.group_description,
           pal.performed_by,
           u.username as performed_by_username,
           u.user_hash as performed_by_hash,
           pal.performed_at, pal.old_values, pal.new_values,
           pal.ip_address
    FROM permission_audit_log pal
    LEFT JOIN permission_groups pg ON pal.permission_group_id = pg.id
    LEFT JOIN users u ON pal.performed_by = u.id
    WHERE pal.target_user_id = p_user_id
      AND pal.project_id = p_project_id
      AND pal.action_type IN ('ASSIGN_ROLE', 'REMOVE_ROLE')
    ORDER BY pal.performed_at DESC
    LIMIT p_limit OFFSET p_offset;
END$$

-- =====================================================
-- sp_rbac_count_user_role_assignment_history
-- -----------------------------------------------------
-- Count role assignment history entries
-- =====================================================
DROP PROCEDURE IF EXISTS sp_rbac_count_user_role_assignment_history$$
CREATE PROCEDURE sp_rbac_count_user_role_assignment_history(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT COUNT(*) as total_count
    FROM permission_audit_log
    WHERE target_user_id = p_user_id
      AND project_id = p_project_id
      AND action_type IN ('ASSIGN_ROLE', 'REMOVE_ROLE');
END$$

DELIMITER ; 