-- ===================================================================================
-- API KEY MANAGEMENT STORED PROCEDURES
-- GROUPS OF GROUPS Architecture
-- ===================================================================================
-- This file contains all stored procedures related to API key lifecycle:
-- - sp_create_api_key
-- - sp_validate_api_key
-- - sp_revoke_api_key
-- - sp_list_user_api_keys
-- - sp_list_project_api_keys
-- - sp_update_api_key
-- - sp_get_api_key_by_prefix
-- - sp_cleanup_expired_api_keys
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- 1. SP_CREATE_API_KEY
-- Creates a new API key after validating user has project access
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_create_api_key$$
CREATE PROCEDURE sp_create_api_key(
    IN p_key_id VARCHAR(64),
    IN p_public_id VARCHAR(16),
    IN p_project_id VARCHAR(64),
    IN p_owner_user_id VARCHAR(64),
    IN p_created_by VARCHAR(64),
    IN p_name VARCHAR(100),
    IN p_description TEXT,
    IN p_secret_hash BINARY(32),
    IN p_hash_algorithm VARCHAR(20),
    IN p_fingerprint CHAR(12),
    IN p_secret_last4 CHAR(4),
    IN p_expires_at DATETIME
)
BEGIN
    DECLARE v_owner_exists INT DEFAULT 0;
    DECLARE v_owner_active INT DEFAULT 0;
    DECLARE v_project_exists INT DEFAULT 0;
    DECLARE v_project_active INT DEFAULT 0;
    DECLARE v_has_access BOOLEAN DEFAULT FALSE;

    -- Validate owner user exists and is active
    SELECT COUNT(*) INTO v_owner_exists FROM users WHERE id = p_owner_user_id;
    IF v_owner_exists = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Owner user does not exist';
    END IF;

    SELECT COUNT(*) INTO v_owner_active FROM users WHERE id = p_owner_user_id AND is_active = 1;
    IF v_owner_active = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Owner user is not active';
    END IF;

    -- Validate project exists and is active
    SELECT COUNT(*) INTO v_project_exists FROM projects WHERE id = p_project_id;
    IF v_project_exists = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Project does not exist';
    END IF;

    SELECT COUNT(*) INTO v_project_active FROM projects WHERE id = p_project_id AND is_active = 1;
    IF v_project_active = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Project is not active';
    END IF;

    -- Check if CREATOR is root - root can create keys for any user on any project
    -- Spec: "Root Can Manage Any Key" - root bypasses target user's project access check
    BEGIN
        DECLARE v_creator_type VARCHAR(20);
        DECLARE v_creator_exists INT DEFAULT 0;
        
        -- Check creator exists and get their user_type
        SELECT COUNT(*) INTO v_creator_exists FROM users WHERE id = p_created_by AND is_active = 1;
        IF v_creator_exists > 0 THEN
            SELECT user_type INTO v_creator_type FROM users WHERE id = p_created_by AND is_active = 1;
        END IF;
        
        -- If creator is root, bypass all access checks (spec requirement)
        IF v_creator_type = 'root' THEN
            SET v_has_access = TRUE;
        ELSE
            -- Non-root creator: check that target user has access to project
            -- This enforces: API keys can only be created for users with project access
            CALL sp_check_user_project_access(p_owner_user_id, p_project_id);
            -- Since MySQL stored procs can't easily capture result sets,
            -- we re-implement the check inline here for the SIGNAL:
            BEGIN
                DECLARE v_owner_type VARCHAR(20);
                SELECT user_type INTO v_owner_type FROM users WHERE id = p_owner_user_id AND is_active = 1;

                IF v_owner_type = 'root' THEN
                    SET v_has_access = TRUE;
                ELSE
                    SELECT COUNT(*) > 0 INTO v_has_access
                    FROM user_group_members ugm
                    JOIN user_group_project_groups ugpg ON ugm.user_group_id = ugpg.user_group_id
                    JOIN project_group_members pgm ON ugpg.project_group_id = pgm.project_group_id
                    WHERE ugm.user_id = p_owner_user_id
                      AND pgm.project_id = p_project_id
                      AND ugm.is_active = 1
                      AND ugpg.is_active = 1
                      AND pgm.is_active = 1;
                END IF;
            END;

            IF v_has_access = FALSE THEN
                SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Owner user does not have access to the specified project';
            END IF;
        END IF;
    END;

    -- Insert the API key
    INSERT INTO user_project_api_keys (
        id, public_id, project_id, owner_user_id, created_by,
        name, description, secret_hash, hash_algorithm,
        fingerprint, secret_last4, is_active, expires_at,
        created_at
    ) VALUES (
        p_key_id, p_public_id, p_project_id, p_owner_user_id, p_created_by,
        p_name, p_description, p_secret_hash, p_hash_algorithm,
        p_fingerprint, p_secret_last4, TRUE, p_expires_at,
        NOW()
    );

    -- Return the created key's metadata (no secret_hash)
    SELECT
        id, public_id, project_id, owner_user_id, created_by,
        name, description, hash_algorithm, fingerprint, secret_last4,
        is_active, expires_at, created_at
    FROM user_project_api_keys
    WHERE id = p_key_id;
END$$

-- ===================================================================================
-- 2. SP_VALIDATE_API_KEY
-- Looks up key by public_id and returns metadata + stored hash for app-layer comparison
-- Also checks owner still has project access (live permission check)
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_validate_api_key$$
CREATE PROCEDURE sp_validate_api_key(
    IN p_public_id VARCHAR(16)
)
BEGIN
    DECLARE v_key_id VARCHAR(64);
    DECLARE v_owner_user_id VARCHAR(64);
    DECLARE v_project_id VARCHAR(64);
    DECLARE v_is_active BOOLEAN;
    DECLARE v_expires_at DATETIME;
    DECLARE v_secret_hash BINARY(32);
    DECLARE v_hash_algorithm VARCHAR(20);
    DECLARE v_owner_active INT DEFAULT 0;
    DECLARE v_has_access BOOLEAN DEFAULT FALSE;

    -- Lookup key record
    SELECT
        id, owner_user_id, project_id, is_active, expires_at,
        secret_hash, hash_algorithm
    INTO
        v_key_id, v_owner_user_id, v_project_id, v_is_active, v_expires_at,
        v_secret_hash, v_hash_algorithm
    FROM user_project_api_keys
    WHERE public_id = p_public_id
    LIMIT 1;

    -- If key not found, return empty result set
    IF v_key_id IS NULL THEN
        SELECT
            NULL as id, NULL as public_id, NULL as owner_user_id,
            NULL as project_id, NULL as is_active, NULL as expires_at,
            NULL as secret_hash, NULL as hash_algorithm,
            'not_found' as validation_status;
    ELSEIF v_is_active = FALSE THEN
        -- Key is revoked
        SELECT
            v_key_id as id, p_public_id as public_id, v_owner_user_id as owner_user_id,
            v_project_id as project_id, v_is_active as is_active, v_expires_at as expires_at,
            v_secret_hash as secret_hash, v_hash_algorithm as hash_algorithm,
            'revoked' as validation_status;
    ELSEIF v_expires_at IS NOT NULL AND v_expires_at < NOW() THEN
        -- Key is expired
        SELECT
            v_key_id as id, p_public_id as public_id, v_owner_user_id as owner_user_id,
            v_project_id as project_id, v_is_active as is_active, v_expires_at as expires_at,
            v_secret_hash as secret_hash, v_hash_algorithm as hash_algorithm,
            'expired' as validation_status;
    ELSE
        -- Check owner is still active
        SELECT COUNT(*) INTO v_owner_active FROM users WHERE id = v_owner_user_id AND is_active = 1;
        IF v_owner_active = 0 THEN
            SELECT
                v_key_id as id, p_public_id as public_id, v_owner_user_id as owner_user_id,
                v_project_id as project_id, v_is_active as is_active, v_expires_at as expires_at,
                v_secret_hash as secret_hash, v_hash_algorithm as hash_algorithm,
                'owner_inactive' as validation_status;
        ELSE
            -- Check owner still has project access via group chain
            BEGIN
                DECLARE v_user_type VARCHAR(20);
                SELECT user_type INTO v_user_type FROM users WHERE id = v_owner_user_id AND is_active = 1;

                IF v_user_type = 'root' THEN
                    SET v_has_access = TRUE;
                ELSE
                    SELECT COUNT(*) > 0 INTO v_has_access
                    FROM user_group_members ugm
                    JOIN user_group_project_groups ugpg ON ugm.user_group_id = ugpg.user_group_id
                    JOIN project_group_members pgm ON ugpg.project_group_id = pgm.project_group_id
                    WHERE ugm.user_id = v_owner_user_id
                      AND pgm.project_id = v_project_id
                      AND ugm.is_active = 1
                      AND ugpg.is_active = 1
                      AND pgm.is_active = 1;
                END IF;
            END;

            IF v_has_access = FALSE THEN
                SELECT
                    v_key_id as id, p_public_id as public_id, v_owner_user_id as owner_user_id,
                    v_project_id as project_id, v_is_active as is_active, v_expires_at as expires_at,
                    v_secret_hash as secret_hash, v_hash_algorithm as hash_algorithm,
                    'no_project_access' as validation_status;
            ELSE
                -- Update last_used_at
                UPDATE user_project_api_keys SET last_used_at = NOW() WHERE id = v_key_id;

                -- Return key metadata + owner info for app-layer hash comparison
                SELECT
                    v_key_id as id, p_public_id as public_id, v_owner_user_id as owner_user_id,
                    v_project_id as project_id, v_is_active as is_active, v_expires_at as expires_at,
                    v_secret_hash as secret_hash, v_hash_algorithm as hash_algorithm,
                    'valid' as validation_status;
            END IF;
        END IF;
    END IF;
END$$

-- ===================================================================================
-- 3. SP_REVOKE_API_KEY
-- Soft-revokes an active API key
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_revoke_api_key$$
CREATE PROCEDURE sp_revoke_api_key(
    IN p_key_id VARCHAR(64),
    IN p_revoked_by VARCHAR(64),
    IN p_revoke_reason VARCHAR(255)
)
BEGIN
    DECLARE v_affected_rows INT DEFAULT 0;

    UPDATE user_project_api_keys
    SET
        is_active = FALSE,
        revoked_at = NOW(),
        revoked_by = p_revoked_by,
        revoke_reason = p_revoke_reason,
        updated_at = NOW()
    WHERE id = p_key_id AND is_active = TRUE;

    SET v_affected_rows = ROW_COUNT();

    IF v_affected_rows = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'API key is already revoked or does not exist';
    END IF;

    SELECT v_affected_rows as affected_rows;
END$$

-- ===================================================================================
-- 4. SP_LIST_USER_API_KEYS
-- Lists all API keys owned by a user, with project name JOIN, paginated
-- Does NOT return secret_hash
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_list_user_api_keys$$
CREATE PROCEDURE sp_list_user_api_keys(
    IN p_owner_user_id VARCHAR(64),
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    SELECT
        apk.id,
        apk.public_id,
        apk.project_id,
        p.project_name,
        p.project_hash,
        apk.owner_user_id,
        apk.created_by,
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
        apk.revoke_reason,
        apk.created_at,
        apk.updated_at
    FROM user_project_api_keys apk
    JOIN projects p ON apk.project_id = p.id
    WHERE apk.owner_user_id = p_owner_user_id
    ORDER BY apk.created_at DESC
    LIMIT p_limit OFFSET p_offset;

    -- Return total count for pagination
    SELECT COUNT(*) as total_count
    FROM user_project_api_keys
    WHERE owner_user_id = p_owner_user_id;
END$$

-- ===================================================================================
-- 5. SP_LIST_PROJECT_API_KEYS
-- Lists all API keys scoped to a project, with owner username JOIN, paginated
-- Does NOT return secret_hash
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_list_project_api_keys$$
CREATE PROCEDURE sp_list_project_api_keys(
    IN p_project_id VARCHAR(64),
    IN p_limit INT,
    IN p_offset INT,
    IN p_active_only BOOLEAN
)
BEGIN
    SELECT
        apk.id,
        apk.public_id,
        apk.project_id,
        p.project_name,
        p.project_hash,
        apk.owner_user_id,
        u.username as owner_username,
        u.user_hash as owner_user_hash,
        apk.created_by,
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
        apk.revoke_reason,
        apk.created_at,
        apk.updated_at
    FROM user_project_api_keys apk
    JOIN projects p ON apk.project_id = p.id
    JOIN users u ON apk.owner_user_id = u.id
    WHERE apk.project_id = p_project_id
      AND (p_active_only = FALSE OR apk.is_active = TRUE)
    ORDER BY apk.created_at DESC
    LIMIT p_limit OFFSET p_offset;

    -- Return total count for pagination
    SELECT COUNT(*) as total_count
    FROM user_project_api_keys
    WHERE project_id = p_project_id
      AND (p_active_only = FALSE OR is_active = TRUE);
END$$

-- ===================================================================================
-- 6. SP_UPDATE_API_KEY
-- COALESCE-based UPDATE for name/description/expires_at
-- Handles reactivation: if expires_at extended past NOW() and was expired, set is_active=TRUE
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_update_api_key$$
CREATE PROCEDURE sp_update_api_key(
    IN p_key_id VARCHAR(64),
    IN p_name VARCHAR(100),
    IN p_description TEXT,
    IN p_expires_at DATETIME
)
BEGIN
    DECLARE v_old_expires_at DATETIME;
    DECLARE v_was_expired BOOLEAN DEFAULT FALSE;
    DECLARE v_reactivated BOOLEAN DEFAULT FALSE;

    -- Get current expires_at to check for reactivation
    SELECT expires_at, (expires_at IS NOT NULL AND expires_at < NOW() AND is_active = FALSE)
    INTO v_old_expires_at, v_was_expired
    FROM user_project_api_keys
    WHERE id = p_key_id;

    IF v_old_expires_at IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'API key not found';
    END IF;

    -- Check if this update would reactivate an expired key
    IF v_was_expired = TRUE AND p_expires_at IS NOT NULL AND p_expires_at > NOW() THEN
        SET v_reactivated = TRUE;
    END IF;

    -- Perform the update
    UPDATE user_project_api_keys
    SET
        name = COALESCE(p_name, name),
        description = COALESCE(p_description, description),
        expires_at = COALESCE(p_expires_at, expires_at),
        is_active = CASE
            WHEN v_reactivated = TRUE THEN TRUE
            ELSE is_active
        END,
        updated_at = NOW()
    WHERE id = p_key_id;

    -- Return updated key metadata
    SELECT
        id, public_id, project_id, owner_user_id, created_by,
        name, description, hash_algorithm, fingerprint, secret_last4,
        is_active, expires_at, last_used_at, revoked_at, revoked_by,
        revoke_reason, created_at, updated_at
    FROM user_project_api_keys
    WHERE id = p_key_id;
END$$

-- ===================================================================================
-- 7. SP_GET_API_KEY_BY_PREFIX
-- Looks up a key by public_id for admin lookup (no secret_hash)
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_get_api_key_by_prefix$$
CREATE PROCEDURE sp_get_api_key_by_prefix(
    IN p_public_id VARCHAR(16)
)
BEGIN
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
        apk.created_by,
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
        apk.revoke_reason,
        apk.created_at,
        apk.updated_at
    FROM user_project_api_keys apk
    JOIN projects p ON apk.project_id = p.id
    JOIN users u ON apk.owner_user_id = u.id
    WHERE apk.public_id = p_public_id;
END$$

-- ===================================================================================
-- 8. SP_CLEANUP_EXPIRED_API_KEYS
-- Deactivates all keys past their expiration date
-- Returns count of keys deactivated
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_cleanup_expired_api_keys$$
CREATE PROCEDURE sp_cleanup_expired_api_keys()
BEGIN
    UPDATE user_project_api_keys
    SET
        is_active = FALSE,
        updated_at = NOW()
    WHERE expires_at < NOW()
      AND is_active = TRUE
      AND expires_at IS NOT NULL;

    SELECT ROW_COUNT() as deactivated_count;
END$$

DELIMITER ;

-- ===================================================================================
-- API KEY STORED PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'API key stored procedures created!' as status,
       '8 procedures for API key lifecycle management' as details;
