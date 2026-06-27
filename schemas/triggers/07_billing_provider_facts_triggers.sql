-- ===================================================================================
-- Provider-Agnostic Billing Integrity Triggers
-- ===================================================================================
-- Defense-in-depth checks for encrypted operational refs, HMAC/fingerprint shape,
-- immutable user/project/provider scope, active uniqueness helpers, terminal no-paid
-- states, append-only normalized history, retention caps, and raw provider payload
-- storage only in encrypted quarantine.
-- ===================================================================================

USE magic_auth;

DELIMITER //

-- =================== PROVIDER REGISTRY ===================
DROP TRIGGER IF EXISTS trg_billing_providers_before_insert//
CREATE TRIGGER trg_billing_providers_before_insert BEFORE INSERT ON billing_providers FOR EACH ROW
BEGIN
    IF NEW.provider_code IS NULL OR NEW.provider_code = '' OR NEW.provider_code <> LOWER(NEW.provider_code) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing provider_code must be lowercase and non-empty';
    END IF;

    IF NEW.status <> 'enabled' THEN
        SET NEW.checkout_enabled = FALSE;
        SET NEW.portal_enabled = FALSE;
        SET NEW.webhooks_enabled = FALSE;
        SET NEW.sync_enabled = FALSE;
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_providers_before_update//
CREATE TRIGGER trg_billing_providers_before_update BEFORE UPDATE ON billing_providers FOR EACH ROW
BEGIN
    IF OLD.provider_code <> NEW.provider_code THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing provider_code is immutable';
    END IF;

    IF NEW.status <> 'enabled' THEN
        SET NEW.checkout_enabled = FALSE;
        SET NEW.portal_enabled = FALSE;
        SET NEW.webhooks_enabled = FALSE;
        SET NEW.sync_enabled = FALSE;
    END IF;
END//

-- =================== BILLING GROUPS ===================
DROP TRIGGER IF EXISTS trg_billing_groups_before_insert//
CREATE TRIGGER trg_billing_groups_before_insert BEFORE INSERT ON billing_groups FOR EACH ROW
BEGIN
    IF NEW.billing_group_hash IS NULL OR NEW.billing_group_hash = '' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing group hash must be non-empty';
    END IF;

    IF NEW.stripe_secret_key_hmac IS NOT NULL AND OCTET_LENGTH(NEW.stripe_secret_key_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing group secret key HMAC must be 32 bytes';
    END IF;

    IF NEW.stripe_webhook_secret_hmac IS NOT NULL AND OCTET_LENGTH(NEW.stripe_webhook_secret_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing group webhook secret HMAC must be 32 bytes';
    END IF;

    IF NEW.credential_status = 'active'
       AND (NEW.stripe_secret_key_ciphertext IS NULL
            OR OCTET_LENGTH(NEW.stripe_secret_key_ciphertext) = 0
            OR NEW.credential_key_id IS NULL OR NEW.credential_key_id = '') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Active billing group credentials require encrypted secret key and key id';
    END IF;

    -- capability flags require an active group with active credentials
    IF NEW.status <> 'active' OR NEW.credential_status <> 'active' THEN
        SET NEW.checkout_enabled = FALSE;
        SET NEW.portal_enabled = FALSE;
        SET NEW.provisioning_enabled = FALSE;
        SET NEW.webhooks_enabled = FALSE;
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_groups_before_update//
CREATE TRIGGER trg_billing_groups_before_update BEFORE UPDATE ON billing_groups FOR EACH ROW
BEGIN
    IF OLD.billing_group_hash <> NEW.billing_group_hash
       OR OLD.provider <> NEW.provider THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing group hash/provider is immutable';
    END IF;

    IF NEW.stripe_secret_key_hmac IS NOT NULL AND OCTET_LENGTH(NEW.stripe_secret_key_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing group secret key HMAC must be 32 bytes';
    END IF;

    IF NEW.stripe_webhook_secret_hmac IS NOT NULL AND OCTET_LENGTH(NEW.stripe_webhook_secret_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing group webhook secret HMAC must be 32 bytes';
    END IF;

    IF NEW.credential_status = 'active'
       AND (NEW.stripe_secret_key_ciphertext IS NULL
            OR OCTET_LENGTH(NEW.stripe_secret_key_ciphertext) = 0
            OR NEW.credential_key_id IS NULL OR NEW.credential_key_id = '') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Active billing group credentials require encrypted secret key and key id';
    END IF;

    IF NEW.status <> 'active' OR NEW.credential_status <> 'active' THEN
        SET NEW.checkout_enabled = FALSE;
        SET NEW.portal_enabled = FALSE;
        SET NEW.provisioning_enabled = FALSE;
        SET NEW.webhooks_enabled = FALSE;
    END IF;
END//

-- =================== BILLING GROUP <-> PROJECT MAPPING ===================
DROP TRIGGER IF EXISTS trg_billing_group_projects_before_update//
CREATE TRIGGER trg_billing_group_projects_before_update BEFORE UPDATE ON billing_group_projects FOR EACH ROW
BEGIN
    -- project_id is the identity; re-home is an UPDATE of billing_group_id, not project_id
    IF OLD.project_id <> NEW.project_id THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing group mapping project_id is immutable (re-home via billing_group_id)';
    END IF;
END//

-- =================== BILLING CATALOG ITEMS ===================
DROP TRIGGER IF EXISTS trg_billing_catalog_items_before_insert//
CREATE TRIGGER trg_billing_catalog_items_before_insert BEFORE INSERT ON billing_catalog_items FOR EACH ROW
BEGIN
    IF NEW.catalog_item_hash IS NULL OR NEW.catalog_item_hash = '' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing catalog item hash must be non-empty';
    END IF;

    IF NEW.provider_product_id_hmac IS NOT NULL AND OCTET_LENGTH(NEW.provider_product_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing catalog product HMAC must be 32 bytes';
    END IF;

    IF NEW.provider_price_id_hmac IS NOT NULL AND OCTET_LENGTH(NEW.provider_price_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing catalog price HMAC must be 32 bytes';
    END IF;

    IF NEW.provisioning_idempotency_key_hmac IS NOT NULL AND OCTET_LENGTH(NEW.provisioning_idempotency_key_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing catalog provisioning idempotency HMAC must be 32 bytes';
    END IF;

    IF (NEW.provider_product_id_ciphertext IS NOT NULL OR NEW.provider_price_id_ciphertext IS NOT NULL)
       AND (NEW.provider_ref_key_id IS NULL OR NEW.provider_ref_key_id = '') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing catalog encrypted refs require key id';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_catalog_items_before_update//
CREATE TRIGGER trg_billing_catalog_items_before_update BEFORE UPDATE ON billing_catalog_items FOR EACH ROW
BEGIN
    IF OLD.catalog_item_hash <> NEW.catalog_item_hash
       OR OLD.billing_group_id <> NEW.billing_group_id
       OR OLD.provider <> NEW.provider
       OR OLD.item_type <> NEW.item_type
       OR OLD.plan_code <> NEW.plan_code THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing catalog identity (hash/group/provider/item_type/plan_code) is immutable';
    END IF;

    IF NEW.provider_product_id_hmac IS NOT NULL AND OCTET_LENGTH(NEW.provider_product_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing catalog product HMAC must be 32 bytes';
    END IF;

    IF NEW.provider_price_id_hmac IS NOT NULL AND OCTET_LENGTH(NEW.provider_price_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing catalog price HMAC must be 32 bytes';
    END IF;

    IF (NEW.provider_product_id_ciphertext IS NOT NULL OR NEW.provider_price_id_ciphertext IS NOT NULL)
       AND (NEW.provider_ref_key_id IS NULL OR NEW.provider_ref_key_id = '') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing catalog encrypted refs require key id';
    END IF;
END//

-- =================== CUSTOMERS ===================
DROP TRIGGER IF EXISTS trg_billing_customers_before_insert//
CREATE TRIGGER trg_billing_customers_before_insert BEFORE INSERT ON billing_customers FOR EACH ROW
BEGIN
    IF NEW.provider_customer_id_hmac IS NULL OR OCTET_LENGTH(NEW.provider_customer_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing customer HMAC must be 32 bytes';
    END IF;

    IF NEW.provider_customer_id_fingerprint IS NULL
       OR CHAR_LENGTH(NEW.provider_customer_id_fingerprint) <> 12
       OR LOWER(NEW.provider_customer_id_fingerprint) NOT REGEXP '^[0-9a-f]{12}$' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing customer fingerprint must be 12 lowercase hex chars';
    END IF;

    IF NEW.provider_customer_id_ciphertext IS NULL OR OCTET_LENGTH(NEW.provider_customer_id_ciphertext) = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing customer operational ref requires encrypted ciphertext';
    END IF;

    IF NEW.provider_ref_key_id IS NULL OR NEW.provider_ref_key_id = '' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing customer encrypted ref requires key id';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_customers_before_update//
CREATE TRIGGER trg_billing_customers_before_update BEFORE UPDATE ON billing_customers FOR EACH ROW
BEGIN
    IF OLD.user_id <> NEW.user_id
       OR OLD.billing_group_id <> NEW.billing_group_id
       OR OLD.provider <> NEW.provider
       OR OLD.customer_ref <> NEW.customer_ref
       OR NOT (OLD.provider_customer_id_hmac <=> NEW.provider_customer_id_hmac) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing customer identity/provider scope is immutable';
    END IF;

    IF NEW.provider_customer_id_hmac IS NULL OR OCTET_LENGTH(NEW.provider_customer_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing customer HMAC must be 32 bytes';
    END IF;

    IF NEW.provider_customer_id_fingerprint IS NULL
       OR CHAR_LENGTH(NEW.provider_customer_id_fingerprint) <> 12
       OR LOWER(NEW.provider_customer_id_fingerprint) NOT REGEXP '^[0-9a-f]{12}$' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing customer fingerprint must be 12 lowercase hex chars';
    END IF;

    IF NEW.provider_ref_key_id IS NULL OR NEW.provider_ref_key_id = '' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing customer encrypted ref requires key id';
    END IF;
END//

-- =================== CHECKOUT INTENTS ===================
DROP TRIGGER IF EXISTS trg_billing_checkout_intents_before_insert//
CREATE TRIGGER trg_billing_checkout_intents_before_insert BEFORE INSERT ON billing_checkout_intents FOR EACH ROW
BEGIN
    IF NEW.provider_price_ref_hmac IS NULL OR OCTET_LENGTH(NEW.provider_price_ref_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing checkout price HMAC must be 32 bytes';
    END IF;

    IF NEW.idempotency_key_hmac IS NULL OR OCTET_LENGTH(NEW.idempotency_key_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing checkout idempotency HMAC must be 32 bytes';
    END IF;

    IF NEW.canonical_request_hash IS NULL OR OCTET_LENGTH(NEW.canonical_request_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing checkout canonical request hash must be 32 bytes';
    END IF;

    IF NEW.provider_price_ref_fingerprint IS NULL
       OR CHAR_LENGTH(NEW.provider_price_ref_fingerprint) <> 12
       OR LOWER(NEW.provider_price_ref_fingerprint) NOT REGEXP '^[0-9a-f]{12}$' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing checkout price fingerprint must be 12 lowercase hex chars';
    END IF;

    IF NEW.quantity IS NULL OR NEW.quantity < 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing checkout quantity must be positive';
    END IF;

    IF NEW.provider_checkout_session_id_ciphertext IS NOT NULL
       AND (NEW.provider_ref_key_id IS NULL OR NEW.provider_ref_key_id = '') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing checkout encrypted session ref requires key id';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_checkout_intents_before_update//
CREATE TRIGGER trg_billing_checkout_intents_before_update BEFORE UPDATE ON billing_checkout_intents FOR EACH ROW
BEGIN
    IF OLD.user_id <> NEW.user_id
       OR OLD.project_id <> NEW.project_id
       OR OLD.billing_group_id <> NEW.billing_group_id
       OR OLD.provider <> NEW.provider
       OR OLD.checkout_ref <> NEW.checkout_ref
       OR OLD.intent_type <> NEW.intent_type
       OR NOT (OLD.idempotency_key_hmac <=> NEW.idempotency_key_hmac)
       OR NOT (OLD.canonical_request_hash <=> NEW.canonical_request_hash) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing checkout identity and idempotency scope are immutable';
    END IF;

    IF NEW.provider_checkout_session_id_hmac IS NOT NULL
       AND OCTET_LENGTH(NEW.provider_checkout_session_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing checkout session HMAC must be 32 bytes';
    END IF;

    IF NEW.provider_checkout_session_id_fingerprint IS NOT NULL
       AND (CHAR_LENGTH(NEW.provider_checkout_session_id_fingerprint) <> 12
            OR LOWER(NEW.provider_checkout_session_id_fingerprint) NOT REGEXP '^[0-9a-f]{12}$') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing checkout session fingerprint must be 12 lowercase hex chars';
    END IF;

    IF NEW.provider_checkout_session_id_ciphertext IS NOT NULL
       AND (NEW.provider_ref_key_id IS NULL OR NEW.provider_ref_key_id = '') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing checkout encrypted session ref requires key id';
    END IF;
END//

-- =================== SUBSCRIPTIONS / SNAPSHOTS / CURRENT ===================
DROP TRIGGER IF EXISTS trg_billing_subscriptions_before_insert//
CREATE TRIGGER trg_billing_subscriptions_before_insert BEFORE INSERT ON billing_subscriptions FOR EACH ROW
BEGIN
    IF NEW.provider_subscription_id_hmac IS NOT NULL
       AND OCTET_LENGTH(NEW.provider_subscription_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing subscription HMAC must be 32 bytes';
    END IF;

    IF NEW.provider_subscription_id_fingerprint IS NOT NULL
       AND (CHAR_LENGTH(NEW.provider_subscription_id_fingerprint) <> 12
            OR LOWER(NEW.provider_subscription_id_fingerprint) NOT REGEXP '^[0-9a-f]{12}$') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing subscription fingerprint must be 12 lowercase hex chars';
    END IF;

    IF NEW.provider_subscription_id_ciphertext IS NOT NULL
       AND (NEW.provider_ref_key_id IS NULL OR NEW.provider_ref_key_id = '') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing subscription encrypted ref requires key id';
    END IF;

    IF NEW.status IN ('canceled','former','unknown')
       AND (NEW.plan_code <> 'free' OR NEW.tier_code IS NOT NULL OR NEW.tier_name IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal billing subscription must not grant paid plan';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_subscriptions_before_update//
CREATE TRIGGER trg_billing_subscriptions_before_update BEFORE UPDATE ON billing_subscriptions FOR EACH ROW
BEGIN
    IF OLD.user_id <> NEW.user_id
       OR OLD.billing_group_id <> NEW.billing_group_id
       OR OLD.provider <> NEW.provider
       OR OLD.customer_id <> NEW.customer_id
       OR OLD.subscription_ref <> NEW.subscription_ref
       OR (OLD.provider_subscription_id_hmac IS NOT NULL AND NOT (OLD.provider_subscription_id_hmac <=> NEW.provider_subscription_id_hmac)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing subscription identity/provider scope is immutable';
    END IF;

    IF NEW.status IN ('canceled','former','unknown')
       AND (NEW.plan_code <> 'free' OR NEW.tier_code IS NOT NULL OR NEW.tier_name IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal billing subscription must not grant paid plan';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_subscription_snapshots_before_insert//
CREATE TRIGGER trg_billing_subscription_snapshots_before_insert BEFORE INSERT ON billing_subscription_snapshots FOR EACH ROW
BEGIN
    IF NEW.payload_hash IS NOT NULL AND OCTET_LENGTH(NEW.payload_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing subscription snapshot payload hash must be 32 bytes';
    END IF;

    IF NEW.provider_event_id_hmac IS NOT NULL AND OCTET_LENGTH(NEW.provider_event_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing subscription event HMAC must be 32 bytes';
    END IF;

    IF NEW.sanitized_metadata IS NOT NULL
       AND LOWER(CAST(NEW.sanitized_metadata AS CHAR)) REGEXP 'raw_payload|raw_body|provider_payload|stripe_signature' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing subscription snapshot metadata must be sanitized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_subscription_snapshots_before_update//
CREATE TRIGGER trg_billing_subscription_snapshots_before_update BEFORE UPDATE ON billing_subscription_snapshots FOR EACH ROW
BEGIN
    IF OLD.subscription_id <> NEW.subscription_id
       OR OLD.customer_id <> NEW.customer_id
       OR OLD.user_id <> NEW.user_id
       OR OLD.billing_group_id <> NEW.billing_group_id
       OR OLD.provider <> NEW.provider
       OR NOT (OLD.payload_hash <=> NEW.payload_hash) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing subscription snapshot identity is immutable';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_current_before_insert//
CREATE TRIGGER trg_billing_current_before_insert BEFORE INSERT ON billing_entitlements_current FOR EACH ROW
BEGIN
    IF NEW.status IN ('free','canceled','former','unknown')
       AND (NEW.plan_code <> 'free' OR NEW.tier_code IS NOT NULL OR NEW.tier_name IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal billing current row must not grant paid plan';
    END IF;

    IF NEW.safe_metadata IS NOT NULL
       AND LOWER(CAST(NEW.safe_metadata AS CHAR)) REGEXP 'raw_payload|raw_body|provider_payload|stripe_signature' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing current metadata must be sanitized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_current_before_update//
CREATE TRIGGER trg_billing_current_before_update BEFORE UPDATE ON billing_entitlements_current FOR EACH ROW
BEGIN
    IF OLD.user_id <> NEW.user_id
       OR OLD.billing_group_id <> NEW.billing_group_id
       OR OLD.provider <> NEW.provider THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing current user/group/provider scope is immutable';
    END IF;

    IF NEW.status IN ('free','canceled','former','unknown')
       AND (NEW.plan_code <> 'free' OR NEW.tier_code IS NOT NULL OR NEW.tier_name IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal billing current row must not grant paid plan';
    END IF;

    IF NEW.safe_metadata IS NOT NULL
       AND LOWER(CAST(NEW.safe_metadata AS CHAR)) REGEXP 'raw_payload|raw_body|provider_payload|stripe_signature' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing current metadata must be sanitized';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_entitlement_history_before_update//
CREATE TRIGGER trg_billing_entitlement_history_before_update BEFORE UPDATE ON billing_entitlement_history FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing entitlement history is append-only';
END//

DROP TRIGGER IF EXISTS trg_billing_entitlement_history_before_delete//
CREATE TRIGGER trg_billing_entitlement_history_before_delete BEFORE DELETE ON billing_entitlement_history FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing entitlement history is retained indefinitely';
END//

-- =================== PURCHASE FACTS ===================
DROP TRIGGER IF EXISTS trg_billing_purchase_events_before_insert//
CREATE TRIGGER trg_billing_purchase_events_before_insert BEFORE INSERT ON billing_purchase_events FOR EACH ROW
BEGIN
    IF NEW.provider_payment_intent_id_hmac IS NOT NULL
       AND OCTET_LENGTH(NEW.provider_payment_intent_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing purchase payment HMAC must be 32 bytes';
    END IF;

    IF NEW.provider_charge_id_hmac IS NOT NULL
       AND OCTET_LENGTH(NEW.provider_charge_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing purchase charge HMAC must be 32 bytes';
    END IF;

    IF NEW.provider_payment_intent_id_fingerprint IS NOT NULL
       AND (CHAR_LENGTH(NEW.provider_payment_intent_id_fingerprint) <> 12
            OR LOWER(NEW.provider_payment_intent_id_fingerprint) NOT REGEXP '^[0-9a-f]{12}$') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing purchase payment fingerprint must be 12 lowercase hex chars';
    END IF;

    IF NEW.provider_charge_id_fingerprint IS NOT NULL
       AND (CHAR_LENGTH(NEW.provider_charge_id_fingerprint) <> 12
            OR LOWER(NEW.provider_charge_id_fingerprint) NOT REGEXP '^[0-9a-f]{12}$') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing purchase charge fingerprint must be 12 lowercase hex chars';
    END IF;

    IF (NEW.provider_payment_intent_id_ciphertext IS NOT NULL OR NEW.provider_charge_id_ciphertext IS NOT NULL)
       AND (NEW.provider_ref_key_id IS NULL OR NEW.provider_ref_key_id = '') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing purchase encrypted refs require key id';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_purchase_events_before_update//
CREATE TRIGGER trg_billing_purchase_events_before_update BEFORE UPDATE ON billing_purchase_events FOR EACH ROW
BEGIN
    IF OLD.user_id <> NEW.user_id
       OR OLD.project_id <> NEW.project_id
       OR OLD.billing_group_id <> NEW.billing_group_id
       OR OLD.provider <> NEW.provider
       OR OLD.purchase_ref <> NEW.purchase_ref
       OR (OLD.provider_payment_intent_id_hmac IS NOT NULL AND NOT (OLD.provider_payment_intent_id_hmac <=> NEW.provider_payment_intent_id_hmac))
       OR (OLD.provider_charge_id_hmac IS NOT NULL AND NOT (OLD.provider_charge_id_hmac <=> NEW.provider_charge_id_hmac)) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing purchase identity/provider scope is immutable';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_purchase_history_before_update//
CREATE TRIGGER trg_billing_purchase_history_before_update BEFORE UPDATE ON billing_purchase_history FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing purchase history is append-only';
END//

DROP TRIGGER IF EXISTS trg_billing_purchase_history_before_delete//
CREATE TRIGGER trg_billing_purchase_history_before_delete BEFORE DELETE ON billing_purchase_history FOR EACH ROW
BEGIN
    SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing purchase history is retained indefinitely';
END//

-- =================== WEBHOOKS / SYNC / QUARANTINE ===================
DROP TRIGGER IF EXISTS trg_billing_webhook_deliveries_before_insert//
CREATE TRIGGER trg_billing_webhook_deliveries_before_insert BEFORE INSERT ON billing_webhook_deliveries FOR EACH ROW
BEGIN
    IF NEW.provider_event_id_hmac IS NULL OR OCTET_LENGTH(NEW.provider_event_id_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing webhook event HMAC must be 32 bytes';
    END IF;

    IF NEW.provider_event_id_fingerprint IS NULL
       OR CHAR_LENGTH(NEW.provider_event_id_fingerprint) <> 12
       OR LOWER(NEW.provider_event_id_fingerprint) NOT REGEXP '^[0-9a-f]{12}$' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing webhook event fingerprint must be 12 lowercase hex chars';
    END IF;

    IF NEW.raw_body_sha256 IS NULL OR OCTET_LENGTH(NEW.raw_body_sha256) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing webhook body digest must be 32 bytes';
    END IF;

    IF NEW.expires_at IS NULL THEN
        SET NEW.expires_at = DATE_ADD(NEW.received_at, INTERVAL 90 DAY);
    END IF;

    IF NEW.expires_at > DATE_ADD(NEW.received_at, INTERVAL 90 DAY) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing webhook delivery retention cannot exceed 90 days';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_webhook_deliveries_before_update//
CREATE TRIGGER trg_billing_webhook_deliveries_before_update BEFORE UPDATE ON billing_webhook_deliveries FOR EACH ROW
BEGIN
    IF OLD.provider <> NEW.provider
       OR OLD.billing_group_id <> NEW.billing_group_id
       OR NOT (OLD.provider_event_id_hmac <=> NEW.provider_event_id_hmac)
       OR NOT (OLD.raw_body_sha256 <=> NEW.raw_body_sha256)
       OR OLD.event_type <> NEW.event_type THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing webhook idempotency identity is immutable';
    END IF;

    IF NEW.expires_at > DATE_ADD(NEW.received_at, INTERVAL 90 DAY) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing webhook delivery retention cannot exceed 90 days';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_sync_jobs_before_insert//
CREATE TRIGGER trg_billing_sync_jobs_before_insert BEFORE INSERT ON billing_sync_jobs FOR EACH ROW
BEGIN
    IF NEW.dedupe_key_hmac IS NULL OR OCTET_LENGTH(NEW.dedupe_key_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing sync dedupe HMAC must be 32 bytes';
    END IF;

    IF NEW.attempts < 0 OR NEW.max_attempts < 1 OR NEW.attempts > NEW.max_attempts THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing sync attempts are outside allowed range';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_sync_jobs_before_update//
CREATE TRIGGER trg_billing_sync_jobs_before_update BEFORE UPDATE ON billing_sync_jobs FOR EACH ROW
BEGIN
    IF OLD.provider <> NEW.provider
       OR OLD.job_type <> NEW.job_type
       OR NOT (OLD.dedupe_key_hmac <=> NEW.dedupe_key_hmac) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing sync provider/job/dedupe identity is immutable';
    END IF;

    IF NEW.attempts < 0 OR NEW.max_attempts < 1 OR NEW.attempts > NEW.max_attempts THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing sync attempts are outside allowed range';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_raw_payload_quarantine_before_insert//
CREATE TRIGGER trg_billing_raw_payload_quarantine_before_insert BEFORE INSERT ON billing_raw_payload_quarantine FOR EACH ROW
BEGIN
    IF NEW.payload_hash IS NULL OR OCTET_LENGTH(NEW.payload_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing raw payload hash must be 32 bytes';
    END IF;

    IF NEW.payload_ciphertext IS NULL OR OCTET_LENGTH(NEW.payload_ciphertext) = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing raw payload quarantine requires encrypted ciphertext';
    END IF;

    IF NEW.encryption_key_id IS NULL OR NEW.encryption_key_id = '' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing raw payload quarantine requires key id';
    END IF;

    IF NEW.purge_at > DATE_ADD(NEW.received_at, INTERVAL 30 DAY) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing raw payload quarantine retention cannot exceed 30 days';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_billing_raw_payload_quarantine_before_update//
CREATE TRIGGER trg_billing_raw_payload_quarantine_before_update BEFORE UPDATE ON billing_raw_payload_quarantine FOR EACH ROW
BEGIN
    IF OLD.provider <> NEW.provider
       OR NOT (OLD.payload_hash <=> NEW.payload_hash)
       OR OLD.source <> NEW.source THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing raw payload quarantine identity is immutable';
    END IF;

    IF NEW.purge_at > DATE_ADD(NEW.received_at, INTERVAL 30 DAY) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing raw payload quarantine retention cannot exceed 30 days';
    END IF;

    IF NEW.payload_ciphertext IS NOT NULL
       AND OCTET_LENGTH(NEW.payload_ciphertext) = 0
       AND NEW.purged_at IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing raw payload ciphertext can be emptied only by retention purge';
    END IF;
END//

DELIMITER ;

-- ===================================================================================
-- BILLING PROVIDER FACT TRIGGERS CREATED
-- ===================================================================================
SELECT 'Billing provider fact triggers created!' AS status,
       'Integrity triggers for HMAC/fingerprint shape, encrypted refs, active uniqueness helpers, terminal no-paid-plan behavior, append-only history, immutable scope, retention caps, and quarantine-only raw payload storage' AS details;
