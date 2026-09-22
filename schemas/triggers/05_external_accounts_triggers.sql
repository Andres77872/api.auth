-- ===================================================================================
-- External Account Integrity Triggers
-- ===================================================================================
-- Database-boundary invariants for external account lifecycle rows. Which provider
-- types exist is data in oauth_provider_catalog, not a literal list here, and these
-- triggers check ONLY that: the provider must have a catalog row. They do not read the
-- row's status, login_enabled or link_enabled -- whether a type may log in is application
-- policy (Patreon stays no-login entitlement/link authority: its row is seeded with
-- login_enabled = FALSE and the administration API refuses to enable it). A catalog row
-- is therefore schema, not disposable data: deleting one makes every write for that
-- provider fail closed. Workflow ownership stays in stored procedures and policy code.
--
-- identity_namespace scopes the subject and is immutable. Rows written by older,
-- provider-keyed procedures arrive without one and get identity_namespace = provider.
-- ===================================================================================

USE magic_auth;

DELIMITER //

DROP TRIGGER IF EXISTS trg_external_accounts_before_insert//
CREATE TRIGGER trg_external_accounts_before_insert BEFORE INSERT ON user_external_accounts FOR EACH ROW
BEGIN
    IF NOT EXISTS (SELECT 1 FROM oauth_provider_catalog WHERE provider_type = NEW.provider) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unsupported external account provider';
    END IF;

    IF NEW.identity_namespace IS NULL OR NEW.identity_namespace = '' THEN
        SET NEW.identity_namespace = NEW.provider;
    END IF;

    IF NEW.provider_sub_hash IS NULL OR OCTET_LENGTH(NEW.provider_sub_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject hash must be 32 bytes';
    END IF;

    IF NEW.provider_sub_fingerprint IS NULL OR CHAR_LENGTH(NEW.provider_sub_fingerprint) <> 12 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account fingerprint must be 12 characters';
    END IF;

    IF NEW.linked_at IS NULL THEN
        SET NEW.linked_at = NOW();
    END IF;

    IF NEW.status = 'linked' AND NEW.unlinked_at IS NOT NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Linked external account cannot have unlink time';
    END IF;

    IF NEW.status IN ('unlinked','revoked') AND NEW.unlinked_at IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal external account status requires unlink time';
    END IF;

    IF NEW.unlinked_at IS NOT NULL AND NEW.unlinked_at < NEW.linked_at THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account unlink time cannot precede link time';
    END IF;

    IF NEW.last_seen_at IS NOT NULL AND NEW.last_seen_at < NEW.linked_at THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account last seen cannot precede link time';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_external_accounts_before_update//
CREATE TRIGGER trg_external_accounts_before_update BEFORE UPDATE ON user_external_accounts FOR EACH ROW
BEGIN
    -- The one permitted namespace change is the backfill of rows that predate the column.
    IF NEW.provider <> OLD.provider
       OR NEW.user_id <> OLD.user_id
       OR NEW.provider_sub_hash <> OLD.provider_sub_hash
       OR (NEW.identity_namespace <> OLD.identity_namespace AND OLD.identity_namespace <> '') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account identity fields are immutable';
    END IF;

    IF NOT EXISTS (SELECT 1 FROM oauth_provider_catalog WHERE provider_type = NEW.provider) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unsupported external account provider';
    END IF;

    IF NEW.provider_sub_hash IS NULL OR OCTET_LENGTH(NEW.provider_sub_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account subject hash must be 32 bytes';
    END IF;

    IF NEW.provider_sub_fingerprint IS NULL OR CHAR_LENGTH(NEW.provider_sub_fingerprint) <> 12 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account fingerprint must be 12 characters';
    END IF;

    IF OLD.status IN ('unlinked','revoked') AND NEW.status <> OLD.status THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal external account status is immutable';
    END IF;

    IF OLD.status = 'linked' AND NEW.status NOT IN ('linked','unlinked','revoked') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Illegal external account status transition';
    END IF;

    IF OLD.status = 'linked' AND NEW.status IN ('unlinked','revoked') AND NEW.unlinked_at IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal external account transition requires unlink time';
    END IF;

    IF NEW.status = 'linked' AND NEW.unlinked_at IS NOT NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Linked external account cannot have unlink time';
    END IF;

    IF NEW.unlinked_at IS NOT NULL AND NEW.unlinked_at < NEW.linked_at THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account unlink time cannot precede link time';
    END IF;

    IF NEW.last_seen_at IS NOT NULL AND NEW.last_seen_at < NEW.linked_at THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account last seen cannot precede link time';
    END IF;
END//

DELIMITER ;

SELECT 'External account triggers created!' AS status,
       'Integrity triggers for catalog-validated, namespace-keyed user_external_accounts' AS details;
