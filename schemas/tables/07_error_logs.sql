-- ===================================================================================
-- ERROR LOGGING SYSTEM
-- Table for comprehensive error logging and tracking
-- ===================================================================================
-- This table captures ALL errors that occur in the system, regardless of DEBUG_MODE
-- DEBUG_MODE only controls what's returned in API responses, not what's logged
-- ===================================================================================

USE magic_auth;

-- =================== ERROR_LOGS TABLE ===================
-- Comprehensive error logging table that captures all error information
-- ALWAYS logs errors regardless of DEBUG_MODE setting
CREATE TABLE IF NOT EXISTS error_logs (
    -- Primary identification
    id VARCHAR(64) NOT NULL,
    error_hash VARCHAR(255) NOT NULL,  -- Unique identifier for this error occurrence
    
    -- Error classification
    error_code VARCHAR(20) NOT NULL,  -- Error code from ErrorCode enum (e.g., AUTH_1001, VAL_3001)
    error_category VARCHAR(50) NOT NULL,  -- Error category (authentication, validation, etc.)
    error_message TEXT NOT NULL,  -- Sanitized user-friendly error message
    status_code INT NOT NULL,  -- HTTP status code (400, 401, 404, 500, etc.)
    severity_level ENUM('info', 'warning', 'error', 'critical') NOT NULL DEFAULT 'error',
    
    -- Context: User and session
    user_id VARCHAR(64) NULL,  -- User who encountered the error (if authenticated)
    project_id VARCHAR(64) NULL,  -- Project context (if available)
    session_id VARCHAR(256) NULL,  -- Session ID (if available)
    
    -- Context: API Request
    request_path VARCHAR(500) NULL,  -- API endpoint path
    request_method VARCHAR(10) NULL,  -- HTTP method (GET, POST, PUT, DELETE, etc.)
    request_query_params JSON NULL,  -- Query parameters
    client_ip VARCHAR(45) NULL,  -- Client IP address (supports IPv4 and IPv6)
    user_agent TEXT NULL,  -- User agent string
    
    -- Context: Function execution
    function_name VARCHAR(255) NULL,  -- Name of the function where error occurred
    function_params JSON NULL,  -- Function parameters (sanitized)
    error_context TEXT NULL,  -- Full error context string (e.g., "create_user(username='john')")
    
    -- Error details
    error_details JSON NULL,  -- Additional error details (sanitized)
    database_error JSON NULL,  -- Database-specific error information (MySQL error codes, etc.)
    original_error_type VARCHAR(255) NULL,  -- Type of the original exception
    original_error_message TEXT NULL,  -- Sanitized original error message
    
    -- Stack trace - ALWAYS captured regardless of DEBUG_MODE
    stack_trace LONGTEXT NULL,  -- Full stack trace for debugging
    
    -- Metadata
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    environment VARCHAR(20) NULL,  -- Environment (development, staging, production)
    debug_mode BOOLEAN NOT NULL DEFAULT FALSE,  -- Was DEBUG_MODE enabled when this error occurred
    
    -- Indexes
    PRIMARY KEY (id),
    UNIQUE KEY uk_error_hash (error_hash),
    INDEX idx_error_code (error_code),
    INDEX idx_error_category (error_category),
    INDEX idx_severity (severity_level),
    INDEX idx_user_id (user_id),
    INDEX idx_project_id (project_id),
    INDEX idx_created_at (created_at),
    INDEX idx_status_code (status_code),
    INDEX idx_request_path (request_path(255)),
    INDEX idx_function_name (function_name),
    INDEX idx_composite_search (error_category, severity_level, created_at),
    
    -- Foreign keys (soft references - don't cascade delete)
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ERROR_LOG_STATISTICS TABLE ===================
-- Aggregated statistics for error monitoring and dashboards
CREATE TABLE IF NOT EXISTS error_log_statistics (
    id VARCHAR(64) NOT NULL,
    error_code VARCHAR(20) NOT NULL,
    error_category VARCHAR(50) NOT NULL,
    occurrence_count INT NOT NULL DEFAULT 1,
    first_occurrence DATETIME NOT NULL,
    last_occurrence DATETIME NOT NULL,
    affected_users_count INT NOT NULL DEFAULT 0,
    affected_projects_count INT NOT NULL DEFAULT 0,
    date_bucket DATE NOT NULL,  -- For daily aggregation
    hour_bucket INT NOT NULL,  -- For hourly aggregation (0-23)
    
    PRIMARY KEY (id),
    UNIQUE KEY uk_error_stats (error_code, date_bucket, hour_bucket),
    INDEX idx_error_code (error_code),
    INDEX idx_error_category (error_category),
    INDEX idx_date_bucket (date_bucket),
    INDEX idx_occurrence_count (occurrence_count),
    INDEX idx_last_occurrence (last_occurrence)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ERROR_LOG_ALERTS TABLE ===================
-- Track error patterns that require immediate attention
CREATE TABLE IF NOT EXISTS error_log_alerts (
    id VARCHAR(64) NOT NULL,
    alert_type ENUM('spike', 'critical_error', 'repeated_error', 'new_error') NOT NULL,
    error_code VARCHAR(20) NOT NULL,
    error_category VARCHAR(50) NOT NULL,
    alert_message TEXT NOT NULL,
    occurrence_count INT NOT NULL,
    time_window_minutes INT NOT NULL,  -- Time window for this alert
    threshold_exceeded BOOLEAN NOT NULL DEFAULT TRUE,
    first_detected DATETIME NOT NULL,
    last_updated DATETIME NOT NULL,
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_by VARCHAR(64) NULL,
    acknowledged_at DATETIME NULL,
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_by VARCHAR(64) NULL,
    resolved_at DATETIME NULL,
    resolution_notes TEXT NULL,
    
    PRIMARY KEY (id),
    INDEX idx_error_code (error_code),
    INDEX idx_alert_type (alert_type),
    INDEX idx_acknowledged (acknowledged),
    INDEX idx_resolved (resolved),
    INDEX idx_first_detected (first_detected),
    
    FOREIGN KEY (acknowledged_by) REFERENCES users(id) ON DELETE SET NULL,
    FOREIGN KEY (resolved_by) REFERENCES users(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== VIEWS FOR ERROR MONITORING ===================

-- View: Recent errors (last 24 hours)
CREATE OR REPLACE VIEW v_recent_error_logs AS
SELECT 
    id,
    error_code,
    error_category,
    error_message,
    status_code,
    severity_level,
    user_id,
    project_id,
    request_path,
    request_method,
    function_name,
    created_at
FROM error_logs
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY created_at DESC;

-- View: Error summary by code
CREATE OR REPLACE VIEW v_error_summary_by_code AS
SELECT 
    error_code,
    error_category,
    COUNT(*) as total_occurrences,
    COUNT(DISTINCT user_id) as unique_users_affected,
    COUNT(DISTINCT project_id) as unique_projects_affected,
    MIN(created_at) as first_occurrence,
    MAX(created_at) as last_occurrence,
    AVG(status_code) as avg_status_code
FROM error_logs
GROUP BY error_code, error_category
ORDER BY total_occurrences DESC;

-- View: Critical errors requiring attention
CREATE OR REPLACE VIEW v_critical_errors AS
SELECT 
    id,
    error_code,
    error_category,
    error_message,
    user_id,
    project_id,
    request_path,
    function_name,
    stack_trace,
    created_at
FROM error_logs
WHERE severity_level = 'critical'
   OR status_code = 500
   OR error_category IN ('database', 'internal')
ORDER BY created_at DESC;

-- View: Error frequency by hour (last 7 days)
CREATE OR REPLACE VIEW v_error_frequency_hourly AS
SELECT 
    DATE(created_at) as error_date,
    HOUR(created_at) as error_hour,
    error_category,
    COUNT(*) as error_count
FROM error_logs
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY DATE(created_at), HOUR(created_at), error_category
ORDER BY error_date DESC, error_hour DESC, error_count DESC;

-- =================== COMPLETION MESSAGE ===================
SELECT 'Error logging tables created successfully!' as status,
       '4 tables and 4 views created for comprehensive error tracking' as details;
