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

-- ===================================================================================
-- PROJECT-SCOPED ROLE ASSIGNMENTS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_assign_scoped_role_to_user_group$$
CREATE PROCEDURE sp_assign_scoped_role_to_user_group(
    IN p_link_id VARCHAR(64), IN p_user_group_id VARCHAR(64),
    IN p_project_group_id VARCHAR(64), IN p_role_id VARCHAR(64), IN p_assigned_by VARCHAR(64)
)
BEGIN
    INSERT INTO user_group_project_group_roles (id, user_group_id, project_group_id, role_id, assigned_by, is_active)
    VALUES (p_link_id, p_user_group_id, p_project_group_id, p_role_id, p_assigned_by, TRUE)
    ON DUPLICATE KEY UPDATE is_active = TRUE, assigned_at = CURRENT_TIMESTAMP, assigned_by = p_assigned_by,
                            removed_at = NULL, removed_by = NULL;
END$$

DROP PROCEDURE IF EXISTS sp_remove_scoped_role_from_user_group$$
CREATE PROCEDURE sp_remove_scoped_role_from_user_group(
    IN p_user_group_id VARCHAR(64), IN p_project_group_id VARCHAR(64), 
    IN p_role_id VARCHAR(64), IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE user_group_project_group_roles 
    SET is_active = FALSE, removed_at = CURRENT_TIMESTAMP, removed_by = p_removed_by
    WHERE user_group_id = p_user_group_id AND project_group_id = p_project_group_id 
      AND role_id = p_role_id AND is_active = TRUE;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_scoped_roles$$
CREATE PROCEDURE sp_get_user_scoped_roles(IN p_user_id VARCHAR(64))
BEGIN
    SELECT 
        r.id as role_id, r.role_hash, r.role_name, r.role_display_name, r.role_priority,
        pg.id as project_group_id, pg.group_hash as project_group_hash, pg.group_name as project_group_name,
        ug.id as user_group_id, ug.group_name as user_group_name,
        ugpgr.assigned_at
    FROM user_group_members ugm
    INNER JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = TRUE
    INNER JOIN user_group_project_group_roles ugpgr ON ug.id = ugpgr.user_group_id AND ugpgr.is_active = TRUE
    INNER JOIN project_groups pg ON ugpgr.project_group_id = pg.id AND pg.is_active = TRUE
    INNER JOIN roles r ON ugpgr.role_id = r.id AND r.is_active = TRUE
    WHERE ugm.user_id = p_user_id AND ugm.is_active = TRUE
    ORDER BY pg.group_name, r.role_priority DESC;
END$$

DROP PROCEDURE IF EXISTS sp_get_user_role_for_project$$
CREATE PROCEDURE sp_get_user_role_for_project(IN p_user_id VARCHAR(64), IN p_project_id VARCHAR(64))
BEGIN
    -- Returns highest priority role for user in specific project context
    -- First checks scoped roles, then falls back to global role
    SELECT 
        r.id as role_id, r.role_hash, r.role_name, r.role_display_name, r.role_priority,
        CASE WHEN ugpgr.id IS NOT NULL THEN 'scoped' ELSE 'global' END as role_scope,
        pg.group_name as project_group_name
    FROM users u
    LEFT JOIN (
        -- Scoped roles via user group -> project group -> role
        SELECT ugpgr.role_id, ugpgr.id, pg.group_name, pgm.project_id
        FROM user_group_members ugm
        INNER JOIN user_group_project_group_roles ugpgr ON ugm.user_group_id = ugpgr.user_group_id AND ugpgr.is_active = TRUE
        INNER JOIN project_groups pg ON ugpgr.project_group_id = pg.id AND pg.is_active = TRUE
        INNER JOIN project_group_members pgm ON pg.id = pgm.project_group_id AND pgm.is_active = TRUE
        WHERE ugm.user_id = p_user_id AND ugm.is_active = TRUE AND pgm.project_id = p_project_id
    ) scoped ON 1=1
    LEFT JOIN project_groups pg ON scoped.group_name = pg.group_name
    LEFT JOIN user_group_project_group_roles ugpgr ON scoped.id = ugpgr.id
    LEFT JOIN roles r ON COALESCE(scoped.role_id, u.role_id) = r.id AND r.is_active = TRUE
    WHERE u.id = p_user_id AND u.is_active = TRUE
    ORDER BY r.role_priority DESC
    LIMIT 1;
END$$

-- ===================================================================================
-- SCOPED PERMISSION ASSIGNMENTS WITH GRANT/DENY
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_assign_scoped_permission_group$$
CREATE PROCEDURE sp_assign_scoped_permission_group(
    IN p_link_id VARCHAR(64), IN p_user_group_id VARCHAR(64),
    IN p_project_group_id VARCHAR(64), IN p_permission_group_id VARCHAR(64),
    IN p_permission_type VARCHAR(10), IN p_priority INT, IN p_assigned_by VARCHAR(64)
)
BEGIN
    INSERT INTO user_group_project_group_permissions 
        (id, user_group_id, project_group_id, permission_group_id, permission_type, priority, assigned_by, is_active)
    VALUES (p_link_id, p_user_group_id, p_project_group_id, p_permission_group_id, 
            COALESCE(p_permission_type, 'grant'), COALESCE(p_priority, 0), p_assigned_by, TRUE)
    ON DUPLICATE KEY UPDATE 
        is_active = TRUE, 
        permission_type = COALESCE(p_permission_type, permission_type),
        priority = COALESCE(p_priority, priority),
        assigned_at = CURRENT_TIMESTAMP, 
        assigned_by = p_assigned_by,
        removed_at = NULL, 
        removed_by = NULL;
END$$

DROP PROCEDURE IF EXISTS sp_check_user_permission_for_project_with_deny$$
CREATE PROCEDURE sp_check_user_permission_for_project_with_deny(
    IN p_user_id VARCHAR(64), IN p_project_id VARCHAR(64), IN p_permission_name VARCHAR(100)
)
BEGIN
    DECLARE v_user_type VARCHAR(20);
    DECLARE v_has_grant BOOLEAN DEFAULT FALSE;
    DECLARE v_has_deny BOOLEAN DEFAULT FALSE;
    DECLARE v_max_deny_priority INT DEFAULT 0;
    DECLARE v_max_grant_priority INT DEFAULT 0;
    
    -- Check user type (root bypasses all checks)
    SELECT user_type INTO v_user_type FROM users WHERE id = p_user_id AND is_active = TRUE;
    
    IF v_user_type = 'root' THEN
        SELECT TRUE as has_permission, 'root_bypass' as source;
    ELSE
        -- Check for scoped deny permissions (higher priority denies override grants)
        SELECT 
            MAX(CASE WHEN ugpgp.permission_type = 'deny' THEN ugpgp.priority ELSE 0 END),
            MAX(CASE WHEN ugpgp.permission_type = 'grant' THEN ugpgp.priority ELSE 0 END),
            MAX(CASE WHEN ugpgp.permission_type = 'deny' THEN 1 ELSE 0 END),
            MAX(CASE WHEN ugpgp.permission_type = 'grant' THEN 1 ELSE 0 END)
        INTO v_max_deny_priority, v_max_grant_priority, v_has_deny, v_has_grant
        FROM user_group_members ugm
        INNER JOIN user_group_project_group_permissions ugpgp ON ugm.user_group_id = ugpgp.user_group_id AND ugpgp.is_active = TRUE
        INNER JOIN project_group_members pgm ON ugpgp.project_group_id = pgm.project_group_id AND pgm.is_active = TRUE
        INNER JOIN global_permission_group_permissions gpgp ON ugpgp.permission_group_id = gpgp.permission_group_id AND gpgp.is_active = TRUE
        INNER JOIN global_permissions gp ON gpgp.permission_id = gp.id AND gp.is_active = TRUE
        WHERE ugm.user_id = p_user_id AND ugm.is_active = TRUE 
          AND pgm.project_id = p_project_id AND gp.permission_name = p_permission_name;
        
        -- Deny with higher or equal priority wins
        IF v_has_deny = TRUE AND v_max_deny_priority >= v_max_grant_priority THEN
            SELECT FALSE as has_permission, 'scoped_deny' as source;
        ELSEIF v_has_grant = TRUE THEN
            SELECT TRUE as has_permission, 'scoped_grant' as source;
        ELSE
            -- Fall back to global permissions check
            SELECT 
                COUNT(*) > 0 as has_permission,
                'global' as source
            FROM global_permissions p
            INNER JOIN global_permission_group_permissions pgp ON p.id = pgp.permission_id
            WHERE p.permission_name = p_permission_name AND pgp.permission_group_id IN (
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
        END IF;
    END IF;
END$$

-- ===================================================================================
-- GET USER ALL GROUPS (Including Inherited)
-- NOTE: Recursive queries can be expensive - consider caching for frequent use
-- ===================================================================================

-- ===================================================================================
-- PERMISSION GROUP PROJECT CATALOG (METADATA ONLY - for UI suggestions)
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_add_permission_group_to_project_catalog$$
CREATE PROCEDURE sp_add_permission_group_to_project_catalog(
    IN p_catalog_id VARCHAR(64), IN p_permission_group_id VARCHAR(64),
    IN p_project_id VARCHAR(64), IN p_catalog_purpose VARCHAR(255),
    IN p_notes TEXT, IN p_added_by VARCHAR(64)
)
BEGIN
    INSERT INTO permission_group_project_catalog 
        (id, permission_group_id, project_id, catalog_purpose, notes, added_by, is_active)
    VALUES (p_catalog_id, p_permission_group_id, p_project_id, p_catalog_purpose, p_notes, p_added_by, TRUE)
    ON DUPLICATE KEY UPDATE 
        is_active = TRUE, 
        catalog_purpose = COALESCE(p_catalog_purpose, catalog_purpose),
        notes = COALESCE(p_notes, notes),
        added_at = CURRENT_TIMESTAMP, 
        added_by = p_added_by,
        removed_at = NULL, 
        removed_by = NULL;
END$$

DROP PROCEDURE IF EXISTS sp_remove_permission_group_from_project_catalog$$
CREATE PROCEDURE sp_remove_permission_group_from_project_catalog(
    IN p_permission_group_id VARCHAR(64), IN p_project_id VARCHAR(64), IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE permission_group_project_catalog 
    SET is_active = FALSE, removed_at = CURRENT_TIMESTAMP, removed_by = p_removed_by
    WHERE permission_group_id = p_permission_group_id AND project_id = p_project_id AND is_active = TRUE;
END$$

DROP PROCEDURE IF EXISTS sp_get_project_cataloged_permission_groups$$
CREATE PROCEDURE sp_get_project_cataloged_permission_groups(IN p_project_id VARCHAR(64))
BEGIN
    SELECT pg.id, pg.group_hash, pg.group_name, pg.group_display_name, pg.group_description,
           pg.group_category, pgpc.catalog_purpose, pgpc.notes, pgpc.added_at, pgpc.added_by
    FROM permission_group_project_catalog pgpc
    INNER JOIN global_permission_groups pg ON pgpc.permission_group_id = pg.id
    WHERE pgpc.project_id = p_project_id AND pgpc.is_active = TRUE AND pg.is_active = TRUE
    ORDER BY pg.group_name;
END$$

DROP PROCEDURE IF EXISTS sp_get_permission_group_cataloged_projects$$
CREATE PROCEDURE sp_get_permission_group_cataloged_projects(IN p_permission_group_id VARCHAR(64))
BEGIN
    SELECT p.id, p.project_hash, p.project_name, p.project_description,
           pgpc.catalog_purpose, pgpc.notes, pgpc.added_at, pgpc.added_by
    FROM permission_group_project_catalog pgpc
    INNER JOIN projects p ON pgpc.project_id = p.id
    WHERE pgpc.permission_group_id = p_permission_group_id AND pgpc.is_active = TRUE AND p.is_active = TRUE
    ORDER BY p.project_name;
END$$

-- ===================================================================================
-- GET USER ALL GROUPS (Including Inherited)
-- NOTE: Recursive queries can be expensive - consider caching for frequent use
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_user_all_groups_with_inheritance$$
CREATE PROCEDURE sp_get_user_all_groups_with_inheritance(IN p_user_id VARCHAR(64))
BEGIN
    WITH RECURSIVE group_tree AS (
        -- Direct membership
        SELECT ugm.user_group_id, ug.group_name, ug.group_hash, 
               0 as depth, 'direct' as membership_type
        FROM user_group_members ugm
        JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = TRUE
        WHERE ugm.user_id = p_user_id AND ugm.is_active = TRUE
        
        UNION ALL
        
        -- Ancestor groups - walk UP the tree via parent_group_id
        SELECT parent_ug.id, parent_ug.group_name, parent_ug.group_hash, 
               gt.depth + 1, 'inherited'
        FROM group_tree gt
        JOIN user_groups ug ON gt.user_group_id = ug.id
        JOIN user_groups parent_ug ON ug.parent_group_id = parent_ug.id AND parent_ug.is_active = TRUE
        WHERE ug.parent_group_id IS NOT NULL AND gt.depth < 10
    )
    SELECT DISTINCT user_group_id, group_name, group_hash, membership_type, 
           MIN(depth) as inheritance_depth
    FROM group_tree
    GROUP BY user_group_id, group_name, group_hash, membership_type
    ORDER BY inheritance_depth, group_name;
END$$

DELIMITER ;

-- ===================================================================================
-- PERMISSION ASSIGNMENT PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Permission assignment system stored procedures created successfully!' as status,
       '21 procedures for permission assignment and resolution' as details;

