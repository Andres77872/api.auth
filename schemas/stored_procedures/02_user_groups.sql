-- ===================================================================================
-- USER GROUP MANAGEMENT STORED PROCEDURES
-- GROUPS OF GROUPS Architecture
-- ===================================================================================
-- This file contains all stored procedures related to user group management:
-- - User group CRUD operations
-- - User group membership management
-- - User group → Project group access (groups of groups)
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- USER GROUP CRUD OPERATIONS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_create_user_group$$
CREATE PROCEDURE sp_create_user_group(
    IN p_group_id VARCHAR(64),
    IN p_group_hash VARCHAR(255),
    IN p_group_name VARCHAR(100),
    IN p_group_description TEXT,
    IN p_parent_group_id VARCHAR(64),
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO user_groups (id, group_hash, group_name, group_description, parent_group_id, created_by, created_at)
    VALUES (p_group_id, p_group_hash, p_group_name, p_group_description, p_parent_group_id, p_created_by, NOW());
END$$

DROP PROCEDURE IF EXISTS sp_get_user_group_by_id$$
CREATE PROCEDURE sp_get_user_group_by_id(IN p_group_id VARCHAR(64))
BEGIN
    SELECT id, group_hash, group_name, group_description, parent_group_id, created_at, updated_at, created_by, is_active
    FROM user_groups WHERE id = p_group_id AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_group_by_hash$$
CREATE PROCEDURE sp_get_user_group_by_hash(IN p_group_hash VARCHAR(255))
BEGIN
    SELECT id, group_hash, group_name, group_description, parent_group_id, created_at, updated_at, created_by, is_active
    FROM user_groups WHERE group_hash = p_group_hash AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_group_by_name$$
CREATE PROCEDURE sp_get_user_group_by_name(IN p_group_name VARCHAR(100))
BEGIN
    SELECT id, group_hash, group_name, group_description, parent_group_id, created_at, updated_at, created_by, is_active
    FROM user_groups WHERE group_name = p_group_name AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_update_user_group$$
CREATE PROCEDURE sp_update_user_group(
    IN p_group_id VARCHAR(64),
    IN p_group_name VARCHAR(100),
    IN p_group_description TEXT
)
BEGIN
    UPDATE user_groups
    SET group_name = COALESCE(p_group_name, group_name),
        group_description = COALESCE(p_group_description, group_description),
        updated_at = NOW()
    WHERE id = p_group_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_delete_user_group$$
CREATE PROCEDURE sp_delete_user_group(IN p_group_id VARCHAR(64), IN p_deleted_by VARCHAR(64))
BEGIN
    UPDATE user_groups SET is_active = 0, updated_at = NOW() WHERE id = p_group_id AND is_active = 1;
    UPDATE user_group_members SET is_active = 0, removed_at = NOW(), removed_by = p_deleted_by
    WHERE user_group_id = p_group_id AND is_active = 1;
    UPDATE user_group_project_groups SET is_active = 0, revoked_at = NOW(), revoked_by = p_deleted_by
    WHERE user_group_id = p_group_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_list_all_user_groups$$
CREATE PROCEDURE sp_list_all_user_groups(
    IN p_limit INT,
    IN p_offset INT,
    IN p_sort_by VARCHAR(50),
    IN p_sort_order VARCHAR(4),
    IN p_search VARCHAR(255)
)
BEGIN
    SET @sort_col := CASE LOWER(p_sort_by)
        WHEN 'created_at' THEN 'created_at'
        WHEN 'updated_at' THEN 'updated_at'
        ELSE 'group_name' END;
    SET @dir := IF(LOWER(p_sort_order) = 'desc', 'DESC', 'ASC');
    
    IF p_search IS NOT NULL THEN
        SET @sql := CONCAT('SELECT id, group_hash, group_name, group_description, parent_group_id, created_at, updated_at, is_active ',
                          'FROM user_groups WHERE is_active = 1 AND group_name LIKE ', QUOTE(CONCAT('%', p_search, '%')), ' ',
                          'ORDER BY ', @sort_col, ' ', @dir, ' LIMIT ', p_limit, ' OFFSET ', p_offset);
    ELSE
        SET @sql := CONCAT('SELECT id, group_hash, group_name, group_description, parent_group_id, created_at, updated_at, is_active ',
                          'FROM user_groups WHERE is_active = 1 ORDER BY ', @sort_col, ' ', @dir, ' ',
                          'LIMIT ', p_limit, ' OFFSET ', p_offset);
    END IF;
    PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
END$$

DROP PROCEDURE IF EXISTS sp_count_user_groups$$
CREATE PROCEDURE sp_count_user_groups()
BEGIN
    SELECT COUNT(*) as count FROM user_groups WHERE is_active = 1;
END$$

-- ===================================================================================
-- USER GROUP MEMBERSHIP MANAGEMENT
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_assign_user_to_group$$
CREATE PROCEDURE sp_assign_user_to_group(
    IN p_member_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64),
    IN p_assigned_by VARCHAR(64)
)
BEGIN
    INSERT INTO user_group_members (id, user_id, user_group_id, assigned_at, assigned_by)
    VALUES (p_member_id, p_user_id, p_user_group_id, NOW(), p_assigned_by)
    ON DUPLICATE KEY UPDATE
        is_active = TRUE,
        assigned_at = NOW(),
        assigned_by = p_assigned_by,
        removed_at = NULL,
        removed_by = NULL;
END$$

DROP PROCEDURE IF EXISTS sp_reactivate_user_group_membership$$
CREATE PROCEDURE sp_reactivate_user_group_membership(
    IN p_user_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64),
    IN p_assigned_by VARCHAR(64)
)
BEGIN
    UPDATE user_group_members
    SET is_active = TRUE,
        assigned_at = NOW(),
        assigned_by = p_assigned_by,
        removed_at = NULL,
        removed_by = NULL
    WHERE user_id = p_user_id
      AND user_group_id = p_user_group_id;

    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_remove_user_from_group$$
CREATE PROCEDURE sp_remove_user_from_group(
    IN p_user_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64),
    IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE user_group_members 
    SET is_active = 0, removed_at = NOW(), removed_by = p_removed_by
    WHERE user_id = p_user_id AND user_group_id = p_user_group_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_get_users_in_group$$
CREATE PROCEDURE sp_get_users_in_group(IN p_user_group_id VARCHAR(64))
BEGIN
    SELECT u.id, u.user_hash, u.username, u.email, u.user_type, u.role_id, u.created_at, u.updated_at, u.is_active,
           ugm.assigned_at, ugm.assigned_by
    FROM users u
    INNER JOIN user_group_members ugm ON u.id = ugm.user_id
    WHERE ugm.user_group_id = p_user_group_id AND u.is_active = 1 AND ugm.is_active = 1
    ORDER BY u.username ASC;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_groups_for_user$$
CREATE PROCEDURE sp_get_user_groups_for_user(IN p_user_id VARCHAR(64))
BEGIN
    SELECT ug.id, ug.group_hash, ug.group_name, ug.group_description, ug.parent_group_id,
           ug.created_at, ug.updated_at, ug.is_active,
           ugm.assigned_at as joined_at
    FROM user_groups ug
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    WHERE ugm.user_id = p_user_id AND ug.is_active = 1 AND ugm.is_active = 1
    ORDER BY ug.group_name ASC;
END$$

DROP PROCEDURE IF EXISTS sp_check_user_in_group$$
CREATE PROCEDURE sp_check_user_in_group(IN p_user_id VARCHAR(64), IN p_user_group_id VARCHAR(64))
BEGIN
    SELECT COUNT(*) > 0 as is_member
    FROM user_group_members
    WHERE user_id = p_user_id AND user_group_id = p_user_group_id AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_group_membership$$
CREATE PROCEDURE sp_get_user_group_membership(
    IN p_user_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64)
)
BEGIN
    SELECT id, user_id, user_group_id, assigned_at, assigned_by,
           removed_at, removed_by, is_active
    FROM user_group_members
    WHERE user_id = p_user_id
      AND user_group_id = p_user_group_id
    LIMIT 1;
END$$

-- ===================================================================================
-- USER GROUP → PROJECT GROUP ACCESS (GROUPS OF GROUPS)
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_grant_user_group_project_group_access$$
CREATE PROCEDURE sp_grant_user_group_project_group_access(
    IN p_access_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64),
    IN p_project_group_id VARCHAR(64),
    IN p_granted_by VARCHAR(64)
)
BEGIN
    INSERT INTO user_group_project_groups (id, user_group_id, project_group_id, granted_at, granted_by)
    VALUES (p_access_id, p_user_group_id, p_project_group_id, NOW(), p_granted_by)
    ON DUPLICATE KEY UPDATE
        is_active = TRUE,
        granted_at = NOW(),
        granted_by = p_granted_by,
        revoked_at = NULL,
        revoked_by = NULL;
END$$

DROP PROCEDURE IF EXISTS sp_revoke_user_group_project_group_access$$
CREATE PROCEDURE sp_revoke_user_group_project_group_access(
    IN p_user_group_id VARCHAR(64),
    IN p_project_group_id VARCHAR(64),
    IN p_revoked_by VARCHAR(64)
)
BEGIN
    UPDATE user_group_project_groups 
    SET is_active = FALSE, revoked_at = NOW(), revoked_by = p_revoked_by
    WHERE user_group_id = p_user_group_id 
      AND project_group_id = p_project_group_id 
      AND is_active = TRUE;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_get_project_groups_for_user_group$$
CREATE PROCEDURE sp_get_project_groups_for_user_group(IN p_user_group_id VARCHAR(64))
BEGIN
    SELECT pg.id, pg.group_hash, pg.group_name, pg.group_description, 
           pg.created_at, pg.is_active, ugpg.granted_at, ugpg.granted_by
    FROM project_groups pg
    INNER JOIN user_group_project_groups ugpg ON pg.id = ugpg.project_group_id
    WHERE ugpg.user_group_id = p_user_group_id 
      AND ugpg.is_active = TRUE 
      AND pg.is_active = TRUE
    ORDER BY pg.group_name;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_groups_for_project_group$$
CREATE PROCEDURE sp_get_user_groups_for_project_group(IN p_project_group_id VARCHAR(64))
BEGIN
    SELECT ug.id, ug.group_hash, ug.group_name, ug.group_description,
           ug.parent_group_id, ug.is_active,
           ugpg.granted_at, ugpg.granted_by
    FROM user_groups ug
    INNER JOIN user_group_project_groups ugpg ON ug.id = ugpg.user_group_id
    WHERE ugpg.project_group_id = p_project_group_id 
      AND ugpg.is_active = TRUE 
      AND ug.is_active = TRUE
    ORDER BY ug.group_name;
END$$

DROP PROCEDURE IF EXISTS sp_check_user_group_project_group_access$$
CREATE PROCEDURE sp_check_user_group_project_group_access(
    IN p_user_group_id VARCHAR(64),
    IN p_project_group_id VARCHAR(64)
)
BEGIN
    SELECT COUNT(*) > 0 AS has_access
    FROM user_group_project_groups
    WHERE user_group_id = p_user_group_id 
      AND project_group_id = p_project_group_id 
      AND is_active = TRUE;
END$$

-- ===================================================================================
-- USER ACCESS TO PROJECTS (via groups of groups)
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_user_accessible_projects$$
CREATE PROCEDURE sp_get_user_accessible_projects(IN p_user_id VARCHAR(64))
BEGIN
    DECLARE v_user_type VARCHAR(20);
    SELECT user_type INTO v_user_type FROM users WHERE id = p_user_id AND is_active = 1;

    IF v_user_type = 'root' THEN
        SELECT p.id, p.project_hash, p.project_name, p.project_description,
               'root_access' as access_type
        FROM projects p
        WHERE p.is_active = 1
          AND (p.archived = FALSE OR p.archived IS NULL)
        ORDER BY p.project_name;
    ELSE
        SELECT DISTINCT p.id, p.project_hash, p.project_name, p.project_description,
               'group_access' as access_type
        FROM user_group_members ugm
        JOIN user_groups ug ON ug.id = ugm.user_group_id AND ug.is_active = 1
        JOIN user_group_project_groups ugpg ON ugpg.user_group_id = ug.id AND ugpg.is_active = 1
        JOIN project_groups pg ON pg.id = ugpg.project_group_id AND pg.is_active = 1
        JOIN project_group_members pgm ON pgm.project_group_id = pg.id AND pgm.is_active = 1
        JOIN projects p ON p.id = pgm.project_id
            AND p.is_active = 1
            AND (p.archived = FALSE OR p.archived IS NULL)
        WHERE ugm.user_id = p_user_id
          AND ugm.is_active = 1
        ORDER BY p.project_name;
    END IF;
END$$

DROP PROCEDURE IF EXISTS sp_check_user_project_access$$
CREATE PROCEDURE sp_check_user_project_access(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64)
)
BEGIN
    DECLARE v_user_type VARCHAR(20);
    DECLARE v_has_access BOOLEAN DEFAULT FALSE;
    
    SELECT user_type INTO v_user_type FROM users WHERE id = p_user_id AND is_active = 1;
    
    IF v_user_type = 'root' THEN
        SELECT COUNT(*) > 0 INTO v_has_access
        FROM projects p
        WHERE p.id = p_project_id
          AND p.is_active = 1
          AND (p.archived = FALSE OR p.archived IS NULL);
    ELSE
        SELECT COUNT(*) > 0 INTO v_has_access
        FROM user_group_members ugm
        JOIN user_groups ug ON ug.id = ugm.user_group_id AND ug.is_active = 1
        JOIN user_group_project_groups ugpg ON ugpg.user_group_id = ug.id AND ugpg.is_active = 1
        JOIN project_groups pg ON pg.id = ugpg.project_group_id AND pg.is_active = 1
        JOIN project_group_members pgm ON pgm.project_group_id = pg.id AND pgm.is_active = 1
        JOIN projects p ON p.id = pgm.project_id
            AND p.is_active = 1
            AND (p.archived = FALSE OR p.archived IS NULL)
        WHERE ugm.user_id = p_user_id 
          AND pgm.project_id = p_project_id
          AND ugm.is_active = 1;
    END IF;
    
    SELECT v_has_access as has_access;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_access_path_to_project$$
CREATE PROCEDURE sp_get_user_access_path_to_project(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT ug.group_name as user_group, pg.group_name as project_group, ugpg.granted_at
    FROM user_group_members ugm
    JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
    JOIN user_group_project_groups ugpg ON ug.id = ugpg.user_group_id AND ugpg.is_active = 1
    JOIN project_groups pg ON ugpg.project_group_id = pg.id AND pg.is_active = 1
    JOIN project_group_members pgm ON pg.id = pgm.project_group_id AND pgm.is_active = 1
    WHERE ugm.user_id = p_user_id 
      AND pgm.project_id = p_project_id
      AND ugm.is_active = 1;
END$$

-- ===================================================================================
-- USER GROUPS IN PROJECT CONTEXT
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_user_groups_in_project$$
CREATE PROCEDURE sp_get_user_groups_in_project(IN p_user_id VARCHAR(64), IN p_project_id VARCHAR(64))
BEGIN
    SELECT DISTINCT ug.id, ug.group_hash, ug.group_name, ug.group_description, ug.created_at, ug.updated_at, ug.is_active
    FROM user_groups ug
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    INNER JOIN user_group_project_groups ugpg ON ug.id = ugpg.user_group_id
    INNER JOIN project_groups pg ON pg.id = ugpg.project_group_id
    INNER JOIN project_group_members pgm ON pg.id = pgm.project_group_id
    INNER JOIN projects p ON pgm.project_id = p.id
    WHERE ugm.user_id = p_user_id 
      AND pgm.project_id = p_project_id
      AND ug.is_active = 1 
      AND ugm.is_active = 1 
      AND ugpg.is_active = 1
      AND pg.is_active = 1
      AND pgm.is_active = 1
      AND p.is_active = 1
      AND (p.archived = FALSE OR p.archived IS NULL)
    ORDER BY ug.group_name ASC;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_groups_in_project_by_hash$$
CREATE PROCEDURE sp_get_user_groups_in_project_by_hash(IN p_user_id VARCHAR(64), IN p_project_hash VARCHAR(255))
BEGIN
    SELECT DISTINCT ug.id, ug.group_hash, ug.group_name, ug.group_description,
           ug.created_at, ug.updated_at, ug.is_active
    FROM user_groups ug
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    INNER JOIN user_group_project_groups ugpg ON ug.id = ugpg.user_group_id
    INNER JOIN project_groups pg ON pg.id = ugpg.project_group_id
    INNER JOIN project_group_members pgm ON pg.id = pgm.project_group_id
    INNER JOIN projects p ON pgm.project_id = p.id
    WHERE ugm.user_id = p_user_id
      AND p.project_hash = p_project_hash
      AND ug.is_active = 1
      AND ugm.is_active = 1
      AND ugpg.is_active = 1
      AND pg.is_active = 1
      AND pgm.is_active = 1
      AND p.is_active = 1
      AND (p.archived = FALSE OR p.archived IS NULL)
    ORDER BY ug.group_name ASC;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_groups_for_project$$
CREATE PROCEDURE sp_get_user_groups_for_project(IN p_project_id VARCHAR(64))
BEGIN
    -- Get all user groups that have access to a project through project groups
    -- Includes member_count for each group
    SELECT DISTINCT ug.id, ug.group_hash, ug.group_name, ug.group_description,
           ug.created_at, ug.updated_at, ug.is_active,
           (SELECT COUNT(*) FROM user_group_members ugm 
            WHERE ugm.user_group_id = ug.id AND ugm.is_active = 1) AS member_count
    FROM user_groups ug
    INNER JOIN user_group_project_groups ugpg ON ug.id = ugpg.user_group_id
    INNER JOIN project_group_members pgm ON ugpg.project_group_id = pgm.project_group_id
    WHERE pgm.project_id = p_project_id
      AND ug.is_active = 1
      AND ugpg.is_active = 1
      AND pgm.is_active = 1
    ORDER BY ug.group_name ASC;
END$$

DROP PROCEDURE IF EXISTS sp_get_projects_for_user_group$$
CREATE PROCEDURE sp_get_projects_for_user_group(IN p_user_group_id VARCHAR(64))
BEGIN
    -- Get all projects accessible by a user group through project groups
    SELECT DISTINCT p.id, p.project_hash, p.project_name, p.project_description
    FROM projects p
    INNER JOIN project_group_members pgm ON p.id = pgm.project_id
    INNER JOIN user_group_project_groups ugpg ON pgm.project_group_id = ugpg.project_group_id
    INNER JOIN project_groups pg ON pg.id = ugpg.project_group_id
    INNER JOIN user_groups ug ON ug.id = ugpg.user_group_id
    WHERE ugpg.user_group_id = p_user_group_id
      AND p.is_active = 1
      AND (p.archived = FALSE OR p.archived IS NULL)
      AND pg.is_active = 1
      AND ug.is_active = 1
      AND pgm.is_active = 1
      AND ugpg.is_active = 1
    ORDER BY p.project_name ASC;
END$$

DELIMITER ;

-- ===================================================================================
-- USER GROUP PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'User group stored procedures created!' as status,
       'Groups of Groups architecture applied' as details;
