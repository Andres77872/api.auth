-- ===================================================================================
-- PROJECT GROUP MANAGEMENT STORED PROCEDURES
-- GROUPS OF GROUPS Architecture
-- ===================================================================================
-- This file contains all stored procedures related to project group management:
-- - Project group CRUD operations
-- - Project group membership management (project → project group)
-- - Project group statistics
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- PROJECT GROUP CRUD OPERATIONS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_create_project_group$$
CREATE PROCEDURE sp_create_project_group(
    IN p_group_id VARCHAR(64),
    IN p_group_hash VARCHAR(255),
    IN p_group_name VARCHAR(100),
    IN p_group_description TEXT,
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO project_groups (id, group_hash, group_name, group_description, created_by, created_at)
    VALUES (p_group_id, p_group_hash, p_group_name, p_group_description, p_created_by, NOW());
END$$

DROP PROCEDURE IF EXISTS sp_get_project_group_by_id$$
CREATE PROCEDURE sp_get_project_group_by_id(IN p_group_id VARCHAR(64))
BEGIN
    SELECT id, group_hash, group_name, group_description, created_at, updated_at, created_by, is_active
    FROM project_groups WHERE id = p_group_id AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_project_group_by_hash$$
CREATE PROCEDURE sp_get_project_group_by_hash(IN p_group_hash VARCHAR(255))
BEGIN
    SELECT id, group_hash, group_name, group_description, created_at, updated_at, created_by, is_active
    FROM project_groups WHERE group_hash = p_group_hash AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_project_group_by_name$$
CREATE PROCEDURE sp_get_project_group_by_name(IN p_group_name VARCHAR(100))
BEGIN
    SELECT id, group_hash, group_name, group_description, created_at, updated_at, created_by, is_active
    FROM project_groups WHERE group_name = p_group_name AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_list_all_project_groups$$
CREATE PROCEDURE sp_list_all_project_groups(
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
        SET @sql := CONCAT('SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active ',
                          'FROM project_groups WHERE is_active = 1 AND group_name LIKE ', QUOTE(CONCAT('%', p_search, '%')), ' ',
                          'ORDER BY ', @sort_col, ' ', @dir, ' LIMIT ', p_limit, ' OFFSET ', p_offset);
    ELSE
        SET @sql := CONCAT('SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active ',
                          'FROM project_groups WHERE is_active = 1 ORDER BY ', @sort_col, ' ', @dir, ' ',
                          'LIMIT ', p_limit, ' OFFSET ', p_offset);
    END IF;
    PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
END$$

DROP PROCEDURE IF EXISTS sp_update_project_group$$
CREATE PROCEDURE sp_update_project_group(
    IN p_group_id VARCHAR(64),
    IN p_group_name VARCHAR(100),
    IN p_group_description TEXT
)
BEGIN
    UPDATE project_groups
    SET group_name = COALESCE(p_group_name, group_name),
        group_description = COALESCE(p_group_description, group_description),
        updated_at = NOW()
    WHERE id = p_group_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_delete_project_group$$
CREATE PROCEDURE sp_delete_project_group(IN p_group_id VARCHAR(64), IN p_deleted_by VARCHAR(64))
BEGIN
    UPDATE project_groups SET is_active = 0, updated_at = NOW() WHERE id = p_group_id AND is_active = 1;
    UPDATE project_group_members SET is_active = 0, removed_at = NOW(), removed_by = p_deleted_by
    WHERE project_group_id = p_group_id AND is_active = 1;
    UPDATE user_group_project_groups SET is_active = 0, revoked_at = NOW(), revoked_by = p_deleted_by
    WHERE project_group_id = p_group_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_count_project_groups$$
CREATE PROCEDURE sp_count_project_groups()
BEGIN
    SELECT COUNT(*) as count FROM project_groups WHERE is_active = 1;
END$$

-- ===================================================================================
-- PROJECT GROUP MEMBERSHIP MANAGEMENT
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_assign_project_to_group$$
CREATE PROCEDURE sp_assign_project_to_group(
    IN p_member_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_project_group_id VARCHAR(64),
    IN p_assigned_by VARCHAR(64)
)
BEGIN
    INSERT INTO project_group_members (id, project_id, project_group_id, assigned_at, assigned_by)
    VALUES (p_member_id, p_project_id, p_project_group_id, NOW(), p_assigned_by)
    ON DUPLICATE KEY UPDATE
        is_active = TRUE,
        assigned_at = NOW(),
        assigned_by = p_assigned_by,
        removed_at = NULL,
        removed_by = NULL;
END$$

DROP PROCEDURE IF EXISTS sp_remove_project_from_group$$
CREATE PROCEDURE sp_remove_project_from_group(
    IN p_project_id VARCHAR(64),
    IN p_project_group_id VARCHAR(64),
    IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE project_group_members 
    SET is_active = 0, removed_at = NOW(), removed_by = p_removed_by
    WHERE project_id = p_project_id AND project_group_id = p_project_group_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_get_project_groups_for_project$$
CREATE PROCEDURE sp_get_project_groups_for_project(IN p_project_id VARCHAR(64))
BEGIN
    SELECT pg.id, pg.group_hash, pg.group_name, pg.group_description, 
           pg.created_at, pg.updated_at, pg.is_active,
           pgm.assigned_at, pgm.assigned_by
    FROM project_groups pg
    INNER JOIN project_group_members pgm ON pg.id = pgm.project_group_id
    WHERE pgm.project_id = p_project_id AND pg.is_active = 1 AND pgm.is_active = 1
    ORDER BY pg.group_name ASC;
END$$

DROP PROCEDURE IF EXISTS sp_get_projects_in_project_group$$
CREATE PROCEDURE sp_get_projects_in_project_group(IN p_project_group_id VARCHAR(64))
BEGIN
    SELECT p.id, p.project_hash, p.project_name, p.project_description, 
           p.project_created, p.updated_at, p.is_active,
           pgm.assigned_at, pgm.assigned_by
    FROM projects p
    INNER JOIN project_group_members pgm ON p.id = pgm.project_id
    WHERE pgm.project_group_id = p_project_group_id AND p.is_active = 1 AND pgm.is_active = 1
    ORDER BY p.project_name ASC;
END$$

DROP PROCEDURE IF EXISTS sp_check_project_in_group$$
CREATE PROCEDURE sp_check_project_in_group(IN p_project_id VARCHAR(64), IN p_project_group_id VARCHAR(64))
BEGIN
    SELECT COUNT(*) > 0 as is_member
    FROM project_group_members
    WHERE project_id = p_project_id AND project_group_id = p_project_group_id AND is_active = 1;
END$$

-- ===================================================================================
-- PROJECT GROUP STATISTICS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_project_group_stats$$
CREATE PROCEDURE sp_get_project_group_stats(IN p_project_group_id VARCHAR(64))
BEGIN
    SELECT 
        pg.id,
        pg.group_name,
        pg.group_description,
        COUNT(DISTINCT pgm.project_id) as project_count,
        COUNT(DISTINCT ugpg.user_group_id) as user_group_count,
        COUNT(DISTINCT ugm.user_id) as total_users
    FROM project_groups pg
    LEFT JOIN project_group_members pgm ON pg.id = pgm.project_group_id AND pgm.is_active = 1
    LEFT JOIN user_group_project_groups ugpg ON pg.id = ugpg.project_group_id AND ugpg.is_active = 1
    LEFT JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id AND ugm.is_active = 1
    WHERE pg.id = p_project_group_id AND pg.is_active = 1
    GROUP BY pg.id;
END$$

DROP PROCEDURE IF EXISTS sp_get_users_with_access_to_project_group$$
CREATE PROCEDURE sp_get_users_with_access_to_project_group(IN p_project_group_id VARCHAR(64))
BEGIN
    SELECT DISTINCT u.id, u.user_hash, u.username, u.email, u.user_type,
           ug.group_name as via_user_group, ugpg.granted_at
    FROM users u
    JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
    JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
    JOIN user_group_project_groups ugpg ON ug.id = ugpg.user_group_id AND ugpg.is_active = 1
    WHERE ugpg.project_group_id = p_project_group_id AND u.is_active = 1
    ORDER BY u.username;
END$$

DELIMITER ;

-- ===================================================================================
-- PROJECT GROUP PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Project group stored procedures created!' as status,
       'Groups of Groups architecture applied' as details;
