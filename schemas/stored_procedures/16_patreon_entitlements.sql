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
        SET v_result = v_status;
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
        INSERT INTO patreon_memberships (
            id, user_id, external_account_id, campaign_id,
            member_id_hash, member_id_fingerprint,
            patreon_user_id_hash, patreon_user_id_fingerprint,
            status, linked_at, last_seen_at, created_at, updated_at, metadata
        ) VALUES (
            p_membership_id, p_user_id, v_existing_external_id, p_campaign_id,
            p_member_id_hash, p_member_id_fingerprint,
            p_provider_sub_hash, p_provider_sub_fingerprint,
            'active', NOW(), NOW(), NOW(), NOW(), p_metadata
        ) ON DUPLICATE KEY UPDATE
            status = 'active',
            last_seen_at = NOW(),
            unlinked_at = NULL,
            unlink_reason = NULL,
            updated_at = NOW(),
            metadata = COALESCE(VALUES(metadata), metadata);
    END IF;

    COMMIT;

    SELECT v_existing_external_id AS external_account_id,
           p_user_id AS user_id,
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
    INSERT INTO patreon_memberships (
        id, user_id, external_account_id, campaign_id,
        member_id_hash, member_id_fingerprint,
        patreon_user_id_hash, patreon_user_id_fingerprint,
        status, linked_at, last_seen_at, created_at, updated_at, metadata
    ) VALUES (
        p_membership_id, p_user_id, p_external_account_id, p_campaign_id,
        p_member_id_hash, p_member_id_fingerprint,
        p_patreon_user_id_hash, p_patreon_user_id_fingerprint,
        COALESCE(p_status, 'pending'), CASE WHEN p_status = 'active' THEN NOW() ELSE NULL END,
        NOW(), NOW(), NOW(), p_metadata
    ) ON DUPLICATE KEY UPDATE
        status = COALESCE(p_status, status),
        last_seen_at = NOW(),
        updated_at = NOW(),
        metadata = COALESCE(VALUES(metadata), metadata);

    SELECT p_membership_id AS membership_id,
           COALESCE(p_status, 'pending') AS membership_status;
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

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    START TRANSACTION;

    SELECT entitlement_status, plan_code, tier_code
      INTO v_previous_status, v_previous_plan_code, v_previous_tier_code
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

    INSERT INTO patreon_member_snapshot_history (
        id, membership_id, snapshot_id, event_type, previous_status, new_status,
        sync_source, observed_at, created_at, sanitized_metadata
    ) VALUES (
        CONCAT('pmsh-', REPLACE(UUID(), '-', '')), p_membership_id, p_snapshot_id,
        'snapshot_observed', v_previous_status, COALESCE(p_entitlement_status, 'pending'),
        p_sync_source, COALESCE(p_observed_at, NOW()), NOW(), p_safe_metadata
    );

    COMMIT;

    SELECT p_snapshot_id AS snapshot_id,
           COALESCE(p_entitlement_status, 'pending') AS entitlement_status,
           COALESCE(p_plan_code, 'free') AS plan_code;
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

    START TRANSACTION;

    SELECT id, status
      INTO v_existing_id, v_existing_status
    FROM patreon_webhook_deliveries
    WHERE delivery_hash = p_delivery_hash
    LIMIT 1
    FOR UPDATE;

    IF v_existing_id IS NULL THEN
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
        updated_at = NOW();

    SELECT p_job_id AS job_id, 'enqueued' AS job_status;
END$$

DROP PROCEDURE IF EXISTS sp_patreon_sync_job_claim$$
CREATE PROCEDURE sp_patreon_sync_job_claim(
    IN p_worker_id VARCHAR(128),
    IN p_limit INT,
    IN p_lease_seconds INT
)
BEGIN
    START TRANSACTION;

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
    UPDATE patreon_sync_jobs
    SET status = p_status,
        completed_at = CASE WHEN p_status IN ('completed','failed','cancelled') THEN NOW() ELSE completed_at END,
        not_before = CASE WHEN p_status = 'retry' THEN DATE_ADD(NOW(), INTERVAL COALESCE(p_retry_after_seconds, 60) SECOND) ELSE not_before END,
        last_error_redacted = p_last_error_redacted,
        claimed_by = CASE WHEN p_status IN ('pending','retry','completed','failed','cancelled') THEN NULL ELSE claimed_by END,
        lease_until = CASE WHEN p_status IN ('pending','retry','completed','failed','cancelled') THEN NULL ELSE lease_until END,
        updated_at = NOW()
    WHERE id = p_job_id;

    SELECT p_job_id AS job_id, p_status AS job_status;
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
        access_token_ciphertext = VALUES(access_token_ciphertext),
        refresh_token_ciphertext = VALUES(refresh_token_ciphertext),
        token_fingerprint = VALUES(token_fingerprint),
        encryption_key_id = VALUES(encryption_key_id),
        expires_at = VALUES(expires_at),
        refreshed_at = NOW(),
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
CREATE PROCEDURE sp_patreon_retention_purge()
BEGIN
    DECLARE v_proof_rows INT DEFAULT 0;
    DECLARE v_webhook_rows INT DEFAULT 0;
    DECLARE v_raw_rows INT DEFAULT 0;

    DELETE FROM patreon_link_proofs
    WHERE purge_after_at <= NOW()
       OR (expires_at <= DATE_SUB(NOW(), INTERVAL 24 HOUR));
    SET v_proof_rows = ROW_COUNT();

    DELETE FROM patreon_webhook_deliveries
    WHERE expires_at <= NOW()
       OR received_at <= DATE_SUB(NOW(), INTERVAL 90 DAY);
    SET v_webhook_rows = ROW_COUNT();

    UPDATE patreon_raw_payload_quarantine
    SET payload_ciphertext = '',
        purged_at = NOW(),
        sanitized_metadata = JSON_OBJECT('retention', 'purged')
    WHERE purged_at IS NULL
      AND purge_at <= NOW();
    SET v_raw_rows = ROW_COUNT();

    SELECT v_proof_rows AS proof_requests_purged_after_expiry_plus_24h,
           v_webhook_rows AS webhook_delivery_hashes_purged_after_90d,
           v_raw_rows AS raw_payload_quarantine_rows_purged_after_max_30d,
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
           pec.last_synced_at,
           pec.updated_at
    FROM patreon_entitlements_current pec
    JOIN users u ON u.id = pec.user_id
    WHERE (p_status IS NULL OR p_status = '' OR pec.entitlement_status = p_status)
      AND (p_plan_code IS NULL OR p_plan_code = '' OR pec.plan_code = p_plan_code)
    ORDER BY pec.updated_at DESC, pec.created_at DESC
    LIMIT p_limit OFFSET p_offset;

    SELECT FOUND_ROWS() AS total_count;
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
       '21 procedures for proof, link/unlink/relink, membership, current/history, webhooks, sync, token state, quarantine, retention, and ROOT admin list reads' AS details;
