-- ===================================================================================
-- Activity Logging Triggers - Part 2: Permissions & Roles
-- ===================================================================================
-- Triggers for permission, role, and permission group CRUD operations
-- MySQL Database
-- ===================================================================================

USE magic_auth;

DELIMITER //

-- ===================================================================================
-- ROLES TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_role_insert//
CREATE TRIGGER trg_after_role_insert AFTER INSERT ON roles FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.created_by, 'role_assigned', ac.id,
           CONCAT('Role created: ', NEW.role_name, ' (', NEW.role_display_name, ')'),
           JSON_OBJECT('role_hash', NEW.role_hash, 'role_name', NEW.role_name, 'role_priority', NEW.role_priority, 'is_system_role', NEW.is_system_role),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'role_assigned' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_role_update//
CREATE TRIGGER trg_after_role_update AFTER UPDATE ON roles FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'role_assigned', ac.id,
           CONCAT('Role updated: ', NEW.role_name),
           JSON_OBJECT('role_name', NEW.role_name,
                       'old', JSON_OBJECT('role_display_name', OLD.role_display_name, 'role_priority', OLD.role_priority, 'is_active', OLD.is_active),
                       'new', JSON_OBJECT('role_display_name', NEW.role_display_name, 'role_priority', NEW.role_priority, 'is_active', NEW.is_active)),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'role_assigned' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_role_delete//
CREATE TRIGGER trg_after_role_delete AFTER DELETE ON roles FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'role_removed', ac.id,
           CONCAT('Role deleted: ', OLD.role_name),
           JSON_OBJECT('role_hash', OLD.role_hash, 'role_name', OLD.role_name, 'role_display_name', OLD.role_display_name),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'role_removed' AND ac.is_active = TRUE LIMIT 1;
END//

-- ===================================================================================
-- GLOBAL_PERMISSION_GROUPS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_perm_group_insert//
CREATE TRIGGER trg_after_perm_group_insert AFTER INSERT ON global_permission_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.created_by, 'permission_group_assigned', ac.id,
           CONCAT('Permission group created: ', NEW.group_name, ' (', NEW.group_display_name, ')'),
           JSON_OBJECT('group_hash', NEW.group_hash, 'group_name', NEW.group_name, 'group_category', NEW.group_category),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_group_assigned' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_perm_group_update//
CREATE TRIGGER trg_after_perm_group_update AFTER UPDATE ON global_permission_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'permission_group_assigned', ac.id,
           CONCAT('Permission group updated: ', NEW.group_name),
           JSON_OBJECT('group_name', NEW.group_name,
                       'old', JSON_OBJECT('group_display_name', OLD.group_display_name, 'is_active', OLD.is_active),
                       'new', JSON_OBJECT('group_display_name', NEW.group_display_name, 'is_active', NEW.is_active)),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_group_assigned' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_perm_group_delete//
CREATE TRIGGER trg_after_perm_group_delete AFTER DELETE ON global_permission_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'permission_group_revoked', ac.id,
           CONCAT('Permission group deleted: ', OLD.group_name),
           JSON_OBJECT('group_hash', OLD.group_hash, 'group_name', OLD.group_name),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_group_revoked' AND ac.is_active = TRUE LIMIT 1;
END//

-- ===================================================================================
-- GLOBAL_PERMISSIONS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_permission_insert//
CREATE TRIGGER trg_after_permission_insert AFTER INSERT ON global_permissions FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.created_by, 'permission_grant', ac.id,
           CONCAT('Permission created: ', NEW.permission_name, ' (', NEW.permission_display_name, ')'),
           JSON_OBJECT('permission_hash', NEW.permission_hash, 'permission_name', NEW.permission_name, 'permission_category', NEW.permission_category),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_grant' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_permission_update//
CREATE TRIGGER trg_after_permission_update AFTER UPDATE ON global_permissions FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'permission_grant', ac.id,
           CONCAT('Permission updated: ', NEW.permission_name),
           JSON_OBJECT('permission_name', NEW.permission_name,
                       'old', JSON_OBJECT('permission_display_name', OLD.permission_display_name, 'is_active', OLD.is_active),
                       'new', JSON_OBJECT('permission_display_name', NEW.permission_display_name, 'is_active', NEW.is_active)),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_grant' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_permission_delete//
CREATE TRIGGER trg_after_permission_delete AFTER DELETE ON global_permissions FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'permission_revoke', ac.id,
           CONCAT('Permission deleted: ', OLD.permission_name),
           JSON_OBJECT('permission_hash', OLD.permission_hash, 'permission_name', OLD.permission_name),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_revoke' AND ac.is_active = TRUE LIMIT 1;
END//

-- ===================================================================================
-- ROLE_PERMISSION_GROUPS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_rpg_insert//
CREATE TRIGGER trg_after_rpg_insert AFTER INSERT ON role_permission_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.assigned_by, 'permission_group_assigned', ac.id,
           'Permission group assigned to role',
           JSON_OBJECT('role_id', NEW.role_id, 'permission_group_id', NEW.permission_group_id),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_group_assigned' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_rpg_delete//
CREATE TRIGGER trg_after_rpg_delete AFTER DELETE ON role_permission_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'permission_group_revoked', ac.id,
           'Permission group removed from role',
           JSON_OBJECT('role_id', OLD.role_id, 'permission_group_id', OLD.permission_group_id),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_group_revoked' AND ac.is_active = TRUE LIMIT 1;
END//

-- ===================================================================================
-- USER_GROUP_PERMISSION_GROUPS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_ugpg_insert//
CREATE TRIGGER trg_after_ugpg_insert AFTER INSERT ON user_group_permission_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, user_group_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.assigned_by, 'permission_group_assigned', ac.id,
           'Permission group assigned to user group', NEW.user_group_id,
           JSON_OBJECT('user_group_id', NEW.user_group_id, 'permission_group_id', NEW.permission_group_id),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_group_assigned' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_ugpg_delete//
CREATE TRIGGER trg_after_ugpg_delete AFTER DELETE ON user_group_permission_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, user_group_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'permission_group_revoked', ac.id,
           'Permission group removed from user group', OLD.user_group_id,
           JSON_OBJECT('user_group_id', OLD.user_group_id, 'permission_group_id', OLD.permission_group_id),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_group_revoked' AND ac.is_active = TRUE LIMIT 1;
END//

-- ===================================================================================
-- USER_PERMISSION_GROUPS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_upg_insert//
CREATE TRIGGER trg_after_upg_insert AFTER INSERT ON user_permission_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, target_user_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.assigned_by, 'permission_group_assigned', ac.id,
           'Permission group assigned directly to user', NEW.user_id,
           JSON_OBJECT('user_id', NEW.user_id, 'permission_group_id', NEW.permission_group_id, 'notes', NEW.notes),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_group_assigned' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_upg_delete//
CREATE TRIGGER trg_after_upg_delete AFTER DELETE ON user_permission_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, target_user_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'permission_group_revoked', ac.id,
           'Permission group removed from user', OLD.user_id,
           JSON_OBJECT('user_id', OLD.user_id, 'permission_group_id', OLD.permission_group_id),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_group_revoked' AND ac.is_active = TRUE LIMIT 1;
END//

-- ===================================================================================
-- GLOBAL_PERMISSION_GROUP_PERMISSIONS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_gpgp_insert//
CREATE TRIGGER trg_after_gpgp_insert AFTER INSERT ON global_permission_group_permissions FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.granted_by, 'permission_grant', ac.id,
           'Permission added to permission group',
           JSON_OBJECT('permission_group_id', NEW.permission_group_id, 'permission_id', NEW.permission_id),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_grant' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_gpgp_delete//
CREATE TRIGGER trg_after_gpgp_delete AFTER DELETE ON global_permission_group_permissions FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'permission_revoke', ac.id,
           'Permission removed from permission group',
           JSON_OBJECT('permission_group_id', OLD.permission_group_id, 'permission_id', OLD.permission_id),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'permission_revoke' AND ac.is_active = TRUE LIMIT 1;
END//

-- ===================================================================================
-- USER_SESSIONS TABLE TRIGGERS (Login/Logout tracking)
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_session_insert//
CREATE TRIGGER trg_after_session_insert AFTER INSERT ON user_sessions FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, project_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.user_id, 'session_created', ac.id,
           'User session created', NEW.project_id,
           JSON_OBJECT('session_id', NEW.id, 'project_id', NEW.project_id, 'expires_at', NEW.expires_at),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'session_created' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_session_update//
CREATE TRIGGER trg_after_session_update AFTER UPDATE ON user_sessions FOR EACH ROW
BEGIN
    IF NEW.is_active = FALSE AND OLD.is_active = TRUE THEN
        INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, project_id, metadata, severity_level, created_at)
        SELECT CONCAT('act-log-', UUID()), NEW.user_id, 'user_logout', ac.id,
               'User session ended', NEW.project_id,
               JSON_OBJECT('session_id', NEW.id, 'project_id', NEW.project_id),
               ac.severity_level, NOW()
        FROM activity_catalog ac WHERE ac.activity_code = 'user_logout' AND ac.is_active = TRUE LIMIT 1;
    END IF;
END//

DELIMITER ;

SELECT 'Part 2: Permission and role activity logging triggers created!' as status;
