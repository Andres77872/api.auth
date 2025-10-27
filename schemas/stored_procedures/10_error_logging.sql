-- ===================================================================================
-- ERROR LOGGING STORED PROCEDURES
-- Procedures for comprehensive error tracking and monitoring
-- ===================================================================================
-- ALWAYS logs errors regardless of DEBUG_MODE setting
-- DEBUG_MODE only controls API response details, not database logging
-- ===================================================================================

USE magic_auth;

DELIMITER //

-- =================== LOG ERROR ===================
-- Logs a new error to the database
-- This is called by the error handler middleware for EVERY error
DROP PROCEDURE IF EXISTS sp_log_error //
CREATE PROCEDURE sp_log_error(
    IN p_error_hash VARCHAR(255),
    IN p_error_code VARCHAR(20),
    IN p_error_category VARCHAR(50),
    IN p_error_message TEXT,
    IN p_status_code INT,
    IN p_severity_level VARCHAR(20),
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_session_id VARCHAR(256),
    IN p_request_path VARCHAR(500),
    IN p_request_method VARCHAR(10),
    IN p_request_query_params JSON,
    IN p_client_ip VARCHAR(45),
    IN p_user_agent TEXT,
    IN p_function_name VARCHAR(255),
    IN p_function_params JSON,
    IN p_error_context TEXT,
    IN p_error_details JSON,
    IN p_database_error JSON,
    IN p_original_error_type VARCHAR(255),
    IN p_original_error_message TEXT,
    IN p_stack_trace LONGTEXT,
    IN p_environment VARCHAR(20),
    IN p_debug_mode BOOLEAN
)
BEGIN
    DECLARE v_error_id VARCHAR(64);
    DECLARE v_severity ENUM('info', 'warning', 'error', 'critical');
    
    -- Generate error ID
    SET v_error_id = CONCAT('err-', UUID());
    
    -- Normalize severity level
    SET v_severity = CASE 
        WHEN p_severity_level = 'info' THEN 'info'
        WHEN p_severity_level = 'warning' THEN 'warning'
        WHEN p_severity_level = 'critical' THEN 'critical'
        ELSE 'error'
    END;
    
    -- Insert error log
    INSERT INTO error_logs (
        id,
        error_hash,
        error_code,
        error_category,
        error_message,
        status_code,
        severity_level,
        user_id,
        project_id,
        session_id,
        request_path,
        request_method,
        request_query_params,
        client_ip,
        user_agent,
        function_name,
        function_params,
        error_context,
        error_details,
        database_error,
        original_error_type,
        original_error_message,
        stack_trace,
        environment,
        debug_mode,
        created_at
    ) VALUES (
        v_error_id,
        p_error_hash,
        p_error_code,
        p_error_category,
        p_error_message,
        p_status_code,
        v_severity,
        p_user_id,
        p_project_id,
        p_session_id,
        p_request_path,
        p_request_method,
        p_request_query_params,
        p_client_ip,
        p_user_agent,
        p_function_name,
        p_function_params,
        p_error_context,
        p_error_details,
        p_database_error,
        p_original_error_type,
        p_original_error_message,
        p_stack_trace,
        p_environment,
        p_debug_mode,
        NOW()
    );
    
    -- Update statistics (insert or update)
    INSERT INTO error_log_statistics (
        id,
        error_code,
        error_category,
        occurrence_count,
        first_occurrence,
        last_occurrence,
        affected_users_count,
        affected_projects_count,
        date_bucket,
        hour_bucket
    ) VALUES (
        CONCAT('stat-', UUID()),
        p_error_code,
        p_error_category,
        1,
        NOW(),
        NOW(),
        IF(p_user_id IS NOT NULL, 1, 0),
        IF(p_project_id IS NOT NULL, 1, 0),
        CURDATE(),
        HOUR(NOW())
    )
    ON DUPLICATE KEY UPDATE
        occurrence_count = occurrence_count + 1,
        last_occurrence = NOW(),
        affected_users_count = affected_users_count + IF(p_user_id IS NOT NULL, 1, 0),
        affected_projects_count = affected_projects_count + IF(p_project_id IS NOT NULL, 1, 0);
    
    -- Return the error ID
    SELECT v_error_id as error_id, 'Error logged successfully' as message;
END //

-- =================== GET ERROR LOGS ===================
-- Retrieve error logs with filtering and pagination
DROP PROCEDURE IF EXISTS sp_get_error_logs //
CREATE PROCEDURE sp_get_error_logs(
    IN p_limit INT,
    IN p_offset INT,
    IN p_error_code VARCHAR(20),
    IN p_error_category VARCHAR(50),
    IN p_severity_level VARCHAR(20),
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_start_date DATETIME,
    IN p_end_date DATETIME
)
BEGIN
    SELECT 
        id,
        error_hash,
        error_code,
        error_category,
        error_message,
        status_code,
        severity_level,
        user_id,
        project_id,
        session_id,
        request_path,
        request_method,
        request_query_params,
        client_ip,
        function_name,
        function_params,
        error_context,
        error_details,
        database_error,
        original_error_type,
        original_error_message,
        created_at,
        environment,
        debug_mode
    FROM error_logs
    WHERE 
        (p_error_code IS NULL OR error_code = p_error_code)
        AND (p_error_category IS NULL OR error_category = p_error_category)
        AND (p_severity_level IS NULL OR severity_level = p_severity_level)
        AND (p_user_id IS NULL OR user_id = p_user_id)
        AND (p_project_id IS NULL OR project_id = p_project_id)
        AND (p_start_date IS NULL OR created_at >= p_start_date)
        AND (p_end_date IS NULL OR created_at <= p_end_date)
    ORDER BY created_at DESC
    LIMIT p_limit OFFSET p_offset;
END //

-- =================== GET ERROR BY ID ===================
-- Get detailed error log by ID (includes full stack trace)
DROP PROCEDURE IF EXISTS sp_get_error_by_id //
CREATE PROCEDURE sp_get_error_by_id(
    IN p_error_id VARCHAR(64)
)
BEGIN
    SELECT 
        id,
        error_hash,
        error_code,
        error_category,
        error_message,
        status_code,
        severity_level,
        user_id,
        project_id,
        session_id,
        request_path,
        request_method,
        request_query_params,
        client_ip,
        user_agent,
        function_name,
        function_params,
        error_context,
        error_details,
        database_error,
        original_error_type,
        original_error_message,
        stack_trace,  -- Full stack trace
        created_at,
        environment,
        debug_mode
    FROM error_logs
    WHERE id = p_error_id;
END //

-- =================== GET ERROR STATISTICS ===================
-- Get aggregated error statistics
DROP PROCEDURE IF EXISTS sp_get_error_statistics //
CREATE PROCEDURE sp_get_error_statistics(
    IN p_start_date DATE,
    IN p_end_date DATE,
    IN p_error_category VARCHAR(50)
)
BEGIN
    SELECT 
        error_code,
        error_category,
        SUM(occurrence_count) as total_occurrences,
        SUM(affected_users_count) as total_users_affected,
        SUM(affected_projects_count) as total_projects_affected,
        MIN(first_occurrence) as first_seen,
        MAX(last_occurrence) as last_seen,
        COUNT(DISTINCT date_bucket) as days_active
    FROM error_log_statistics
    WHERE 
        (p_start_date IS NULL OR date_bucket >= p_start_date)
        AND (p_end_date IS NULL OR date_bucket <= p_end_date)
        AND (p_error_category IS NULL OR error_category = p_error_category)
    GROUP BY error_code, error_category
    ORDER BY total_occurrences DESC;
END //

-- =================== GET RECENT CRITICAL ERRORS ===================
-- Get recent critical errors that need attention
DROP PROCEDURE IF EXISTS sp_get_critical_errors //
CREATE PROCEDURE sp_get_critical_errors(
    IN p_limit INT,
    IN p_hours_back INT
)
BEGIN
    SELECT 
        id,
        error_code,
        error_category,
        error_message,
        status_code,
        user_id,
        project_id,
        request_path,
        request_method,
        function_name,
        error_context,
        created_at
    FROM error_logs
    WHERE 
        created_at >= DATE_SUB(NOW(), INTERVAL p_hours_back HOUR)
        AND (
            severity_level = 'critical'
            OR status_code = 500
            OR error_category IN ('database', 'internal')
        )
    ORDER BY created_at DESC
    LIMIT p_limit;
END //

-- =================== GET ERROR TRENDS ===================
-- Get error trends over time (hourly aggregation)
DROP PROCEDURE IF EXISTS sp_get_error_trends //
CREATE PROCEDURE sp_get_error_trends(
    IN p_days_back INT,
    IN p_error_category VARCHAR(50)
)
BEGIN
    SELECT 
        DATE(created_at) as error_date,
        HOUR(created_at) as error_hour,
        error_category,
        error_code,
        COUNT(*) as error_count,
        COUNT(DISTINCT user_id) as unique_users,
        COUNT(DISTINCT project_id) as unique_projects
    FROM error_logs
    WHERE 
        created_at >= DATE_SUB(NOW(), INTERVAL p_days_back DAY)
        AND (p_error_category IS NULL OR error_category = p_error_category)
    GROUP BY DATE(created_at), HOUR(created_at), error_category, error_code
    ORDER BY error_date DESC, error_hour DESC, error_count DESC;
END //

-- =================== CREATE ERROR ALERT ===================
-- Create an alert for error patterns requiring attention
DROP PROCEDURE IF EXISTS sp_create_error_alert //
CREATE PROCEDURE sp_create_error_alert(
    IN p_alert_type VARCHAR(50),
    IN p_error_code VARCHAR(20),
    IN p_error_category VARCHAR(50),
    IN p_alert_message TEXT,
    IN p_occurrence_count INT,
    IN p_time_window_minutes INT
)
BEGIN
    DECLARE v_alert_id VARCHAR(64);
    DECLARE v_alert_type_enum ENUM('spike', 'critical_error', 'repeated_error', 'new_error');
    
    SET v_alert_id = CONCAT('alert-', UUID());
    
    -- Normalize alert type
    SET v_alert_type_enum = CASE 
        WHEN p_alert_type = 'spike' THEN 'spike'
        WHEN p_alert_type = 'critical_error' THEN 'critical_error'
        WHEN p_alert_type = 'repeated_error' THEN 'repeated_error'
        WHEN p_alert_type = 'new_error' THEN 'new_error'
        ELSE 'repeated_error'
    END;
    
    INSERT INTO error_log_alerts (
        id,
        alert_type,
        error_code,
        error_category,
        alert_message,
        occurrence_count,
        time_window_minutes,
        threshold_exceeded,
        first_detected,
        last_updated
    ) VALUES (
        v_alert_id,
        v_alert_type_enum,
        p_error_code,
        p_error_category,
        p_alert_message,
        p_occurrence_count,
        p_time_window_minutes,
        TRUE,
        NOW(),
        NOW()
    );
    
    SELECT v_alert_id as alert_id, 'Alert created successfully' as message;
END //

-- =================== GET ACTIVE ALERTS ===================
-- Get active unresolved error alerts
DROP PROCEDURE IF EXISTS sp_get_active_alerts //
CREATE PROCEDURE sp_get_active_alerts()
BEGIN
    SELECT 
        id,
        alert_type,
        error_code,
        error_category,
        alert_message,
        occurrence_count,
        time_window_minutes,
        first_detected,
        last_updated,
        acknowledged,
        acknowledged_by,
        acknowledged_at
    FROM error_log_alerts
    WHERE resolved = FALSE
    ORDER BY 
        CASE 
            WHEN alert_type = 'critical_error' THEN 1
            WHEN alert_type = 'spike' THEN 2
            WHEN alert_type = 'repeated_error' THEN 3
            ELSE 4
        END,
        first_detected DESC;
END //

-- =================== ACKNOWLEDGE ALERT ===================
-- Mark an alert as acknowledged
DROP PROCEDURE IF EXISTS sp_acknowledge_alert //
CREATE PROCEDURE sp_acknowledge_alert(
    IN p_alert_id VARCHAR(64),
    IN p_acknowledged_by VARCHAR(64)
)
BEGIN
    UPDATE error_log_alerts
    SET 
        acknowledged = TRUE,
        acknowledged_by = p_acknowledged_by,
        acknowledged_at = NOW()
    WHERE id = p_alert_id;
    
    SELECT 'Alert acknowledged successfully' as message;
END //

-- =================== RESOLVE ALERT ===================
-- Mark an alert as resolved
DROP PROCEDURE IF EXISTS sp_resolve_alert //
CREATE PROCEDURE sp_resolve_alert(
    IN p_alert_id VARCHAR(64),
    IN p_resolved_by VARCHAR(64),
    IN p_resolution_notes TEXT
)
BEGIN
    UPDATE error_log_alerts
    SET 
        resolved = TRUE,
        resolved_by = p_resolved_by,
        resolved_at = NOW(),
        resolution_notes = p_resolution_notes
    WHERE id = p_alert_id;
    
    SELECT 'Alert resolved successfully' as message;
END //

-- =================== CLEANUP OLD ERROR LOGS ===================
-- Clean up error logs older than specified days
DROP PROCEDURE IF EXISTS sp_cleanup_old_error_logs //
CREATE PROCEDURE sp_cleanup_old_error_logs(
    IN p_days_to_keep INT
)
BEGIN
    DECLARE v_deleted_count INT;
    
    -- Delete old error logs
    DELETE FROM error_logs
    WHERE created_at < DATE_SUB(NOW(), INTERVAL p_days_to_keep DAY);
    
    SET v_deleted_count = ROW_COUNT();
    
    -- Delete old statistics
    DELETE FROM error_log_statistics
    WHERE date_bucket < DATE_SUB(CURDATE(), INTERVAL p_days_to_keep DAY);
    
    SELECT 
        v_deleted_count as deleted_error_logs,
        ROW_COUNT() as deleted_statistics,
        CONCAT('Cleaned up error logs older than ', p_days_to_keep, ' days') as message;
END //

-- =================== GET ERROR LOG SUMMARY ===================
-- Get a summary of error logs for dashboards
DROP PROCEDURE IF EXISTS sp_get_error_log_summary //
CREATE PROCEDURE sp_get_error_log_summary(
    IN p_hours_back INT
)
BEGIN
    -- Overall summary
    SELECT 
        COUNT(*) as total_errors,
        COUNT(DISTINCT error_code) as unique_error_codes,
        COUNT(DISTINCT user_id) as affected_users,
        COUNT(DISTINCT project_id) as affected_projects,
        SUM(CASE WHEN severity_level = 'critical' THEN 1 ELSE 0 END) as critical_errors,
        SUM(CASE WHEN severity_level = 'error' THEN 1 ELSE 0 END) as errors,
        SUM(CASE WHEN severity_level = 'warning' THEN 1 ELSE 0 END) as warnings,
        SUM(CASE WHEN status_code >= 500 THEN 1 ELSE 0 END) as server_errors,
        SUM(CASE WHEN status_code >= 400 AND status_code < 500 THEN 1 ELSE 0 END) as client_errors
    FROM error_logs
    WHERE created_at >= DATE_SUB(NOW(), INTERVAL p_hours_back HOUR);
    
    -- Top error codes
    SELECT 
        error_code,
        error_category,
        COUNT(*) as occurrence_count,
        MAX(created_at) as last_occurrence
    FROM error_logs
    WHERE created_at >= DATE_SUB(NOW(), INTERVAL p_hours_back HOUR)
    GROUP BY error_code, error_category
    ORDER BY occurrence_count DESC
    LIMIT 10;
    
    -- Errors by category
    SELECT 
        error_category,
        COUNT(*) as count,
        AVG(status_code) as avg_status_code
    FROM error_logs
    WHERE created_at >= DATE_SUB(NOW(), INTERVAL p_hours_back HOUR)
    GROUP BY error_category
    ORDER BY count DESC;
END //

DELIMITER ;

-- =================== COMPLETION MESSAGE ===================
SELECT 'Error logging stored procedures created successfully!' as status,
       '14 procedures created for comprehensive error tracking and monitoring' as details;
