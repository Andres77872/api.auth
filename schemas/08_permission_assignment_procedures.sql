-- Permission Assignment System - Stored Procedures
-- Procedures for user group and direct user assignment of permission groups
-- Date: October 12, 2024

USE magic_auth;

DELIMITER $$

-- =================== USER GROUP PERMISSION GROUP ASSIGNMENTS ===================

-- Assign permission group to user group
DROP PROCEDURE IF EXISTS sp_assign_permission_group_to_user_group$$
CREATE PROCEDURE sp_assign_permission_group_to_user_group(
    IN p_link_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64),
    IN p_assigned_by VARCHAR(64)
)
BEGIN
    INSERT INTO user_group_permission_groups (
        id, user_group_id, permission_group_id, assigned_by, is_active
    ) VALUES (
        p_link_id, p_user_group_id, p_permission_group_id, p_assigned_by, TRUE
    )
    ON DUPLICATE KEY UPDATE
        is_active = TRUE,
        assigned_at = CURRENT_TIMESTAMP,
        assigned_by = p_assigned_by,
        removed_at = NULL,
        removed_by = NULL;
END$$

-- Remove permission group from user group
DROP PROCEDURE IF EXISTS sp_remove_permission_group_from_user_group$$
CREATE PROCEDURE sp_remove_permission_group_from_user_group(
    IN p_user_group_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64),
    IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE user_group_permission_groups
    SET is_active = FALSE,
        removed_at = CURRENT_TIMESTAMP,
        removed_by = p_removed_by
    WHERE user_group_id = p_user_group_id
      AND permission_group_id = p_permission_group_id
      AND is_active = TRUE;
END$$

-- Get permission groups for a user group
DROP PROCEDURE IF EXISTS sp_get_user_group_permission_groups$$
CREATE PROCEDURE sp_get_user_group_permission_groups(
    IN p_user_group_id VARCHAR(64)
)
BEGIN
    SELECT 
        pg.id,
        pg.group_hash,
        pg.group_name,
        pg.group_display_name,
        pg.group_description,
        pg.group_category,
        ugpg.assigned_at,
        ugpg.assigned_by
    FROM user_group_permission_groups ugpg
    INNER JOIN global_permission_groups pg ON ugpg.permission_group_id = pg.id
    WHERE ugpg.user_group_id = p_user_group_id
      AND ugpg.is_active = TRUE
      AND pg.is_active = TRUE
    ORDER BY pg.group_name;
END$$

-- Get user groups that have a specific permission group
DROP PROCEDURE IF EXISTS sp_get_user_groups_with_permission_group$$
CREATE PROCEDURE sp_get_user_groups_with_permission_group(
    IN p_permission_group_id VARCHAR(64)
)
BEGIN
    SELECT 
        ug.id,
        ug.group_hash,
        ug.group_name,
        ug.group_description,
        ugpg.assigned_at,
        ugpg.assigned_by
    FROM user_group_permission_groups ugpg
    INNER JOIN user_groups ug ON ugpg.user_group_id = ug.id
    WHERE ugpg.permission_group_id = p_permission_group_id
      AND ugpg.is_active = TRUE
      AND ug.is_active = TRUE
    ORDER BY ug.group_name;
END$$

-- =================== DIRECT USER PERMISSION GROUP ASSIGNMENTS ===================

-- Assign permission group directly to user
DROP PROCEDURE IF EXISTS sp_assign_permission_group_to_user$$
CREATE PROCEDURE sp_assign_permission_group_to_user(
    IN p_link_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64),
    IN p_assigned_by VARCHAR(64),
    IN p_notes TEXT
)
BEGIN
    INSERT INTO user_permission_groups (
        id, user_id, permission_group_id, assigned_by, notes, is_active
    ) VALUES (
        p_link_id, p_user_id, p_permission_group_id, p_assigned_by, p_notes, TRUE
    )
    ON DUPLICATE KEY UPDATE
        is_active = TRUE,
        assigned_at = CURRENT_TIMESTAMP,
        assigned_by = p_assigned_by,
        notes = p_notes,
        removed_at = NULL,
        removed_by = NULL;
END$$

-- Remove permission group from user
DROP PROCEDURE IF EXISTS sp_remove_permission_group_from_user$$
CREATE PROCEDURE sp_remove_permission_group_from_user(
    IN p_user_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64),
    IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE user_permission_groups
    SET is_active = FALSE,
        removed_at = CURRENT_TIMESTAMP,
        removed_by = p_removed_by
    WHERE user_id = p_user_id
      AND permission_group_id = p_permission_group_id
      AND is_active = TRUE;
END$$

-- Get permission groups directly assigned to a user
DROP PROCEDURE IF EXISTS sp_get_user_permission_groups$$
CREATE PROCEDURE sp_get_user_permission_groups(
    IN p_user_id VARCHAR(64)
)
BEGIN
    SELECT 
        pg.id,
        pg.group_hash,
        pg.group_name,
        pg.group_display_name,
        pg.group_description,
        pg.group_category,
        upg.assigned_at,
        upg.assigned_by,
        upg.notes
    FROM user_permission_groups upg
    INNER JOIN global_permission_groups pg ON upg.permission_group_id = pg.id
    WHERE upg.user_id = p_user_id
      AND upg.is_active = TRUE
      AND pg.is_active = TRUE
    ORDER BY pg.group_name;
END$$

-- Get users that have a specific permission group directly assigned
DROP PROCEDURE IF EXISTS sp_get_users_with_permission_group$$
CREATE PROCEDURE sp_get_users_with_permission_group(
    IN p_permission_group_id VARCHAR(64)
)
BEGIN
    SELECT 
        u.id,
        u.user_hash,
        u.username,
        u.email,
        upg.assigned_at,
        upg.assigned_by,
        upg.notes
    FROM user_permission_groups upg
    INNER JOIN users u ON upg.user_id = u.id
    WHERE upg.permission_group_id = p_permission_group_id
      AND upg.is_active = TRUE
      AND u.is_active = TRUE
    ORDER BY u.username;
END$$

-- =================== PERMISSION GROUP PROJECT CATALOG (METADATA ONLY) ===================

-- Add permission group to project catalog
DROP PROCEDURE IF EXISTS sp_add_permission_group_to_project_catalog$$
CREATE PROCEDURE sp_add_permission_group_to_project_catalog(
    IN p_catalog_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_catalog_purpose VARCHAR(255),
    IN p_notes TEXT,
    IN p_added_by VARCHAR(64)
)
BEGIN
    INSERT INTO permission_group_project_catalog (
        id, permission_group_id, project_id, catalog_purpose, notes, added_by, is_active
    ) VALUES (
        p_catalog_id, p_permission_group_id, p_project_id, p_catalog_purpose, p_notes, p_added_by, TRUE
    )
    ON DUPLICATE KEY UPDATE
        is_active = TRUE,
        catalog_purpose = p_catalog_purpose,
        notes = p_notes,
        added_at = CURRENT_TIMESTAMP,
        added_by = p_added_by,
        removed_at = NULL,
        removed_by = NULL;
END$$

-- Remove permission group from project catalog
DROP PROCEDURE IF EXISTS sp_remove_permission_group_from_project_catalog$$
CREATE PROCEDURE sp_remove_permission_group_from_project_catalog(
    IN p_permission_group_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE permission_group_project_catalog
    SET is_active = FALSE,
        removed_at = CURRENT_TIMESTAMP,
        removed_by = p_removed_by
    WHERE permission_group_id = p_permission_group_id
      AND project_id = p_project_id
      AND is_active = TRUE;
END$$

-- Get permission groups cataloged for a project
DROP PROCEDURE IF EXISTS sp_get_project_cataloged_permission_groups$$
CREATE PROCEDURE sp_get_project_cataloged_permission_groups(
    IN p_project_id VARCHAR(64)
)
BEGIN
    SELECT 
        pg.id,
        pg.group_hash,
        pg.group_name,
        pg.group_display_name,
        pg.group_description,
        pg.group_category,
        pgpc.catalog_purpose,
        pgpc.notes,
        pgpc.added_at,
        pgpc.added_by
    FROM permission_group_project_catalog pgpc
    INNER JOIN global_permission_groups pg ON pgpc.permission_group_id = pg.id
    WHERE pgpc.project_id = p_project_id
      AND pgpc.is_active = TRUE
      AND pg.is_active = TRUE
    ORDER BY pg.group_name;
END$$

-- Get projects that catalog a specific permission group
DROP PROCEDURE IF EXISTS sp_get_permission_group_cataloged_projects$$
CREATE PROCEDURE sp_get_permission_group_cataloged_projects(
    IN p_permission_group_id VARCHAR(64)
)
BEGIN
    SELECT 
        p.id,
        p.project_hash,
        p.project_name,
        p.project_description,
        pgpc.catalog_purpose,
        pgpc.notes,
        pgpc.added_at,
        pgpc.added_by
    FROM permission_group_project_catalog pgpc
    INNER JOIN projects p ON pgpc.project_id = p.id
    WHERE pgpc.permission_group_id = p_permission_group_id
      AND pgpc.is_active = TRUE
      AND p.is_active = TRUE
    ORDER BY p.project_name;
END$$

-- =================== ENHANCED PERMISSION RESOLUTION ===================

-- Get all permissions for a user from all sources
DROP PROCEDURE IF EXISTS sp_get_user_all_permissions$$
CREATE PROCEDURE sp_get_user_all_permissions(
    IN p_user_id VARCHAR(64)
)
BEGIN
    SELECT DISTINCT p.permission_name
    FROM global_permissions p
    INNER JOIN global_permission_group_permissions pgp ON p.id = pgp.permission_id
    INNER JOIN global_permission_groups pg ON pgp.permission_group_id = pg.id
    WHERE pg.id IN (
        -- From role (Rev1)
        SELECT rpg.permission_group_id
        FROM role_permission_groups rpg
        INNER JOIN users u ON u.role_id = rpg.role_id
        WHERE u.id = p_user_id
          AND rpg.is_active = TRUE
          AND u.is_active = TRUE
        
        UNION
        
        -- From user groups
        SELECT ugpg.permission_group_id
        FROM user_group_permission_groups ugpg
        INNER JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id
        WHERE ugm.user_id = p_user_id
          AND ugpg.is_active = TRUE
          AND ugm.is_active = TRUE
        
        UNION
        
        -- From direct user assignments
        SELECT upg.permission_group_id
        FROM user_permission_groups upg
        WHERE upg.user_id = p_user_id
          AND upg.is_active = TRUE
    )
    AND pgp.is_active = TRUE
    AND p.is_active = TRUE
    ORDER BY p.permission_name;
END$$

-- Check if user has specific permission from all sources
DROP PROCEDURE IF EXISTS sp_check_user_has_permission$$
CREATE PROCEDURE sp_check_user_has_permission(
    IN p_user_id VARCHAR(64),
    IN p_permission_name VARCHAR(100)
)
BEGIN
    SELECT COUNT(*) > 0 AS has_permission
    FROM global_permissions p
    INNER JOIN global_permission_group_permissions pgp ON p.id = pgp.permission_id
    INNER JOIN global_permission_groups pg ON pgp.permission_group_id = pg.id
    WHERE p.permission_name = p_permission_name
      AND pg.id IN (
          -- From role (Rev1)
          SELECT rpg.permission_group_id
          FROM role_permission_groups rpg
          INNER JOIN users u ON u.role_id = rpg.role_id
          WHERE u.id = p_user_id
            AND rpg.is_active = TRUE
            AND u.is_active = TRUE
          
          UNION
          
          -- From user groups
          SELECT ugpg.permission_group_id
          FROM user_group_permission_groups ugpg
          INNER JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id
          WHERE ugm.user_id = p_user_id
            AND ugpg.is_active = TRUE
            AND ugm.is_active = TRUE
          
          UNION
          
          -- From direct user assignments
          SELECT upg.permission_group_id
          FROM user_permission_groups upg
          WHERE upg.user_id = p_user_id
            AND upg.is_active = TRUE
      )
      AND pgp.is_active = TRUE
      AND p.is_active = TRUE;
END$$

-- Get detailed permission sources for a user
DROP PROCEDURE IF EXISTS sp_get_user_permission_sources$$
CREATE PROCEDURE sp_get_user_permission_sources(
    IN p_user_id VARCHAR(64)
)
BEGIN
    -- From role
    SELECT 
        'role' AS source_type,
        r.role_name AS source_name,
        pg.group_name AS permission_group_name,
        pg.group_hash AS permission_group_hash,
        NULL AS notes
    FROM role_permission_groups rpg
    INNER JOIN roles r ON rpg.role_id = r.id
    INNER JOIN global_permission_groups pg ON rpg.permission_group_id = pg.id
    INNER JOIN users u ON u.role_id = r.id
    WHERE u.id = p_user_id
      AND rpg.is_active = TRUE
      AND r.is_active = TRUE
      AND pg.is_active = TRUE
      AND u.is_active = TRUE
    
    UNION ALL
    
    -- From user groups
    SELECT 
        'user_group' AS source_type,
        ug.group_name AS source_name,
        pg.group_name AS permission_group_name,
        pg.group_hash AS permission_group_hash,
        NULL AS notes
    FROM user_group_permission_groups ugpg
    INNER JOIN user_groups ug ON ugpg.user_group_id = ug.id
    INNER JOIN global_permission_groups pg ON ugpg.permission_group_id = pg.id
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    WHERE ugm.user_id = p_user_id
      AND ugpg.is_active = TRUE
      AND ug.is_active = TRUE
      AND pg.is_active = TRUE
      AND ugm.is_active = TRUE
    
    UNION ALL
    
    -- From direct assignments
    SELECT 
        'direct' AS source_type,
        'Direct Assignment' AS source_name,
        pg.group_name AS permission_group_name,
        pg.group_hash AS permission_group_hash,
        upg.notes
    FROM user_permission_groups upg
    INNER JOIN global_permission_groups pg ON upg.permission_group_id = pg.id
    WHERE upg.user_id = p_user_id
      AND upg.is_active = TRUE
      AND pg.is_active = TRUE;
END$$

DELIMITER ;
