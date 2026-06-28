-- ===================================================================================
-- Billing Groups, Catalog & Resolver Procedures
-- ===================================================================================
-- Companion to 17_billing_provider_facts.sql. Manages the billing unit (a billing group
-- owns one provider account + one catalog and can span multiple projects), the per-group
-- encrypted Stripe credentials, the centralized catalog, and project->group resolution.
--
-- Encrypted credentials/refs are accepted/returned only as ciphertext + HMAC/fingerprint
-- companions. Consumer-facing reads never expose ciphertext.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- sp_billing_resolve_user_billing_group
-- Resolve a (user, project) pair to its billing group through the access view. No row
-- when the project is not mapped to a group (the "none" plan signal).
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_resolve_user_billing_group$$
CREATE PROCEDURE sp_billing_resolve_user_billing_group(
    IN p_user_hash VARCHAR(255),
    IN p_project_hash VARCHAR(255)
)
BEGIN
    SELECT user_id,
           user_hash,
           project_id,
           project_hash,
           billing_group_id,
           billing_group_hash,
           billing_group_provider,
           billing_group_status
    FROM v_user_billing_group_access
    WHERE user_hash = p_user_hash
      AND project_hash = p_project_hash
    LIMIT 1;
END$$

-- ===================================================================================
-- BILLING GROUP CRUD
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_group_create$$
CREATE PROCEDURE sp_billing_group_create(
    IN p_id VARCHAR(64),
    IN p_billing_group_hash VARCHAR(255),
    IN p_name VARCHAR(120),
    IN p_description TEXT,
    IN p_owner_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO billing_groups (
        id, billing_group_hash, name, description, owner_id, provider,
        status, credential_status, created_at, created_by, updated_at
    ) VALUES (
        p_id, p_billing_group_hash, p_name, p_description, p_owner_id,
        COALESCE(NULLIF(TRIM(p_provider), ''), 'stripe'),
        'active', 'absent', NOW(), p_created_by, NOW()
    );

    SELECT id, billing_group_hash, name, status, provider, credential_status
    FROM billing_groups WHERE id = p_id LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_group_update$$
CREATE PROCEDURE sp_billing_group_update(
    IN p_id VARCHAR(64),
    IN p_name VARCHAR(120),
    IN p_description TEXT,
    IN p_status VARCHAR(16)
)
BEGIN
    UPDATE billing_groups
    SET name = COALESCE(NULLIF(TRIM(p_name), ''), name),
        description = COALESCE(p_description, description),
        status = COALESCE(NULLIF(TRIM(p_status), ''), status),
        updated_at = NOW()
    WHERE id = p_id;

    SELECT id, billing_group_hash, name, status, provider, credential_status
    FROM billing_groups WHERE id = p_id LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_group_set_capabilities$$
CREATE PROCEDURE sp_billing_group_set_capabilities(
    IN p_id VARCHAR(64),
    IN p_checkout_enabled BOOLEAN,
    IN p_portal_enabled BOOLEAN,
    IN p_provisioning_enabled BOOLEAN,
    IN p_webhooks_enabled BOOLEAN
)
BEGIN
    -- trigger zeroes these unless status='active' AND credential_status='active'
    UPDATE billing_groups
    SET checkout_enabled = COALESCE(p_checkout_enabled, checkout_enabled),
        portal_enabled = COALESCE(p_portal_enabled, portal_enabled),
        provisioning_enabled = COALESCE(p_provisioning_enabled, provisioning_enabled),
        webhooks_enabled = COALESCE(p_webhooks_enabled, webhooks_enabled),
        updated_at = NOW()
    WHERE id = p_id;

    SELECT id, status, credential_status, checkout_enabled, portal_enabled,
           provisioning_enabled, webhooks_enabled
    FROM billing_groups WHERE id = p_id LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_group_set_credentials$$
CREATE PROCEDURE sp_billing_group_set_credentials(
    IN p_id VARCHAR(64),
    IN p_stripe_account_label VARCHAR(120),
    IN p_stripe_account_fingerprint CHAR(12),
    IN p_stripe_secret_key_ciphertext LONGBLOB,
    IN p_stripe_secret_key_hmac BINARY(32),
    IN p_stripe_secret_key_fingerprint CHAR(12),
    IN p_stripe_webhook_secret_ciphertext LONGBLOB,
    IN p_stripe_webhook_secret_hmac BINARY(32),
    IN p_stripe_webhook_secret_fingerprint CHAR(12),
    IN p_stripe_portal_configuration_id_ciphertext LONGBLOB,
    IN p_credential_key_id VARCHAR(128)
)
BEGIN
    IF p_stripe_secret_key_ciphertext IS NULL OR OCTET_LENGTH(p_stripe_secret_key_ciphertext) = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing group credentials require an encrypted secret key';
    END IF;

    IF p_credential_key_id IS NULL OR p_credential_key_id = '' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Billing group credentials require a key id';
    END IF;

    UPDATE billing_groups
    SET stripe_account_label = p_stripe_account_label,
        stripe_account_fingerprint = p_stripe_account_fingerprint,
        stripe_secret_key_ciphertext = p_stripe_secret_key_ciphertext,
        stripe_secret_key_hmac = p_stripe_secret_key_hmac,
        stripe_secret_key_fingerprint = p_stripe_secret_key_fingerprint,
        stripe_webhook_secret_ciphertext = p_stripe_webhook_secret_ciphertext,
        stripe_webhook_secret_hmac = p_stripe_webhook_secret_hmac,
        stripe_webhook_secret_fingerprint = p_stripe_webhook_secret_fingerprint,
        stripe_portal_configuration_id_ciphertext = p_stripe_portal_configuration_id_ciphertext,
        credential_key_id = p_credential_key_id,
        credential_encryption_alg = 'fernet-v1',
        credential_status = 'active',
        credentials_set_at = NOW(),
        updated_at = NOW()
    WHERE id = p_id;

    SELECT id, credential_status, credentials_set_at,
           stripe_account_label, stripe_account_fingerprint,
           stripe_secret_key_fingerprint, stripe_webhook_secret_fingerprint,
           credential_key_id
    FROM billing_groups WHERE id = p_id LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_group_get_operational_credentials$$
CREATE PROCEDURE sp_billing_group_get_operational_credentials(
    IN p_id VARCHAR(64)
)
BEGIN
    -- SERVER-ONLY. Returns encrypted material for Stripe replay. Never expose to S2S DTOs.
    SELECT id, billing_group_hash, provider, status, credential_status,
           checkout_enabled, portal_enabled, provisioning_enabled, webhooks_enabled,
           stripe_secret_key_ciphertext,
           stripe_webhook_secret_ciphertext,
           stripe_portal_configuration_id_ciphertext,
           credential_key_id, credential_encryption_alg
    FROM billing_groups
    WHERE id = p_id
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_group_get_by_hash$$
CREATE PROCEDURE sp_billing_group_get_by_hash(
    IN p_billing_group_hash VARCHAR(255)
)
BEGIN
    SELECT id, billing_group_hash, name, description, owner_id, provider, status,
           checkout_enabled, portal_enabled, provisioning_enabled, webhooks_enabled,
           credential_status, credentials_set_at,
           stripe_account_label, stripe_account_fingerprint,
           stripe_secret_key_fingerprint, stripe_webhook_secret_fingerprint,
           (stripe_secret_key_ciphertext IS NOT NULL) AS has_secret_key,
           (stripe_webhook_secret_ciphertext IS NOT NULL) AS has_webhook_secret,
           credential_key_id, created_at, updated_at,
           (SELECT COUNT(*) FROM billing_group_projects bgp WHERE bgp.billing_group_id = bg.id AND bgp.status = 'active') AS project_count,
           (SELECT COUNT(*) FROM billing_catalog_items ci WHERE ci.billing_group_id = bg.id AND ci.provisioning_status <> 'archived') AS catalog_item_count
    FROM billing_groups bg
    WHERE bg.billing_group_hash = p_billing_group_hash
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_group_list$$
CREATE PROCEDURE sp_billing_group_list(
    IN p_search VARCHAR(255),
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    SELECT SQL_CALC_FOUND_ROWS
           id, billing_group_hash, name, description, owner_id, provider, status,
           credential_status,
           (stripe_secret_key_ciphertext IS NOT NULL) AS has_secret_key,
           created_at, updated_at,
           (SELECT COUNT(*) FROM billing_group_projects bgp WHERE bgp.billing_group_id = bg.id AND bgp.status = 'active') AS project_count,
           (SELECT COUNT(*) FROM billing_catalog_items ci WHERE ci.billing_group_id = bg.id AND ci.provisioning_status <> 'archived') AS catalog_item_count
    FROM billing_groups bg
    WHERE (p_search IS NULL OR p_search = ''
           OR bg.name LIKE CONCAT('%', p_search, '%')
           OR bg.billing_group_hash LIKE CONCAT('%', p_search, '%'))
    ORDER BY bg.created_at DESC
    LIMIT p_limit OFFSET p_offset;

    SELECT FOUND_ROWS() AS total_count;
END$$

DROP PROCEDURE IF EXISTS sp_billing_group_delete$$
CREATE PROCEDURE sp_billing_group_delete(
    IN p_id VARCHAR(64)
)
BEGIN
    DECLARE v_active_subs INT DEFAULT 0;

    SELECT COUNT(*) INTO v_active_subs
    FROM billing_subscriptions
    WHERE billing_group_id = p_id
      AND status IN ('trialing','active','past_due','unpaid','paused');

    IF v_active_subs > 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Cannot delete billing group with active subscriptions';
    END IF;

    DELETE FROM billing_groups WHERE id = p_id;

    SELECT p_id AS billing_group_id, 'deleted' AS result;
END$$

DROP PROCEDURE IF EXISTS sp_billing_group_resolve_by_webhook_secret_hmac$$
CREATE PROCEDURE sp_billing_group_resolve_by_webhook_secret_hmac(
    IN p_provider VARCHAR(32),
    IN p_stripe_webhook_secret_hmac BINARY(32)
)
BEGIN
    -- Defensive correlation only; webhook routing is path-scoped by hash. Returns the
    -- group whose stored webhook secret HMAC matches.
    SELECT id, billing_group_hash, status, credential_status, webhooks_enabled
    FROM billing_groups
    WHERE provider = p_provider
      AND stripe_webhook_secret_hmac = p_stripe_webhook_secret_hmac
    LIMIT 1;
END$$

-- ===================================================================================
-- BILLING GROUP <-> PROJECT MAPPING
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_group_attach_project$$
CREATE PROCEDURE sp_billing_group_attach_project(
    IN p_id VARCHAR(64),
    IN p_billing_group_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_added_by VARCHAR(64)
)
BEGIN
    DECLARE v_existing_group VARCHAR(64) DEFAULT NULL;
    DECLARE v_existing_status VARCHAR(16) DEFAULT NULL;

    SELECT billing_group_id, status INTO v_existing_group, v_existing_status
    FROM billing_group_projects WHERE project_id = p_project_id LIMIT 1;

    IF v_existing_group IS NOT NULL AND v_existing_status = 'active' AND v_existing_group <> p_billing_group_id THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Project already attached to another billing group';
    END IF;

    INSERT INTO billing_group_projects (id, billing_group_id, project_id, status, added_at, added_by)
    VALUES (p_id, p_billing_group_id, p_project_id, 'active', NOW(), p_added_by)
    ON DUPLICATE KEY UPDATE
        billing_group_id = VALUES(billing_group_id),
        status = 'active',
        added_at = NOW(),
        added_by = VALUES(added_by),
        removed_at = NULL,
        removed_by = NULL;

    SELECT bgp.id, bgp.billing_group_id, bgp.project_id, bgp.status, p.project_hash, p.project_name
    FROM billing_group_projects bgp
    JOIN projects p ON p.id = bgp.project_id
    WHERE bgp.project_id = p_project_id
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_group_detach_project$$
CREATE PROCEDURE sp_billing_group_detach_project(
    IN p_project_id VARCHAR(64),
    IN p_removed_by VARCHAR(64)
)
BEGIN
    UPDATE billing_group_projects
    SET status = 'removed', removed_at = NOW(), removed_by = p_removed_by
    WHERE project_id = p_project_id AND status = 'active';

    SELECT p_project_id AS project_id, 'removed' AS result;
END$$

DROP PROCEDURE IF EXISTS sp_billing_group_list_projects$$
CREATE PROCEDURE sp_billing_group_list_projects(
    IN p_billing_group_id VARCHAR(64)
)
BEGIN
    SELECT bgp.id, bgp.billing_group_id, bgp.project_id, bgp.status, bgp.added_at,
           p.project_hash, p.project_name, p.project_description
    FROM billing_group_projects bgp
    JOIN projects p ON p.id = bgp.project_id
    WHERE bgp.billing_group_id = p_billing_group_id
      AND bgp.status = 'active'
    ORDER BY bgp.added_at DESC;
END$$

-- ===================================================================================
-- CATALOG ITEMS
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_catalog_item_create$$
CREATE PROCEDURE sp_billing_catalog_item_create(
    IN p_id VARCHAR(64),
    IN p_catalog_item_hash VARCHAR(255),
    IN p_billing_group_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_item_type VARCHAR(32),
    IN p_plan_code VARCHAR(64),
    IN p_tier_code VARCHAR(64),
    IN p_tier_name VARCHAR(120),
    IN p_display_name VARCHAR(120),
    IN p_currency CHAR(3),
    IN p_unit_amount BIGINT,
    IN p_recurring_interval VARCHAR(8),
    IN p_lookup_key VARCHAR(200),
    IN p_features JSON,
    IN p_metadata JSON,
    IN p_sort_order INT,
    IN p_provisioning_idempotency_key_hmac BINARY(32),
    IN p_created_by VARCHAR(64)
)
BEGIN
    INSERT INTO billing_catalog_items (
        id, catalog_item_hash, billing_group_id, provider, item_type, plan_code,
        tier_code, tier_name, display_name, currency, unit_amount, recurring_interval,
        lookup_key, features, metadata, sort_order, active, provisioning_status,
        provisioning_idempotency_key_hmac, created_at, created_by, updated_at
    ) VALUES (
        p_id, p_catalog_item_hash, p_billing_group_id,
        COALESCE(NULLIF(TRIM(p_provider), ''), 'stripe'), p_item_type, p_plan_code,
        p_tier_code, p_tier_name, p_display_name, p_currency, p_unit_amount,
        NULLIF(TRIM(p_recurring_interval), ''), p_lookup_key, p_features, p_metadata,
        COALESCE(p_sort_order, 0), FALSE, 'pending',
        p_provisioning_idempotency_key_hmac, NOW(), p_created_by, NOW()
    );

    SELECT id, catalog_item_hash, billing_group_id, item_type, plan_code,
           provisioning_status, active
    FROM billing_catalog_items WHERE id = p_id LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_catalog_item_set_provisioned$$
CREATE PROCEDURE sp_billing_catalog_item_set_provisioned(
    IN p_id VARCHAR(64),
    IN p_provider_product_id_ciphertext LONGBLOB,
    IN p_provider_product_id_hmac BINARY(32),
    IN p_provider_product_id_fingerprint CHAR(12),
    IN p_provider_price_id_ciphertext LONGBLOB,
    IN p_provider_price_id_hmac BINARY(32),
    IN p_provider_price_id_fingerprint CHAR(12),
    IN p_provider_ref_key_id VARCHAR(128),
    IN p_lookup_key VARCHAR(200),
    IN p_activate BOOLEAN
)
BEGIN
    UPDATE billing_catalog_items
    SET provider_product_id_ciphertext = p_provider_product_id_ciphertext,
        provider_product_id_hmac = p_provider_product_id_hmac,
        provider_product_id_fingerprint = p_provider_product_id_fingerprint,
        provider_price_id_ciphertext = p_provider_price_id_ciphertext,
        provider_price_id_hmac = p_provider_price_id_hmac,
        provider_price_id_fingerprint = p_provider_price_id_fingerprint,
        provider_ref_key_id = p_provider_ref_key_id,
        provider_ref_encryption_alg = 'fernet-v1',
        lookup_key = COALESCE(p_lookup_key, lookup_key),
        provisioning_status = 'active',
        provisioning_error_redacted = NULL,
        provisioned_at = NOW(),
        active = CASE WHEN COALESCE(p_activate, TRUE) THEN TRUE ELSE active END,
        updated_at = NOW()
    WHERE id = p_id;

    SELECT id, catalog_item_hash, provisioning_status, active,
           provider_price_id_fingerprint
    FROM billing_catalog_items WHERE id = p_id LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_catalog_item_set_failed$$
CREATE PROCEDURE sp_billing_catalog_item_set_failed(
    IN p_id VARCHAR(64),
    IN p_provisioning_error_redacted TEXT
)
BEGIN
    UPDATE billing_catalog_items
    SET provisioning_status = 'failed',
        active = FALSE,
        provisioning_error_redacted = p_provisioning_error_redacted,
        updated_at = NOW()
    WHERE id = p_id;

    SELECT id, catalog_item_hash, provisioning_status, active
    FROM billing_catalog_items WHERE id = p_id LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_catalog_item_set_active$$
CREATE PROCEDURE sp_billing_catalog_item_set_active(
    IN p_id VARCHAR(64),
    IN p_active BOOLEAN
)
BEGIN
    UPDATE billing_catalog_items
    SET active = COALESCE(p_active, active),
        updated_at = NOW()
    WHERE id = p_id;

    SELECT id, catalog_item_hash, provisioning_status, active
    FROM billing_catalog_items WHERE id = p_id LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_catalog_item_archive$$
CREATE PROCEDURE sp_billing_catalog_item_archive(
    IN p_id VARCHAR(64)
)
BEGIN
    UPDATE billing_catalog_items
    SET provisioning_status = 'archived',
        active = FALSE,
        updated_at = NOW()
    WHERE id = p_id;

    SELECT id, catalog_item_hash, provisioning_status, active
    FROM billing_catalog_items WHERE id = p_id LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_catalog_item_update$$
CREATE PROCEDURE sp_billing_catalog_item_update(
    IN p_id VARCHAR(64),
    IN p_display_name VARCHAR(120),
    IN p_tier_name VARCHAR(120),
    IN p_currency CHAR(3),
    IN p_unit_amount BIGINT,
    IN p_recurring_interval VARCHAR(8),
    IN p_features JSON,
    IN p_metadata JSON,
    IN p_sort_order INT
)
BEGIN
    UPDATE billing_catalog_items
    SET display_name = COALESCE(NULLIF(TRIM(p_display_name), ''), display_name),
        tier_name = COALESCE(p_tier_name, tier_name),
        currency = COALESCE(p_currency, currency),
        unit_amount = COALESCE(p_unit_amount, unit_amount),
        recurring_interval = COALESCE(NULLIF(TRIM(p_recurring_interval), ''), recurring_interval),
        features = COALESCE(p_features, features),
        metadata = COALESCE(p_metadata, metadata),
        sort_order = COALESCE(p_sort_order, sort_order),
        updated_at = NOW()
    WHERE id = p_id;

    SELECT id, catalog_item_hash, provisioning_status, active
    FROM billing_catalog_items WHERE id = p_id LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_catalog_get_operational_refs$$
CREATE PROCEDURE sp_billing_catalog_get_operational_refs(
    IN p_id VARCHAR(64)
)
BEGIN
    -- SERVER-ONLY. Encrypted product/price refs for Stripe replay (e.g. price rotation).
    SELECT id, catalog_item_hash, billing_group_id, provider, item_type, plan_code,
           provider_product_id_ciphertext, provider_price_id_ciphertext,
           provider_ref_key_id, provider_ref_encryption_alg, lookup_key,
           provisioning_status
    FROM billing_catalog_items WHERE id = p_id LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_catalog_get_by_hash$$
CREATE PROCEDURE sp_billing_catalog_get_by_hash(
    IN p_catalog_item_hash VARCHAR(255)
)
BEGIN
    SELECT id, catalog_item_hash, billing_group_id, provider, item_type, plan_code,
           tier_code, tier_name, display_name, currency, unit_amount, recurring_interval,
           lookup_key, provider_price_id_fingerprint, features, metadata, sort_order,
           active, provisioning_status, provisioning_error_redacted, provisioned_at,
           created_at, updated_at
    FROM billing_catalog_items WHERE catalog_item_hash = p_catalog_item_hash LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_billing_catalog_list_for_group$$
CREATE PROCEDURE sp_billing_catalog_list_for_group(
    IN p_billing_group_id VARCHAR(64),
    IN p_item_type VARCHAR(32),
    IN p_include_archived BOOLEAN
)
BEGIN
    SELECT id, catalog_item_hash, billing_group_id, provider, item_type, plan_code,
           tier_code, tier_name, display_name, currency, unit_amount, recurring_interval,
           lookup_key, provider_price_id_fingerprint, features, metadata, sort_order,
           active, provisioning_status, provisioning_error_redacted, provisioned_at,
           created_at, updated_at
    FROM billing_catalog_items
    WHERE billing_group_id = p_billing_group_id
      AND (p_item_type IS NULL OR p_item_type = '' OR item_type = p_item_type)
      AND (COALESCE(p_include_archived, FALSE) = TRUE OR provisioning_status <> 'archived')
    ORDER BY item_type, sort_order, created_at;
END$$

-- ===================================================================================
-- sp_billing_catalog_list_for_project
-- Consumer-facing per-project listing. Resolves project_hash -> billing group, returns
-- ACTIVE provisioned items only, never any ciphertext.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_catalog_list_for_project$$
CREATE PROCEDURE sp_billing_catalog_list_for_project(
    IN p_project_hash VARCHAR(255),
    IN p_item_type VARCHAR(32),
    IN p_provider VARCHAR(32)
)
BEGIN
    SELECT p.project_hash,
           bg.billing_group_hash,
           ci.provider,
           ci.catalog_item_hash,
           ci.item_type,
           ci.plan_code,
           ci.tier_code,
           ci.tier_name,
           ci.display_name,
           ci.currency,
           ci.unit_amount,
           ci.recurring_interval,
           ci.lookup_key,
           ci.provider_price_id_fingerprint,
           ci.features,
           ci.metadata,
           ci.sort_order,
           ci.active
    FROM projects p
    JOIN billing_group_projects bgp ON bgp.project_id = p.id AND bgp.status = 'active'
    JOIN billing_groups bg ON bg.id = bgp.billing_group_id
    JOIN billing_catalog_items ci
      ON ci.billing_group_id = bg.id
     AND ci.active = TRUE
     AND ci.provisioning_status = 'active'
     AND ci.provider = COALESCE(NULLIF(TRIM(p_provider), ''), 'stripe')
    WHERE p.project_hash = p_project_hash
      AND (p_item_type IS NULL OR p_item_type = '' OR ci.item_type = p_item_type)
    ORDER BY ci.item_type, ci.sort_order, ci.created_at;
END$$

-- ===================================================================================
-- sp_billing_admin_metrics
-- Aggregate counts for the admin dashboard (groups by status / credential state, catalog
-- by item_type and provisioning state, projects mapped). Counts only — no secrets, no
-- per-user data, no product meaning. Returns exactly one row.
-- ===================================================================================

DROP PROCEDURE IF EXISTS sp_billing_admin_metrics$$
CREATE PROCEDURE sp_billing_admin_metrics()
BEGIN
    SELECT
        (SELECT COUNT(*) FROM billing_groups)                                            AS groups_total,
        (SELECT COUNT(*) FROM billing_groups WHERE status = 'active')                    AS groups_active,
        (SELECT COUNT(*) FROM billing_groups WHERE status = 'suspended')                 AS groups_suspended,
        (SELECT COUNT(*) FROM billing_groups WHERE status = 'archived')                  AS groups_archived,
        (SELECT COUNT(*) FROM billing_groups WHERE credential_status = 'active')         AS credentials_active,
        (SELECT COUNT(*) FROM billing_groups WHERE credential_status = 'absent')         AS credentials_absent,
        (SELECT COUNT(*) FROM billing_groups WHERE credential_status = 'rotating')       AS credentials_rotating,
        (SELECT COUNT(*) FROM billing_groups WHERE credential_status = 'revoked')        AS credentials_revoked,
        (SELECT COUNT(*) FROM billing_catalog_items
            WHERE item_type = 'subscription_plan' AND provisioning_status <> 'archived') AS subscription_plans,
        (SELECT COUNT(*) FROM billing_catalog_items
            WHERE item_type = 'credit_package' AND provisioning_status <> 'archived')    AS credit_packages,
        (SELECT COUNT(*) FROM billing_catalog_items WHERE provisioning_status = 'active') AS catalog_active,
        (SELECT COUNT(*) FROM billing_catalog_items WHERE provisioning_status = 'pending') AS catalog_pending,
        (SELECT COUNT(*) FROM billing_catalog_items WHERE provisioning_status = 'failed') AS catalog_failed,
        (SELECT COUNT(*) FROM billing_catalog_items WHERE provisioning_status = 'archived') AS catalog_archived,
        (SELECT COUNT(*) FROM billing_group_projects WHERE status = 'active')            AS projects_mapped,
        (SELECT COUNT(*) FROM billing_groups
            WHERE credential_status = 'active' AND stripe_webhook_secret_ciphertext IS NOT NULL) AS groups_with_webhook_secret,
        (SELECT COUNT(*) FROM billing_groups
            WHERE status = 'active' AND credential_status = 'active'
              AND webhooks_enabled = 1 AND stripe_webhook_secret_ciphertext IS NULL)            AS webhook_secret_missing_active_groups;
END$$

-- ===================================================================================
-- sp_billing_catalog_list_refs_for_group
-- SERVER-ONLY. Catalog rows WITH provider-ref fingerprints + key id, to drive the
-- Stripe->local reconcile join. (sp_billing_catalog_list_for_group omits the refs.)
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_catalog_list_refs_for_group$$
CREATE PROCEDURE sp_billing_catalog_list_refs_for_group(
    IN p_billing_group_id VARCHAR(64),
    IN p_include_archived BOOLEAN
)
BEGIN
    SELECT id, catalog_item_hash, plan_code, item_type, currency, unit_amount,
           recurring_interval, lookup_key, active, provisioning_status,
           provider_product_id_fingerprint, provider_price_id_fingerprint, provider_ref_key_id
    FROM billing_catalog_items
    WHERE billing_group_id = p_billing_group_id
      AND (COALESCE(p_include_archived, FALSE) = TRUE OR provisioning_status <> 'archived')
    ORDER BY item_type, sort_order, created_at;
END$$

-- ===================================================================================
-- sp_billing_catalog_item_adopt_refs
-- Reconcile repair: adopt existing Stripe product/price refs onto a local row missing
-- them. Never touches money/plan_code (api.auth owns the catalog). Marks the row
-- provisioned and stamps provisioned_at if not already set.
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_catalog_item_adopt_refs$$
CREATE PROCEDURE sp_billing_catalog_item_adopt_refs(
    IN p_id VARCHAR(64),
    IN p_provider_product_id_ciphertext LONGBLOB,
    IN p_provider_product_id_hmac BINARY(32),
    IN p_provider_product_id_fingerprint CHAR(12),
    IN p_provider_price_id_ciphertext LONGBLOB,
    IN p_provider_price_id_hmac BINARY(32),
    IN p_provider_price_id_fingerprint CHAR(12),
    IN p_provider_ref_key_id VARCHAR(128),
    IN p_lookup_key VARCHAR(200)
)
BEGIN
    UPDATE billing_catalog_items
    SET provider_product_id_ciphertext = p_provider_product_id_ciphertext,
        provider_product_id_hmac = p_provider_product_id_hmac,
        provider_product_id_fingerprint = p_provider_product_id_fingerprint,
        provider_price_id_ciphertext = p_provider_price_id_ciphertext,
        provider_price_id_hmac = p_provider_price_id_hmac,
        provider_price_id_fingerprint = p_provider_price_id_fingerprint,
        provider_ref_key_id = p_provider_ref_key_id,
        provider_ref_encryption_alg = 'fernet-v1',
        lookup_key = COALESCE(p_lookup_key, lookup_key),
        provisioning_status = CASE WHEN provisioning_status = 'archived' THEN provisioning_status ELSE 'active' END,
        provisioned_at = COALESCE(provisioned_at, NOW()),
        updated_at = NOW()
    WHERE id = p_id;

    SELECT id, catalog_item_hash, provisioning_status, provider_price_id_fingerprint
    FROM billing_catalog_items WHERE id = p_id LIMIT 1;
END$$

-- ===================================================================================
-- sp_billing_catalog_item_import
-- Idempotently adopt an orphan Stripe product/price as an already-provisioned catalog
-- item. If a non-archived row in the group already carries the same price fingerprint,
-- returns it without inserting (repeated imports are no-ops).
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_catalog_item_import$$
CREATE PROCEDURE sp_billing_catalog_item_import(
    IN p_id VARCHAR(64),
    IN p_catalog_item_hash VARCHAR(255),
    IN p_billing_group_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_item_type VARCHAR(32),
    IN p_plan_code VARCHAR(64),
    IN p_display_name VARCHAR(120),
    IN p_currency CHAR(3),
    IN p_unit_amount BIGINT,
    IN p_recurring_interval VARCHAR(8),
    IN p_lookup_key VARCHAR(200),
    IN p_provider_product_id_ciphertext LONGBLOB,
    IN p_provider_product_id_hmac BINARY(32),
    IN p_provider_product_id_fingerprint CHAR(12),
    IN p_provider_price_id_ciphertext LONGBLOB,
    IN p_provider_price_id_hmac BINARY(32),
    IN p_provider_price_id_fingerprint CHAR(12),
    IN p_provider_ref_key_id VARCHAR(128),
    IN p_provisioning_idempotency_key_hmac BINARY(32)
)
BEGIN
    DECLARE v_existing VARCHAR(64) DEFAULT NULL;

    SELECT id INTO v_existing
    FROM billing_catalog_items
    WHERE billing_group_id = p_billing_group_id
      AND provider = COALESCE(NULLIF(TRIM(p_provider), ''), 'stripe')
      AND provider_price_id_fingerprint = p_provider_price_id_fingerprint
      AND provisioning_status <> 'archived'
    LIMIT 1;

    IF v_existing IS NULL THEN
        INSERT INTO billing_catalog_items (
            id, catalog_item_hash, billing_group_id, provider, item_type, plan_code,
            display_name, currency, unit_amount, recurring_interval, lookup_key,
            provider_product_id_ciphertext, provider_product_id_hmac, provider_product_id_fingerprint,
            provider_price_id_ciphertext, provider_price_id_hmac, provider_price_id_fingerprint,
            provider_ref_key_id, provider_ref_encryption_alg, provisioning_idempotency_key_hmac,
            sort_order, active, provisioning_status, provisioned_at, created_at, updated_at
        ) VALUES (
            p_id, p_catalog_item_hash, p_billing_group_id,
            COALESCE(NULLIF(TRIM(p_provider), ''), 'stripe'), p_item_type, p_plan_code,
            p_display_name, p_currency, p_unit_amount, NULLIF(TRIM(p_recurring_interval), ''), p_lookup_key,
            p_provider_product_id_ciphertext, p_provider_product_id_hmac, p_provider_product_id_fingerprint,
            p_provider_price_id_ciphertext, p_provider_price_id_hmac, p_provider_price_id_fingerprint,
            p_provider_ref_key_id, 'fernet-v1', p_provisioning_idempotency_key_hmac,
            0, TRUE, 'active', NOW(), NOW(), NOW()
        );
        SET v_existing = p_id;
    END IF;

    SELECT id, catalog_item_hash, plan_code, provisioning_status, active,
           provider_price_id_fingerprint
    FROM billing_catalog_items WHERE id = v_existing LIMIT 1;
END$$

-- ===================================================================================
-- sp_billing_group_set_catalog_sync_status
-- Record the per-group catalog reconcile outcome (status/timestamp only; no secrets).
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_billing_group_set_catalog_sync_status$$
CREATE PROCEDURE sp_billing_group_set_catalog_sync_status(
    IN p_id VARCHAR(64),
    IN p_status VARCHAR(16),
    IN p_error_redacted TEXT,
    IN p_synced_at VARCHAR(40)
)
BEGIN
    UPDATE billing_groups
    SET catalog_sync_status = COALESCE(NULLIF(TRIM(p_status), ''), 'never'),
        catalog_sync_error_redacted = p_error_redacted,
        last_catalog_synced_at = COALESCE(
            CASE WHEN p_synced_at IS NULL OR p_synced_at = '' THEN NULL
                 ELSE STR_TO_DATE(SUBSTRING(REPLACE(p_synced_at, 'T', ' '), 1, 19), '%Y-%m-%d %H:%i:%s') END,
            NOW()),
        updated_at = NOW()
    WHERE id = p_id;

    SELECT id, billing_group_hash, catalog_sync_status, last_catalog_synced_at
    FROM billing_groups WHERE id = p_id LIMIT 1;
END$$

DELIMITER ;

-- ===================================================================================
-- BILLING GROUP & CATALOG PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'Billing group and catalog stored procedures created!' AS status,
       'Group CRUD + encrypted credentials, project mapping, catalog CRUD + provisioning transitions, per-project/per-group catalog listing, and project->group resolution' AS details;
