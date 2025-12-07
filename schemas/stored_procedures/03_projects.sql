-- ===================================================================================
-- PROJECT MANAGEMENT STORED PROCEDURES
-- GROUPS OF GROUPS Architecture
-- ===================================================================================
-- This file contains all stored procedures related to project management:
-- - Project CRUD operations
-- - Project listing and search
-- - Project statistics
-- - Project member access (via groups of groups)
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- PROJECT CRUD OPERATIONS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_create_project$$
CREATE PROCEDURE sp_create_project(
    IN p_project_id VARCHAR(64),
    IN p_project_hash VARCHAR(255),
    IN p_project_name VARCHAR(100),
    IN p_project_description TEXT,
    IN p_created_by VARCHAR(64),
    IN p_owner_id VARCHAR(64)
)
BEGIN
    INSERT INTO projects (id, project_hash, project_name, project_description, project_created, created_by, owner_id)
    VALUES (p_project_id, p_project_hash, p_project_name, p_project_description, NOW(), p_created_by, p_owner_id);
END$$

DROP PROCEDURE IF EXISTS sp_get_project_by_id$$
CREATE PROCEDURE sp_get_project_by_id(IN p_project_id VARCHAR(64))
BEGIN
    SELECT id, project_hash, project_name, project_description, project_created, updated_at, owner_id, archived, is_active
    FROM projects WHERE id = p_project_id AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_project_by_hash$$
CREATE PROCEDURE sp_get_project_by_hash(IN p_project_hash VARCHAR(255))
BEGIN
    SELECT id, project_hash, project_name, project_description, project_created, updated_at, owner_id, archived, is_active
    FROM projects WHERE project_hash = p_project_hash AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_update_project$$
CREATE PROCEDURE sp_update_project(
    IN p_project_id VARCHAR(64),
    IN p_project_name VARCHAR(100),
    IN p_project_description TEXT
)
BEGIN
    UPDATE projects
    SET project_name = COALESCE(p_project_name, project_name),
        project_description = COALESCE(p_project_description, project_description),
        updated_at = NOW()
    WHERE id = p_project_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_delete_project$$
CREATE PROCEDURE sp_delete_project(IN p_project_id VARCHAR(64), IN p_deleted_by VARCHAR(64))
BEGIN
    UPDATE projects SET is_active = 0, updated_at = NOW() WHERE id = p_project_id AND is_active = 1;
    UPDATE project_group_members SET is_active = 0, removed_at = NOW(), removed_by = p_deleted_by
    WHERE project_id = p_project_id AND is_active = 1;
    UPDATE user_sessions SET is_active = 0 WHERE project_id = p_project_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_archive_project$$
CREATE PROCEDURE sp_archive_project(IN p_project_id VARCHAR(64), IN p_archived_by VARCHAR(64))
BEGIN
    UPDATE projects 
    SET archived = TRUE, archived_at = NOW(), archived_by = p_archived_by, updated_at = NOW()
    WHERE id = p_project_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_unarchive_project$$
CREATE PROCEDURE sp_unarchive_project(IN p_project_id VARCHAR(64))
BEGIN
    UPDATE projects 
    SET archived = FALSE, archived_at = NULL, archived_by = NULL, updated_at = NOW()
    WHERE id = p_project_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

-- ===================================================================================
-- PROJECT LISTING & SEARCH
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_list_all_projects$$
CREATE PROCEDURE sp_list_all_projects(
    IN p_limit INT,
    IN p_offset INT,
    IN p_sort_by VARCHAR(50),
    IN p_sort_order VARCHAR(4),
    IN p_search VARCHAR(255),
    IN p_include_archived BOOLEAN
)
BEGIN
    SET @sort_col := CASE LOWER(p_sort_by)
        WHEN 'project_name' THEN 'project_name'
        WHEN 'updated_at' THEN 'updated_at'
        ELSE 'project_created' END;
    SET @dir := IF(LOWER(p_sort_order) = 'desc', 'DESC', 'ASC');
    
    SET @sql := 'SELECT id, project_hash, project_name, project_description, project_created, updated_at, owner_id, archived, is_active FROM projects WHERE is_active = 1 ';
    
    IF p_include_archived = FALSE THEN
        SET @sql := CONCAT(@sql, 'AND archived = FALSE ');
    END IF;
    
    IF p_search IS NOT NULL THEN
        SET @sql := CONCAT(@sql, 'AND (project_name LIKE ', QUOTE(CONCAT('%', p_search, '%')), 
                          ' OR project_description LIKE ', QUOTE(CONCAT('%', p_search, '%')), ') ');
    END IF;
    
    SET @sql := CONCAT(@sql, 'ORDER BY ', @sort_col, ' ', @dir, ' LIMIT ', p_limit, ' OFFSET ', p_offset);
    PREPARE stmt FROM @sql; EXECUTE stmt; DEALLOCATE PREPARE stmt;
END$$

DROP PROCEDURE IF EXISTS sp_count_projects$$
CREATE PROCEDURE sp_count_projects(IN p_include_archived BOOLEAN)
BEGIN
    IF p_include_archived THEN
        SELECT COUNT(*) as count FROM projects WHERE is_active = 1;
    ELSE
        SELECT COUNT(*) as count FROM projects WHERE is_active = 1 AND archived = FALSE;
    END IF;
END$$

DROP PROCEDURE IF EXISTS sp_search_projects$$
CREATE PROCEDURE sp_search_projects(IN p_search_term VARCHAR(255), IN p_limit INT)
BEGIN
    SELECT id, project_hash, project_name, project_description, project_created, is_active
    FROM projects WHERE is_active = 1 AND archived = FALSE
      AND (project_name LIKE CONCAT('%', p_search_term, '%') OR project_description LIKE CONCAT('%', p_search_term, '%'))
    ORDER BY project_name ASC LIMIT p_limit;
END$$

DROP PROCEDURE IF EXISTS sp_get_recent_projects_count$$
CREATE PROCEDURE sp_get_recent_projects_count(IN p_days INT)
BEGIN
    SELECT COUNT(*) as count FROM projects
    WHERE project_created >= DATE_SUB(NOW(), INTERVAL p_days DAY) AND is_active = 1;
END$$

-- ===================================================================================
-- PROJECT STATISTICS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_project_stats$$
CREATE PROCEDURE sp_get_project_stats(IN p_project_id VARCHAR(64))
BEGIN
    -- Total distinct users with access (via groups of groups)
    SELECT COUNT(DISTINCT ugm.user_id) as total_users
    FROM user_group_members ugm
    JOIN user_group_project_groups ugpg ON ugm.user_group_id = ugpg.user_group_id AND ugpg.is_active = 1
    JOIN project_group_members pgm ON ugpg.project_group_id = pgm.project_group_id AND pgm.is_active = 1
    WHERE pgm.project_id = p_project_id AND ugm.is_active = 1;
    
    -- Active sessions
    SELECT COUNT(*) as active_sessions
    FROM user_sessions
    WHERE project_id = p_project_id AND is_active = 1 AND expires_at > NOW();
    
    -- Project groups containing this project
    SELECT COUNT(DISTINCT pgm.project_group_id) as project_group_count
    FROM project_group_members pgm
    WHERE pgm.project_id = p_project_id AND pgm.is_active = 1;
    
    -- User groups with access
    SELECT COUNT(DISTINCT ugpg.user_group_id) as user_group_count
    FROM user_group_project_groups ugpg
    JOIN project_group_members pgm ON ugpg.project_group_id = pgm.project_group_id AND pgm.is_active = 1
    WHERE pgm.project_id = p_project_id AND ugpg.is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_project_statistics$$
CREATE PROCEDURE sp_get_project_statistics(IN p_project_id VARCHAR(64))
BEGIN
    -- Project info
    SELECT p.id, p.project_name, p.project_description, p.owner_id, p.archived
    FROM projects p WHERE p.id = p_project_id AND p.is_active = 1;
    
    -- Access statistics
    SELECT 
        COUNT(DISTINCT ugm.user_id) as total_users,
        COUNT(DISTINCT ugpg.user_group_id) as user_groups,
        COUNT(DISTINCT pgm.project_group_id) as project_groups
    FROM project_group_members pgm
    LEFT JOIN user_group_project_groups ugpg ON pgm.project_group_id = ugpg.project_group_id AND ugpg.is_active = 1
    LEFT JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id AND ugm.is_active = 1
    WHERE pgm.project_id = p_project_id AND pgm.is_active = 1;
    
    -- User group distribution
    SELECT ug.group_name, COUNT(DISTINCT ugm.user_id) AS user_count
    FROM user_groups ug
    JOIN user_group_project_groups ugpg ON ug.id = ugpg.user_group_id AND ugpg.is_active = 1
    JOIN project_group_members pgm ON ugpg.project_group_id = pgm.project_group_id AND pgm.is_active = 1
    LEFT JOIN user_group_members ugm ON ugm.user_group_id = ug.id AND ugm.is_active = 1
    WHERE pgm.project_id = p_project_id AND ug.is_active = 1
    GROUP BY ug.id, ug.group_name
    ORDER BY user_count DESC;
END$$

-- ===================================================================================
-- PROJECT MEMBERS (via groups of groups)
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_project_members$$
CREATE PROCEDURE sp_get_project_members(IN p_project_id VARCHAR(64))
BEGIN
    -- Root users (always have access)
    SELECT u.id, u.user_hash, u.username, u.email, u.user_type, u.role_id, u.is_active, u.created_at,
           NULL as granted_at, NULL as user_group, NULL as project_group, 'root_access' as access_type
    FROM users u
    WHERE u.user_type = 'root' AND u.is_active = 1
    
    UNION
    
    -- Users via groups of groups
    SELECT DISTINCT u.id, u.user_hash, u.username, u.email, u.user_type, u.role_id, u.is_active, u.created_at,
           ugpg.granted_at, ug.group_name as user_group, pg.group_name as project_group, 'group_access' as access_type
    FROM users u
    JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
    JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
    JOIN user_group_project_groups ugpg ON ug.id = ugpg.user_group_id AND ugpg.is_active = 1
    JOIN project_groups pg ON ugpg.project_group_id = pg.id AND pg.is_active = 1
    JOIN project_group_members pgm ON pg.id = pgm.project_group_id AND pgm.is_active = 1
    WHERE pgm.project_id = p_project_id AND u.is_active = 1
    
    ORDER BY user_type, username;
END$$

DROP PROCEDURE IF EXISTS sp_get_admin_assigned_projects$$
CREATE PROCEDURE sp_get_admin_assigned_projects(IN p_user_id VARCHAR(64))
BEGIN
    SELECT DISTINCT p.id, p.project_hash, p.project_name, p.project_description
    FROM projects p
    INNER JOIN project_group_members pgm ON p.id = pgm.project_id AND pgm.is_active = 1
    INNER JOIN user_group_project_groups ugpg ON pgm.project_group_id = ugpg.project_group_id AND ugpg.is_active = 1
    INNER JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id AND ugm.is_active = 1
    WHERE ugm.user_id = p_user_id AND p.is_active = 1
    ORDER BY p.project_name;
END$$

DROP PROCEDURE IF EXISTS sp_check_admin_multi_project_access$$
CREATE PROCEDURE sp_check_admin_multi_project_access(IN p_user_id VARCHAR(64), IN p_project_id VARCHAR(64))
BEGIN
    SELECT COUNT(*) > 0 AS has_access
    FROM user_group_members ugm
    INNER JOIN user_group_project_groups ugpg ON ugm.user_group_id = ugpg.user_group_id AND ugpg.is_active = 1
    INNER JOIN project_group_members pgm ON ugpg.project_group_id = pgm.project_group_id AND pgm.is_active = 1
    WHERE ugm.user_id = p_user_id AND pgm.project_id = p_project_id AND ugm.is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_admin_project_assignments_with_details$$
CREATE PROCEDURE sp_get_admin_project_assignments_with_details(IN p_user_id VARCHAR(64))
BEGIN
    SELECT DISTINCT 
        p.id as project_id,
        p.project_hash,
        p.project_name,
        p.project_description,
        ugpg.granted_at as assigned_at,
        ugpg.granted_by as assigned_by,
        ug.group_name as access_through_user_group,
        pg.group_name as access_through_project_group
    FROM projects p
    INNER JOIN project_group_members pgm ON p.id = pgm.project_id AND pgm.is_active = 1
    INNER JOIN project_groups pg ON pgm.project_group_id = pg.id AND pg.is_active = 1
    INNER JOIN user_group_project_groups ugpg ON pg.id = ugpg.project_group_id AND ugpg.is_active = 1
    INNER JOIN user_groups ug ON ugpg.user_group_id = ug.id AND ug.is_active = 1
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id AND ugm.is_active = 1
    WHERE ugm.user_id = p_user_id AND p.is_active = 1
    ORDER BY p.project_name;
END$$

DELIMITER ;

-- ===================================================================================
-- PROJECT PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Project stored procedures created!' as status,
       'Groups of Groups architecture applied' as details;
