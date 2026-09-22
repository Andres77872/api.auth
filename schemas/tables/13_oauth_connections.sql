-- ===================================================================================
-- Provider-agnostic OAuth configuration (docs/agnostic_oauth)
-- ===================================================================================
-- Three levels:
--   oauth_provider_catalog   provider TYPE registry + master kill switch (adapter code lives
--                            in src/Util/oauth/adapters; a type is usable only when it is
--                            registered in code AND enabled here).
--   oauth_connections        one OAuth client at one provider: non-secret config plus
--                            ENCRYPTED credentials. May be shared by several projects.
--   project_oauth_bindings   per-project policy for one connection, with exact-match URL
--                            allow-lists in project_oauth_allowed_urls.
--
-- Secrets: client secrets, signing keys and legacy redeem tokens are stored ONLY as
-- ciphertext with a key id. HMAC/fingerprint columns exist for row-binding checks and safe
-- display. Peppers, the state HMAC key and the encryption keys stay in the environment.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- =================== PROVIDER TYPE REGISTRY ===================
CREATE TABLE IF NOT EXISTS oauth_provider_catalog (
    id VARCHAR(64) NOT NULL,
    provider_type VARCHAR(32) NOT NULL,
    display_name VARCHAR(120) NOT NULL,
    protocol ENUM('oidc','oauth2','custom') NOT NULL,
    status ENUM('disabled','enabled','degraded','archived') NOT NULL DEFAULT 'disabled',
    login_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    link_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    tenant_endpoints_allowed BOOLEAN NOT NULL DEFAULT FALSE,
    default_scopes VARCHAR(512) NULL,
    capability_metadata JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_oauth_provider_type (provider_type),
    INDEX idx_oauth_provider_status (status, login_enabled)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== CONNECTIONS ===================
CREATE TABLE IF NOT EXISTS oauth_connections (
    id VARCHAR(64) NOT NULL,
    connection_hash VARCHAR(255) NOT NULL,
    provider_type VARCHAR(32) NOT NULL,
    owner_project_id VARCHAR(64) NULL COMMENT 'NULL = platform-owned, shareable across projects',
    display_name VARCHAR(120) NOT NULL,
    status ENUM('draft','active','disabled','archived') NOT NULL DEFAULT 'draft',

    client_id VARCHAR(512) NOT NULL,
    client_secret_ciphertext LONGBLOB NULL,
    client_secret_hmac BINARY(32) NULL,
    client_secret_fingerprint CHAR(12) NULL,
    signing_key_ciphertext LONGBLOB NULL,
    signing_key_hmac BINARY(32) NULL,
    signing_key_fingerprint CHAR(12) NULL,
    credential_key_id VARCHAR(128) NULL,
    credential_encryption_alg VARCHAR(32) NOT NULL DEFAULT 'fernet-v1',
    credential_status ENUM('absent','active','rotating','revoked') NOT NULL DEFAULT 'absent',
    credentials_set_at DATETIME NULL,
    credentials_set_by VARCHAR(64) NULL,

    issuer VARCHAR(512) NULL,
    discovery_url VARCHAR(1024) NULL,
    authorize_endpoint VARCHAR(1024) NULL,
    token_endpoint VARCHAR(1024) NULL,
    jwks_uri VARCHAR(1024) NULL,
    userinfo_endpoint VARCHAR(1024) NULL,

    scopes VARCHAR(512) NOT NULL,
    restrictions JSON NULL,
    provider_params JSON NULL,
    identity_namespace VARCHAR(191) NOT NULL,

    created_by VARCHAR(64) NULL,
    updated_by VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_oauth_connection_hash (connection_hash),
    INDEX idx_oauth_connection_owner (owner_project_id, status),
    INDEX idx_oauth_connection_type (provider_type, status),
    CONSTRAINT fk_oauth_connection_type FOREIGN KEY (provider_type)
        REFERENCES oauth_provider_catalog(provider_type) ON UPDATE CASCADE,
    CONSTRAINT fk_oauth_connection_owner FOREIGN KEY (owner_project_id)
        REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_oauth_connection_created_by FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_oauth_connection_updated_by FOREIGN KEY (updated_by)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PROJECT BINDINGS ===================
CREATE TABLE IF NOT EXISTS project_oauth_bindings (
    id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    connection_id VARCHAR(64) NOT NULL,
    connection_key VARCHAR(64) NOT NULL COMMENT 'slug used in routes: google, acme-okta',
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    login_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    link_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    provisioning_mode ENUM('disabled','link_only','auto_create','both') NOT NULL DEFAULT 'disabled',
    default_user_group_id VARCHAR(64) NULL,
    existing_user_policy ENUM('deny','join_default_group') NOT NULL DEFAULT 'deny',
    init_mode ENUM('api','legacy_redeem') NOT NULL DEFAULT 'api',
    legacy_redeem_url_ciphertext LONGBLOB NULL,
    legacy_redeem_token_ciphertext LONGBLOB NULL,
    legacy_redeem_key_id VARCHAR(128) NULL,
    delivery_mode ENUM('bff','hosted') NOT NULL DEFAULT 'bff',
    state_ttl_seconds SMALLINT UNSIGNED NULL COMMENT 'NULL = deployment default; capped by the env ceiling',
    rate_limit_overrides JSON NULL COMMENT 'may only lower the deployment ceilings',
    created_by VARCHAR(64) NULL,
    updated_by VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_project_oauth_key (project_id, connection_key),
    UNIQUE KEY uk_project_oauth_connection (project_id, connection_id),
    INDEX idx_pob_connection (connection_id, enabled),
    INDEX idx_pob_init_mode (init_mode, connection_key),
    CONSTRAINT fk_pob_project FOREIGN KEY (project_id)
        REFERENCES projects(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_pob_connection FOREIGN KEY (connection_id)
        REFERENCES oauth_connections(id) ON DELETE RESTRICT ON UPDATE CASCADE,
    CONSTRAINT fk_pob_group FOREIGN KEY (default_user_group_id)
        REFERENCES user_groups(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_pob_created_by FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_pob_updated_by FOREIGN KEY (updated_by)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== EXACT-MATCH URL ALLOW-LISTS ===================
-- One row per URL. Matching is exact string equality; there is no prefix, wildcard or
-- "default to the first entry" behaviour.
CREATE TABLE IF NOT EXISTS project_oauth_allowed_urls (
    id VARCHAR(64) NOT NULL,
    binding_id VARCHAR(64) NOT NULL,
    kind ENUM('redirect_uri','return_origin','return_to') NOT NULL,
    url VARCHAR(2048) NOT NULL,
    url_hash BINARY(32) NOT NULL COMMENT 'SHA-256 of the exact string',
    created_by VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_poau (binding_id, kind, url_hash),
    CONSTRAINT fk_poau_binding FOREIGN KEY (binding_id)
        REFERENCES project_oauth_bindings(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_poau_created_by FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== CATALOG SEED ===================
-- Re-running this file must never undo an operator's kill-switch decision, so the upsert
-- refreshes descriptive columns only: status, login_enabled and link_enabled are set on the
-- FIRST insert and left alone afterwards.
--   patreon  link-only by design; login_enabled stays FALSE so the database itself keeps
--            refusing Patreon logins.
--   oidc     tenant-supplied endpoints (mix-up and SSRF surface): seeded DISABLED; a root
--            operator enables it deliberately.
INSERT INTO oauth_provider_catalog
    (id, provider_type, display_name, protocol, status, login_enabled, link_enabled, tenant_endpoints_allowed, default_scopes)
VALUES
    ('oapc-google',    'google',    'Google',           'oidc',   'enabled',  TRUE,  TRUE,  FALSE, 'openid email'),
    ('oapc-github',    'github',    'GitHub',           'oauth2', 'enabled',  TRUE,  TRUE,  FALSE, 'read:user user:email'),
    ('oapc-discord',   'discord',   'Discord',          'oauth2', 'enabled',  TRUE,  TRUE,  FALSE, 'identify email'),
    ('oapc-microsoft', 'microsoft', 'Microsoft',        'oidc',   'enabled',  TRUE,  TRUE,  FALSE, 'openid profile email'),
    ('oapc-oidc',      'oidc',      'OpenID Connect',   'oidc',   'disabled', TRUE,  TRUE,  TRUE,  'openid email'),
    ('oapc-patreon',   'patreon',   'Patreon',          'custom', 'enabled',  FALSE, TRUE,  FALSE, NULL)
ON DUPLICATE KEY UPDATE
    display_name = VALUES(display_name),
    protocol = VALUES(protocol),
    tenant_endpoints_allowed = VALUES(tenant_endpoints_allowed),
    default_scopes = VALUES(default_scopes),
    updated_at = NOW();

SELECT 'OAuth connection tables created successfully!' AS status,
       '4 tables: oauth_provider_catalog, oauth_connections, project_oauth_bindings, project_oauth_allowed_urls; secrets are ciphertext-only' AS details;
