-- ===================================================================================
-- Provider-agnostic OAuth stored procedures (docs/agnostic_oauth)
-- ===================================================================================
-- Catalog, connections (encrypted credentials), project bindings, URL allow-lists, and
-- the namespace-aware external-identity procedures used by the shared OAuth pipeline.
--
-- The provider-keyed procedures in 15_external_accounts.sql are left untouched: Patreon
-- and older callers keep using them, and rows they write get identity_namespace = provider
-- from the insert trigger. The *_external_identity procedures below key on
-- (identity_namespace, provider_sub_hash) instead.
--
-- Two procedures return ciphertext and are SERVER-ONLY:
--   sp_oauth_connection_get_operational_credentials, sp_oauth_binding_get_legacy_redeem.
-- Nothing else selects a ciphertext or HMAC column.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
SET character_set_client = utf8mb4;
SET character_set_connection = utf8mb4;
SET character_set_results = utf8mb4;
SET collation_connection = utf8mb4_unicode_ci;

DELIMITER $$

-- ===================================================================================
-- CATALOG
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_oauth_catalog_list$$
CREATE PROCEDURE sp_oauth_catalog_list()
BEGIN
    SELECT c.id, c.provider_type, c.display_name, c.protocol, c.status,
           c.login_enabled, c.link_enabled, c.tenant_endpoints_allowed,
           c.default_scopes, c.capability_metadata, c.created_at, c.updated_at,
           (SELECT COUNT(*) FROM oauth_connections oc WHERE oc.provider_type = c.provider_type AND oc.status <> 'archived') AS connection_count
    FROM oauth_provider_catalog c
    ORDER BY c.display_name;
END$$

DROP PROCEDURE IF EXISTS sp_oauth_catalog_get$$
CREATE PROCEDURE sp_oauth_catalog_get(IN p_provider_type VARCHAR(32))
BEGIN
    SELECT id, provider_type, display_name, protocol, status, login_enabled, link_enabled,
           tenant_endpoints_allowed, default_scopes, capability_metadata, created_at, updated_at
    FROM oauth_provider_catalog
    WHERE provider_type = p_provider_type
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_oauth_catalog_set_status$$
CREATE PROCEDURE sp_oauth_catalog_set_status(
    IN p_provider_type VARCHAR(32),
    IN p_status VARCHAR(16),
    IN p_login_enabled BOOLEAN,
    IN p_link_enabled BOOLEAN,
    IN p_capability_metadata JSON
)
BEGIN
    -- Patreon is link authority only: it can never be made login-capable from here.
    IF p_provider_type = 'patreon' AND COALESCE(p_login_enabled, FALSE) = TRUE THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon cannot be enabled for login';
    END IF;

    UPDATE oauth_provider_catalog
    SET status = COALESCE(p_status, status),
        login_enabled = COALESCE(p_login_enabled, login_enabled),
        link_enabled = COALESCE(p_link_enabled, link_enabled),
        capability_metadata = COALESCE(p_capability_metadata, capability_metadata),
        updated_at = NOW()
    WHERE provider_type = p_provider_type;

    SELECT id, provider_type, display_name, protocol, status, login_enabled, link_enabled,
           tenant_endpoints_allowed, default_scopes, capability_metadata, created_at, updated_at
    FROM oauth_provider_catalog
    WHERE provider_type = p_provider_type
    LIMIT 1;
END$$

-- ===================================================================================
-- CONNECTIONS
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_oauth_connection_create$$
CREATE PROCEDURE sp_oauth_connection_create(
    IN p_id VARCHAR(64),
    IN p_connection_hash VARCHAR(255),
    IN p_provider_type VARCHAR(32),
    IN p_owner_project_id VARCHAR(64),
    IN p_display_name VARCHAR(120),
    IN p_client_id VARCHAR(512),
    IN p_issuer VARCHAR(512),
    IN p_discovery_url VARCHAR(1024),
    IN p_authorize_endpoint VARCHAR(1024),
    IN p_token_endpoint VARCHAR(1024),
    IN p_jwks_uri VARCHAR(1024),
    IN p_userinfo_endpoint VARCHAR(1024),
    IN p_scopes VARCHAR(512),
    IN p_restrictions JSON,
    IN p_provider_params JSON,
    IN p_identity_namespace VARCHAR(191),
    IN p_created_by VARCHAR(64)
)
BEGIN
    IF NOT EXISTS (SELECT 1 FROM oauth_provider_catalog WHERE provider_type = p_provider_type AND status <> 'archived') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unknown OAuth provider type';
    END IF;

    INSERT INTO oauth_connections (
        id, connection_hash, provider_type, owner_project_id, display_name, status,
        client_id, issuer, discovery_url, authorize_endpoint, token_endpoint, jwks_uri,
        userinfo_endpoint, scopes, restrictions, provider_params, identity_namespace,
        created_by, created_at
    ) VALUES (
        p_id, p_connection_hash, p_provider_type, p_owner_project_id, p_display_name, 'draft',
        p_client_id, p_issuer, p_discovery_url, p_authorize_endpoint, p_token_endpoint, p_jwks_uri,
        p_userinfo_endpoint, p_scopes, p_restrictions, p_provider_params, p_identity_namespace,
        p_created_by, NOW()
    );

    CALL sp_oauth_connection_get_by_id(p_id);
END$$

DROP PROCEDURE IF EXISTS sp_oauth_connection_update$$
CREATE PROCEDURE sp_oauth_connection_update(
    IN p_id VARCHAR(64),
    IN p_display_name VARCHAR(120),
    IN p_client_id VARCHAR(512),
    IN p_issuer VARCHAR(512),
    IN p_discovery_url VARCHAR(1024),
    IN p_authorize_endpoint VARCHAR(1024),
    IN p_token_endpoint VARCHAR(1024),
    IN p_jwks_uri VARCHAR(1024),
    IN p_userinfo_endpoint VARCHAR(1024),
    IN p_scopes VARCHAR(512),
    IN p_restrictions JSON,
    IN p_provider_params JSON,
    IN p_identity_namespace VARCHAR(191),
    IN p_updated_by VARCHAR(64)
)
BEGIN
    -- The application sends the complete non-secret field set. Namespace immutability once
    -- identities are linked is enforced by the BEFORE UPDATE trigger.
    UPDATE oauth_connections
    SET display_name = p_display_name,
        client_id = p_client_id,
        issuer = p_issuer,
        discovery_url = p_discovery_url,
        authorize_endpoint = p_authorize_endpoint,
        token_endpoint = p_token_endpoint,
        jwks_uri = p_jwks_uri,
        userinfo_endpoint = p_userinfo_endpoint,
        scopes = p_scopes,
        restrictions = p_restrictions,
        provider_params = p_provider_params,
        identity_namespace = p_identity_namespace,
        updated_by = p_updated_by,
        updated_at = NOW()
    WHERE id = p_id;

    CALL sp_oauth_connection_get_by_id(p_id);
END$$

DROP PROCEDURE IF EXISTS sp_oauth_connection_set_status$$
CREATE PROCEDURE sp_oauth_connection_set_status(
    IN p_id VARCHAR(64),
    IN p_status VARCHAR(16),
    IN p_updated_by VARCHAR(64)
)
BEGIN
    UPDATE oauth_connections
    SET status = p_status, updated_by = p_updated_by, updated_at = NOW()
    WHERE id = p_id;

    CALL sp_oauth_connection_get_by_id(p_id);
END$$

DROP PROCEDURE IF EXISTS sp_oauth_connection_set_credentials$$
CREATE PROCEDURE sp_oauth_connection_set_credentials(
    IN p_id VARCHAR(64),
    IN p_client_secret_ciphertext LONGBLOB,
    IN p_client_secret_hmac BINARY(32),
    IN p_client_secret_fingerprint CHAR(12),
    IN p_signing_key_ciphertext LONGBLOB,
    IN p_signing_key_hmac BINARY(32),
    IN p_signing_key_fingerprint CHAR(12),
    IN p_credential_key_id VARCHAR(128),
    IN p_set_by VARCHAR(64)
)
BEGIN
    IF (p_client_secret_ciphertext IS NULL OR OCTET_LENGTH(p_client_secret_ciphertext) = 0)
       AND (p_signing_key_ciphertext IS NULL OR OCTET_LENGTH(p_signing_key_ciphertext) = 0) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OAuth connection credentials require an encrypted secret';
    END IF;

    IF p_credential_key_id IS NULL OR p_credential_key_id = '' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OAuth connection credentials require a key id';
    END IF;

    UPDATE oauth_connections
    SET client_secret_ciphertext = p_client_secret_ciphertext,
        client_secret_hmac = p_client_secret_hmac,
        client_secret_fingerprint = p_client_secret_fingerprint,
        signing_key_ciphertext = p_signing_key_ciphertext,
        signing_key_hmac = p_signing_key_hmac,
        signing_key_fingerprint = p_signing_key_fingerprint,
        credential_key_id = p_credential_key_id,
        credential_encryption_alg = 'fernet-v1',
        credential_status = 'active',
        credentials_set_at = NOW(),
        credentials_set_by = p_set_by,
        updated_by = p_set_by,
        updated_at = NOW()
    WHERE id = p_id;

    CALL sp_oauth_connection_get_by_id(p_id);
END$$

DROP PROCEDURE IF EXISTS sp_oauth_connection_get_by_id$$
CREATE PROCEDURE sp_oauth_connection_get_by_id(IN p_id VARCHAR(64))
BEGIN
    SELECT oc.id, oc.connection_hash, oc.provider_type, oc.owner_project_id,
           op.project_hash AS owner_project_hash, op.project_name AS owner_project_name,
           oc.display_name, oc.status, oc.client_id,
           oc.credential_status, oc.credentials_set_at, oc.credential_key_id,
           oc.client_secret_fingerprint, oc.signing_key_fingerprint,
           (oc.client_secret_ciphertext IS NOT NULL) AS has_client_secret,
           (oc.signing_key_ciphertext IS NOT NULL) AS has_signing_key,
           oc.issuer, oc.discovery_url, oc.authorize_endpoint, oc.token_endpoint, oc.jwks_uri,
           oc.userinfo_endpoint, oc.scopes, oc.restrictions, oc.provider_params,
           oc.identity_namespace, oc.created_at, oc.updated_at,
           c.status AS catalog_status, c.login_enabled AS catalog_login_enabled,
           c.link_enabled AS catalog_link_enabled, c.tenant_endpoints_allowed,
           (SELECT COUNT(*) FROM project_oauth_bindings b WHERE b.connection_id = oc.id) AS binding_count,
           (SELECT COUNT(*) FROM user_external_accounts ea WHERE ea.connection_id = oc.id AND ea.status = 'linked') AS linked_identity_count
    FROM oauth_connections oc
    JOIN oauth_provider_catalog c ON c.provider_type = oc.provider_type
    LEFT JOIN projects op ON op.id = oc.owner_project_id
    WHERE oc.id = p_id
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_oauth_connection_get_by_hash$$
CREATE PROCEDURE sp_oauth_connection_get_by_hash(IN p_connection_hash VARCHAR(255))
BEGIN
    DECLARE v_id VARCHAR(64) DEFAULT NULL;
    SELECT id INTO v_id FROM oauth_connections WHERE connection_hash = p_connection_hash LIMIT 1;
    CALL sp_oauth_connection_get_by_id(v_id);
END$$

DROP PROCEDURE IF EXISTS sp_oauth_connection_get_operational_credentials$$
CREATE PROCEDURE sp_oauth_connection_get_operational_credentials(IN p_id VARCHAR(64))
BEGIN
    -- SERVER-ONLY. Returns encrypted material for the token exchange. Never expose to DTOs.
    SELECT id, provider_type, status, credential_status,
           client_secret_ciphertext, client_secret_hmac,
           signing_key_ciphertext, signing_key_hmac,
           credential_key_id, credential_encryption_alg
    FROM oauth_connections
    WHERE id = p_id
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_oauth_connection_list$$
CREATE PROCEDURE sp_oauth_connection_list(
    IN p_provider_type VARCHAR(32),
    IN p_status VARCHAR(16),
    IN p_search VARCHAR(120),
    IN p_limit INT,
    IN p_offset INT
)
BEGIN
    SELECT oc.id, oc.connection_hash, oc.provider_type, oc.owner_project_id,
           op.project_hash AS owner_project_hash, op.project_name AS owner_project_name,
           oc.display_name, oc.status, oc.credential_status, oc.credentials_set_at,
           oc.client_secret_fingerprint, oc.identity_namespace, oc.scopes,
           oc.created_at, oc.updated_at,
           c.status AS catalog_status,
           (SELECT COUNT(*) FROM project_oauth_bindings b WHERE b.connection_id = oc.id) AS binding_count
    FROM oauth_connections oc
    JOIN oauth_provider_catalog c ON c.provider_type = oc.provider_type
    LEFT JOIN projects op ON op.id = oc.owner_project_id
    WHERE (p_provider_type IS NULL OR p_provider_type = '' OR oc.provider_type = p_provider_type)
      AND (p_status IS NULL OR p_status = '' OR oc.status = p_status)
      AND (p_search IS NULL OR p_search = '' OR oc.display_name LIKE CONCAT('%', p_search, '%'))
    ORDER BY oc.display_name, oc.created_at
    LIMIT p_limit OFFSET p_offset;

    SELECT COUNT(*) AS total
    FROM oauth_connections oc
    WHERE (p_provider_type IS NULL OR p_provider_type = '' OR oc.provider_type = p_provider_type)
      AND (p_status IS NULL OR p_status = '' OR oc.status = p_status)
      AND (p_search IS NULL OR p_search = '' OR oc.display_name LIKE CONCAT('%', p_search, '%'));
END$$

DROP PROCEDURE IF EXISTS sp_oauth_connection_delete$$
CREATE PROCEDURE sp_oauth_connection_delete(IN p_id VARCHAR(64), IN p_deleted_by VARCHAR(64))
BEGIN
    DECLARE v_bindings INT DEFAULT 0;
    DECLARE v_identities INT DEFAULT 0;

    SELECT COUNT(*) INTO v_bindings FROM project_oauth_bindings WHERE connection_id = p_id;
    SELECT COUNT(*) INTO v_identities FROM user_external_accounts WHERE connection_id = p_id;

    IF v_bindings > 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OAuth connection is still bound to projects';
    END IF;

    -- A connection that people have signed in through is archived, never deleted: its
    -- namespace still identifies those users.
    IF v_identities > 0 THEN
        UPDATE oauth_connections
        SET status = 'archived', credential_status = 'revoked',
            client_secret_ciphertext = NULL, client_secret_hmac = NULL,
            signing_key_ciphertext = NULL, signing_key_hmac = NULL,
            updated_by = p_deleted_by, updated_at = NOW()
        WHERE id = p_id;
        SELECT 'archived' AS outcome;
    ELSE
        DELETE FROM oauth_connections WHERE id = p_id;
        SELECT 'deleted' AS outcome;
    END IF;
END$$

-- ===================================================================================
-- PROJECT BINDINGS
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_oauth_binding_select$$
CREATE PROCEDURE sp_oauth_binding_select(IN p_binding_id VARCHAR(64))
BEGIN
    -- One fully resolved row: binding policy + connection non-secret config + catalog gate.
    SELECT b.id AS binding_id, b.connection_key, b.enabled, b.login_enabled, b.link_enabled,
           b.provisioning_mode, b.existing_user_policy, b.init_mode, b.delivery_mode,
           b.state_ttl_seconds, b.rate_limit_overrides,
           (b.legacy_redeem_url_ciphertext IS NOT NULL AND b.legacy_redeem_token_ciphertext IS NOT NULL) AS has_legacy_redeem,
           b.created_at AS binding_created_at, b.updated_at AS binding_updated_at,
           p.id AS project_id, p.project_hash, p.project_name,
           p.is_active AS project_is_active, p.archived AS project_archived,
           b.default_user_group_id, ug.group_hash AS default_user_group_hash,
           ug.group_name AS default_user_group_name, ug.is_active AS default_user_group_is_active,
           EXISTS (
               SELECT 1
               FROM user_group_project_groups ugpg
               JOIN project_groups pg ON pg.id = ugpg.project_group_id AND pg.is_active = 1
               JOIN project_group_members pgm ON pgm.project_group_id = pg.id AND pgm.is_active = 1
               WHERE ugpg.user_group_id = b.default_user_group_id
                 AND ugpg.is_active = 1
                 AND pgm.project_id = b.project_id
           ) AS default_user_group_reaches_project,
           oc.id AS connection_id, oc.connection_hash, oc.provider_type, oc.display_name,
           oc.status AS connection_status, oc.credential_status, oc.client_id,
           oc.issuer, oc.discovery_url, oc.authorize_endpoint, oc.token_endpoint, oc.jwks_uri,
           oc.userinfo_endpoint, oc.scopes, oc.restrictions, oc.provider_params,
           oc.identity_namespace, oc.owner_project_id,
           c.status AS catalog_status, c.login_enabled AS catalog_login_enabled,
           c.link_enabled AS catalog_link_enabled, c.tenant_endpoints_allowed,
           (SELECT JSON_ARRAYAGG(u.url) FROM project_oauth_allowed_urls u
             WHERE u.binding_id = b.id AND u.kind = 'redirect_uri') AS redirect_uris,
           (SELECT JSON_ARRAYAGG(u.url) FROM project_oauth_allowed_urls u
             WHERE u.binding_id = b.id AND u.kind = 'return_origin') AS return_origins
    FROM project_oauth_bindings b
    JOIN projects p ON p.id = b.project_id
    JOIN oauth_connections oc ON oc.id = b.connection_id
    JOIN oauth_provider_catalog c ON c.provider_type = oc.provider_type
    LEFT JOIN user_groups ug ON ug.id = b.default_user_group_id
    WHERE b.id = p_binding_id
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_oauth_binding_upsert$$
CREATE PROCEDURE sp_oauth_binding_upsert(
    IN p_id VARCHAR(64),
    IN p_project_id VARCHAR(64),
    IN p_connection_id VARCHAR(64),
    IN p_connection_key VARCHAR(64),
    IN p_enabled BOOLEAN,
    IN p_login_enabled BOOLEAN,
    IN p_link_enabled BOOLEAN,
    IN p_provisioning_mode VARCHAR(16),
    IN p_default_user_group_id VARCHAR(64),
    IN p_existing_user_policy VARCHAR(32),
    IN p_init_mode VARCHAR(16),
    IN p_delivery_mode VARCHAR(16),
    IN p_state_ttl_seconds INT,
    IN p_rate_limit_overrides JSON,
    IN p_actor VARCHAR(64)
)
BEGIN
    DECLARE v_binding_id VARCHAR(64) DEFAULT NULL;

    IF NOT EXISTS (SELECT 1 FROM oauth_connections WHERE id = p_connection_id AND status <> 'archived') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OAuth connection not found';
    END IF;

    -- The provisioning group is api.auth's own validated configuration, never a caller's
    -- assertion: it must exist, be active, and actually reach this project.
    IF p_default_user_group_id IS NOT NULL THEN
        IF NOT EXISTS (SELECT 1 FROM user_groups WHERE id = p_default_user_group_id AND is_active = 1) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Default user group is not active';
        END IF;
        IF NOT EXISTS (
            SELECT 1
            FROM user_group_project_groups ugpg
            JOIN project_groups pg ON pg.id = ugpg.project_group_id AND pg.is_active = 1
            JOIN project_group_members pgm ON pgm.project_group_id = pg.id AND pgm.is_active = 1
            WHERE ugpg.user_group_id = p_default_user_group_id
              AND ugpg.is_active = 1
              AND pgm.project_id = p_project_id
        ) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Default user group does not reach this project';
        END IF;
    END IF;

    IF p_provisioning_mode IN ('auto_create','both') AND p_default_user_group_id IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Auto-create requires a default user group';
    END IF;

    IF p_existing_user_policy = 'join_default_group' AND p_default_user_group_id IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Join-default-group policy requires a default user group';
    END IF;

    SELECT id INTO v_binding_id
    FROM project_oauth_bindings
    WHERE project_id = p_project_id AND connection_key = p_connection_key
    LIMIT 1;

    IF v_binding_id IS NULL THEN
        SET v_binding_id = p_id;
        INSERT INTO project_oauth_bindings (
            id, project_id, connection_id, connection_key, enabled, login_enabled, link_enabled,
            provisioning_mode, default_user_group_id, existing_user_policy, init_mode,
            delivery_mode, state_ttl_seconds, rate_limit_overrides, created_by, created_at
        ) VALUES (
            v_binding_id, p_project_id, p_connection_id, p_connection_key,
            COALESCE(p_enabled, FALSE), COALESCE(p_login_enabled, TRUE), COALESCE(p_link_enabled, TRUE),
            COALESCE(p_provisioning_mode, 'disabled'), p_default_user_group_id,
            COALESCE(p_existing_user_policy, 'deny'), COALESCE(p_init_mode, 'api'),
            COALESCE(p_delivery_mode, 'bff'), p_state_ttl_seconds, p_rate_limit_overrides,
            p_actor, NOW()
        );
    ELSE
        UPDATE project_oauth_bindings
        SET connection_id = p_connection_id,
            enabled = COALESCE(p_enabled, enabled),
            login_enabled = COALESCE(p_login_enabled, login_enabled),
            link_enabled = COALESCE(p_link_enabled, link_enabled),
            provisioning_mode = COALESCE(p_provisioning_mode, provisioning_mode),
            default_user_group_id = p_default_user_group_id,
            existing_user_policy = COALESCE(p_existing_user_policy, existing_user_policy),
            init_mode = COALESCE(p_init_mode, init_mode),
            delivery_mode = COALESCE(p_delivery_mode, delivery_mode),
            state_ttl_seconds = p_state_ttl_seconds,
            rate_limit_overrides = p_rate_limit_overrides,
            updated_by = p_actor,
            updated_at = NOW()
        WHERE id = v_binding_id;
    END IF;

    CALL sp_oauth_binding_select(v_binding_id);
END$$

DROP PROCEDURE IF EXISTS sp_oauth_binding_set_legacy_redeem$$
CREATE PROCEDURE sp_oauth_binding_set_legacy_redeem(
    IN p_binding_id VARCHAR(64),
    IN p_url_ciphertext LONGBLOB,
    IN p_token_ciphertext LONGBLOB,
    IN p_key_id VARCHAR(128),
    IN p_actor VARCHAR(64)
)
BEGIN
    UPDATE project_oauth_bindings
    SET legacy_redeem_url_ciphertext = p_url_ciphertext,
        legacy_redeem_token_ciphertext = p_token_ciphertext,
        legacy_redeem_key_id = p_key_id,
        updated_by = p_actor,
        updated_at = NOW()
    WHERE id = p_binding_id;

    CALL sp_oauth_binding_select(p_binding_id);
END$$

DROP PROCEDURE IF EXISTS sp_oauth_binding_get_legacy_redeem$$
CREATE PROCEDURE sp_oauth_binding_get_legacy_redeem(IN p_binding_id VARCHAR(64))
BEGIN
    -- SERVER-ONLY. Returns encrypted companion-handshake material. Never expose to DTOs.
    SELECT id AS binding_id, legacy_redeem_url_ciphertext, legacy_redeem_token_ciphertext, legacy_redeem_key_id
    FROM project_oauth_bindings
    WHERE id = p_binding_id AND init_mode = 'legacy_redeem'
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_oauth_binding_get$$
CREATE PROCEDURE sp_oauth_binding_get(IN p_project_hash VARCHAR(255), IN p_connection_key VARCHAR(64))
BEGIN
    DECLARE v_binding_id VARCHAR(64) DEFAULT NULL;
    SELECT b.id INTO v_binding_id
    FROM project_oauth_bindings b
    JOIN projects p ON p.id = b.project_id
    WHERE p.project_hash = p_project_hash AND b.connection_key = p_connection_key
    LIMIT 1;
    CALL sp_oauth_binding_select(v_binding_id);
END$$

DROP PROCEDURE IF EXISTS sp_oauth_binding_get_by_ids$$
CREATE PROCEDURE sp_oauth_binding_get_by_ids(IN p_connection_id VARCHAR(64), IN p_binding_id VARCHAR(64))
BEGIN
    DECLARE v_binding_id VARCHAR(64) DEFAULT NULL;
    SELECT id INTO v_binding_id
    FROM project_oauth_bindings
    WHERE id = p_binding_id AND connection_id = p_connection_id
    LIMIT 1;
    CALL sp_oauth_binding_select(v_binding_id);
END$$

DROP PROCEDURE IF EXISTS sp_oauth_binding_list_for_project$$
CREATE PROCEDURE sp_oauth_binding_list_for_project(IN p_project_hash VARCHAR(255))
BEGIN
    SELECT b.id AS binding_id
    FROM project_oauth_bindings b
    JOIN projects p ON p.id = b.project_id
    WHERE p.project_hash = p_project_hash
    ORDER BY b.connection_key;
END$$

DROP PROCEDURE IF EXISTS sp_oauth_binding_list_for_connection$$
CREATE PROCEDURE sp_oauth_binding_list_for_connection(IN p_connection_id VARCHAR(64))
BEGIN
    SELECT b.id AS binding_id
    FROM project_oauth_bindings b
    JOIN projects p ON p.id = b.project_id
    WHERE b.connection_id = p_connection_id
    ORDER BY p.project_name;
END$$

DROP PROCEDURE IF EXISTS sp_oauth_binding_list_legacy$$
CREATE PROCEDURE sp_oauth_binding_list_legacy(IN p_connection_key VARCHAR(64))
BEGIN
    SELECT b.id AS binding_id
    FROM project_oauth_bindings b
    WHERE b.init_mode = 'legacy_redeem' AND b.connection_key = p_connection_key
    ORDER BY b.created_at;
END$$

DROP PROCEDURE IF EXISTS sp_oauth_binding_delete$$
CREATE PROCEDURE sp_oauth_binding_delete(IN p_binding_id VARCHAR(64))
BEGIN
    DELETE FROM project_oauth_bindings WHERE id = p_binding_id;
    SELECT ROW_COUNT() AS removed;
END$$

DROP PROCEDURE IF EXISTS sp_oauth_binding_url_add$$
CREATE PROCEDURE sp_oauth_binding_url_add(
    IN p_id VARCHAR(64),
    IN p_binding_id VARCHAR(64),
    IN p_kind VARCHAR(16),
    IN p_url VARCHAR(2048),
    IN p_url_hash BINARY(32),
    IN p_created_by VARCHAR(64)
)
BEGIN
    IF p_url_hash IS NULL OR OCTET_LENGTH(p_url_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Allowed URL hash must be 32 bytes';
    END IF;

    INSERT INTO project_oauth_allowed_urls (id, binding_id, kind, url, url_hash, created_by, created_at)
    VALUES (p_id, p_binding_id, p_kind, p_url, p_url_hash, p_created_by, NOW())
    ON DUPLICATE KEY UPDATE url = VALUES(url);

    SELECT id, binding_id, kind, url, created_at
    FROM project_oauth_allowed_urls
    WHERE binding_id = p_binding_id AND kind = p_kind AND url_hash = p_url_hash
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_oauth_binding_url_remove$$
CREATE PROCEDURE sp_oauth_binding_url_remove(IN p_binding_id VARCHAR(64), IN p_url_id VARCHAR(64))
BEGIN
    DELETE FROM project_oauth_allowed_urls WHERE id = p_url_id AND binding_id = p_binding_id;
    SELECT ROW_COUNT() AS removed;
END$$

DROP PROCEDURE IF EXISTS sp_oauth_binding_urls$$
CREATE PROCEDURE sp_oauth_binding_urls(IN p_binding_id VARCHAR(64))
BEGIN
    SELECT id, binding_id, kind, url, created_at
    FROM project_oauth_allowed_urls
    WHERE binding_id = p_binding_id
    ORDER BY kind, created_at;
END$$

-- ===================================================================================
-- NAMESPACE-AWARE EXTERNAL IDENTITIES
-- ===================================================================================
DROP PROCEDURE IF EXISTS sp_get_user_by_external_identity$$
CREATE PROCEDURE sp_get_user_by_external_identity(
    IN p_identity_namespace VARCHAR(191),
    IN p_provider_sub_hash BINARY(32)
)
BEGIN
    IF p_provider_sub_hash IS NULL OR OCTET_LENGTH(p_provider_sub_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject hash must be 32 bytes';
    END IF;

    SELECT u.id, u.user_hash, u.username, u.email, u.user_type, u.is_active, u.created_at,
           ea.id AS external_account_id, ea.provider, ea.identity_namespace,
           ea.provider_sub_fingerprint, ea.provider_email_masked,
           ea.provider_email_verified_at_link, ea.status AS external_account_status,
           ea.linked_at, ea.last_seen_at
    FROM user_external_accounts ea
    JOIN users u ON u.id = ea.user_id
    WHERE ea.identity_namespace = p_identity_namespace
      AND ea.provider_sub_hash = p_provider_sub_hash
      AND ea.status = 'linked'
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_touch_external_identity_last_seen$$
CREATE PROCEDURE sp_touch_external_identity_last_seen(
    IN p_identity_namespace VARCHAR(191),
    IN p_provider_sub_hash BINARY(32),
    IN p_provider_email_hash BINARY(32),
    IN p_provider_email_masked VARCHAR(255),
    IN p_provider_email_verified_at_link BOOLEAN
)
BEGIN
    UPDATE user_external_accounts
    SET last_seen_at = NOW(),
        provider_email_hash = COALESCE(p_provider_email_hash, provider_email_hash),
        provider_email_masked = COALESCE(p_provider_email_masked, provider_email_masked),
        provider_email_verified_at_link = COALESCE(p_provider_email_verified_at_link, provider_email_verified_at_link)
    WHERE identity_namespace = p_identity_namespace
      AND provider_sub_hash = p_provider_sub_hash
      AND status = 'linked';

    SELECT ROW_COUNT() AS touched;
END$$

DROP PROCEDURE IF EXISTS sp_link_external_identity$$
CREATE PROCEDURE sp_link_external_identity(
    IN p_external_account_id VARCHAR(64),
    IN p_user_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_identity_namespace VARCHAR(191),
    IN p_connection_id VARCHAR(64),
    IN p_provider_sub_hash BINARY(32),
    IN p_provider_sub_fingerprint CHAR(12),
    IN p_provider_email_hash BINARY(32),
    IN p_provider_email_masked VARCHAR(255),
    IN p_provider_email_verified_at_link BOOLEAN,
    IN p_linked_by VARCHAR(64),
    IN p_metadata JSON
)
BEGIN
    DECLARE v_existing_user VARCHAR(64) DEFAULT NULL;
    DECLARE v_existing_hash BINARY(32) DEFAULT NULL;

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF NOT EXISTS (
        SELECT 1 FROM oauth_provider_catalog
        WHERE provider_type = p_provider AND status IN ('enabled','degraded') AND link_enabled = TRUE
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unsupported external account provider';
    END IF;
    IF p_provider_sub_hash IS NULL OR OCTET_LENGTH(p_provider_sub_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject hash must be 32 bytes';
    END IF;
    IF p_provider_sub_fingerprint IS NULL OR CHAR_LENGTH(p_provider_sub_fingerprint) <> 12 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account fingerprint must be 12 characters';
    END IF;

    START TRANSACTION;

    SELECT user_id INTO v_existing_user
    FROM user_external_accounts
    WHERE identity_namespace = p_identity_namespace
      AND provider_sub_hash = p_provider_sub_hash
      AND status = 'linked'
    LIMIT 1
    FOR UPDATE;

    IF v_existing_user IS NOT NULL AND v_existing_user <> p_user_id THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject is already linked';
    END IF;

    SELECT provider_sub_hash INTO v_existing_hash
    FROM user_external_accounts
    WHERE user_id = p_user_id
      AND identity_namespace = p_identity_namespace
      AND status = 'linked'
    LIMIT 1
    FOR UPDATE;

    IF v_existing_hash IS NOT NULL AND v_existing_hash <> p_provider_sub_hash THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'User already has an active external account for this provider';
    END IF;

    IF v_existing_hash IS NOT NULL THEN
        UPDATE user_external_accounts
        SET provider_sub_fingerprint = p_provider_sub_fingerprint,
            provider_email_hash = p_provider_email_hash,
            provider_email_masked = p_provider_email_masked,
            provider_email_verified_at_link = COALESCE(p_provider_email_verified_at_link, FALSE),
            last_seen_at = NOW()
        WHERE user_id = p_user_id
          AND identity_namespace = p_identity_namespace
          AND status = 'linked';
    ELSE
        INSERT INTO user_external_accounts (
            id, user_id, provider, identity_namespace, connection_id,
            provider_sub_hash, provider_sub_fingerprint, provider_email_hash,
            provider_email_masked, provider_email_verified_at_link, status, linked_at,
            linked_by, last_seen_at, metadata
        ) VALUES (
            p_external_account_id, p_user_id, p_provider, p_identity_namespace, p_connection_id,
            p_provider_sub_hash, p_provider_sub_fingerprint, p_provider_email_hash,
            p_provider_email_masked, COALESCE(p_provider_email_verified_at_link, FALSE), 'linked', NOW(),
            p_linked_by, NOW(), p_metadata
        );
    END IF;

    COMMIT;

    SELECT id, user_id, provider, identity_namespace, provider_sub_fingerprint,
           provider_email_masked, provider_email_verified_at_link, status, linked_at
    FROM user_external_accounts
    WHERE user_id = p_user_id
      AND identity_namespace = p_identity_namespace
      AND status = 'linked'
    LIMIT 1;
END$$

DROP PROCEDURE IF EXISTS sp_unlink_external_identity$$
CREATE PROCEDURE sp_unlink_external_identity(
    IN p_user_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_identity_namespace VARCHAR(191),
    IN p_unlinked_by VARCHAR(64),
    IN p_reason VARCHAR(64)
)
BEGIN
    -- A namespace ending in ':*' (a multi-tenant connection) unlinks that provider's
    -- identities under the prefix; any other namespace matches exactly.
    UPDATE user_external_accounts
    SET status = 'unlinked',
        unlinked_at = NOW(),
        unlinked_by = p_unlinked_by,
        unlink_reason = p_reason
    WHERE user_id = p_user_id
      AND provider = p_provider
      AND status = 'linked'
      AND (
            identity_namespace = p_identity_namespace
            OR (RIGHT(p_identity_namespace, 2) = ':*'
                AND identity_namespace LIKE CONCAT(LEFT(p_identity_namespace, CHAR_LENGTH(p_identity_namespace) - 1), '%'))
          );

    SELECT ROW_COUNT() AS unlinked;
END$$

DROP PROCEDURE IF EXISTS sp_list_external_accounts_for_user$$
CREATE PROCEDURE sp_list_external_accounts_for_user(IN p_user_id VARCHAR(64))
BEGIN
    SELECT id, provider, identity_namespace, provider_sub_fingerprint, provider_email_masked,
           provider_email_verified_at_link, status, linked_at, last_seen_at
    FROM user_external_accounts
    WHERE user_id = p_user_id AND status = 'linked'
    ORDER BY linked_at;
END$$

-- Create a local consumer and link the external identity in one transaction. The
-- provisioning policy and the group are read from the BINDING inside this transaction
-- whenever a binding id is given, so the caller cannot choose either.
DROP PROCEDURE IF EXISTS sp_create_consumer_user_from_external_identity$$
CREATE PROCEDURE sp_create_consumer_user_from_external_identity(
    IN p_user_id VARCHAR(64),
    IN p_user_hash VARCHAR(255),
    IN p_username VARCHAR(100),
    IN p_password_hash VARCHAR(255),
    IN p_external_account_id VARCHAR(64),
    IN p_provider VARCHAR(32),
    IN p_identity_namespace VARCHAR(191),
    IN p_connection_id VARCHAR(64),
    IN p_binding_id VARCHAR(64),
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
    DECLARE v_existing INT DEFAULT 0;
    DECLARE v_group_id VARCHAR(64) DEFAULT NULL;
    DECLARE v_mode VARCHAR(16) DEFAULT NULL;
    DECLARE v_group_member_id VARCHAR(64);

    DECLARE EXIT HANDLER FOR SQLEXCEPTION
    BEGIN
        ROLLBACK;
        RESIGNAL;
    END;

    IF NOT EXISTS (
        SELECT 1 FROM oauth_provider_catalog
        WHERE provider_type = p_provider AND status = 'enabled' AND login_enabled = TRUE
    ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unsupported external account provider';
    END IF;
    IF p_provider_sub_hash IS NULL OR OCTET_LENGTH(p_provider_sub_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject hash must be 32 bytes';
    END IF;
    IF p_provider_sub_fingerprint IS NULL OR CHAR_LENGTH(p_provider_sub_fingerprint) <> 12 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account fingerprint must be 12 characters';
    END IF;

    SET v_group_id = p_user_group_id;
    IF p_binding_id IS NOT NULL THEN
        SELECT provisioning_mode, default_user_group_id INTO v_mode, v_group_id
        FROM project_oauth_bindings
        WHERE id = p_binding_id AND enabled = TRUE AND login_enabled = TRUE
        LIMIT 1;
        IF v_mode IS NULL OR v_mode NOT IN ('auto_create','both') THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Binding does not permit auto-provisioning';
        END IF;
    END IF;

    IF v_group_id IS NULL
       OR NOT EXISTS (SELECT 1 FROM user_groups WHERE id = v_group_id AND is_active = TRUE) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Provider-bound user group is not active';
    END IF;

    START TRANSACTION;

    SELECT COUNT(*) INTO v_existing
    FROM user_external_accounts
    WHERE identity_namespace = p_identity_namespace
      AND provider_sub_hash = p_provider_sub_hash
      AND status = 'linked'
    FOR UPDATE;

    IF v_existing > 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject is already linked';
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

    SET v_group_member_id = COALESCE(p_group_member_id, CONCAT('ugm-', REPLACE(UUID(), '-', '')));
    INSERT INTO user_group_members (
        id, user_id, user_group_id, assigned_at, assigned_by, is_active
    ) VALUES (
        v_group_member_id, p_user_id, v_group_id, NOW(), p_created_by, TRUE
    ) ON DUPLICATE KEY UPDATE
        is_active = TRUE,
        assigned_at = NOW(),
        assigned_by = VALUES(assigned_by);

    INSERT INTO user_external_accounts (
        id, user_id, provider, identity_namespace, connection_id,
        provider_sub_hash, provider_sub_fingerprint, provider_email_hash,
        provider_email_masked, provider_email_verified_at_link, status, linked_at,
        linked_by, last_seen_at, metadata
    ) VALUES (
        p_external_account_id, p_user_id, p_provider, p_identity_namespace, p_connection_id,
        p_provider_sub_hash, p_provider_sub_fingerprint, p_provider_email_hash,
        p_provider_email_masked, COALESCE(p_provider_email_verified_at_link, FALSE), 'linked', NOW(),
        p_created_by, NOW(), p_metadata
    );

    COMMIT;

    SELECT u.id, u.user_hash, u.username, u.email, u.user_type, u.is_active, u.created_at,
           ea.id AS external_account_id, ea.provider, ea.identity_namespace,
           ea.provider_sub_fingerprint, ea.provider_email_masked,
           ea.provider_email_verified_at_link, ea.status AS external_account_status
    FROM users u
    JOIN user_external_accounts ea ON ea.user_id = u.id AND ea.id = p_external_account_id
    WHERE u.id = p_user_id
    LIMIT 1;
END$$

DELIMITER ;

-- ===================================================================================
-- OAUTH CONNECTION PROCEDURES COMPLETE
-- ===================================================================================
SELECT 'OAuth connection stored procedures created!' AS status,
       'Catalog kill switch, connection CRUD + encrypted credentials, project bindings with validated default group, exact-match URL allow-lists, namespace-aware external identities' AS details;
