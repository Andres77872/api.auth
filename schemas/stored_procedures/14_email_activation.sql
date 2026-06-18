-- ===================================================================================
-- EMAIL ACTIVATION AND TRANSACTIONAL AUTH EMAIL STORED PROCEDURES
-- ===================================================================================
-- State transitions for authoritative user email lifecycle, hash-only link tokens,
-- durable outbox delivery, provider webhooks, and durable idempotency.
--
-- Security posture:
-- - Link token secrets are never accepted or stored by these procedures.
-- - Callers pass lookup_id plus a BINARY(32) HMAC token_hash computed in app code.
-- - The legacy plaintext password-reset storage pattern is intentionally not reused.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- sp_user_email_add_and_enqueue
-- Adds/reuses a pending user_emails row, creates a hash-only activation token, and
-- enqueues an activation email in one transaction.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_user_email_add_and_enqueue$$
CREATE PROCEDURE sp_user_email_add_and_enqueue(
    IN p_user_email_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_email_normalized VARCHAR(255),
    IN p_email_hash BINARY(32),
    IN p_email_masked VARCHAR(255),
    IN p_token_id VARCHAR(64),
    IN p_lookup_id VARCHAR(32),
    IN p_token_hash BINARY(32),
    IN p_token_fingerprint CHAR(12),
    IN p_token_expires_at DATETIME,
    IN p_email_message_id VARCHAR(64),
    IN p_provider VARCHAR(50),
    IN p_provider_idempotency_key VARCHAR(128),
    IN p_render_payload_ciphertext LONGBLOB,
    IN p_created_by VARCHAR(64),
    IN p_created_ip_hash BINARY(32),
    IN p_idempotency_id VARCHAR(64),
    IN p_idempotency_scope VARCHAR(128),
    IN p_idempotency_key_hash BINARY(32),
    IN p_idempotency_request_hash BINARY(32),
    IN p_idempotency_expires_at DATETIME
)
BEGIN
    DECLARE v_email_normalized VARCHAR(255);
    DECLARE v_active_count INT DEFAULT 0;
    DECLARE v_existing_email_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_existing_status VARCHAR(32) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    SET v_email_normalized = LOWER(TRIM(p_email_normalized));

    START TRANSACTION;

    IF NOT EXISTS (SELECT 1 FROM users WHERE id = p_user_id AND is_active = TRUE) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'User does not exist or is inactive';
    END IF;

    SELECT id, status
      INTO v_existing_email_id, v_existing_status
    FROM user_emails
    WHERE user_id = p_user_id
      AND email_normalized = v_email_normalized
      AND removed_at IS NULL
      AND status IN ('pending','activated','suppressed')
    ORDER BY added_at ASC
    LIMIT 1
    FOR UPDATE;

    IF v_existing_email_id IS NULL THEN
        SELECT COUNT(*) INTO v_active_count
        FROM user_emails
        WHERE user_id = p_user_id
          AND removed_at IS NULL
          AND status IN ('pending','activated');

        IF v_active_count >= 5 THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'User cannot have more than five active email rows';
        END IF;

        INSERT INTO user_emails (
            id, user_id, email_normalized, email_hash, email_masked,
            status, is_primary, added_at, created_by, updated_at
        ) VALUES (
            p_user_email_id, p_user_id, v_email_normalized, p_email_hash, p_email_masked,
            'pending', FALSE, NOW(), p_created_by, NOW()
        );

        SET v_existing_email_id = p_user_email_id;
        SET v_existing_status = 'pending';
    ELSE
        UPDATE user_emails
        SET email_hash = p_email_hash,
            email_masked = p_email_masked,
            updated_at = NOW()
        WHERE id = v_existing_email_id;
    END IF;

    IF v_existing_status = 'activated' THEN
        COMMIT;
        SELECT v_existing_email_id AS user_email_id,
               NULL AS token_id,
               NULL AS email_message_id,
               'already_activated' AS lifecycle_status;
    ELSEIF v_existing_status = 'suppressed' THEN
        COMMIT;
        SELECT v_existing_email_id AS user_email_id,
               NULL AS token_id,
               NULL AS email_message_id,
               'suppressed' AS lifecycle_status;
    ELSE
        UPDATE user_email_link_tokens
        SET revoked_at = NOW(),
            revocation_reason = 'replaced_by_new_activation'
        WHERE user_email_id = v_existing_email_id
          AND purpose = 'email_activation'
          AND consumed_at IS NULL
          AND revoked_at IS NULL;

        INSERT INTO user_email_link_tokens (
            id, user_id, user_email_id, purpose, lookup_id, token_hash,
            token_fingerprint, expires_at, created_at, created_ip_hash
        ) VALUES (
            p_token_id, p_user_id, v_existing_email_id, 'email_activation', p_lookup_id, p_token_hash,
            p_token_fingerprint, p_token_expires_at, NOW(), p_created_ip_hash
        );

        INSERT INTO email_messages (
            id, user_id, user_email_id, token_id, purpose, template_code,
            recipient_email, recipient_hash, recipient_masked, provider,
            provider_idempotency_key, status, priority, attempt_count, max_attempts,
            next_attempt_at, render_payload_ciphertext, payload_purge_at, created_at, updated_at
        ) VALUES (
            p_email_message_id, p_user_id, v_existing_email_id, p_token_id, 'email_activation', 'email_activation',
            v_email_normalized, p_email_hash, p_email_masked, COALESCE(p_provider, 'resend'),
            p_provider_idempotency_key, 'pending', 5, 0, 8,
            NOW(), p_render_payload_ciphertext, DATE_ADD(NOW(), INTERVAL 30 DAY), NOW(), NOW()
        );

        UPDATE user_emails
        SET last_activation_sent_at = NOW(), updated_at = NOW()
        WHERE id = v_existing_email_id;

        IF p_idempotency_id IS NOT NULL AND p_idempotency_key_hash IS NOT NULL THEN
            INSERT INTO email_idempotency_keys (
                id, scope, key_hash, request_hash, user_id, recipient_hash,
                email_message_id, status, replay_status_code, replay_body,
                expires_at, created_at, completed_at
            ) VALUES (
                p_idempotency_id, p_idempotency_scope, p_idempotency_key_hash, p_idempotency_request_hash,
                p_user_id, p_email_hash, p_email_message_id, 'complete', 202,
                JSON_OBJECT('success', TRUE, 'message', 'If the request can be processed, it has been accepted.'),
                p_idempotency_expires_at, NOW(), NOW()
            ) ON DUPLICATE KEY UPDATE
                email_message_id = VALUES(email_message_id),
                status = 'complete',
                replay_status_code = 202,
                replay_body = VALUES(replay_body),
                completed_at = NOW();
        END IF;

        COMMIT;
        SELECT v_existing_email_id AS user_email_id,
               p_token_id AS token_id,
               p_email_message_id AS email_message_id,
               'activation_enqueued' AS lifecycle_status;
    END IF;
END$$

-- ===================================================================================
-- sp_user_email_resend_and_enqueue
-- Revokes previous pending activation tokens for an owned pending email row and enqueues
-- a new activation email.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_user_email_resend_and_enqueue$$
CREATE PROCEDURE sp_user_email_resend_and_enqueue(
    IN p_user_id VARCHAR(64),
    IN p_user_email_id VARCHAR(64),
    IN p_token_id VARCHAR(64),
    IN p_lookup_id VARCHAR(32),
    IN p_token_hash BINARY(32),
    IN p_token_fingerprint CHAR(12),
    IN p_token_expires_at DATETIME,
    IN p_email_message_id VARCHAR(64),
    IN p_provider VARCHAR(50),
    IN p_provider_idempotency_key VARCHAR(128),
    IN p_render_payload_ciphertext LONGBLOB,
    IN p_created_ip_hash BINARY(32),
    IN p_idempotency_id VARCHAR(64),
    IN p_idempotency_scope VARCHAR(128),
    IN p_idempotency_key_hash BINARY(32),
    IN p_idempotency_request_hash BINARY(32),
    IN p_idempotency_expires_at DATETIME,
    IN p_cooldown_seconds INT
)
BEGIN
    DECLARE v_email_normalized VARCHAR(255);
    DECLARE v_email_hash BINARY(32);
    DECLARE v_email_masked VARCHAR(255);
    DECLARE v_status VARCHAR(32);
    DECLARE v_last_sent DATETIME DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT email_normalized, email_hash, email_masked, status, last_activation_sent_at
      INTO v_email_normalized, v_email_hash, v_email_masked, v_status, v_last_sent
    FROM user_emails
    WHERE id = p_user_email_id
      AND user_id = p_user_id
      AND removed_at IS NULL
    LIMIT 1
    FOR UPDATE;

    IF v_email_normalized IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Email row does not exist for user';
    END IF;

    IF v_status <> 'pending' THEN
        COMMIT;
        SELECT p_user_email_id AS user_email_id,
               NULL AS token_id,
               NULL AS email_message_id,
               v_status AS lifecycle_status;
    ELSEIF p_cooldown_seconds IS NOT NULL
           AND p_cooldown_seconds > 0
           AND v_last_sent IS NOT NULL
           AND v_last_sent > DATE_SUB(NOW(), INTERVAL p_cooldown_seconds SECOND) THEN
        -- Defense-in-depth cooldown behind the route-level Redis check: refuse a
        -- resend within the cooldown window without minting/enqueuing anything.
        COMMIT;
        SELECT p_user_email_id AS user_email_id,
               NULL AS token_id,
               NULL AS email_message_id,
               'cooldown' AS lifecycle_status;
    ELSE
        UPDATE user_email_link_tokens
        SET revoked_at = NOW(),
            revocation_reason = 'replaced_by_resend'
        WHERE user_email_id = p_user_email_id
          AND purpose = 'email_activation'
          AND consumed_at IS NULL
          AND revoked_at IS NULL;

        INSERT INTO user_email_link_tokens (
            id, user_id, user_email_id, purpose, lookup_id, token_hash,
            token_fingerprint, expires_at, created_at, created_ip_hash
        ) VALUES (
            p_token_id, p_user_id, p_user_email_id, 'email_activation', p_lookup_id, p_token_hash,
            p_token_fingerprint, p_token_expires_at, NOW(), p_created_ip_hash
        );

        INSERT INTO email_messages (
            id, user_id, user_email_id, token_id, purpose, template_code,
            recipient_email, recipient_hash, recipient_masked, provider,
            provider_idempotency_key, status, priority, attempt_count, max_attempts,
            next_attempt_at, render_payload_ciphertext, payload_purge_at, created_at, updated_at
        ) VALUES (
            p_email_message_id, p_user_id, p_user_email_id, p_token_id, 'email_activation', 'email_activation',
            v_email_normalized, v_email_hash, v_email_masked, COALESCE(p_provider, 'resend'),
            p_provider_idempotency_key, 'pending', 5, 0, 8,
            NOW(), p_render_payload_ciphertext, DATE_ADD(NOW(), INTERVAL 30 DAY), NOW(), NOW()
        );

        UPDATE user_emails
        SET last_activation_sent_at = NOW(), updated_at = NOW()
        WHERE id = p_user_email_id;

        IF p_idempotency_id IS NOT NULL AND p_idempotency_key_hash IS NOT NULL THEN
            INSERT INTO email_idempotency_keys (
                id, scope, key_hash, request_hash, user_id, recipient_hash,
                email_message_id, status, replay_status_code, replay_body,
                expires_at, created_at, completed_at
            ) VALUES (
                p_idempotency_id, p_idempotency_scope, p_idempotency_key_hash, p_idempotency_request_hash,
                p_user_id, v_email_hash, p_email_message_id, 'complete', 202,
                JSON_OBJECT('success', TRUE, 'message', 'If the request can be processed, it has been accepted.'),
                p_idempotency_expires_at, NOW(), NOW()
            ) ON DUPLICATE KEY UPDATE
                email_message_id = VALUES(email_message_id),
                status = 'complete',
                replay_status_code = 202,
                replay_body = VALUES(replay_body),
                completed_at = NOW();
        END IF;

        COMMIT;
        SELECT p_user_email_id AS user_email_id,
               p_token_id AS token_id,
               p_email_message_id AS email_message_id,
               'activation_resent' AS lifecycle_status;
    END IF;
END$$

-- ===================================================================================
-- sp_consume_email_activation_token
-- Atomically consumes one hash-only activation token and activates the email if no
-- global active-activated conflict exists.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_consume_email_activation_token$$
CREATE PROCEDURE sp_consume_email_activation_token(
    IN p_lookup_id VARCHAR(32),
    IN p_token_hash BINARY(32),
    IN p_consumed_ip_hash BINARY(32),
    IN p_consumed_user_agent_hash BINARY(32)
)
BEGIN
    DECLARE v_token_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_user_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_user_email_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_stored_hash BINARY(32) DEFAULT NULL;
    DECLARE v_expires_at DATETIME DEFAULT NULL;
    DECLARE v_consumed_at DATETIME DEFAULT NULL;
    DECLARE v_revoked_at DATETIME DEFAULT NULL;
    DECLARE v_email_normalized VARCHAR(255) DEFAULT NULL;
    DECLARE v_conflict_count INT DEFAULT 0;
    DECLARE v_existing_primary_count INT DEFAULT 0;
    DECLARE v_identity_changed BOOLEAN DEFAULT FALSE;
    DECLARE v_result VARCHAR(64) DEFAULT 'not_found';

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT id, user_id, user_email_id, token_hash, expires_at, consumed_at, revoked_at
      INTO v_token_id, v_user_id, v_user_email_id, v_stored_hash, v_expires_at, v_consumed_at, v_revoked_at
    FROM user_email_link_tokens
    WHERE lookup_id = p_lookup_id
      AND purpose = 'email_activation'
    LIMIT 1
    FOR UPDATE;

    IF v_token_id IS NULL THEN
        SET v_result = 'not_found';
    ELSEIF v_stored_hash <> p_token_hash THEN
        SET v_result = 'invalid';
    ELSEIF v_consumed_at IS NOT NULL THEN
        SET v_result = 'already_consumed';
    ELSEIF v_revoked_at IS NOT NULL THEN
        SET v_result = 'revoked';
    ELSEIF v_expires_at <= NOW() THEN
        UPDATE user_email_link_tokens
        SET revoked_at = NOW(), revocation_reason = 'expired'
        WHERE id = v_token_id;
        SET v_result = 'expired';
    ELSE
        SELECT email_normalized
          INTO v_email_normalized
        FROM user_emails
        WHERE id = v_user_email_id
          AND user_id = v_user_id
          AND removed_at IS NULL
          AND status = 'pending'
        LIMIT 1
        FOR UPDATE;

        IF v_email_normalized IS NULL THEN
            UPDATE user_email_link_tokens
            SET consumed_at = NOW(),
                consumed_ip_hash = p_consumed_ip_hash,
                consumed_user_agent_hash = p_consumed_user_agent_hash,
                revocation_reason = 'email_not_pending'
            WHERE id = v_token_id;
            SET v_result = 'email_not_pending';
        ELSE
            -- FOR UPDATE serializes concurrent activations of the same address.
            -- The uk_user_emails_active_activated_email VIRTUAL unique index is
            -- the authoritative guard; this lock turns a would-be duplicate-key
            -- rollback into the clean 'activation_conflict' result below.
            SELECT COUNT(*) INTO v_conflict_count
            FROM user_emails
            WHERE email_normalized = v_email_normalized
              AND status = 'activated'
              AND removed_at IS NULL
              AND id <> v_user_email_id
            FOR UPDATE;

            UPDATE user_email_link_tokens
            SET consumed_at = NOW(),
                consumed_ip_hash = p_consumed_ip_hash,
                consumed_user_agent_hash = p_consumed_user_agent_hash,
                revocation_reason = CASE WHEN v_conflict_count > 0 THEN 'activation_conflict' ELSE revocation_reason END
            WHERE id = v_token_id;

            IF v_conflict_count > 0 THEN
                SET v_result = 'activation_conflict';
            ELSE
                SELECT COUNT(*) INTO v_existing_primary_count
                FROM user_emails
                WHERE user_id = v_user_id
                  AND status = 'activated'
                  AND removed_at IS NULL
                  AND is_primary = TRUE
                FOR UPDATE;

                UPDATE user_emails
                SET status = 'activated',
                    activated_at = COALESCE(activated_at, NOW()),
                    is_primary = CASE WHEN v_existing_primary_count = 0 THEN TRUE ELSE is_primary END,
                    updated_at = NOW()
                WHERE id = v_user_email_id;

                IF v_existing_primary_count = 0 THEN
                    UPDATE users
                    SET email = v_email_normalized, updated_at = NOW()
                    WHERE id = v_user_id;
                END IF;

                SET v_identity_changed = TRUE;
                SET v_result = 'activated';
            END IF;
        END IF;
    END IF;

    COMMIT;
    SELECT v_result AS consume_status,
           v_user_id AS user_id,
           v_user_email_id AS user_email_id,
           v_identity_changed AS identity_changed;
END$$

-- ===================================================================================
-- sp_user_email_remove
-- Marks an owned email removed, revokes pending activation tokens, and safely updates
-- primary/shadow state.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_user_email_remove$$
CREATE PROCEDURE sp_user_email_remove(
    IN p_user_id VARCHAR(64),
    IN p_user_email_id VARCHAR(64),
    IN p_removed_by VARCHAR(64)
)
BEGIN
    DECLARE v_is_primary BOOLEAN DEFAULT FALSE;
    DECLARE v_status VARCHAR(32) DEFAULT NULL;
    DECLARE v_next_primary_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_next_primary_email VARCHAR(255) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT is_primary, status
      INTO v_is_primary, v_status
    FROM user_emails
    WHERE id = p_user_email_id
      AND user_id = p_user_id
      AND removed_at IS NULL
    LIMIT 1
    FOR UPDATE;

    IF v_status IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Email row does not exist for user';
    END IF;

    UPDATE user_emails
    SET status = 'removed',
        is_primary = FALSE,
        removed_at = NOW(),
        updated_at = NOW()
    WHERE id = p_user_email_id;

    UPDATE user_email_link_tokens
    SET revoked_at = NOW(),
        revocation_reason = 'email_removed'
    WHERE user_email_id = p_user_email_id
      AND consumed_at IS NULL
      AND revoked_at IS NULL;

    IF v_is_primary = TRUE THEN
        SELECT id, email_normalized
          INTO v_next_primary_id, v_next_primary_email
        FROM user_emails
        WHERE user_id = p_user_id
          AND status = 'activated'
          AND removed_at IS NULL
        ORDER BY activated_at ASC, added_at ASC
        LIMIT 1
        FOR UPDATE;

        IF v_next_primary_id IS NOT NULL THEN
            UPDATE user_emails
            SET is_primary = TRUE, updated_at = NOW()
            WHERE id = v_next_primary_id;

            UPDATE users
            SET email = v_next_primary_email, updated_at = NOW()
            WHERE id = p_user_id;
        ELSE
            UPDATE users
            SET email = NULL, updated_at = NOW()
            WHERE id = p_user_id;
        END IF;
    END IF;

    COMMIT;
    SELECT p_user_email_id AS user_email_id,
           v_next_primary_id AS new_primary_email_id,
           'removed' AS lifecycle_status;
END$$

-- ===================================================================================
-- sp_user_email_set_primary
-- Switches primary to an owned active activated email and syncs users.email shadow.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_user_email_set_primary$$
CREATE PROCEDURE sp_user_email_set_primary(
    IN p_user_id VARCHAR(64),
    IN p_user_email_id VARCHAR(64)
)
BEGIN
    DECLARE v_email_normalized VARCHAR(255) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT email_normalized
      INTO v_email_normalized
    FROM user_emails
    WHERE id = p_user_email_id
      AND user_id = p_user_id
      AND status = 'activated'
      AND removed_at IS NULL
    LIMIT 1
    FOR UPDATE;

    IF v_email_normalized IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Primary email must be an active activated email owned by the user';
    END IF;

    UPDATE user_emails
    SET is_primary = FALSE, updated_at = NOW()
    WHERE user_id = p_user_id
      AND removed_at IS NULL
      AND is_primary = TRUE;

    UPDATE user_emails
    SET is_primary = TRUE, updated_at = NOW()
    WHERE id = p_user_email_id;

    UPDATE users
    SET email = v_email_normalized, updated_at = NOW()
    WHERE id = p_user_id;

    COMMIT;
    SELECT p_user_email_id AS user_email_id,
           v_email_normalized AS email_normalized,
           'primary_changed' AS lifecycle_status;
END$$

-- ===================================================================================
-- sp_user_email_list_for_user
-- Authenticated owner list of non-removed email states.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_user_email_list_for_user$$
CREATE PROCEDURE sp_user_email_list_for_user(
    IN p_user_id VARCHAR(64)
)
BEGIN
    SELECT id,
           email_normalized,
           email_masked,
           status,
           is_primary,
           added_at,
           activated_at,
           removed_at,
           last_activation_sent_at,
           updated_at
    FROM user_emails
    WHERE user_id = p_user_id
      AND removed_at IS NULL
    ORDER BY is_primary DESC, added_at ASC;
END$$

-- ===================================================================================
-- sp_admin_user_email_list
-- Admin/root masked/hash list for a target user. Does not return plaintext full email.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_admin_user_email_list$$
CREATE PROCEDURE sp_admin_user_email_list(
    IN p_target_user_id VARCHAR(64)
)
BEGIN
    SELECT id,
           user_id,
           HEX(email_hash) AS email_hash,
           email_masked,
           status,
           is_primary,
           added_at,
           activated_at,
           removed_at,
           last_activation_sent_at,
           updated_at
    FROM user_emails
    WHERE user_id = p_target_user_id
    ORDER BY removed_at IS NULL DESC, is_primary DESC, added_at ASC;
END$$

-- ===================================================================================
-- sp_password_reset_link_enqueue
-- Self-service forgot-password: generic public posture. If an active activated email or
-- username resolves to a recipient, creates a hash-only reset token and outbox message.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_password_reset_link_enqueue$$
CREATE PROCEDURE sp_password_reset_link_enqueue(
    IN p_identifier VARCHAR(255),
    IN p_token_id VARCHAR(64),
    IN p_lookup_id VARCHAR(32),
    IN p_token_hash BINARY(32),
    IN p_token_fingerprint CHAR(12),
    IN p_token_expires_at DATETIME,
    IN p_email_message_id VARCHAR(64),
    IN p_provider VARCHAR(50),
    IN p_provider_idempotency_key VARCHAR(128),
    IN p_render_payload_ciphertext LONGBLOB,
    IN p_created_ip_hash BINARY(32),
    IN p_idempotency_id VARCHAR(64),
    IN p_idempotency_scope VARCHAR(128),
    IN p_idempotency_key_hash BINARY(32),
    IN p_idempotency_request_hash BINARY(32),
    IN p_idempotency_expires_at DATETIME
)
BEGIN
    DECLARE v_identifier_normalized VARCHAR(255);
    DECLARE v_user_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_user_email_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_email_normalized VARCHAR(255) DEFAULT NULL;
    DECLARE v_email_hash BINARY(32) DEFAULT NULL;
    DECLARE v_email_masked VARCHAR(255) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    SET v_identifier_normalized = LOWER(TRIM(p_identifier));

    START TRANSACTION;

    SELECT ue.user_id, ue.id, ue.email_normalized, ue.email_hash, ue.email_masked
      INTO v_user_id, v_user_email_id, v_email_normalized, v_email_hash, v_email_masked
    FROM user_emails ue
    JOIN users u ON u.id = ue.user_id AND u.is_active = TRUE
    WHERE ue.status = 'activated'
      AND ue.removed_at IS NULL
      AND (ue.email_normalized = v_identifier_normalized OR u.username = p_identifier)
    ORDER BY ue.is_primary DESC, ue.activated_at ASC, ue.added_at ASC
    LIMIT 1
    FOR UPDATE;

    IF v_user_id IS NOT NULL THEN
        INSERT INTO user_email_link_tokens (
            id, user_id, user_email_id, purpose, lookup_id, token_hash,
            token_fingerprint, expires_at, created_at, created_ip_hash
        ) VALUES (
            p_token_id, v_user_id, v_user_email_id, 'password_reset', p_lookup_id, p_token_hash,
            p_token_fingerprint, p_token_expires_at, NOW(), p_created_ip_hash
        );

        INSERT INTO email_messages (
            id, user_id, user_email_id, token_id, purpose, template_code,
            recipient_email, recipient_hash, recipient_masked, provider,
            provider_idempotency_key, status, priority, attempt_count, max_attempts,
            next_attempt_at, render_payload_ciphertext, payload_purge_at, created_at, updated_at
        ) VALUES (
            p_email_message_id, v_user_id, v_user_email_id, p_token_id, 'password_reset', 'password_reset',
            v_email_normalized, v_email_hash, v_email_masked, COALESCE(p_provider, 'resend'),
            p_provider_idempotency_key, 'pending', 5, 0, 8,
            NOW(), p_render_payload_ciphertext, DATE_ADD(NOW(), INTERVAL 30 DAY), NOW(), NOW()
        );
    END IF;

    IF p_idempotency_id IS NOT NULL AND p_idempotency_key_hash IS NOT NULL THEN
        INSERT INTO email_idempotency_keys (
            id, scope, key_hash, request_hash, user_id, recipient_hash,
            email_message_id, status, replay_status_code, replay_body,
            expires_at, created_at, completed_at
        ) VALUES (
            p_idempotency_id, p_idempotency_scope, p_idempotency_key_hash, p_idempotency_request_hash,
            v_user_id, v_email_hash, p_email_message_id, 'complete', 202,
            JSON_OBJECT('success', TRUE, 'message', 'If the request can be processed, it has been accepted.'),
            p_idempotency_expires_at, NOW(), NOW()
        ) ON DUPLICATE KEY UPDATE
            email_message_id = VALUES(email_message_id),
            status = 'complete',
            replay_status_code = 202,
            replay_body = VALUES(replay_body),
            completed_at = NOW();
    END IF;

    COMMIT;
    SELECT 'accepted' AS request_status,
           v_user_id AS user_id,
           v_user_email_id AS user_email_id,
           CASE WHEN v_user_id IS NULL THEN NULL ELSE p_email_message_id END AS email_message_id;
END$$

-- ===================================================================================
-- sp_admin_password_reset_link_enqueue
-- Admin/root reset-link enqueue. Does not mutate password and does not return plaintext
-- password, full recipient, or reset link.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_admin_password_reset_link_enqueue$$
CREATE PROCEDURE sp_admin_password_reset_link_enqueue(
    IN p_target_user_id VARCHAR(64),
    IN p_created_by VARCHAR(64),
    IN p_token_id VARCHAR(64),
    IN p_lookup_id VARCHAR(32),
    IN p_token_hash BINARY(32),
    IN p_token_fingerprint CHAR(12),
    IN p_token_expires_at DATETIME,
    IN p_email_message_id VARCHAR(64),
    IN p_provider VARCHAR(50),
    IN p_provider_idempotency_key VARCHAR(128),
    IN p_render_payload_ciphertext LONGBLOB,
    IN p_created_ip_hash BINARY(32)
)
BEGIN
    DECLARE v_user_email_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_email_normalized VARCHAR(255) DEFAULT NULL;
    DECLARE v_email_hash BINARY(32) DEFAULT NULL;
    DECLARE v_email_masked VARCHAR(255) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    IF NOT EXISTS (SELECT 1 FROM users WHERE id = p_target_user_id AND is_active = TRUE) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Target user does not exist or is inactive';
    END IF;

    SELECT id, email_normalized, email_hash, email_masked
      INTO v_user_email_id, v_email_normalized, v_email_hash, v_email_masked
    FROM user_emails
    WHERE user_id = p_target_user_id
      AND status = 'activated'
      AND removed_at IS NULL
    ORDER BY is_primary DESC, activated_at ASC, added_at ASC
    LIMIT 1
    FOR UPDATE;

    IF v_user_email_id IS NOT NULL THEN
        INSERT INTO user_email_link_tokens (
            id, user_id, user_email_id, purpose, lookup_id, token_hash,
            token_fingerprint, expires_at, created_at, created_ip_hash
        ) VALUES (
            p_token_id, p_target_user_id, v_user_email_id, 'admin_password_reset', p_lookup_id, p_token_hash,
            p_token_fingerprint, p_token_expires_at, NOW(), p_created_ip_hash
        );

        INSERT INTO email_messages (
            id, user_id, user_email_id, token_id, purpose, template_code,
            recipient_email, recipient_hash, recipient_masked, provider,
            provider_idempotency_key, status, priority, attempt_count, max_attempts,
            next_attempt_at, render_payload_ciphertext, payload_purge_at, created_at, updated_at
        ) VALUES (
            p_email_message_id, p_target_user_id, v_user_email_id, p_token_id, 'admin_password_reset', 'admin_password_reset',
            v_email_normalized, v_email_hash, v_email_masked, COALESCE(p_provider, 'resend'),
            p_provider_idempotency_key, 'pending', 4, 0, 8,
            NOW(), p_render_payload_ciphertext, DATE_ADD(NOW(), INTERVAL 30 DAY), NOW(), NOW()
        );
    END IF;

    COMMIT;
    SELECT 'accepted' AS request_status,
           p_target_user_id AS target_user_id,
           v_user_email_id AS user_email_id,
           CASE WHEN v_user_email_id IS NULL THEN NULL ELSE p_email_message_id END AS email_message_id;
END$$

-- ===================================================================================
-- sp_consume_password_reset_token
-- Atomically consumes password reset/admin-reset token and updates password hash.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_consume_password_reset_token$$
CREATE PROCEDURE sp_consume_password_reset_token(
    IN p_lookup_id VARCHAR(32),
    IN p_token_hash BINARY(32),
    IN p_new_password_hash VARCHAR(255),
    IN p_consumed_ip_hash BINARY(32),
    IN p_consumed_user_agent_hash BINARY(32)
)
BEGIN
    DECLARE v_token_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_user_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_stored_hash BINARY(32) DEFAULT NULL;
    DECLARE v_expires_at DATETIME DEFAULT NULL;
    DECLARE v_consumed_at DATETIME DEFAULT NULL;
    DECLARE v_revoked_at DATETIME DEFAULT NULL;
    DECLARE v_result VARCHAR(64) DEFAULT 'not_found';
    DECLARE v_password_changed BOOLEAN DEFAULT FALSE;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT id, user_id, token_hash, expires_at, consumed_at, revoked_at
      INTO v_token_id, v_user_id, v_stored_hash, v_expires_at, v_consumed_at, v_revoked_at
    FROM user_email_link_tokens
    WHERE lookup_id = p_lookup_id
      AND purpose IN ('password_reset','admin_password_reset')
    LIMIT 1
    FOR UPDATE;

    IF v_token_id IS NULL THEN
        SET v_result = 'not_found';
    ELSEIF v_stored_hash <> p_token_hash THEN
        SET v_result = 'invalid';
    ELSEIF v_consumed_at IS NOT NULL THEN
        SET v_result = 'already_consumed';
    ELSEIF v_revoked_at IS NOT NULL THEN
        SET v_result = 'revoked';
    ELSEIF v_expires_at <= NOW() THEN
        UPDATE user_email_link_tokens
        SET revoked_at = NOW(), revocation_reason = 'expired'
        WHERE id = v_token_id;
        SET v_result = 'expired';
    ELSE
        UPDATE user_email_link_tokens
        SET consumed_at = NOW(),
            consumed_ip_hash = p_consumed_ip_hash,
            consumed_user_agent_hash = p_consumed_user_agent_hash
        WHERE id = v_token_id
          AND consumed_at IS NULL
          AND revoked_at IS NULL;

        UPDATE users
        SET password_hash = p_new_password_hash,
            updated_at = NOW()
        WHERE id = v_user_id
          AND is_active = TRUE;

        SET v_password_changed = ROW_COUNT() > 0;
        SET v_result = CASE WHEN v_password_changed THEN 'password_changed' ELSE 'user_inactive' END;
    END IF;

    COMMIT;
    SELECT v_result AS consume_status,
           v_user_id AS user_id,
           v_password_changed AS password_changed;
END$$

-- ===================================================================================
-- sp_claim_email_messages
-- Claims eligible pending/retry messages using MySQL 8 FOR UPDATE SKIP LOCKED.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_claim_email_messages$$
CREATE PROCEDURE sp_claim_email_messages(
    IN p_worker_id VARCHAR(128),
    IN p_limit INT,
    IN p_lease_seconds INT
)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    DROP TEMPORARY TABLE IF EXISTS tmp_email_claim_ids;
    CREATE TEMPORARY TABLE tmp_email_claim_ids (
        id VARCHAR(64) NOT NULL PRIMARY KEY
    ) ENGINE=MEMORY;

    INSERT INTO tmp_email_claim_ids (id)
    SELECT id
    FROM email_messages
    WHERE (
            status IN ('pending','retry')
            AND next_attempt_at <= NOW()
          )
       OR (
            status = 'processing'
            AND lease_until IS NOT NULL
            AND lease_until < NOW()
          )
    ORDER BY priority ASC, created_at ASC
    LIMIT p_limit
    FOR UPDATE SKIP LOCKED;

    UPDATE email_messages em
    JOIN tmp_email_claim_ids t ON t.id = em.id
    SET em.status = 'processing',
        em.claimed_by = p_worker_id,
        em.claimed_at = NOW(),
        em.lease_until = DATE_ADD(NOW(), INTERVAL p_lease_seconds SECOND),
        em.updated_at = NOW();

    COMMIT;

    SELECT em.id,
           em.user_id,
           em.user_email_id,
           em.token_id,
           em.purpose,
           em.template_code,
           em.recipient_email,
           em.recipient_hash,
           em.recipient_masked,
           em.provider,
           em.provider_idempotency_key,
           em.status,
           em.priority,
           em.attempt_count,
           em.max_attempts,
           em.next_attempt_at,
           em.claimed_by,
           em.claimed_at,
           em.lease_until,
           em.render_payload_ciphertext,
           EXISTS (
               SELECT 1
               FROM email_suppressions es
               WHERE es.email_hash = em.recipient_hash
                 AND es.is_active = TRUE
           ) AS suppressed
    FROM email_messages em
    JOIN tmp_email_claim_ids t ON t.id = em.id
    ORDER BY em.priority ASC, em.created_at ASC;

    DROP TEMPORARY TABLE IF EXISTS tmp_email_claim_ids;
END$$

-- ===================================================================================
-- sp_finalize_email_message
-- Finalizes worker/provider outcome and applies retry/dead-letter state.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_finalize_email_message$$
CREATE PROCEDURE sp_finalize_email_message(
    IN p_email_message_id VARCHAR(64),
    IN p_status VARCHAR(32),
    IN p_provider_message_id VARCHAR(255),
    IN p_error_code VARCHAR(100),
    IN p_error_message TEXT,
    IN p_retry_after_seconds INT
)
BEGIN
    DECLARE v_attempt_count INT DEFAULT NULL;
    DECLARE v_max_attempts INT DEFAULT NULL;
    DECLARE v_next_attempt_count INT DEFAULT NULL;
    DECLARE v_next_status VARCHAR(32);

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT attempt_count, max_attempts
      INTO v_attempt_count, v_max_attempts
    FROM email_messages
    WHERE id = p_email_message_id
    LIMIT 1
    FOR UPDATE;

    IF v_attempt_count IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Email message does not exist';
    END IF;

    SET v_next_attempt_count = v_attempt_count + 1;
    SET v_next_status = p_status;

    IF p_status = 'retry' AND v_next_attempt_count >= v_max_attempts THEN
        SET v_next_status = 'dead';
    END IF;

    UPDATE email_messages
    SET status = v_next_status,
        provider_message_id = COALESCE(p_provider_message_id, provider_message_id),
        attempt_count = CASE
            WHEN p_status IN ('sent','retry','dead','suppressed') THEN v_next_attempt_count
            ELSE attempt_count
        END,
        sent_at = CASE WHEN v_next_status = 'sent' THEN NOW() ELSE sent_at END,
        terminal_at = CASE
            WHEN v_next_status IN ('delivered','bounced','complained','suppressed','dead','cancelled') THEN NOW()
            ELSE terminal_at
        END,
        next_attempt_at = CASE
            WHEN v_next_status = 'retry' THEN DATE_ADD(NOW(), INTERVAL COALESCE(p_retry_after_seconds, 0) SECOND)
            ELSE next_attempt_at
        END,
        claimed_by = CASE WHEN v_next_status IN ('pending','retry') THEN NULL ELSE claimed_by END,
        lease_until = CASE WHEN v_next_status IN ('pending','retry') THEN NULL ELSE lease_until END,
        last_error_code = p_error_code,
        last_error_message = p_error_message,
        render_payload_ciphertext = CASE
            WHEN v_next_status IN ('sent','delivered','bounced','complained','suppressed','dead','cancelled') THEN NULL
            ELSE render_payload_ciphertext
        END,
        updated_at = NOW()
    WHERE id = p_email_message_id;

    COMMIT;
    SELECT p_email_message_id AS email_message_id,
           v_next_status AS status,
           v_next_attempt_count AS attempt_count;
END$$

-- ===================================================================================
-- sp_record_email_delivery_attempt
-- Appends one sanitized delivery attempt/event record.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_record_email_delivery_attempt$$
CREATE PROCEDURE sp_record_email_delivery_attempt(
    IN p_attempt_id VARCHAR(64),
    IN p_email_message_id VARCHAR(64),
    IN p_attempt_no INT,
    IN p_provider VARCHAR(50),
    IN p_status VARCHAR(32),
    IN p_provider_message_id VARCHAR(255),
    IN p_provider_event_id VARCHAR(255),
    IN p_error_code VARCHAR(100),
    IN p_error_message TEXT,
    IN p_response_metadata JSON
)
BEGIN
    INSERT INTO email_delivery_attempts (
        id, email_message_id, attempt_no, provider, status,
        provider_message_id, provider_event_id, error_code, error_message,
        response_metadata, created_at
    ) VALUES (
        p_attempt_id, p_email_message_id, p_attempt_no, p_provider, p_status,
        p_provider_message_id, p_provider_event_id, p_error_code, p_error_message,
        p_response_metadata, NOW()
    );

    SELECT p_attempt_id AS attempt_id,
           p_email_message_id AS email_message_id,
           'recorded' AS attempt_status;
END$$

-- ===================================================================================
-- sp_apply_email_provider_event
-- Deduplicates provider events, updates message state, and upserts hashed suppression
-- records for bounces/complaints.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_apply_email_provider_event$$
CREATE PROCEDURE sp_apply_email_provider_event(
    IN p_delivery_attempt_id VARCHAR(64),
    IN p_email_message_id VARCHAR(64),
    IN p_provider VARCHAR(50),
    IN p_provider_message_id VARCHAR(255),
    IN p_provider_event_id VARCHAR(255),
    IN p_event_type VARCHAR(64),
    IN p_recipient_hash BINARY(32),
    IN p_suppression_id VARCHAR(64),
    IN p_response_metadata JSON
)
BEGIN
    DECLARE v_existing_event_count INT DEFAULT 0;
    DECLARE v_message_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_attempt_no INT DEFAULT 1;
    DECLARE v_message_recipient_hash BINARY(32) DEFAULT NULL;
    DECLARE v_suppression_reason VARCHAR(32) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    IF p_provider_event_id IS NOT NULL THEN
        SELECT COUNT(*) INTO v_existing_event_count
        FROM email_delivery_attempts
        WHERE provider = p_provider
          AND provider_event_id = p_provider_event_id;
    END IF;

    IF v_existing_event_count > 0 THEN
        COMMIT;
        SELECT p_provider_event_id AS provider_event_id,
               'duplicate' AS event_status,
               NULL AS email_message_id;
    ELSE
        SET v_message_id = p_email_message_id;

        IF v_message_id IS NULL AND p_provider_message_id IS NOT NULL THEN
            SELECT id
              INTO v_message_id
            FROM email_messages
            WHERE provider = p_provider
              AND provider_message_id = p_provider_message_id
            ORDER BY created_at DESC
            LIMIT 1
            FOR UPDATE;
        END IF;

        IF v_message_id IS NULL THEN
            COMMIT;
            SELECT p_provider_event_id AS provider_event_id,
                   'message_not_found' AS event_status,
                   NULL AS email_message_id;
        ELSE
            SELECT recipient_hash
              INTO v_message_recipient_hash
            FROM email_messages
            WHERE id = v_message_id
            LIMIT 1
            FOR UPDATE;

            SELECT COALESCE(MAX(attempt_no), 0) + 1
              INTO v_attempt_no
            FROM email_delivery_attempts
            WHERE email_message_id = v_message_id;

            INSERT INTO email_delivery_attempts (
                id, email_message_id, attempt_no, provider, status,
                provider_message_id, provider_event_id, response_metadata, created_at
            ) VALUES (
                COALESCE(p_delivery_attempt_id, CONCAT('eda-', UUID())), v_message_id, v_attempt_no, p_provider, 'webhook_event',
                p_provider_message_id, p_provider_event_id, p_response_metadata, NOW()
            );

            IF p_event_type IN ('delivered','email.delivered','delivery.delivered') THEN
                UPDATE email_messages
                SET status = 'delivered',
                    provider_message_id = COALESCE(p_provider_message_id, provider_message_id),
                    terminal_at = NOW(),
                    updated_at = NOW()
                WHERE id = v_message_id;
            ELSEIF p_event_type IN ('bounced','bounce','hard_bounce','email.bounced') THEN
                UPDATE email_messages
                SET status = 'bounced',
                    provider_message_id = COALESCE(p_provider_message_id, provider_message_id),
                    terminal_at = NOW(),
                    updated_at = NOW()
                WHERE id = v_message_id;

                SET v_suppression_reason = 'hard_bounce';
            ELSEIF p_event_type IN ('complained','complaint','email.complained') THEN
                UPDATE email_messages
                SET status = 'complained',
                    provider_message_id = COALESCE(p_provider_message_id, provider_message_id),
                    terminal_at = NOW(),
                    updated_at = NOW()
                WHERE id = v_message_id;

                SET v_suppression_reason = 'complaint';
            END IF;

            IF v_suppression_reason IS NOT NULL THEN
                INSERT INTO email_suppressions (
                    id, email_hash, reason, source, provider, provider_event_id,
                    is_active, created_at, metadata
                ) VALUES (
                    COALESCE(p_suppression_id, CONCAT('esup-', UUID())),
                    COALESCE(p_recipient_hash, v_message_recipient_hash),
                    v_suppression_reason,
                    'provider_webhook',
                    p_provider,
                    p_provider_event_id,
                    TRUE,
                    NOW(),
                    p_response_metadata
                ) ON DUPLICATE KEY UPDATE
                    is_active = TRUE,
                    lifted_at = NULL,
                    provider = VALUES(provider),
                    provider_event_id = VALUES(provider_event_id),
                    metadata = VALUES(metadata);

                -- Flip the matching account email identity to 'suppressed'. The
                -- email_suppressions ledger only blocks the worker from sending;
                -- without this, a hard-bounced/complained address would stay
                -- 'activated' and remain usable for email login and as a
                -- password-reset target (sp_user_login / sp_password_reset_link_enqueue
                -- filter on status='activated'). Suppressing it here excludes the
                -- undeliverable address from those flows. Username login is
                -- unaffected, so this does not lock the account out.
                UPDATE user_emails
                SET status = 'suppressed',
                    is_primary = FALSE,
                    updated_at = NOW()
                WHERE email_hash = COALESCE(p_recipient_hash, v_message_recipient_hash)
                  AND status = 'activated'
                  AND removed_at IS NULL;
            END IF;

            COMMIT;
            SELECT p_provider_event_id AS provider_event_id,
                   COALESCE(v_suppression_reason, p_event_type) AS event_status,
                   v_message_id AS email_message_id;
        END IF;
    END IF;
END$$

-- ===================================================================================
-- sp_email_retention_purge
-- GDPR-baseline minimization for token rows, transient render payloads, recipient PII,
-- and old delivery-attempt metadata. Token rows are purged/anonymized after 30 days;
-- attempt metadata is PII-stripped after the 365-day operations window.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_email_retention_purge$$
CREATE PROCEDURE sp_email_retention_purge()
BEGIN
    DECLARE v_payload_rows INT DEFAULT 0;
    DECLARE v_recipient_rows INT DEFAULT 0;
    DECLARE v_token_rows INT DEFAULT 0;
    DECLARE v_attempt_rows INT DEFAULT 0;
    DECLARE v_idempotency_rows INT DEFAULT 0;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    UPDATE email_messages
    SET render_payload_ciphertext = NULL,
        updated_at = NOW()
    WHERE render_payload_ciphertext IS NOT NULL
      AND (
          payload_purge_at <= NOW()
          OR terminal_at <= DATE_SUB(NOW(), INTERVAL 30 DAY)
          OR created_at <= DATE_SUB(NOW(), INTERVAL 30 DAY)
      );
    SET v_payload_rows = ROW_COUNT();

    UPDATE email_messages
    SET recipient_email = NULL,
        last_error_message = NULL,
        updated_at = NOW()
    WHERE recipient_email IS NOT NULL
      AND (
          terminal_at <= DATE_SUB(NOW(), INTERVAL 30 DAY)
          OR created_at <= DATE_SUB(NOW(), INTERVAL 30 DAY)
      );
    SET v_recipient_rows = ROW_COUNT();

    DELETE FROM user_email_link_tokens
    WHERE (consumed_at IS NOT NULL AND consumed_at <= DATE_SUB(NOW(), INTERVAL 30 DAY))
       OR (revoked_at IS NOT NULL AND revoked_at <= DATE_SUB(NOW(), INTERVAL 30 DAY))
       OR expires_at <= DATE_SUB(NOW(), INTERVAL 30 DAY);
    SET v_token_rows = ROW_COUNT();

    UPDATE email_delivery_attempts
    SET error_message = NULL,
        response_metadata = JSON_OBJECT('retention', 'pii_stripped', 'retained_days', 365)
    WHERE created_at <= DATE_SUB(NOW(), INTERVAL 365 DAY)
      AND (error_message IS NOT NULL OR response_metadata IS NOT NULL);
    SET v_attempt_rows = ROW_COUNT();

    UPDATE email_idempotency_keys
    SET status = 'expired',
        replay_body = JSON_OBJECT('success', TRUE, 'message', 'If the request can be processed, it has been accepted.'),
        completed_at = COALESCE(completed_at, NOW())
    WHERE expires_at <= NOW()
      AND status <> 'expired';
    SET v_idempotency_rows = ROW_COUNT();

    COMMIT;
    SELECT v_payload_rows AS payload_rows_purged,
           v_recipient_rows AS recipient_rows_minimized,
           v_token_rows AS token_rows_purged,
           v_attempt_rows AS delivery_attempt_rows_stripped,
           v_idempotency_rows AS idempotency_rows_expired;
END$$

-- ===================================================================================
-- sp_anonymize_user_email_data
-- Tombstones user email PII for erasure while preserving minimum non-PII security and
-- delivery evidence. Pending/retry messages are cancelled so erased recipients are not
-- delivered later.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_anonymize_user_email_data$$
CREATE PROCEDURE sp_anonymize_user_email_data(
    IN p_user_id VARCHAR(64)
)
BEGIN
    DECLARE v_user_email_rows INT DEFAULT 0;
    DECLARE v_message_rows INT DEFAULT 0;
    DECLARE v_attempt_rows INT DEFAULT 0;
    DECLARE v_token_rows INT DEFAULT 0;
    DECLARE v_idempotency_rows INT DEFAULT 0;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    DROP TEMPORARY TABLE IF EXISTS tmp_erased_email_message_ids;
    CREATE TEMPORARY TABLE tmp_erased_email_message_ids (
        id VARCHAR(64) NOT NULL PRIMARY KEY
    ) ENGINE=MEMORY;

    INSERT INTO tmp_erased_email_message_ids (id)
    SELECT DISTINCT em.id
    FROM email_messages em
    LEFT JOIN user_emails ue ON ue.id = em.user_email_id
    WHERE em.user_id = p_user_id
       OR ue.user_id = p_user_id;

    UPDATE users
    SET email = NULL,
        updated_at = NOW()
    WHERE id = p_user_id;

    UPDATE user_emails
    SET email_normalized = CONCAT('erased+', id, '@redacted.local'),
        email_hash = UNHEX(SHA2(CONCAT('erased:user_email:', id), 256)),
        email_masked = '[erased]',
        status = 'removed',
        is_primary = FALSE,
        removed_at = COALESCE(removed_at, NOW()),
        updated_at = NOW()
    WHERE user_id = p_user_id;
    SET v_user_email_rows = ROW_COUNT();

    DELETE FROM user_email_link_tokens
    WHERE user_id = p_user_id;
    SET v_token_rows = ROW_COUNT();

    UPDATE email_messages em
    JOIN tmp_erased_email_message_ids tmp ON tmp.id = em.id
    SET em.user_id = NULL,
        em.user_email_id = NULL,
        em.token_id = NULL,
        em.recipient_email = NULL,
        em.recipient_hash = UNHEX(SHA2(CONCAT('erased:email_message:', em.id), 256)),
        em.recipient_masked = '[erased]',
        em.render_payload_ciphertext = NULL,
        em.last_error_message = NULL,
        em.terminal_at = CASE
            WHEN em.status IN ('pending','processing','retry') THEN COALESCE(em.terminal_at, NOW())
            ELSE em.terminal_at
        END,
        em.status = CASE
            WHEN em.status IN ('pending','processing','retry') THEN 'cancelled'
            ELSE em.status
        END,
        em.updated_at = NOW();
    SET v_message_rows = ROW_COUNT();

    UPDATE email_delivery_attempts eda
    JOIN tmp_erased_email_message_ids tmp ON tmp.id = eda.email_message_id
    SET eda.error_message = NULL,
        eda.response_metadata = JSON_OBJECT('retention', 'user_erasure_tombstone');
    SET v_attempt_rows = ROW_COUNT();

    UPDATE email_idempotency_keys
    SET user_id = NULL,
        recipient_hash = NULL,
        replay_body = JSON_OBJECT('success', TRUE, 'message', 'If the request can be processed, it has been accepted.'),
        status = CASE WHEN status = 'in_progress' THEN 'expired' ELSE status END,
        completed_at = COALESCE(completed_at, NOW())
    WHERE user_id = p_user_id;
    SET v_idempotency_rows = ROW_COUNT();

    DROP TEMPORARY TABLE IF EXISTS tmp_erased_email_message_ids;

    COMMIT;
    SELECT v_user_email_rows AS user_email_rows_tombstoned,
           v_message_rows AS email_message_rows_tombstoned,
           v_attempt_rows AS delivery_attempt_rows_stripped,
           v_token_rows AS token_rows_purged,
           v_idempotency_rows AS idempotency_rows_minimized;
END$$

-- ===================================================================================
-- sp_email_idempotency_begin
-- Durable local idempotency record creation/replay lookup. Provider idempotency never
-- replaces this local truth.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_email_idempotency_begin$$
CREATE PROCEDURE sp_email_idempotency_begin(
    IN p_idempotency_id VARCHAR(64),
    IN p_scope VARCHAR(128),
    IN p_key_hash BINARY(32),
    IN p_request_hash BINARY(32),
    IN p_user_id VARCHAR(64),
    IN p_recipient_hash BINARY(32),
    IN p_expires_at DATETIME,
    IN p_replay_body JSON
)
BEGIN
    DECLARE v_existing_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_existing_request_hash BINARY(32) DEFAULT NULL;
    DECLARE v_existing_status VARCHAR(32) DEFAULT NULL;
    DECLARE v_replay_status_code INT DEFAULT NULL;
    DECLARE v_replay_body JSON DEFAULT NULL;

    START TRANSACTION;

    SELECT id, request_hash, status, replay_status_code, replay_body
      INTO v_existing_id, v_existing_request_hash, v_existing_status, v_replay_status_code, v_replay_body
    FROM email_idempotency_keys
    WHERE scope = p_scope
      AND key_hash = p_key_hash
      AND expires_at > NOW()
    LIMIT 1
    FOR UPDATE;

    IF v_existing_id IS NULL THEN
        INSERT INTO email_idempotency_keys (
            id, scope, key_hash, request_hash, user_id, recipient_hash,
            status, replay_status_code, replay_body, expires_at, created_at
        ) VALUES (
            p_idempotency_id, p_scope, p_key_hash, p_request_hash, p_user_id, p_recipient_hash,
            'in_progress', 202,
            COALESCE(p_replay_body, JSON_OBJECT('success', TRUE, 'message', 'If the request can be processed, it has been accepted.')),
            p_expires_at, NOW()
        );

        COMMIT;
        SELECT 'created' AS idempotency_status,
               p_idempotency_id AS idempotency_id,
               202 AS replay_status_code,
               COALESCE(p_replay_body, JSON_OBJECT('success', TRUE, 'message', 'If the request can be processed, it has been accepted.')) AS replay_body;
    ELSEIF v_existing_request_hash <> p_request_hash THEN
        UPDATE email_idempotency_keys
        SET status = 'conflict'
        WHERE id = v_existing_id;

        COMMIT;
        SELECT 'conflict' AS idempotency_status,
               v_existing_id AS idempotency_id,
               409 AS replay_status_code,
               JSON_OBJECT('success', TRUE, 'message', 'If the request can be processed, it has been accepted.') AS replay_body;
    ELSE
        COMMIT;
        SELECT v_existing_status AS idempotency_status,
               v_existing_id AS idempotency_id,
               v_replay_status_code AS replay_status_code,
               v_replay_body AS replay_body;
    END IF;
END$$

-- ===================================================================================
-- sp_email_idempotency_complete
-- Marks a local idempotency key complete and binds the resulting email message.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_email_idempotency_complete$$
CREATE PROCEDURE sp_email_idempotency_complete(
    IN p_scope VARCHAR(128),
    IN p_key_hash BINARY(32),
    IN p_email_message_id VARCHAR(64),
    IN p_replay_status_code INT,
    IN p_replay_body JSON
)
BEGIN
    UPDATE email_idempotency_keys
    SET email_message_id = p_email_message_id,
        status = 'complete',
        replay_status_code = COALESCE(p_replay_status_code, 202),
        replay_body = COALESCE(p_replay_body, JSON_OBJECT('success', TRUE, 'message', 'If the request can be processed, it has been accepted.')),
        completed_at = NOW()
    WHERE scope = p_scope
      AND key_hash = p_key_hash
      AND status IN ('in_progress','complete');

    SELECT ROW_COUNT() AS rows_affected;
END$$

-- ===================================================================================
-- sp_email_idempotency_get
-- Reads replay state for an unexpired idempotency key.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_email_idempotency_get$$
CREATE PROCEDURE sp_email_idempotency_get(
    IN p_scope VARCHAR(128),
    IN p_key_hash BINARY(32)
)
BEGIN
    SELECT id,
           scope,
           status,
           replay_status_code,
           replay_body,
           email_message_id,
           expires_at,
           created_at,
           completed_at
    FROM email_idempotency_keys
    WHERE scope = p_scope
      AND key_hash = p_key_hash
      AND expires_at > NOW()
    LIMIT 1;
END$$

-- ===================================================================================
-- sp_email_enqueue_patreon_link_proof
-- Durable outbox enqueue for Patreon email-loop proof messages. This supports the
-- `patreon_link_proof` purpose without inserting local user_email_link_tokens or
-- changing local email activation/password reset semantics.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_email_enqueue_patreon_link_proof$$
CREATE PROCEDURE sp_email_enqueue_patreon_link_proof(
    IN p_email_message_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_recipient_email VARCHAR(255),
    IN p_recipient_hash BINARY(32),
    IN p_recipient_masked VARCHAR(255),
    IN p_provider VARCHAR(50),
    IN p_provider_idempotency_key VARCHAR(128),
    IN p_render_payload_ciphertext LONGBLOB,
    IN p_payload_purge_at DATETIME,
    IN p_priority TINYINT
)
BEGIN
    IF p_recipient_hash IS NULL OR OCTET_LENGTH(p_recipient_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon link proof recipient hash must be 32 bytes';
    END IF;

    IF p_payload_purge_at IS NULL OR p_payload_purge_at <= NOW() THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon link proof payload purge time must be in the future';
    END IF;

    INSERT INTO email_messages (
        id, user_id, user_email_id, token_id, purpose, template_code,
        recipient_email, recipient_hash, recipient_masked, provider,
        provider_idempotency_key, status, priority, attempt_count, max_attempts,
        next_attempt_at, render_payload_ciphertext, payload_purge_at, created_at, updated_at
    ) VALUES (
        p_email_message_id, p_user_id, NULL, NULL, 'patreon_link_proof', 'patreon_link_proof',
        p_recipient_email, p_recipient_hash, p_recipient_masked, COALESCE(p_provider, 'resend'),
        p_provider_idempotency_key, 'pending', COALESCE(p_priority, 4), 0, 8,
        NOW(), p_render_payload_ciphertext, p_payload_purge_at, NOW(), NOW()
    );

    SELECT p_email_message_id AS email_message_id,
           'patreon_link_proof_enqueued' AS lifecycle_status;
END$$

-- ===================================================================================
-- DB-MANAGED TRANSACTIONAL EMAIL TEMPLATES
-- ===================================================================================
-- Admin-editable, versioned bodies for the fixed transactional-scope template
-- codes. The application resolves the active version at render time and falls
-- back to in-code defaults on an empty/unavailable table, so these procedures
-- never become a hard delivery dependency. Single-active-per-code is enforced
-- transactionally here because MySQL cannot express a partial unique index on
-- is_active.
-- ===================================================================================

-- Return the active version for one code (deterministic newest-active).
DROP PROCEDURE IF EXISTS sp_email_template_get_active$$
CREATE PROCEDURE sp_email_template_get_active(
    IN p_template_code VARCHAR(100)
)
BEGIN
    SELECT template_code, version, subject_template, html_template, text_template,
           is_active, created_at
    FROM email_templates
    WHERE template_code = p_template_code
      AND is_active = TRUE
    ORDER BY version DESC
    LIMIT 1;
END$$

-- List the active version of every code (subject only; full bodies via get_active).
DROP PROCEDURE IF EXISTS sp_email_template_list$$
CREATE PROCEDURE sp_email_template_list()
BEGIN
    SELECT template_code, version, subject_template, is_active, created_at
    FROM email_templates
    WHERE is_active = TRUE
    ORDER BY template_code ASC;
END$$

-- Version history for one code (metadata only; newest first).
DROP PROCEDURE IF EXISTS sp_email_template_versions$$
CREATE PROCEDURE sp_email_template_versions(
    IN p_template_code VARCHAR(100)
)
BEGIN
    SELECT template_code, version, subject_template, is_active, created_at
    FROM email_templates
    WHERE template_code = p_template_code
    ORDER BY version DESC;
END$$

-- Fetch the full bodies of one specific version (for diff/preview/rollback UI).
DROP PROCEDURE IF EXISTS sp_email_template_get_version$$
CREATE PROCEDURE sp_email_template_get_version(
    IN p_template_code VARCHAR(100),
    IN p_version INT
)
BEGIN
    SELECT template_code, version, subject_template, html_template, text_template,
           is_active, created_at
    FROM email_templates
    WHERE template_code = p_template_code
      AND version = p_version
    LIMIT 1;
END$$

-- Save a new version and make it the single active one, atomically.
DROP PROCEDURE IF EXISTS sp_email_template_save_and_activate$$
CREATE PROCEDURE sp_email_template_save_and_activate(
    IN p_id VARCHAR(64),
    IN p_template_code VARCHAR(100),
    IN p_subject_template VARCHAR(255),
    IN p_html_template TEXT,
    IN p_text_template TEXT
)
BEGIN
    DECLARE v_next_version INT DEFAULT 1;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    -- Lock existing rows for this code to serialise concurrent saves; the
    -- UNIQUE(template_code, version) key is the backstop on the empty-table race.
    SELECT COALESCE(MAX(version), 0) + 1
      INTO v_next_version
    FROM email_templates
    WHERE template_code = p_template_code
    FOR UPDATE;

    UPDATE email_templates
       SET is_active = FALSE
     WHERE template_code = p_template_code
       AND is_active = TRUE;

    INSERT INTO email_templates (
        id, template_code, version, subject_template, html_template, text_template,
        is_active, created_at
    ) VALUES (
        p_id, p_template_code, v_next_version, p_subject_template, p_html_template,
        p_text_template, TRUE, NOW()
    );

    COMMIT;

    SELECT p_template_code AS template_code, v_next_version AS version, TRUE AS is_active;
END$$

-- Re-activate an existing prior version (rollback), atomically single-active.
DROP PROCEDURE IF EXISTS sp_email_template_rollback$$
CREATE PROCEDURE sp_email_template_rollback(
    IN p_template_code VARCHAR(100),
    IN p_version INT
)
BEGIN
    DECLARE v_exists INT DEFAULT 0;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT COUNT(*)
      INTO v_exists
    FROM email_templates
    WHERE template_code = p_template_code
      AND version = p_version
    FOR UPDATE;

    IF v_exists = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'email template version not found';
    END IF;

    UPDATE email_templates
       SET is_active = FALSE
     WHERE template_code = p_template_code
       AND is_active = TRUE;

    UPDATE email_templates
       SET is_active = TRUE
     WHERE template_code = p_template_code
       AND version = p_version;

    COMMIT;

    SELECT p_template_code AS template_code, p_version AS version, TRUE AS is_active;
END$$

DELIMITER ;

-- ===================================================================================
-- EMAIL ACTIVATION STORED PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Email activation stored procedures created!' AS status,
       '27 procedures for email lifecycle, reset links, outbox delivery, Patreon proof, webhooks, idempotency, retention, anonymization, and DB-managed templates' AS details;
