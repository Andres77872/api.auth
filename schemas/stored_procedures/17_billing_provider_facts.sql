-- ===================================================================================
-- Provider-Agnostic Billing Provider Fact Procedures
-- ===================================================================================
-- Procedures mirror the additive billing_* table family. They never issue local
-- sessions, never mutate JWT/session/cookie state, and never return raw provider refs
-- to consumer-facing callers. Operational refs are accepted only as encrypted
-- ciphertext plus HMAC/fingerprint companions.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- sp_billing_resolve_user_project
-- Resolve an active user/project scope through the existing groups-of-groups access
-- view. No billing state is required for this procedure to return a scope.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_resolve_user_project$$
CREATE PROCEDURE sp_billing_resolve_user_project(
    IN p_user_hash VARCHAR(255),
    IN p_project_hash VARCHAR(255)
)
BEGIN
    SELECT vupa.user_id,
           vupa.project_id,
           vupa.user_hash,
           vupa.project_hash,
           vupa.access_type
    FROM v_user_project_access vupa
    WHERE vupa.user_hash = p_user_hash
      AND vupa.project_hash = p_project_hash
    LIMIT 1;
END$$

-- ===================================================================================
-- sp_billing_get_current_by_user_project
-- Safe S2S read shape. Resolves the project to its billing group, then reads the
-- group-scoped entitlement. Missing billing group / state returns a free default.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_get_current_by_user_project$$
CREATE PROCEDURE sp_billing_get_current_by_user_project(
    IN p_user_hash VARCHAR(255),
    IN p_project_hash VARCHAR(255),
    IN p_provider VARCHAR(32)
)
BEGIN
    SELECT vupa.user_hash,
           vupa.project_hash,
           bg.billing_group_id,
           bg.billing_group_hash,
           COALESCE(bec.provider, COALESCE(NULLIF(TRIM(p_provider), ''), 'stripe')) AS provider,
           COALESCE(bec.status, 'free') AS status,
           COALESCE(bec.plan_code, 'free') AS plan_code,
           bec.tier_code,
           bec.tier_name,
           COALESCE(bec.link_status, 'none') AS link_status,
           COALESCE(bec.cancel_at_period_end, FALSE) AS cancel_at_period_end,
           bec.current_period_end,
           bec.trial_end,
           bec.last_synced_at,
           bec.stale_after,
           COALESCE(bec.classification_version, 2) AS classification_version,
           2 AS contract_version,
           bc.customer_ref,
           bs.subscription_ref
    FROM v_user_project_access vupa
    LEFT JOIN v_user_billing_group_access bg
      ON bg.user_id = vupa.user_id
     AND bg.project_id = vupa.project_id
    LEFT JOIN billing_entitlements_current bec
      ON bec.user_id = vupa.user_id
     AND bec.billing_group_id = bg.billing_group_id
     AND bec.provider = COALESCE(NULLIF(TRIM(p_provider), ''), 'stripe')
    LEFT JOIN billing_customers bc ON bc.id = bec.customer_id
    LEFT JOIN billing_subscriptions bs ON bs.id = bec.subscription_id
    WHERE vupa.user_hash = p_user_hash
      AND vupa.project_hash = p_project_hash
    LIMIT 1;
END$$

-- ===================================================================================
-- sp_billing_get_session_plan
-- Hot-path projection for /auth/validate's `plan` object. Takes INTERNAL ids (access is
-- already verified by validate_session) and resolves the project to its billing group,
-- returning the subscription entitlement plus a has_billing_group signal. NULL status +
-- has_billing_group=0 => plan state "none"; has_billing_group=1 with no row => "free".
-- Subscriptions only; never returns operational refs.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_get_session_plan$$
CREATE PROCEDURE sp_billing_get_session_plan(
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_provider VARCHAR(32)
)
BEGIN
    SELECT
        COALESCE(NULLIF(TRIM(p_provider), ''), 'stripe') AS provider,
        bgp.billing_group_id AS billing_group_id,
        CASE WHEN bgp.billing_group_id IS NULL THEN 0 ELSE 1 END AS has_billing_group,
        bec.status AS status,
        bec.plan_code AS plan_code,
        bec.tier_code AS tier_code,
        bec.current_period_end AS current_period_end,
        bec.trial_end AS trial_end,
        COALESCE(bec.cancel_at_period_end, FALSE) AS cancel_at_period_end
    FROM (SELECT p_user_id AS user_id, p_project_id AS project_id) s
    LEFT JOIN billing_group_projects bgp
      ON bgp.project_id = s.project_id AND bgp.status = 'active'
    LEFT JOIN billing_entitlements_current bec
      ON bec.user_id = s.user_id
     AND bec.billing_group_id = bgp.billing_group_id
     AND bec.provider = COALESCE(NULLIF(TRIM(p_provider), ''), 'stripe')
    LIMIT 1;
END$$

-- ===================================================================================
-- sp_billing_checkout_intent_begin
-- Begins an idempotent S2S Checkout intent. Same key + same request returns replay;
-- same key + different request returns conflict without provider side effects.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_checkout_intent_begin$$
CREATE PROCEDURE sp_billing_checkout_intent_begin(
    IN p_intent_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_billing_group_id VARCHAR(64),
    IN p_customer_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_checkout_ref VARCHAR(64),
    IN p_subscription_ref VARCHAR(64),
    IN p_purchase_ref VARCHAR(64),
    IN p_intent_type VARCHAR(32),
    IN p_provider_price_ref_type VARCHAR(32),
    IN p_provider_price_ref_hmac BINARY(32),
    IN p_provider_price_ref_fingerprint CHAR(12),
    IN p_idempotency_key_hmac BINARY(32),
    IN p_canonical_request_hash BINARY(32),
    IN p_plan_code VARCHAR(64),
    IN p_tier_code VARCHAR(64),
    IN p_tier_name VARCHAR(120),
    IN p_credit_product_code VARCHAR(64),
    IN p_quantity INT,
    IN p_safe_metadata JSON
)
BEGIN
    DECLARE v_existing_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_existing_status VARCHAR(32) DEFAULT NULL;
    DECLARE v_existing_request_hash BINARY(32) DEFAULT NULL;
    DECLARE v_existing_response LONGTEXT DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF p_idempotency_key_hmac IS NULL OR OCTET_LENGTH(p_idempotency_key_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing checkout idempotency HMAC must be 32 bytes';
    END IF;

    IF p_canonical_request_hash IS NULL OR OCTET_LENGTH(p_canonical_request_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing checkout request hash must be 32 bytes';
    END IF;

    START TRANSACTION;

    -- Idempotency scope mirrors the generated active_idempotency_scope column:
    -- subscriptions dedupe per (provider,user,billing_group); credit purchases per
    -- (provider,user,project).
    SELECT id, status, canonical_request_hash, safe_response_json
      INTO v_existing_id, v_existing_status, v_existing_request_hash, v_existing_response
    FROM billing_checkout_intents
    WHERE provider = p_provider
      AND user_id = p_user_id
      AND idempotency_key_hmac = p_idempotency_key_hmac
      AND status IN ('pending','completed')
      AND (
            (p_intent_type = 'subscription' AND billing_group_id = p_billing_group_id)
            OR (p_intent_type <> 'subscription' AND project_id = p_project_id)
          )
    LIMIT 1
    FOR UPDATE;

    IF v_existing_id IS NULL THEN
        INSERT INTO billing_checkout_intents (
            id, user_id, project_id, billing_group_id, customer_id, provider, checkout_ref,
            subscription_ref, purchase_ref, intent_type, provider_price_ref_type,
            provider_price_ref_hmac, provider_price_ref_fingerprint,
            idempotency_key_hmac, canonical_request_hash, plan_code, tier_code,
            tier_name, credit_product_code, quantity, status, created_at, updated_at,
            safe_metadata
        ) VALUES (
            p_intent_id, p_user_id, p_project_id, p_billing_group_id, p_customer_id, p_provider, p_checkout_ref,
            p_subscription_ref, p_purchase_ref, p_intent_type, p_provider_price_ref_type,
            p_provider_price_ref_hmac, p_provider_price_ref_fingerprint,
            p_idempotency_key_hmac, p_canonical_request_hash, p_plan_code, p_tier_code,
            p_tier_name, p_credit_product_code, COALESCE(p_quantity, 1), 'pending', NOW(), NOW(),
            p_safe_metadata
        );

        COMMIT;

        SELECT p_intent_id AS checkout_intent_id,
               p_checkout_ref AS checkout_ref,
               p_purchase_ref AS purchase_ref,
               p_subscription_ref AS subscription_ref,
               'created' AS intent_status,
               NULL AS safe_response_json;
    ELSEIF v_existing_request_hash = p_canonical_request_hash THEN
        COMMIT;

        SELECT v_existing_id AS checkout_intent_id,
               p_checkout_ref AS checkout_ref,
               p_purchase_ref AS purchase_ref,
               p_subscription_ref AS subscription_ref,
               'replay' AS intent_status,
               v_existing_response AS safe_response_json;
    ELSE
        UPDATE billing_checkout_intents
        SET status = 'conflict', updated_at = NOW()
        WHERE id = v_existing_id;

        COMMIT;

        SELECT v_existing_id AS checkout_intent_id,
               NULL AS checkout_ref,
               NULL AS purchase_ref,
               NULL AS subscription_ref,
               'conflict' AS intent_status,
               NULL AS safe_response_json;
    END IF;
END$$

-- ===================================================================================
-- sp_billing_checkout_intent_complete
-- Completes Checkout intent with encrypted provider session evidence and safe replay
-- response metadata only.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_checkout_intent_complete$$
CREATE PROCEDURE sp_billing_checkout_intent_complete(
    IN p_intent_id VARCHAR(64),
    IN p_status VARCHAR(32),
    IN p_provider_checkout_session_id_ciphertext LONGBLOB,
    IN p_provider_checkout_session_id_hmac BINARY(32),
    IN p_provider_checkout_session_id_fingerprint CHAR(12),
    IN p_provider_ref_key_id VARCHAR(128),
    IN p_hosted_session_fingerprint CHAR(12),
    IN p_safe_response_json JSON,
    IN p_completed_at DATETIME
)
BEGIN
    UPDATE billing_checkout_intents
    SET status = COALESCE(NULLIF(TRIM(p_status), ''), 'completed'),
        provider_checkout_session_id_ciphertext = p_provider_checkout_session_id_ciphertext,
        provider_checkout_session_id_hmac = p_provider_checkout_session_id_hmac,
        provider_checkout_session_id_fingerprint = p_provider_checkout_session_id_fingerprint,
        provider_ref_key_id = p_provider_ref_key_id,
        provider_ref_encryption_alg = CASE WHEN p_provider_checkout_session_id_ciphertext IS NULL THEN NULL ELSE 'fernet-v1' END,
        hosted_session_fingerprint = p_hosted_session_fingerprint,
        safe_response_json = p_safe_response_json,
        completed_at = COALESCE(p_completed_at, NOW()),
        updated_at = NOW()
    WHERE id = p_intent_id;

    SELECT p_intent_id AS checkout_intent_id,
           COALESCE(NULLIF(TRIM(p_status), ''), 'completed') AS intent_status;
END$$

-- ===================================================================================
-- sp_billing_customer_upsert
-- Upserts one encrypted provider customer ref per (user, project, provider).
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_customer_upsert$$
CREATE PROCEDURE sp_billing_customer_upsert(
    IN p_customer_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_billing_group_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_customer_ref VARCHAR(64),
    IN p_provider_customer_id_ciphertext LONGBLOB,
    IN p_provider_customer_id_hmac BINARY(32),
    IN p_provider_customer_id_fingerprint CHAR(12),
    IN p_provider_ref_key_id VARCHAR(128),
    IN p_status VARCHAR(32),
    IN p_safe_metadata JSON
)
BEGIN
    IF p_provider_customer_id_hmac IS NULL OR OCTET_LENGTH(p_provider_customer_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing customer HMAC must be 32 bytes';
    END IF;

    INSERT INTO billing_customers (
        id, user_id, billing_group_id, provider, customer_ref,
        provider_customer_id_ciphertext, provider_customer_id_hmac,
        provider_customer_id_fingerprint, provider_ref_key_id,
        provider_ref_encryption_alg, status, created_at, updated_at, safe_metadata
    ) VALUES (
        p_customer_id, p_user_id, p_billing_group_id, p_provider, p_customer_ref,
        p_provider_customer_id_ciphertext, p_provider_customer_id_hmac,
        p_provider_customer_id_fingerprint, p_provider_ref_key_id,
        'fernet-v1', COALESCE(NULLIF(TRIM(p_status), ''), 'active'), NOW(), NOW(), p_safe_metadata
    ) ON DUPLICATE KEY UPDATE
        provider_customer_id_ciphertext = VALUES(provider_customer_id_ciphertext),
        provider_customer_id_hmac = VALUES(provider_customer_id_hmac),
        provider_customer_id_fingerprint = VALUES(provider_customer_id_fingerprint),
        provider_ref_key_id = VALUES(provider_ref_key_id),
        provider_ref_encryption_alg = VALUES(provider_ref_encryption_alg),
        status = VALUES(status),
        safe_metadata = COALESCE(VALUES(safe_metadata), safe_metadata),
        updated_at = NOW();

    SELECT id AS customer_id,
           customer_ref,
           status AS customer_status
    FROM billing_customers
    WHERE user_id = p_user_id
      AND billing_group_id = p_billing_group_id
      AND provider = p_provider
      AND status IN ('creating','active','stale')
    LIMIT 1;
END$$

-- ===================================================================================
-- sp_billing_get_customer_operational_ref
-- Server-only read of encrypted provider customer ref. No S2S DTO may expose it.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_get_customer_operational_ref$$
CREATE PROCEDURE sp_billing_get_customer_operational_ref(
    IN p_user_id VARCHAR(64),
    IN p_billing_group_id VARCHAR(64),
    IN p_provider VARCHAR(32)
)
BEGIN
    SELECT id AS customer_id,
           customer_ref,
           provider,
           provider_customer_id_ciphertext,
           provider_customer_id_hmac,
           provider_customer_id_fingerprint,
           provider_ref_key_id,
           provider_ref_encryption_alg,
           status
    FROM billing_customers
    WHERE user_id = p_user_id
      AND billing_group_id = p_billing_group_id
      AND provider = p_provider
      AND status IN ('creating','active','stale')
    LIMIT 1;
END$$

-- ===================================================================================
-- sp_billing_webhook_delivery_record
-- Records provider webhook idempotency evidence. Duplicate delivery returns replay.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_webhook_delivery_record$$
CREATE PROCEDURE sp_billing_webhook_delivery_record(
    IN p_delivery_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_billing_group_id VARCHAR(64),
    IN p_provider_event_id_hmac BINARY(32),
    IN p_provider_event_id_fingerprint CHAR(12),
    IN p_event_type VARCHAR(96),
    IN p_raw_body_sha256 BINARY(32),
    IN p_signature_valid BOOLEAN,
    IN p_status VARCHAR(32),
    IN p_sanitized_metadata JSON
)
BEGIN
    DECLARE v_existing_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_existing_status VARCHAR(32) DEFAULT NULL;

    IF p_provider_event_id_hmac IS NULL OR OCTET_LENGTH(p_provider_event_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing webhook event HMAC must be 32 bytes';
    END IF;

    IF p_raw_body_sha256 IS NULL OR OCTET_LENGTH(p_raw_body_sha256) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing webhook body digest must be 32 bytes';
    END IF;

    START TRANSACTION;

    -- Dedupe scope is per (provider, billing_group, event) so two separate Stripe
    -- accounts cannot collide in the evt_ namespace.
    SELECT id, status
      INTO v_existing_id, v_existing_status
    FROM billing_webhook_deliveries
    WHERE provider = p_provider
      AND billing_group_id = p_billing_group_id
      AND provider_event_id_hmac = p_provider_event_id_hmac
    LIMIT 1
    FOR UPDATE;

    IF v_existing_id IS NULL THEN
        INSERT INTO billing_webhook_deliveries (
            id, provider, billing_group_id, provider_event_id_hmac, provider_event_id_fingerprint,
            event_type, raw_body_sha256, signature_valid, status, received_at,
            expires_at, sanitized_metadata
        ) VALUES (
            p_delivery_id, p_provider, p_billing_group_id, p_provider_event_id_hmac, p_provider_event_id_fingerprint,
            p_event_type, p_raw_body_sha256, COALESCE(p_signature_valid, FALSE),
            COALESCE(NULLIF(TRIM(p_status), ''), 'received'), NOW(),
            DATE_ADD(NOW(), INTERVAL 90 DAY), p_sanitized_metadata
        );
        COMMIT;
        SELECT p_delivery_id AS delivery_id, 'accepted' AS delivery_status;
    ELSE
        UPDATE billing_webhook_deliveries
        SET status = CASE WHEN status IN ('processed','ignored','resync_required','replay') THEN 'replay' ELSE status END,
            sanitized_metadata = COALESCE(sanitized_metadata, p_sanitized_metadata)
        WHERE id = v_existing_id;
        COMMIT;
        SELECT v_existing_id AS delivery_id, 'replay' AS delivery_status;
    END IF;
END$$

-- ===================================================================================
-- sp_billing_subscription_observe
-- Appends subscription snapshot/history and upserts current safe billing facts.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_subscription_observe$$
CREATE PROCEDURE sp_billing_subscription_observe(
    IN p_snapshot_id VARCHAR(64),
    IN p_history_id VARCHAR(64),
    IN p_current_id VARCHAR(64),
    IN p_subscription_id VARCHAR(64),
    IN p_customer_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_billing_group_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_subscription_ref VARCHAR(64),
    IN p_provider_subscription_id_ciphertext LONGBLOB,
    IN p_provider_subscription_id_hmac BINARY(32),
    IN p_provider_subscription_id_fingerprint CHAR(12),
    IN p_provider_ref_key_id VARCHAR(128),
    IN p_observed_at DATETIME,
    IN p_sync_source VARCHAR(32),
    IN p_normalized_status VARCHAR(32),
    IN p_plan_code VARCHAR(64),
    IN p_tier_code VARCHAR(64),
    IN p_tier_name VARCHAR(120),
    IN p_cancel_at_period_end BOOLEAN,
    IN p_current_period_end DATETIME,
    IN p_trial_end DATETIME,
    IN p_payload_hash BINARY(32),
    IN p_is_complete BOOLEAN,
    IN p_requires_resync BOOLEAN,
    IN p_stale_after DATETIME,
    IN p_reason VARCHAR(128),
    IN p_safe_metadata JSON
)
BEGIN
    DECLARE v_subscription_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_previous_status VARCHAR(32) DEFAULT NULL;
    DECLARE v_previous_plan_code VARCHAR(64) DEFAULT NULL;
    DECLARE v_previous_tier_code VARCHAR(64) DEFAULT NULL;
    DECLARE v_status VARCHAR(32) DEFAULT 'unknown';
    DECLARE v_plan_code VARCHAR(64) DEFAULT 'free';
    DECLARE v_tier_code VARCHAR(64) DEFAULT NULL;
    DECLARE v_tier_name VARCHAR(120) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    SET v_status = COALESCE(NULLIF(TRIM(p_normalized_status), ''), 'unknown');
    SET v_plan_code = CASE WHEN v_status IN ('free','canceled','former','unknown') THEN 'free' ELSE COALESCE(NULLIF(TRIM(p_plan_code), ''), 'free') END;
    SET v_tier_code = CASE WHEN v_plan_code = 'free' THEN NULL ELSE p_tier_code END;
    SET v_tier_name = CASE WHEN v_plan_code = 'free' THEN NULL ELSE p_tier_name END;

    START TRANSACTION;

    SELECT status, plan_code, tier_code
      INTO v_previous_status, v_previous_plan_code, v_previous_tier_code
    FROM billing_entitlements_current
    WHERE user_id = p_user_id
      AND billing_group_id = p_billing_group_id
      AND provider = p_provider
    LIMIT 1
    FOR UPDATE;

    INSERT INTO billing_subscriptions (
        id, user_id, billing_group_id, customer_id, provider, subscription_ref,
        provider_subscription_id_ciphertext, provider_subscription_id_hmac,
        provider_subscription_id_fingerprint, provider_ref_key_id,
        provider_ref_encryption_alg, status, plan_code, tier_code, tier_name,
        cancel_at_period_end, current_period_end, trial_end, last_synced_at,
        stale_after, created_at, updated_at, safe_metadata
    ) VALUES (
        p_subscription_id, p_user_id, p_billing_group_id, p_customer_id, p_provider, p_subscription_ref,
        p_provider_subscription_id_ciphertext, p_provider_subscription_id_hmac,
        p_provider_subscription_id_fingerprint, p_provider_ref_key_id,
        CASE WHEN p_provider_subscription_id_ciphertext IS NULL THEN NULL ELSE 'fernet-v1' END,
        v_status, v_plan_code, v_tier_code, v_tier_name,
        COALESCE(p_cancel_at_period_end, FALSE), p_current_period_end, p_trial_end,
        COALESCE(p_observed_at, NOW()), p_stale_after, NOW(), NOW(), p_safe_metadata
    ) ON DUPLICATE KEY UPDATE
        provider_subscription_id_ciphertext = COALESCE(VALUES(provider_subscription_id_ciphertext), provider_subscription_id_ciphertext),
        provider_subscription_id_hmac = COALESCE(VALUES(provider_subscription_id_hmac), provider_subscription_id_hmac),
        provider_subscription_id_fingerprint = COALESCE(VALUES(provider_subscription_id_fingerprint), provider_subscription_id_fingerprint),
        provider_ref_key_id = COALESCE(VALUES(provider_ref_key_id), provider_ref_key_id),
        provider_ref_encryption_alg = COALESCE(VALUES(provider_ref_encryption_alg), provider_ref_encryption_alg),
        status = VALUES(status),
        plan_code = VALUES(plan_code),
        tier_code = VALUES(tier_code),
        tier_name = VALUES(tier_name),
        cancel_at_period_end = VALUES(cancel_at_period_end),
        current_period_end = VALUES(current_period_end),
        trial_end = VALUES(trial_end),
        last_synced_at = VALUES(last_synced_at),
        stale_after = VALUES(stale_after),
        safe_metadata = COALESCE(VALUES(safe_metadata), safe_metadata),
        updated_at = NOW();

    SELECT id INTO v_subscription_id
    FROM billing_subscriptions
    WHERE subscription_ref = p_subscription_ref
    LIMIT 1;

    INSERT INTO billing_subscription_snapshots (
        id, subscription_id, customer_id, user_id, billing_group_id, provider,
        observed_at, sync_source, normalized_status, plan_code, tier_code, tier_name,
        cancel_at_period_end, current_period_end, trial_end, payload_hash,
        is_complete, requires_resync, created_at, sanitized_metadata
    ) VALUES (
        p_snapshot_id, v_subscription_id, p_customer_id, p_user_id, p_billing_group_id, p_provider,
        COALESCE(p_observed_at, NOW()), p_sync_source, v_status, v_plan_code, v_tier_code, v_tier_name,
        COALESCE(p_cancel_at_period_end, FALSE), p_current_period_end, p_trial_end, p_payload_hash,
        COALESCE(p_is_complete, FALSE), COALESCE(p_requires_resync, FALSE), NOW(), p_safe_metadata
    ) ON DUPLICATE KEY UPDATE
        requires_resync = VALUES(requires_resync),
        sanitized_metadata = COALESCE(VALUES(sanitized_metadata), sanitized_metadata);

    INSERT INTO billing_entitlements_current (
        id, user_id, billing_group_id, provider, customer_id, subscription_id, status,
        link_status, plan_code, tier_code, tier_name, cancel_at_period_end,
        current_period_end, trial_end, last_synced_at, stale_after, sync_source,
        classification_version, safe_metadata, created_at, updated_at
    ) VALUES (
        COALESCE(p_current_id, CONCAT('bec-', REPLACE(UUID(), '-', ''))), p_user_id, p_billing_group_id,
        p_provider, p_customer_id, v_subscription_id, v_status,
        CASE WHEN v_status = 'free' THEN 'none' ELSE 'linked' END,
        v_plan_code, v_tier_code, v_tier_name, COALESCE(p_cancel_at_period_end, FALSE),
        p_current_period_end, p_trial_end, COALESCE(p_observed_at, NOW()), p_stale_after,
        p_sync_source, 2, p_safe_metadata, NOW(), NOW()
    ) ON DUPLICATE KEY UPDATE
        customer_id = VALUES(customer_id),
        subscription_id = VALUES(subscription_id),
        status = VALUES(status),
        link_status = VALUES(link_status),
        plan_code = VALUES(plan_code),
        tier_code = VALUES(tier_code),
        tier_name = VALUES(tier_name),
        cancel_at_period_end = VALUES(cancel_at_period_end),
        current_period_end = VALUES(current_period_end),
        trial_end = VALUES(trial_end),
        last_synced_at = VALUES(last_synced_at),
        stale_after = VALUES(stale_after),
        sync_source = VALUES(sync_source),
        safe_metadata = VALUES(safe_metadata),
        updated_at = NOW();

    INSERT INTO billing_entitlement_history (
        id, user_id, billing_group_id, provider, customer_id, subscription_id,
        previous_status, new_status, previous_plan_code, new_plan_code,
        previous_tier_code, new_tier_code, link_status, reason, sync_source,
        observed_at, created_at, sanitized_metadata
    ) VALUES (
        COALESCE(p_history_id, CONCAT('beh-', REPLACE(UUID(), '-', ''))), p_user_id, p_billing_group_id,
        p_provider, p_customer_id, v_subscription_id, v_previous_status, v_status,
        v_previous_plan_code, v_plan_code, v_previous_tier_code, v_tier_code,
        CASE WHEN v_status = 'free' THEN 'none' ELSE 'linked' END,
        COALESCE(NULLIF(TRIM(p_reason), ''), 'subscription_observed'), p_sync_source,
        COALESCE(p_observed_at, NOW()), NOW(), p_safe_metadata
    );

    COMMIT;

    SELECT v_subscription_id AS subscription_id,
           v_status AS status,
           v_plan_code AS plan_code;
END$$

-- ===================================================================================
-- sp_billing_purchase_event_record
-- Upserts current purchase facts and appends normalized purchase history only.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_purchase_event_record$$
CREATE PROCEDURE sp_billing_purchase_event_record(
    IN p_purchase_id VARCHAR(64),
    IN p_history_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_billing_group_id VARCHAR(64),
    IN p_customer_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_purchase_ref VARCHAR(64),
    IN p_checkout_ref VARCHAR(64),
    IN p_status VARCHAR(32),
    IN p_credit_product_code VARCHAR(64),
    IN p_quantity INT,
    IN p_provider_payment_intent_id_ciphertext LONGBLOB,
    IN p_provider_payment_intent_id_hmac BINARY(32),
    IN p_provider_payment_intent_id_fingerprint CHAR(12),
    IN p_provider_charge_id_ciphertext LONGBLOB,
    IN p_provider_charge_id_hmac BINARY(32),
    IN p_provider_charge_id_fingerprint CHAR(12),
    IN p_provider_ref_key_id VARCHAR(128),
    IN p_observed_at DATETIME,
    IN p_sync_source VARCHAR(32),
    IN p_paid_at DATETIME,
    IN p_refunded_at DATETIME,
    IN p_disputed_at DATETIME,
    IN p_stale_after DATETIME,
    IN p_reason VARCHAR(128),
    IN p_safe_metadata JSON
)
BEGIN
    DECLARE v_purchase_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_previous_status VARCHAR(32) DEFAULT NULL;
    DECLARE v_status VARCHAR(32) DEFAULT 'unknown';

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    SET v_status = COALESCE(NULLIF(TRIM(p_status), ''), 'unknown');

    START TRANSACTION;

    SELECT status
      INTO v_previous_status
    FROM billing_purchase_events
    WHERE purchase_ref = p_purchase_ref
    LIMIT 1
    FOR UPDATE;

    INSERT INTO billing_purchase_events (
        id, user_id, project_id, billing_group_id, customer_id, provider, purchase_ref, checkout_ref,
        status, credit_product_code, quantity,
        provider_payment_intent_id_ciphertext, provider_payment_intent_id_hmac,
        provider_payment_intent_id_fingerprint, provider_charge_id_ciphertext,
        provider_charge_id_hmac, provider_charge_id_fingerprint, provider_ref_key_id,
        provider_ref_encryption_alg, paid_at, refunded_at, disputed_at,
        last_synced_at, stale_after, created_at, updated_at, safe_metadata
    ) VALUES (
        p_purchase_id, p_user_id, p_project_id, p_billing_group_id, p_customer_id, p_provider, p_purchase_ref, p_checkout_ref,
        v_status, p_credit_product_code, p_quantity,
        p_provider_payment_intent_id_ciphertext, p_provider_payment_intent_id_hmac,
        p_provider_payment_intent_id_fingerprint, p_provider_charge_id_ciphertext,
        p_provider_charge_id_hmac, p_provider_charge_id_fingerprint, p_provider_ref_key_id,
        CASE WHEN p_provider_payment_intent_id_ciphertext IS NULL AND p_provider_charge_id_ciphertext IS NULL THEN NULL ELSE 'fernet-v1' END,
        p_paid_at, p_refunded_at, p_disputed_at, COALESCE(p_observed_at, NOW()),
        p_stale_after, NOW(), NOW(), p_safe_metadata
    ) ON DUPLICATE KEY UPDATE
        status = VALUES(status),
        credit_product_code = COALESCE(VALUES(credit_product_code), credit_product_code),
        quantity = COALESCE(VALUES(quantity), quantity),
        provider_payment_intent_id_ciphertext = COALESCE(VALUES(provider_payment_intent_id_ciphertext), provider_payment_intent_id_ciphertext),
        provider_payment_intent_id_hmac = COALESCE(VALUES(provider_payment_intent_id_hmac), provider_payment_intent_id_hmac),
        provider_payment_intent_id_fingerprint = COALESCE(VALUES(provider_payment_intent_id_fingerprint), provider_payment_intent_id_fingerprint),
        provider_charge_id_ciphertext = COALESCE(VALUES(provider_charge_id_ciphertext), provider_charge_id_ciphertext),
        provider_charge_id_hmac = COALESCE(VALUES(provider_charge_id_hmac), provider_charge_id_hmac),
        provider_charge_id_fingerprint = COALESCE(VALUES(provider_charge_id_fingerprint), provider_charge_id_fingerprint),
        provider_ref_key_id = COALESCE(VALUES(provider_ref_key_id), provider_ref_key_id),
        provider_ref_encryption_alg = COALESCE(VALUES(provider_ref_encryption_alg), provider_ref_encryption_alg),
        paid_at = COALESCE(VALUES(paid_at), paid_at),
        refunded_at = COALESCE(VALUES(refunded_at), refunded_at),
        disputed_at = COALESCE(VALUES(disputed_at), disputed_at),
        last_synced_at = VALUES(last_synced_at),
        stale_after = VALUES(stale_after),
        safe_metadata = COALESCE(VALUES(safe_metadata), safe_metadata),
        updated_at = NOW();

    SELECT id INTO v_purchase_id
    FROM billing_purchase_events
    WHERE purchase_ref = p_purchase_ref
    LIMIT 1;

    INSERT INTO billing_purchase_history (
        id, purchase_id, user_id, project_id, billing_group_id, provider, purchase_ref,
        previous_status, new_status, credit_product_code, quantity,
        reason, sync_source, observed_at, created_at, sanitized_metadata
    ) VALUES (
        COALESCE(p_history_id, CONCAT('bph-', REPLACE(UUID(), '-', ''))), v_purchase_id,
        p_user_id, p_project_id, p_billing_group_id, p_provider, p_purchase_ref, v_previous_status, v_status,
        p_credit_product_code, p_quantity, COALESCE(NULLIF(TRIM(p_reason), ''), 'purchase_observed'),
        p_sync_source, COALESCE(p_observed_at, NOW()), NOW(), p_safe_metadata
    );

    COMMIT;

    SELECT v_purchase_id AS purchase_id,
           p_purchase_ref AS purchase_ref,
           v_status AS purchase_status;
END$$

-- ===================================================================================
-- sp_billing_sync_job_enqueue / claim / complete
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_sync_job_enqueue$$
CREATE PROCEDURE sp_billing_sync_job_enqueue(
    IN p_job_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_job_type VARCHAR(32),
    IN p_user_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_billing_group_id VARCHAR(64),
    IN p_customer_id VARCHAR(64),
    IN p_subscription_id VARCHAR(64),
    IN p_purchase_id VARCHAR(64),
    IN p_dedupe_key_hmac BINARY(32),
    IN p_priority TINYINT,
    IN p_not_before DATETIME,
    IN p_source VARCHAR(32),
    IN p_sanitized_metadata JSON
)
BEGIN
    IF p_dedupe_key_hmac IS NULL OR OCTET_LENGTH(p_dedupe_key_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing sync dedupe HMAC must be 32 bytes';
    END IF;

    INSERT INTO billing_sync_jobs (
        id, provider, job_type, user_id, project_id, billing_group_id, customer_id, subscription_id,
        purchase_id, dedupe_key_hmac, status, priority, not_before, attempts,
        max_attempts, source, created_at, updated_at, sanitized_metadata
    ) VALUES (
        p_job_id, p_provider, p_job_type, p_user_id, p_project_id, p_billing_group_id, p_customer_id, p_subscription_id,
        p_purchase_id, p_dedupe_key_hmac, 'pending', COALESCE(p_priority, 5),
        COALESCE(p_not_before, NOW()), 0, 8, p_source, NOW(), NOW(), p_sanitized_metadata
    ) ON DUPLICATE KEY UPDATE
        not_before = LEAST(not_before, COALESCE(VALUES(not_before), not_before)),
        priority = LEAST(priority, VALUES(priority)),
        sanitized_metadata = COALESCE(VALUES(sanitized_metadata), sanitized_metadata),
        updated_at = NOW();

    SELECT id AS job_id,
           status AS job_status
    FROM billing_sync_jobs
    WHERE provider = p_provider
      AND dedupe_key_hmac = p_dedupe_key_hmac
      AND status IN ('pending','running','retry')
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_sync_job_claim$$
CREATE PROCEDURE sp_billing_sync_job_claim(
    IN p_worker_id VARCHAR(128),
    IN p_limit INT,
    IN p_lease_seconds INT
)
BEGIN
    START TRANSACTION;

    DROP TEMPORARY TABLE IF EXISTS tmp_billing_sync_claim_ids;
    CREATE TEMPORARY TABLE tmp_billing_sync_claim_ids (id VARCHAR(64) NOT NULL PRIMARY KEY) ENGINE=MEMORY;

    INSERT INTO tmp_billing_sync_claim_ids (id)
    SELECT id
    FROM billing_sync_jobs
    WHERE (status IN ('pending','retry') AND not_before <= NOW())
       OR (status = 'running' AND lease_until IS NOT NULL AND lease_until < NOW())
    ORDER BY priority ASC, created_at ASC
    LIMIT p_limit
    FOR UPDATE SKIP LOCKED;

    UPDATE billing_sync_jobs bsj
    JOIN tmp_billing_sync_claim_ids tmp ON tmp.id = bsj.id
    SET bsj.status = 'running',
        bsj.claimed_by = p_worker_id,
        bsj.claimed_at = NOW(),
        bsj.lease_until = DATE_ADD(NOW(), INTERVAL p_lease_seconds SECOND),
        bsj.attempts = bsj.attempts + 1,
        bsj.updated_at = NOW();

    COMMIT;

    SELECT bsj.*
    FROM billing_sync_jobs bsj
    JOIN tmp_billing_sync_claim_ids tmp ON tmp.id = bsj.id
    ORDER BY bsj.priority ASC, bsj.created_at ASC;

    DROP TEMPORARY TABLE IF EXISTS tmp_billing_sync_claim_ids;
END$$

DROP PROCEDURE IF EXISTS sp_billing_sync_job_complete$$
CREATE PROCEDURE sp_billing_sync_job_complete(
    IN p_job_id VARCHAR(64),
    IN p_status VARCHAR(32),
    IN p_retry_after_seconds INT,
    IN p_last_error_redacted TEXT
)
BEGIN
    UPDATE billing_sync_jobs
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
-- sp_billing_retention_purge
-- Purges bounded webhook/quarantine artifacts only. Normalized histories are preserved.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_retention_purge$$
CREATE PROCEDURE sp_billing_retention_purge()
BEGIN
    DECLARE v_webhook_rows INT DEFAULT 0;
    DECLARE v_raw_rows INT DEFAULT 0;

    DELETE FROM billing_webhook_deliveries
    WHERE expires_at <= NOW()
       OR received_at <= DATE_SUB(NOW(), INTERVAL 90 DAY);
    SET v_webhook_rows = ROW_COUNT();

    UPDATE billing_raw_payload_quarantine
    SET payload_ciphertext = '',
        purged_at = NOW(),
        sanitized_metadata = JSON_OBJECT('retention', 'purged')
    WHERE purged_at IS NULL
      AND (purge_at <= NOW() OR received_at <= DATE_SUB(NOW(), INTERVAL 30 DAY));
    SET v_raw_rows = ROW_COUNT();

    SELECT v_webhook_rows AS webhook_delivery_rows_purged_after_90d,
           v_raw_rows AS raw_payload_quarantine_rows_purged_after_max_30d,
           'billing_entitlement_history_and_billing_purchase_history_preserved_indefinitely' AS history_retention_status;
END$$

DELIMITER ;

-- ===================================================================================
-- BILLING PROVIDER FACT PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Billing provider fact stored procedures created!' AS status,
       '14 procedures for scope resolution, free-default reads, session plan projection, checkout idempotency, customers, webhooks, normalized facts, sync jobs, and retention' AS details;
