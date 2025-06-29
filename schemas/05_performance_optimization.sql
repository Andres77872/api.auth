-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Performance Optimization Script
-- MySQL Database

USE magic_auth;

-- =================== ADDITIONAL PERFORMANCE INDEXES ===================

-- User authentication queries
CREATE INDEX idx_users_username_password ON users(username, password_hash, is_active);
CREATE INDEX idx_users_email_password ON users(email, password_hash, is_active);
CREATE INDEX idx_users_type_active ON users(user_type, is_active);

-- Admin user project access queries
CREATE INDEX idx_admin_projects_user_active ON admin_project_assignments(user_id, is_active);
CREATE INDEX idx_admin_projects_project_user ON admin_project_assignments(project_id, user_id, is_active);

-- Session lookup optimization
CREATE INDEX idx_sessions_token_active ON user_sessions(session_token, is_active, expires_at);

-- Permission checks optimization
CREATE INDEX idx_user_proj_perm_groups_lookup ON user_project_permission_groups(user_id, project_id, permission_group_id, is_active);
CREATE INDEX idx_perm_group_permissions_active ON permission_group_permissions(permission_group_id, permission_id, is_active);

-- User group membership queries
CREATE INDEX idx_user_group_members_user ON user_group_members(user_id, is_active);
CREATE INDEX idx_user_group_members_group ON user_group_members(user_group_id, is_active);

-- Project access queries
CREATE INDEX idx_user_projects_user_project ON user_projects(user_id, project_id, is_active);
CREATE INDEX idx_user_group_projects_access ON user_group_projects(user_group_id, project_id, is_active);

-- Audit log queries
CREATE INDEX idx_audit_log_project_time ON permission_audit_log(project_id, action_timestamp);
CREATE INDEX idx_audit_log_user_time ON permission_audit_log(target_user_id, action_timestamp);
CREATE INDEX idx_audit_log_action_type ON permission_audit_log(action_type, action_timestamp);

-- Activity log queries
CREATE INDEX idx_activity_log_user_type_time ON activity_logs(user_id, activity_type, created_at);
CREATE INDEX idx_activity_log_project_time ON activity_logs(project_id, created_at);
CREATE INDEX idx_activity_log_target_user_time ON activity_logs(target_user_id, created_at);
CREATE INDEX idx_activity_log_type_time ON activity_logs(activity_type, created_at);

-- =================== COMPOSITE INDEXES FOR COMPLEX QUERIES ===================

-- User permission check query optimization
CREATE INDEX idx_user_permission_check ON permissions(project_id, permission_name, is_active);

-- Group permission lookup
CREATE INDEX idx_permission_groups_lookup ON permission_groups(project_id, group_name, is_active);

-- User project group membership
CREATE INDEX idx_user_project_groups_lookup ON user_project_groups(user_project_id, group_id, is_active);

-- =================== QUERY OPTIMIZATION VIEWS ===================

-- View for quick user permission checks
CREATE OR REPLACE VIEW v_user_effective_permissions AS
SELECT DISTINCT 
    uppg.user_id,
    uppg.project_id,
    p.permission_name,
    p.permission_display_name,
    p.permission_category,
    pg.group_name as granted_through_role
FROM user_project_permission_groups uppg
JOIN permission_groups pg ON uppg.permission_group_id = pg.id
JOIN permission_group_permissions pgp ON pg.id = pgp.permission_group_id
JOIN permissions p ON pgp.permission_id = p.id
WHERE uppg.is_active = 1 
  AND pg.is_active = 1 
  AND pgp.is_active = 1 
  AND p.is_active = 1;

-- View for admin project access
CREATE OR REPLACE VIEW v_admin_project_access AS
SELECT 
    u.id as user_id,
    u.username,
    u.user_hash,
    p.id as project_id,
    p.project_name,
    p.project_hash,
    apa.assigned_at
FROM users u
JOIN admin_project_assignments apa ON u.id = apa.user_id
JOIN projects p ON apa.project_id = p.id
WHERE u.user_type = 'admin'
  AND u.is_active = 1
  AND apa.is_active = 1
  AND p.is_active = 1;

-- View for user project access summary
CREATE OR REPLACE VIEW v_user_project_access_summary AS
SELECT 
    u.id as user_id,
    u.username,
    u.user_type,
    COUNT(DISTINCT 
        CASE 
            WHEN u.user_type = 'root' THEN p.id
            WHEN u.user_type = 'admin' THEN apa.project_id
            WHEN u.user_type = 'consumer' THEN up.project_id
        END
    ) as accessible_projects
FROM users u
LEFT JOIN admin_project_assignments apa ON u.id = apa.user_id AND u.user_type = 'admin' AND apa.is_active = 1
LEFT JOIN user_projects up ON u.id = up.user_id AND u.user_type = 'consumer' AND up.is_active = 1
LEFT JOIN projects p ON u.user_type = 'root' AND p.is_active = 1
WHERE u.is_active = 1
GROUP BY u.id, u.username, u.user_type;

-- =================== STORED PROCEDURES FOR COMMON OPERATIONS ===================

DELIMITER $$

-- Check user permission efficiently
CREATE PROCEDURE sp_check_user_permission(
    IN p_user_id INT,
    IN p_project_id INT,
    IN p_permission_name VARCHAR(100),
    OUT p_has_permission BOOLEAN
)
BEGIN
    DECLARE v_user_type VARCHAR(20);
    
    -- Get user type
    SELECT user_type INTO v_user_type
    FROM users
    WHERE id = p_user_id AND is_active = 1;
    
    -- Root users always have permission
    IF v_user_type = 'root' THEN
        SET p_has_permission = TRUE;
    -- Admin users have permission in their assigned projects
    ELSEIF v_user_type = 'admin' THEN
        SELECT COUNT(*) > 0 INTO p_has_permission
        FROM admin_project_assignments
        WHERE user_id = p_user_id 
          AND project_id = p_project_id 
          AND is_active = 1;
    -- Consumer users check through RBAC
    ELSE
        SELECT COUNT(*) > 0 INTO p_has_permission
        FROM v_user_effective_permissions
        WHERE user_id = p_user_id 
          AND project_id = p_project_id 
          AND permission_name = p_permission_name;
    END IF;
END$$

-- Get user's accessible projects
CREATE PROCEDURE sp_get_user_projects(
    IN p_user_id INT
)
BEGIN
    DECLARE v_user_type VARCHAR(20);
    
    -- Get user type
    SELECT user_type INTO v_user_type
    FROM users
    WHERE id = p_user_id AND is_active = 1;
    
    -- Return projects based on user type
    IF v_user_type = 'root' THEN
        SELECT p.*, 'root_access' as access_type
        FROM projects p
        WHERE p.is_active = 1;
    ELSEIF v_user_type = 'admin' THEN
        SELECT p.*, 'admin_access' as access_type
        FROM projects p
        JOIN admin_project_assignments apa ON p.id = apa.project_id
        WHERE apa.user_id = p_user_id 
          AND apa.is_active = 1 
          AND p.is_active = 1;
    ELSE
        SELECT p.*, 'consumer_access' as access_type
        FROM projects p
        JOIN user_projects up ON p.id = up.project_id
        WHERE up.user_id = p_user_id 
          AND up.is_active = 1 
          AND p.is_active = 1;
    END IF;
END$$

DELIMITER ;

-- =================== TABLE PARTITIONING FOR LARGE TABLES ===================

-- Partition audit log by month (if supported by your MySQL version)
-- ALTER TABLE permission_audit_log
-- PARTITION BY RANGE (YEAR(action_timestamp) * 100 + MONTH(action_timestamp)) (
--     PARTITION p202401 VALUES LESS THAN (202402),
--     PARTITION p202402 VALUES LESS THAN (202403),
--     -- Add more partitions as needed
--     PARTITION p_future VALUES LESS THAN MAXVALUE
-- );

-- =================== MAINTENANCE PROCEDURES ===================

DELIMITER $$

-- Clean up expired sessions
CREATE PROCEDURE sp_cleanup_expired_sessions()
BEGIN
    UPDATE user_sessions 
    SET is_active = 0 
    WHERE expires_at < NOW() AND is_active = 1;
END$$

-- Archive old audit logs
CREATE PROCEDURE sp_archive_audit_logs(
    IN p_days_to_keep INT
)
BEGIN
    -- This is a placeholder - implement based on your archival strategy
    -- For example, move old records to an archive table
    SELECT COUNT(*) as records_to_archive
    FROM permission_audit_log
    WHERE action_timestamp < DATE_SUB(NOW(), INTERVAL p_days_to_keep DAY);
END$$

-- Clean up old activity logs
CREATE PROCEDURE sp_cleanup_activity_logs(
    IN p_days_to_keep INT
)
BEGIN
    DELETE FROM activity_logs 
    WHERE created_at < DATE_SUB(NOW(), INTERVAL p_days_to_keep DAY);
    
    SELECT ROW_COUNT() as deleted_records;
END$$

-- Get activity log statistics
CREATE PROCEDURE sp_activity_log_stats()
BEGIN
    SELECT 
        COUNT(*) as total_activities,
        COUNT(DISTINCT user_id) as unique_users,
        COUNT(DISTINCT project_id) as unique_projects,
        COUNT(DISTINCT activity_type) as unique_activity_types,
        MIN(created_at) as oldest_activity,
        MAX(created_at) as newest_activity
    FROM activity_logs;
    
    SELECT 
        activity_type,
        COUNT(*) as count,
        COUNT(DISTINCT user_id) as unique_users
    FROM activity_logs 
    WHERE created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY)
    GROUP BY activity_type 
    ORDER BY count DESC;
END$$

DELIMITER ;

-- =================== ANALYSIS TABLES ===================

-- Table for caching expensive permission calculations
CREATE TABLE IF NOT EXISTS permission_cache (
    user_id INT UNSIGNED NOT NULL,
    project_id INT UNSIGNED NOT NULL,
    permission_name VARCHAR(100) NOT NULL,
    has_permission BOOLEAN NOT NULL,
    cached_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    expires_at DATETIME NOT NULL,
    PRIMARY KEY (user_id, project_id, permission_name),
    INDEX idx_expires (expires_at),
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERFORMANCE MONITORING ===================

-- Enable slow query log (requires SUPER privilege)
-- SET GLOBAL slow_query_log = 'ON';
-- SET GLOBAL long_query_time = 2;
-- SET GLOBAL slow_query_log_file = '/var/log/mysql/slow-query.log';

-- Example query to identify missing indexes
-- SELECT 
--     tables.table_schema,
--     tables.table_name,
--     tables.table_rows,
--     round(data_length / 1024 / 1024, 2) as data_mb,
--     round(index_length / 1024 / 1024, 2) as index_mb
-- FROM information_schema.tables
-- WHERE table_schema = 'magic_auth'
-- ORDER BY data_length DESC; 