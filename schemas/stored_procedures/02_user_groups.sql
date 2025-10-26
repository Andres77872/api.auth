-- ===================================================================================
-- USER GROUP MANAGEMENT STORED PROCEDURES
-- ===================================================================================
-- This file contains all stored procedures related to user group management:
-- - User group CRUD operations
-- - User group membership management
-- - User group project access
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
    IN p_group_id VARCHAR(64), IN p_group_hash VARCHAR(255),
    IN p_group_name VARCHAR(100), IN p_group_description TEXT
)
BEGIN
    INSERT INTO user_groups (id, group_hash, group_name, group_description, created_at)
    VALUES (p_group_id, p_group_hash, p_group_name, p_group_description, NOW());
END$$

DROP PROCEDURE IF EXISTS sp_get_user_group_by_id$$
CREATE PROCEDURE sp_get_user_group_by_id(IN p_group_id VARCHAR(64))
BEGIN
    SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active
    FROM user_groups WHERE id = p_group_id AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_group_by_hash$$
CREATE PROCEDURE sp_get_user_group_by_hash(IN p_group_hash VARCHAR(255))
BEGIN
    SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active
    FROM user_groups WHERE group_hash = p_group_hash AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_group_by_name$$
CREATE PROCEDURE sp_get_user_group_by_name(IN p_group_name VARCHAR(100))
BEGIN
    SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active
    FROM user_groups WHERE group_name = p_group_name AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_update_user_group$$
CREATE PROCEDURE sp_update_user_group(
    IN p_group_id VARCHAR(64), IN p_group_name VARCHAR(100), IN p_group_description TEXT
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
    UPDATE user_group_projects SET is_active = 0, revoked_at = NOW(), revoked_by = p_deleted_by
    WHERE user_group_id = p_group_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_list_all_user_groups$$
CREATE PROCEDURE sp_list_all_user_groups(
    IN p_limit INT, IN p_offset INT, IN p_sort_by VARCHAR(50),
    IN p_sort_order VARCHAR(4), IN p_search VARCHAR(255)
)
BEGIN
    SET @sort_col := CASE LOWER(p_sort_by)
        WHEN 'created_at' THEN 'created_at' WHEN 'updated_at' THEN 'updated_at'
        WHEN 'id' THEN 'id' ELSE 'group_name' END;
    SET @dir := IF(LOWER(p_sort_order) = 'desc', 'DESC', 'ASC');
    
    IF p_search IS NOT NULL THEN
        SET @sql := CONCAT('SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active ',
                          'FROM user_groups WHERE is_active = 1 AND group_name LIKE ', QUOTE(CONCAT('%', p_search, '%')), ' ',
                          'ORDER BY ', @sort_col, ' ', @dir, ' LIMIT ', p_limit, ' OFFSET ', p_offset);
    ELSE
        SET @sql := CONCAT('SELECT id, group_hash, group_name, group_description, created_at, updated_at, is_active ',
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
    IN p_member_id VARCHAR(64), IN p_user_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64), IN p_assigned_by VARCHAR(64)
)
BEGIN
    INSERT INTO user_group_members (id, user_id, user_group_id, assigned_at, assigned_by)
    VALUES (p_member_id, p_user_id, p_user_group_id, NOW(), p_assigned_by);
END$$

DROP PROCEDURE IF EXISTS sp_remove_user_from_group$$
CREATE PROCEDURE sp_remove_user_from_group(
    IN p_user_id VARCHAR(64), IN p_user_group_id VARCHAR(64), IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE user_group_members SET is_active = 0, removed_at = NOW(), removed_by = p_removed_by
    WHERE user_id = p_user_id AND user_group_id = p_user_group_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_reactivate_user_group_membership$$
CREATE PROCEDURE sp_reactivate_user_group_membership(
    IN p_user_id VARCHAR(64), IN p_user_group_id VARCHAR(64), IN p_assigned_by VARCHAR(64)
)
BEGIN
    UPDATE user_group_members
    SET is_active = 1,
        removed_at = NULL,
        removed_by = NULL,
        assigned_by = p_assigned_by
    WHERE user_id = p_user_id
      AND user_group_id = p_user_group_id;
END$$

DROP PROCEDURE IF EXISTS sp_get_users_in_group$$
CREATE PROCEDURE sp_get_users_in_group(IN p_user_group_id VARCHAR(64))
BEGIN
    SELECT u.id, u.user_hash, u.username, u.email, u.user_type, u.role_id, u.created_at, u.updated_at, u.is_active
    FROM users u INNER JOIN user_group_members ugm ON u.id = ugm.user_id
    WHERE ugm.user_group_id = p_user_group_id AND u.is_active = 1 AND ugm.is_active = 1
    ORDER BY u.username ASC;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_groups_for_user$$
CREATE PROCEDURE sp_get_user_groups_for_user(IN p_user_id VARCHAR(64))
BEGIN
    SELECT ug.id, ug.group_hash, ug.group_name, ug.group_description, ug.created_at, ug.updated_at, ug.is_active
    FROM user_groups ug INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    WHERE ugm.user_id = p_user_id AND ug.is_active = 1 AND ugm.is_active = 1
    ORDER BY ug.group_name ASC;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_group_membership$$
CREATE PROCEDURE sp_get_user_group_membership(IN p_user_id VARCHAR(64), IN p_user_group_id VARCHAR(64))
BEGIN
    SELECT id, user_id, user_group_id, assigned_at, assigned_by, removed_at, removed_by, is_active
    FROM user_group_members WHERE user_id = p_user_id AND user_group_id = p_user_group_id AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_check_user_in_group$$
CREATE PROCEDURE sp_check_user_in_group(IN p_user_id VARCHAR(64), IN p_user_group_id VARCHAR(64))
BEGIN
    SELECT COUNT(*) as is_member
    FROM user_group_members ugm
    WHERE ugm.user_id = p_user_id
      AND ugm.user_group_id = p_user_group_id
      AND ugm.is_active = 1;
END$$

-- ===================================================================================
-- USER GROUP PROJECT ACCESS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_grant_group_project_access$$
CREATE PROCEDURE sp_grant_group_project_access(
    IN p_access_id VARCHAR(64), IN p_user_group_id VARCHAR(64),
    IN p_project_id VARCHAR(64), IN p_granted_by VARCHAR(64)
)
BEGIN
    INSERT INTO user_group_projects (id, user_group_id, project_id, granted_at, granted_by)
    VALUES (p_access_id, p_user_group_id, p_project_id, NOW(), p_granted_by);
END$$

DROP PROCEDURE IF EXISTS sp_revoke_group_project_access$$
CREATE PROCEDURE sp_revoke_group_project_access(
    IN p_user_group_id VARCHAR(64), IN p_project_id VARCHAR(64), IN p_revoked_by VARCHAR(64)
)
BEGIN
    UPDATE user_group_projects SET is_active = 0, revoked_at = NOW(), revoked_by = p_revoked_by
    WHERE user_group_id = p_user_group_id AND project_id = p_project_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_get_projects_for_user_group$$
CREATE PROCEDURE sp_get_projects_for_user_group(IN p_user_group_id VARCHAR(64))
BEGIN
    SELECT p.id, p.project_hash, p.project_name, p.project_description, p.project_created
    FROM projects p INNER JOIN user_group_projects ugp ON p.id = ugp.project_id
    WHERE ugp.user_group_id = p_user_group_id AND p.is_active = 1 AND ugp.is_active = 1
    ORDER BY p.project_name ASC;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_groups_for_project$$
CREATE PROCEDURE sp_get_user_groups_for_project(IN p_project_id VARCHAR(64))
BEGIN
    SELECT ug.id, ug.group_hash, ug.group_name, ug.group_description, ug.created_at, ug.updated_at, ug.is_active
    FROM user_groups ug INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
    WHERE ugp.project_id = p_project_id AND ug.is_active = 1 AND ugp.is_active = 1
    ORDER BY ug.group_name ASC;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_groups_in_project$$
CREATE PROCEDURE sp_get_user_groups_in_project(IN p_user_id VARCHAR(64), IN p_project_id VARCHAR(64))
BEGIN
    SELECT DISTINCT ug.id, ug.group_hash, ug.group_name, ug.group_description, ug.created_at, ug.updated_at, ug.is_active
    FROM user_groups ug
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
    WHERE ugm.user_id = p_user_id AND ugp.project_id = p_project_id
      AND ug.is_active = 1 AND ugm.is_active = 1 AND ugp.is_active = 1
    ORDER BY ug.group_name ASC;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_groups_in_project_by_hash$$
CREATE PROCEDURE sp_get_user_groups_in_project_by_hash(IN p_user_id VARCHAR(64), IN p_project_hash VARCHAR(255))
BEGIN
    SELECT DISTINCT ug.id, ug.group_hash, ug.group_name, ug.group_description,
           ug.created_at, ug.updated_at, ug.is_active
    FROM user_groups ug
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
    INNER JOIN projects p ON ugp.project_id = p.id
    WHERE ugm.user_id = p_user_id
      AND p.project_hash = p_project_hash
      AND ug.is_active = 1
      AND ugm.is_active = 1
      AND ugp.is_active = 1
      AND p.is_active = 1
    ORDER BY ug.group_name ASC;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_accessible_projects$$
CREATE PROCEDURE sp_get_user_accessible_projects(IN p_user_id VARCHAR(64))
BEGIN
    DECLARE v_user_type VARCHAR(20);
    SELECT user_type INTO v_user_type FROM users WHERE id = p_user_id AND is_active = 1;
    
    IF v_user_type = 'root' THEN
        SELECT p.id, p.project_hash, p.project_name, p.project_description FROM projects p WHERE p.is_active = 1;
    ELSE
        SELECT DISTINCT p.id, p.project_hash, p.project_name, p.project_description
        FROM user_group_members ugm
        JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
        JOIN user_group_projects ugp ON ug.id = ugp.user_group_id AND ugp.is_active = 1
        JOIN projects p ON ugp.project_id = p.id AND p.is_active = 1
        WHERE ugm.user_id = p_user_id AND ugm.is_active = 1;
    END IF;
END$$

DROP PROCEDURE IF EXISTS sp_find_user_groups_for_project_access$$
CREATE PROCEDURE sp_find_user_groups_for_project_access(IN p_user_id VARCHAR(64), IN p_project_id VARCHAR(64))
BEGIN
    SELECT DISTINCT ug.id
    FROM user_groups ug
    INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    WHERE ugm.user_id = p_user_id
      AND ugp.project_id = p_project_id
      AND ugm.is_active = 1
      AND ugp.is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_find_default_user_group_for_project$$
CREATE PROCEDURE sp_find_default_user_group_for_project(IN p_project_id VARCHAR(64))
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

DROP PROCEDURE IF EXISTS sp_find_admin_group_for_project$$
CREATE PROCEDURE sp_find_admin_group_for_project(IN p_project_id VARCHAR(64))
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

DROP PROCEDURE IF EXISTS sp_find_admin_groups_for_user_in_project$$
CREATE PROCEDURE sp_find_admin_groups_for_user_in_project(IN p_project_id VARCHAR(64), IN p_user_id VARCHAR(64))
BEGIN
    SELECT ug.id
    FROM user_groups ug
    INNER JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    WHERE ugp.project_id = p_project_id
      AND ugm.user_id = p_user_id
      AND ug.group_name LIKE '%admin%'
      AND ug.is_active = 1
      AND ugp.is_active = 1
      AND ugm.is_active = 1;
END$$

-- Get user groups by user for a project (alternate name for compatibility)
DROP PROCEDURE IF EXISTS sp_get_user_groups_by_user_for_project$$
CREATE PROCEDURE sp_get_user_groups_by_user_for_project(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT DISTINCT ug.id, ug.group_hash, ug.group_name, ug.group_description,
           ug.created_at, ug.updated_at, ug.is_active
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

DELIMITER ;

-- ===================================================================================
-- USER GROUP PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'User group management stored procedures created successfully!' as status,
       '26 procedures for user group operations' as details;

