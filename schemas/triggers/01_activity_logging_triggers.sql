-- ===================================================================================
-- Activity Logging Triggers - Part 1: Core Entities
-- ===================================================================================
-- Automatic triggers to log all CRUD operations for activity tracking
-- These triggers capture user actions (not API logs) for audit purposes
-- MySQL Database
-- ===================================================================================

USE magic_auth;

DELIMITER //

-- ===================================================================================
-- USERS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_user_insert//
CREATE TRIGGER trg_after_user_insert AFTER INSERT ON users FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, target_user_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.created_by, 'user_registration', ac.id,
           CONCAT('User created: ', NEW.username, ' (', NEW.user_type, ')'), NEW.id,
           JSON_OBJECT('user_hash', NEW.user_hash, 'username', NEW.username, 'user_type', NEW.user_type),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'user_registration' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_user_update//
CREATE TRIGGER trg_after_user_update AFTER UPDATE ON users FOR EACH ROW
BEGIN
    DECLARE v_code VARCHAR(50);
    SET v_code = CASE
        WHEN NEW.user_type != OLD.user_type THEN 'user_type_changed'
        WHEN NEW.is_active != OLD.is_active THEN 'user_status_change'
        WHEN NEW.password_hash != OLD.password_hash THEN 'user_password_reset'
        ELSE 'user_update' END;
    
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, target_user_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.id, v_code, ac.id,
           CONCAT('User updated: ', NEW.username, ' - ', v_code), NEW.id,
           JSON_OBJECT('old', JSON_OBJECT('user_type', OLD.user_type, 'is_active', OLD.is_active),
                       'new', JSON_OBJECT('user_type', NEW.user_type, 'is_active', NEW.is_active)),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = v_code AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_user_delete//
CREATE TRIGGER trg_after_user_delete AFTER DELETE ON users FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, target_user_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'user_deleted', ac.id,
           CONCAT('User deleted: ', OLD.username), OLD.id,
           JSON_OBJECT('user_hash', OLD.user_hash, 'username', OLD.username),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'user_deleted' AND ac.is_active = TRUE LIMIT 1;
END//

-- ===================================================================================
-- PROJECTS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_project_insert//
CREATE TRIGGER trg_after_project_insert AFTER INSERT ON projects FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, project_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.created_by, 'project_creation', ac.id,
           CONCAT('Project created: ', NEW.project_name), NEW.id,
           JSON_OBJECT('project_hash', NEW.project_hash, 'project_name', NEW.project_name, 'owner_id', NEW.owner_id),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'project_creation' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_project_update//
CREATE TRIGGER trg_after_project_update AFTER UPDATE ON projects FOR EACH ROW
BEGIN
    DECLARE v_code VARCHAR(50);
    SET v_code = CASE
        WHEN NEW.archived = TRUE AND OLD.archived = FALSE THEN 'project_archived'
        WHEN NEW.archived = FALSE AND OLD.archived = TRUE THEN 'project_unarchived'
        WHEN NEW.owner_id != OLD.owner_id THEN 'project_ownership_transferred'
        ELSE 'project_update' END;
    
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, project_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.id, v_code, ac.id,
           CONCAT('Project ', v_code, ': ', NEW.project_name), NEW.id,
           JSON_OBJECT('old', JSON_OBJECT('archived', OLD.archived, 'owner_id', OLD.owner_id),
                       'new', JSON_OBJECT('archived', NEW.archived, 'owner_id', NEW.owner_id)),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = v_code AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_project_delete//
CREATE TRIGGER trg_after_project_delete AFTER DELETE ON projects FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, project_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'project_delete', ac.id,
           CONCAT('Project deleted: ', OLD.project_name), OLD.id,
           JSON_OBJECT('project_hash', OLD.project_hash, 'project_name', OLD.project_name),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'project_delete' AND ac.is_active = TRUE LIMIT 1;
END//

-- ===================================================================================
-- USER_GROUPS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_user_group_insert//
CREATE TRIGGER trg_after_user_group_insert AFTER INSERT ON user_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, user_group_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.created_by, 'group_creation', ac.id,
           CONCAT('User group created: ', NEW.group_name), NEW.id,
           JSON_OBJECT('group_hash', NEW.group_hash, 'group_name', NEW.group_name, 'group_level', NEW.group_level),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'group_creation' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_user_group_update//
CREATE TRIGGER trg_after_user_group_update AFTER UPDATE ON user_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, user_group_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'group_update', ac.id,
           CONCAT('User group updated: ', NEW.group_name), NEW.id,
           JSON_OBJECT('old', JSON_OBJECT('group_name', OLD.group_name, 'is_active', OLD.is_active),
                       'new', JSON_OBJECT('group_name', NEW.group_name, 'is_active', NEW.is_active)),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'group_update' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_user_group_delete//
CREATE TRIGGER trg_after_user_group_delete AFTER DELETE ON user_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, user_group_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'group_delete', ac.id,
           CONCAT('User group deleted: ', OLD.group_name), OLD.id,
           JSON_OBJECT('group_hash', OLD.group_hash, 'group_name', OLD.group_name),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'group_delete' AND ac.is_active = TRUE LIMIT 1;
END//

-- ===================================================================================
-- USER_GROUP_MEMBERS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_ugm_insert//
CREATE TRIGGER trg_after_ugm_insert AFTER INSERT ON user_group_members FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, target_user_id, user_group_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.assigned_by, 'user_group_assign', ac.id,
           CONCAT('User assigned to group'), NEW.user_id, NEW.user_group_id,
           JSON_OBJECT('user_id', NEW.user_id, 'user_group_id', NEW.user_group_id),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'user_group_assign' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_ugm_delete//
CREATE TRIGGER trg_after_ugm_delete AFTER DELETE ON user_group_members FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, target_user_id, user_group_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'user_group_remove', ac.id,
           CONCAT('User removed from group'), OLD.user_id, OLD.user_group_id,
           JSON_OBJECT('user_id', OLD.user_id, 'user_group_id', OLD.user_group_id),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'user_group_remove' AND ac.is_active = TRUE LIMIT 1;
END//

-- ===================================================================================
-- USER_GROUP_PROJECTS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_ugp_insert//
CREATE TRIGGER trg_after_ugp_insert AFTER INSERT ON user_group_projects FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, activity_catalog_id, details, project_id, user_group_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), NEW.granted_by, 'group_project_access_granted', ac.id,
           'Group granted access to project', NEW.project_id, NEW.user_group_id,
           JSON_OBJECT('user_group_id', NEW.user_group_id, 'project_id', NEW.project_id),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'group_project_access_granted' AND ac.is_active = TRUE LIMIT 1;
END//

DROP TRIGGER IF EXISTS trg_after_ugp_delete//
CREATE TRIGGER trg_after_ugp_delete AFTER DELETE ON user_group_projects FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, activity_catalog_id, details, project_id, user_group_id, metadata, severity_level, created_at)
    SELECT CONCAT('act-log-', UUID()), 'group_project_access_revoked', ac.id,
           'Group access revoked from project', OLD.project_id, OLD.user_group_id,
           JSON_OBJECT('user_group_id', OLD.user_group_id, 'project_id', OLD.project_id),
           ac.severity_level, NOW()
    FROM activity_catalog ac WHERE ac.activity_code = 'group_project_access_revoked' AND ac.is_active = TRUE LIMIT 1;
END//

DELIMITER ;

SELECT 'Part 1: Core entity activity logging triggers created!' as status;
