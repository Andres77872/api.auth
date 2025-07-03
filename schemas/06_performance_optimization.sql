-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Performance Optimization Script (Updated for Group-Based Access)
-- MySQL Database

USE magic_auth;

-- =================== QUERY OPTIMIZATION VIEWS ===================

-- View for quick user permission checks through group hierarchy
CREATE OR REPLACE VIEW v_user_effective_permissions AS
SELECT DISTINCT 
    ugm.user_id,
    ugpg.project_id,
    p.permission_name,
    p.permission_display_name,
    p.permission_category,
    pg.group_name as granted_through_role,
    ug.group_name as granted_through_user_group,
    p.permission_level,
    pg.group_level as role_level,
    ug.group_level as user_group_level
FROM user_group_members ugm
JOIN user_groups ug ON ugm.user_group_id = ug.id
JOIN user_group_permission_groups ugpg ON ug.id = ugpg.user_group_id
JOIN permission_groups pg ON ugpg.permission_group_id = pg.id
JOIN permission_group_permissions pgp ON pg.id = pgp.permission_group_id
JOIN permissions p ON pgp.permission_id = p.id
WHERE ugm.is_active = 1 
  AND ug.is_active = 1
  AND ugpg.is_active = 1
  AND pg.is_active = 1 
  AND pgp.is_active = 1 
  AND p.is_active = 1;

-- View for user project access through groups
CREATE OR REPLACE VIEW v_user_project_access AS
SELECT 
    u.id as user_id,
    u.username,
    u.user_hash,
    u.user_type,
    p.id as project_id,
    p.project_name,
    p.project_hash,
    ug.group_name as access_through_group,
    ugp.granted_at as access_granted_at,
    CASE u.user_type
        WHEN 'root' THEN 'root_access'
        WHEN 'admin' THEN 'admin_group_access'
        WHEN 'consumer' THEN 'group_access'
    END as access_type
FROM users u
JOIN user_group_members ugm ON u.id = ugm.user_id
JOIN user_groups ug ON ugm.user_group_id = ug.id
JOIN user_group_projects ugp ON ug.id = ugp.user_group_id
JOIN projects p ON ugp.project_id = p.id
WHERE u.is_active = 1
  AND ugm.is_active = 1
  AND ug.is_active = 1
  AND ugp.is_active = 1
  AND p.is_active = 1
UNION
-- Root users have access to all projects
SELECT 
    u.id as user_id,
    u.username,
    u.user_hash,
    u.user_type,
    p.id as project_id,
    p.project_name,
    p.project_hash,
    'root_global_access' as access_through_group,
    p.project_created as access_granted_at,
    'root_access' as access_type
FROM users u
CROSS JOIN projects p
WHERE u.user_type = 'root'
  AND u.is_active = 1
  AND p.is_active = 1;

-- View for user project access summary
CREATE OR REPLACE VIEW v_user_project_access_summary AS
SELECT 
    u.id as user_id,
    u.username,
    u.user_type,
    COUNT(DISTINCT vupa.project_id) as accessible_projects,
    COUNT(DISTINCT ugm.user_group_id) as member_of_groups,
    GROUP_CONCAT(DISTINCT ug.group_name ORDER BY ug.group_name) as user_groups
FROM users u
LEFT JOIN v_user_project_access vupa ON u.id = vupa.user_id
LEFT JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
LEFT JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
WHERE u.is_active = 1
GROUP BY u.id, u.username, u.user_type;

-- View for active user sessions with group context
CREATE OR REPLACE VIEW v_active_user_sessions AS
SELECT 
    u.id as user_id,
    u.username,
    u.user_type,
    us.session_token,
    us.expires_at,
    us.project_id,
    p.project_name,
    GROUP_CONCAT(DISTINCT ug.group_name ORDER BY ug.group_name) as user_groups
FROM users u
JOIN user_sessions us ON u.id = us.user_id
JOIN projects p ON us.project_id = p.id
LEFT JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
LEFT JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
WHERE u.is_active = 1 
  AND us.is_active = 1 
  AND us.expires_at > NOW()
  AND p.is_active = 1
GROUP BY u.id, u.username, u.user_type, us.session_token, us.expires_at, us.project_id, p.project_name;

-- User Summary View for enhanced performance
CREATE OR REPLACE VIEW user_summary_view AS
SELECT 
    u.id,
    u.user_hash,
    u.username,
    u.email,
    u.user_type,
    u.is_active,
    u.created_at,
    COUNT(DISTINCT ugm.user_group_id) as total_groups,
    COUNT(DISTINCT vupa.project_id) as total_projects,
    MAX(al.created_at) as last_activity,
    GROUP_CONCAT(DISTINCT ug.group_name ORDER BY ug.group_name) as group_memberships
FROM users u
LEFT JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
LEFT JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
LEFT JOIN v_user_project_access vupa ON u.id = vupa.user_id
LEFT JOIN activity_logs al ON u.id = al.user_id
WHERE u.is_active = 1
GROUP BY u.id;

-- Project Health View for monitoring and analytics
CREATE OR REPLACE VIEW project_health_view AS
SELECT 
    p.id,
    p.project_hash,
    p.project_name,
    p.archived,
    p.owner_id,
    COUNT(DISTINCT vupa.user_id) as member_count,
    COUNT(DISTINCT pg.id) as role_count,
    COUNT(DISTINCT perm.id) as permission_count,
    COUNT(DISTINCT ug.id) as user_groups_with_access,
    MAX(al.created_at) as last_activity,
    CASE 
        WHEN COUNT(DISTINCT vupa.user_id) = 0 THEN 'inactive'
        WHEN COUNT(DISTINCT vupa.user_id) < 5 THEN 'low'
        WHEN COUNT(DISTINCT vupa.user_id) < 20 THEN 'medium'
        ELSE 'high'
    END as activity_level
FROM projects p
LEFT JOIN v_user_project_access vupa ON p.id = vupa.project_id
LEFT JOIN permission_groups pg ON p.id = pg.project_id AND pg.is_active = 1
LEFT JOIN permissions perm ON p.id = perm.project_id AND perm.is_active = 1
LEFT JOIN user_group_projects ugp ON p.id = ugp.project_id AND ugp.is_active = 1
LEFT JOIN user_groups ug ON ugp.user_group_id = ug.id AND ug.is_active = 1
LEFT JOIN activity_logs al ON p.id = al.project_id
WHERE p.is_active = 1
GROUP BY p.id;

-- View for hierarchical group structure
CREATE OR REPLACE VIEW v_user_group_hierarchy AS
WITH RECURSIVE group_hierarchy AS (
    -- Base case: root level groups
    SELECT 
        id,
        group_hash,
        group_name,
        group_description,
        parent_group_id,
        group_level,
        CAST(group_name AS CHAR(1000)) as hierarchy_path,
        0 as calculated_level
    FROM user_groups 
    WHERE parent_group_id IS NULL AND is_active = 1
    
    UNION ALL
    
    -- Recursive case: child groups
    SELECT 
        ug.id,
        ug.group_hash,
        ug.group_name,
        ug.group_description,
        ug.parent_group_id,
        ug.group_level,
        CONCAT(gh.hierarchy_path, ' > ', ug.group_name),
        gh.calculated_level + 1
    FROM user_groups ug
    JOIN group_hierarchy gh ON ug.parent_group_id = gh.id
    WHERE ug.is_active = 1
)
SELECT * FROM group_hierarchy;

-- View for hierarchical permission structure
CREATE OR REPLACE VIEW v_permission_hierarchy AS
WITH RECURSIVE permission_hierarchy AS (
    -- Base case: root level permissions
    SELECT 
        id,
        permission_hash,
        project_id,
        permission_name,
        permission_display_name,
        permission_description,
        permission_category,
        parent_permission_id,
        permission_level,
        CAST(permission_name AS CHAR(1000)) as hierarchy_path,
        0 as calculated_level
    FROM permissions 
    WHERE parent_permission_id IS NULL AND is_active = 1
    
    UNION ALL
    
    -- Recursive case: child permissions
    SELECT 
        p.id,
        p.permission_hash,
        p.project_id,
        p.permission_name,
        p.permission_display_name,
        p.permission_description,
        p.permission_category,
        p.parent_permission_id,
        p.permission_level,
        CONCAT(ph.hierarchy_path, ' > ', p.permission_name),
        ph.calculated_level + 1
    FROM permissions p
    JOIN permission_hierarchy ph ON p.parent_permission_id = ph.id
    WHERE p.is_active = 1
)
SELECT * FROM permission_hierarchy;

-- =================== ENHANCED STORED PROCEDURES ===================

DELIMITER $$

-- Check user permission efficiently through group hierarchy
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
    ELSE
        -- Check through group-based permissions
        SELECT COUNT(*) > 0 INTO p_has_permission
        FROM v_user_effective_permissions
        WHERE user_id = p_user_id 
          AND project_id = p_project_id 
          AND permission_name = p_permission_name;
    END IF;
END$$

-- Get user's accessible projects through groups
CREATE PROCEDURE sp_get_user_projects(
    IN p_user_id INT
)
BEGIN
    DECLARE v_user_type VARCHAR(20);
    
    -- Get user type
    SELECT user_type INTO v_user_type
    FROM users
    WHERE id = p_user_id AND is_active = 1;
    
    -- Return projects based on user type and group memberships
    IF v_user_type = 'root' THEN
        SELECT p.*, 'root_access' as access_type, NULL as access_through_group
        FROM projects p
        WHERE p.is_active = 1;
    ELSE
        SELECT p.*, vupa.access_type, vupa.access_through_group
        FROM projects p
        JOIN v_user_project_access vupa ON p.id = vupa.project_id
        WHERE vupa.user_id = p_user_id;
    END IF;
END$$

-- Get user groups hierarchy for a user
CREATE PROCEDURE sp_get_user_group_hierarchy(
    IN p_user_id INT
)
BEGIN
    SELECT 
        ugh.*,
        ugm.assigned_at as user_joined_at,
        COUNT(DISTINCT ugp.project_id) as projects_accessible
    FROM v_user_group_hierarchy ugh
    JOIN user_group_members ugm ON ugh.id = ugm.user_group_id
    LEFT JOIN user_group_projects ugp ON ugh.id = ugp.user_group_id AND ugp.is_active = 1
    WHERE ugm.user_id = p_user_id 
      AND ugm.is_active = 1
    GROUP BY ugh.id, ugm.assigned_at
    ORDER BY ugh.calculated_level, ugh.group_name;
END$$

-- Get permission hierarchy for a project
CREATE PROCEDURE sp_get_project_permission_hierarchy(
    IN p_project_id INT
)
BEGIN
    SELECT 
        ph.*,
        CASE WHEN pgp.permission_id IS NOT NULL THEN TRUE ELSE FALSE END as is_assigned_to_group,
        COUNT(DISTINCT pgp.permission_group_id) as assigned_to_groups_count
    FROM v_permission_hierarchy ph
    LEFT JOIN permission_group_permissions pgp ON ph.id = pgp.permission_id AND pgp.is_active = 1
    WHERE ph.project_id = p_project_id
    GROUP BY ph.id
    ORDER BY ph.calculated_level, ph.permission_name;
END$$

-- Clean up orphaned records with group awareness
CREATE PROCEDURE sp_cleanup_orphaned_records()
BEGIN
    -- Remove user group memberships for deleted users
    UPDATE user_group_members ugm
    LEFT JOIN users u ON ugm.user_id = u.id
    SET ugm.is_active = 0, ugm.removed_at = NOW()
    WHERE u.id IS NULL OR u.is_active = 0;
    
    -- Remove user group project assignments for deleted groups or projects
    UPDATE user_group_projects ugp
    LEFT JOIN user_groups ug ON ugp.user_group_id = ug.id
    LEFT JOIN projects p ON ugp.project_id = p.id
    SET ugp.is_active = 0, ugp.revoked_at = NOW()
    WHERE ug.id IS NULL OR ug.is_active = 0 OR p.id IS NULL OR p.is_active = 0;
    
    -- Remove user group permission group assignments for deleted items
    UPDATE user_group_permission_groups ugpg
    LEFT JOIN user_groups ug ON ugpg.user_group_id = ug.id
    LEFT JOIN projects p ON ugpg.project_id = p.id
    LEFT JOIN permission_groups pg ON ugpg.permission_group_id = pg.id
    SET ugpg.is_active = 0, ugpg.removed_at = NOW()
    WHERE ug.id IS NULL OR ug.is_active = 0 
       OR p.id IS NULL OR p.is_active = 0
       OR pg.id IS NULL OR pg.is_active = 0;
    
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

-- Clean up expired permission cache entries
CREATE PROCEDURE sp_cleanup_permission_cache()
BEGIN
    DELETE FROM permission_cache 
    WHERE expires_at < NOW();
    
    SELECT ROW_COUNT() as cleaned_cache_entries;
END$$

-- Get comprehensive user access summary
CREATE PROCEDURE sp_get_user_access_summary(
    IN p_user_id INT
)
BEGIN
    DECLARE v_user_type VARCHAR(20);
    
    SELECT user_type INTO v_user_type
    FROM users WHERE id = p_user_id AND is_active = 1;
    
    -- User basic info
    SELECT 
        id, user_hash, username, email, user_type, created_at,
        v_user_type as confirmed_user_type
    FROM users 
    WHERE id = p_user_id AND is_active = 1;
    
    -- User groups
    SELECT 
        ug.group_name,
        ug.group_description,
        ug.group_level,
        pug.group_name as parent_group,
        ugm.assigned_at
    FROM user_group_members ugm
    JOIN user_groups ug ON ugm.user_group_id = ug.id
    LEFT JOIN user_groups pug ON ug.parent_group_id = pug.id
    WHERE ugm.user_id = p_user_id AND ugm.is_active = 1 AND ug.is_active = 1
    ORDER BY ug.group_level, ug.group_name;
    
    -- Accessible projects
    SELECT DISTINCT
        p.project_name,
        p.project_description,
        vupa.access_through_group,
        vupa.access_type,
        vupa.access_granted_at
    FROM v_user_project_access vupa
    JOIN projects p ON vupa.project_id = p.id
    WHERE vupa.user_id = p_user_id
    ORDER BY p.project_name;
    
    -- Effective permissions summary
    SELECT 
        project_id,
        COUNT(DISTINCT permission_name) as total_permissions,
        COUNT(DISTINCT granted_through_role) as granted_through_roles,
        COUNT(DISTINCT granted_through_user_group) as granted_through_user_groups
    FROM v_user_effective_permissions
    WHERE user_id = p_user_id
    GROUP BY project_id;
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

    -- Check for orphaned user group memberships
    SELECT COUNT(*) as orphaned_user_group_memberships,
           'User group memberships without valid users or groups' as issue_description
    FROM user_group_members ugm
    LEFT JOIN users u ON ugm.user_id = u.id
    LEFT JOIN user_groups ug ON ugm.user_group_id = ug.id
    WHERE ugm.is_active = 1 
      AND (u.id IS NULL OR u.is_active = 0 OR ug.id IS NULL OR ug.is_active = 0);

    -- Check for orphaned user group project assignments
    SELECT COUNT(*) as orphaned_group_project_assignments,
           'User group project assignments without valid groups or projects' as issue_description
    FROM user_group_projects ugp
    LEFT JOIN user_groups ug ON ugp.user_group_id = ug.id
    LEFT JOIN projects p ON ugp.project_id = p.id
    WHERE ugp.is_active = 1 
      AND (ug.id IS NULL OR ug.is_active = 0 OR p.id IS NULL OR p.is_active = 0);

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
    
    -- Check for circular references in user group hierarchy
    SELECT COUNT(*) as circular_group_references,
           'Potential circular references in user group hierarchy' as issue_description
    FROM user_groups ug1
    JOIN user_groups ug2 ON ug1.parent_group_id = ug2.id
    WHERE ug2.parent_group_id = ug1.id AND ug1.is_active = 1 AND ug2.is_active = 1;
    
    -- Check for permission groups without any permissions
    SELECT COUNT(*) as empty_permission_groups,
           'Permission groups without any assigned permissions' as issue_description
    FROM permission_groups pg
    LEFT JOIN permission_group_permissions pgp ON pg.id = pgp.permission_group_id AND pgp.is_active = 1
    WHERE pg.is_active = 1 AND pgp.id IS NULL;
    
    -- Check for user groups without any users
    SELECT COUNT(*) as empty_user_groups,
           'User groups without any members' as issue_description
    FROM user_groups ug
    LEFT JOIN user_group_members ugm ON ug.id = ugm.user_group_id AND ugm.is_active = 1
    WHERE ug.is_active = 1 AND ugm.id IS NULL;
END$$
DELIMITER ;

-- =================== SUMMARY ===================
SELECT 'Performance optimization script completed successfully for group-based access!' as status;