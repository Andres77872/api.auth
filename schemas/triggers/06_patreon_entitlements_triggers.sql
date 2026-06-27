-- ===================================================================================
-- Patreon Entitlement Integrity Triggers
-- ===================================================================================
-- Defense-in-depth checks for Patreon link/proof/entitlement rows. These triggers
-- enforce immutable HMAC identifiers, terminal states, retention caps, and raw
-- token/payload safety where SQL can enforce it. Application code remains responsible
-- for computing HMACs/fingerprints and for keeping raw provider values server-only.
-- ===================================================================================

USE magic_auth;

DELIMITER //

-- =================== PROOF SAFETY ===================
DROP TRIGGER IF EXISTS trg_patreon_link_proofs_before_insert//
CREATE TRIGGER trg_patreon_link_proofs_before_insert BEFORE INSERT ON patreon_link_proofs FOR EACH ROW
BEGIN
    IF NEW.token_hash IS NULL OR OCTET_LENGTH(NEW.token_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon proof token hash must be 32 bytes';
    END IF;

    IF NEW.proof_email_hash IS NULL OR OCTET_LENGTH(NEW.proof_email_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon proof email hash must be 32 bytes';
    END IF;

    IF NEW.patreon_user_id_hash IS NOT NULL AND OCTET_LENGTH(NEW.patreon_user_id_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon user hash must be 32 bytes';
    END IF;

    IF NEW.member_id_hash IS NOT NULL AND OCTET_LENGTH(NEW.member_id_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon member hash must be 32 bytes';
    END IF;

    IF NEW.expires_at <= NOW() THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon proof expiry must be in the future';
    END IF;

    IF NEW.purge_after_at IS NULL THEN
        SET NEW.purge_after_at = DATE_ADD(NEW.expires_at, INTERVAL 24 HOUR);
    END IF;

    IF NEW.purge_after_at > DATE_ADD(NEW.expires_at, INTERVAL 24 HOUR) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon proof retention cannot exceed expiry plus 24 hours';
    END IF;

    IF NEW.attempts < 0 OR NEW.max_attempts < 1 OR NEW.attempts > NEW.max_attempts THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon proof attempts are outside allowed range';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_link_proofs_before_update//
CREATE TRIGGER trg_patreon_link_proofs_before_update BEFORE UPDATE ON patreon_link_proofs FOR EACH ROW
BEGIN
    IF OLD.status IN ('consumed','expired','revoked','blocked') THEN
        IF NOT (OLD.token_hash <=> NEW.token_hash)
           OR OLD.lookup_id <> NEW.lookup_id
           OR OLD.user_id <> NEW.user_id
           OR NOT (OLD.proof_email_hash <=> NEW.proof_email_hash)
           OR NOT (OLD.member_id_hash <=> NEW.member_id_hash)
           OR NOT (OLD.patreon_user_id_hash <=> NEW.patreon_user_id_hash) THEN
            SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal Patreon proof identity is immutable';
        END IF;
    END IF;

    IF NEW.token_hash IS NULL OR OCTET_LENGTH(NEW.token_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon proof token hash must be 32 bytes';
    END IF;

    IF NEW.purge_after_at > DATE_ADD(NEW.expires_at, INTERVAL 24 HOUR) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon proof retention cannot exceed expiry plus 24 hours';
    END IF;
END//

-- =================== CAMPAIGN AND TIER MAP SAFETY ===================
DROP TRIGGER IF EXISTS trg_patreon_campaigns_before_insert//
CREATE TRIGGER trg_patreon_campaigns_before_insert BEFORE INSERT ON patreon_campaigns FOR EACH ROW
BEGIN
    IF NEW.campaign_id_hash IS NULL OR OCTET_LENGTH(NEW.campaign_id_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon campaign hash must be 32 bytes';
    END IF;

    IF NEW.campaign_id_fingerprint IS NULL OR CHAR_LENGTH(NEW.campaign_id_fingerprint) <> 12 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon campaign fingerprint must be 12 characters';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_campaigns_before_update//
CREATE TRIGGER trg_patreon_campaigns_before_update BEFORE UPDATE ON patreon_campaigns FOR EACH ROW
BEGIN
    IF NOT (OLD.campaign_id_hash <=> NEW.campaign_id_hash)
       OR OLD.campaign_id_fingerprint <> NEW.campaign_id_fingerprint THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon campaign HMAC identity is immutable';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_tier_map_before_insert//
CREATE TRIGGER trg_patreon_tier_map_before_insert BEFORE INSERT ON patreon_tier_map FOR EACH ROW
BEGIN
    IF NEW.tier_id_hash IS NULL OR OCTET_LENGTH(NEW.tier_id_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon tier hash must be 32 bytes';
    END IF;

    IF NEW.tier_id_fingerprint IS NULL OR CHAR_LENGTH(NEW.tier_id_fingerprint) <> 12 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon tier fingerprint must be 12 characters';
    END IF;

    IF NEW.effective_until IS NOT NULL AND NEW.effective_until <= NEW.effective_from THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon tier map effective_until must be after effective_from';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_tier_map_before_update//
CREATE TRIGGER trg_patreon_tier_map_before_update BEFORE UPDATE ON patreon_tier_map FOR EACH ROW
BEGIN
    IF OLD.campaign_id <> NEW.campaign_id
       OR NOT (OLD.tier_id_hash <=> NEW.tier_id_hash)
       OR OLD.tier_id_fingerprint <> NEW.tier_id_fingerprint THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon tier map provider identity is immutable';
    END IF;

    IF NEW.effective_until IS NOT NULL AND NEW.effective_until <= NEW.effective_from THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon tier map effective_until must be after effective_from';
    END IF;
END//

-- =================== MEMBERSHIP SAFETY ===================
DROP TRIGGER IF EXISTS trg_patreon_memberships_before_insert//
CREATE TRIGGER trg_patreon_memberships_before_insert BEFORE INSERT ON patreon_memberships FOR EACH ROW
BEGIN
    IF NEW.member_id_hash IS NULL OR OCTET_LENGTH(NEW.member_id_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon member hash must be 32 bytes';
    END IF;

    IF NEW.patreon_user_id_hash IS NULL OR OCTET_LENGTH(NEW.patreon_user_id_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon user hash must be 32 bytes';
    END IF;

    IF NEW.status IN ('unlinked','revoked') AND NEW.unlinked_at IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal Patreon membership status requires unlink time';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_memberships_before_update//
CREATE TRIGGER trg_patreon_memberships_before_update BEFORE UPDATE ON patreon_memberships FOR EACH ROW
BEGIN
    IF OLD.user_id <> NEW.user_id
       OR OLD.external_account_id <> NEW.external_account_id
       OR OLD.campaign_id <> NEW.campaign_id
       OR NOT (OLD.member_id_hash <=> NEW.member_id_hash)
       OR NOT (OLD.patreon_user_id_hash <=> NEW.patreon_user_id_hash) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon membership HMAC identity is immutable';
    END IF;

    IF OLD.status IN ('unlinked','revoked') AND NEW.status <> OLD.status THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal Patreon membership status is immutable';
    END IF;

    IF NEW.status IN ('unlinked','revoked') AND NEW.unlinked_at IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Terminal Patreon membership status requires unlink time';
    END IF;

    IF NEW.unlinked_at IS NOT NULL AND NEW.linked_at IS NOT NULL AND NEW.unlinked_at < NEW.linked_at THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon unlink time cannot precede link time';
    END IF;
END//

-- =================== SNAPSHOT / CURRENT / HISTORY SAFETY ===================
DROP TRIGGER IF EXISTS trg_patreon_member_snapshots_before_insert//
CREATE TRIGGER trg_patreon_member_snapshots_before_insert BEFORE INSERT ON patreon_member_snapshots FOR EACH ROW
BEGIN
    IF NEW.payload_hash IS NOT NULL AND OCTET_LENGTH(NEW.payload_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon snapshot payload hash must be 32 bytes';
    END IF;

    IF NEW.observed_at > DATE_ADD(NOW(), INTERVAL 5 MINUTE) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon snapshot observed_at cannot be in the future';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_current_before_insert//
CREATE TRIGGER trg_patreon_current_before_insert BEFORE INSERT ON patreon_entitlements_current FOR EACH ROW
BEGIN
    IF NEW.external_source <> 'patreon' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon current entitlement external_source must be patreon';
    END IF;

    IF NEW.plan_code IS NULL OR NEW.plan_code = '' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon current entitlement requires a plan_code';
    END IF;

    IF NEW.link_status IN ('unlinked','revoked')
       AND (
           NEW.entitlement_status = 'active'
           OR NEW.plan_code <> 'free'
           OR NEW.tier_code IS NOT NULL
           OR NEW.tier_name IS NOT NULL
       ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unlinked/revoked Patreon entitlement must not grant paid plan';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_current_before_update//
CREATE TRIGGER trg_patreon_current_before_update BEFORE UPDATE ON patreon_entitlements_current FOR EACH ROW
BEGIN
    IF OLD.user_id <> NEW.user_id THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon current entitlement user is immutable';
    END IF;

    IF NEW.external_source <> 'patreon' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon current entitlement external_source must be patreon';
    END IF;

    IF NEW.link_status IN ('unlinked','revoked')
       AND (
           NEW.entitlement_status = 'active'
           OR NEW.plan_code <> 'free'
           OR NEW.tier_code IS NOT NULL
           OR NEW.tier_name IS NOT NULL
       ) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Unlinked/revoked Patreon entitlement must not grant paid plan';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_entitlement_history_before_insert//
CREATE TRIGGER trg_patreon_entitlement_history_before_insert BEFORE INSERT ON patreon_entitlement_history FOR EACH ROW
BEGIN
    IF NEW.new_status IS NULL OR NEW.new_plan_code IS NULL THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon entitlement history requires new status and plan';
    END IF;
END//

-- =================== WEBHOOK / SYNC / QUARANTINE / TOKEN STATE SAFETY ===================
DROP TRIGGER IF EXISTS trg_patreon_webhook_deliveries_before_insert//
CREATE TRIGGER trg_patreon_webhook_deliveries_before_insert BEFORE INSERT ON patreon_webhook_deliveries FOR EACH ROW
BEGIN
    IF NEW.delivery_hash IS NULL OR OCTET_LENGTH(NEW.delivery_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon webhook delivery hash must be 32 bytes';
    END IF;

    IF NEW.raw_body_sha256 IS NULL OR OCTET_LENGTH(NEW.raw_body_sha256) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon webhook body digest must be 32 bytes';
    END IF;

    IF NEW.expires_at IS NULL THEN
        SET NEW.expires_at = DATE_ADD(NEW.received_at, INTERVAL 90 DAY);
    END IF;

    IF NEW.expires_at > DATE_ADD(NEW.received_at, INTERVAL 90 DAY) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon webhook delivery retention cannot exceed 90 days';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_webhook_deliveries_before_update//
CREATE TRIGGER trg_patreon_webhook_deliveries_before_update BEFORE UPDATE ON patreon_webhook_deliveries FOR EACH ROW
BEGIN
    IF NOT (OLD.delivery_hash <=> NEW.delivery_hash)
       OR NOT (OLD.raw_body_sha256 <=> NEW.raw_body_sha256)
       OR OLD.event_type <> NEW.event_type THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon webhook delivery idempotency identity is immutable';
    END IF;

    IF NEW.expires_at > DATE_ADD(NEW.received_at, INTERVAL 90 DAY) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon webhook delivery retention cannot exceed 90 days';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_sync_jobs_before_insert//
CREATE TRIGGER trg_patreon_sync_jobs_before_insert BEFORE INSERT ON patreon_sync_jobs FOR EACH ROW
BEGIN
    IF NEW.dedupe_key_hash IS NULL OR OCTET_LENGTH(NEW.dedupe_key_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon sync dedupe key hash must be 32 bytes';
    END IF;

    IF NEW.attempts < 0 OR NEW.max_attempts < 1 OR NEW.attempts > NEW.max_attempts THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon sync attempts are outside allowed range';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_raw_payload_quarantine_before_insert//
CREATE TRIGGER trg_patreon_raw_payload_quarantine_before_insert BEFORE INSERT ON patreon_raw_payload_quarantine FOR EACH ROW
BEGIN
    IF NEW.payload_hash IS NULL OR OCTET_LENGTH(NEW.payload_hash) <> 32 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon raw payload hash must be 32 bytes';
    END IF;

    IF NEW.purge_at > DATE_ADD(NEW.received_at, INTERVAL 30 DAY) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon raw payload quarantine retention cannot exceed 30 days';
    END IF;

    IF NEW.payload_ciphertext IS NULL OR OCTET_LENGTH(NEW.payload_ciphertext) = 0 THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon raw payload quarantine requires encrypted ciphertext';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_raw_payload_quarantine_before_update//
CREATE TRIGGER trg_patreon_raw_payload_quarantine_before_update BEFORE UPDATE ON patreon_raw_payload_quarantine FOR EACH ROW
BEGIN
    IF NOT (OLD.payload_hash <=> NEW.payload_hash)
       OR OLD.source <> NEW.source THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon raw payload quarantine identity is immutable';
    END IF;

    IF NEW.purge_at > DATE_ADD(NEW.received_at, INTERVAL 30 DAY) THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon raw payload quarantine retention cannot exceed 30 days';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_provider_token_state_before_insert//
CREATE TRIGGER trg_patreon_provider_token_state_before_insert BEFORE INSERT ON patreon_provider_token_state FOR EACH ROW
BEGIN
    IF NEW.provider <> 'patreon' OR NEW.token_kind <> 'creator' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Only global Patreon creator token state is allowed';
    END IF;

    IF NEW.encryption_key_id IS NULL OR NEW.encryption_key_id = '' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Encrypted Patreon token state requires key id';
    END IF;
END//

DROP TRIGGER IF EXISTS trg_patreon_provider_token_state_before_update//
CREATE TRIGGER trg_patreon_provider_token_state_before_update BEFORE UPDATE ON patreon_provider_token_state FOR EACH ROW
BEGIN
    IF OLD.provider <> NEW.provider OR OLD.token_kind <> NEW.token_kind THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Patreon token state provider identity is immutable';
    END IF;

    IF NEW.encryption_key_id IS NULL OR NEW.encryption_key_id = '' THEN
        SIGNAL SQLSTATE '45000' SET MESSAGE_TEXT = 'Encrypted Patreon token state requires key id';
    END IF;
END//

DELIMITER ;

-- ===================================================================================
-- PATREON TRIGGERS CREATED
-- ===================================================================================
SELECT 'Patreon entitlement triggers created!' AS status,
       'Integrity triggers for immutable HMAC identifiers, terminal states, retention caps, and encrypted raw payload/token safety' AS details;
