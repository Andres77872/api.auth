-- 07_stored_procedures.sql
-- Stored Procedures for application logic (initial set)
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
-- DEPRECATED RBAC PROCEDURES - REMOVED
-- =====================================================
-- The following procedures have been removed due to the
-- refactor to the global role system. They referenced
-- deprecated tables: permissions, permission_groups,
-- permission_group_permissions, user_group_permission_groups
--
-- Removed procedures:
-- - sp_rbac_create_permission
-- - sp_rbac_get_project_permissions
-- - sp_rbac_check_user_permission
-- - sp_rbac_create_permission_group
-- - sp_rbac_get_project_permission_groups
-- - sp_rbac_assign_permission_to_group
-- - sp_rbac_assign_user_to_permission_group
-- - sp_rbac_remove_user_from_permission_group
-- - sp_rbac_get_user_permission_groups_in_project
-- - sp_rbac_get_user_effective_permissions
-- - sp_rbac_get_group_permissions
-- - sp_rbac_get_group_users
-- - sp_rbac_get_project_users_with_permissions
--
-- Use the global role system instead:
-- - global_permissions
-- - roles
-- - global_permission_groups
-- - role_permission_groups
-- - global_permission_group_permissions
-- =====================================================

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
-- DEPRECATED PROCEDURES - REMOVED
-- =====================================================
-- - sp_rbac_get_project_user_assignments (used user_group_permission_groups)
-- - sp_rbac_get_user_role_assignment_history (used permission_groups)
-- - sp_rbac_count_user_role_assignment_history
-- =====================================================

-- =====================================================
-- ACTIVITY LOGGING PROCEDURES
-- =====================================================

-- =====================================================
-- sp_log_activity
-- -----------------------------------------------------
-- Log an activity with catalog reference
-- =====================================================
DROP PROCEDURE IF EXISTS sp_log_activity$$
CREATE PROCEDURE sp_log_activity(
    IN p_activity_log_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_activity_code VARCHAR(50),
    IN p_details TEXT,
    IN p_project_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64),
    IN p_target_user_id VARCHAR(64),
    IN p_ip_address VARCHAR(45),
    IN p_user_agent TEXT,
    IN p_metadata JSON
)
BEGIN
    DECLARE v_activity_catalog_id VARCHAR(64);
    DECLARE v_severity_level VARCHAR(20);
    
    -- Get catalog info
    SELECT id, severity_level 
    INTO v_activity_catalog_id, v_severity_level
    FROM activity_catalog
    WHERE activity_code = p_activity_code
      AND is_active = 1
    LIMIT 1;
    
    -- Insert activity log
    INSERT INTO activity_logs (
        id, user_id, activity_type, activity_catalog_id, details,
        project_id, user_group_id, target_user_id,
        ip_address, user_agent, metadata, severity_level, created_at
    ) VALUES (
        p_activity_log_id, p_user_id, p_activity_code, v_activity_catalog_id, p_details,
        p_project_id, p_user_group_id, p_target_user_id,
        p_ip_address, p_user_agent, p_metadata, IFNULL(v_severity_level, 'info'), NOW()
    );
END$$

-- =====================================================
-- sp_get_activity_logs
-- -----------------------------------------------------
-- Get activity logs with filtering and pagination
-- =====================================================
DROP PROCEDURE IF EXISTS sp_get_activity_logs$$
CREATE PROCEDURE sp_get_activity_logs(
    IN p_limit INT,
    IN p_offset INT,
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_activity_code VARCHAR(50),
    IN p_days INT
)
BEGIN
    SELECT 
        al.id,
        al.user_id,
        al.activity_type,
        al.details,
        al.project_id,
        al.user_group_id,
        al.target_user_id,
        al.ip_address,
        al.user_agent,
        al.metadata,
        al.severity_level,
        al.created_at,
        u.username,
        u.user_hash,
        p.project_name,
        p.project_hash,
        tu.username as target_username,
        tu.user_hash as target_user_hash,
        ug.group_name as user_group_name,
        ac.activity_name,
        ac.activity_category,
        ac.activity_description
    FROM activity_logs al
    LEFT JOIN users u ON al.user_id = u.id
    LEFT JOIN projects p ON al.project_id = p.id
    LEFT JOIN users tu ON al.target_user_id = tu.id
    LEFT JOIN user_groups ug ON al.user_group_id = ug.id
    LEFT JOIN activity_catalog ac ON al.activity_catalog_id = ac.id
    WHERE al.created_at >= DATE_SUB(NOW(), INTERVAL p_days DAY)
      AND (p_user_id IS NULL OR al.user_id = p_user_id)
      AND (p_project_id IS NULL OR al.project_id = p_project_id)
      AND (p_activity_code IS NULL OR al.activity_type = p_activity_code)
    ORDER BY al.created_at DESC
    LIMIT p_limit OFFSET p_offset;
END$$

-- =====================================================
-- sp_count_activity_logs
-- -----------------------------------------------------
-- Count activity logs with filtering
-- =====================================================
DROP PROCEDURE IF EXISTS sp_count_activity_logs$$
CREATE PROCEDURE sp_count_activity_logs(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_activity_code VARCHAR(50),
    IN p_days INT
)
BEGIN
    SELECT COUNT(*) as total_count
    FROM activity_logs al
    WHERE al.created_at >= DATE_SUB(NOW(), INTERVAL p_days DAY)
      AND (p_user_id IS NULL OR al.user_id = p_user_id)
      AND (p_project_id IS NULL OR al.project_id = p_project_id)
      AND (p_activity_code IS NULL OR al.activity_type = p_activity_code);
END$$

-- =====================================================
-- sp_get_activity_catalog
-- -----------------------------------------------------
-- Get all active activity types from catalog
-- =====================================================
DROP PROCEDURE IF EXISTS sp_get_activity_catalog$$
CREATE PROCEDURE sp_get_activity_catalog(
    IN p_category VARCHAR(50)
)
BEGIN
    IF p_category IS NOT NULL THEN
        SELECT id, activity_code, activity_name, activity_description,
               activity_category, severity_level, requires_audit, is_active
        FROM activity_catalog
        WHERE activity_category = p_category
          AND is_active = 1
        ORDER BY activity_category, activity_name;
    ELSE
        SELECT id, activity_code, activity_name, activity_description,
               activity_category, severity_level, requires_audit, is_active
        FROM activity_catalog
        WHERE is_active = 1
        ORDER BY activity_category, activity_name;
    END IF;
END$$

-- =====================================================
-- sp_get_activity_by_code
-- -----------------------------------------------------
-- Get catalog entry by activity code
-- =====================================================
DROP PROCEDURE IF EXISTS sp_get_activity_by_code$$
CREATE PROCEDURE sp_get_activity_by_code(
    IN p_activity_code VARCHAR(50)
)
BEGIN
    SELECT id, activity_code, activity_name, activity_description,
           activity_category, severity_level, requires_audit, is_active
    FROM activity_catalog
    WHERE activity_code = p_activity_code
      AND is_active = 1
    LIMIT 1;
END$$

-- =====================================================
-- sp_get_activity_stats
-- -----------------------------------------------------
-- Get activity statistics by category
-- =====================================================
DROP PROCEDURE IF EXISTS sp_get_activity_stats$$
CREATE PROCEDURE sp_get_activity_stats(
    IN p_project_id VARCHAR(64),
    IN p_days INT
)
BEGIN
    SELECT 
        ac.activity_category,
        ac.severity_level,
        COUNT(*) as activity_count,
        COUNT(DISTINCT al.user_id) as unique_users
    FROM activity_logs al
    JOIN activity_catalog ac ON al.activity_catalog_id = ac.id
    WHERE al.created_at >= DATE_SUB(NOW(), INTERVAL p_days DAY)
      AND (p_project_id IS NULL OR al.project_id = p_project_id)
    GROUP BY ac.activity_category, ac.severity_level
    ORDER BY activity_count DESC;
END$$

-- =====================================================
-- GLOBAL ROLE SYSTEM PROCEDURES
-- =====================================================

-- =====================================================
-- sp_global_create_role
-- -----------------------------------------------------
-- Create a new global role
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_create_role$$
CREATE PROCEDURE sp_global_create_role(
    IN p_role_id VARCHAR(64),
    IN p_role_hash VARCHAR(255),
    IN p_role_name VARCHAR(100),
    IN p_role_display_name VARCHAR(255),
    IN p_role_description TEXT,
    IN p_role_priority INT,
    IN p_is_system_role BOOLEAN,
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO roles (id, role_hash, role_name, role_display_name, role_description,
                      role_priority, is_system_role, created_by, created_at, is_active)
    VALUES (p_role_id, p_role_hash, p_role_name, p_role_display_name, p_role_description,
            p_role_priority, p_is_system_role, p_created_by, NOW(), TRUE);
    
    SELECT * FROM roles WHERE id = p_role_id;
END$$

-- =====================================================
-- sp_global_get_role_by_hash
-- -----------------------------------------------------
-- Get role by hash
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_get_role_by_hash$$
CREATE PROCEDURE sp_global_get_role_by_hash(
    IN p_role_hash VARCHAR(255)
)
BEGIN
    SELECT * FROM roles WHERE role_hash = p_role_hash AND is_active = TRUE;
END$$

-- =====================================================
-- sp_global_list_roles
-- -----------------------------------------------------
-- List all roles with pagination
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_list_roles$$
CREATE PROCEDURE sp_global_list_roles(
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    SELECT * FROM roles WHERE is_active = TRUE 
    ORDER BY role_priority DESC, role_name ASC 
    LIMIT p_limit OFFSET p_offset;
END$$

-- =====================================================
-- sp_global_update_role
-- -----------------------------------------------------
-- Update role details
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_update_role$$
CREATE PROCEDURE sp_global_update_role(
    IN p_role_id VARCHAR(64),
    IN p_role_display_name VARCHAR(255),
    IN p_role_description TEXT,
    IN p_role_priority INT
)
BEGIN
    UPDATE roles 
    SET role_display_name = COALESCE(p_role_display_name, role_display_name),
        role_description = COALESCE(p_role_description, role_description),
        role_priority = COALESCE(p_role_priority, role_priority),
        updated_at = NOW()
    WHERE id = p_role_id;
    
    SELECT ROW_COUNT() as rows_affected;
END$$

-- =====================================================
-- sp_global_delete_role
-- -----------------------------------------------------
-- Soft delete a role
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_delete_role$$
CREATE PROCEDURE sp_global_delete_role(
    IN p_role_id VARCHAR(64)
)
BEGIN
    UPDATE roles SET is_active = FALSE, updated_at = NOW() WHERE id = p_role_id;
    SELECT ROW_COUNT() as rows_affected;
END$$

-- =====================================================
-- sp_global_create_permission_group
-- -----------------------------------------------------
-- Create a new permission group
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_create_permission_group$$
CREATE PROCEDURE sp_global_create_permission_group(
    IN p_group_id VARCHAR(64),
    IN p_group_hash VARCHAR(255),
    IN p_group_name VARCHAR(100),
    IN p_group_display_name VARCHAR(255),
    IN p_group_description TEXT,
    IN p_group_category VARCHAR(50),
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO global_permission_groups (id, group_hash, group_name, group_display_name,
                                         group_description, group_category, created_by, created_at, is_active)
    VALUES (p_group_id, p_group_hash, p_group_name, p_group_display_name,
            p_group_description, p_group_category, p_created_by, NOW(), TRUE);
    
    SELECT * FROM global_permission_groups WHERE id = p_group_id;
END$$

-- =====================================================
-- sp_global_get_permission_group_by_hash
-- -----------------------------------------------------
-- Get permission group by hash
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_get_permission_group_by_hash$$
CREATE PROCEDURE sp_global_get_permission_group_by_hash(
    IN p_group_hash VARCHAR(255)
)
BEGIN
    SELECT * FROM global_permission_groups WHERE group_hash = p_group_hash AND is_active = TRUE;
END$$

-- =====================================================
-- sp_global_list_permission_groups
-- -----------------------------------------------------
-- List permission groups with optional category filter
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_list_permission_groups$$
CREATE PROCEDURE sp_global_list_permission_groups(
    IN p_category VARCHAR(50),
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    IF p_category IS NOT NULL THEN
        SELECT * FROM global_permission_groups 
        WHERE is_active = TRUE AND group_category = p_category
        ORDER BY group_name ASC LIMIT p_limit OFFSET p_offset;
    ELSE
        SELECT * FROM global_permission_groups WHERE is_active = TRUE 
        ORDER BY group_name ASC LIMIT p_limit OFFSET p_offset;
    END IF;
END$$

-- =====================================================
-- sp_global_create_permission
-- -----------------------------------------------------
-- Create a new global permission
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_create_permission$$
CREATE PROCEDURE sp_global_create_permission(
    IN p_permission_id VARCHAR(64),
    IN p_permission_hash VARCHAR(255),
    IN p_permission_name VARCHAR(100),
    IN p_permission_display_name VARCHAR(255),
    IN p_permission_description TEXT,
    IN p_permission_category VARCHAR(50),
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO global_permissions (id, permission_hash, permission_name, permission_display_name,
                                   permission_description, permission_category, created_by, created_at, is_active)
    VALUES (p_permission_id, p_permission_hash, p_permission_name, p_permission_display_name,
            p_permission_description, p_permission_category, p_created_by, NOW(), TRUE);
    
    SELECT * FROM global_permissions WHERE id = p_permission_id;
END$$

-- =====================================================
-- sp_global_get_permission_by_hash
-- -----------------------------------------------------
-- Get permission by hash
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_get_permission_by_hash$$
CREATE PROCEDURE sp_global_get_permission_by_hash(
    IN p_permission_hash VARCHAR(255)
)
BEGIN
    SELECT * FROM global_permissions WHERE permission_hash = p_permission_hash AND is_active = TRUE;
END$$

-- =====================================================
-- sp_global_list_permissions
-- -----------------------------------------------------
-- List permissions with optional category filter
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_list_permissions$$
CREATE PROCEDURE sp_global_list_permissions(
    IN p_category VARCHAR(50),
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    IF p_category IS NOT NULL THEN
        SELECT * FROM global_permissions 
        WHERE is_active = TRUE AND permission_category = p_category
        ORDER BY permission_name ASC LIMIT p_limit OFFSET p_offset;
    ELSE
        SELECT * FROM global_permissions WHERE is_active = TRUE 
        ORDER BY permission_name ASC LIMIT p_limit OFFSET p_offset;
    END IF;
END$$

-- =====================================================
-- sp_global_assign_permission_group_to_role
-- -----------------------------------------------------
-- Assign a permission group to a role
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_assign_permission_group_to_role$$
CREATE PROCEDURE sp_global_assign_permission_group_to_role(
    IN p_link_id VARCHAR(64),
    IN p_role_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64),
    IN p_assigned_by VARCHAR(64)
)
BEGIN
    INSERT INTO role_permission_groups (id, role_id, permission_group_id, assigned_by, assigned_at, is_active)
    VALUES (p_link_id, p_role_id, p_permission_group_id, p_assigned_by, NOW(), TRUE)
    ON DUPLICATE KEY UPDATE is_active = TRUE, assigned_at = NOW(), assigned_by = p_assigned_by;
    
    SELECT ROW_COUNT() as rows_affected;
END$$

-- =====================================================
-- sp_global_get_role_permission_groups
-- -----------------------------------------------------
-- Get permission groups for a role
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_get_role_permission_groups$$
CREATE PROCEDURE sp_global_get_role_permission_groups(
    IN p_role_id VARCHAR(64)
)
BEGIN
    SELECT gpg.* FROM global_permission_groups gpg
    JOIN role_permission_groups rpg ON gpg.id = rpg.permission_group_id
    WHERE rpg.role_id = p_role_id AND rpg.is_active = TRUE AND gpg.is_active = TRUE
    ORDER BY gpg.group_name;
END$$

-- =====================================================
-- sp_global_assign_permission_to_group
-- -----------------------------------------------------
-- Assign a permission to a permission group
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_assign_permission_to_group$$
CREATE PROCEDURE sp_global_assign_permission_to_group(
    IN p_link_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64),
    IN p_permission_id VARCHAR(64),
    IN p_granted_by VARCHAR(64)
)
BEGIN
    INSERT INTO global_permission_group_permissions (id, permission_group_id, permission_id, granted_by, granted_at, is_active)
    VALUES (p_link_id, p_permission_group_id, p_permission_id, p_granted_by, NOW(), TRUE)
    ON DUPLICATE KEY UPDATE is_active = TRUE, granted_at = NOW(), granted_by = p_granted_by;
    
    SELECT ROW_COUNT() as rows_affected;
END$$

-- =====================================================
-- sp_global_get_permission_group_permissions
-- -----------------------------------------------------
-- Get permissions in a permission group
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_get_permission_group_permissions$$
CREATE PROCEDURE sp_global_get_permission_group_permissions(
    IN p_permission_group_id VARCHAR(64)
)
BEGIN
    SELECT gp.* FROM global_permissions gp
    JOIN global_permission_group_permissions pgp ON gp.id = pgp.permission_id
    WHERE pgp.permission_group_id = p_permission_group_id AND pgp.is_active = TRUE AND gp.is_active = TRUE
    ORDER BY gp.permission_name;
END$$

-- =====================================================
-- sp_global_assign_role_to_user
-- -----------------------------------------------------
-- Assign a role to a user
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_assign_role_to_user$$
CREATE PROCEDURE sp_global_assign_role_to_user(
    IN p_user_id VARCHAR(64),
    IN p_role_id VARCHAR(64)
)
BEGIN
    UPDATE users SET role_id = p_role_id, updated_at = NOW() WHERE id = p_user_id;
    SELECT ROW_COUNT() as rows_affected;
END$$

-- =====================================================
-- sp_global_get_user_role
-- -----------------------------------------------------
-- Get the role assigned to a user
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_get_user_role$$
CREATE PROCEDURE sp_global_get_user_role(
    IN p_user_id VARCHAR(64)
)
BEGIN
    SELECT r.* FROM roles r
    JOIN users u ON r.id = u.role_id
    WHERE u.id = p_user_id AND u.is_active = TRUE AND r.is_active = TRUE;
END$$

-- =====================================================
-- sp_global_get_user_permissions
-- -----------------------------------------------------
-- Get all permissions for a user (GLOBAL - no project context)
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_get_user_permissions$$
CREATE PROCEDURE sp_global_get_user_permissions(
    IN p_user_id VARCHAR(64)
)
BEGIN
    SELECT DISTINCT gp.permission_name, gp.permission_display_name, gp.permission_category
    FROM users u
    JOIN roles r ON u.role_id = r.id AND r.is_active = TRUE
    JOIN role_permission_groups rpg ON r.id = rpg.role_id AND rpg.is_active = TRUE
    JOIN global_permission_group_permissions pgp ON rpg.permission_group_id = pgp.permission_group_id AND pgp.is_active = TRUE
    JOIN global_permissions gp ON pgp.permission_id = gp.id AND gp.is_active = TRUE
    WHERE u.id = p_user_id AND u.is_active = TRUE
    ORDER BY gp.permission_category, gp.permission_name;
END$$

-- =====================================================
-- sp_global_check_user_has_permission
-- -----------------------------------------------------
-- Check if user has a specific permission (GLOBAL)
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_check_user_has_permission$$
CREATE PROCEDURE sp_global_check_user_has_permission(
    IN p_user_id VARCHAR(64),
    IN p_permission_name VARCHAR(100)
)
BEGIN
    SELECT EXISTS(
        SELECT 1 FROM users u
        JOIN roles r ON u.role_id = r.id AND r.is_active = TRUE
        JOIN role_permission_groups rpg ON r.id = rpg.role_id AND rpg.is_active = TRUE
        JOIN global_permission_group_permissions pgp ON rpg.permission_group_id = pgp.permission_group_id AND pgp.is_active = TRUE
        JOIN global_permissions gp ON pgp.permission_id = gp.id AND gp.is_active = TRUE
        WHERE u.id = p_user_id AND gp.permission_name = p_permission_name AND u.is_active = TRUE
    ) as has_permission;
END$$

-- =====================================================
-- sp_global_add_role_to_project_catalog
-- -----------------------------------------------------
-- Add role to project catalog (METADATA ONLY)
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_add_role_to_project_catalog$$
CREATE PROCEDURE sp_global_add_role_to_project_catalog(
    IN p_catalog_id VARCHAR(64),
    IN p_role_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_catalog_purpose VARCHAR(255),
    IN p_notes TEXT,
    IN p_added_by VARCHAR(64)
)
BEGIN
    INSERT INTO role_project_catalog (id, role_id, project_id, catalog_purpose, notes, added_by, added_at, is_active)
    VALUES (p_catalog_id, p_role_id, p_project_id, p_catalog_purpose, p_notes, p_added_by, NOW(), TRUE)
    ON DUPLICATE KEY UPDATE is_active = TRUE, added_at = NOW(), catalog_purpose = p_catalog_purpose, notes = p_notes;
    
    SELECT ROW_COUNT() as rows_affected;
END$$

-- =====================================================
-- sp_global_get_project_cataloged_roles
-- -----------------------------------------------------
-- Get roles cataloged for a project (METADATA - for UI suggestions only)
-- =====================================================
DROP PROCEDURE IF EXISTS sp_global_get_project_cataloged_roles$$
CREATE PROCEDURE sp_global_get_project_cataloged_roles(
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT r.*, rpc.catalog_purpose, rpc.notes 
    FROM roles r
    JOIN role_project_catalog rpc ON r.id = rpc.role_id
    WHERE rpc.project_id = p_project_id AND rpc.is_active = TRUE AND r.is_active = TRUE
    ORDER BY r.role_priority DESC, r.role_name;
END$$

DELIMITER ; 