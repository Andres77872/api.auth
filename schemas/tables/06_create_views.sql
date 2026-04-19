-- ===================================================================================
-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Performance Views Creation Script - GROUPS OF GROUPS Architecture
-- ===================================================================================
-- This script creates all views for the authentication system
-- MySQL Database
-- ===================================================================================

USE magic_auth;

-- ===================================================================================
-- USER PROJECT ACCESS VIEW
-- Shows how users access projects via: User → User Group → Project Group → Project
-- ===================================================================================
CREATE OR REPLACE VIEW v_user_project_access AS
SELECT 
    u.id as user_id,
    u.username,
    u.user_hash,
    u.user_type,
    ug.id as user_group_id,
    ug.group_name as user_group_name,
    pg.id as project_group_id,
    pg.group_name as project_group_name,
    p.id as project_id,
    p.project_name,
    p.project_hash,
    ugpg.granted_at as access_granted_at,
    'group_access' as access_type
FROM users u
JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
JOIN user_group_project_groups ugpg ON ug.id = ugpg.user_group_id AND ugpg.is_active = 1
JOIN project_groups pg ON ugpg.project_group_id = pg.id AND pg.is_active = 1
JOIN project_group_members pgm ON pg.id = pgm.project_group_id AND pgm.is_active = 1
JOIN projects p ON pgm.project_id = p.id AND p.is_active = 1
WHERE u.is_active = 1

UNION

-- Root users have access to all ACTIVE and NON-ARCHIVED projects
SELECT 
    u.id as user_id,
    u.username,
    u.user_hash,
    u.user_type,
    NULL as user_group_id,
    'root_global_access' as user_group_name,
    NULL as project_group_id,
    'all_projects' as project_group_name,
    p.id as project_id,
    p.project_name,
    p.project_hash,
    p.project_created as access_granted_at,
    'root_access' as access_type
FROM users u
CROSS JOIN projects p
WHERE u.user_type = 'root'
  AND u.is_active = 1
  AND p.is_active = 1
  AND (p.archived = FALSE OR p.archived IS NULL);

-- ===================================================================================
-- USER PROJECT ACCESS SUMMARY VIEW
-- ===================================================================================
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

-- ===================================================================================
-- ACTIVE USER SESSIONS VIEW
-- ===================================================================================
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

-- ===================================================================================
-- USER SUMMARY VIEW
-- ===================================================================================
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

-- ===================================================================================
-- PROJECT HEALTH VIEW
-- ===================================================================================
CREATE OR REPLACE VIEW project_health_view AS
SELECT 
    p.id,
    p.project_hash,
    p.project_name,
    p.archived,
    p.owner_id,
    COUNT(DISTINCT vupa.user_id) as member_count,
    COUNT(DISTINCT pg.id) as project_groups_count,
    MAX(al.request_timestamp) as last_activity,
    CASE 
        WHEN COUNT(DISTINCT vupa.user_id) = 0 THEN 'inactive'
        WHEN COUNT(DISTINCT vupa.user_id) < 5 THEN 'low'
        WHEN COUNT(DISTINCT vupa.user_id) < 20 THEN 'medium'
        ELSE 'high'
    END as activity_level
FROM projects p
LEFT JOIN v_user_project_access vupa ON p.id = vupa.project_id
LEFT JOIN project_group_members pgm ON p.id = pgm.project_id AND pgm.is_active = 1
LEFT JOIN project_groups pg ON pgm.project_group_id = pg.id AND pg.is_active = 1
LEFT JOIN api_audit_log al ON p.id = al.project_id
WHERE p.is_active = 1
GROUP BY p.id;

-- ===================================================================================
-- USER GROUP HIERARCHY VIEW
-- Computes depth dynamically - root groups have parent_group_id IS NULL
-- ===================================================================================
CREATE OR REPLACE VIEW v_user_group_hierarchy AS
WITH RECURSIVE group_hierarchy AS (
    -- Root groups: parent_group_id IS NULL
    SELECT 
        id,
        group_hash,
        group_name,
        group_description,
        parent_group_id,
        CAST(group_name AS CHAR(1000)) as hierarchy_path,
        0 as depth,
        TRUE as is_root
    FROM user_groups 
    WHERE parent_group_id IS NULL AND is_active = TRUE
    
    UNION ALL
    
    -- Child groups
    SELECT 
        ug.id,
        ug.group_hash,
        ug.group_name,
        ug.group_description,
        ug.parent_group_id,
        CONCAT(gh.hierarchy_path, ' > ', ug.group_name),
        gh.depth + 1,
        FALSE
    FROM user_groups ug
    JOIN group_hierarchy gh ON ug.parent_group_id = gh.id
    WHERE ug.is_active = TRUE AND gh.depth < 10
)
SELECT id, group_hash, group_name, group_description, parent_group_id, 
       hierarchy_path, depth, is_root
FROM group_hierarchy;

-- ===================================================================================
-- PROJECT GROUP HIERARCHY VIEW
-- Computes depth dynamically - root groups have parent_group_id IS NULL
-- ===================================================================================
CREATE OR REPLACE VIEW v_project_group_hierarchy AS
WITH RECURSIVE group_hierarchy AS (
    -- Root groups: parent_group_id IS NULL
    SELECT 
        id,
        group_hash,
        group_name,
        group_description,
        parent_group_id,
        CAST(group_name AS CHAR(1000)) as hierarchy_path,
        0 as depth,
        TRUE as is_root
    FROM project_groups 
    WHERE parent_group_id IS NULL AND is_active = TRUE
    
    UNION ALL
    
    -- Child groups
    SELECT 
        pg.id,
        pg.group_hash,
        pg.group_name,
        pg.group_description,
        pg.parent_group_id,
        CONCAT(gh.hierarchy_path, ' > ', pg.group_name),
        gh.depth + 1,
        FALSE
    FROM project_groups pg
    JOIN group_hierarchy gh ON pg.parent_group_id = gh.id
    WHERE pg.is_active = TRUE AND gh.depth < 10
)
SELECT id, group_hash, group_name, group_description, parent_group_id,
       hierarchy_path, depth, is_root
FROM group_hierarchy;

-- ===================================================================================
-- USER ALL GROUPS VIEW (Including Ancestors for Permission Inheritance)
-- NOTE: Recursive hierarchy can be expensive - use with caution on large datasets
-- ===================================================================================
CREATE OR REPLACE VIEW v_user_all_groups AS
WITH RECURSIVE group_tree AS (
    -- Direct membership
    SELECT ugm.user_id, ugm.user_group_id, ug.group_name, ug.group_hash, 
           0 as depth, 'direct' as membership_type
    FROM user_group_members ugm
    JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = TRUE
    WHERE ugm.is_active = TRUE
    
    UNION ALL
    
    -- Ancestor groups (inherited membership) - walk UP the tree
    SELECT gt.user_id, parent_ug.id, parent_ug.group_name, parent_ug.group_hash,
           gt.depth + 1, 'inherited'
    FROM group_tree gt
    JOIN user_groups ug ON gt.user_group_id = ug.id
    JOIN user_groups parent_ug ON ug.parent_group_id = parent_ug.id AND parent_ug.is_active = TRUE
    WHERE ug.parent_group_id IS NOT NULL AND gt.depth < 10
)
SELECT DISTINCT user_id, user_group_id, group_name, group_hash, membership_type, 
       MIN(depth) as inheritance_depth
FROM group_tree
GROUP BY user_id, user_group_id, group_name, group_hash, membership_type;

-- ===================================================================================
-- PROJECT GROUP SUMMARY VIEW
-- ===================================================================================
CREATE OR REPLACE VIEW v_project_group_summary AS
SELECT 
    pg.id as project_group_id,
    pg.group_hash,
    pg.group_name,
    pg.group_description,
    pg.is_active,
    COUNT(DISTINCT pgm.project_id) as project_count,
    COUNT(DISTINCT ugpg.user_group_id) as user_group_count,
    COUNT(DISTINCT ugm.user_id) as total_users_with_access
FROM project_groups pg
LEFT JOIN project_group_members pgm ON pg.id = pgm.project_group_id AND pgm.is_active = 1
LEFT JOIN user_group_project_groups ugpg ON pg.id = ugpg.project_group_id AND ugpg.is_active = 1
LEFT JOIN user_group_members ugm ON ugpg.user_group_id = ugm.user_group_id AND ugm.is_active = 1
WHERE pg.is_active = 1
GROUP BY pg.id, pg.group_hash, pg.group_name, pg.group_description, pg.is_active;

-- ===================================================================================
-- USER SCOPED PERMISSIONS VIEW (with grant/deny support)
-- ===================================================================================
CREATE OR REPLACE VIEW v_user_scoped_permissions AS
-- Global permissions (via role)
SELECT 
    u.id as user_id,
    u.username,
    gp.permission_name,
    gp.permission_display_name,
    'global' as scope_type,
    NULL as project_group_id,
    NULL as project_group_name,
    r.role_name as permission_source,
    'grant' as permission_type,
    100 as priority
FROM users u
JOIN roles r ON u.role_id = r.id AND r.is_active = TRUE
JOIN role_permission_groups rpg ON r.id = rpg.role_id AND rpg.is_active = TRUE
JOIN global_permission_group_permissions pgp ON rpg.permission_group_id = pgp.permission_group_id AND pgp.is_active = TRUE
JOIN global_permissions gp ON pgp.permission_id = gp.id AND gp.is_active = TRUE
WHERE u.is_active = TRUE

UNION

-- User Group global permissions
SELECT 
    u.id as user_id,
    u.username,
    gp.permission_name,
    gp.permission_display_name,
    'user_group_global' as scope_type,
    NULL as project_group_id,
    NULL as project_group_name,
    CONCAT('user_group:', ug.group_name) as permission_source,
    'grant' as permission_type,
    50 as priority
FROM users u
JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = TRUE
JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = TRUE
JOIN user_group_permission_groups ugpg ON ug.id = ugpg.user_group_id AND ugpg.is_active = TRUE
JOIN global_permission_group_permissions pgp ON ugpg.permission_group_id = pgp.permission_group_id AND pgp.is_active = TRUE
JOIN global_permissions gp ON pgp.permission_id = gp.id AND gp.is_active = TRUE
WHERE u.is_active = TRUE

UNION

-- Scoped permissions (per project group) with grant/deny and priority
SELECT 
    u.id as user_id,
    u.username,
    gp.permission_name,
    gp.permission_display_name,
    'project_group_scoped' as scope_type,
    pg.id as project_group_id,
    pg.group_name as project_group_name,
    CONCAT('user_group:', ug.group_name, ' -> project_group:', pg.group_name) as permission_source,
    ugpgp.permission_type as permission_type,
    ugpgp.priority as priority
FROM users u
JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = TRUE
JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = TRUE
JOIN user_group_project_group_permissions ugpgp ON ug.id = ugpgp.user_group_id AND ugpgp.is_active = TRUE
JOIN project_groups pg ON ugpgp.project_group_id = pg.id AND pg.is_active = TRUE
JOIN global_permission_group_permissions pgp ON ugpgp.permission_group_id = pgp.permission_group_id AND pgp.is_active = TRUE
JOIN global_permissions gp ON pgp.permission_id = gp.id AND gp.is_active = TRUE
WHERE u.is_active = TRUE;

-- ===================================================================================
-- USER PROJECT SCOPED ROLES VIEW
-- ===================================================================================
CREATE OR REPLACE VIEW v_user_project_scoped_roles AS
SELECT 
    u.id as user_id,
    u.username,
    u.user_type,
    ug.id as user_group_id,
    ug.group_name as user_group_name,
    pg.id as project_group_id,
    pg.group_name as project_group_name,
    r.id as role_id,
    r.role_name,
    r.role_display_name,
    r.role_priority,
    ugpgr.assigned_at,
    'scoped' as role_scope
FROM users u
JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = TRUE
JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = TRUE
JOIN user_group_project_group_roles ugpgr ON ug.id = ugpgr.user_group_id AND ugpgr.is_active = TRUE
JOIN project_groups pg ON ugpgr.project_group_id = pg.id AND pg.is_active = TRUE
JOIN roles r ON ugpgr.role_id = r.id AND r.is_active = TRUE
WHERE u.is_active = TRUE

UNION

-- Global role from user's direct role assignment
SELECT 
    u.id as user_id,
    u.username,
    u.user_type,
    NULL as user_group_id,
    'global_role' as user_group_name,
    NULL as project_group_id,
    'all_projects' as project_group_name,
    r.id as role_id,
    r.role_name,
    r.role_display_name,
    r.role_priority,
    u.created_at as assigned_at,
    'global' as role_scope
FROM users u
JOIN roles r ON u.role_id = r.id AND r.is_active = TRUE
WHERE u.is_active = TRUE;

-- ===================================================================================
-- ACCESS CHAIN VIEW (Full path visualization)
-- ===================================================================================
CREATE OR REPLACE VIEW v_access_chain AS
SELECT 
    u.id as user_id,
    u.username,
    u.user_type,
    ug.id as user_group_id,
    ug.group_name as user_group_name,
    CASE WHEN ug.parent_group_id IS NULL THEN TRUE ELSE FALSE END as is_root_group,
    pg.id as project_group_id,
    pg.group_name as project_group_name,
    p.id as project_id,
    p.project_name,
    CONCAT(u.username, ' -> ', ug.group_name, ' -> ', pg.group_name, ' -> ', p.project_name) as access_path
FROM users u
JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = TRUE
JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = TRUE
JOIN user_group_project_groups ugpg ON ug.id = ugpg.user_group_id AND ugpg.is_active = TRUE
JOIN project_groups pg ON ugpg.project_group_id = pg.id AND pg.is_active = TRUE
JOIN project_group_members pgm ON pg.id = pgm.project_group_id AND pgm.is_active = TRUE
JOIN projects p ON pgm.project_id = p.id AND p.is_active = TRUE
WHERE u.is_active = TRUE;

-- ===================================================================================
-- API KEY AUDIT VIEW
-- Joins user_project_api_keys with users and projects for audit queries
-- Excludes secret_hash for security
-- ===================================================================================
CREATE OR REPLACE VIEW v_api_key_audit AS
SELECT
    apk.id,
    apk.public_id,
    apk.project_id,
    p.project_name,
    p.project_hash,
    apk.owner_user_id,
    u.username as owner_username,
    u.user_hash as owner_user_hash,
    u.user_type as owner_user_type,
    u.is_active as owner_is_active,
    apk.created_by,
    cb.username as created_by_username,
    cb.user_hash as created_by_user_hash,
    apk.name,
    apk.description,
    apk.hash_algorithm,
    apk.fingerprint,
    apk.secret_last4,
    apk.is_active,
    apk.expires_at,
    apk.last_used_at,
    apk.revoked_at,
    apk.revoked_by,
    rb.username as revoked_by_username,
    rb.user_hash as revoked_by_user_hash,
    apk.revoke_reason,
    apk.created_at,
    apk.updated_at,
    CASE
        WHEN apk.is_active = FALSE AND apk.revoked_at IS NOT NULL THEN 'revoked'
        WHEN apk.is_active = FALSE AND apk.expires_at IS NOT NULL AND apk.expires_at < NOW() THEN 'expired'
        WHEN apk.is_active = TRUE AND apk.expires_at IS NOT NULL AND apk.expires_at < NOW() THEN 'expired_but_active'
        WHEN apk.is_active = TRUE THEN 'active'
        ELSE 'inactive'
    END as effective_status
FROM user_project_api_keys apk
JOIN projects p ON apk.project_id = p.id
JOIN users u ON apk.owner_user_id = u.id
LEFT JOIN users cb ON apk.created_by = cb.id
LEFT JOIN users rb ON apk.revoked_by = rb.id;

-- ===================================================================================
-- VIEWS CREATED SUCCESSFULLY
-- ===================================================================================
SELECT 'All views created successfully!' as status,
       'Groups of Groups architecture views applied' as details;
