-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Initial Data Script
-- MySQL Database

USE magic_auth;

-- =================== CREATE ROOT USER ===================
-- Create the first root user (password: admin123)
-- Password hash for 'admin123': 240BE518FABD2724DDB6F04EEB1DA5967448D7E831C08C8FA822809F74C720A9
INSERT INTO users (user_hash, username, email, password_hash, user_type, created_at)
VALUES (CONCAT('usr-', UUID()), 'root', 'root@system.local', 
        '240BE518FABD2724DDB6F04EEB1DA5967448D7E831C08C8FA822809F74C720A9', 
        'root', NOW());

SET @root_user_id = LAST_INSERT_ID();

-- =================== CREATE DEFAULT PROJECT ===================
INSERT INTO projects (project_hash, project_name, project_description, created_by, project_created)
VALUES ('DEFAULTPROJECT', 'Default Project', 'Initial default project for the system', @root_user_id, NOW());

SET @default_project_id = LAST_INSERT_ID();

-- =================== CREATE DEFAULT USER GROUPS (Legacy) ===================
-- These are project-specific groups for backward compatibility
INSERT INTO user_groups (group_hash, group_name, group_description, project_id, permissions, created_at)
VALUES 
    (CONCAT('GRP-', UUID()), 'admin', 'Project administrators', @default_project_id, 
     '["admin", "read", "write", "delete", "manage_users"]', NOW()),
    (CONCAT('GRP-', UUID()), 'user', 'Regular users', @default_project_id, 
     '["read", "write"]', NOW()),
    (CONCAT('GRP-', UUID()), 'readonly', 'Read-only users', @default_project_id, 
     '["read"]', NOW());

-- =================== CREATE DEFAULT PROJECT GROUPS ===================
INSERT INTO project_groups (group_hash, group_name, group_description, permissions, created_at)
VALUES 
    (CONCAT('PG-', UUID()), 'full-access', 'Full access to project resources', 
     '["admin", "read", "write", "delete", "manage_users", "manage_groups", "export_data"]', NOW()),
    (CONCAT('PG-', UUID()), 'read-write', 'Read and write access to project resources', 
     '["read", "write", "create"]', NOW()),
    (CONCAT('PG-', UUID()), 'read-only', 'Read-only access to project resources', 
     '["read", "view"]', NOW());

-- Link default project to project groups
INSERT INTO project_group_members (project_id, project_group_id, assigned_at, assigned_by)
SELECT @default_project_id, id, NOW(), @root_user_id
FROM project_groups;

-- =================== CREATE DEFAULT PERMISSIONS ===================
INSERT INTO permissions (permission_hash, project_id, permission_name, permission_display_name, 
                        permission_description, permission_category, is_system_permission, created_by)
VALUES 
    -- General permissions
    (CONCAT('PERM-', UUID()), @default_project_id, 'read', 'Read Access', 
     'Can view content and data', 'general', TRUE, @root_user_id),
    (CONCAT('PERM-', UUID()), @default_project_id, 'write', 'Write Access', 
     'Can create and modify content', 'general', TRUE, @root_user_id),
    (CONCAT('PERM-', UUID()), @default_project_id, 'delete', 'Delete Access', 
     'Can delete content and data', 'general', TRUE, @root_user_id),
    (CONCAT('PERM-', UUID()), @default_project_id, 'create', 'Create Access', 
     'Can create new items', 'general', TRUE, @root_user_id),
    (CONCAT('PERM-', UUID()), @default_project_id, 'update', 'Update Access', 
     'Can modify existing items', 'general', TRUE, @root_user_id),
    
    -- Admin permissions
    (CONCAT('PERM-', UUID()), @default_project_id, 'admin', 'Administrator', 
     'Full administrative access', 'admin', TRUE, @root_user_id),
    (CONCAT('PERM-', UUID()), @default_project_id, 'manage_users', 'Manage Users', 
     'Can manage user accounts and roles', 'admin', TRUE, @root_user_id),
    (CONCAT('PERM-', UUID()), @default_project_id, 'manage_roles', 'Manage Roles', 
     'Can create and modify roles and permissions', 'admin', TRUE, @root_user_id),
    (CONCAT('PERM-', UUID()), @default_project_id, 'view_audit', 'View Audit Log', 
     'Can view audit trail and logs', 'admin', TRUE, @root_user_id),
    
    -- Data permissions
    (CONCAT('PERM-', UUID()), @default_project_id, 'export_data', 'Export Data', 
     'Can export data from the system', 'data', TRUE, @root_user_id),
    (CONCAT('PERM-', UUID()), @default_project_id, 'import_data', 'Import Data', 
     'Can import data into the system', 'data', TRUE, @root_user_id),
    
    -- API permissions
    (CONCAT('PERM-', UUID()), @default_project_id, 'api_access', 'API Access', 
     'Can access API endpoints', 'api', TRUE, @root_user_id),
    (CONCAT('PERM-', UUID()), @default_project_id, 'full_access', 'Full Access', 
     'Complete access to all features', 'admin', TRUE, @root_user_id);

-- =================== CREATE DEFAULT PERMISSION GROUPS (ROLES) ===================
INSERT INTO permission_groups (group_hash, project_id, group_name, group_display_name, 
                              group_description, group_priority, is_system_role, created_by)
VALUES 
    (CONCAT('ROLE-', UUID()), @default_project_id, 'admin', 'Administrator', 
     'Full administrative access to all features', 100, TRUE, @root_user_id),
    (CONCAT('ROLE-', UUID()), @default_project_id, 'manager', 'Manager', 
     'Management access with user and role management', 80, TRUE, @root_user_id),
    (CONCAT('ROLE-', UUID()), @default_project_id, 'editor', 'Editor', 
     'Content editing and management access', 60, TRUE, @root_user_id),
    (CONCAT('ROLE-', UUID()), @default_project_id, 'contributor', 'Contributor', 
     'Can create and edit own content', 40, TRUE, @root_user_id),
    (CONCAT('ROLE-', UUID()), @default_project_id, 'viewer', 'Viewer', 
     'Read-only access to content', 20, TRUE, @root_user_id),
    (CONCAT('ROLE-', UUID()), @default_project_id, 'api_user', 'API User', 
     'API access for integrations', 30, TRUE, @root_user_id);

-- =================== ASSIGN PERMISSIONS TO ROLES ===================
-- Admin role gets all permissions
INSERT INTO permission_group_permissions (permission_group_id, permission_id, granted_by)
SELECT pg.id, p.id, @root_user_id
FROM permission_groups pg, permissions p
WHERE pg.group_name = 'admin' AND p.project_id = @default_project_id;

-- Manager role permissions
INSERT INTO permission_group_permissions (permission_group_id, permission_id, granted_by)
SELECT pg.id, p.id, @root_user_id
FROM permission_groups pg, permissions p
WHERE pg.group_name = 'manager' 
  AND p.project_id = @default_project_id
  AND p.permission_name IN ('read', 'write', 'create', 'update', 'manage_users', 'view_audit', 'export_data', 'api_access');

-- Editor role permissions
INSERT INTO permission_group_permissions (permission_group_id, permission_id, granted_by)
SELECT pg.id, p.id, @root_user_id
FROM permission_groups pg, permissions p
WHERE pg.group_name = 'editor' 
  AND p.project_id = @default_project_id
  AND p.permission_name IN ('read', 'write', 'create', 'update', 'api_access');

-- Contributor role permissions
INSERT INTO permission_group_permissions (permission_group_id, permission_id, granted_by)
SELECT pg.id, p.id, @root_user_id
FROM permission_groups pg, permissions p
WHERE pg.group_name = 'contributor' 
  AND p.project_id = @default_project_id
  AND p.permission_name IN ('read', 'create', 'update');

-- Viewer role permissions
INSERT INTO permission_group_permissions (permission_group_id, permission_id, granted_by)
SELECT pg.id, p.id, @root_user_id
FROM permission_groups pg, permissions p
WHERE pg.group_name = 'viewer' 
  AND p.project_id = @default_project_id
  AND p.permission_name IN ('read');

-- API User role permissions
INSERT INTO permission_group_permissions (permission_group_id, permission_id, granted_by)
SELECT pg.id, p.id, @root_user_id
FROM permission_groups pg, permissions p
WHERE pg.group_name = 'api_user' 
  AND p.project_id = @default_project_id
  AND p.permission_name IN ('api_access', 'read');

-- =================== CREATE SAMPLE ADMIN USER ===================
-- Create a sample admin user (password: admin123)
INSERT INTO users (user_hash, username, email, password_hash, user_type, assigned_project_id, created_by, created_at)
VALUES (CONCAT('usr-', UUID()), 'admin', 'admin@example.com', 
        '240BE518FABD2724DDB6F04EEB1DA5967448D7E831C08C8FA822809F74C720A9', 
        'admin', @default_project_id, @root_user_id, NOW());

SET @admin_user_id = LAST_INSERT_ID();

-- Add admin to admin_project_assignments for multi-project support
INSERT INTO admin_project_assignments (user_id, project_id, assigned_at, assigned_by)
VALUES (@admin_user_id, @default_project_id, NOW(), @root_user_id);

-- =================== CREATE SAMPLE CONSUMER USER ===================
-- Create a sample consumer user (password: user123)
-- Password hash for 'user123': 0B14D501A594442A01C6859541BCB3E8164D183D32937B851835442F69D5C94E
INSERT INTO users (user_hash, username, email, password_hash, user_type, created_by, created_at)
VALUES (CONCAT('usr-', UUID()), 'user', 'user@example.com', 
        '0B14D501A594442A01C6859541BCB3E8164D183D32937B851835442F69D5C94E', 
        'consumer', @root_user_id, NOW());

SET @consumer_user_id = LAST_INSERT_ID();

-- Grant consumer user access to default project
INSERT INTO user_projects (user_id, project_id, user_project_hash, granted_by)
VALUES (@consumer_user_id, @default_project_id, 
        CONCAT('uprj-', UUID()), @root_user_id);

SET @user_project_id = LAST_INSERT_ID();

-- Assign consumer user to the 'contributor' role in the default project
INSERT INTO user_project_permission_groups (user_id, project_id, permission_group_id, assigned_by)
SELECT @consumer_user_id, @default_project_id, id, @root_user_id
FROM permission_groups 
WHERE group_name = 'contributor' AND project_id = @default_project_id;

-- Output created users info
SELECT 'Created users:' as '';
SELECT 'Username: root, Password: admin123, Type: Root User' as 'User Info'
UNION ALL
SELECT 'Username: admin, Password: admin123, Type: Admin User (Default Project)'
UNION ALL
SELECT 'Username: user, Password: user123, Type: Consumer User (Contributor Role)'; 