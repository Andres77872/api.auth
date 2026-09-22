-- ===================================================================================
-- OAuth Connection Integrity Triggers (docs/agnostic_oauth)
-- ===================================================================================
-- Fail-closed backstop behind the application checks:
--   * an ACTIVE connection must hold active, encrypted credentials with a key id;
--   * HMAC columns are exactly 32 bytes;
--   * tenant-supplied endpoints are accepted only for provider types whose catalog row
--     allows them (the generic 'oidc' type) -- built-in types use compiled-in endpoints;
--   * the provider type and, once identities are linked, the identity namespace of a
--     connection are immutable: re-pointing a connection would let a different issuer
--     impersonate the users already linked through it.
-- ===================================================================================

USE magic_auth;

DELIMITER //

DROP TRIGGER IF EXISTS trg_oauth_connections_before_insert//
CREATE TRIGGER trg_oauth_connections_before_insert BEFORE INSERT ON oauth_connections FOR EACH ROW
BEGIN
    DECLARE v_tenant_endpoints BOOLEAN DEFAULT FALSE;

    SELECT tenant_endpoints_allowed INTO v_tenant_endpoints
    FROM oauth_provider_catalog WHERE provider_type = NEW.provider_type LIMIT 1;

    IF NEW.identity_namespace IS NULL OR NEW.identity_namespace = '' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OAuth connection requires an identity namespace';
    END IF;

    IF COALESCE(v_tenant_endpoints, FALSE) = FALSE
       AND (NEW.discovery_url IS NOT NULL OR NEW.authorize_endpoint IS NOT NULL
            OR NEW.token_endpoint IS NOT NULL OR NEW.jwks_uri IS NOT NULL
            OR NEW.userinfo_endpoint IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Provider type does not accept tenant-supplied endpoints';
    END IF;

    IF NEW.status = 'active' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OAuth connection cannot be created active';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_oauth_connections_before_update//
CREATE TRIGGER trg_oauth_connections_before_update BEFORE UPDATE ON oauth_connections FOR EACH ROW
BEGIN
    DECLARE v_tenant_endpoints BOOLEAN DEFAULT FALSE;
    DECLARE v_linked INT DEFAULT 0;

    IF NEW.provider_type <> OLD.provider_type THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OAuth connection provider type is immutable';
    END IF;

    IF NEW.identity_namespace <> OLD.identity_namespace THEN
        SELECT COUNT(*) INTO v_linked FROM user_external_accounts WHERE connection_id = OLD.id;
        IF v_linked > 0 THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OAuth connection identity namespace is immutable once identities are linked';
        END IF;
    END IF;

    SELECT tenant_endpoints_allowed INTO v_tenant_endpoints
    FROM oauth_provider_catalog WHERE provider_type = NEW.provider_type LIMIT 1;

    IF COALESCE(v_tenant_endpoints, FALSE) = FALSE
       AND (NEW.discovery_url IS NOT NULL OR NEW.authorize_endpoint IS NOT NULL
            OR NEW.token_endpoint IS NOT NULL OR NEW.jwks_uri IS NOT NULL
            OR NEW.userinfo_endpoint IS NOT NULL) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Provider type does not accept tenant-supplied endpoints';
    END IF;

    IF NEW.client_secret_hmac IS NOT NULL AND OCTET_LENGTH(NEW.client_secret_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OAuth client secret HMAC must be 32 bytes';
    END IF;

    IF NEW.signing_key_hmac IS NOT NULL AND OCTET_LENGTH(NEW.signing_key_hmac) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'OAuth signing key HMAC must be 32 bytes';
    END IF;

    IF NEW.credential_status = 'active'
       AND ((NEW.client_secret_ciphertext IS NULL AND NEW.signing_key_ciphertext IS NULL)
            OR NEW.credential_key_id IS NULL OR NEW.credential_key_id = '') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Active OAuth credentials require ciphertext and a key id';
    END IF;

    IF NEW.status = 'active' AND NEW.credential_status <> 'active' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'An active OAuth connection requires active credentials';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_project_oauth_bindings_before_insert//
CREATE TRIGGER trg_project_oauth_bindings_before_insert BEFORE INSERT ON project_oauth_bindings FOR EACH ROW
BEGIN
    IF NEW.provisioning_mode IN ('auto_create','both') AND NEW.default_user_group_id IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Auto-create requires a default user group';
    END IF;
    IF NEW.connection_key IS NULL OR NEW.connection_key = '' OR NEW.connection_key REGEXP '[^a-z0-9_-]' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Connection key must be a lowercase slug';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_project_oauth_bindings_before_update//
CREATE TRIGGER trg_project_oauth_bindings_before_update BEFORE UPDATE ON project_oauth_bindings FOR EACH ROW
BEGIN
    IF NEW.project_id <> OLD.project_id OR NEW.connection_key <> OLD.connection_key THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Binding project and connection key are immutable';
    END IF;
    IF NEW.provisioning_mode IN ('auto_create','both') AND NEW.default_user_group_id IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Auto-create requires a default user group';
    END IF;
END//

DELIMITER ;

SELECT 'OAuth connection triggers created!' AS status,
       'Fail-closed credential, endpoint, namespace-immutability and binding-policy backstops' AS details;
