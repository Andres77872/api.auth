-- ===================================================================================
-- Provider-Agnostic Billing Provider Fact Tables
-- ===================================================================================
-- Billing is provider-fact state only. Local api.auth sessions, JWTs, refresh-token
-- state, cookies, /auth/validate identity, Patreon artifacts, and consuming-project
-- projection stay outside this schema family.
--
-- Billing unit:
-- - Billing is owned by a BILLING GROUP. A billing group holds one provider account
--   (e.g. one Stripe account, credentials encrypted) and one product catalog, and can
--   span one OR MORE projects. A standalone project is a billing group of one.
-- - Subscriptions/customers/entitlements are scoped to (user_id, billing_group_id,
--   provider): one subscription applies to every project in the group.
-- - Credit purchases keep BOTH billing_group_id (for the provider account/customer) AND
--   project_id (credits are consumer-owned per project).
--
-- Privacy split:
-- - Raw provider operational refs (incl. per-group Stripe secret/webhook keys) are stored
--   only as encrypted ciphertext when a server-side provider operation requires replay.
-- - HMAC-SHA-256 digests plus 12-hex fingerprints are used for matching, idempotency,
--   and support correlation without exposing raw refs.
-- - Webhook delivery rows retain only delivery evidence for 90 days.
-- - Encrypted raw payload quarantine is disabled-by-default and capped at 30 days.
-- - Normalized current/history rows are retained indefinitely unless a later spec
--   changes that policy.
--
-- api.auth stays AGNOSTIC of product meaning: catalog rows carry opaque features/metadata
-- JSON (consumer-defined numeric knobs and labels) that api.auth never reads or interprets.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- =================== PROVIDER REGISTRY ===================
-- Single global registry. Master kill switch ANDed with per-group capability flags.
CREATE TABLE IF NOT EXISTS billing_providers (
    id VARCHAR(64) NOT NULL,
    provider_code VARCHAR(32) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    status ENUM('disabled','enabled','degraded','archived') NOT NULL DEFAULT 'disabled',
    checkout_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    portal_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    webhooks_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    sync_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    api_version VARCHAR(64) NULL,
    capability_metadata JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_provider_code (provider_code),
    INDEX idx_billing_provider_status (status, checkout_enabled, webhooks_enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== BILLING GROUPS ===================
-- The billing unit. Owns one provider account (encrypted credentials) + one catalog and
-- can span multiple projects. Effective capability = global provider flag AND global
-- config flag AND per-group flag AND credential_status='active' (enforced in app + trigger).
CREATE TABLE IF NOT EXISTS billing_groups (
    id VARCHAR(64) NOT NULL,
    billing_group_hash VARCHAR(255) NOT NULL,
    name VARCHAR(120) NOT NULL,
    description TEXT NULL,
    owner_id VARCHAR(64) NULL,
    provider VARCHAR(32) NOT NULL DEFAULT 'stripe',
    status ENUM('active','suspended','archived') NOT NULL DEFAULT 'active',

    -- per-group capability flags (zeroed by trigger unless status='active')
    checkout_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    portal_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    provisioning_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    webhooks_enabled BOOLEAN NOT NULL DEFAULT FALSE,

    -- per-account Stripe credentials (LOCKED DECISION 1): each group its own keys
    stripe_account_label VARCHAR(120) NULL,
    stripe_account_fingerprint CHAR(12) NULL,
    stripe_secret_key_ciphertext LONGBLOB NULL,
    stripe_secret_key_hmac BINARY(32) NULL,
    stripe_secret_key_fingerprint CHAR(12) NULL,
    stripe_webhook_secret_ciphertext LONGBLOB NULL,
    stripe_webhook_secret_hmac BINARY(32) NULL,
    stripe_webhook_secret_fingerprint CHAR(12) NULL,
    stripe_portal_configuration_id_ciphertext LONGBLOB NULL,
    credential_key_id VARCHAR(128) NULL,
    credential_encryption_alg VARCHAR(32) NOT NULL DEFAULT 'fernet-v1',
    credential_status ENUM('absent','active','rotating','revoked') NOT NULL DEFAULT 'absent',
    credentials_set_at DATETIME NULL,

    -- Catalog reconcile (Stripe -> local pull) bookkeeping: counts/status only, never secrets.
    last_catalog_synced_at DATETIME NULL,
    catalog_sync_status ENUM('never','ok','drift','error') NOT NULL DEFAULT 'never',
    catalog_sync_error_redacted TEXT NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(64) NULL,
    updated_at DATETIME NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_group_hash (billing_group_hash),
    -- defensive: a webhook secret must not be shared across groups (NULLs coexist)
    UNIQUE KEY uk_billing_group_webhook_secret_hmac (provider, stripe_webhook_secret_hmac),
    INDEX idx_billing_group_status (status, checkout_enabled, webhooks_enabled),
    INDEX idx_billing_group_owner (owner_id),
    INDEX idx_billing_group_acct_fp (provider, stripe_account_fingerprint),
    CONSTRAINT fk_billing_group_owner FOREIGN KEY (owner_id)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_group_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== BILLING GROUP <-> PROJECT MAPPING ===================
-- A project belongs to EXACTLY ONE billing group (re-home via UPDATE of billing_group_id).
CREATE TABLE IF NOT EXISTS billing_group_projects (
    id VARCHAR(64) NOT NULL,
    billing_group_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    status ENUM('active','removed') NOT NULL DEFAULT 'active',
    added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    added_by VARCHAR(64) NULL,
    removed_at DATETIME NULL,
    removed_by VARCHAR(64) NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_group_project (project_id),
    INDEX idx_bgp_group (billing_group_id, status),
    CONSTRAINT fk_bgp_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_bgp_project FOREIGN KEY (project_id)
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== BILLING CATALOG ITEMS ===================
-- The centralized, per-billing-group product catalog (subscription plans + credit
-- packages). api.auth owns this and provisions Stripe Product/Price (LOCKED DECISION 2),
-- but never interprets the opaque features/metadata JSON (LOCKED DECISION 5). Only
-- subscription_plan rows feed /auth/validate's plan object; credit_package rows are
-- listed for consumers but never produce entitlements.
CREATE TABLE IF NOT EXISTS billing_catalog_items (
    id VARCHAR(64) NOT NULL,
    catalog_item_hash VARCHAR(255) NOT NULL,
    billing_group_id VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL DEFAULT 'stripe',
    item_type ENUM('subscription_plan','credit_package') NOT NULL,

    plan_code VARCHAR(64) NOT NULL,
    tier_code VARCHAR(64) NULL,
    tier_name VARCHAR(120) NULL,
    display_name VARCHAR(120) NOT NULL,

    -- display-only money/interval (api.auth never charges/computes from these)
    currency CHAR(3) NULL,
    unit_amount BIGINT NULL,
    recurring_interval ENUM('day','week','month','year') NULL,

    -- Stripe provisioning result (encrypted refs + HMAC + fingerprint)
    provider_product_id_ciphertext LONGBLOB NULL,
    provider_product_id_hmac BINARY(32) NULL,
    provider_product_id_fingerprint CHAR(12) NULL,
    provider_price_id_ciphertext LONGBLOB NULL,
    provider_price_id_hmac BINARY(32) NULL,
    provider_price_id_fingerprint CHAR(12) NULL,
    provider_ref_key_id VARCHAR(128) NULL,
    provider_ref_encryption_alg VARCHAR(32) NULL,
    lookup_key VARCHAR(200) NULL,

    features JSON NULL,
    metadata JSON NULL,
    sort_order INT NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT FALSE,

    provisioning_status ENUM('pending','active','failed','archived') NOT NULL DEFAULT 'pending',
    provisioning_idempotency_key_hmac BINARY(32) NULL,
    provisioning_error_redacted TEXT NULL,
    provisioned_at DATETIME NULL,

    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_by VARCHAR(64) NULL,
    updated_at DATETIME NULL,

    -- one active plan_code per billing group (archived/failed rows drop out)
    active_plan_scope VARCHAR(160)
        GENERATED ALWAYS AS (
            CASE WHEN active = TRUE AND provisioning_status IN ('pending','active')
                 THEN CONCAT(billing_group_id, ':', plan_code)
                 ELSE NULL END
        ) VIRTUAL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_catalog_item_hash (catalog_item_hash),
    UNIQUE KEY uk_catalog_active_plan (active_plan_scope),
    UNIQUE KEY uk_catalog_provisioning_idem (provider, provisioning_idempotency_key_hmac),
    INDEX idx_catalog_group_type_active (billing_group_id, item_type, active, sort_order),
    INDEX idx_catalog_price_fp (provider, provider_price_id_fingerprint),
    INDEX idx_catalog_lookup (provider, lookup_key),
    CONSTRAINT fk_catalog_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_catalog_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== GROUP-SCOPED CUSTOMERS ===================
-- One provider customer per (user_id, billing_group_id, provider). A local user can have
-- separate provider customers across billing groups.
CREATE TABLE IF NOT EXISTS billing_customers (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    billing_group_id VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    customer_ref VARCHAR(64) NOT NULL,
    provider_customer_id_ciphertext LONGBLOB NOT NULL,
    provider_customer_id_hmac BINARY(32) NOT NULL,
    provider_customer_id_fingerprint CHAR(12) NOT NULL,
    provider_ref_key_id VARCHAR(128) NOT NULL,
    provider_ref_encryption_alg VARCHAR(32) NOT NULL DEFAULT 'fernet-v1',
    status ENUM('creating','active','disabled','revoked','stale') NOT NULL DEFAULT 'creating',
    raw_ref_required_until DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    safe_metadata JSON NULL,

    active_user_group_provider VARCHAR(224)
        GENERATED ALWAYS AS (
            CASE WHEN status IN ('creating','active','stale')
                 THEN CONCAT(user_id, ':', billing_group_id, ':', provider)
                 ELSE NULL END
        ) VIRTUAL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_customer_ref (customer_ref),
    UNIQUE KEY uk_billing_customer_scope (active_user_group_provider),
    UNIQUE KEY uk_billing_customer_provider_hmac (provider, provider_customer_id_hmac),
    INDEX idx_billing_customer_user_group (user_id, billing_group_id, provider, status),
    INDEX idx_billing_customer_fp (provider, provider_customer_id_fingerprint),
    CONSTRAINT fk_billing_customer_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_customer_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_customer_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== CHECKOUT INTENTS ===================
-- Keeps BOTH project_id (originating project / credit attribution) and billing_group_id
-- (provider account + subscription scope). Idempotency scope branches by intent_type:
-- subscriptions dedupe per (provider,user,billing_group); credit purchases per
-- (provider,user,project).
CREATE TABLE IF NOT EXISTS billing_checkout_intents (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    billing_group_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NULL,
    provider VARCHAR(32) NOT NULL,
    checkout_ref VARCHAR(64) NOT NULL,
    subscription_ref VARCHAR(64) NULL,
    purchase_ref VARCHAR(64) NULL,
    intent_type ENUM('subscription','credit_purchase') NOT NULL,
    provider_price_ref_type ENUM('price_id','lookup_key') NOT NULL,
    provider_price_ref_hmac BINARY(32) NOT NULL,
    provider_price_ref_fingerprint CHAR(12) NOT NULL,
    idempotency_key_hmac BINARY(32) NOT NULL,
    canonical_request_hash BINARY(32) NOT NULL,
    plan_code VARCHAR(64) NULL,
    tier_code VARCHAR(64) NULL,
    tier_name VARCHAR(120) NULL,
    credit_product_code VARCHAR(64) NULL,
    quantity INT NOT NULL DEFAULT 1,
    status ENUM('pending','completed','replay','conflict','failed','expired','cancelled') NOT NULL DEFAULT 'pending',
    provider_checkout_session_id_ciphertext LONGBLOB NULL,
    provider_checkout_session_id_hmac BINARY(32) NULL,
    provider_checkout_session_id_fingerprint CHAR(12) NULL,
    provider_ref_key_id VARCHAR(128) NULL,
    provider_ref_encryption_alg VARCHAR(32) NULL,
    hosted_session_fingerprint CHAR(12) NULL,
    safe_response_json JSON NULL,
    expires_at DATETIME NULL,
    completed_at DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    safe_metadata JSON NULL,

    active_idempotency_scope VARCHAR(256)
        GENERATED ALWAYS AS (
            CASE WHEN status IN ('pending','completed')
                 THEN CASE WHEN intent_type = 'subscription'
                           THEN CONCAT(provider, ':', user_id, ':g:', billing_group_id, ':', HEX(idempotency_key_hmac))
                           ELSE CONCAT(provider, ':', user_id, ':p:', project_id, ':', HEX(idempotency_key_hmac))
                      END
                 ELSE NULL END
        ) VIRTUAL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_checkout_ref (checkout_ref),
    UNIQUE KEY uk_billing_checkout_active_idem (active_idempotency_scope),
    INDEX idx_billing_checkout_scope (user_id, billing_group_id, project_id, provider, status, created_at),
    INDEX idx_billing_checkout_purchase_ref (purchase_ref),
    INDEX idx_billing_checkout_subscription_ref (subscription_ref),
    INDEX idx_billing_checkout_price_fp (provider, provider_price_ref_fingerprint),
    CONSTRAINT fk_billing_checkout_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_checkout_project FOREIGN KEY (project_id)
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_checkout_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_checkout_customer FOREIGN KEY (customer_id)
        REFERENCES billing_customers(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_checkout_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== SUBSCRIPTIONS ===================
-- One active subscription per (user_id, billing_group_id, provider). Applies to every
-- project in the group.
CREATE TABLE IF NOT EXISTS billing_subscriptions (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    billing_group_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    subscription_ref VARCHAR(64) NOT NULL,
    provider_subscription_id_ciphertext LONGBLOB NULL,
    provider_subscription_id_hmac BINARY(32) NULL,
    provider_subscription_id_fingerprint CHAR(12) NULL,
    provider_ref_key_id VARCHAR(128) NULL,
    provider_ref_encryption_alg VARCHAR(32) NULL,
    status ENUM('pending','incomplete','trialing','active','past_due','unpaid','paused','canceled','former','stale','unknown') NOT NULL DEFAULT 'pending',
    plan_code VARCHAR(64) NOT NULL DEFAULT 'free',
    tier_code VARCHAR(64) NULL,
    tier_name VARCHAR(120) NULL,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    current_period_end DATETIME NULL,
    trial_end DATETIME NULL,
    last_synced_at DATETIME NULL,
    stale_after DATETIME NULL,
    raw_ref_required_until DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    safe_metadata JSON NULL,

    active_user_group_provider VARCHAR(224)
        GENERATED ALWAYS AS (
            CASE WHEN status IN ('pending','incomplete','trialing','active','past_due','unpaid','paused','stale','unknown')
                 THEN CONCAT(user_id, ':', billing_group_id, ':', provider)
                 ELSE NULL END
        ) VIRTUAL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_subscription_ref (subscription_ref),
    UNIQUE KEY uk_billing_subscription_active_scope (active_user_group_provider),
    UNIQUE KEY uk_billing_subscription_provider_hmac (provider, provider_subscription_id_hmac),
    INDEX idx_billing_subscription_scope (user_id, billing_group_id, provider, status),
    INDEX idx_billing_subscription_fp (provider, provider_subscription_id_fingerprint),
    CONSTRAINT fk_billing_subscription_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_subscription_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_subscription_customer FOREIGN KEY (customer_id)
        REFERENCES billing_customers(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_subscription_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== SUBSCRIPTION SNAPSHOTS ===================
CREATE TABLE IF NOT EXISTS billing_subscription_snapshots (
    id VARCHAR(64) NOT NULL,
    subscription_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    billing_group_id VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    provider_event_id_hmac BINARY(32) NULL,
    provider_event_id_fingerprint CHAR(12) NULL,
    observed_at DATETIME NOT NULL,
    sync_source ENUM('webhook','api_pull','manual_resync','checkout','retention') NOT NULL,
    normalized_status ENUM('free','pending','incomplete','trialing','active','past_due','unpaid','paused','canceled','former','stale','unknown') NOT NULL DEFAULT 'unknown',
    plan_code VARCHAR(64) NOT NULL DEFAULT 'free',
    tier_code VARCHAR(64) NULL,
    tier_name VARCHAR(120) NULL,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    current_period_end DATETIME NULL,
    trial_end DATETIME NULL,
    payload_hash BINARY(32) NULL,
    is_complete BOOLEAN NOT NULL DEFAULT FALSE,
    requires_resync BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sanitized_metadata JSON NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_subscription_snapshot_payload (subscription_id, payload_hash),
    INDEX idx_billing_subscription_snapshot_scope (user_id, billing_group_id, provider, observed_at),
    INDEX idx_billing_subscription_snapshot_resync (requires_resync, observed_at),
    CONSTRAINT fk_billing_snapshot_subscription FOREIGN KEY (subscription_id)
        REFERENCES billing_subscriptions(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_snapshot_customer FOREIGN KEY (customer_id)
        REFERENCES billing_customers(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_snapshot_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_snapshot_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_snapshot_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== CURRENT SAFE READ MODEL ===================
-- One current entitlement per (user_id, billing_group_id, provider). The /auth/validate
-- plan object resolves the session project -> billing group -> this row.
CREATE TABLE IF NOT EXISTS billing_entitlements_current (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    billing_group_id VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    customer_id VARCHAR(64) NULL,
    subscription_id VARCHAR(64) NULL,
    status ENUM('free','pending','incomplete','trialing','active','past_due','unpaid','paused','canceled','former','stale','unknown') NOT NULL DEFAULT 'free',
    link_status ENUM('none','pending','linked','revoked','stale') NOT NULL DEFAULT 'none',
    plan_code VARCHAR(64) NOT NULL DEFAULT 'free',
    tier_code VARCHAR(64) NULL,
    tier_name VARCHAR(120) NULL,
    cancel_at_period_end BOOLEAN NOT NULL DEFAULT FALSE,
    current_period_end DATETIME NULL,
    trial_end DATETIME NULL,
    last_synced_at DATETIME NULL,
    stale_after DATETIME NULL,
    sync_source ENUM('webhook','api_pull','manual_resync','checkout','retention') NOT NULL DEFAULT 'retention',
    classification_version INT NOT NULL DEFAULT 2,
    safe_metadata JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_current_scope (user_id, billing_group_id, provider),
    INDEX idx_billing_current_status (status, link_status, stale_after),
    INDEX idx_billing_current_customer (customer_id),
    INDEX idx_billing_current_subscription (subscription_id),
    CONSTRAINT fk_billing_current_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_current_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_current_customer FOREIGN KEY (customer_id)
        REFERENCES billing_customers(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_current_subscription FOREIGN KEY (subscription_id)
        REFERENCES billing_subscriptions(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_current_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ENTITLEMENT HISTORY ===================
CREATE TABLE IF NOT EXISTS billing_entitlement_history (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    billing_group_id VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    customer_id VARCHAR(64) NULL,
    subscription_id VARCHAR(64) NULL,
    previous_status VARCHAR(32) NULL,
    new_status VARCHAR(32) NOT NULL,
    previous_plan_code VARCHAR(64) NULL,
    new_plan_code VARCHAR(64) NOT NULL,
    previous_tier_code VARCHAR(64) NULL,
    new_tier_code VARCHAR(64) NULL,
    link_status VARCHAR(32) NULL,
    reason VARCHAR(128) NOT NULL,
    sync_source ENUM('webhook','api_pull','manual_resync','checkout','retention') NOT NULL,
    observed_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sanitized_metadata JSON NULL,

    PRIMARY KEY (id),
    INDEX idx_billing_history_scope_time (user_id, billing_group_id, provider, observed_at),
    INDEX idx_billing_history_subscription (subscription_id, observed_at),
    CONSTRAINT fk_billing_history_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_history_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_history_customer FOREIGN KEY (customer_id)
        REFERENCES billing_customers(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_history_subscription FOREIGN KEY (subscription_id)
        REFERENCES billing_subscriptions(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_history_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== CURRENT PURCHASE FACTS ===================
-- Credit purchases keep project_id (consumer-owned per project) AND billing_group_id
-- (provider account / customer).
CREATE TABLE IF NOT EXISTS billing_purchase_events (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    billing_group_id VARCHAR(64) NOT NULL,
    customer_id VARCHAR(64) NULL,
    provider VARCHAR(32) NOT NULL,
    purchase_ref VARCHAR(64) NOT NULL,
    checkout_ref VARCHAR(64) NULL,
    status ENUM('pending','paid','refunded','partially_refunded','disputed','dispute_won','dispute_lost','stale','unknown') NOT NULL DEFAULT 'pending',
    credit_product_code VARCHAR(64) NULL,
    quantity INT NULL,
    provider_payment_intent_id_ciphertext LONGBLOB NULL,
    provider_payment_intent_id_hmac BINARY(32) NULL,
    provider_payment_intent_id_fingerprint CHAR(12) NULL,
    provider_charge_id_ciphertext LONGBLOB NULL,
    provider_charge_id_hmac BINARY(32) NULL,
    provider_charge_id_fingerprint CHAR(12) NULL,
    provider_ref_key_id VARCHAR(128) NULL,
    provider_ref_encryption_alg VARCHAR(32) NULL,
    paid_at DATETIME NULL,
    refunded_at DATETIME NULL,
    disputed_at DATETIME NULL,
    last_synced_at DATETIME NULL,
    stale_after DATETIME NULL,
    raw_ref_required_until DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    safe_metadata JSON NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_purchase_ref (purchase_ref),
    INDEX idx_billing_purchase_scope (user_id, project_id, billing_group_id, provider, status, created_at),
    INDEX idx_billing_purchase_payment_fp (provider, provider_payment_intent_id_fingerprint),
    INDEX idx_billing_purchase_charge_fp (provider, provider_charge_id_fingerprint),
    CONSTRAINT fk_billing_purchase_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_purchase_project FOREIGN KEY (project_id)
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_purchase_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_purchase_customer FOREIGN KEY (customer_id)
        REFERENCES billing_customers(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_purchase_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PURCHASE HISTORY ===================
CREATE TABLE IF NOT EXISTS billing_purchase_history (
    id VARCHAR(64) NOT NULL,
    purchase_id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    billing_group_id VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    purchase_ref VARCHAR(64) NOT NULL,
    previous_status VARCHAR(32) NULL,
    new_status VARCHAR(32) NOT NULL,
    credit_product_code VARCHAR(64) NULL,
    quantity INT NULL,
    reason VARCHAR(128) NOT NULL,
    sync_source ENUM('webhook','api_pull','manual_resync','checkout','retention') NOT NULL,
    observed_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sanitized_metadata JSON NULL,

    PRIMARY KEY (id),
    INDEX idx_billing_purchase_history_scope_time (user_id, project_id, billing_group_id, provider, observed_at),
    INDEX idx_billing_purchase_history_purchase (purchase_id, observed_at),
    CONSTRAINT fk_billing_purchase_history_purchase FOREIGN KEY (purchase_id)
        REFERENCES billing_purchase_events(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_purchase_history_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_purchase_history_project FOREIGN KEY (project_id)
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_purchase_history_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_billing_purchase_history_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== WEBHOOK DELIVERY LEDGER ===================
-- Path-scoped webhooks attribute each delivery to its billing group. Dedupe uniqueness
-- includes billing_group_id so two separate Stripe accounts cannot collide in the evt_
-- namespace.
CREATE TABLE IF NOT EXISTS billing_webhook_deliveries (
    id VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    billing_group_id VARCHAR(64) NOT NULL,
    provider_event_id_hmac BINARY(32) NOT NULL,
    provider_event_id_fingerprint CHAR(12) NOT NULL,
    event_type VARCHAR(96) NOT NULL,
    raw_body_sha256 BINARY(32) NOT NULL,
    signature_valid BOOLEAN NOT NULL DEFAULT FALSE,
    status ENUM('received','processing','processed','rejected','replay','failed','ignored','resync_required') NOT NULL DEFAULT 'received',
    received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at DATETIME NULL,
    expires_at DATETIME NOT NULL,
    retry_after_at DATETIME NULL,
    sanitized_metadata JSON NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_webhook_provider_event (provider, billing_group_id, provider_event_id_hmac),
    INDEX idx_billing_webhook_status (provider, status, received_at),
    INDEX idx_billing_webhook_group (billing_group_id, status, received_at),
    INDEX idx_billing_webhook_fp (provider, provider_event_id_fingerprint),
    INDEX idx_billing_webhook_expiry (expires_at),
    CONSTRAINT fk_billing_webhook_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_billing_webhook_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== SYNC JOBS ===================
CREATE TABLE IF NOT EXISTS billing_sync_jobs (
    id VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    job_type ENUM('customer','subscription','purchase','webhook_resync','retention','manual') NOT NULL,
    user_id VARCHAR(64) NULL,
    project_id VARCHAR(64) NULL,
    billing_group_id VARCHAR(64) NULL,
    customer_id VARCHAR(64) NULL,
    subscription_id VARCHAR(64) NULL,
    purchase_id VARCHAR(64) NULL,
    dedupe_key_hmac BINARY(32) NOT NULL,
    status ENUM('pending','running','retry','completed','failed','cancelled') NOT NULL DEFAULT 'pending',
    priority TINYINT NOT NULL DEFAULT 5,
    not_before DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 8,
    claimed_by VARCHAR(128) NULL,
    claimed_at DATETIME NULL,
    lease_until DATETIME NULL,
    completed_at DATETIME NULL,
    source ENUM('webhook','scheduled','manual','checkout','retention','health') NOT NULL,
    last_error_redacted TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    sanitized_metadata JSON NULL,

    active_dedupe_key_hmac BINARY(32)
        GENERATED ALWAYS AS (
            CASE WHEN status IN ('pending','running','retry') THEN dedupe_key_hmac ELSE NULL END
        ) VIRTUAL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_sync_active_dedupe (active_dedupe_key_hmac),
    INDEX idx_billing_sync_claim (provider, status, not_before, priority, created_at),
    INDEX idx_billing_sync_scope (user_id, project_id, status, created_at),
    INDEX idx_billing_sync_group (billing_group_id, status, created_at),
    INDEX idx_billing_sync_customer (customer_id, status, created_at),
    CONSTRAINT fk_billing_sync_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_billing_sync_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_sync_project FOREIGN KEY (project_id)
        REFERENCES projects(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_sync_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_sync_customer FOREIGN KEY (customer_id)
        REFERENCES billing_customers(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_sync_subscription FOREIGN KEY (subscription_id)
        REFERENCES billing_subscriptions(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_sync_purchase FOREIGN KEY (purchase_id)
        REFERENCES billing_purchase_events(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== RAW PAYLOAD QUARANTINE ===================
-- Disabled-by-default incident diagnostics. The only durable raw provider payload
-- location is encrypted ciphertext in this table; retention is capped to 30 days.
CREATE TABLE IF NOT EXISTS billing_raw_payload_quarantine (
    id VARCHAR(64) NOT NULL,
    provider VARCHAR(32) NOT NULL,
    billing_group_id VARCHAR(64) NULL,
    payload_hash BINARY(32) NOT NULL,
    source ENUM('webhook','api_pull','manual') NOT NULL,
    payload_ciphertext LONGBLOB NOT NULL,
    encryption_key_id VARCHAR(128) NOT NULL,
    encryption_alg VARCHAR(32) NOT NULL DEFAULT 'fernet-v1',
    capture_reason VARCHAR(128) NOT NULL,
    received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    purge_at DATETIME NOT NULL,
    purged_at DATETIME NULL,
    created_by VARCHAR(64) NULL,
    sanitized_metadata JSON NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_billing_quarantine_provider_payload (provider, payload_hash),
    INDEX idx_billing_quarantine_purge (purge_at, purged_at),
    INDEX idx_billing_quarantine_group (billing_group_id, received_at),
    CONSTRAINT fk_billing_quarantine_provider FOREIGN KEY (provider)
        REFERENCES billing_providers(provider_code) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_billing_quarantine_group FOREIGN KEY (billing_group_id)
        REFERENCES billing_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_billing_quarantine_created_by FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ACCESS RESOLVER VIEW ===================
-- Composes on v_user_project_access (user -> user_group -> project_group -> project, plus
-- root-global access) to resolve a (user, project) pair to its billing group. A project
-- with no active group mapping simply yields no row (the "none" plan signal).
CREATE OR REPLACE VIEW v_user_billing_group_access AS
SELECT
    vupa.user_id,
    vupa.user_hash,
    vupa.project_id,
    vupa.project_hash,
    vupa.access_type,
    bg.id AS billing_group_id,
    bg.billing_group_hash,
    bg.provider AS billing_group_provider,
    bg.status AS billing_group_status
FROM v_user_project_access vupa
JOIN billing_group_projects bgp
    ON bgp.project_id = vupa.project_id AND bgp.status = 'active'
JOIN billing_groups bg
    ON bg.id = bgp.billing_group_id;

-- ===================================================================================
-- BILLING PROVIDER FACT TABLES COMPLETE
-- ===================================================================================
SELECT 'Billing provider fact tables created successfully!' AS status,
       '15 billing_* tables (billing groups, group-project mapping, catalog, group-scoped customers/subscriptions/entitlements, project-scoped purchases, encrypted refs, webhook ledger, sync jobs, retention) + v_user_billing_group_access view' AS details;
