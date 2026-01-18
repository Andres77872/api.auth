-- ===================================================================================
-- SYSTEM MAINTENANCE STORED PROCEDURES
-- ===================================================================================
-- This file contains all stored procedures related to system maintenance:
-- - Session cleanup
-- - Cache cleanup
-- - Orphaned records cleanup
-- - Health checks
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- CLEANUP OPERATIONS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_cleanup_expired_sessions$$
CREATE PROCEDURE sp_cleanup_expired_sessions()
BEGIN
    UPDATE user_sessions SET is_active = 0 WHERE expires_at < NOW() AND is_active = 1;
    SELECT ROW_COUNT() as cleaned_sessions;
END$$

DROP PROCEDURE IF EXISTS sp_cleanup_permission_cache$$
CREATE PROCEDURE sp_cleanup_permission_cache()
BEGIN
    DELETE FROM permission_cache WHERE expires_at < NOW();
    SELECT ROW_COUNT() as cleaned_cache_entries;
END$$

DROP PROCEDURE IF EXISTS sp_cleanup_orphaned_records$$
CREATE PROCEDURE sp_cleanup_orphaned_records()
BEGIN
    DECLARE v_cleaned_ugm INT DEFAULT 0;
    DECLARE v_cleaned_ugpg INT DEFAULT 0;
    DECLARE v_cleaned_pgm INT DEFAULT 0;
    
    -- Clean orphaned user_group_members (users deleted or inactive)
    UPDATE user_group_members ugm
    LEFT JOIN users u ON ugm.user_id = u.id
    SET ugm.is_active = 0, ugm.removed_at = NOW()
    WHERE ugm.is_active = 1 AND (u.id IS NULL OR u.is_active = 0);
    SET v_cleaned_ugm = ROW_COUNT();
    
    -- Clean orphaned user_group_project_groups (user groups or project groups deleted/inactive)
    UPDATE user_group_project_groups ugpg
    LEFT JOIN user_groups ug ON ugpg.user_group_id = ug.id
    LEFT JOIN project_groups pg ON ugpg.project_group_id = pg.id
    SET ugpg.is_active = 0, ugpg.revoked_at = NOW()
    WHERE ugpg.is_active = 1 AND (ug.id IS NULL OR ug.is_active = 0 OR pg.id IS NULL OR pg.is_active = 0);
    SET v_cleaned_ugpg = ROW_COUNT();
    
    -- Clean orphaned project_group_members (projects or project groups deleted/inactive)
    UPDATE project_group_members pgm
    LEFT JOIN projects p ON pgm.project_id = p.id
    LEFT JOIN project_groups pg ON pgm.project_group_id = pg.id
    SET pgm.is_active = 0, pgm.removed_at = NOW()
    WHERE pgm.is_active = 1 AND (p.id IS NULL OR p.is_active = 0 OR pg.id IS NULL OR pg.is_active = 0);
    SET v_cleaned_pgm = ROW_COUNT();
    
    SELECT 
        v_cleaned_ugm + v_cleaned_ugpg + v_cleaned_pgm as cleaned_records,
        v_cleaned_ugm as cleaned_user_group_members,
        v_cleaned_ugpg as cleaned_user_group_project_groups,
        v_cleaned_pgm as cleaned_project_group_members,
        NOW() as cleanup_timestamp;
END$$

-- ===================================================================================
-- HEALTH CHECKS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_system_health_check$$
CREATE PROCEDURE sp_system_health_check()
BEGIN
    SELECT COUNT(*) as users_without_valid_type, 'Users with invalid user_type' as issue_description
    FROM users WHERE user_type NOT IN ('root', 'admin', 'consumer') OR user_type IS NULL;
    
    SELECT COUNT(*) as orphaned_user_group_memberships,
           'User group memberships without valid users or groups' as issue_description
    FROM user_group_members ugm
    LEFT JOIN users u ON ugm.user_id = u.id
    LEFT JOIN user_groups ug ON ugm.user_group_id = ug.id
    WHERE ugm.is_active = 1 AND (u.id IS NULL OR u.is_active = 0 OR ug.id IS NULL OR ug.is_active = 0);
    
    SELECT COUNT(*) as expired_active_sessions, 'Expired sessions still marked as active' as issue_description
    FROM user_sessions WHERE is_active = 1 AND expires_at < NOW();
    
    SELECT COUNT(*) as empty_permission_groups,
           'Global permission groups without any assigned permissions' as issue_description
    FROM global_permission_groups gpg
    LEFT JOIN global_permission_group_permissions gpgp ON gpg.id = gpgp.permission_group_id AND gpgp.is_active = 1
    WHERE gpg.is_active = 1 AND gpgp.id IS NULL;
END$$

DROP PROCEDURE IF EXISTS sp_check_database_health$$
CREATE PROCEDURE sp_check_database_health()
BEGIN
    SELECT 1 as healthy;
END$$

DELIMITER ;

-- ===================================================================================
-- SYSTEM MAINTENANCE PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'System maintenance stored procedures created successfully!' as status,
       '5 procedures for cleanup and health monitoring' as details;

