-- ===================================================================================
-- Enhanced 3-Tier User Type Multi-Project Authentication Database Schema
-- Initial Data Script (Restructured for Group-Based Access)
-- ===================================================================================
-- This script populates initial data required for the authentication system
-- MySQL Database
-- ===================================================================================

USE magic_auth;

-- =================== CREATE ROOT USER ===================
-- Create the first root user (password: admin123)
-- Password hash for 'admin123': 1be6588ad163643cae7ba7bbc6492c9fd035e01f1a1a9ed46e90f8c8ab3494c1
SET @root_user_id = 'usr-550e8400-e29b-41d4-a716-446655440000';
SET @root_user_hash = 'usr-0a0ca5a2-a7c9-11f0-ab33-22316c040a38';
INSERT INTO users (id, user_hash, username, email, password_hash, user_type, created_at, is_active)
VALUES (@root_user_id, @root_user_hash, 'root', 'root@system.local', 
        '1be6588ad163643cae7ba7bbc6492c9fd035e01f1a1a9ed46e90f8c8ab3494c1',
        'root', NOW(), TRUE);

SELECT 'Root user created successfully!' as status, 
       'Username: root, Password: admin123' as credentials;

-- =================== INITIALIZE ACTIVITY CATALOG ===================
-- Create activity type catalog entries
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active)
VALUES 
    -- User Authentication Activities
    ('act-cat-001', 'user_login', 'User Login', 'User successfully logged into the system', 'authentication', 'info', TRUE, TRUE),
    ('act-cat-002', 'user_logout', 'User Logout', 'User logged out of the system', 'authentication', 'info', TRUE, TRUE),
    ('act-cat-003', 'user_login_failed', 'Login Failed', 'Failed login attempt', 'authentication', 'warning', TRUE, TRUE),
    ('act-cat-004', 'user_password_reset', 'Password Reset', 'User password was reset', 'authentication', 'warning', TRUE, TRUE),
    
    -- User Management Activities
    ('act-cat-005', 'user_registration', 'User Registration', 'New user account created', 'user_management', 'info', TRUE, TRUE),
    ('act-cat-006', 'user_update', 'User Update', 'User account information updated', 'user_management', 'info', TRUE, TRUE),
    ('act-cat-007', 'user_status_change', 'User Status Change', 'User account status changed (activated/deactivated)', 'user_management', 'warning', TRUE, TRUE),
    ('act-cat-008', 'user_type_changed', 'User Type Changed', 'User type modified (root/admin/consumer)', 'user_management', 'critical', TRUE, TRUE),
    ('act-cat-009', 'user_deleted', 'User Deleted', 'User account deleted', 'user_management', 'critical', TRUE, TRUE),
    
    -- Project Management Activities
    ('act-cat-010', 'project_creation', 'Project Created', 'New project created', 'project_management', 'info', TRUE, TRUE),
    ('act-cat-011', 'project_update', 'Project Updated', 'Project information updated', 'project_management', 'info', TRUE, TRUE),
    ('act-cat-012', 'project_delete', 'Project Deleted', 'Project deleted', 'project_management', 'critical', TRUE, TRUE),
    ('act-cat-013', 'project_archived', 'Project Archived', 'Project archived', 'project_management', 'warning', TRUE, TRUE),
    ('act-cat-014', 'project_unarchived', 'Project Unarchived', 'Project unarchived', 'project_management', 'info', TRUE, TRUE),
    ('act-cat-015', 'project_ownership_transferred', 'Project Ownership Transferred', 'Project ownership transferred to another user', 'project_management', 'critical', TRUE, TRUE),
    
    -- Project Member Activities
    ('act-cat-016', 'project_member_add', 'Project Member Added', 'User added to project', 'project_members', 'info', TRUE, TRUE),
    ('act-cat-017', 'project_member_remove', 'Project Member Removed', 'User removed from project', 'project_members', 'warning', TRUE, TRUE),
    ('act-cat-018', 'project_member_removed', 'Project Member Was Removed', 'User was removed from project', 'project_members', 'warning', TRUE, TRUE),
    
    -- Group Management Activities
    ('act-cat-019', 'group_creation', 'Group Created', 'New user group created', 'group_management', 'info', TRUE, TRUE),
    ('act-cat-020', 'group_update', 'Group Updated', 'User group information updated', 'group_management', 'info', TRUE, TRUE),
    ('act-cat-021', 'group_delete', 'Group Deleted', 'User group deleted', 'group_management', 'critical', TRUE, TRUE),
    ('act-cat-022', 'user_group_assign', 'User Assigned to Group', 'User assigned to a group', 'group_management', 'info', TRUE, TRUE),
    ('act-cat-023', 'user_group_remove', 'User Removed from Group', 'User removed from a group', 'group_management', 'warning', TRUE, TRUE),
    
    -- Permission Management Activities
    ('act-cat-024', 'permission_grant', 'Permission Granted', 'Permission granted to user or group', 'permission_management', 'warning', TRUE, TRUE),
    ('act-cat-025', 'permission_revoke', 'Permission Revoked', 'Permission revoked from user or group', 'permission_management', 'warning', TRUE, TRUE),
    ('act-cat-026', 'role_assigned', 'Role Assigned', 'Role assigned to user or group', 'permission_management', 'info', TRUE, TRUE),
    ('act-cat-027', 'role_removed', 'Role Removed', 'Role removed from user or group', 'permission_management', 'warning', TRUE, TRUE),
    
    -- Bulk Operations
    ('act-cat-028', 'bulk_role_assignment', 'Bulk Role Assignment', 'Roles assigned to multiple users', 'bulk_operations', 'warning', TRUE, TRUE),
    ('act-cat-029', 'bulk_group_assignment', 'Bulk Group Assignment', 'Groups assigned to multiple users', 'bulk_operations', 'warning', TRUE, TRUE),
    ('act-cat-030', 'bulk_user_update', 'Bulk User Update', 'Multiple users updated', 'bulk_operations', 'warning', TRUE, TRUE),
    ('act-cat-031', 'bulk_user_delete', 'Bulk User Delete', 'Multiple users deleted', 'bulk_operations', 'critical', TRUE, TRUE),
    
    -- Administrative Actions
    ('act-cat-032', 'admin_action', 'Administrative Action', 'General administrative action performed', 'admin', 'warning', TRUE, TRUE),
    ('act-cat-033', 'system_event', 'System Event', 'System-level event occurred', 'system', 'info', TRUE, TRUE),
    ('act-cat-034', 'system_config_change', 'System Configuration Changed', 'System configuration modified', 'system', 'critical', TRUE, TRUE),
    
    -- API and Integration Activities
    ('act-cat-035', 'api_access', 'API Access', 'API endpoint accessed', 'api', 'info', FALSE, TRUE),
    ('act-cat-036', 'api_error', 'API Error', 'API error occurred', 'api', 'warning', TRUE, TRUE),
    ('act-cat-037', 'integration_sync', 'Integration Sync', 'External integration synchronized', 'integration', 'info', FALSE, TRUE),
    
    -- Security Activities
    ('act-cat-038', 'security_alert', 'Security Alert', 'Security-related alert triggered', 'security', 'critical', TRUE, TRUE),
    ('act-cat-039', 'suspicious_activity', 'Suspicious Activity', 'Suspicious activity detected', 'security', 'critical', TRUE, TRUE),
    ('act-cat-040', 'session_expired', 'Session Expired', 'User session expired', 'security', 'info', FALSE, TRUE);

SELECT 'Activity catalog initialized successfully!' as status,
       '40 activity types created' as details;

-- =================== INITIALIZATION COMPLETE ===================
SELECT 'Database initialization complete!' as status,
       'Root user and activity catalog created' as details;

