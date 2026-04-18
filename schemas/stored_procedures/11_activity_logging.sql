-- ===================================================================================
-- Activity Logging Stored Procedures
-- ===================================================================================
-- Stored procedures for comprehensive activity logging and audit trail
-- MySQL Database
-- ===================================================================================

USE magic_auth;

DELIMITER //

-- =================== SP: LOG ACTIVITY ===================
-- Primary procedure for logging activities
-- Links to activity catalog and stores comprehensive audit information
DROP PROCEDURE IF EXISTS sp_log_activity//
CREATE PROCEDURE sp_log_activity(
    IN p_activity_log_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_activity_code VARCHAR(50),
    IN p_details TEXT,
    IN p_project_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64),
    IN p_target_user_id VARCHAR(64),
    IN p_ip_address VARCHAR(45),
    IN p_user_agent TEXT,
    IN p_metadata JSON
)
BEGIN
    DECLARE v_catalog_id VARCHAR(64);
    DECLARE v_severity_level ENUM('info', 'warning', 'critical');
    
    -- Get catalog entry for this activity code
    SELECT id, severity_level
    INTO v_catalog_id, v_severity_level
    FROM activity_catalog
    WHERE activity_code = p_activity_code
      AND is_active = TRUE
    LIMIT 1;
    
    -- If catalog entry doesn't exist, use defaults
    IF v_catalog_id IS NULL THEN
        SET v_severity_level = 'info';
    END IF;
    
    -- Insert activity log
    INSERT INTO activity_logs (
        id,
        user_id,
        activity_type,
        activity_catalog_id,
        details,
        project_id,
        user_group_id,
        target_user_id,
        ip_address,
        user_agent,
        metadata,
        severity_level,
        created_at
    ) VALUES (
        p_activity_log_id,
        p_user_id,
        p_activity_code,
        v_catalog_id,
        p_details,
        p_project_id,
        p_user_group_id,
        p_target_user_id,
        p_ip_address,
        p_user_agent,
        p_metadata,
        v_severity_level,
        NOW()
    );
    
    SELECT 'Activity logged successfully' as status;
END//

-- =================== SP: GET ACTIVITY LOGS ===================
-- Retrieve audit logs with filtering and pagination
-- Joins with users, projects, groups, and catalog for enriched data
DROP PROCEDURE IF EXISTS sp_get_activity_logs//
CREATE PROCEDURE sp_get_activity_logs(
    IN p_limit INT,
    IN p_offset INT,
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_activity_code VARCHAR(50),
    IN p_days INT,
    IN p_search VARCHAR(255)
)
BEGIN
    DECLARE v_date_filter DATETIME;
    
    -- Calculate date filter
    SET v_date_filter = DATE_SUB(NOW(), INTERVAL p_days DAY);
    
    -- Return enriched activity logs
    SELECT 
        al.id,
        al.user_id,
        al.activity_type,
        al.details,
        al.project_id,
        al.user_group_id,
        al.target_user_id,
        al.ip_address,
        al.user_agent,
        al.metadata,
        al.severity_level,
        al.created_at,
        u.username,
        u.user_hash,
        p.project_name,
        p.project_hash,
        tu.username as target_username,
        tu.user_hash as target_user_hash,
        ug.group_name as user_group_name,
        ac.activity_name,
        ac.activity_category,
        ac.activity_description
    FROM activity_logs al
    LEFT JOIN users u ON al.user_id = u.id
    LEFT JOIN projects p ON al.project_id = p.id
    LEFT JOIN users tu ON al.target_user_id = tu.id
    LEFT JOIN user_groups ug ON al.user_group_id = ug.id
    LEFT JOIN activity_catalog ac ON al.activity_catalog_id = ac.id
    WHERE 
        (p_user_id IS NULL OR al.user_id = p_user_id)
        AND (p_project_id IS NULL OR al.project_id = p_project_id)
        AND (p_activity_code IS NULL OR al.activity_type = p_activity_code)
        AND al.created_at >= v_date_filter
        AND (p_search IS NULL
             OR al.activity_type LIKE CONCAT('%', p_search, '%')
             OR al.details LIKE CONCAT('%', p_search, '%')
             OR u.username LIKE CONCAT('%', p_search, '%'))
    ORDER BY al.created_at DESC
    LIMIT p_limit OFFSET p_offset;
END//

-- =================== SP: COUNT ACTIVITY LOGS ===================
-- Count matching audit logs with filtering
DROP PROCEDURE IF EXISTS sp_count_activity_logs//
CREATE PROCEDURE sp_count_activity_logs(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_activity_code VARCHAR(50),
    IN p_days INT,
    IN p_search VARCHAR(255)
)
BEGIN
    DECLARE v_date_filter DATETIME;
    
    -- Calculate date filter
    SET v_date_filter = DATE_SUB(NOW(), INTERVAL p_days DAY);
    
    -- Return count
    SELECT COUNT(*) as total_count
    FROM activity_logs al
    LEFT JOIN users u ON al.user_id = u.id
    WHERE 
        (p_user_id IS NULL OR al.user_id = p_user_id)
        AND (p_project_id IS NULL OR al.project_id = p_project_id)
        AND (p_activity_code IS NULL OR al.activity_type = p_activity_code)
        AND al.created_at >= v_date_filter
        AND (p_search IS NULL
             OR al.activity_type LIKE CONCAT('%', p_search, '%')
             OR al.details LIKE CONCAT('%', p_search, '%')
             OR u.username LIKE CONCAT('%', p_search, '%'));
END//

-- =================== SP: GET ACTIVITY CATALOG ===================
-- Retrieve activity catalog entries by category
DROP PROCEDURE IF EXISTS sp_get_activity_catalog//
CREATE PROCEDURE sp_get_activity_catalog(
    IN p_category VARCHAR(50)
)
BEGIN
    SELECT 
        id,
        activity_code,
        activity_name,
        activity_description,
        activity_category,
        severity_level,
        requires_audit,
        is_active
    FROM activity_catalog
    WHERE 
        (p_category IS NULL OR activity_category = p_category)
        AND is_active = TRUE
    ORDER BY activity_category, activity_name;
END//

-- =================== SP: GET ACTIVITY BY CODE ===================
-- Get activity catalog entry by activity code
DROP PROCEDURE IF EXISTS sp_get_activity_by_code//
CREATE PROCEDURE sp_get_activity_by_code(
    IN p_activity_code VARCHAR(50)
)
BEGIN
    SELECT 
        id,
        activity_code,
        activity_name,
        activity_description,
        activity_category,
        severity_level,
        requires_audit,
        is_active
    FROM activity_catalog
    WHERE activity_code = p_activity_code
    LIMIT 1;
END//

-- =================== SP: GET ACTIVITY STATS ===================
-- Get activity statistics by category and severity
DROP PROCEDURE IF EXISTS sp_get_activity_stats//
CREATE PROCEDURE sp_get_activity_stats(
    IN p_project_id VARCHAR(64),
    IN p_days INT
)
BEGIN
    DECLARE v_date_filter DATETIME;
    
    -- Calculate date filter
    SET v_date_filter = DATE_SUB(NOW(), INTERVAL p_days DAY);
    
    -- Return statistics grouped by category and severity
    SELECT 
        ac.activity_category,
        al.severity_level,
        COUNT(*) as activity_count,
        COUNT(DISTINCT al.user_id) as unique_users
    FROM activity_logs al
    LEFT JOIN activity_catalog ac ON al.activity_catalog_id = ac.id
    WHERE 
        (p_project_id IS NULL OR al.project_id = p_project_id)
        AND al.created_at >= v_date_filter
    GROUP BY ac.activity_category, al.severity_level
    ORDER BY activity_count DESC;
END//

-- =================== SP: LOG PERMISSION CHANGE ===================
-- Specialized procedure for logging permission-related changes
DROP PROCEDURE IF EXISTS sp_log_permission_change//
CREATE PROCEDURE sp_log_permission_change(
    IN p_audit_id VARCHAR(64),
    IN p_action_type VARCHAR(50),
    IN p_project_id VARCHAR(64),
    IN p_target_user_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64),
    IN p_permission_id VARCHAR(64),
    IN p_permission_group_id VARCHAR(64),
    IN p_performed_by VARCHAR(64),
    IN p_old_values JSON,
    IN p_new_values JSON,
    IN p_ip_address VARCHAR(45),
    IN p_user_agent TEXT,
    IN p_table_name VARCHAR(100),
    IN p_record_id VARCHAR(64)
)
BEGIN
    INSERT INTO permission_audit_log (
        id,
        action_type,
        project_id,
        target_user_id,
        user_group_id,
        permission_id,
        permission_group_id,
        performed_by,
        old_values,
        new_values,
        action_timestamp,
        performed_at,
        ip_address,
        user_agent,
        table_name,
        record_id
    ) VALUES (
        p_audit_id,
        p_action_type,
        p_project_id,
        p_target_user_id,
        p_user_group_id,
        p_permission_id,
        p_permission_group_id,
        p_performed_by,
        p_old_values,
        p_new_values,
        NOW(),
        NOW(),
        p_ip_address,
        p_user_agent,
        p_table_name,
        p_record_id
    );
    
    SELECT 'Permission change logged successfully' as status;
END//

-- =================== SP: GET RECENT SECURITY EVENTS ===================
-- Get recent security-critical events for monitoring
DROP PROCEDURE IF EXISTS sp_get_recent_security_events//
CREATE PROCEDURE sp_get_recent_security_events(
    IN p_hours INT,
    IN p_limit INT
)
BEGIN
    DECLARE v_date_filter DATETIME;
    
    -- Calculate date filter
    SET v_date_filter = DATE_SUB(NOW(), INTERVAL p_hours HOUR);
    
    -- Return security events
    SELECT 
        al.id,
        al.user_id,
        al.activity_type,
        al.details,
        al.ip_address,
        al.severity_level,
        al.created_at,
        u.username,
        ac.activity_name,
        ac.activity_description
    FROM activity_logs al
    LEFT JOIN users u ON al.user_id = u.id
    LEFT JOIN activity_catalog ac ON al.activity_catalog_id = ac.id
    WHERE 
        al.severity_level IN ('warning', 'critical')
        AND al.created_at >= v_date_filter
    ORDER BY al.created_at DESC
    LIMIT p_limit;
END//

-- =================== SP: GET USER ACTIVITY SUMMARY ===================
-- Get summary of user activities for a specific period
DROP PROCEDURE IF EXISTS sp_get_user_activity_summary//
CREATE PROCEDURE sp_get_user_activity_summary(
    IN p_user_id VARCHAR(64),
    IN p_days INT
)
BEGIN
    DECLARE v_date_filter DATETIME;
    
    -- Calculate date filter
    SET v_date_filter = DATE_SUB(NOW(), INTERVAL p_days DAY);
    
    -- Return user activity summary
    SELECT 
        ac.activity_category,
        ac.activity_name,
        COUNT(*) as activity_count,
        MAX(al.created_at) as last_activity
    FROM activity_logs al
    LEFT JOIN activity_catalog ac ON al.activity_catalog_id = ac.id
    WHERE 
        al.user_id = p_user_id
        AND al.created_at >= v_date_filter
    GROUP BY ac.activity_category, ac.activity_name
    ORDER BY activity_count DESC;
END//

-- =================== SP: CLEANUP OLD ACTIVITY LOGS ===================
-- Archive or delete old activity logs based on retention policy
DROP PROCEDURE IF EXISTS sp_cleanup_old_activity_logs//
CREATE PROCEDURE sp_cleanup_old_activity_logs(
    IN p_retention_days INT,
    IN p_dry_run BOOLEAN
)
BEGIN
    DECLARE v_cutoff_date DATETIME;
    DECLARE v_count INT;
    
    -- Calculate cutoff date
    SET v_cutoff_date = DATE_SUB(NOW(), INTERVAL p_retention_days DAY);
    
    -- Count logs to be deleted
    SELECT COUNT(*) INTO v_count
    FROM activity_logs
    WHERE created_at < v_cutoff_date
      AND severity_level = 'info'; -- Only delete info logs, keep warning/critical
    
    IF p_dry_run = TRUE THEN
        -- Return count without deleting
        SELECT v_count as logs_to_delete, v_cutoff_date as cutoff_date, 'DRY RUN - No logs deleted' as status;
    ELSE
        -- Delete old info logs
        DELETE FROM activity_logs
        WHERE created_at < v_cutoff_date
          AND severity_level = 'info';
        
        SELECT v_count as logs_deleted, v_cutoff_date as cutoff_date, 'Cleanup completed' as status;
    END IF;
END//

DELIMITER ;

-- =================== STORED PROCEDURES CREATED ===================
SELECT 'Activity logging stored procedures created successfully!' as status,
       '11 stored procedures created for activity logging' as details;
