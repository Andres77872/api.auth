-- ===================================================================================
-- PERMISSION ASSIGNMENT SYSTEM STORED PROCEDURES
-- ===================================================================================
-- This file contains all stored procedures related to permission assignments:
-- - User group permission group assignments
-- - Direct user permission group assignments
-- - Enhanced permission resolution
-- - Permission source tracking
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- USER GROUP PERMISSION GROUP ASSIGNMENTS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_assign_permission_group_to_user_group$$
CREATE PROCEDURE sp_assign_permission_group_to_user_group(
    IN p_link_id VARCHAR(64), IN p_user_group_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64), IN p_assigned_by VARCHAR(64)
)
BEGIN
    INSERT INTO user_group_permission_groups (id, user_group_id, permission_group_id, assigned_by, is_active)
    VALUES (p_link_id, p_user_group_id, p_permission_group_id, p_assigned_by, TRUE)
    ON DUPLICATE KEY UPDATE is_active = TRUE, assigned_at = CURRENT_TIMESTAMP, assigned_by = p_assigned_by,
                            removed_at = NULL, removed_by = NULL;
END$$

DROP PROCEDURE IF EXISTS sp_remove_permission_group_from_user_group$$
CREATE PROCEDURE sp_remove_permission_group_from_user_group(
    IN p_user_group_id VARCHAR(64), IN p_permission_group_id VARCHAR(64), IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE user_group_permission_groups SET is_active = FALSE, removed_at = CURRENT_TIMESTAMP, removed_by = p_removed_by
    WHERE user_group_id = p_user_group_id AND permission_group_id = p_permission_group_id AND is_active = TRUE;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_group_permission_groups$$
CREATE PROCEDURE sp_get_user_group_permission_groups(IN p_user_group_id VARCHAR(64))
BEGIN
    SELECT pg.id, pg.group_hash, pg.group_name, pg.group_display_name, pg.group_description,
           pg.group_category, ugpg.assigned_at, ugpg.assigned_by
    FROM user_group_permission_groups ugpg
    INNER JOIN global_permission_groups pg ON ugpg.permission_group_id = pg.id
    WHERE ugpg.user_group_id = p_user_group_id AND ugpg.is_active = TRUE AND pg.is_active = TRUE
    ORDER BY pg.group_name;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_groups_with_permission_group$$
CREATE PROCEDURE sp_get_user_groups_with_permission_group(IN p_permission_group_id VARCHAR(64))
BEGIN
    SELECT ug.id, ug.group_hash, ug.group_name, ug.group_description,
           ugpg.assigned_at, ugpg.assigned_by
    FROM user_group_permission_groups ugpg
    INNER JOIN user_groups ug ON ugpg.user_group_id = ug.id
    WHERE ugpg.permission_group_id = p_permission_group_id AND ugpg.is_active = TRUE AND ug.is_active = TRUE
    ORDER BY ug.group_name;
END$$

-- ===================================================================================
-- DIRECT USER PERMISSION GROUP ASSIGNMENTS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_assign_permission_group_to_user$$
CREATE PROCEDURE sp_assign_permission_group_to_user(
    IN p_link_id VARCHAR(64), IN p_user_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64), IN p_assigned_by VARCHAR(64), IN p_notes TEXT
)
BEGIN
    INSERT INTO user_permission_groups (id, user_id, permission_group_id, assigned_by, notes, is_active)
    VALUES (p_link_id, p_user_id, p_permission_group_id, p_assigned_by, p_notes, TRUE)
    ON DUPLICATE KEY UPDATE is_active = TRUE, assigned_at = CURRENT_TIMESTAMP, assigned_by = p_assigned_by,
                            notes = p_notes, removed_at = NULL, removed_by = NULL;
END$$

DROP PROCEDURE IF EXISTS sp_remove_permission_group_from_user$$
CREATE PROCEDURE sp_remove_permission_group_from_user(
    IN p_user_id VARCHAR(64), IN p_permission_group_id VARCHAR(64), IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE user_permission_groups SET is_active = FALSE, removed_at = CURRENT_TIMESTAMP, removed_by = p_removed_by
    WHERE user_id = p_user_id AND permission_group_id = p_permission_group_id AND is_active = TRUE;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_permission_groups$$
CREATE PROCEDURE sp_get_user_permission_groups(IN p_user_id VARCHAR(64))
BEGIN
    SELECT pg.id, pg.group_hash, pg.group_name, pg.group_display_name, pg.group_description,
           pg.group_category, upg.assigned_at, upg.assigned_by, upg.notes
    FROM user_permission_groups upg
    INNER JOIN global_permission_groups pg ON upg.permission_group_id = pg.id
    WHERE upg.user_id = p_user_id AND upg.is_active = TRUE AND pg.is_active = TRUE
    ORDER BY pg.group_name;
END$$

DROP PROCEDURE IF EXISTS sp_get_users_with_permission_group$$
CREATE PROCEDURE sp_get_users_with_permission_group(IN p_permission_group_id VARCHAR(64))
BEGIN
    SELECT u.id, u.user_hash, u.username, u.email, u.user_type, u.role_id,
           upg.assigned_at, upg.assigned_by, upg.notes
    FROM user_permission_groups upg
    INNER JOIN users u ON upg.user_id = u.id
    WHERE upg.permission_group_id = p_permission_group_id AND upg.is_active = TRUE AND u.is_active = TRUE
    ORDER BY u.username;
END$$

-- ===================================================================================
-- ENHANCED PERMISSION RESOLUTION
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_user_all_permissions$$
CREATE PROCEDURE sp_get_user_all_permissions(IN p_user_id VARCHAR(64))
BEGIN
    SELECT DISTINCT p.permission_name FROM global_permissions p
    INNER JOIN global_permission_group_permissions pgp ON p.id = pgp.permission_id
    INNER JOIN global_permission_groups pg ON pgp.permission_group_id = pg.id
    WHERE pg.id IN (
        SELECT rpg.permission_group_id FROM role_permission_groups rpg
        INNER JOIN users u ON u.role_id = rpg.role_id
        WHERE u.id = p_user_id AND rpg.is_active = TRUE AND u.is_active = TRUE
        UNION
        SELECT ugpg.permission_group_id FROM user_group_permission_groups ugpg
        INNER JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id
        WHERE ugm.user_id = p_user_id AND ugpg.is_active = TRUE AND ugm.is_active = TRUE
        UNION
        SELECT upg.permission_group_id FROM user_permission_groups upg
        WHERE upg.user_id = p_user_id AND upg.is_active = TRUE
    ) AND pgp.is_active = TRUE AND p.is_active = TRUE
    ORDER BY p.permission_name;
END$$

DROP PROCEDURE IF EXISTS sp_check_user_has_permission_extended$$
CREATE PROCEDURE sp_check_user_has_permission_extended(IN p_user_id VARCHAR(64), IN p_permission_name VARCHAR(100))
BEGIN
    SELECT COUNT(*) > 0 AS has_permission FROM global_permissions p
    INNER JOIN global_permission_group_permissions pgp ON p.id = pgp.permission_id
    INNER JOIN global_permission_groups pg ON pgp.permission_group_id = pg.id
    WHERE p.permission_name = p_permission_name AND pg.id IN (
        SELECT rpg.permission_group_id FROM role_permission_groups rpg
        INNER JOIN users u ON u.role_id = rpg.role_id
        WHERE u.id = p_user_id AND rpg.is_active = TRUE AND u.is_active = TRUE
        UNION
        SELECT ugpg.permission_group_id FROM user_group_permission_groups ugpg
        INNER JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id
        WHERE ugm.user_id = p_user_id AND ugpg.is_active = TRUE AND ugm.is_active = TRUE
        UNION
        SELECT upg.permission_group_id FROM user_permission_groups upg
        WHERE upg.user_id = p_user_id AND upg.is_active = TRUE
    ) AND pgp.is_active = TRUE AND p.is_active = TRUE;
END$$

-- ===================================================================================
-- PERMISSION SOURCE TRACKING
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_user_permission_sources$$
CREATE PROCEDURE sp_get_user_permission_sources(IN p_user_id VARCHAR(64))
BEGIN
    SELECT 'role' AS source_type, r.role_name AS source_name, pg.group_name AS permission_group_name,
           pg.group_hash AS permission_group_hash, NULL AS notes
    FROM role_permission_groups rpg
    INNER JOIN roles r ON rpg.role_id = r.id
    INNER JOIN global_permission_groups pg ON rpg.permission_group_id = pg.id
    INNER JOIN users u ON u.role_id = r.id
    WHERE u.id = p_user_id AND rpg.is_active = TRUE AND r.is_active = TRUE
      AND pg.is_active = TRUE AND u.is_active = TRUE
    UNION ALL
    SELECT 'user_group' AS source_type, ug.group_name AS source_name, pg.group_name AS permission_group_name,
           pg.group_hash AS permission_group_hash, NULL AS notes
    FROM user_group_permission_groups ugpg
    INNER JOIN user_groups ug ON ugpg.user_group_id = ug.id
    INNER JOIN global_permission_groups pg ON ugpg.permission_group_id = pg.id
    INNER JOIN user_group_members ugm ON ug.id = ugm.user_group_id
    WHERE ugm.user_id = p_user_id AND ugpg.is_active = TRUE AND ug.is_active = TRUE
      AND pg.is_active = TRUE AND ugm.is_active = TRUE
    UNION ALL
    SELECT 'direct' AS source_type, 'Direct Assignment' AS source_name, pg.group_name AS permission_group_name,
           pg.group_hash AS permission_group_hash, upg.notes
    FROM user_permission_groups upg
    INNER JOIN global_permission_groups pg ON upg.permission_group_id = pg.id
    WHERE upg.user_id = p_user_id AND upg.is_active = TRUE AND pg.is_active = TRUE;
END$$

DELIMITER ;

-- ===================================================================================
-- PERMISSION ASSIGNMENT PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Permission assignment system stored procedures created successfully!' as status,
       '11 procedures for permission assignment and resolution' as details;

