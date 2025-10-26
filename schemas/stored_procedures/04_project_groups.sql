-- ===================================================================================
-- PROJECT GROUP MANAGEMENT STORED PROCEDURES
-- ===================================================================================
-- This file contains all stored procedures related to project group management:
-- - Project group CRUD operations
-- - Project group membership management
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
    IN p_group_id VARCHAR(64), IN p_group_hash VARCHAR(255),
    IN p_group_name VARCHAR(100), IN p_group_description TEXT, IN p_permissions JSON
)
BEGIN
    INSERT INTO project_groups (id, group_hash, group_name, group_description, permissions, created_at)
    VALUES (p_group_id, p_group_hash, p_group_name, p_group_description, p_permissions, NOW());
END$$

DROP PROCEDURE IF EXISTS sp_get_project_group_by_id$$
CREATE PROCEDURE sp_get_project_group_by_id(IN p_group_id VARCHAR(64))
BEGIN
    SELECT id, group_hash, group_name, group_description, permissions, created_at, updated_at, is_active
    FROM project_groups WHERE id = p_group_id AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_project_group_by_hash$$
CREATE PROCEDURE sp_get_project_group_by_hash(IN p_group_hash VARCHAR(255))
BEGIN
    SELECT id, group_hash, group_name, group_description, permissions, created_at, updated_at, is_active
    FROM project_groups WHERE group_hash = p_group_hash AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_project_group_by_name$$
CREATE PROCEDURE sp_get_project_group_by_name(IN p_group_name VARCHAR(100))
BEGIN
    SELECT id, group_hash, group_name, group_description, permissions, created_at, updated_at, is_active
    FROM project_groups WHERE group_name = p_group_name AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_list_all_project_groups$$
CREATE PROCEDURE sp_list_all_project_groups(IN p_limit INT, IN p_offset INT)
BEGIN
    SELECT id, group_hash, group_name, group_description, permissions, created_at, updated_at, is_active
    FROM project_groups WHERE is_active = 1 ORDER BY group_name ASC LIMIT p_limit OFFSET p_offset;
END$$

DROP PROCEDURE IF EXISTS sp_update_project_group$$
CREATE PROCEDURE sp_update_project_group(
    IN p_group_id VARCHAR(64), IN p_group_name VARCHAR(100),
    IN p_group_description TEXT, IN p_permissions JSON
)
BEGIN
    UPDATE project_groups
    SET group_name = COALESCE(p_group_name, group_name),
        group_description = COALESCE(p_group_description, group_description),
        permissions = COALESCE(p_permissions, permissions),
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
    IN p_member_id VARCHAR(64), IN p_project_id VARCHAR(64),
    IN p_project_group_id VARCHAR(64), IN p_assigned_by VARCHAR(64)
)
BEGIN
    INSERT INTO project_group_members (id, project_id, project_group_id, assigned_at, assigned_by)
    VALUES (p_member_id, p_project_id, p_project_group_id, NOW(), p_assigned_by);
END$$

DROP PROCEDURE IF EXISTS sp_remove_project_from_group$$
CREATE PROCEDURE sp_remove_project_from_group(
    IN p_project_id VARCHAR(64), IN p_project_group_id VARCHAR(64), IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE project_group_members SET is_active = 0, removed_at = NOW(), removed_by = p_removed_by
    WHERE project_id = p_project_id AND project_group_id = p_project_group_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_get_project_groups_for_project$$
CREATE PROCEDURE sp_get_project_groups_for_project(IN p_project_id VARCHAR(64))
BEGIN
    SELECT pg.id, pg.group_hash, pg.group_name, pg.group_description, pg.permissions, pg.created_at, pg.updated_at, pg.is_active
    FROM project_groups pg INNER JOIN project_group_members pgm ON pg.id = pgm.project_group_id
    WHERE pgm.project_id = p_project_id AND pg.is_active = 1 AND pgm.is_active = 1
    ORDER BY pg.group_name ASC;
END$$

DROP PROCEDURE IF EXISTS sp_get_projects_in_project_group$$
CREATE PROCEDURE sp_get_projects_in_project_group(IN p_project_group_id VARCHAR(64))
BEGIN
    SELECT p.id, p.project_hash, p.project_name, p.project_description, p.project_created, p.updated_at, p.is_active
    FROM projects p INNER JOIN project_group_members pgm ON p.id = pgm.project_id
    WHERE pgm.project_group_id = p_project_group_id AND p.is_active = 1 AND pgm.is_active = 1
    ORDER BY p.project_name ASC;
END$$

DELIMITER ;

-- ===================================================================================
-- PROJECT GROUP PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Project group management stored procedures created successfully!' as status,
       '12 procedures for project group operations' as details;

