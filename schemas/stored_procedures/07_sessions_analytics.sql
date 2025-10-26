-- ===================================================================================
-- SESSIONS AND ANALYTICS STORED PROCEDURES
-- ===================================================================================
-- This file contains all stored procedures related to sessions and analytics:
-- - Activity logging
-- - Activity catalog management
-- - Login statistics
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- ACTIVITY LOGGING
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_log_activity$$
CREATE PROCEDURE sp_log_activity(
    IN p_activity_log_id VARCHAR(64), IN p_user_id VARCHAR(64), IN p_activity_code VARCHAR(50),
    IN p_details TEXT, IN p_project_id VARCHAR(64), IN p_user_group_id VARCHAR(64),
    IN p_target_user_id VARCHAR(64), IN p_ip_address VARCHAR(45), IN p_user_agent TEXT, IN p_metadata JSON
)
BEGIN
    DECLARE v_activity_catalog_id VARCHAR(64);
    DECLARE v_severity_level VARCHAR(20);
    
    SELECT id, severity_level INTO v_activity_catalog_id, v_severity_level
    FROM activity_catalog WHERE activity_code = p_activity_code AND is_active = 1 LIMIT 1;
    
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details,
                               project_id, user_group_id, target_user_id, ip_address, user_agent,
                               metadata, severity_level, created_at)
    VALUES (p_activity_log_id, p_user_id, p_activity_code, v_activity_catalog_id, p_details,
            p_project_id, p_user_group_id, p_target_user_id, p_ip_address, p_user_agent,
            p_metadata, IFNULL(v_severity_level, 'info'), NOW());
END$$

DROP PROCEDURE IF EXISTS sp_get_activity_logs$$
CREATE PROCEDURE sp_get_activity_logs(
    IN p_limit INT, IN p_offset INT, IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64), IN p_activity_code VARCHAR(50), IN p_days INT
)
BEGIN
    SELECT al.id, al.user_id, al.activity_type, al.details, al.project_id, al.user_group_id,
           al.target_user_id, al.ip_address, al.user_agent, al.metadata, al.severity_level, al.created_at,
           u.username, u.user_hash, p.project_name, p.project_hash,
           tu.username as target_username, tu.user_hash as target_user_hash,
           ug.group_name as user_group_name, ac.activity_name, ac.activity_category, ac.activity_description
    FROM activity_logs al
    LEFT JOIN users u ON al.user_id = u.id
    LEFT JOIN projects p ON al.project_id = p.id
    LEFT JOIN users tu ON al.target_user_id = tu.id
    LEFT JOIN user_groups ug ON al.user_group_id = ug.id
    LEFT JOIN activity_catalog ac ON al.activity_catalog_id = ac.id
    WHERE al.created_at >= DATE_SUB(NOW(), INTERVAL p_days DAY)
      AND (p_user_id IS NULL OR al.user_id = p_user_id)
      AND (p_project_id IS NULL OR al.project_id = p_project_id)
      AND (p_activity_code IS NULL OR al.activity_type = p_activity_code)
    ORDER BY al.created_at DESC LIMIT p_limit OFFSET p_offset;
END$$

DROP PROCEDURE IF EXISTS sp_count_activity_logs$$
CREATE PROCEDURE sp_count_activity_logs(
    IN p_user_id VARCHAR(64), IN p_project_id VARCHAR(64),
    IN p_activity_code VARCHAR(50), IN p_days INT
)
BEGIN
    SELECT COUNT(*) as total_count FROM activity_logs al
    WHERE al.created_at >= DATE_SUB(NOW(), INTERVAL p_days DAY)
      AND (p_user_id IS NULL OR al.user_id = p_user_id)
      AND (p_project_id IS NULL OR al.project_id = p_project_id)
      AND (p_activity_code IS NULL OR al.activity_type = p_activity_code);
END$$

-- ===================================================================================
-- ACTIVITY CATALOG MANAGEMENT
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_activity_catalog$$
CREATE PROCEDURE sp_get_activity_catalog(IN p_category VARCHAR(50))
BEGIN
    IF p_category IS NOT NULL THEN
        SELECT id, activity_code, activity_name, activity_description, activity_category,
               severity_level, requires_audit, is_active
        FROM activity_catalog WHERE activity_category = p_category AND is_active = 1
        ORDER BY activity_category, activity_name;
    ELSE
        SELECT id, activity_code, activity_name, activity_description, activity_category,
               severity_level, requires_audit, is_active
        FROM activity_catalog WHERE is_active = 1 ORDER BY activity_category, activity_name;
    END IF;
END$$

-- ===================================================================================
-- LOGIN STATISTICS
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_get_login_statistics$$
CREATE PROCEDURE sp_get_login_statistics(IN p_days INT)
BEGIN
    SELECT COUNT(*) as login_count
    FROM activity_logs
    WHERE activity_type = 'user_login'
      AND created_at >= DATE_SUB(NOW(), INTERVAL p_days DAY);
    
    SELECT COUNT(DISTINCT user_id) as unique_users
    FROM activity_logs
    WHERE activity_type = 'user_login'
      AND created_at >= DATE_SUB(NOW(), INTERVAL p_days DAY);
END$$

DELIMITER ;

-- ===================================================================================
-- SESSIONS AND ANALYTICS PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Sessions and analytics stored procedures created successfully!' as status,
       '6 procedures for activity logging and statistics' as details;

