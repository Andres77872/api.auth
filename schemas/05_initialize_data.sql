-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Initial Data Script (Restructured for Group-Based Access)
-- MySQL Database

USE magic_auth;

-- =================== CREATE ROOT USER ===================
-- Create the first root user (password: admin123)
-- Password hash for 'admin123': 1be6588ad163643cae7ba7bbc6492c9fd035e01f1a1a9ed46e90f8c8ab3494c1
SET @root_user_id = 'usr-550e8400-e29b-41d4-a716-446655440000';
INSERT INTO users (id, user_hash, username, email, password_hash, user_type, created_at, is_active)
VALUES (@root_user_id, CONCAT('usr-', UUID()), 'root', 'root@system.local', 
        '1be6588ad163643cae7ba7bbc6492c9fd035e01f1a1a9ed46e90f8c8ab3494c1',
        'root', NOW(), TRUE);

-- =================== CREATE DEFAULT PROJECT ===================
SET @default_project_id = 'proj-550e8400-e29b-41d4-a716-446655440001';
INSERT INTO projects (id, project_hash, project_name, project_description, created_by, project_created, is_active)
VALUES (@default_project_id, 'DEFAULTPROJECT', 'Default Project', 'Initial default project for the system', @root_user_id, NOW(), TRUE);

-- =================== CREATE DEFAULT USER GROUPS ===================
-- Global user groups that can span multiple projects
SET @admin_group_id = 'ug-550e8400-e29b-41d4-a716-446655440002';
SET @manager_group_id = 'ug-550e8400-e29b-41d4-a716-446655440003';
SET @developer_group_id = 'ug-550e8400-e29b-41d4-a716-446655440004';
SET @tester_group_id = 'ug-550e8400-e29b-41d4-a716-446655440005';
SET @viewer_group_id = 'ug-550e8400-e29b-41d4-a716-446655440006';

INSERT INTO user_groups (id, group_hash, group_name, group_description, parent_group_id, group_level, created_by, created_at, is_active)
VALUES 
    -- Root level groups
    (@admin_group_id, CONCAT('UG-', REPLACE(UUID(),'-','')), 'administrators', 'System administrators group', NULL, 0, @root_user_id, NOW(), TRUE),
    (@manager_group_id, CONCAT('UG-', REPLACE(UUID(),'-','')), 'project_managers', 'Project managers group', NULL, 0, @root_user_id, NOW(), TRUE),
    (@developer_group_id, CONCAT('UG-', REPLACE(UUID(),'-','')), 'developers', 'Developers group', NULL, 0, @root_user_id, NOW(), TRUE),
    (@tester_group_id, CONCAT('UG-', REPLACE(UUID(),'-','')), 'testers', 'Quality assurance testers group', NULL, 0, @root_user_id, NOW(), TRUE),
    (@viewer_group_id, CONCAT('UG-', REPLACE(UUID(),'-','')), 'viewers', 'Read-only viewers group', NULL, 0, @root_user_id, NOW(), TRUE);

-- Create hierarchical sub-groups
SET @senior_dev_group_id = 'ug-550e8400-e29b-41d4-a716-446655440007';
SET @junior_dev_group_id = 'ug-550e8400-e29b-41d4-a716-446655440008';
SET @auto_tester_group_id = 'ug-550e8400-e29b-41d4-a716-446655440009';
SET @manual_tester_group_id = 'ug-550e8400-e29b-41d4-a716-446655440010';

INSERT INTO user_groups (id, group_hash, group_name, group_description, parent_group_id, group_level, created_by, created_at, is_active)
VALUES 
    -- Sub-groups under developers
    (@senior_dev_group_id, CONCAT('UG-', REPLACE(UUID(),'-','')), 'senior_developers', 'Senior developers sub-group', @developer_group_id, 1, @root_user_id, NOW(), TRUE),
    (@junior_dev_group_id, CONCAT('UG-', REPLACE(UUID(),'-','')), 'junior_developers', 'Junior developers sub-group', @developer_group_id, 1, @root_user_id, NOW(), TRUE),
    
    -- Sub-groups under testers
    (@auto_tester_group_id, CONCAT('UG-', REPLACE(UUID(),'-','')), 'automation_testers', 'Automation testers sub-group', @tester_group_id, 1, @root_user_id, NOW(), TRUE),
    (@manual_tester_group_id, CONCAT('UG-', REPLACE(UUID(),'-','')), 'manual_testers', 'Manual testers sub-group', @tester_group_id, 1, @root_user_id, NOW(), TRUE);

-- =================== GRANT USER GROUPS ACCESS TO DEFAULT PROJECT ===================
-- Link user groups to the default project
INSERT INTO user_group_projects (id, user_group_id, project_id, granted_at, granted_by, is_active)
VALUES 
    (CONCAT('ugp-', REPLACE(UUID(),'-','')), @admin_group_id, @default_project_id, NOW(), @root_user_id, TRUE),
    (CONCAT('ugp-', REPLACE(UUID(),'-','')), @manager_group_id, @default_project_id, NOW(), @root_user_id, TRUE),
    (CONCAT('ugp-', REPLACE(UUID(),'-','')), @developer_group_id, @default_project_id, NOW(), @root_user_id, TRUE),
    (CONCAT('ugp-', REPLACE(UUID(),'-','')), @tester_group_id, @default_project_id, NOW(), @root_user_id, TRUE),
    (CONCAT('ugp-', REPLACE(UUID(),'-','')), @viewer_group_id, @default_project_id, NOW(), @root_user_id, TRUE);

-- =================== CREATE DEFAULT PERMISSIONS ===================
-- Set permission IDs for reference
SET @read_perm_id = 'perm-550e8400-e29b-41d4-a716-446655440011';
SET @write_perm_id = 'perm-550e8400-e29b-41d4-a716-446655440012';
SET @delete_perm_id = 'perm-550e8400-e29b-41d4-a716-446655440013';
SET @admin_perm_id = 'perm-550e8400-e29b-41d4-a716-446655440014';
SET @manage_users_perm_id = 'perm-550e8400-e29b-41d4-a716-446655440015';
SET @manage_roles_perm_id = 'perm-550e8400-e29b-41d4-a716-446655440016';
SET @export_data_perm_id = 'perm-550e8400-e29b-41d4-a716-446655440017';
SET @import_data_perm_id = 'perm-550e8400-e29b-41d4-a716-446655440018';
SET @api_access_perm_id = 'perm-550e8400-e29b-41d4-a716-446655440019';

INSERT INTO permissions (id, permission_hash, project_id, permission_name, permission_display_name, 
                        permission_description, permission_category, parent_permission_id, permission_level,
                        is_system_permission, created_by, created_at, is_active)
VALUES 
    -- Root level permissions - General category
    (@read_perm_id, CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'read', 'Read Access', 
     'Can view content and data', 'general', NULL, 0, TRUE, @root_user_id, NOW(), TRUE),
    (@write_perm_id, CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'write', 'Write Access', 
     'Can create and modify content', 'general', NULL, 0, TRUE, @root_user_id, NOW(), TRUE),
    (@delete_perm_id, CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'delete', 'Delete Access', 
     'Can delete content and data', 'general', NULL, 0, TRUE, @root_user_id, NOW(), TRUE),
    
    -- Root level permissions - Admin category
    (@admin_perm_id, CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'admin', 'Administrator', 
     'Full administrative access', 'admin', NULL, 0, TRUE, @root_user_id, NOW(), TRUE),
    (@manage_users_perm_id, CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'manage_users', 'Manage Users', 
     'Can manage user accounts and roles', 'admin', NULL, 0, TRUE, @root_user_id, NOW(), TRUE),
    (@manage_roles_perm_id, CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'manage_roles', 'Manage Roles', 
     'Can create and modify roles and permissions', 'admin', NULL, 0, TRUE, @root_user_id, NOW(), TRUE),
    
    -- Root level permissions - Data category
    (@export_data_perm_id, CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'export_data', 'Export Data', 
     'Can export data from the system', 'data', NULL, 0, TRUE, @root_user_id, NOW(), TRUE),
    (@import_data_perm_id, CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'import_data', 'Import Data', 
     'Can import data into the system', 'data', NULL, 0, TRUE, @root_user_id, NOW(), TRUE),
    
    -- Root level permissions - API category
    (@api_access_perm_id, CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'api_access', 'API Access', 
     'Can access API endpoints', 'api', NULL, 0, TRUE, @root_user_id, NOW(), TRUE);

-- Create hierarchical permissions
INSERT INTO permissions (id, permission_hash, project_id, permission_name, permission_display_name, 
                        permission_description, permission_category, parent_permission_id, permission_level,
                        is_system_permission, created_by, created_at, is_active)
VALUES 
    -- Sub-permissions under 'read'
    ('perm-550e8400-e29b-41d4-a716-446655440020', CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'read_projects', 'Read Projects', 
     'Can view project information', 'general', @read_perm_id, 1, TRUE, @root_user_id, NOW(), TRUE),
    ('perm-550e8400-e29b-41d4-a716-446655440021', CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'read_users', 'Read Users', 
     'Can view user information', 'general', @read_perm_id, 1, TRUE, @root_user_id, NOW(), TRUE),
    
    -- Sub-permissions under 'write'
    ('perm-550e8400-e29b-41d4-a716-446655440022', CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'create_content', 'Create Content', 
     'Can create new content', 'general', @write_perm_id, 1, TRUE, @root_user_id, NOW(), TRUE),
    ('perm-550e8400-e29b-41d4-a716-446655440023', CONCAT('PERM-', REPLACE(UUID(),'-','')), @default_project_id, 'update_content', 'Update Content', 
     'Can modify existing content', 'general', @write_perm_id, 1, TRUE, @root_user_id, NOW(), TRUE);

-- =================== CREATE DEFAULT PERMISSION GROUPS (ROLES) ===================
-- Get permission group IDs
SET @full_admin_role_id = 'pg-550e8400-e29b-41d4-a716-446655440024';
SET @project_admin_role_id = 'pg-550e8400-e29b-41d4-a716-446655440025';
SET @manager_role_id = 'pg-550e8400-e29b-41d4-a716-446655440026';
SET @developer_role_id = 'pg-550e8400-e29b-41d4-a716-446655440027';
SET @tester_role_id = 'pg-550e8400-e29b-41d4-a716-446655440028';
SET @viewer_role_id = 'pg-550e8400-e29b-41d4-a716-446655440029';
SET @api_user_role_id = 'pg-550e8400-e29b-41d4-a716-446655440030';

INSERT INTO permission_groups (id, group_hash, project_id, group_name, group_display_name, 
                              group_description, parent_permission_group_id, group_level, group_priority, 
                              is_system_role, created_by, created_at, is_active)
VALUES 
    -- Root level permission groups
    (@full_admin_role_id, CONCAT('ROLE-', REPLACE(UUID(),'-','')), @default_project_id, 'full_admin', 'Full Administrator', 
     'Complete administrative access to all features', NULL, 0, 100, TRUE, @root_user_id, NOW(), TRUE),
    (@project_admin_role_id, CONCAT('ROLE-', REPLACE(UUID(),'-','')), @default_project_id, 'project_admin', 'Project Administrator', 
     'Administrative access within project scope', NULL, 0, 90, TRUE, @root_user_id, NOW(), TRUE),
    (@manager_role_id, CONCAT('ROLE-', REPLACE(UUID(),'-','')), @default_project_id, 'manager', 'Manager', 
     'Management access with user oversight', NULL, 0, 80, TRUE, @root_user_id, NOW(), TRUE),
    (@developer_role_id, CONCAT('ROLE-', REPLACE(UUID(),'-','')), @default_project_id, 'developer', 'Developer', 
     'Development access with content management', NULL, 0, 60, TRUE, @root_user_id, NOW(), TRUE),
    (@tester_role_id, CONCAT('ROLE-', REPLACE(UUID(),'-','')), @default_project_id, 'tester', 'Tester', 
     'Testing access with limited content creation', NULL, 0, 40, TRUE, @root_user_id, NOW(), TRUE),
    (@viewer_role_id, CONCAT('ROLE-', REPLACE(UUID(),'-','')), @default_project_id, 'viewer', 'Viewer', 
     'Read-only access to content', NULL, 0, 20, TRUE, @root_user_id, NOW(), TRUE),
    (@api_user_role_id, CONCAT('ROLE-', REPLACE(UUID(),'-','')), @default_project_id, 'api_user', 'API User', 
     'API access for integrations', NULL, 0, 30, TRUE, @root_user_id, NOW(), TRUE);

-- Create hierarchical permission groups
INSERT INTO permission_groups (id, group_hash, project_id, group_name, group_display_name, 
                              group_description, parent_permission_group_id, group_level, group_priority, 
                              is_system_role, created_by, created_at, is_active)
VALUES 
    -- Sub-roles under developer
    ('pg-550e8400-e29b-41d4-a716-446655440031', CONCAT('ROLE-', REPLACE(UUID(),'-','')), @default_project_id, 'senior_developer', 'Senior Developer', 
     'Senior development access with additional privileges', @developer_role_id, 1, 65, TRUE, @root_user_id, NOW(), TRUE),
    ('pg-550e8400-e29b-41d4-a716-446655440032', CONCAT('ROLE-', REPLACE(UUID(),'-','')), @default_project_id, 'junior_developer', 'Junior Developer', 
     'Limited development access for junior staff', @developer_role_id, 1, 55, TRUE, @root_user_id, NOW(), TRUE);

-- =================== ASSIGN PERMISSIONS TO PERMISSION GROUPS ===================
-- Full Admin gets all permissions
INSERT INTO permission_group_permissions (id, permission_group_id, permission_id, granted_at, granted_by, is_active)
SELECT CONCAT('pgp-', REPLACE(UUID(),'-','')), @full_admin_role_id, p.id, NOW(), @root_user_id, TRUE
FROM permissions p
WHERE p.project_id = @default_project_id;

-- Project Admin gets most permissions except some admin functions
INSERT INTO permission_group_permissions (id, permission_group_id, permission_id, granted_at, granted_by, is_active)
SELECT CONCAT('pgp-', REPLACE(UUID(),'-','')), @project_admin_role_id, p.id, NOW(), @root_user_id, TRUE
FROM permissions p
WHERE p.project_id = @default_project_id
  AND p.permission_name IN ('read', 'write', 'delete', 'manage_users', 'export_data', 'import_data', 'api_access',
                            'read_projects', 'read_users', 'create_content', 'update_content');

-- Manager permissions
INSERT INTO permission_group_permissions (id, permission_group_id, permission_id, granted_at, granted_by, is_active)
SELECT CONCAT('pgp-', REPLACE(UUID(),'-','')), @manager_role_id, p.id, NOW(), @root_user_id, TRUE
FROM permissions p
WHERE p.project_id = @default_project_id
  AND p.permission_name IN ('read', 'write', 'manage_users', 'export_data', 'api_access',
                            'read_projects', 'read_users', 'create_content', 'update_content');

-- Developer permissions
INSERT INTO permission_group_permissions (id, permission_group_id, permission_id, granted_at, granted_by, is_active)
SELECT CONCAT('pgp-', REPLACE(UUID(),'-','')), @developer_role_id, p.id, NOW(), @root_user_id, TRUE
FROM permissions p
WHERE p.project_id = @default_project_id
  AND p.permission_name IN ('read', 'write', 'api_access', 'read_projects', 'create_content', 'update_content');

-- Tester permissions
INSERT INTO permission_group_permissions (id, permission_group_id, permission_id, granted_at, granted_by, is_active)
SELECT CONCAT('pgp-', REPLACE(UUID(),'-','')), @tester_role_id, p.id, NOW(), @root_user_id, TRUE
FROM permissions p
WHERE p.project_id = @default_project_id
  AND p.permission_name IN ('read', 'read_projects', 'read_users');

-- Viewer permissions
INSERT INTO permission_group_permissions (id, permission_group_id, permission_id, granted_at, granted_by, is_active)
SELECT CONCAT('pgp-', REPLACE(UUID(),'-','')), @viewer_role_id, p.id, NOW(), @root_user_id, TRUE
FROM permissions p
WHERE p.project_id = @default_project_id
  AND p.permission_name IN ('read', 'read_projects');

-- API User permissions
INSERT INTO permission_group_permissions (id, permission_group_id, permission_id, granted_at, granted_by, is_active)
SELECT CONCAT('pgp-', REPLACE(UUID(),'-','')), @api_user_role_id, p.id, NOW(), @root_user_id, TRUE
FROM permissions p
WHERE p.project_id = @default_project_id
  AND p.permission_name IN ('api_access', 'read');

-- =================== CREATE SAMPLE ADMIN USER ===================
-- Create a sample admin user (password: admin123)
-- Note: Admin users get project access through user groups, not direct assignment
SET @admin_user_id = 'usr-550e8400-e29b-41d4-a716-446655440033';
INSERT INTO users (id, user_hash, username, email, password_hash, user_type, created_by, created_at, is_active)
VALUES (@admin_user_id, CONCAT('usr-', UUID()), 'admin', 'admin@example.com', 
        '$argon2id$v=19$m=65536,t=3,p=4$hash_placeholder_for_admin123', 
        'admin', @root_user_id, NOW(), TRUE);

-- Add admin user to administrators user group
INSERT INTO user_group_members (id, user_id, user_group_id, assigned_at, assigned_by, is_active)
VALUES (CONCAT('ugm-', REPLACE(UUID(),'-','')), @admin_user_id, @admin_group_id, NOW(), @root_user_id, TRUE);

-- Link administrators user group to project_admin permission group
INSERT INTO user_group_permission_groups (id, user_group_id, project_id, permission_group_id, assigned_at, assigned_by, is_active)
VALUES (CONCAT('ugpg-', REPLACE(UUID(),'-','')), @admin_group_id, @default_project_id, @project_admin_role_id, NOW(), @root_user_id, TRUE);

-- =================== CREATE SAMPLE CONSUMER USER ===================
-- Create a sample consumer user (password: user123)
-- Password hash for 'user123': $argon2id$v=19$m=65536,t=3,p=4$hash_placeholder_for_user123
SET @consumer_user_id = 'usr-550e8400-e29b-41d4-a716-446655440034';
INSERT INTO users (id, user_hash, username, email, password_hash, user_type, created_by, created_at, is_active)
VALUES (@consumer_user_id, CONCAT('usr-', UUID()), 'user', 'user@example.com', 
        '$argon2id$v=19$m=65536,t=3,p=4$hash_placeholder_for_user123', 
        'consumer', @root_user_id, NOW(), TRUE);

-- Add consumer user to developers user group
INSERT INTO user_group_members (id, user_id, user_group_id, assigned_at, assigned_by, is_active)
VALUES (CONCAT('ugm-', REPLACE(UUID(),'-','')), @consumer_user_id, @developer_group_id, NOW(), @root_user_id, TRUE);

-- Link developers user group to developer permission group
INSERT INTO user_group_permission_groups (id, user_group_id, project_id, permission_group_id, assigned_at, assigned_by, is_active)
VALUES (CONCAT('ugpg-', REPLACE(UUID(),'-','')), @developer_group_id, @default_project_id, @developer_role_id, NOW(), @root_user_id, TRUE);

-- =================== CREATE ADDITIONAL SAMPLE USERS ===================
-- Create a sample manager user
SET @manager_user_id = 'usr-550e8400-e29b-41d4-a716-446655440035';
INSERT INTO users (id, user_hash, username, email, password_hash, user_type, created_by, created_at, is_active)
VALUES (@manager_user_id, CONCAT('usr-', UUID()), 'manager', 'manager@example.com', 
        '$argon2id$v=19$m=65536,t=3,p=4$hash_placeholder_for_manager123', 
        'consumer', @root_user_id, NOW(), TRUE);

-- Add manager to project_managers user group
INSERT INTO user_group_members (id, user_id, user_group_id, assigned_at, assigned_by, is_active)
VALUES (CONCAT('ugm-', REPLACE(UUID(),'-','')), @manager_user_id, @manager_group_id, NOW(), @root_user_id, TRUE);

-- Link project_managers user group to manager permission group
INSERT INTO user_group_permission_groups (id, user_group_id, project_id, permission_group_id, assigned_at, assigned_by, is_active)
VALUES (CONCAT('ugpg-', REPLACE(UUID(),'-','')), @manager_group_id, @default_project_id, @manager_role_id, NOW(), @root_user_id, TRUE);

-- Create a sample tester user
SET @tester_user_id = 'usr-550e8400-e29b-41d4-a716-446655440036';
INSERT INTO users (id, user_hash, username, email, password_hash, user_type, created_by, created_at, is_active)
VALUES (@tester_user_id, CONCAT('usr-', UUID()), 'tester', 'tester@example.com', 
        '$argon2id$v=19$m=65536,t=3,p=4$hash_placeholder_for_tester123', 
        'consumer', @root_user_id, NOW(), TRUE);

-- Add tester to testers user group
INSERT INTO user_group_members (id, user_id, user_group_id, assigned_at, assigned_by, is_active)
VALUES (CONCAT('ugm-', REPLACE(UUID(),'-','')), @tester_user_id, @tester_group_id, NOW(), @root_user_id, TRUE);

-- Link testers user group to tester permission group
INSERT INTO user_group_permission_groups (id, user_group_id, project_id, permission_group_id, assigned_at, assigned_by, is_active)
VALUES (CONCAT('ugpg-', REPLACE(UUID(),'-','')), @tester_group_id, @default_project_id, @tester_role_id, NOW(), @root_user_id, TRUE);

-- =================== LINK ADDITIONAL USER GROUPS TO PERMISSION GROUPS ===================
-- Link viewers user group to viewer permission group
INSERT INTO user_group_permission_groups (id, user_group_id, project_id, permission_group_id, assigned_at, assigned_by, is_active)
VALUES (CONCAT('ugpg-', REPLACE(UUID(),'-','')), @viewer_group_id, @default_project_id, @viewer_role_id, NOW(), @root_user_id, TRUE);

-- =================== CREATE AUDIT LOG ENTRIES ===================
-- Log the initial setup actions
INSERT INTO permission_audit_log (id, action_type, project_id, performed_by, new_values, action_timestamp)
VALUES 
    (CONCAT('audit-', REPLACE(UUID(),'-','')), 'INITIAL_SETUP', @default_project_id, @root_user_id, 
     JSON_OBJECT('action', 'database_initialization', 'project_name', 'Default Project'), NOW()),
    (CONCAT('audit-', REPLACE(UUID(),'-','')), 'CREATE_USER_GROUPS', @default_project_id, @root_user_id, 
     JSON_OBJECT('groups_created', 5, 'hierarchical_groups', 4), NOW()),
    (CONCAT('audit-', REPLACE(UUID(),'-','')), 'CREATE_PERMISSION_GROUPS', @default_project_id, @root_user_id, 
     JSON_OBJECT('roles_created', 7, 'hierarchical_roles', 2), NOW()),
    (CONCAT('audit-', REPLACE(UUID(),'-','')), 'ASSIGN_INITIAL_PERMISSIONS', @default_project_id, @root_user_id, 
     JSON_OBJECT('permission_assignments', 'completed'), NOW());

-- Output setup summary
SELECT 'Database initialization completed successfully!' as '';
SELECT CONCAT('Created ', COUNT(*), ' users') as 'User Summary' FROM users WHERE is_active = TRUE
UNION ALL
SELECT CONCAT('Created ', COUNT(*), ' user groups') FROM user_groups WHERE is_active = TRUE
UNION ALL
SELECT CONCAT('Created ', COUNT(*), ' permission groups') FROM permission_groups WHERE project_id = @default_project_id AND is_active = TRUE
UNION ALL
SELECT CONCAT('Created ', COUNT(*), ' permissions') FROM permissions WHERE project_id = @default_project_id AND is_active = TRUE;

-- Output user login information
SELECT 'User Login Information:' as '';
SELECT 'Username: root, Password: admin123, Type: Root User (Global Access)' as 'Login Info'
UNION ALL
SELECT 'Username: admin, Password: admin123, Type: Admin User (Project Administrator via administrators group)'
UNION ALL
SELECT 'Username: manager, Password: manager123, Type: Consumer User (Manager via project_managers group)'
UNION ALL
SELECT 'Username: user, Password: user123, Type: Consumer User (Developer via developers group)'
UNION ALL
SELECT 'Username: tester, Password: tester123, Type: Consumer User (Tester via testers group)';

-- Output group structure
SELECT 'User Group Structure:' as '';
SELECT 
    CONCAT(
        'Group: ', ug.group_name, 
        ' (Level ', ug.group_level, ')',
        CASE WHEN ug.parent_group_id IS NOT NULL 
             THEN CONCAT(' -> Parent: ', pug.group_name)
             ELSE ' (Root Level)'
        END
    ) as 'Group Hierarchy'
FROM user_groups ug
LEFT JOIN user_groups pug ON ug.parent_group_id = pug.id
WHERE ug.is_active = TRUE
ORDER BY ug.group_level, ug.group_name; 