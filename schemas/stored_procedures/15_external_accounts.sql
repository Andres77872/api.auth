-- ===================================================================================
-- External Account Stored Procedures
-- ===================================================================================
-- Consumer external-account identity lifecycle. Generic link/unlink/get/touch
-- procedures accept Google and Patreon provider subjects represented as HMACs and
-- masked snapshots from application code. Google-only auto-create/login procedures
-- remain Google-only because Patreon is entitlement/link authority only and never a
-- local session issuer. Provider token material is never persisted here.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- Resolve a linked Google or Patreon external account to an active local consumer.
-- Application policy decides whether a resolved provider can be used for login;
-- Patreon callers must use this only as link/entitlement authority, never login.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_get_user_by_external_account$$
CREATE PROCEDURE sp_get_user_by_external_account(
    IN p_provider VARCHAR(32),
    IN p_provider_sub_hash BINARY(32)
)
BEGIN
    IF p_provider NOT IN ('google','patreon') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unsupported external account provider';
    END IF;

    IF p_provider_sub_hash IS NULL OR OCTET_LENGTH(p_provider_sub_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject hash must be 32 bytes';
    END IF;

    SELECT
        u.id,
        u.user_hash,
        u.username,
        u.email,
        u.password_hash,
        u.user_type,
        u.role_id,
        u.created_at,
        u.last_login,
        u.updated_at,
        u.is_active,
        ea.id AS external_account_id,
        ea.provider,
        ea.provider_sub_fingerprint,
        ea.provider_email_masked,
        ea.provider_email_verified_at_link,
        ea.status AS external_account_status,
        ea.linked_at,
        ea.last_seen_at
    FROM user_external_accounts ea
    INNER JOIN users u ON u.id = ea.user_id
    WHERE ea.provider = p_provider
      AND ea.provider_sub_hash = p_provider_sub_hash
      AND ea.status = 'linked'
      AND u.user_type = 'consumer'
      AND u.is_active = TRUE
    LIMIT 1;
END$$

-- ===================================================================================
-- Link a Google or Patreon external account to an existing active consumer.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_link_external_account$$
CREATE PROCEDURE sp_link_external_account(
    IN p_external_account_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_provider_sub_hash BINARY(32),
    IN p_provider_sub_fingerprint CHAR(12),
    IN p_provider_email_hash BINARY(32),
    IN p_provider_email_masked VARCHAR(255),
    IN p_provider_email_verified_at_link BOOLEAN,
    IN p_linked_by VARCHAR(64),
    IN p_metadata JSON
)
BEGIN
    DECLARE v_user_is_consumer INT DEFAULT 0;
    DECLARE v_existing_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_existing_user_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_existing_user_provider_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_existing_user_provider_hash BINARY(32) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF p_provider NOT IN ('google','patreon') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unsupported external account provider';
    END IF;

    IF p_provider_sub_hash IS NULL OR OCTET_LENGTH(p_provider_sub_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject hash must be 32 bytes';
    END IF;

    IF p_provider_sub_fingerprint IS NULL OR CHAR_LENGTH(p_provider_sub_fingerprint) <> 12 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account fingerprint must be 12 characters';
    END IF;

    START TRANSACTION;

    SELECT COUNT(*) INTO v_user_is_consumer
    FROM users
    WHERE id = p_user_id
      AND user_type = 'consumer'
      AND is_active = TRUE;

    IF v_user_is_consumer = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account link target is not an active consumer';
    END IF;

    SELECT id, user_id
      INTO v_existing_id, v_existing_user_id
    FROM user_external_accounts
    WHERE provider = p_provider
      AND provider_sub_hash = p_provider_sub_hash
      AND status = 'linked'
    LIMIT 1
    FOR UPDATE;

    IF v_existing_id IS NOT NULL AND v_existing_user_id <> p_user_id THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject is already linked';
    END IF;

    SELECT id, provider_sub_hash
      INTO v_existing_user_provider_id, v_existing_user_provider_hash
    FROM user_external_accounts
    WHERE user_id = p_user_id
      AND provider = p_provider
      AND status = 'linked'
    LIMIT 1
    FOR UPDATE;

    IF v_existing_user_provider_id IS NOT NULL
       AND v_existing_user_provider_hash <> p_provider_sub_hash THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'User already has an active external account for this provider';
    END IF;

    IF v_existing_id IS NOT NULL THEN
        UPDATE user_external_accounts
        SET provider_sub_fingerprint = p_provider_sub_fingerprint,
            provider_email_hash = p_provider_email_hash,
            provider_email_masked = p_provider_email_masked,
            provider_email_verified_at_link = COALESCE(p_provider_email_verified_at_link, FALSE),
            last_seen_at = COALESCE(last_seen_at, NOW()),
            metadata = COALESCE(p_metadata, metadata)
        WHERE id = v_existing_id;
    ELSE
        INSERT INTO user_external_accounts (
            id, user_id, provider, provider_sub_hash, provider_sub_fingerprint,
            provider_email_hash, provider_email_masked,
            provider_email_verified_at_link, status, linked_at, linked_by,
            metadata
        ) VALUES (
            p_external_account_id, p_user_id, p_provider, p_provider_sub_hash,
            p_provider_sub_fingerprint, p_provider_email_hash, p_provider_email_masked,
            COALESCE(p_provider_email_verified_at_link, FALSE), 'linked', NOW(),
            p_linked_by, p_metadata
        );
        SET v_existing_id = p_external_account_id;
    END IF;

    COMMIT;

    SELECT
        id,
        user_id,
        provider,
        provider_sub_fingerprint,
        provider_email_masked,
        provider_email_verified_at_link,
        status,
        linked_at,
        last_seen_at,
        unlinked_at
    FROM user_external_accounts
    WHERE id = v_existing_id;
END$$

-- ===================================================================================
-- Soft-unlink a user's active Google or Patreon external account.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_unlink_external_account$$
CREATE PROCEDURE sp_unlink_external_account(
    IN p_user_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_unlinked_by VARCHAR(64),
    IN p_reason VARCHAR(64)
)
BEGIN
    IF p_provider NOT IN ('google','patreon') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unsupported external account provider';
    END IF;

    UPDATE user_external_accounts
    SET status = 'unlinked',
        unlinked_at = NOW(),
        unlinked_by = p_unlinked_by,
        unlink_reason = COALESCE(NULLIF(TRIM(p_reason), ''), 'user_requested')
    WHERE user_id = p_user_id
      AND provider = p_provider
      AND status = 'linked';

    IF ROW_COUNT() = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account is not linked';
    END IF;

    SELECT ROW_COUNT() AS affected_rows;
END$$

-- ===================================================================================
-- Refresh last-seen and masked snapshots after a provider observation.
-- For Patreon this is sync/webhook/link evidence only, never login authority.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_touch_external_account_last_seen$$
CREATE PROCEDURE sp_touch_external_account_last_seen(
    IN p_provider VARCHAR(32),
    IN p_provider_sub_hash BINARY(32),
    IN p_provider_email_hash BINARY(32),
    IN p_provider_email_masked VARCHAR(255),
    IN p_provider_email_verified_at_link BOOLEAN
)
BEGIN
    IF p_provider NOT IN ('google','patreon') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unsupported external account provider';
    END IF;

    IF p_provider_sub_hash IS NULL OR OCTET_LENGTH(p_provider_sub_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject hash must be 32 bytes';
    END IF;

    UPDATE user_external_accounts
    SET last_seen_at = NOW(),
        provider_email_hash = COALESCE(p_provider_email_hash, provider_email_hash),
        provider_email_masked = COALESCE(p_provider_email_masked, provider_email_masked),
        provider_email_verified_at_link = COALESCE(p_provider_email_verified_at_link, provider_email_verified_at_link)
    WHERE provider = p_provider
      AND provider_sub_hash = p_provider_sub_hash
      AND status = 'linked';

    SELECT ROW_COUNT() AS affected_rows;
END$$

-- ===================================================================================
-- Create a local consumer and link the external account in one transaction.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_create_consumer_user_from_external_account$$
CREATE PROCEDURE sp_create_consumer_user_from_external_account(
    IN p_user_id VARCHAR(64),
    IN p_user_hash VARCHAR(255),
    IN p_username VARCHAR(100),
    IN p_password_hash VARCHAR(255),
    IN p_external_account_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_provider_sub_hash BINARY(32),
    IN p_provider_sub_fingerprint CHAR(12),
    IN p_provider_email_hash BINARY(32),
    IN p_provider_email_masked VARCHAR(255),
    IN p_provider_email_verified_at_link BOOLEAN,
    IN p_user_email_id VARCHAR(64),
    IN p_email_normalized VARCHAR(255),
    IN p_group_member_id VARCHAR(64),
    IN p_user_group_id VARCHAR(64),
    IN p_created_by VARCHAR(64),
    IN p_metadata JSON
)
BEGIN
    DECLARE v_existing_external_count INT DEFAULT 0;
    DECLARE v_group_member_id VARCHAR(64);

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF p_provider <> 'google' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unsupported external account provider';
    END IF;

    IF p_provider_sub_hash IS NULL OR OCTET_LENGTH(p_provider_sub_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject hash must be 32 bytes';
    END IF;

    IF p_provider_sub_fingerprint IS NULL OR CHAR_LENGTH(p_provider_sub_fingerprint) <> 12 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account fingerprint must be 12 characters';
    END IF;

    START TRANSACTION;

    SELECT COUNT(*) INTO v_existing_external_count
    FROM user_external_accounts
    WHERE provider = p_provider
      AND provider_sub_hash = p_provider_sub_hash
      AND status = 'linked'
    FOR UPDATE;

    IF v_existing_external_count > 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject is already linked';
    END IF;

    IF p_user_group_id IS NOT NULL
       AND NOT EXISTS (SELECT 1 FROM user_groups WHERE id = p_user_group_id AND is_active = TRUE) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Provider-bound user group is not active';
    END IF;

    INSERT INTO users (
        id, user_hash, username, email, password_hash, user_type, created_by, created_at
    ) VALUES (
        p_user_id, p_user_hash, p_username, NULL, p_password_hash, 'consumer', p_created_by, NOW()
    );

    IF p_user_email_id IS NOT NULL
       AND p_email_normalized IS NOT NULL
       AND p_provider_email_hash IS NOT NULL
       AND p_provider_email_masked IS NOT NULL THEN
        INSERT INTO user_emails (
            id, user_id, email_normalized, email_hash, email_masked,
            status, is_primary, added_at, created_by, updated_at
        ) VALUES (
            p_user_email_id, p_user_id, LOWER(TRIM(p_email_normalized)),
            p_provider_email_hash, p_provider_email_masked,
            'pending', FALSE, NOW(), p_created_by, NOW()
        );
    END IF;

    IF p_user_group_id IS NOT NULL THEN
        SET v_group_member_id = COALESCE(p_group_member_id, CONCAT('ugm-', REPLACE(UUID(), '-', '')));
        INSERT INTO user_group_members (
            id, user_id, user_group_id, assigned_at, assigned_by, is_active
        ) VALUES (
            v_group_member_id, p_user_id, p_user_group_id, NOW(), p_created_by, TRUE
        ) ON DUPLICATE KEY UPDATE
            is_active = TRUE,
            assigned_at = NOW(),
            assigned_by = p_created_by,
            removed_at = NULL,
            removed_by = NULL;
    END IF;

    INSERT INTO user_external_accounts (
        id, user_id, provider, provider_sub_hash, provider_sub_fingerprint,
        provider_email_hash, provider_email_masked,
        provider_email_verified_at_link, status, linked_at, linked_by,
        metadata
    ) VALUES (
        p_external_account_id, p_user_id, p_provider, p_provider_sub_hash,
        p_provider_sub_fingerprint, p_provider_email_hash, p_provider_email_masked,
        COALESCE(p_provider_email_verified_at_link, FALSE), 'linked', NOW(),
        p_created_by, p_metadata
    );

    COMMIT;

    SELECT
        u.id,
        u.user_hash,
        u.username,
        u.email,
        u.password_hash,
        u.user_type,
        u.role_id,
        u.created_at,
        u.last_login,
        u.updated_at,
        u.is_active,
        ea.id AS external_account_id,
        ea.provider,
        ea.provider_sub_fingerprint,
        ea.provider_email_masked,
        ea.provider_email_verified_at_link,
        ea.status AS external_account_status,
        ea.linked_at,
        ea.last_seen_at,
        p_user_group_id AS assigned_user_group_id
    FROM users u
    INNER JOIN user_external_accounts ea ON ea.user_id = u.id
    WHERE u.id = p_user_id
      AND ea.id = p_external_account_id;
END$$

DELIMITER ;

SELECT 'External account stored procedures created successfully!' AS status,
       '5 procedures created; generic link/unlink/get/touch support google|patreon while auto-create remains Google-only' AS details;
