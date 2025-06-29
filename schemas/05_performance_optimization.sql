-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Performance Optimization Script
-- MySQL Database

USE magic_auth;

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

-- View for active user sessions
CREATE OR REPLACE VIEW v_active_user_sessions AS
SELECT 
    u.id as user_id,
    u.username,
    u.user_type,
    us.session_token,
    us.expires_at,
    up.project_id,
    p.project_name
FROM users u
JOIN user_projects up ON u.id = up.user_id
JOIN user_sessions us ON us.user_project_id = up.id
JOIN projects p ON up.project_id = p.id
WHERE u.is_active = 1 
  AND up.is_active = 1 
  AND us.is_active = 1 
  AND us.expires_at > NOW();

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

-- Procedure to validate user access efficiently
CREATE PROCEDURE sp_validate_user_access(
    IN p_user_id INT,
    IN p_project_id INT,
    OUT p_has_access BOOLEAN,
    OUT p_access_type VARCHAR(20)
)
BEGIN
    DECLARE v_user_type VARCHAR(20);
    
    -- Get user type
    SELECT user_type INTO v_user_type
    FROM users
    WHERE id = p_user_id AND is_active = 1;
    
    IF v_user_type = 'root' THEN
        SET p_has_access = TRUE;
        SET p_access_type = 'root_access';
    ELSEIF v_user_type = 'admin' THEN
        SELECT COUNT(*) > 0 INTO p_has_access
        FROM admin_project_assignments
        WHERE user_id = p_user_id 
          AND project_id = p_project_id 
          AND is_active = 1;
        SET p_access_type = IF(p_has_access, 'admin_access', 'no_access');
    ELSE -- consumer
        SELECT COUNT(*) > 0 INTO p_has_access
        FROM user_projects
        WHERE user_id = p_user_id 
          AND project_id = p_project_id 
          AND is_active = 1;
        SET p_access_type = IF(p_has_access, 'consumer_access', 'no_access');
    END IF;
END$$

-- Procedure to clean up orphaned records
CREATE PROCEDURE sp_cleanup_orphaned_records()
BEGIN
    -- Remove user_project_groups entries for deleted user_projects
    UPDATE user_project_groups upg
    LEFT JOIN user_projects up ON upg.user_project_id = up.id
    SET upg.is_active = 0, upg.removed_at = NOW()
    WHERE up.id IS NULL OR up.is_active = 0;
    
    -- Remove user_group_members for deleted users
    UPDATE user_group_members ugm
    LEFT JOIN users u ON ugm.user_id = u.id
    SET ugm.is_active = 0, ugm.removed_at = NOW()
    WHERE u.id IS NULL OR u.is_active = 0;
    
    -- Remove permission assignments for deleted users
    UPDATE user_project_permission_groups uppg
    LEFT JOIN users u ON uppg.user_id = u.id
    SET uppg.is_active = 0, uppg.removed_at = NOW()
    WHERE u.id IS NULL OR u.is_active = 0;
    
    -- Report cleanup results
    SELECT 
        ROW_COUNT() as cleaned_records,
        NOW() as cleanup_timestamp;
END$$

-- Clean up expired sessions
CREATE PROCEDURE sp_cleanup_expired_sessions()
BEGIN
    UPDATE user_sessions 
    SET is_active = 0 
    WHERE expires_at < NOW() AND is_active = 1;
    
    SELECT ROW_COUNT() as cleaned_sessions;
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

-- Clean up expired permission cache entries
CREATE PROCEDURE sp_cleanup_permission_cache()
BEGIN
    DELETE FROM permission_cache 
    WHERE expires_at < NOW();
    
    SELECT ROW_COUNT() as cleaned_cache_entries;
END$$

DELIMITER ;

-- =================== DATA CONSISTENCY CHECKS ===================

-- Create procedure to check system health
DELIMITER $$
CREATE PROCEDURE sp_system_health_check()
BEGIN
    -- Check for users without proper type
    SELECT COUNT(*) as users_without_valid_type,
           'Users with invalid user_type' as issue_description
    FROM users
    WHERE user_type NOT IN ('root', 'admin', 'consumer')
       OR user_type IS NULL;

    -- Check for orphaned sessions
    SELECT COUNT(*) as orphaned_sessions,
           'User sessions without valid user_projects' as issue_description
    FROM user_sessions us
    LEFT JOIN user_projects up ON us.user_project_id = up.id
    WHERE up.id IS NULL OR up.is_active = 0;

    -- Check for admin users without project assignments
    SELECT COUNT(*) as admins_without_assignments,
           'Admin users without active project assignments' as issue_description
    FROM users u
    LEFT JOIN admin_project_assignments apa ON u.id = apa.user_id AND apa.is_active = 1
    WHERE u.user_type = 'admin'
      AND u.is_active = 1
      AND apa.id IS NULL
      AND u.assigned_project_id IS NULL;
      
    -- Check for expired sessions that are still marked active
    SELECT COUNT(*) as expired_active_sessions,
           'Expired sessions still marked as active' as issue_description
    FROM user_sessions
    WHERE is_active = 1 AND expires_at < NOW();
    
    -- Check for permission cache entries that should be cleaned up
    SELECT COUNT(*) as expired_cache_entries,
           'Expired permission cache entries' as issue_description
    FROM permission_cache
    WHERE expires_at < NOW();
END$$
DELIMITER ;

-- =================== PERFORMANCE MONITORING ===================

-- Create procedure for performance statistics
DELIMITER $$
CREATE PROCEDURE sp_performance_stats()
BEGIN
    -- Table sizes
    SELECT 
        'users' as table_name,
        COUNT(*) as total_records,
        COUNT(CASE WHEN is_active = 1 THEN 1 END) as active_records
    FROM users
    UNION ALL
    SELECT 
        'projects' as table_name,
        COUNT(*) as total_records,
        COUNT(CASE WHEN is_active = 1 THEN 1 END) as active_records
    FROM projects
    UNION ALL
    SELECT 
        'user_sessions' as table_name,
        COUNT(*) as total_records,
        COUNT(CASE WHEN is_active = 1 AND expires_at > NOW() THEN 1 END) as active_records
    FROM user_sessions
    UNION ALL
    SELECT 
        'activity_logs' as table_name,
        COUNT(*) as total_records,
        COUNT(CASE WHEN created_at >= DATE_SUB(NOW(), INTERVAL 30 DAY) THEN 1 END) as recent_records
    FROM activity_logs;
    
    -- Index usage statistics (MySQL 5.7+)
    SELECT 
        TABLE_NAME,
        INDEX_NAME,
        SEQ_IN_INDEX,
        COLUMN_NAME,
        CARDINALITY
    FROM INFORMATION_SCHEMA.STATISTICS 
    WHERE TABLE_SCHEMA = 'magic_auth'
    ORDER BY TABLE_NAME, INDEX_NAME, SEQ_IN_INDEX;
END$$
DELIMITER ;

-- =================== SUMMARY ===================
SELECT 'Performance optimization script completed successfully' as status; 