-- ===================================================================================
-- Activity Logging and Audit System Tables
-- ===================================================================================
-- Tables for comprehensive activity logging and audit trail
-- MySQL Database
-- ===================================================================================

USE magic_auth;

-- =================== ACTIVITY CATALOG TABLE ===================
-- Defines all possible activity types in the system
CREATE TABLE IF NOT EXISTS activity_catalog (
    id VARCHAR(64) NOT NULL,
    activity_code VARCHAR(50) NOT NULL,
    activity_name VARCHAR(100) NOT NULL,
    activity_description TEXT,
    activity_category VARCHAR(50) NOT NULL DEFAULT 'general',
    severity_level ENUM('info', 'warning', 'critical') NOT NULL DEFAULT 'info',
    requires_audit BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME,
    PRIMARY KEY (id),
    UNIQUE KEY uk_activity_code (activity_code),
    INDEX idx_category (activity_category),
    INDEX idx_severity (severity_level),
    INDEX idx_active (is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ACTIVITY LOGS TABLE ===================
-- Stores actual audit log entries
CREATE TABLE IF NOT EXISTS activity_logs (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64),
    activity_type VARCHAR(50) NOT NULL,
    activity_catalog_id VARCHAR(64),
    details TEXT,
    project_id VARCHAR(64),
    user_group_id VARCHAR(64),
    target_user_id VARCHAR(64),
    ip_address VARCHAR(45),
    user_agent TEXT,
    metadata JSON,
    severity_level ENUM('info', 'warning', 'critical') NOT NULL DEFAULT 'info',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    INDEX idx_user_activity (user_id, created_at DESC),
    INDEX idx_project_activity (project_id, created_at DESC),
    INDEX idx_activity_type (activity_type, created_at DESC),
    INDEX idx_severity (severity_level, created_at DESC),
    INDEX idx_target_user (target_user_id, created_at DESC),
    INDEX idx_activity_catalog (activity_catalog_id),
    INDEX idx_created_at (created_at DESC),
    FOREIGN KEY (activity_catalog_id) REFERENCES activity_catalog(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PERMISSION AUDIT LOG TABLE ===================
-- Specialized audit trail for permission-related changes
CREATE TABLE IF NOT EXISTS permission_audit_log (
    id VARCHAR(64) NOT NULL,
    action_type VARCHAR(50) NOT NULL,
    project_id VARCHAR(64),
    target_user_id VARCHAR(64),
    user_group_id VARCHAR(64),
    permission_id VARCHAR(64),
    permission_group_id VARCHAR(64),
    performed_by VARCHAR(64),
    old_values JSON,
    new_values JSON,
    action_timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    performed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent TEXT,
    table_name VARCHAR(100),
    record_id VARCHAR(64),
    PRIMARY KEY (id),
    INDEX idx_action_timestamp (action_timestamp DESC),
    INDEX idx_performed_by (performed_by, action_timestamp DESC),
    INDEX idx_target_user (target_user_id, action_timestamp DESC),
    INDEX idx_project (project_id, action_timestamp DESC),
    INDEX idx_action_type (action_type, action_timestamp DESC)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== POPULATE ACTIVITY CATALOG ===================
-- Insert predefined activity types

-- Authentication Activities
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-001', 'user_login', 'User Login', 'User successfully logged in', 'authentication', 'info', TRUE, TRUE),
('act-cat-002', 'user_logout', 'User Logout', 'User logged out', 'authentication', 'info', TRUE, TRUE),
('act-cat-003', 'user_login_failed', 'Login Failed', 'User login attempt failed', 'authentication', 'warning', TRUE, TRUE),
('act-cat-004', 'session_created', 'Session Created', 'New user session created', 'authentication', 'info', FALSE, TRUE),
('act-cat-005', 'session_expired', 'Session Expired', 'User session expired', 'authentication', 'info', FALSE, TRUE);

-- User Management Activities
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-006', 'user_registration', 'User Registration', 'New user registered', 'user_management', 'info', TRUE, TRUE),
('act-cat-007', 'user_update', 'User Updated', 'User profile updated', 'user_management', 'info', TRUE, TRUE),
('act-cat-008', 'user_status_change', 'User Status Changed', 'User status changed (active/inactive)', 'user_management', 'warning', TRUE, TRUE),
('act-cat-009', 'user_password_reset', 'Password Reset', 'User password was reset', 'user_management', 'warning', TRUE, TRUE),
('act-cat-010', 'user_type_changed', 'User Type Changed', 'User type changed (root/admin/consumer)', 'user_management', 'critical', TRUE, TRUE),
('act-cat-011', 'user_deleted', 'User Deleted', 'User account deleted', 'user_management', 'critical', TRUE, TRUE);

-- Project Management Activities
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-012', 'project_creation', 'Project Created', 'New project created', 'project_management', 'info', TRUE, TRUE),
('act-cat-013', 'project_update', 'Project Updated', 'Project details updated', 'project_management', 'info', TRUE, TRUE),
('act-cat-014', 'project_delete', 'Project Deleted', 'Project deleted', 'project_management', 'critical', TRUE, TRUE),
('act-cat-015', 'project_archived', 'Project Archived', 'Project archived', 'project_management', 'warning', TRUE, TRUE),
('act-cat-016', 'project_unarchived', 'Project Unarchived', 'Project unarchived', 'project_management', 'info', TRUE, TRUE),
('act-cat-017', 'project_ownership_transferred', 'Ownership Transferred', 'Project ownership transferred to another user', 'project_management', 'critical', TRUE, TRUE);

-- Project Members Activities
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-018', 'project_member_add', 'Member Added', 'User added to project', 'project_members', 'info', TRUE, TRUE),
('act-cat-019', 'project_member_remove', 'Member Removed', 'User removed from project', 'project_members', 'warning', TRUE, TRUE),
('act-cat-020', 'project_member_removed', 'Member Left', 'User removed from project', 'project_members', 'info', TRUE, TRUE);

-- Group Management Activities
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-021', 'group_creation', 'Group Created', 'New user group created', 'group_management', 'info', TRUE, TRUE),
('act-cat-022', 'group_update', 'Group Updated', 'User group details updated', 'group_management', 'info', TRUE, TRUE),
('act-cat-023', 'group_delete', 'Group Deleted', 'User group deleted', 'group_management', 'critical', TRUE, TRUE),
('act-cat-024', 'user_group_assign', 'User Assigned to Group', 'User assigned to user group', 'group_management', 'info', TRUE, TRUE),
('act-cat-025', 'user_group_remove', 'User Removed from Group', 'User removed from user group', 'group_management', 'warning', TRUE, TRUE),
('act-cat-026', 'group_project_access_granted', 'Group Project Access', 'User group granted access to project', 'group_management', 'warning', TRUE, TRUE),
('act-cat-027', 'group_project_access_revoked', 'Group Access Revoked', 'User group access to project revoked', 'group_management', 'warning', TRUE, TRUE);

-- Permission Management Activities
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-028', 'permission_grant', 'Permission Granted', 'Permission granted to user', 'permission_management', 'warning', TRUE, TRUE),
('act-cat-029', 'permission_revoke', 'Permission Revoked', 'Permission revoked from user', 'permission_management', 'warning', TRUE, TRUE),
('act-cat-030', 'role_removed', 'Role Removed', 'Role removed from user', 'permission_management', 'warning', TRUE, TRUE),
('act-cat-031', 'role_assigned', 'Role Assigned', 'Role assigned to user', 'permission_management', 'warning', TRUE, TRUE),
('act-cat-032', 'permission_group_assigned', 'Permission Group Assigned', 'Permission group assigned', 'permission_management', 'warning', TRUE, TRUE),
('act-cat-033', 'permission_group_revoked', 'Permission Group Revoked', 'Permission group revoked', 'permission_management', 'warning', TRUE, TRUE);

-- Bulk Operations Activities
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-034', 'bulk_role_assignment', 'Bulk Role Assignment', 'Multiple roles assigned at once', 'bulk_operations', 'critical', TRUE, TRUE),
('act-cat-035', 'bulk_group_assignment', 'Bulk Group Assignment', 'Multiple users assigned to groups', 'bulk_operations', 'warning', TRUE, TRUE),
('act-cat-036', 'bulk_user_update', 'Bulk User Update', 'Multiple users updated at once', 'bulk_operations', 'warning', TRUE, TRUE),
('act-cat-037', 'bulk_user_delete', 'Bulk User Delete', 'Multiple users deleted at once', 'bulk_operations', 'critical', TRUE, TRUE);

-- Admin and System Activities
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-038', 'admin_action', 'Admin Action', 'General administrative action', 'admin', 'warning', TRUE, TRUE),
('act-cat-039', 'system_event', 'System Event', 'System-level event', 'system', 'info', TRUE, TRUE),
('act-cat-040', 'security_alert', 'Security Alert', 'Security-related alert or event', 'security', 'critical', TRUE, TRUE);

-- API Key Management Activities
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-041', 'api_key_created', 'API Key Created', 'New API key created for user on project', 'api_keys', 'warning', TRUE, TRUE),
('act-cat-042', 'api_key_revoked', 'API Key Revoked', 'API key was revoked', 'api_keys', 'warning', TRUE, TRUE),
('act-cat-043', 'api_key_reactivated', 'API Key Reactivated', 'Expired API key was reactivated by extending expiration', 'api_keys', 'warning', TRUE, TRUE),
('act-cat-044', 'api_key_expired', 'API Key Expired', 'API key was auto-deactivated due to expiration', 'api_keys', 'info', TRUE, TRUE),
('act-cat-045', 'api_key_updated', 'API Key Updated', 'API key name or description was updated', 'api_keys', 'info', TRUE, TRUE);

-- Email Activation, Reset, and Delivery Activities
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-046', 'user_email_added', 'User Email Added', 'User email row was added for activation', 'email', 'info', TRUE, TRUE),
('act-cat-047', 'user_email_activation_requested', 'Email Activation Requested', 'Email activation link was requested', 'email', 'info', TRUE, TRUE),
('act-cat-048', 'user_email_activation_resent', 'Email Activation Resent', 'Email activation link was resent', 'email', 'info', TRUE, TRUE),
('act-cat-049', 'user_email_activated', 'User Email Activated', 'User email was activated', 'email', 'warning', TRUE, TRUE),
('act-cat-050', 'user_email_removed', 'User Email Removed', 'User email was removed', 'email', 'warning', TRUE, TRUE),
('act-cat-051', 'user_email_primary_changed', 'Primary Email Changed', 'Primary user email was changed', 'email', 'warning', TRUE, TRUE),
('act-cat-052', 'auth_email_login', 'Email Login', 'User authenticated using an activated email identifier', 'authentication', 'info', TRUE, TRUE),
('act-cat-053', 'password_reset_requested', 'Password Reset Requested', 'Password reset link was requested', 'authentication', 'warning', TRUE, TRUE),
('act-cat-054', 'password_reset_consumed', 'Password Reset Consumed', 'Password reset link was consumed', 'authentication', 'critical', TRUE, TRUE),
('act-cat-055', 'admin_password_reset_requested', 'Admin Password Reset Requested', 'Admin/root requested a password reset link', 'admin', 'critical', TRUE, TRUE),
('act-cat-056', 'email_message_enqueued', 'Email Message Enqueued', 'Transactional auth email was enqueued', 'email_delivery', 'info', TRUE, TRUE),
('act-cat-057', 'email_message_sent', 'Email Message Sent', 'Transactional auth email was sent by provider', 'email_delivery', 'info', TRUE, TRUE),
('act-cat-058', 'email_message_delivered', 'Email Message Delivered', 'Provider reported email delivery', 'email_delivery', 'info', TRUE, TRUE),
('act-cat-059', 'email_message_bounced', 'Email Message Bounced', 'Provider reported email bounce', 'email_delivery', 'warning', TRUE, TRUE),
('act-cat-060', 'email_message_complained', 'Email Complaint Received', 'Provider reported recipient complaint', 'email_delivery', 'critical', TRUE, TRUE),
('act-cat-061', 'email_message_dead_lettered', 'Email Message Dead Lettered', 'Transactional auth email exhausted retry budget', 'email_delivery', 'critical', TRUE, TRUE),
('act-cat-062', 'email_suppression_updated', 'Email Suppression Updated', 'Email suppression state was updated', 'email_delivery', 'warning', TRUE, TRUE);

-- Password Recovery / Change Activities
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-063', 'password_changed', 'Password Changed', 'Authenticated self-service password change succeeded', 'authentication', 'critical', TRUE, TRUE)
ON DUPLICATE KEY UPDATE
    activity_code = VALUES(activity_code),
    activity_name = VALUES(activity_name),
    activity_description = VALUES(activity_description),
    activity_category = VALUES(activity_category),
    severity_level = VALUES(severity_level),
    requires_audit = VALUES(requires_audit),
    is_active = VALUES(is_active);

-- Google OAuth Activities
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-064', 'google_oauth_started', 'Google OAuth Started', 'Google OAuth authorization start created after provider-init redemption', 'authentication', 'info', TRUE, TRUE),
('act-cat-065', 'google_oauth_provider_init_rejected', 'Google OAuth Provider-Init Rejected', 'Google OAuth provider-init redemption was rejected', 'authentication', 'warning', TRUE, TRUE),
('act-cat-066', 'google_oauth_callback_received', 'Google OAuth Callback Received', 'Google OAuth callback entered after basic query parsing', 'authentication', 'info', TRUE, TRUE),
('act-cat-067', 'google_oauth_state_rejected', 'Google OAuth State Rejected', 'Google OAuth state was missing, expired, replayed, or mismatched', 'authentication', 'warning', TRUE, TRUE),
('act-cat-068', 'google_oauth_nonce_rejected', 'Google OAuth Nonce Rejected', 'Google OAuth ID-token nonce mismatch was rejected', 'authentication', 'warning', TRUE, TRUE),
('act-cat-069', 'google_oauth_token_exchange_failed', 'Google OAuth Token Exchange Failed', 'Google OAuth token endpoint exchange failed', 'authentication', 'warning', TRUE, TRUE),
('act-cat-070', 'google_oauth_id_token_rejected', 'Google OAuth ID Token Rejected', 'Google OAuth ID-token validation failed', 'authentication', 'warning', TRUE, TRUE),
('act-cat-071', 'google_oauth_login_succeeded', 'Google OAuth Login Succeeded', 'Google OAuth local session issuance succeeded', 'authentication', 'info', TRUE, TRUE),
('act-cat-072', 'google_oauth_login_denied', 'Google OAuth Login Denied', 'Google OAuth login denied by provisioning, project access, consumer policy, or collision checks', 'authentication', 'warning', TRUE, TRUE),
('act-cat-073', 'google_oauth_external_account_linked', 'Google OAuth External Account Linked', 'Google external account linked to a local consumer', 'authentication', 'warning', TRUE, TRUE),
('act-cat-074', 'google_oauth_external_account_unlinked', 'Google OAuth External Account Unlinked', 'Google external account unlinked from a local consumer', 'authentication', 'warning', TRUE, TRUE)
ON DUPLICATE KEY UPDATE
    activity_code = VALUES(activity_code),
    activity_name = VALUES(activity_name),
    activity_description = VALUES(activity_description),
    activity_category = VALUES(activity_category),
    severity_level = VALUES(severity_level),
    requires_audit = VALUES(requires_audit),
    is_active = VALUES(is_active);

-- Patreon Entitlement/Link Activities (reserved act-cat-075+ range)
-- These are redacted operational/security evidence events. Details must never contain
-- raw Patreon IDs, raw email, signatures, raw payloads, creator tokens, proof tokens,
-- webhook secrets, or provider API responses.
INSERT INTO activity_catalog (id, activity_code, activity_name, activity_description, activity_category, severity_level, requires_audit, is_active) VALUES
('act-cat-075', 'patreon_link_proof_requested', 'Patreon Link Proof Requested', 'Patreon email-loop link proof was requested and enqueued', 'patreon', 'info', TRUE, TRUE),
('act-cat-076', 'patreon_link_proof_consumed', 'Patreon Link Proof Consumed', 'Patreon email-loop link proof was consumed', 'patreon', 'warning', TRUE, TRUE),
('act-cat-077', 'patreon_linked', 'Patreon Linked', 'Patreon provider identity linked to a local consumer', 'patreon', 'warning', TRUE, TRUE),
('act-cat-078', 'patreon_link_rejected', 'Patreon Link Rejected', 'Patreon link request was rejected or blocked safely', 'patreon', 'warning', TRUE, TRUE),
('act-cat-079', 'patreon_unlinked', 'Patreon Unlinked', 'Patreon provider identity was soft-unlinked from a local consumer', 'patreon', 'warning', TRUE, TRUE),
('act-cat-080', 'patreon_webhook_received', 'Patreon Webhook Received', 'Verified Patreon webhook was accepted for idempotent processing', 'patreon', 'info', TRUE, TRUE),
('act-cat-081', 'patreon_webhook_rejected', 'Patreon Webhook Rejected', 'Patreon webhook was rejected before mutation', 'patreon', 'critical', TRUE, TRUE),
('act-cat-082', 'patreon_webhook_replay_ignored', 'Patreon Webhook Replay Ignored', 'Duplicate Patreon webhook delivery was ignored idempotently', 'patreon', 'info', TRUE, TRUE),
('act-cat-083', 'patreon_sync_started', 'Patreon Sync Started', 'Patreon scheduled or manual sync started', 'patreon', 'info', TRUE, TRUE),
('act-cat-084', 'patreon_sync_completed', 'Patreon Sync Completed', 'Patreon scheduled or manual sync completed', 'patreon', 'info', TRUE, TRUE),
('act-cat-085', 'patreon_sync_failed', 'Patreon Sync Failed', 'Patreon sync failed or entered retry/degraded state', 'patreon', 'warning', TRUE, TRUE),
('act-cat-086', 'patreon_entitlement_changed', 'Patreon Entitlement Changed', 'Normalized Patreon entitlement changed', 'patreon', 'warning', TRUE, TRUE),
('act-cat-087', 'patreon_tier_map_miss', 'Patreon Tier Map Miss', 'Observed Patreon tier did not match an active internal tier map', 'patreon', 'warning', TRUE, TRUE),
('act-cat-088', 'patreon_token_refreshed', 'Patreon Token Refreshed', 'Server-only Patreon creator token state refreshed or rotated', 'patreon', 'info', TRUE, TRUE),
('act-cat-089', 'patreon_token_revoked', 'Patreon Token Revoked', 'Server-only Patreon creator token appears revoked or unusable', 'patreon', 'critical', TRUE, TRUE),
('act-cat-090', 'patreon_retention_purged', 'Patreon Retention Purged', 'Bounded Patreon proof, webhook, or raw-payload retention purge ran', 'patreon', 'info', TRUE, TRUE)
ON DUPLICATE KEY UPDATE
    activity_code = VALUES(activity_code),
    activity_name = VALUES(activity_name),
    activity_description = VALUES(activity_description),
    activity_category = VALUES(activity_category),
    severity_level = VALUES(severity_level),
    requires_audit = VALUES(requires_audit),
    is_active = VALUES(is_active);

-- =================== TABLE CREATION COMPLETE ===================
SELECT 'Activity logging tables created successfully!' as status, 
       '3 tables created: activity_catalog, activity_logs, permission_audit_log' as details;
