-- ===================================================================================
-- Activity Logging Triggers - Part 3: API Keys
-- GROUPS OF GROUPS Architecture
-- ===================================================================================
-- Automatic triggers to log API key lifecycle events to activity_logs
-- MySQL Database
-- ===================================================================================

USE magic_auth;

DELIMITER //

-- ===================================================================================
-- USER_PROJECT_API_KEYS TABLE TRIGGERS
-- ===================================================================================

-- AFTER INSERT: Log api_key_created event
DROP TRIGGER IF EXISTS trg_after_api_key_insert//
CREATE TRIGGER trg_after_api_key_insert AFTER INSERT ON user_project_api_keys FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (
        id, user_id, activity_type, details, project_id, target_user_id,
        metadata, severity_level, created_at
    ) VALUES (
        CONCAT('act-log-', UUID()),
        NEW.created_by,
        'api_key_created',
        CONCAT('API key created: ', NEW.name, ' for owner ', NEW.owner_user_id, ' on project ', NEW.project_id),
        NEW.project_id,
        NEW.owner_user_id,
        JSON_OBJECT(
            'key_id', NEW.id,
            'public_id', NEW.public_id,
            'name', NEW.name,
            'fingerprint', NEW.fingerprint,
            'secret_last4', NEW.secret_last4,
            'expires_at', NEW.expires_at,
            'hash_algorithm', NEW.hash_algorithm
        ),
        'warning',
        NOW()
    );
END//

-- AFTER UPDATE: Log api_key_revoked, api_key_reactivated, api_key_updated events
DROP TRIGGER IF EXISTS trg_after_api_key_update//
CREATE TRIGGER trg_after_api_key_update AFTER UPDATE ON user_project_api_keys FOR EACH ROW
BEGIN
    -- Key revoked: is_active went from TRUE to FALSE
    IF NEW.is_active = FALSE AND OLD.is_active = TRUE AND NEW.revoked_at IS NOT NULL THEN
        INSERT INTO activity_logs (
            id, user_id, activity_type, details, project_id, target_user_id,
            metadata, severity_level, created_at
        ) VALUES (
            CONCAT('act-log-', UUID()),
            NEW.revoked_by,
            'api_key_revoked',
            CONCAT('API key revoked: ', NEW.name, ' (', NEW.public_id, ')'),
            NEW.project_id,
            NEW.owner_user_id,
            JSON_OBJECT(
                'key_id', NEW.id,
                'public_id', NEW.public_id,
                'name', NEW.name,
                'revoked_by', NEW.revoked_by,
                'revoke_reason', COALESCE(NEW.revoke_reason, '')
            ),
            'warning',
            NOW()
        );
    END IF;

    -- Key reactivated: is_active went from FALSE to TRUE (expired key extended)
    IF NEW.is_active = TRUE AND OLD.is_active = FALSE
       AND NEW.expires_at IS NOT NULL
       AND (OLD.expires_at IS NULL OR OLD.expires_at < NOW())
       AND NEW.expires_at > NOW() THEN
        INSERT INTO activity_logs (
            id, user_id, activity_type, details, project_id, target_user_id,
            metadata, severity_level, created_at
        ) VALUES (
            CONCAT('act-log-', UUID()),
            NEW.owner_user_id,
            'api_key_reactivated',
            CONCAT('API key reactivated: ', NEW.name, ' (', NEW.public_id, ')'),
            NEW.project_id,
            NEW.owner_user_id,
            JSON_OBJECT(
                'key_id', NEW.id,
                'public_id', NEW.public_id,
                'name', NEW.name,
                'old_expires_at', OLD.expires_at,
                'new_expires_at', NEW.expires_at
            ),
            'warning',
            NOW()
        );
    END IF;

    -- Key updated: name or description changed (not revocation/reactivation)
    IF (NEW.name != OLD.name OR NEW.description != OLD.description)
       AND NOT (NEW.is_active = FALSE AND OLD.is_active = TRUE AND NEW.revoked_at IS NOT NULL)
       AND NOT (NEW.is_active = TRUE AND OLD.is_active = FALSE
                AND NEW.expires_at IS NOT NULL
                AND (OLD.expires_at IS NULL OR OLD.expires_at < NOW())
                AND NEW.expires_at > NOW()) THEN
        INSERT INTO activity_logs (
            id, user_id, activity_type, details, project_id, target_user_id,
            metadata, severity_level, created_at
        ) VALUES (
            CONCAT('act-log-', UUID()),
            NEW.owner_user_id,
            'api_key_updated',
            CONCAT('API key updated: ', NEW.name, ' (', NEW.public_id, ')'),
            NEW.project_id,
            NEW.owner_user_id,
            JSON_OBJECT(
                'key_id', NEW.id,
                'public_id', NEW.public_id,
                'old_name', OLD.name,
                'new_name', NEW.name,
                'old_description', OLD.description,
                'new_description', NEW.description
            ),
            'info',
            NOW()
        );
    END IF;
END//

DELIMITER ;

-- ===================================================================================
-- API KEY ACTIVITY LOGGING TRIGGERS CREATED
-- ===================================================================================
SELECT 'API key activity logging triggers created!' as status;
