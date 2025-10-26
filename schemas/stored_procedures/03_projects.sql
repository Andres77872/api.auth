-- ===================================================================================
-- PROJECT MANAGEMENT STORED PROCEDURES
-- ===================================================================================
-- This file contains all stored procedures related to project management:
-- - Project CRUD operations
-- - Project listing and search
-- - Project statistics
-- - Project member management
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
    IN p_project_id VARCHAR(64), IN p_project_hash VARCHAR(255),
    IN p_project_name VARCHAR(100), IN p_project_description TEXT, IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO projects (id, project_hash, project_name, project_description, project_created, created_by)
    VALUES (p_project_id, p_project_hash, p_project_name, p_project_description, NOW(), p_created_by);
END$$

DROP PROCEDURE IF EXISTS sp_get_project_by_id$$
CREATE PROCEDURE sp_get_project_by_id(IN p_project_id VARCHAR(64))
BEGIN
    SELECT id, project_hash, project_name, project_description, project_created, is_active
    FROM projects WHERE id = p_project_id AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_project_by_hash$$
CREATE PROCEDURE sp_get_project_by_hash(IN p_project_hash VARCHAR(255))
BEGIN
    SELECT id, project_hash, project_name, project_description, project_created, is_active
    FROM projects WHERE project_hash = p_project_hash AND is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_update_project$$
CREATE PROCEDURE sp_update_project(
    IN p_project_id VARCHAR(64), IN p_project_name VARCHAR(100), IN p_project_description TEXT
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
    UPDATE user_group_projects SET is_active = 0, revoked_at = NOW(), revoked_by = p_deleted_by
    WHERE project_id = p_project_id AND is_active = 1;
    UPDATE user_sessions SET is_active = 0 WHERE project_id = p_project_id AND is_active = 1;
    SELECT ROW_COUNT() as rows_affected;
END$$

-- ===================================================================================
-- PROJECT LISTING & SEARCH
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_list_all_projects$$
CREATE PROCEDURE sp_list_all_projects(IN p_limit INT, IN p_offset INT)
BEGIN
    SELECT id, project_hash, project_name, project_description, project_created, is_active
    FROM projects WHERE is_active = 1 ORDER BY project_created DESC LIMIT p_limit OFFSET p_offset;
END$$

DROP PROCEDURE IF EXISTS sp_count_projects$$
CREATE PROCEDURE sp_count_projects()
BEGIN
    SELECT COUNT(*) as count FROM projects WHERE is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_search_projects$$
CREATE PROCEDURE sp_search_projects(IN p_search_term VARCHAR(255), IN p_limit INT)
BEGIN
    SELECT id, project_hash, project_name, project_description, project_created, is_active
    FROM projects WHERE is_active = 1
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
    SELECT COUNT(DISTINCT ugm.user_id) as total_users FROM user_group_members ugm
    JOIN user_group_projects ugp ON ugm.user_group_id = ugp.user_group_id AND ugp.is_active = 1
    WHERE ugp.project_id = p_project_id AND ugm.is_active = 1;
    
    SELECT COUNT(*) as active_sessions FROM user_sessions
    WHERE project_id = p_project_id AND is_active = 1 AND expires_at > NOW();
    
    SELECT COUNT(DISTINCT ugp.user_group_id) as total_groups FROM user_group_projects ugp
    WHERE ugp.project_id = p_project_id AND ugp.is_active = 1;
END$$

DROP PROCEDURE IF EXISTS sp_get_project_statistics$$
CREATE PROCEDURE sp_get_project_statistics(IN p_project_id VARCHAR(64))
BEGIN
    -- Total distinct users with access
    SELECT COUNT(DISTINCT ugm.user_id) as total_users
    FROM user_group_members ugm
    JOIN user_group_projects ugp ON ugm.user_group_id = ugp.user_group_id AND ugp.is_active = 1
    WHERE ugp.project_id = p_project_id AND ugm.is_active = 1;
    
    -- Active sessions
    SELECT COUNT(*) as active_sessions
    FROM user_sessions
    WHERE project_id = p_project_id AND is_active = 1 AND expires_at > NOW();
    
    -- Total groups with access
    SELECT COUNT(DISTINCT ugp.user_group_id) as total_groups
    FROM user_group_projects ugp
    WHERE ugp.project_id = p_project_id AND ugp.is_active = 1;
    
    -- Group distribution
    SELECT ug.group_name, COUNT(DISTINCT ugm.user_id) AS user_count
    FROM user_groups ug
    JOIN user_group_projects ugp ON ug.id = ugp.user_group_id AND ugp.is_active = 1
    LEFT JOIN user_group_members ugm ON ugm.user_group_id = ug.id AND ugm.is_active = 1
    WHERE ugp.project_id = p_project_id AND ug.is_active = 1
    GROUP BY ug.id, ug.group_name
    ORDER BY user_count DESC;
END$$

-- ===================================================================================
-- PROJECT MEMBERS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_project_members$$
CREATE PROCEDURE sp_get_project_members(IN p_project_id VARCHAR(64))
BEGIN
    SELECT DISTINCT u.id, u.user_hash, u.username, u.email, u.user_type, u.role_id, u.is_active, u.created_at,
           ugp.granted_at, ugp.granted_by, ug.group_name
    FROM users u
    LEFT JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
    LEFT JOIN user_group_projects ugp ON ugm.user_group_id = ugp.user_group_id AND ugp.project_id = p_project_id AND ugp.is_active = 1
    LEFT JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
    WHERE u.is_active = 1 AND (u.user_type = 'root' OR ugp.user_group_id IS NOT NULL)
    ORDER BY u.user_type, u.username;
END$$

DELIMITER ;

-- ===================================================================================
-- PROJECT PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Project management stored procedures created successfully!' as status,
       '10+ procedures for project operations' as details;

