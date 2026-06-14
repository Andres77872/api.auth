-- ===================================================================================
-- Email Activation Integrity Triggers
-- ===================================================================================
-- Defensive database-boundary checks for email activation data. Stored procedures own
-- workflow transitions; these triggers only enforce invariants that must never be
-- bypassed by ad-hoc writes.
--
-- Privacy posture:
-- - No plaintext token material is logged, copied, or generated here.
-- - users.email is not read here and does not become authoritative.
-- ===================================================================================

USE magic_auth;

DELIMITER //

-- ===================================================================================
-- USER_EMAILS SAFETY
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_user_emails_before_insert//
CREATE TRIGGER trg_user_emails_before_insert BEFORE INSERT ON user_emails FOR EACH ROW
BEGIN
    DECLARE v_active_email_count INT DEFAULT 0;

    SET NEW.email_normalized = LOWER(TRIM(NEW.email_normalized));

    IF NEW.status <> 'activated' AND NEW.is_primary = TRUE THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only activated email rows may be primary';
    END IF;

    IF NEW.removed_at IS NOT NULL AND NEW.is_primary = TRUE THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Removed email rows may not be primary';
    END IF;

    IF NEW.status IN ('pending','activated') AND NEW.removed_at IS NULL THEN
        SELECT COUNT(*) INTO v_active_email_count
        FROM user_emails
        WHERE user_id = NEW.user_id
          AND status IN ('pending','activated')
          AND removed_at IS NULL;

        IF v_active_email_count >= 5 THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'User cannot have more than five active email rows';
        END IF;
    END IF;
END//

DROP TRIGGER IF EXISTS trg_user_emails_before_update//
CREATE TRIGGER trg_user_emails_before_update BEFORE UPDATE ON user_emails FOR EACH ROW
BEGIN
    DECLARE v_active_email_count INT DEFAULT 0;

    SET NEW.email_normalized = LOWER(TRIM(NEW.email_normalized));

    IF NEW.status <> 'activated' AND NEW.is_primary = TRUE THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only activated email rows may be primary';
    END IF;

    IF NEW.removed_at IS NOT NULL AND NEW.is_primary = TRUE THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Removed email rows may not be primary';
    END IF;

    IF NEW.status IN ('pending','activated') AND NEW.removed_at IS NULL
       AND NOT (OLD.status IN ('pending','activated') AND OLD.removed_at IS NULL) THEN
        SELECT COUNT(*) INTO v_active_email_count
        FROM user_emails
        WHERE user_id = NEW.user_id
          AND id <> OLD.id
          AND status IN ('pending','activated')
          AND removed_at IS NULL;

        IF v_active_email_count >= 5 THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'User cannot have more than five active email rows';
        END IF;
    END IF;
END//

-- ===================================================================================
-- HASH-ONLY LINK TOKEN SAFETY
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_email_link_tokens_before_insert//
CREATE TRIGGER trg_email_link_tokens_before_insert BEFORE INSERT ON user_email_link_tokens FOR EACH ROW
BEGIN
    IF NEW.expires_at <= NOW() THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Email link token expiry must be in the future';
    END IF;

    IF OCTET_LENGTH(NEW.token_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Email link token hash must be 32 bytes';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_email_link_tokens_before_update//
CREATE TRIGGER trg_email_link_tokens_before_update BEFORE UPDATE ON user_email_link_tokens FOR EACH ROW
BEGIN
    IF OLD.consumed_at IS NOT NULL OR OLD.revoked_at IS NOT NULL THEN
        IF NOT (OLD.consumed_at <=> NEW.consumed_at)
           OR NOT (OLD.revoked_at <=> NEW.revoked_at)
           OR NOT (OLD.revocation_reason <=> NEW.revocation_reason)
           OR OLD.lookup_id <> NEW.lookup_id
           OR OLD.purpose <> NEW.purpose
           OR NOT (OLD.token_hash <=> NEW.token_hash)
           OR OLD.user_id <> NEW.user_id
           OR NOT (OLD.user_email_id <=> NEW.user_email_id) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal email link token state is immutable';
        END IF;
    END IF;

    IF NEW.expires_at <= NEW.created_at THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Email link token expiry must be after creation';
    END IF;
END//

-- ===================================================================================
-- EMAIL OUTBOX MESSAGE SAFETY
-- ===================================================================================

DROP TRIGGER IF EXISTS trg_email_messages_before_insert//
CREATE TRIGGER trg_email_messages_before_insert BEFORE INSERT ON email_messages FOR EACH ROW
BEGIN
    IF NEW.payload_purge_at <= NOW() THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Email message payload purge time must be in the future';
    END IF;

    IF NEW.max_attempts < 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Email message max_attempts must be positive';
    END IF;

    IF NEW.attempt_count < 0 OR NEW.attempt_count > NEW.max_attempts THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Email message attempt_count is outside allowed range';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_email_messages_before_update//
CREATE TRIGGER trg_email_messages_before_update BEFORE UPDATE ON email_messages FOR EACH ROW
BEGIN
    IF NEW.max_attempts < 1 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Email message max_attempts must be positive';
    END IF;

    IF NEW.attempt_count < 0 OR NEW.attempt_count > NEW.max_attempts THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Email message attempt_count is outside allowed range';
    END IF;

    IF NEW.status IN ('sent','delivered','bounced','complained','suppressed','dead','cancelled') THEN
        SET NEW.render_payload_ciphertext = NULL;
        SET NEW.lease_until = NULL;
    END IF;
END//

DELIMITER ;

-- ===================================================================================
-- EMAIL ACTIVATION TRIGGERS CREATED
-- ===================================================================================
SELECT 'Email activation triggers created!' AS status,
       'Integrity triggers for user_emails, user_email_link_tokens, and email_messages' AS details;
