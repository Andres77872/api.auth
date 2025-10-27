-- ===================================================================================
-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Performance Views Creation Script
-- ===================================================================================
-- This script creates all performance views for query optimization and analytics
-- MySQL Database
-- ===================================================================================

USE magic_auth;

-- =================== QUERY OPTIMIZATION VIEWS ===================

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
    MAX(al.request_timestamp) as last_activity,
    GROUP_CONCAT(DISTINCT ug.group_name ORDER BY ug.group_name) as group_memberships
FROM users u
LEFT JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
LEFT JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
LEFT JOIN v_user_project_access vupa ON u.id = vupa.user_id
LEFT JOIN api_audit_log al ON u.id = al.user_id
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
    COUNT(DISTINCT ug.id) as user_groups_with_access,
    MAX(al.request_timestamp) as last_activity,
    CASE 
        WHEN COUNT(DISTINCT vupa.user_id) = 0 THEN 'inactive'
        WHEN COUNT(DISTINCT vupa.user_id) < 5 THEN 'low'
        WHEN COUNT(DISTINCT vupa.user_id) < 20 THEN 'medium'
        ELSE 'high'
    END as activity_level
FROM projects p
LEFT JOIN v_user_project_access vupa ON p.id = vupa.project_id
LEFT JOIN user_group_projects ugp ON p.id = ugp.project_id AND ugp.is_active = 1
LEFT JOIN user_groups ug ON ugp.user_group_id = ug.id AND ug.is_active = 1
LEFT JOIN api_audit_log al ON p.id = al.project_id
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

-- =================== VIEW CREATION COMPLETE ===================
SELECT 'All performance views created successfully!' as status,
       '6 views created for query optimization and analytics' as details;


