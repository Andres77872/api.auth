-- ===================================================================================
-- External Account Integrity Triggers
-- ===================================================================================
-- Database-boundary invariants for Google and Patreon external account lifecycle
-- rows. Google may be login-capable in application policy; Patreon is no-login
-- entitlement/link authority only. Workflow ownership stays in stored procedures
-- and application policy code.
-- ===================================================================================

USE magic_auth;

DELIMITER //

DROP TRIGGER IF EXISTS trg_external_accounts_before_insert//
CREATE TRIGGER trg_external_accounts_before_insert BEFORE INSERT ON user_external_accounts FOR EACH ROW
BEGIN
    IF NEW.provider NOT IN ('google','patreon') THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unsupported external account provider';
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
    IF NEW.provider <> OLD.provider
       OR NEW.user_id <> OLD.user_id
       OR NEW.provider_sub_hash <> OLD.provider_sub_hash THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'External account identity fields are immutable';
    END IF;

    IF NEW.provider NOT IN ('google','patreon') THEN
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
       'Integrity triggers for google|patreon user_external_accounts' AS details;
