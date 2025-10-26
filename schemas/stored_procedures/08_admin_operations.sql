-- ===================================================================================
-- ADMIN OPERATIONS STORED PROCEDURES
-- ===================================================================================
-- This file contains all stored procedures related to admin operations:
-- - Audit logging
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- AUDIT LOGGING
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_rbac_get_project_audit_log$$
CREATE PROCEDURE sp_rbac_get_project_audit_log(
    IN p_project_id VARCHAR(64), IN p_action_type VARCHAR(50), IN p_limit INT, IN p_offset INT
)
BEGIN
    IF p_action_type IS NOT NULL THEN
        SELECT id, action_type, table_name, record_id, old_values, new_values,
               performed_by, performed_at, ip_address, user_agent, project_id
        FROM permission_audit_log WHERE project_id = p_project_id AND action_type = p_action_type
        ORDER BY performed_at DESC LIMIT p_limit OFFSET p_offset;
    ELSE
        SELECT id, action_type, table_name, record_id, old_values, new_values,
               performed_by, performed_at, ip_address, user_agent, project_id
        FROM permission_audit_log WHERE project_id = p_project_id
        ORDER BY performed_at DESC LIMIT p_limit OFFSET p_offset;
    END IF;
END$$

DELIMITER ;

-- ===================================================================================
-- ADMIN OPERATIONS PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Admin operations stored procedures created successfully!' as status,
       '1 procedure for audit logging' as details;

