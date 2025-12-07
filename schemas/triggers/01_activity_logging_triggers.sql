-- ===================================================================================
-- Activity Logging Triggers - Part 1: Core Entities
-- GROUPS OF GROUPS Architecture
-- ===================================================================================
-- Automatic triggers to log all CRUD operations for activity tracking
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
    INSERT INTO activity_logs (id, user_id, activity_type, details, target_user_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        NEW.created_by,
        'user_registration',
        CONCAT('User created: ', NEW.username, ' (', NEW.user_type, ')'),
        NEW.id,
        JSON_OBJECT('user_hash', NEW.user_hash, 'username', NEW.username, 'user_type', NEW.user_type),
        'INFO',
        NOW()
    );
END//

DROP TRIGGER IF EXISTS trg_after_user_update//
CREATE TRIGGER trg_after_user_update AFTER UPDATE ON users FOR EACH ROW
BEGIN
    DECLARE v_activity_type VARCHAR(50);
    SET v_activity_type = CASE
        WHEN NEW.user_type != OLD.user_type THEN 'user_type_changed'
        WHEN NEW.is_active != OLD.is_active THEN 'user_status_change'
        WHEN NEW.password_hash != OLD.password_hash THEN 'user_password_reset'
        ELSE 'user_update'
    END;
    
    INSERT INTO activity_logs (id, user_id, activity_type, details, target_user_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        NEW.id,
        v_activity_type,
        CONCAT('User updated: ', NEW.username, ' - ', v_activity_type),
        NEW.id,
        JSON_OBJECT(
            'old', JSON_OBJECT('user_type', OLD.user_type, 'is_active', OLD.is_active),
            'new', JSON_OBJECT('user_type', NEW.user_type, 'is_active', NEW.is_active)
        ),
        'INFO',
        NOW()
    );
END//

DROP TRIGGER IF EXISTS trg_after_user_delete//
CREATE TRIGGER trg_after_user_delete AFTER DELETE ON users FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, details, target_user_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        'user_deleted',
        CONCAT('User deleted: ', OLD.username),
        OLD.id,
        JSON_OBJECT('user_hash', OLD.user_hash, 'username', OLD.username),
        'WARN',
        NOW()
    );
END//

-- ===================================================================================
-- PROJECTS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_project_insert//
CREATE TRIGGER trg_after_project_insert AFTER INSERT ON projects FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, details, project_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        NEW.created_by,
        'project_creation',
        CONCAT('Project created: ', NEW.project_name),
        NEW.id,
        JSON_OBJECT('project_hash', NEW.project_hash, 'project_name', NEW.project_name, 'owner_id', NEW.owner_id),
        'INFO',
        NOW()
    );
END//

DROP TRIGGER IF EXISTS trg_after_project_update//
CREATE TRIGGER trg_after_project_update AFTER UPDATE ON projects FOR EACH ROW
BEGIN
    DECLARE v_activity_type VARCHAR(50);
    SET v_activity_type = CASE
        WHEN NEW.archived = TRUE AND OLD.archived = FALSE THEN 'project_archived'
        WHEN NEW.archived = FALSE AND OLD.archived = TRUE THEN 'project_unarchived'
        WHEN NEW.owner_id != OLD.owner_id THEN 'project_ownership_transferred'
        ELSE 'project_update'
    END;
    
    INSERT INTO activity_logs (id, user_id, activity_type, details, project_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        NEW.id,
        v_activity_type,
        CONCAT('Project ', v_activity_type, ': ', NEW.project_name),
        NEW.id,
        JSON_OBJECT(
            'old', JSON_OBJECT('archived', OLD.archived, 'owner_id', OLD.owner_id),
            'new', JSON_OBJECT('archived', NEW.archived, 'owner_id', NEW.owner_id)
        ),
        'INFO',
        NOW()
    );
END//

DROP TRIGGER IF EXISTS trg_after_project_delete//
CREATE TRIGGER trg_after_project_delete AFTER DELETE ON projects FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, details, project_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        'project_delete',
        CONCAT('Project deleted: ', OLD.project_name),
        OLD.id,
        JSON_OBJECT('project_hash', OLD.project_hash, 'project_name', OLD.project_name),
        'WARN',
        NOW()
    );
END//

-- ===================================================================================
-- USER_GROUPS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_user_group_insert//
CREATE TRIGGER trg_after_user_group_insert AFTER INSERT ON user_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, details, user_group_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        NEW.created_by,
        'group_creation',
        CONCAT('User group created: ', NEW.group_name),
        NEW.id,
        JSON_OBJECT('group_hash', NEW.group_hash, 'group_name', NEW.group_name, 'is_root', NEW.parent_group_id IS NULL),
        'INFO',
        NOW()
    );
END//

DROP TRIGGER IF EXISTS trg_after_user_group_update//
CREATE TRIGGER trg_after_user_group_update AFTER UPDATE ON user_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, details, user_group_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        'group_update',
        CONCAT('User group updated: ', NEW.group_name),
        NEW.id,
        JSON_OBJECT(
            'old', JSON_OBJECT('group_name', OLD.group_name, 'is_active', OLD.is_active),
            'new', JSON_OBJECT('group_name', NEW.group_name, 'is_active', NEW.is_active)
        ),
        'INFO',
        NOW()
    );
END//

DROP TRIGGER IF EXISTS trg_after_user_group_delete//
CREATE TRIGGER trg_after_user_group_delete AFTER DELETE ON user_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, details, user_group_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        'group_delete',
        CONCAT('User group deleted: ', OLD.group_name),
        OLD.id,
        JSON_OBJECT('group_hash', OLD.group_hash, 'group_name', OLD.group_name),
        'WARN',
        NOW()
    );
END//

-- ===================================================================================
-- PROJECT_GROUPS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_project_group_insert//
CREATE TRIGGER trg_after_project_group_insert AFTER INSERT ON project_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, details, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        NEW.created_by,
        'project_group_creation',
        CONCAT('Project group created: ', NEW.group_name),
        JSON_OBJECT('group_hash', NEW.group_hash, 'group_name', NEW.group_name),
        'INFO',
        NOW()
    );
END//

DROP TRIGGER IF EXISTS trg_after_project_group_update//
CREATE TRIGGER trg_after_project_group_update AFTER UPDATE ON project_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, details, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        'project_group_update',
        CONCAT('Project group updated: ', NEW.group_name),
        JSON_OBJECT(
            'old', JSON_OBJECT('group_name', OLD.group_name, 'is_active', OLD.is_active),
            'new', JSON_OBJECT('group_name', NEW.group_name, 'is_active', NEW.is_active)
        ),
        'INFO',
        NOW()
    );
END//

DROP TRIGGER IF EXISTS trg_after_project_group_delete//
CREATE TRIGGER trg_after_project_group_delete AFTER DELETE ON project_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, details, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        'project_group_delete',
        CONCAT('Project group deleted: ', OLD.group_name),
        JSON_OBJECT('group_hash', OLD.group_hash, 'group_name', OLD.group_name),
        'WARN',
        NOW()
    );
END//

-- ===================================================================================
-- USER_GROUP_MEMBERS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_ugm_insert//
CREATE TRIGGER trg_after_ugm_insert AFTER INSERT ON user_group_members FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, details, target_user_id, user_group_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        NEW.assigned_by,
        'user_group_assign',
        'User assigned to group',
        NEW.user_id,
        NEW.user_group_id,
        JSON_OBJECT('user_id', NEW.user_id, 'user_group_id', NEW.user_group_id),
        'INFO',
        NOW()
    );
END//

DROP TRIGGER IF EXISTS trg_after_ugm_update//
CREATE TRIGGER trg_after_ugm_update AFTER UPDATE ON user_group_members FOR EACH ROW
BEGIN
    IF NEW.is_active = FALSE AND OLD.is_active = TRUE THEN
        INSERT INTO activity_logs (id, user_id, activity_type, details, target_user_id, user_group_id, metadata, severity_level, created_at)
        VALUES (
            CONCAT('act-log-', UUID()),
            NEW.removed_by,
            'user_group_remove',
            'User removed from group',
            NEW.user_id,
            NEW.user_group_id,
            JSON_OBJECT('user_id', NEW.user_id, 'user_group_id', NEW.user_group_id),
            'WARN',
            NOW()
        );
    END IF;
END//

DROP TRIGGER IF EXISTS trg_after_ugm_delete//
CREATE TRIGGER trg_after_ugm_delete AFTER DELETE ON user_group_members FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, details, target_user_id, user_group_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        'user_group_remove',
        'User membership deleted from group',
        OLD.user_id,
        OLD.user_group_id,
        JSON_OBJECT('user_id', OLD.user_id, 'user_group_id', OLD.user_group_id),
        'WARN',
        NOW()
    );
END//

-- ===================================================================================
-- PROJECT_GROUP_MEMBERS TABLE TRIGGERS
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_pgm_insert//
CREATE TRIGGER trg_after_pgm_insert AFTER INSERT ON project_group_members FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, details, project_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        NEW.assigned_by,
        'project_group_assign',
        'Project assigned to project group',
        NEW.project_id,
        JSON_OBJECT('project_id', NEW.project_id, 'project_group_id', NEW.project_group_id),
        'INFO',
        NOW()
    );
END//

DROP TRIGGER IF EXISTS trg_after_pgm_update//
CREATE TRIGGER trg_after_pgm_update AFTER UPDATE ON project_group_members FOR EACH ROW
BEGIN
    IF NEW.is_active = FALSE AND OLD.is_active = TRUE THEN
        INSERT INTO activity_logs (id, user_id, activity_type, details, project_id, metadata, severity_level, created_at)
        VALUES (
            CONCAT('act-log-', UUID()),
            NEW.removed_by,
            'project_group_remove',
            'Project removed from project group',
            NEW.project_id,
            JSON_OBJECT('project_id', NEW.project_id, 'project_group_id', NEW.project_group_id),
            'WARN',
            NOW()
        );
    END IF;
END//

DROP TRIGGER IF EXISTS trg_after_pgm_delete//
CREATE TRIGGER trg_after_pgm_delete AFTER DELETE ON project_group_members FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, details, project_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        'project_group_remove',
        'Project membership deleted from project group',
        OLD.project_id,
        JSON_OBJECT('project_id', OLD.project_id, 'project_group_id', OLD.project_group_id),
        'WARN',
        NOW()
    );
END//

-- ===================================================================================
-- USER_GROUP_PROJECT_GROUPS TABLE TRIGGERS (GROUPS OF GROUPS)
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_after_ugpg_insert//
CREATE TRIGGER trg_after_ugpg_insert AFTER INSERT ON user_group_project_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, user_id, activity_type, details, user_group_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        NEW.granted_by,
        'user_group_project_group_access_granted',
        'User group granted access to project group',
        NEW.user_group_id,
        JSON_OBJECT('user_group_id', NEW.user_group_id, 'project_group_id', NEW.project_group_id),
        'INFO',
        NOW()
    );
END//

DROP TRIGGER IF EXISTS trg_after_ugpg_update//
CREATE TRIGGER trg_after_ugpg_update AFTER UPDATE ON user_group_project_groups FOR EACH ROW
BEGIN
    IF NEW.is_active = FALSE AND OLD.is_active = TRUE THEN
        INSERT INTO activity_logs (id, user_id, activity_type, details, user_group_id, metadata, severity_level, created_at)
        VALUES (
            CONCAT('act-log-', UUID()),
            NEW.revoked_by,
            'user_group_project_group_access_revoked',
            'User group access revoked from project group',
            NEW.user_group_id,
            JSON_OBJECT('user_group_id', NEW.user_group_id, 'project_group_id', NEW.project_group_id),
            'WARN',
            NOW()
        );
    END IF;
END//

DROP TRIGGER IF EXISTS trg_after_ugpg_delete//
CREATE TRIGGER trg_after_ugpg_delete AFTER DELETE ON user_group_project_groups FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (id, activity_type, details, user_group_id, metadata, severity_level, created_at)
    VALUES (
        CONCAT('act-log-', UUID()),
        'user_group_project_group_access_revoked',
        'User group project group access deleted',
        OLD.user_group_id,
        JSON_OBJECT('user_group_id', OLD.user_group_id, 'project_group_id', OLD.project_group_id),
        'WARN',
        NOW()
    );
END//

DELIMITER ;

SELECT 'Core entity activity logging triggers created!' as status;
