-- ===================================================================================
-- GLOBAL ROLE SYSTEM STORED PROCEDURES
-- ===================================================================================
-- This file contains all stored procedures related to the global role system:
-- - Role management
-- - Permission group management
-- - Permission management
-- - Role-permission group links
-- - User role assignment
-- - Permission resolution
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- ROLE MANAGEMENT
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_global_create_role$$
CREATE PROCEDURE sp_global_create_role(
    IN p_role_id VARCHAR(64), IN p_role_hash VARCHAR(255), IN p_role_name VARCHAR(100),
    IN p_role_display_name VARCHAR(255), IN p_role_description TEXT,
    IN p_role_priority INT, IN p_is_system_role BOOLEAN, IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO roles (id, role_hash, role_name, role_display_name, role_description,
                      role_priority, is_system_role, created_by, created_at, is_active)
    VALUES (p_role_id, p_role_hash, p_role_name, p_role_display_name, p_role_description,
            p_role_priority, p_is_system_role, p_created_by, NOW(), TRUE);
    SELECT * FROM roles WHERE id = p_role_id;
END$$

DROP PROCEDURE IF EXISTS sp_global_get_role_by_hash$$
CREATE PROCEDURE sp_global_get_role_by_hash(IN p_role_hash VARCHAR(255))
BEGIN
    SELECT * FROM roles WHERE role_hash = p_role_hash AND is_active = TRUE;
END$$

DROP PROCEDURE IF EXISTS sp_global_list_roles$$
CREATE PROCEDURE sp_global_list_roles(IN p_limit INT, IN p_offset INT)
BEGIN
    SELECT * FROM roles WHERE is_active = TRUE 
    ORDER BY role_priority DESC, role_name ASC LIMIT p_limit OFFSET p_offset;
END$$

DROP PROCEDURE IF EXISTS sp_global_update_role$$
CREATE PROCEDURE sp_global_update_role(
    IN p_role_id VARCHAR(64), IN p_role_display_name VARCHAR(255),
    IN p_role_description TEXT, IN p_role_priority INT
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

DROP PROCEDURE IF EXISTS sp_global_delete_role$$
CREATE PROCEDURE sp_global_delete_role(IN p_role_id VARCHAR(64))
BEGIN
    UPDATE roles SET is_active = FALSE, updated_at = NOW() WHERE id = p_role_id;
    SELECT ROW_COUNT() as rows_affected;
END$$

-- ===================================================================================
-- PERMISSION GROUP MANAGEMENT
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_global_create_permission_group$$
CREATE PROCEDURE sp_global_create_permission_group(
    IN p_group_id VARCHAR(64), IN p_group_hash VARCHAR(255), IN p_group_name VARCHAR(100),
    IN p_group_display_name VARCHAR(255), IN p_group_description TEXT,
    IN p_group_category VARCHAR(50), IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO global_permission_groups (id, group_hash, group_name, group_display_name,
                                         group_description, group_category, created_by, created_at, is_active)
    VALUES (p_group_id, p_group_hash, p_group_name, p_group_display_name,
            p_group_description, p_group_category, p_created_by, NOW(), TRUE);
    SELECT * FROM global_permission_groups WHERE id = p_group_id;
END$$

DROP PROCEDURE IF EXISTS sp_global_get_permission_group_by_hash$$
CREATE PROCEDURE sp_global_get_permission_group_by_hash(IN p_group_hash VARCHAR(255))
BEGIN
    SELECT * FROM global_permission_groups WHERE group_hash = p_group_hash AND is_active = TRUE;
END$$

DROP PROCEDURE IF EXISTS sp_global_list_permission_groups$$
CREATE PROCEDURE sp_global_list_permission_groups(IN p_category VARCHAR(50), IN p_limit INT, IN p_offset INT)
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

-- ===================================================================================
-- PERMISSION MANAGEMENT
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_global_create_permission$$
CREATE PROCEDURE sp_global_create_permission(
    IN p_permission_id VARCHAR(64), IN p_permission_hash VARCHAR(255),
    IN p_permission_name VARCHAR(100), IN p_permission_display_name VARCHAR(255),
    IN p_permission_description TEXT, IN p_permission_category VARCHAR(50), IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO global_permissions (id, permission_hash, permission_name, permission_display_name,
                                   permission_description, permission_category, created_by, created_at, is_active)
    VALUES (p_permission_id, p_permission_hash, p_permission_name, p_permission_display_name,
            p_permission_description, p_permission_category, p_created_by, NOW(), TRUE);
    SELECT * FROM global_permissions WHERE id = p_permission_id;
END$$

DROP PROCEDURE IF EXISTS sp_global_get_permission_by_hash$$
CREATE PROCEDURE sp_global_get_permission_by_hash(IN p_permission_hash VARCHAR(255))
BEGIN
    SELECT * FROM global_permissions WHERE permission_hash = p_permission_hash AND is_active = TRUE;
END$$

DROP PROCEDURE IF EXISTS sp_global_list_permissions$$
CREATE PROCEDURE sp_global_list_permissions(IN p_category VARCHAR(50), IN p_limit INT, IN p_offset INT)
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

-- ===================================================================================
-- ROLE-PERMISSION GROUP LINKS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_global_assign_permission_group_to_role$$
CREATE PROCEDURE sp_global_assign_permission_group_to_role(
    IN p_link_id VARCHAR(64), IN p_role_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64), IN p_assigned_by VARCHAR(64)
)
BEGIN
    INSERT INTO role_permission_groups (id, role_id, permission_group_id, assigned_by, assigned_at, is_active)
    VALUES (p_link_id, p_role_id, p_permission_group_id, p_assigned_by, NOW(), TRUE)
    ON DUPLICATE KEY UPDATE is_active = TRUE, assigned_at = NOW(), assigned_by = p_assigned_by;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_global_get_role_permission_groups$$
CREATE PROCEDURE sp_global_get_role_permission_groups(IN p_role_id VARCHAR(64))
BEGIN
    SELECT gpg.* FROM global_permission_groups gpg
    JOIN role_permission_groups rpg ON gpg.id = rpg.permission_group_id
    WHERE rpg.role_id = p_role_id AND rpg.is_active = TRUE AND gpg.is_active = TRUE
    ORDER BY gpg.group_name;
END$$

-- ===================================================================================
-- PERMISSION GROUP-PERMISSION LINKS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_global_assign_permission_to_group$$
CREATE PROCEDURE sp_global_assign_permission_to_group(
    IN p_link_id VARCHAR(64), IN p_permission_group_id VARCHAR(64),
    IN p_permission_id VARCHAR(64), IN p_granted_by VARCHAR(64)
)
BEGIN
    INSERT INTO global_permission_group_permissions (id, permission_group_id, permission_id, granted_by, granted_at, is_active)
    VALUES (p_link_id, p_permission_group_id, p_permission_id, p_granted_by, NOW(), TRUE)
    ON DUPLICATE KEY UPDATE is_active = TRUE, granted_at = NOW(), granted_by = p_granted_by;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_global_get_permission_group_permissions$$
CREATE PROCEDURE sp_global_get_permission_group_permissions(IN p_permission_group_id VARCHAR(64))
BEGIN
    SELECT gp.* FROM global_permissions gp
    JOIN global_permission_group_permissions pgp ON gp.id = pgp.permission_id
    WHERE pgp.permission_group_id = p_permission_group_id AND pgp.is_active = TRUE AND gp.is_active = TRUE
    ORDER BY gp.permission_name;
END$$

-- ===================================================================================
-- USER ROLE ASSIGNMENT
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_global_assign_role_to_user$$
CREATE PROCEDURE sp_global_assign_role_to_user(IN p_user_id VARCHAR(64), IN p_role_id VARCHAR(64))
BEGIN
    UPDATE users SET role_id = p_role_id, updated_at = NOW() WHERE id = p_user_id;
    SELECT ROW_COUNT() as rows_affected;
END$$

DROP PROCEDURE IF EXISTS sp_global_get_user_role$$
CREATE PROCEDURE sp_global_get_user_role(IN p_user_id VARCHAR(64))
BEGIN
    SELECT r.* FROM roles r
    JOIN users u ON r.id = u.role_id
    WHERE u.id = p_user_id AND u.is_active = TRUE AND r.is_active = TRUE;
END$$

-- ===================================================================================
-- PERMISSION RESOLUTION
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_global_get_user_permissions$$
CREATE PROCEDURE sp_global_get_user_permissions(IN p_user_id VARCHAR(64))
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

DROP PROCEDURE IF EXISTS sp_global_check_user_has_permission$$
CREATE PROCEDURE sp_global_check_user_has_permission(IN p_user_id VARCHAR(64), IN p_permission_name VARCHAR(100))
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

DELIMITER ;

-- ===================================================================================
-- GLOBAL ROLE SYSTEM PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Global role system stored procedures created successfully!' as status,
       '17 procedures for role and permission management' as details;

