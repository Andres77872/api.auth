-- ===================================================================================
-- API AUDIT LOG STORED PROCEDURES
-- ===================================================================================
-- This file contains all stored procedures for API audit logging:
-- - Log API requests and responses
-- - Query audit logs with filters
-- - Generate audit statistics and reports
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- LOG API REQUEST (Called when request starts)
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_log_api_request$$
CREATE PROCEDURE sp_log_api_request(
    IN p_id VARCHAR(64),
    IN p_request_id VARCHAR(64),
    IN p_http_method VARCHAR(10),
    IN p_endpoint_path VARCHAR(512),
    IN p_route_pattern VARCHAR(512),
    IN p_user_id VARCHAR(64),
    IN p_user_type VARCHAR(20),
    IN p_session_id VARCHAR(256),
    IN p_request_headers JSON,
    IN p_request_body JSON,
    IN p_request_query JSON,
    IN p_request_size_bytes INT,
    IN p_client_ip VARCHAR(45),
    IN p_user_agent TEXT,
    IN p_referer VARCHAR(512),
    IN p_project_id VARCHAR(64),
    IN p_metadata JSON,
    IN p_auth_method ENUM('session', 'api_key')
)
BEGIN
    INSERT INTO api_audit_log (
        id, request_id, http_method, endpoint_path, route_pattern,
        user_id, user_type, session_id, auth_method,
        request_headers, request_body, request_query, request_size_bytes,
        request_timestamp, client_ip, user_agent, referer,
        project_id, metadata, response_status
    ) VALUES (
        p_id, p_request_id, p_http_method, p_endpoint_path, p_route_pattern,
        p_user_id, p_user_type, p_session_id, p_auth_method,
        p_request_headers, p_request_body, p_request_query, p_request_size_bytes,
        NOW(), p_client_ip, p_user_agent, p_referer,
        p_project_id, p_metadata, 0  -- Placeholder status, updated later
    );
END$$

-- ===================================================================================
-- UPDATE API RESPONSE (Called when request completes)
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_update_api_response$$
CREATE PROCEDURE sp_update_api_response(
    IN p_id VARCHAR(64),
    IN p_response_status INT,
    IN p_response_body JSON,
    IN p_response_headers JSON,
    IN p_response_size_bytes INT,
    IN p_error_code VARCHAR(50),
    IN p_error_message TEXT,
    IN p_target_resource_type VARCHAR(50),
    IN p_target_resource_id VARCHAR(64),
    IN p_tags JSON,
    IN p_security_event BOOLEAN
)
BEGIN
    DECLARE v_duration_ms INT;
    DECLARE v_is_success BOOLEAN;
    
    -- Calculate duration
    SELECT TIMESTAMPDIFF(MICROSECOND, request_timestamp, NOW()) / 1000
    INTO v_duration_ms
    FROM api_audit_log
    WHERE id = p_id;
    
    -- Determine success based on status code (2xx = success)
    SET v_is_success = (p_response_status >= 200 AND p_response_status < 300);
    
    -- Update the audit log entry
    UPDATE api_audit_log
    SET response_status = p_response_status,
        response_body = p_response_body,
        response_headers = p_response_headers,
        response_size_bytes = p_response_size_bytes,
        response_timestamp = NOW(),
        duration_ms = v_duration_ms,
        is_success = v_is_success,
        error_code = p_error_code,
        error_message = p_error_message,
        target_resource_type = p_target_resource_type,
        target_resource_id = p_target_resource_id,
        tags = p_tags,
        security_event = IFNULL(p_security_event, FALSE)
    WHERE id = p_id;
END$$

-- ===================================================================================
-- GET AUDIT LOGS (With comprehensive filtering)
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_get_audit_logs$$
CREATE PROCEDURE sp_get_audit_logs(
    IN p_limit INT,
    IN p_offset INT,
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_endpoint_path VARCHAR(512),
    IN p_http_method VARCHAR(10),
    IN p_status_code INT,
    IN p_is_success BOOLEAN,
    IN p_security_event BOOLEAN,
    IN p_days INT
)
BEGIN
    SELECT 
        a.id, a.request_id, a.http_method, a.endpoint_path, a.route_pattern,
        a.user_id, a.user_type, a.session_id,
        a.request_body, a.request_query, a.request_size_bytes,
        a.response_status, a.response_body, a.response_size_bytes,
        a.request_timestamp, a.response_timestamp, a.duration_ms,
        a.client_ip, a.user_agent, a.referer,
        a.is_success, a.error_code, a.error_message,
        a.project_id, a.target_resource_type, a.target_resource_id,
        a.metadata, a.tags, a.security_event,
        u.username, u.user_hash,
        p.project_name, p.project_hash
    FROM api_audit_log a
    LEFT JOIN users u ON a.user_id = u.id
    LEFT JOIN projects p ON a.project_id = p.id
    WHERE a.request_timestamp >= DATE_SUB(NOW(), INTERVAL IFNULL(p_days, 30) DAY)
      AND (p_user_id IS NULL OR a.user_id = p_user_id)
      AND (p_project_id IS NULL OR a.project_id = p_project_id)
      AND (p_endpoint_path IS NULL OR a.endpoint_path LIKE CONCAT('%', p_endpoint_path, '%'))
      AND (p_http_method IS NULL OR a.http_method = p_http_method)
      AND (p_status_code IS NULL OR a.response_status = p_status_code)
      AND (p_is_success IS NULL OR a.is_success = p_is_success)
      AND (p_security_event IS NULL OR a.security_event = p_security_event)
    ORDER BY a.request_timestamp DESC
    LIMIT p_limit OFFSET p_offset;
END$$

-- ===================================================================================
-- COUNT AUDIT LOGS
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_count_audit_logs$$
CREATE PROCEDURE sp_count_audit_logs(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_endpoint_path VARCHAR(512),
    IN p_http_method VARCHAR(10),
    IN p_status_code INT,
    IN p_is_success BOOLEAN,
    IN p_security_event BOOLEAN,
    IN p_days INT
)
BEGIN
    SELECT COUNT(*) as total_count
    FROM api_audit_log a
    WHERE a.request_timestamp >= DATE_SUB(NOW(), INTERVAL IFNULL(p_days, 30) DAY)
      AND (p_user_id IS NULL OR a.user_id = p_user_id)
      AND (p_project_id IS NULL OR a.project_id = p_project_id)
      AND (p_endpoint_path IS NULL OR a.endpoint_path LIKE CONCAT('%', p_endpoint_path, '%'))
      AND (p_http_method IS NULL OR a.http_method = p_http_method)
      AND (p_status_code IS NULL OR a.response_status = p_status_code)
      AND (p_is_success IS NULL OR a.is_success = p_is_success)
      AND (p_security_event IS NULL OR a.security_event = p_security_event);
END$$

-- ===================================================================================
-- GET AUDIT STATISTICS
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_get_audit_statistics$$
CREATE PROCEDURE sp_get_audit_statistics(IN p_days INT)
BEGIN
    -- Request statistics
    SELECT 
        COUNT(*) as total_requests,
        SUM(CASE WHEN is_success = TRUE THEN 1 ELSE 0 END) as successful_requests,
        SUM(CASE WHEN is_success = FALSE THEN 1 ELSE 0 END) as failed_requests,
        AVG(duration_ms) as avg_duration_ms,
        MAX(duration_ms) as max_duration_ms,
        AVG(request_size_bytes) as avg_request_size,
        AVG(response_size_bytes) as avg_response_size
    FROM api_audit_log
    WHERE request_timestamp >= DATE_SUB(NOW(), INTERVAL IFNULL(p_days, 7) DAY);
    
    -- Requests by method
    SELECT 
        http_method,
        COUNT(*) as request_count,
        AVG(duration_ms) as avg_duration_ms
    FROM api_audit_log
    WHERE request_timestamp >= DATE_SUB(NOW(), INTERVAL IFNULL(p_days, 7) DAY)
    GROUP BY http_method
    ORDER BY request_count DESC;
    
    -- Top endpoints
    SELECT 
        endpoint_path,
        COUNT(*) as request_count,
        AVG(duration_ms) as avg_duration_ms,
        SUM(CASE WHEN is_success = TRUE THEN 1 ELSE 0 END) as success_count,
        SUM(CASE WHEN is_success = FALSE THEN 1 ELSE 0 END) as failure_count
    FROM api_audit_log
    WHERE request_timestamp >= DATE_SUB(NOW(), INTERVAL IFNULL(p_days, 7) DAY)
    GROUP BY endpoint_path
    ORDER BY request_count DESC
    LIMIT 20;
    
    -- Status code distribution
    SELECT 
        response_status,
        COUNT(*) as count
    FROM api_audit_log
    WHERE request_timestamp >= DATE_SUB(NOW(), INTERVAL IFNULL(p_days, 7) DAY)
    GROUP BY response_status
    ORDER BY count DESC;
END$$

-- ===================================================================================
-- GET SECURITY EVENTS
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_get_security_events$$
CREATE PROCEDURE sp_get_security_events(
    IN p_limit INT,
    IN p_offset INT,
    IN p_days INT
)
BEGIN
    SELECT 
        a.id, a.request_id, a.http_method, a.endpoint_path,
        a.user_id, a.user_type, a.client_ip,
        a.response_status, a.error_code, a.error_message,
        a.request_timestamp, a.duration_ms,
        a.tags, a.metadata,
        u.username, u.user_hash
    FROM api_audit_log a
    LEFT JOIN users u ON a.user_id = u.id
    WHERE a.security_event = TRUE
      AND a.request_timestamp >= DATE_SUB(NOW(), INTERVAL IFNULL(p_days, 30) DAY)
    ORDER BY a.request_timestamp DESC
    LIMIT p_limit OFFSET p_offset;
END$$

-- ===================================================================================
-- GET FAILED REQUESTS (For monitoring)
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_get_failed_requests$$
CREATE PROCEDURE sp_get_failed_requests(
    IN p_limit INT,
    IN p_offset INT,
    IN p_days INT
)
BEGIN
    SELECT 
        a.id, a.request_id, a.http_method, a.endpoint_path,
        a.user_id, a.user_type, a.client_ip,
        a.response_status, a.error_code, a.error_message,
        a.request_timestamp, a.duration_ms,
        u.username
    FROM api_audit_log a
    LEFT JOIN users u ON a.user_id = u.id
    WHERE a.is_success = FALSE
      AND a.request_timestamp >= DATE_SUB(NOW(), INTERVAL IFNULL(p_days, 7) DAY)
    ORDER BY a.request_timestamp DESC
    LIMIT p_limit OFFSET p_offset;
END$$

-- ===================================================================================
-- GET USER ACTIVITY SUMMARY
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_get_user_api_activity_summary$$
CREATE PROCEDURE sp_get_user_api_activity_summary(
    IN p_user_id VARCHAR(64),
    IN p_days INT
)
BEGIN
    SELECT 
        COUNT(*) as total_requests,
        SUM(CASE WHEN is_success = TRUE THEN 1 ELSE 0 END) as successful_requests,
        SUM(CASE WHEN is_success = FALSE THEN 1 ELSE 0 END) as failed_requests,
        COUNT(DISTINCT endpoint_path) as unique_endpoints,
        MIN(request_timestamp) as first_request,
        MAX(request_timestamp) as last_request,
        AVG(duration_ms) as avg_duration_ms
    FROM api_audit_log
    WHERE user_id = p_user_id
      AND request_timestamp >= DATE_SUB(NOW(), INTERVAL IFNULL(p_days, 30) DAY);
    
    -- Recent activity by endpoint
    SELECT 
        endpoint_path,
        http_method,
        COUNT(*) as request_count,
        MAX(request_timestamp) as last_access
    FROM api_audit_log
    WHERE user_id = p_user_id
      AND request_timestamp >= DATE_SUB(NOW(), INTERVAL IFNULL(p_days, 30) DAY)
    GROUP BY endpoint_path, http_method
    ORDER BY last_access DESC
    LIMIT 20;
END$$

DELIMITER ;

-- ===================================================================================
-- API AUDIT LOG PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'API audit log stored procedures created successfully!' as status,
       '8 procedures for comprehensive API auditing' as details;

