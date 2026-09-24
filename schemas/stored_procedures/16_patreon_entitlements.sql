-- ===================================================================================
-- Patreon Account Link, Entitlement, Webhook, Sync, and Retention Procedures
-- ===================================================================================
-- Patreon procedures operate on HMAC/fingerprint identifiers supplied by application
-- code. They never issue local sessions, never mutate JWT/session/refresh-token state,
-- and never store per-user Patreon token material. Public routes must still enforce
-- authentication, recent local reauth, rate limits, and generic errors.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- sp_patreon_proof_create
-- Creates a hash-only Patreon email-loop proof and durable email outbox message using
-- purpose/template `patreon_link_proof`. Does not touch local email activation tokens.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_proof_create$$
CREATE PROCEDURE sp_patreon_proof_create(
    IN p_proof_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_campaign_id VARCHAR(64),
    IN p_patreon_user_id_hash BINARY(32),
    IN p_patreon_user_id_fingerprint CHAR(12),
    IN p_member_id_hash BINARY(32),
    IN p_member_id_fingerprint CHAR(12),
    IN p_proof_email_hash BINARY(32),
    IN p_proof_email_masked VARCHAR(255),
    IN p_lookup_id VARCHAR(32),
    IN p_token_hash BINARY(32),
    IN p_token_fingerprint CHAR(12),
    IN p_expires_at DATETIME,
    IN p_email_message_id VARCHAR(64),
    IN p_recipient_email VARCHAR(255),
    IN p_provider VARCHAR(50),
    IN p_provider_idempotency_key VARCHAR(128),
    IN p_render_payload_ciphertext LONGBLOB,
    IN p_created_ip_hash BINARY(32),
    IN p_created_user_agent_hash BINARY(32),
    IN p_metadata JSON
)
BEGIN
    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF p_token_hash IS NULL OR OCTET_LENGTH(p_token_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon proof token hash must be 32 bytes';
    END IF;

    IF p_proof_email_hash IS NULL OR OCTET_LENGTH(p_proof_email_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon proof email hash must be 32 bytes';
    END IF;

    IF p_expires_at <= NOW() THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon proof expiry must be in the future';
    END IF;

    START TRANSACTION;

    IF NOT EXISTS (SELECT 1 FROM users WHERE id = p_user_id AND is_active = TRUE) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon proof user is not active';
    END IF;

    -- The outbox message goes first: patreon_link_proofs.email_message_id references it.
    INSERT INTO email_messages (
        id, user_id, user_email_id, token_id, purpose, template_code,
        recipient_email, recipient_hash, recipient_masked, provider,
        provider_idempotency_key, status, priority, attempt_count, max_attempts,
        next_attempt_at, render_payload_ciphertext, payload_purge_at, created_at, updated_at
    ) VALUES (
        p_email_message_id, p_user_id, NULL, NULL, 'patreon_link_proof', 'patreon_link_proof',
        p_recipient_email, p_proof_email_hash, p_proof_email_masked, COALESCE(p_provider, 'resend'),
        p_provider_idempotency_key, 'pending', 4, 0, 8,
        NOW(), p_render_payload_ciphertext, LEAST(DATE_ADD(NOW(), INTERVAL 30 DAY), DATE_ADD(p_expires_at, INTERVAL 24 HOUR)), NOW(), NOW()
    );

    INSERT INTO patreon_link_proofs (
        id, user_id, campaign_id, patreon_user_id_hash, patreon_user_id_fingerprint,
        member_id_hash, member_id_fingerprint, proof_email_hash, proof_email_masked,
        lookup_id, token_hash, token_fingerprint, status, attempts, max_attempts,
        expires_at, purge_after_at, created_ip_hash, created_user_agent_hash,
        email_message_id, created_at, updated_at, metadata
    ) VALUES (
        p_proof_id, p_user_id, p_campaign_id, p_patreon_user_id_hash, p_patreon_user_id_fingerprint,
        p_member_id_hash, p_member_id_fingerprint, p_proof_email_hash, p_proof_email_masked,
        p_lookup_id, p_token_hash, p_token_fingerprint, 'pending', 0, 8,
        p_expires_at, DATE_ADD(p_expires_at, INTERVAL 24 HOUR), p_created_ip_hash,
        p_created_user_agent_hash, p_email_message_id, NOW(), NOW(), p_metadata
    );

    COMMIT;

    SELECT p_proof_id AS proof_id,
           p_email_message_id AS email_message_id,
           'proof_enqueued' AS lifecycle_status;
END$$

-- ===================================================================================
-- sp_patreon_proof_consume
-- Atomically consumes one pending Patreon proof token. Successful consumption advances
-- proof state only; it does not create a local session or activate local email.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_proof_consume$$
CREATE PROCEDURE sp_patreon_proof_consume(
    IN p_lookup_id VARCHAR(32),
    IN p_token_hash BINARY(32),
    IN p_consumed_ip_hash BINARY(32),
    IN p_consumed_user_agent_hash BINARY(32),
    IN p_user_id VARCHAR(64)
)
BEGIN
    DECLARE v_proof_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_user_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_stored_hash BINARY(32) DEFAULT NULL;
    DECLARE v_status VARCHAR(32) DEFAULT NULL;
    DECLARE v_expires_at DATETIME DEFAULT NULL;
    DECLARE v_attempts INT DEFAULT 0;
    DECLARE v_max_attempts INT DEFAULT 8;
    DECLARE v_result VARCHAR(64) DEFAULT 'not_found';
    DECLARE v_campaign_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_patreon_user_id_hash BINARY(32) DEFAULT NULL;
    DECLARE v_patreon_user_id_fingerprint CHAR(12) DEFAULT NULL;
    DECLARE v_member_id_hash BINARY(32) DEFAULT NULL;
    DECLARE v_member_id_fingerprint CHAR(12) DEFAULT NULL;
    DECLARE v_proof_email_hash BINARY(32) DEFAULT NULL;
    DECLARE v_proof_email_masked VARCHAR(255) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT id, user_id, token_hash, status, expires_at, attempts, max_attempts,
           campaign_id, patreon_user_id_hash, patreon_user_id_fingerprint,
           member_id_hash, member_id_fingerprint, proof_email_hash, proof_email_masked
      INTO v_proof_id, v_user_id, v_stored_hash, v_status, v_expires_at, v_attempts, v_max_attempts,
           v_campaign_id, v_patreon_user_id_hash, v_patreon_user_id_fingerprint,
           v_member_id_hash, v_member_id_fingerprint, v_proof_email_hash, v_proof_email_masked
    FROM patreon_link_proofs
    WHERE lookup_id = p_lookup_id
      AND (p_user_id IS NULL OR user_id = p_user_id)
    LIMIT 1
    FOR UPDATE;

    IF v_proof_id IS NULL THEN
        SET v_result = 'not_found';
    ELSEIF v_status <> 'pending' THEN
        -- A proof is single-use: a replay must never look like a fresh consumption.
        SET v_result = CASE WHEN v_status = 'consumed' THEN 'already_consumed' ELSE v_status END;
    ELSEIF v_stored_hash <> p_token_hash THEN
        UPDATE patreon_link_proofs
        SET attempts = attempts + 1,
            status = CASE WHEN attempts + 1 >= max_attempts THEN 'blocked' ELSE status END,
            updated_at = NOW()
        WHERE id = v_proof_id;
        SET v_result = 'invalid';
    ELSEIF v_expires_at <= NOW() THEN
        UPDATE patreon_link_proofs
        SET status = 'expired', updated_at = NOW()
        WHERE id = v_proof_id;
        SET v_result = 'expired';
    ELSE
        UPDATE patreon_link_proofs
        SET status = 'consumed',
            consumed_at = NOW(),
            consumed_ip_hash = p_consumed_ip_hash,
            consumed_user_agent_hash = p_consumed_user_agent_hash,
            attempts = attempts + 1,
            updated_at = NOW()
        WHERE id = v_proof_id;
        SET v_result = 'consumed';
    END IF;

    COMMIT;

    -- Proof identity is released only for the one call that consumed it.
    IF v_result = 'consumed' THEN
        SELECT v_result AS consume_status,
               v_proof_id AS proof_id,
               v_user_id AS user_id,
               v_campaign_id AS campaign_id,
               v_patreon_user_id_hash AS patreon_user_id_hash,
               v_patreon_user_id_fingerprint AS patreon_user_id_fingerprint,
               v_member_id_hash AS member_id_hash,
               v_member_id_fingerprint AS member_id_fingerprint,
               v_proof_email_hash AS proof_email_hash,
               v_proof_email_masked AS proof_email_masked;
    ELSE
        SELECT v_result AS consume_status;
    END IF;
END$$

-- ===================================================================================
-- sp_patreon_link_conflict_check
-- Checks active Patreon provider/user conflicts without returning another user's data.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_link_conflict_check$$
CREATE PROCEDURE sp_patreon_link_conflict_check(
    IN p_user_id VARCHAR(64),
    IN p_provider_sub_hash BINARY(32)
)
BEGIN
    DECLARE v_other_count INT DEFAULT 0;
    DECLARE v_same_user_count INT DEFAULT 0;

    SELECT COUNT(*) INTO v_other_count
    FROM user_external_accounts
    WHERE provider = 'patreon'
      AND provider_sub_hash = p_provider_sub_hash
      AND status = 'linked'
      AND user_id <> p_user_id;

    SELECT COUNT(*) INTO v_same_user_count
    FROM user_external_accounts
    WHERE provider = 'patreon'
      AND status = 'linked'
      AND user_id = p_user_id;

    SELECT CASE
               WHEN v_other_count > 0 THEN 'linked_to_other_user'
               WHEN v_same_user_count > 0 THEN 'same_user_already_linked'
               ELSE 'clear'
           END AS conflict_status;
END$$

-- ===================================================================================
-- sp_patreon_link_account
-- Activates Patreon link authority in user_external_accounts and optionally records an
-- initial membership observation. This is a no-login operation.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_link_account$$
CREATE PROCEDURE sp_patreon_link_account(
    IN p_external_account_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_provider_sub_hash BINARY(32),
    IN p_provider_sub_fingerprint CHAR(12),
    IN p_provider_email_hash BINARY(32),
    IN p_provider_email_masked VARCHAR(255),
    IN p_linked_by VARCHAR(64),
    IN p_proof_id VARCHAR(64),
    IN p_campaign_id VARCHAR(64),
    IN p_membership_id VARCHAR(64),
    IN p_member_id_hash BINARY(32),
    IN p_member_id_fingerprint CHAR(12),
    IN p_metadata JSON
)
BEGIN
    DECLARE v_existing_external_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_existing_user_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_existing_user_provider_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_membership_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_membership_user_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_membership_external_id VARCHAR(64) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF p_provider_sub_hash IS NULL OR OCTET_LENGTH(p_provider_sub_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon provider subject hash must be 32 bytes';
    END IF;

    START TRANSACTION;

    IF NOT EXISTS (SELECT 1 FROM users WHERE id = p_user_id AND user_type = 'consumer' AND is_active = TRUE) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon link target is not an active consumer';
    END IF;

    SELECT id, user_id
      INTO v_existing_external_id, v_existing_user_id
    FROM user_external_accounts
    WHERE provider = 'patreon'
      AND provider_sub_hash = p_provider_sub_hash
      AND status = 'linked'
    LIMIT 1
    FOR UPDATE;

    IF v_existing_external_id IS NOT NULL AND v_existing_user_id <> p_user_id THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon provider identity is already linked';
    END IF;

    SELECT id
      INTO v_existing_user_provider_id
    FROM user_external_accounts
    WHERE provider = 'patreon'
      AND user_id = p_user_id
      AND status = 'linked'
      AND provider_sub_hash <> p_provider_sub_hash
    LIMIT 1
    FOR UPDATE;

    IF v_existing_user_provider_id IS NOT NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'User already has an active Patreon external account';
    END IF;

    IF v_existing_external_id IS NULL THEN
        INSERT INTO user_external_accounts (
            id, user_id, provider, provider_sub_hash, provider_sub_fingerprint,
            provider_email_hash, provider_email_masked,
            provider_email_verified_at_link, status, linked_at, linked_by,
            metadata
        ) VALUES (
            p_external_account_id, p_user_id, 'patreon', p_provider_sub_hash, p_provider_sub_fingerprint,
            p_provider_email_hash, p_provider_email_masked,
            p_provider_email_hash IS NOT NULL, 'linked', NOW(), p_linked_by,
            p_metadata
        );
        SET v_existing_external_id = p_external_account_id;
    ELSE
        UPDATE user_external_accounts
        SET provider_sub_fingerprint = p_provider_sub_fingerprint,
            provider_email_hash = COALESCE(p_provider_email_hash, provider_email_hash),
            provider_email_masked = COALESCE(p_provider_email_masked, provider_email_masked),
            provider_email_verified_at_link = COALESCE(p_provider_email_hash IS NOT NULL, provider_email_verified_at_link),
            last_seen_at = NOW(),
            metadata = COALESCE(p_metadata, metadata)
        WHERE id = v_existing_external_id;
    END IF;

    IF p_proof_id IS NOT NULL THEN
        UPDATE patreon_link_proofs
        SET external_account_id = v_existing_external_id,
            status = CASE WHEN status = 'pending' THEN 'consumed' ELSE status END,
            consumed_at = COALESCE(consumed_at, NOW()),
            updated_at = NOW()
        WHERE id = p_proof_id
          AND user_id = p_user_id;
    END IF;

    IF p_campaign_id IS NOT NULL AND p_membership_id IS NOT NULL THEN
        -- Resolve the member's ACTIVE membership instead of upserting by id: unlinked
        -- rows are terminal (history), so a relink must get its own membership row.
        SELECT id, user_id, external_account_id
          INTO v_membership_id, v_membership_user_id, v_membership_external_id
        FROM patreon_memberships
        WHERE campaign_id = p_campaign_id
          AND active_member_hash = p_member_id_hash
        LIMIT 1
        FOR UPDATE;

        IF v_membership_id IS NOT NULL AND v_membership_user_id <> p_user_id THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon membership is already linked to another user';
        END IF;

        IF v_membership_id IS NOT NULL AND v_membership_external_id <> v_existing_external_id THEN
            UPDATE patreon_memberships
            SET status = 'unlinked', unlinked_at = NOW(), unlink_reason = 'link_superseded', updated_at = NOW()
            WHERE id = v_membership_id;
            SET v_membership_id = NULL;
        END IF;

        IF v_membership_id IS NULL THEN
            -- A different member of the same campaign (a re-created membership) is superseded.
            UPDATE patreon_memberships
            SET status = 'unlinked', unlinked_at = NOW(), unlink_reason = 'member_superseded', updated_at = NOW()
            WHERE active_user_campaign = CONCAT(p_user_id, ':', p_campaign_id);

            SET v_membership_id = p_membership_id;
            IF EXISTS (SELECT 1 FROM patreon_memberships WHERE id = v_membership_id) THEN
                SET v_membership_id = CONCAT('pmem-', REPLACE(UUID(), '-', ''));
            END IF;

            INSERT INTO patreon_memberships (
                id, user_id, external_account_id, campaign_id,
                member_id_hash, member_id_fingerprint,
                patreon_user_id_hash, patreon_user_id_fingerprint,
                status, linked_at, last_seen_at, created_at, updated_at, metadata
            ) VALUES (
                v_membership_id, p_user_id, v_existing_external_id, p_campaign_id,
                p_member_id_hash, p_member_id_fingerprint,
                p_provider_sub_hash, p_provider_sub_fingerprint,
                'active', NOW(), NOW(), NOW(), NOW(), p_metadata
            );
        ELSE
            UPDATE patreon_memberships
            SET status = 'active',
                last_seen_at = NOW(),
                updated_at = NOW(),
                metadata = COALESCE(p_metadata, metadata)
            WHERE id = v_membership_id;
        END IF;
    END IF;

    COMMIT;

    SELECT v_existing_external_id AS external_account_id,
           p_user_id AS user_id,
           v_membership_id AS membership_id,
           'linked' AS link_status;
END$$

-- ===================================================================================
-- sp_patreon_relink_account
-- Marks the user's prior active Patreon link as unlinked before a new explicit link.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_relink_account$$
CREATE PROCEDURE sp_patreon_relink_account(
    IN p_user_id VARCHAR(64),
    IN p_unlinked_by VARCHAR(64),
    IN p_reason VARCHAR(64)
)
BEGIN
    UPDATE patreon_memberships
    SET status = 'unlinked',
        unlinked_at = COALESCE(unlinked_at, NOW()),
        unlink_reason = COALESCE(NULLIF(TRIM(p_reason), ''), 'relink_requested'),
        updated_at = NOW()
    WHERE user_id = p_user_id
      AND status IN ('pending','proof_required','active','stale');

    UPDATE user_external_accounts
    SET status = 'unlinked',
        unlinked_at = COALESCE(unlinked_at, NOW()),
        unlinked_by = p_unlinked_by,
        unlink_reason = COALESCE(NULLIF(TRIM(p_reason), ''), 'relink_requested')
    WHERE user_id = p_user_id
      AND provider = 'patreon'
      AND status = 'linked';

    SELECT ROW_COUNT() AS external_accounts_unlinked;
END$$

-- ===================================================================================
-- sp_patreon_unlink_account
-- Soft-unlinks Patreon. It never revokes local sessions; entitlement is projected free.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_unlink_account$$
CREATE PROCEDURE sp_patreon_unlink_account(
    IN p_user_id VARCHAR(64),
    IN p_unlinked_by VARCHAR(64),
    IN p_reason VARCHAR(64),
    IN p_history_id VARCHAR(64)
)
BEGIN
    DECLARE v_external_account_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_membership_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_previous_status VARCHAR(64) DEFAULT NULL;
    DECLARE v_previous_plan_code VARCHAR(64) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT id INTO v_external_account_id
    FROM user_external_accounts
    WHERE user_id = p_user_id
      AND provider = 'patreon'
      AND status = 'linked'
    LIMIT 1
    FOR UPDATE;

    IF v_external_account_id IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon external account is not linked';
    END IF;

    SELECT id INTO v_membership_id
    FROM patreon_memberships
    WHERE user_id = p_user_id
      AND external_account_id = v_external_account_id
      AND status IN ('pending','proof_required','active','stale')
    LIMIT 1
    FOR UPDATE;

    SELECT entitlement_status, plan_code
      INTO v_previous_status, v_previous_plan_code
    FROM patreon_entitlements_current
    WHERE user_id = p_user_id
    LIMIT 1
    FOR UPDATE;

    UPDATE user_external_accounts
    SET status = 'unlinked',
        unlinked_at = NOW(),
        unlinked_by = p_unlinked_by,
        unlink_reason = COALESCE(NULLIF(TRIM(p_reason), ''), 'user_requested')
    WHERE id = v_external_account_id;

    UPDATE patreon_memberships
    SET status = 'unlinked',
        unlinked_at = NOW(),
        unlink_reason = COALESCE(NULLIF(TRIM(p_reason), ''), 'user_requested'),
        updated_at = NOW()
    WHERE id = v_membership_id;

    INSERT INTO patreon_entitlements_current (
        id, user_id, external_account_id, membership_id, entitlement_status,
        link_status, plan_code, tier_code, tier_name, subscription_status,
        last_synced_at, stale_after, sync_source, classification_version,
        safe_metadata, created_at, updated_at
    ) VALUES (
        CONCAT('pec-', REPLACE(UUID(), '-', '')), p_user_id, v_external_account_id, v_membership_id,
        'free', 'unlinked', 'free', NULL, NULL, 'unlinked', NOW(), NULL, 'retention', 1,
        JSON_OBJECT('reason', COALESCE(NULLIF(TRIM(p_reason), ''), 'user_requested')), NOW(), NOW()
    ) ON DUPLICATE KEY UPDATE
        entitlement_status = 'free',
        link_status = 'unlinked',
        plan_code = 'free',
        tier_code = NULL,
        tier_name = NULL,
        subscription_status = 'unlinked',
        last_synced_at = NOW(),
        stale_after = NULL,
        sync_source = 'retention',
        updated_at = NOW();

    INSERT INTO patreon_entitlement_history (
        id, user_id, external_account_id, membership_id,
        previous_status, new_status, previous_plan_code, new_plan_code,
        previous_tier_code, new_tier_code, link_status, reason, sync_source,
        observed_at, created_at, sanitized_metadata
    ) VALUES (
        COALESCE(p_history_id, CONCAT('peh-', REPLACE(UUID(), '-', ''))), p_user_id,
        v_external_account_id, v_membership_id,
        v_previous_status, 'free', v_previous_plan_code, 'free',
        NULL, NULL, 'unlinked', COALESCE(NULLIF(TRIM(p_reason), ''), 'user_requested'), 'unlink',
        NOW(), NOW(), JSON_OBJECT('operation', 'patreon_unlink')
    );

    COMMIT;

    SELECT v_external_account_id AS external_account_id,
           v_membership_id AS membership_id,
           'unlinked' AS link_status;
END$$

-- ===================================================================================
-- sp_patreon_membership_observe
-- Upserts a privacy-minimized membership observation for sync/webhook/link paths.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_membership_observe$$
CREATE PROCEDURE sp_patreon_membership_observe(
    IN p_membership_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_external_account_id VARCHAR(64),
    IN p_campaign_id VARCHAR(64),
    IN p_member_id_hash BINARY(32),
    IN p_member_id_fingerprint CHAR(12),
    IN p_patreon_user_id_hash BINARY(32),
    IN p_patreon_user_id_fingerprint CHAR(12),
    IN p_status VARCHAR(32),
    IN p_metadata JSON
)
BEGIN
    DECLARE v_status VARCHAR(32) DEFAULT COALESCE(p_status, 'pending');
    DECLARE v_membership_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_membership_user_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_membership_external_id VARCHAR(64) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    -- Callers pass the member's canonical id, but the row that matters is the ACTIVE
    -- membership for (campaign, member): after an unlink/relink that is a newer row.
    SELECT id, user_id, external_account_id
      INTO v_membership_id, v_membership_user_id, v_membership_external_id
    FROM patreon_memberships
    WHERE campaign_id = p_campaign_id
      AND active_member_hash = p_member_id_hash
    LIMIT 1
    FOR UPDATE;

    -- The caller resolved the current link authority; an active row owned by an older
    -- link is stale and is retired (kept as history) rather than overwritten.
    IF v_membership_id IS NOT NULL
       AND (v_membership_user_id <> p_user_id OR v_membership_external_id <> p_external_account_id) THEN
        UPDATE patreon_memberships
        SET status = 'unlinked', unlinked_at = NOW(), unlink_reason = 'link_superseded', updated_at = NOW()
        WHERE id = v_membership_id;
        SET v_membership_id = NULL;
    END IF;

    IF v_membership_id IS NULL THEN
        -- Patreon re-creates a member after delete+renew: the old member row is superseded.
        UPDATE patreon_memberships
        SET status = 'unlinked', unlinked_at = NOW(), unlink_reason = 'member_superseded', updated_at = NOW()
        WHERE active_user_campaign = CONCAT(p_user_id, ':', p_campaign_id);

        SET v_membership_id = p_membership_id;
        IF v_membership_id IS NULL OR EXISTS (SELECT 1 FROM patreon_memberships WHERE id = v_membership_id) THEN
            SET v_membership_id = CONCAT('pmem-', REPLACE(UUID(), '-', ''));
        END IF;

        INSERT INTO patreon_memberships (
            id, user_id, external_account_id, campaign_id,
            member_id_hash, member_id_fingerprint,
            patreon_user_id_hash, patreon_user_id_fingerprint,
            status, linked_at, last_seen_at, unlinked_at, created_at, updated_at, metadata
        ) VALUES (
            v_membership_id, p_user_id, p_external_account_id, p_campaign_id,
            p_member_id_hash, p_member_id_fingerprint,
            p_patreon_user_id_hash, p_patreon_user_id_fingerprint,
            v_status, CASE WHEN v_status = 'active' THEN NOW() ELSE NULL END,
            NOW(), CASE WHEN v_status IN ('unlinked','revoked') THEN NOW() ELSE NULL END,
            NOW(), NOW(), p_metadata
        );
    ELSE
        UPDATE patreon_memberships
        SET status = v_status,
            last_seen_at = NOW(),
            unlinked_at = CASE WHEN v_status IN ('unlinked','revoked') THEN COALESCE(unlinked_at, NOW()) ELSE unlinked_at END,
            updated_at = NOW(),
            metadata = COALESCE(p_metadata, metadata)
        WHERE id = v_membership_id;
    END IF;

    COMMIT;

    SELECT v_membership_id AS membership_id,
           v_status AS membership_status;
END$$

-- ===================================================================================
-- sp_patreon_list_active_memberships
-- Active linked memberships, optionally narrowed to a campaign, user, or member hash.
-- Used by source-of-truth reconciliation to find members Patreon no longer returns.
-- Server-only: member hashes never leave the worker.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_list_active_memberships$$
CREATE PROCEDURE sp_patreon_list_active_memberships(
    IN p_campaign_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_member_id_hash BINARY(32)
)
BEGIN
    SELECT pm.id AS membership_id,
           pm.user_id,
           pm.external_account_id,
           pm.campaign_id,
           pm.member_id_hash
    FROM patreon_memberships pm
    INNER JOIN user_external_accounts ea
        ON ea.id = pm.external_account_id
       AND ea.status = 'linked'
    WHERE pm.status IN ('pending','proof_required','active','stale')
      AND (p_campaign_id IS NULL OR pm.campaign_id = p_campaign_id)
      AND (p_user_id IS NULL OR pm.user_id = p_user_id)
      AND (p_member_id_hash IS NULL OR pm.member_id_hash = p_member_id_hash)
    ORDER BY pm.created_at ASC
    LIMIT 5000;
END$$

-- ===================================================================================
-- sp_patreon_entitlement_snapshot_upsert
-- Appends snapshot/history evidence and upserts current normalized entitlement.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_entitlement_snapshot_upsert$$
CREATE PROCEDURE sp_patreon_entitlement_snapshot_upsert(
    IN p_snapshot_id VARCHAR(64),
    IN p_history_id VARCHAR(64),
    IN p_current_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_external_account_id VARCHAR(64),
    IN p_membership_id VARCHAR(64),
    IN p_observed_at DATETIME,
    IN p_sync_source VARCHAR(32),
    IN p_patron_status_normalized VARCHAR(64),
    IN p_tier_hashes_json JSON,
    IN p_last_charge_status_normalized VARCHAR(64),
    IN p_next_charge_at DATETIME,
    IN p_payload_hash BINARY(32),
    IN p_is_complete BOOLEAN,
    IN p_requires_resync BOOLEAN,
    IN p_entitlement_status VARCHAR(32),
    IN p_link_status VARCHAR(32),
    IN p_plan_code VARCHAR(64),
    IN p_tier_code VARCHAR(64),
    IN p_tier_name VARCHAR(120),
    IN p_next_renewal_at DATETIME,
    IN p_grace_period_until DATETIME,
    IN p_stale_after DATETIME,
    IN p_reason VARCHAR(128),
    IN p_safe_metadata JSON
)
BEGIN
    DECLARE v_previous_status VARCHAR(64) DEFAULT NULL;
    DECLARE v_previous_plan_code VARCHAR(64) DEFAULT NULL;
    DECLARE v_previous_tier_code VARCHAR(64) DEFAULT NULL;
    DECLARE v_previous_link_status VARCHAR(64) DEFAULT NULL;
    DECLARE v_previous_membership_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_snapshot_id VARCHAR(64) DEFAULT p_snapshot_id;
    DECLARE v_snapshot_inserted BOOLEAN DEFAULT TRUE;
    DECLARE v_keep_current BOOLEAN DEFAULT FALSE;
    DECLARE v_changed BOOLEAN DEFAULT TRUE;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT entitlement_status, plan_code, tier_code, link_status, membership_id
      INTO v_previous_status, v_previous_plan_code, v_previous_tier_code,
           v_previous_link_status, v_previous_membership_id
    FROM patreon_entitlements_current
    WHERE user_id = p_user_id
    LIMIT 1
    FOR UPDATE;

    INSERT INTO patreon_member_snapshots (
        id, membership_id, observed_at, sync_source, patron_status_normalized,
        tier_hashes_json, last_charge_status_normalized, next_charge_at,
        payload_hash, is_complete, requires_resync, created_at, sanitized_metadata
    ) VALUES (
        p_snapshot_id, p_membership_id, COALESCE(p_observed_at, NOW()), p_sync_source,
        COALESCE(p_patron_status_normalized, 'unknown'), p_tier_hashes_json,
        p_last_charge_status_normalized, p_next_charge_at, p_payload_hash,
        COALESCE(p_is_complete, FALSE), COALESCE(p_requires_resync, FALSE), NOW(), p_safe_metadata
    ) ON DUPLICATE KEY UPDATE
        requires_resync = VALUES(requires_resync),
        sanitized_metadata = COALESCE(VALUES(sanitized_metadata), sanitized_metadata);

    -- An unchanged payload hits uk_patreon_snapshot_payload: history must reference the
    -- snapshot row that already exists, never the id that was not inserted.
    IF ROW_COUNT() <> 1 THEN
        SET v_snapshot_inserted = FALSE;
        SELECT id INTO v_snapshot_id
        FROM patreon_member_snapshots
        WHERE membership_id = p_membership_id
          AND payload_hash = p_payload_hash
        LIMIT 1;
    END IF;

    -- With several campaigns, a non-paid read of one membership must not overwrite a
    -- paid entitlement that another still-active membership of the same user grants.
    IF v_previous_membership_id IS NOT NULL
       AND v_previous_membership_id <> p_membership_id
       AND v_previous_status IN ('active','stale')
       AND COALESCE(v_previous_plan_code, 'free') <> 'free'
       AND COALESCE(p_plan_code, 'free') = 'free'
       AND EXISTS (
           SELECT 1 FROM patreon_memberships
           WHERE id = v_previous_membership_id
             AND status IN ('pending','proof_required','active','stale')
       ) THEN
        SET v_keep_current = TRUE;
    END IF;

    SET v_changed = v_previous_status IS NULL
        OR NOT (v_previous_status <=> COALESCE(p_entitlement_status, 'pending'))
        OR NOT (v_previous_plan_code <=> COALESCE(p_plan_code, 'free'))
        OR NOT (v_previous_tier_code <=> p_tier_code)
        OR NOT (v_previous_link_status <=> COALESCE(p_link_status, 'linked'));

    IF NOT v_keep_current THEN
    INSERT INTO patreon_entitlements_current (
        id, user_id, external_account_id, membership_id, entitlement_status,
        link_status, plan_code, tier_code, tier_name, subscription_status,
        next_renewal_at, grace_period_until, last_synced_at, stale_after,
        sync_source, classification_version, safe_metadata, created_at, updated_at
    ) VALUES (
        COALESCE(p_current_id, CONCAT('pec-', REPLACE(UUID(), '-', ''))), p_user_id,
        p_external_account_id, p_membership_id, COALESCE(p_entitlement_status, 'pending'),
        COALESCE(p_link_status, 'linked'), COALESCE(p_plan_code, 'free'), p_tier_code,
        p_tier_name, p_patron_status_normalized, p_next_renewal_at, p_grace_period_until,
        COALESCE(p_observed_at, NOW()), p_stale_after, p_sync_source, 1,
        p_safe_metadata, NOW(), NOW()
    ) ON DUPLICATE KEY UPDATE
        external_account_id = VALUES(external_account_id),
        membership_id = VALUES(membership_id),
        entitlement_status = VALUES(entitlement_status),
        link_status = VALUES(link_status),
        plan_code = VALUES(plan_code),
        tier_code = VALUES(tier_code),
        tier_name = VALUES(tier_name),
        subscription_status = VALUES(subscription_status),
        next_renewal_at = VALUES(next_renewal_at),
        grace_period_until = VALUES(grace_period_until),
        last_synced_at = VALUES(last_synced_at),
        stale_after = VALUES(stale_after),
        sync_source = VALUES(sync_source),
        safe_metadata = VALUES(safe_metadata),
        updated_at = NOW();

    -- History records transitions (and every tier-map miss, which feeds the
    -- 24h miss metric), not every unchanged sync pass.
    IF v_changed OR p_reason = 'tier_map_miss' THEN
        INSERT INTO patreon_entitlement_history (
            id, user_id, external_account_id, membership_id,
            previous_status, new_status, previous_plan_code, new_plan_code,
            previous_tier_code, new_tier_code, link_status, reason, sync_source,
            observed_at, created_at, sanitized_metadata
        ) VALUES (
            COALESCE(p_history_id, CONCAT('peh-', REPLACE(UUID(), '-', ''))), p_user_id,
            p_external_account_id, p_membership_id,
            v_previous_status, COALESCE(p_entitlement_status, 'pending'),
            v_previous_plan_code, COALESCE(p_plan_code, 'free'),
            v_previous_tier_code, p_tier_code, COALESCE(p_link_status, 'linked'),
            COALESCE(p_reason, 'snapshot_upsert'), p_sync_source,
            COALESCE(p_observed_at, NOW()), NOW(), p_safe_metadata
        );
    END IF;
    END IF;

    IF v_snapshot_inserted OR (v_changed AND NOT v_keep_current) THEN
        INSERT INTO patreon_member_snapshot_history (
            id, membership_id, snapshot_id, event_type, previous_status, new_status,
            sync_source, observed_at, created_at, sanitized_metadata
        ) VALUES (
            CONCAT('pmsh-', REPLACE(UUID(), '-', '')), p_membership_id, v_snapshot_id,
            'snapshot_observed', v_previous_status, COALESCE(p_entitlement_status, 'pending'),
            p_sync_source, COALESCE(p_observed_at, NOW()), NOW(), p_safe_metadata
        );
    END IF;

    COMMIT;

    SELECT v_snapshot_id AS snapshot_id,
           COALESCE(p_entitlement_status, 'pending') AS entitlement_status,
           COALESCE(p_plan_code, 'free') AS plan_code,
           NOT v_keep_current AS current_updated;
END$$

-- Current entitlement read for S2S; output is normalized and contains no raw Patreon IDs.
DROP PROCEDURE IF EXISTS sp_patreon_get_entitlement_by_user_hash$$
CREATE PROCEDURE sp_patreon_get_entitlement_by_user_hash(
    IN p_user_hash VARCHAR(255)
)
BEGIN
    SELECT u.user_hash,
           COALESCE(pec.external_source, 'patreon') AS external_source,
           COALESCE(pec.entitlement_status, 'free') AS entitlement_status,
           COALESCE(pec.link_status, 'none') AS link_status,
           COALESCE(pec.plan_code, 'free') AS plan_code,
           pec.tier_code,
           pec.tier_name,
           pec.next_renewal_at,
           pec.grace_period_until,
           pec.last_synced_at,
           pec.stale_after,
           pec.classification_version
    FROM users u
    LEFT JOIN patreon_entitlements_current pec ON pec.user_id = u.id
    WHERE u.user_hash = p_user_hash
      AND u.is_active = TRUE
    LIMIT 1;
END$$

-- ===================================================================================
-- sp_patreon_webhook_delivery_record
-- Records webhook idempotency; duplicates return replay without repeating side effects.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_webhook_delivery_record$$
CREATE PROCEDURE sp_patreon_webhook_delivery_record(
    IN p_delivery_id VARCHAR(64),
    IN p_delivery_hash BINARY(32),
    IN p_event_type VARCHAR(80),
    IN p_member_id_hash BINARY(32),
    IN p_campaign_id_hash BINARY(32),
    IN p_raw_body_sha256 BINARY(32),
    IN p_signature_valid BOOLEAN,
    IN p_status VARCHAR(32),
    IN p_sanitized_metadata JSON
)
BEGIN
    DECLARE v_existing_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_existing_status VARCHAR(32) DEFAULT NULL;
    DECLARE v_existing_received_at DATETIME DEFAULT NULL;

    START TRANSACTION;

    SELECT id, status, received_at
      INTO v_existing_id, v_existing_status, v_existing_received_at
    FROM patreon_webhook_deliveries
    WHERE delivery_hash = p_delivery_hash
    LIMIT 1
    FOR UPDATE;

    IF v_existing_id IS NOT NULL
       AND (v_existing_status = 'failed'
            OR (v_existing_status IN ('received','processing')
                AND v_existing_received_at < DATE_SUB(NOW(), INTERVAL 10 MINUTE))) THEN
        -- Patreon redelivers after a non-2xx: a failed (or abandoned) delivery is
        -- processed again instead of being swallowed as a replay.
        UPDATE patreon_webhook_deliveries
        SET status = 'received', processed_at = NULL
        WHERE id = v_existing_id;
        COMMIT;
        SELECT v_existing_id AS delivery_id, 'accepted' AS delivery_status;
    ELSEIF v_existing_id IS NULL THEN
        INSERT INTO patreon_webhook_deliveries (
            id, delivery_hash, event_type, member_id_hash, campaign_id_hash,
            raw_body_sha256, signature_valid, status, received_at, expires_at,
            sanitized_metadata
        ) VALUES (
            p_delivery_id, p_delivery_hash, p_event_type, p_member_id_hash, p_campaign_id_hash,
            p_raw_body_sha256, COALESCE(p_signature_valid, FALSE), COALESCE(p_status, 'received'),
            NOW(), DATE_ADD(NOW(), INTERVAL 90 DAY), p_sanitized_metadata
        );
        COMMIT;
        SELECT p_delivery_id AS delivery_id, 'accepted' AS delivery_status;
    ELSE
        UPDATE patreon_webhook_deliveries
        SET status = CASE WHEN status IN ('processed','replay') THEN 'replay' ELSE status END,
            sanitized_metadata = COALESCE(sanitized_metadata, p_sanitized_metadata)
        WHERE id = v_existing_id;
        COMMIT;
        SELECT v_existing_id AS delivery_id, 'replay' AS delivery_status;
    END IF;
END$$

-- Records the outcome of one delivery so the ledger reflects what actually happened.
DROP PROCEDURE IF EXISTS sp_patreon_webhook_delivery_mark$$
CREATE PROCEDURE sp_patreon_webhook_delivery_mark(
    IN p_delivery_id VARCHAR(64),
    IN p_status VARCHAR(32)
)
BEGIN
    IF p_status NOT IN ('processing','processed','failed','ignored') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unsupported Patreon webhook delivery status';
    END IF;

    UPDATE patreon_webhook_deliveries
    SET status = p_status,
        processed_at = CASE WHEN p_status IN ('processed','failed','ignored') THEN NOW() ELSE processed_at END
    WHERE id = p_delivery_id;

    SELECT p_delivery_id AS delivery_id, p_status AS delivery_status, ROW_COUNT() AS rows_updated;
END$$

-- ===================================================================================
-- sp_patreon_sync_job_enqueue / claim / complete
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_sync_job_enqueue$$
CREATE PROCEDURE sp_patreon_sync_job_enqueue(
    IN p_job_id VARCHAR(64),
    IN p_job_type VARCHAR(32),
    IN p_campaign_id VARCHAR(64),
    IN p_member_id_hash BINARY(32),
    IN p_user_id VARCHAR(64),
    IN p_dedupe_key_hash BINARY(32),
    IN p_priority TINYINT,
    IN p_not_before DATETIME,
    IN p_source VARCHAR(32),
    IN p_sanitized_metadata JSON
)
BEGIN
    DECLARE v_job_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_status VARCHAR(32) DEFAULT NULL;

    INSERT INTO patreon_sync_jobs (
        id, job_type, campaign_id, member_id_hash, user_id, dedupe_key_hash,
        status, priority, not_before, attempts, max_attempts, source,
        created_at, updated_at, sanitized_metadata
    ) VALUES (
        p_job_id, p_job_type, p_campaign_id, p_member_id_hash, p_user_id, p_dedupe_key_hash,
        'pending', COALESCE(p_priority, 5), COALESCE(p_not_before, NOW()), 0, 8, p_source,
        NOW(), NOW(), p_sanitized_metadata
    ) ON DUPLICATE KEY UPDATE
        not_before = LEAST(not_before, COALESCE(VALUES(not_before), not_before)),
        priority = LEAST(priority, VALUES(priority)),
        -- A request that lands while the same job is running must not be lost: the
        -- running job re-queues itself once it completes (sp_patreon_sync_job_complete).
        sanitized_metadata = CASE
            WHEN status = 'running'
                THEN JSON_SET(COALESCE(sanitized_metadata, JSON_OBJECT()), '$.rerun_requested', TRUE)
            ELSE sanitized_metadata
        END,
        updated_at = NOW();

    SELECT id, status INTO v_job_id, v_status
    FROM patreon_sync_jobs
    WHERE id = p_job_id;

    IF v_job_id IS NULL THEN
        -- Deduplicated into an active job: report THAT job so callers can find it.
        SELECT id, status INTO v_job_id, v_status
        FROM patreon_sync_jobs
        WHERE active_dedupe_key_hash = p_dedupe_key_hash
        LIMIT 1;
        SELECT v_job_id AS job_id, 'deduplicated' AS job_status, v_status AS existing_status;
    ELSE
        SELECT v_job_id AS job_id, 'enqueued' AS job_status, v_status AS existing_status;
    END IF;
END$$

DROP PROCEDURE IF EXISTS sp_patreon_sync_job_claim$$
CREATE PROCEDURE sp_patreon_sync_job_claim(
    IN p_worker_id VARCHAR(128),
    IN p_limit INT,
    IN p_lease_seconds INT
)
BEGIN
    START TRANSACTION;

    -- A job whose lease expired after its last allowed attempt is failed, not re-run.
    UPDATE patreon_sync_jobs
    SET status = 'failed',
        completed_at = NOW(),
        claimed_by = NULL,
        lease_until = NULL,
        last_error_redacted = COALESCE(last_error_redacted, 'lease_expired_after_max_attempts'),
        updated_at = NOW()
    WHERE status = 'running'
      AND lease_until IS NOT NULL
      AND lease_until < NOW()
      AND attempts >= max_attempts;

    DROP TEMPORARY TABLE IF EXISTS tmp_patreon_sync_claim_ids;
    CREATE TEMPORARY TABLE tmp_patreon_sync_claim_ids (id VARCHAR(64) NOT NULL PRIMARY KEY) ENGINE=MEMORY;

    INSERT INTO tmp_patreon_sync_claim_ids (id)
    SELECT id
    FROM patreon_sync_jobs
    WHERE (status IN ('pending','retry') AND not_before <= NOW())
       OR (status = 'running' AND lease_until IS NOT NULL AND lease_until < NOW())
    ORDER BY priority ASC, created_at ASC
    LIMIT p_limit
    FOR UPDATE SKIP LOCKED;

    UPDATE patreon_sync_jobs psj
    JOIN tmp_patreon_sync_claim_ids tmp ON tmp.id = psj.id
    SET psj.status = 'running',
        psj.claimed_by = p_worker_id,
        psj.claimed_at = NOW(),
        psj.lease_until = DATE_ADD(NOW(), INTERVAL p_lease_seconds SECOND),
        psj.attempts = psj.attempts + 1,
        psj.updated_at = NOW();

    COMMIT;

    SELECT psj.*
    FROM patreon_sync_jobs psj
    JOIN tmp_patreon_sync_claim_ids tmp ON tmp.id = psj.id
    ORDER BY psj.priority ASC, psj.created_at ASC;

    DROP TEMPORARY TABLE IF EXISTS tmp_patreon_sync_claim_ids;
END$$

DROP PROCEDURE IF EXISTS sp_patreon_sync_job_complete$$
CREATE PROCEDURE sp_patreon_sync_job_complete(
    IN p_job_id VARCHAR(64),
    IN p_status VARCHAR(32),
    IN p_retry_after_seconds INT,
    IN p_last_error_redacted TEXT
)
BEGIN
    DECLARE v_rerun BOOLEAN DEFAULT FALSE;

    -- A completed job that received a new request while running goes back to pending
    -- in the same statement, so it never leaves the active dedupe set in between.
    SELECT p_status = 'completed'
           AND COALESCE(JSON_UNQUOTE(JSON_EXTRACT(sanitized_metadata, '$.rerun_requested')), 'false') = 'true'
      INTO v_rerun
    FROM patreon_sync_jobs
    WHERE id = p_job_id;

    UPDATE patreon_sync_jobs
    SET status = CASE WHEN v_rerun THEN 'pending' ELSE p_status END,
        completed_at = CASE
            WHEN v_rerun THEN NULL
            WHEN p_status IN ('completed','failed','cancelled') THEN NOW()
            ELSE completed_at
        END,
        not_before = CASE
            WHEN v_rerun THEN NOW()
            WHEN p_status = 'retry' THEN DATE_ADD(NOW(), INTERVAL COALESCE(p_retry_after_seconds, 60) SECOND)
            ELSE not_before
        END,
        attempts = CASE WHEN v_rerun THEN 0 ELSE attempts END,
        last_error_redacted = p_last_error_redacted,
        claimed_by = CASE WHEN v_rerun OR p_status IN ('pending','retry','completed','failed','cancelled') THEN NULL ELSE claimed_by END,
        lease_until = CASE WHEN v_rerun OR p_status IN ('pending','retry','completed','failed','cancelled') THEN NULL ELSE lease_until END,
        sanitized_metadata = CASE WHEN v_rerun THEN JSON_REMOVE(sanitized_metadata, '$.rerun_requested') ELSE sanitized_metadata END,
        updated_at = NOW()
    WHERE id = p_job_id;

    SELECT p_job_id AS job_id, CASE WHEN v_rerun THEN 'pending' ELSE p_status END AS job_status;
END$$

-- ===================================================================================
-- Campaign / tier-map catalog. The server-only tier-map config is the classification
-- authority; the runtime mirrors it here (HMAC/fingerprints only) so memberships can
-- reference their campaign and the ROOT dashboard lists the map actually in force.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_catalog_campaign_upsert$$
CREATE PROCEDURE sp_patreon_catalog_campaign_upsert(
    IN p_campaign_db_id VARCHAR(64),
    IN p_campaign_id_hash BINARY(32),
    IN p_campaign_id_fingerprint CHAR(12),
    IN p_display_name VARCHAR(120),
    IN p_enabled BOOLEAN
)
BEGIN
    INSERT INTO patreon_campaigns (
        id, campaign_id_hash, campaign_id_fingerprint, display_name,
        status, enabled, created_at, updated_at, metadata
    ) VALUES (
        p_campaign_db_id, p_campaign_id_hash, p_campaign_id_fingerprint, p_display_name,
        CASE WHEN p_enabled THEN 'enabled' ELSE 'disabled' END, p_enabled, NOW(), NOW(),
        JSON_OBJECT('source', 'runtime_tier_map_config')
    ) ON DUPLICATE KEY UPDATE
        display_name = COALESCE(VALUES(display_name), display_name),
        status = VALUES(status),
        enabled = VALUES(enabled),
        updated_at = NOW();

    SELECT p_campaign_db_id AS campaign_id;
END$$

DROP PROCEDURE IF EXISTS sp_patreon_catalog_tier_upsert$$
CREATE PROCEDURE sp_patreon_catalog_tier_upsert(
    IN p_tier_db_id VARCHAR(64),
    IN p_campaign_db_id VARCHAR(64),
    IN p_tier_id_hash BINARY(32),
    IN p_tier_id_fingerprint CHAR(12),
    IN p_plan_code VARCHAR(64),
    IN p_tier_code VARCHAR(64),
    IN p_tier_name VARCHAR(120),
    IN p_priority INT,
    IN p_active BOOLEAN
)
BEGIN
    INSERT INTO patreon_tier_map (
        id, campaign_id, tier_id_hash, tier_id_fingerprint,
        plan_code, tier_code, tier_name, priority, active,
        effective_from, created_at, updated_at, metadata
    ) VALUES (
        p_tier_db_id, p_campaign_db_id, p_tier_id_hash, p_tier_id_fingerprint,
        p_plan_code, p_tier_code, p_tier_name, COALESCE(p_priority, 0), p_active,
        NOW(), NOW(), NOW(), JSON_OBJECT('source', 'runtime_tier_map_config')
    ) ON DUPLICATE KEY UPDATE
        plan_code = VALUES(plan_code),
        tier_code = VALUES(tier_code),
        tier_name = VALUES(tier_name),
        priority = VALUES(priority),
        active = VALUES(active),
        effective_until = NULL,
        updated_at = NOW();

    SELECT p_tier_db_id AS tier_map_id;
END$$

-- Deactivates catalog rows that are no longer configured. Nothing is deleted:
-- memberships keep referencing their campaign and history stays intact.
DROP PROCEDURE IF EXISTS sp_patreon_catalog_retire_missing$$
CREATE PROCEDURE sp_patreon_catalog_retire_missing(
    IN p_campaign_ids JSON,
    IN p_tier_map_ids JSON
)
BEGIN
    DECLARE v_tiers INT DEFAULT 0;
    DECLARE v_campaigns INT DEFAULT 0;

    UPDATE patreon_tier_map
    SET active = FALSE, updated_at = NOW()
    WHERE active = TRUE
      AND NOT JSON_CONTAINS(COALESCE(p_tier_map_ids, JSON_ARRAY()), JSON_QUOTE(id));
    SET v_tiers = ROW_COUNT();

    UPDATE patreon_campaigns
    SET enabled = FALSE, status = 'disabled', updated_at = NOW()
    WHERE enabled = TRUE
      AND NOT JSON_CONTAINS(COALESCE(p_campaign_ids, JSON_ARRAY()), JSON_QUOTE(id));
    SET v_campaigns = ROW_COUNT();

    SELECT v_tiers AS tier_map_rows_retired, v_campaigns AS campaigns_retired;
END$$

-- ===================================================================================
-- Token state and raw-payload quarantine helpers. State is global/server-only.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_provider_token_state_upsert$$
CREATE PROCEDURE sp_patreon_provider_token_state_upsert(
    IN p_token_state_id VARCHAR(64),
    IN p_access_token_ciphertext LONGBLOB,
    IN p_refresh_token_ciphertext LONGBLOB,
    IN p_token_fingerprint CHAR(12),
    IN p_encryption_key_id VARCHAR(128),
    IN p_expires_at DATETIME,
    IN p_status VARCHAR(32),
    IN p_last_error_redacted TEXT
)
BEGIN
    INSERT INTO patreon_provider_token_state (
        id, provider, token_kind, access_token_ciphertext, refresh_token_ciphertext,
        token_fingerprint, encryption_key_id, expires_at, refreshed_at, rotated_at,
        status, last_error_redacted, created_at, updated_at
    ) VALUES (
        p_token_state_id, 'patreon', 'creator', p_access_token_ciphertext, p_refresh_token_ciphertext,
        p_token_fingerprint, p_encryption_key_id, p_expires_at, NOW(), NOW(),
        COALESCE(p_status, 'disabled'), p_last_error_redacted, NOW(), NOW()
    ) ON DUPLICATE KEY UPDATE
        -- A failure write carries no token material: keep the last good encrypted
        -- tokens so the next refresh (or a restart) can still use them.
        refreshed_at = CASE WHEN VALUES(access_token_ciphertext) IS NOT NULL THEN NOW() ELSE refreshed_at END,
        rotated_at = CASE WHEN VALUES(refresh_token_ciphertext) IS NOT NULL THEN NOW() ELSE rotated_at END,
        access_token_ciphertext = COALESCE(VALUES(access_token_ciphertext), access_token_ciphertext),
        refresh_token_ciphertext = COALESCE(VALUES(refresh_token_ciphertext), refresh_token_ciphertext),
        token_fingerprint = COALESCE(VALUES(token_fingerprint), token_fingerprint),
        encryption_key_id = VALUES(encryption_key_id),
        expires_at = CASE WHEN VALUES(access_token_ciphertext) IS NOT NULL THEN VALUES(expires_at) ELSE expires_at END,
        status = VALUES(status),
        last_error_redacted = VALUES(last_error_redacted),
        updated_at = NOW();

    SELECT 'upserted' AS token_state_status;
END$$

DROP PROCEDURE IF EXISTS sp_patreon_provider_token_state_get$$
CREATE PROCEDURE sp_patreon_provider_token_state_get()
BEGIN
    SELECT id, provider, token_kind, token_fingerprint, encryption_key_id,
           expires_at, refreshed_at, rotated_at, status, last_error_redacted,
           created_at, updated_at
    FROM patreon_provider_token_state
    WHERE provider = 'patreon'
      AND token_kind = 'creator'
    LIMIT 1;
END$$

-- Server-only read of the encrypted creator-token state so a restarted process uses the
-- last refreshed token instead of the (possibly rotated-out) bootstrap env value. Never
-- exposed through health, admin, or S2S surfaces.
DROP PROCEDURE IF EXISTS sp_patreon_provider_token_state_get_encrypted$$
CREATE PROCEDURE sp_patreon_provider_token_state_get_encrypted()
BEGIN
    SELECT access_token_ciphertext, refresh_token_ciphertext, encryption_key_id,
           expires_at, refreshed_at, status
    FROM patreon_provider_token_state
    WHERE provider = 'patreon'
      AND token_kind = 'creator'
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_patreon_raw_payload_quarantine_insert$$
CREATE PROCEDURE sp_patreon_raw_payload_quarantine_insert(
    IN p_quarantine_id VARCHAR(64),
    IN p_payload_hash BINARY(32),
    IN p_source VARCHAR(32),
    IN p_payload_ciphertext LONGBLOB,
    IN p_encryption_key_id VARCHAR(128),
    IN p_capture_reason VARCHAR(128),
    IN p_retention_days INT,
    IN p_created_by VARCHAR(64),
    IN p_sanitized_metadata JSON
)
BEGIN
    IF p_retention_days IS NULL OR p_retention_days < 1 OR p_retention_days > 30 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon raw payload retention must be 1-30 days';
    END IF;

    INSERT INTO patreon_raw_payload_quarantine (
        id, payload_hash, source, payload_ciphertext, encryption_key_id,
        capture_reason, received_at, purge_at, created_by, sanitized_metadata
    ) VALUES (
        p_quarantine_id, p_payload_hash, p_source, p_payload_ciphertext, p_encryption_key_id,
        p_capture_reason, NOW(), DATE_ADD(NOW(), INTERVAL p_retention_days DAY), p_created_by,
        p_sanitized_metadata
    );

    SELECT p_quarantine_id AS quarantine_id, 'quarantined' AS quarantine_status;
END$$

-- ===================================================================================
-- sp_patreon_retention_purge
-- Purges bounded proof/webhook/quarantine artifacts only. Link/snapshot/unlink history
-- is retained indefinitely and is never destructively deleted here.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_patreon_retention_purge$$
CREATE PROCEDURE sp_patreon_retention_purge(
    IN p_proof_retention_after_expiry_hours INT,
    IN p_webhook_delivery_retention_days INT,
    IN p_sync_job_retention_days INT
)
BEGIN
    DECLARE v_proof_rows INT DEFAULT 0;
    DECLARE v_webhook_rows INT DEFAULT 0;
    DECLARE v_raw_rows INT DEFAULT 0;
    DECLARE v_sync_job_rows INT DEFAULT 0;
    -- Configured windows may only shorten the documented caps (24h / 90d), never extend them.
    DECLARE v_proof_hours INT DEFAULT LEAST(GREATEST(COALESCE(p_proof_retention_after_expiry_hours, 24), 0), 24);
    DECLARE v_webhook_days INT DEFAULT LEAST(GREATEST(COALESCE(p_webhook_delivery_retention_days, 90), 1), 90);
    DECLARE v_sync_job_days INT DEFAULT LEAST(GREATEST(COALESCE(p_sync_job_retention_days, 30), 1), 365);

    DELETE FROM patreon_link_proofs
    WHERE purge_after_at <= NOW()
       OR (expires_at <= DATE_SUB(NOW(), INTERVAL v_proof_hours HOUR));
    SET v_proof_rows = ROW_COUNT();

    DELETE FROM patreon_webhook_deliveries
    WHERE expires_at <= NOW()
       OR received_at <= DATE_SUB(NOW(), INTERVAL v_webhook_days DAY);
    SET v_webhook_rows = ROW_COUNT();

    -- Finished sync jobs are operational noise, not history; active jobs are untouched.
    DELETE FROM patreon_sync_jobs
    WHERE status IN ('completed','failed','cancelled')
      AND COALESCE(completed_at, updated_at, created_at) <= DATE_SUB(NOW(), INTERVAL v_sync_job_days DAY);
    SET v_sync_job_rows = ROW_COUNT();

    UPDATE patreon_raw_payload_quarantine
    SET payload_ciphertext = '',
        purged_at = NOW(),
        sanitized_metadata = JSON_OBJECT('retention', 'purged')
    WHERE purged_at IS NULL
      AND purge_at <= NOW();
    SET v_raw_rows = ROW_COUNT();

    SELECT v_proof_rows AS proof_requests_purged,
           v_webhook_rows AS webhook_delivery_hashes_purged,
           v_raw_rows AS raw_payloads_purged,
           v_sync_job_rows AS sync_jobs_purged,
           'link_snapshot_unlink_history_preserved_indefinitely' AS history_retention_status;
END$$

-- ===================================================================================
-- ROOT admin read surface (dashboard management)
-- Paginated, non-secret list procedures for the ROOT-only /admin/patreon endpoints.
-- These deliberately SELECT only normalized, non-secret columns: never *_hash binary
-- columns, raw_body_sha256, dedupe_key_hash, last_error_redacted text, or *_metadata
-- blobs. Each follows the two-result-set pattern (page rows, then a total_count scalar)
-- mirroring sp_billing_group_list so the dashboard pagination contract lines up.
-- ===================================================================================

-- List current Patreon entitlements across users (keyed on the non-secret user_hash so
-- the dashboard can link a row back to its existing user pages and per-user resync).
DROP PROCEDURE IF EXISTS sp_patreon_admin_list_entitlements$$
CREATE PROCEDURE sp_patreon_admin_list_entitlements(
    IN p_status VARCHAR(32),
    IN p_plan_code VARCHAR(64),
    IN p_link_status VARCHAR(32),
    IN p_search VARCHAR(255),
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    SELECT SQL_CALC_FOUND_ROWS
           u.user_hash,
           u.username AS display_name,
           COALESCE(pec.entitlement_status, 'free') AS entitlement_status,
           COALESCE(pec.link_status, 'none') AS link_status,
           COALESCE(pec.plan_code, 'free') AS plan_code,
           pec.tier_code,
           pec.tier_name,
           pec.next_renewal_at,
           pec.last_synced_at,
           pec.stale_after,
           pec.updated_at
    FROM patreon_entitlements_current pec
    JOIN users u ON u.id = pec.user_id
    WHERE (p_status IS NULL OR p_status = '' OR pec.entitlement_status = p_status)
      AND (p_plan_code IS NULL OR p_plan_code = '' OR pec.plan_code = p_plan_code)
      AND (p_link_status IS NULL OR p_link_status = '' OR pec.link_status = p_link_status)
      AND (
          p_search IS NULL OR p_search = ''
          OR u.user_hash = p_search
          OR u.username LIKE CONCAT(REPLACE(REPLACE(p_search, '%', '\\%'), '_', '\\_'), '%')
          OR u.email LIKE CONCAT(REPLACE(REPLACE(p_search, '%', '\\%'), '_', '\\_'), '%')
      )
    ORDER BY pec.updated_at DESC, pec.created_at DESC
    LIMIT p_limit OFFSET p_offset;

    SELECT FOUND_ROWS() AS total_count;
END$$

-- One user's entitlement transitions, newest first. Normalized columns only: no hashes,
-- payload digests, provider ids or metadata blobs.
DROP PROCEDURE IF EXISTS sp_patreon_admin_entitlement_history$$
CREATE PROCEDURE sp_patreon_admin_entitlement_history(
    IN p_user_hash VARCHAR(255),
    IN p_limit INT
)
BEGIN
    SELECT peh.id AS history_id,
           peh.previous_status,
           peh.new_status,
           peh.previous_plan_code,
           peh.new_plan_code,
           peh.previous_tier_code,
           peh.new_tier_code,
           peh.link_status,
           peh.reason,
           peh.sync_source,
           peh.observed_at
    FROM patreon_entitlement_history peh
    JOIN users u ON u.id = peh.user_id
    WHERE u.user_hash = p_user_hash
    ORDER BY peh.observed_at DESC, peh.created_at DESC
    LIMIT p_limit;
END$$

-- List configured tier-map entries from the durable DB table (NOT server config), so
-- only fingerprints + internal plan/tier codes are exposed, never raw campaign/tier IDs.
DROP PROCEDURE IF EXISTS sp_patreon_admin_list_tier_map$$
CREATE PROCEDURE sp_patreon_admin_list_tier_map(
    IN p_active TINYINT,
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    SELECT SQL_CALC_FOUND_ROWS
           pc.campaign_id_fingerprint AS campaign_fingerprint,
           pc.display_name AS campaign_name,
           tm.tier_id_fingerprint AS tier_fingerprint,
           tm.plan_code,
           tm.tier_code,
           tm.tier_name,
           tm.priority,
           tm.active,
           tm.effective_from,
           tm.effective_until
    FROM patreon_tier_map tm
    JOIN patreon_campaigns pc ON pc.id = tm.campaign_id
    WHERE (p_active IS NULL OR tm.active = p_active)
    ORDER BY tm.priority ASC, tm.effective_from DESC
    LIMIT p_limit OFFSET p_offset;

    SELECT FOUND_ROWS() AS total_count;
END$$

-- List sync jobs for operational monitoring. Errors are reduced to a boolean has_error
-- flag only; the raw redacted error text and dedupe/member hashes are never returned.
DROP PROCEDURE IF EXISTS sp_patreon_admin_list_sync_jobs$$
CREATE PROCEDURE sp_patreon_admin_list_sync_jobs(
    IN p_status VARCHAR(32),
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    SELECT SQL_CALC_FOUND_ROWS
           id AS job_id,
           job_type,
           status,
           priority,
           attempts,
           max_attempts,
           not_before,
           source,
           created_at,
           updated_at,
           completed_at,
           (last_error_redacted IS NOT NULL) AS has_error
    FROM patreon_sync_jobs
    WHERE (p_status IS NULL OR p_status = '' OR status = p_status)
    ORDER BY created_at DESC
    LIMIT p_limit OFFSET p_offset;

    SELECT FOUND_ROWS() AS total_count;
END$$

-- List webhook deliveries for monitoring. Never returns delivery_hash, member/campaign
-- hashes, raw_body_sha256, or sanitized_metadata.
DROP PROCEDURE IF EXISTS sp_patreon_admin_list_webhooks$$
CREATE PROCEDURE sp_patreon_admin_list_webhooks(
    IN p_status VARCHAR(32),
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    SELECT SQL_CALC_FOUND_ROWS
           id AS delivery_id,
           event_type,
           status,
           signature_valid,
           received_at,
           processed_at
    FROM patreon_webhook_deliveries
    WHERE (p_status IS NULL OR p_status = '' OR status = p_status)
    ORDER BY received_at DESC
    LIMIT p_limit OFFSET p_offset;

    SELECT FOUND_ROWS() AS total_count;
END$$

DELIMITER ;

-- ===================================================================================
-- PATREON STORED PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Patreon entitlement stored procedures created!' AS status,
       'Procedures for proof, link/unlink/relink, membership, current/history, webhooks, sync, token state, quarantine, retention, reconciliation, and ROOT admin reads' AS details;
