-- ===================================================================================
-- Patreon Account Link, Entitlement, Webhook, and Sync Tables
-- ===================================================================================
-- Patreon is entitlement/link authority only. Local api.auth sessions, JWTs,
-- refresh-token state, and /auth/validate remain identity-only. Raw Patreon IDs are
-- represented by application-computed HMACs plus short support fingerprints. No
-- per-user Patreon token columns exist in these tables; optional creator-token state
-- is global, encrypted, and server-only.
--
-- Retention split:
-- - Link, membership, snapshot, entitlement, and unlink history: indefinite.
-- - Webhook delivery hashes / sanitized ledger: 90 days.
-- - Proof requests: purged 24 hours after expiry.
-- - Raw payload quarantine: disabled-by-default, encrypted/server-only, max 30 days.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- =================== PATREON LINK PROOFS ===================
-- Hash-only split proof tokens for email-loop ownership proof. This deliberately does
-- not reuse user_email_link_tokens, which belongs to local email activation/reset.
CREATE TABLE IF NOT EXISTS patreon_link_proofs (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    external_account_id VARCHAR(64) NULL,
    campaign_id VARCHAR(64) NULL,
    patreon_user_id_hash BINARY(32) NULL,
    patreon_user_id_fingerprint CHAR(12) NULL,
    member_id_hash BINARY(32) NULL,
    member_id_fingerprint CHAR(12) NULL,
    proof_email_hash BINARY(32) NOT NULL,
    proof_email_masked VARCHAR(255) NOT NULL,
    lookup_id VARCHAR(32) NOT NULL,
    token_hash BINARY(32) NOT NULL,
    token_fingerprint CHAR(12) NOT NULL,
    status ENUM('pending','consumed','expired','revoked','blocked') NOT NULL DEFAULT 'pending',
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 8,
    expires_at DATETIME NOT NULL,
    purge_after_at DATETIME NOT NULL,
    consumed_at DATETIME NULL,
    created_ip_hash BINARY(32) NULL,
    consumed_ip_hash BINARY(32) NULL,
    created_user_agent_hash BINARY(32) NULL,
    consumed_user_agent_hash BINARY(32) NULL,
    email_message_id VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    metadata JSON NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_patreon_proofs_lookup (lookup_id),
    INDEX idx_patreon_proofs_user_status (user_id, status, expires_at),
    INDEX idx_patreon_proofs_token_hash (token_hash),
    INDEX idx_patreon_proofs_email_hash (proof_email_hash, created_at),
    INDEX idx_patreon_proofs_purge (purge_after_at),
    CONSTRAINT fk_patreon_proofs_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_patreon_proofs_external FOREIGN KEY (external_account_id)
        REFERENCES user_external_accounts(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_patreon_proofs_message FOREIGN KEY (email_message_id)
        REFERENCES email_messages(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PATREON CAMPAIGNS ===================
CREATE TABLE IF NOT EXISTS patreon_campaigns (
    id VARCHAR(64) NOT NULL,
    campaign_id_hash BINARY(32) NOT NULL,
    campaign_id_fingerprint CHAR(12) NOT NULL,
    display_name VARCHAR(120) NULL,
    status ENUM('enabled','disabled','archived') NOT NULL DEFAULT 'disabled',
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    metadata JSON NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_patreon_campaign_hash (campaign_id_hash),
    UNIQUE KEY uk_patreon_campaign_fingerprint (campaign_id_fingerprint),
    INDEX idx_patreon_campaign_enabled (enabled, status)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PATREON TIER MAP ===================
-- Raw campaign/tier IDs are read only by server-side config/seed tooling. The DB keeps
-- HMACs/fingerprints plus internal plan/tier codes used for safe classification.
CREATE TABLE IF NOT EXISTS patreon_tier_map (
    id VARCHAR(64) NOT NULL,
    campaign_id VARCHAR(64) NOT NULL,
    tier_id_hash BINARY(32) NOT NULL,
    tier_id_fingerprint CHAR(12) NOT NULL,
    plan_code VARCHAR(64) NOT NULL,
    tier_code VARCHAR(64) NOT NULL,
    tier_name VARCHAR(120) NULL,
    priority INT NOT NULL DEFAULT 0,
    active BOOLEAN NOT NULL DEFAULT TRUE,
    effective_from DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    effective_until DATETIME NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    metadata JSON NULL,

    active_tier_hash BINARY(32)
        GENERATED ALWAYS AS (
            CASE WHEN active = TRUE AND effective_until IS NULL THEN tier_id_hash ELSE NULL END
        ) VIRTUAL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_patreon_tier_active (campaign_id, active_tier_hash),
    INDEX idx_patreon_tier_campaign_priority (campaign_id, active, priority),
    INDEX idx_patreon_tier_fingerprint (tier_id_fingerprint),
    CONSTRAINT fk_patreon_tier_campaign FOREIGN KEY (campaign_id)
        REFERENCES patreon_campaigns(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PATREON MEMBERSHIPS ===================
CREATE TABLE IF NOT EXISTS patreon_memberships (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    external_account_id VARCHAR(64) NOT NULL,
    campaign_id VARCHAR(64) NOT NULL,
    member_id_hash BINARY(32) NOT NULL,
    member_id_fingerprint CHAR(12) NOT NULL,
    patreon_user_id_hash BINARY(32) NOT NULL,
    patreon_user_id_fingerprint CHAR(12) NOT NULL,
    status ENUM('pending','proof_required','active','blocked','conflict','unlinked','revoked','stale') NOT NULL DEFAULT 'pending',
    linked_at DATETIME NULL,
    last_seen_at DATETIME NULL,
    unlinked_at DATETIME NULL,
    unlink_reason VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    metadata JSON NULL,

    active_member_hash BINARY(32)
        GENERATED ALWAYS AS (
            CASE
                WHEN status IN ('pending','proof_required','active','stale') THEN member_id_hash
                ELSE NULL
            END
        ) VIRTUAL,
    active_user_campaign VARCHAR(160)
        GENERATED ALWAYS AS (
            CASE
                WHEN status IN ('pending','proof_required','active','stale') THEN CONCAT(user_id, ':', campaign_id)
                ELSE NULL
            END
        ) VIRTUAL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_patreon_membership_active_member (campaign_id, active_member_hash),
    UNIQUE KEY uk_patreon_membership_active_user_campaign (active_user_campaign),
    INDEX idx_patreon_membership_external (external_account_id, status),
    INDEX idx_patreon_membership_user_status (user_id, status, last_seen_at),
    INDEX idx_patreon_membership_member_fp (member_id_fingerprint),
    CONSTRAINT fk_patreon_membership_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_patreon_membership_external FOREIGN KEY (external_account_id)
        REFERENCES user_external_accounts(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_patreon_membership_campaign FOREIGN KEY (campaign_id)
        REFERENCES patreon_campaigns(id) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== PATREON MEMBER SNAPSHOTS ===================
CREATE TABLE IF NOT EXISTS patreon_member_snapshots (
    id VARCHAR(64) NOT NULL,
    membership_id VARCHAR(64) NOT NULL,
    observed_at DATETIME NOT NULL,
    sync_source ENUM('webhook','api_pull','manual_resync','link_activation','admin_correction') NOT NULL,
    patron_status_normalized ENUM('active_patron','declined_patron','former_patron','unknown','none') NOT NULL DEFAULT 'unknown',
    currently_entitled_tiers_json JSON NULL,
    tier_hashes_json JSON NULL,
    last_charge_status_normalized VARCHAR(64) NULL,
    last_charge_at DATETIME NULL,
    next_charge_at DATETIME NULL,
    payload_hash BINARY(32) NULL,
    is_complete BOOLEAN NOT NULL DEFAULT FALSE,
    requires_resync BOOLEAN NOT NULL DEFAULT FALSE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sanitized_metadata JSON NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_patreon_snapshot_payload (membership_id, payload_hash),
    INDEX idx_patreon_snapshot_membership_time (membership_id, observed_at),
    INDEX idx_patreon_snapshot_resync (requires_resync, observed_at),
    CONSTRAINT fk_patreon_snapshot_membership FOREIGN KEY (membership_id)
        REFERENCES patreon_memberships(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Append-only membership observation history. Retained indefinitely, privacy-minimized.
CREATE TABLE IF NOT EXISTS patreon_member_snapshot_history (
    id VARCHAR(64) NOT NULL,
    membership_id VARCHAR(64) NOT NULL,
    snapshot_id VARCHAR(64) NULL,
    event_type VARCHAR(64) NOT NULL,
    previous_status VARCHAR(64) NULL,
    new_status VARCHAR(64) NULL,
    sync_source ENUM('webhook','api_pull','manual_resync','link_activation','admin_correction','retention') NOT NULL,
    observed_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sanitized_metadata JSON NULL,

    PRIMARY KEY (id),
    INDEX idx_patreon_snapshot_history_membership (membership_id, observed_at),
    CONSTRAINT fk_patreon_snapshot_history_membership FOREIGN KEY (membership_id)
        REFERENCES patreon_memberships(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_patreon_snapshot_history_snapshot FOREIGN KEY (snapshot_id)
        REFERENCES patreon_member_snapshots(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== CURRENT ENTITLEMENT ===================
CREATE TABLE IF NOT EXISTS patreon_entitlements_current (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    external_account_id VARCHAR(64) NULL,
    membership_id VARCHAR(64) NULL,
    external_source ENUM('patreon') NOT NULL DEFAULT 'patreon',
    entitlement_status ENUM('active','free','pending','former','revoked','stale') NOT NULL DEFAULT 'pending',
    link_status ENUM('none','pending','linked','unlinked','revoked','stale') NOT NULL DEFAULT 'pending',
    plan_code VARCHAR(64) NOT NULL DEFAULT 'free',
    tier_code VARCHAR(64) NULL,
    tier_name VARCHAR(120) NULL,
    subscription_status VARCHAR(64) NULL,
    next_renewal_at DATETIME NULL,
    grace_period_until DATETIME NULL,
    last_synced_at DATETIME NULL,
    stale_after DATETIME NULL,
    sync_source ENUM('webhook','api_pull','manual_resync','link_activation','admin_correction','retention') NOT NULL,
    classification_version INT NOT NULL DEFAULT 1,
    safe_metadata JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_patreon_current_user (user_id),
    INDEX idx_patreon_current_status (entitlement_status, link_status, stale_after),
    INDEX idx_patreon_current_external (external_account_id),
    CONSTRAINT fk_patreon_current_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_patreon_current_external FOREIGN KEY (external_account_id)
        REFERENCES user_external_accounts(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_patreon_current_membership FOREIGN KEY (membership_id)
        REFERENCES patreon_memberships(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== ENTITLEMENT HISTORY ===================
CREATE TABLE IF NOT EXISTS patreon_entitlement_history (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    external_account_id VARCHAR(64) NULL,
    membership_id VARCHAR(64) NULL,
    previous_status VARCHAR(64) NULL,
    new_status VARCHAR(64) NOT NULL,
    previous_plan_code VARCHAR(64) NULL,
    new_plan_code VARCHAR(64) NOT NULL,
    previous_tier_code VARCHAR(64) NULL,
    new_tier_code VARCHAR(64) NULL,
    link_status VARCHAR(64) NULL,
    reason VARCHAR(128) NOT NULL,
    sync_source ENUM('webhook','api_pull','manual_resync','link_activation','unlink','relink','admin_correction','retention') NOT NULL,
    observed_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    sanitized_metadata JSON NULL,

    PRIMARY KEY (id),
    INDEX idx_patreon_history_user_time (user_id, observed_at),
    INDEX idx_patreon_history_membership (membership_id, observed_at),
    CONSTRAINT fk_patreon_history_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_patreon_history_external FOREIGN KEY (external_account_id)
        REFERENCES user_external_accounts(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_patreon_history_membership FOREIGN KEY (membership_id)
        REFERENCES patreon_memberships(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== WEBHOOK DELIVERY LEDGER ===================
-- Patreon has no native delivery ID; delivery_hash is app-computed from event type,
-- member identity reference, and raw-body digest. Raw payload bytes are never stored.
CREATE TABLE IF NOT EXISTS patreon_webhook_deliveries (
    id VARCHAR(64) NOT NULL,
    delivery_hash BINARY(32) NOT NULL,
    event_type VARCHAR(80) NOT NULL,
    member_id_hash BINARY(32) NULL,
    campaign_id_hash BINARY(32) NULL,
    raw_body_sha256 BINARY(32) NOT NULL,
    signature_valid BOOLEAN NOT NULL DEFAULT FALSE,
    status ENUM('received','processing','processed','rejected','replay','failed','ignored') NOT NULL DEFAULT 'received',
    received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    processed_at DATETIME NULL,
    expires_at DATETIME NOT NULL,
    retry_after_at DATETIME NULL,
    sanitized_metadata JSON NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_patreon_webhook_delivery_hash (delivery_hash),
    INDEX idx_patreon_webhook_status (status, received_at),
    INDEX idx_patreon_webhook_member (member_id_hash, received_at),
    INDEX idx_patreon_webhook_expiry (expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== SYNC JOBS ===================
CREATE TABLE IF NOT EXISTS patreon_sync_jobs (
    id VARCHAR(64) NOT NULL,
    job_type ENUM('full_campaign','campaign_member','user_member','retention','token_refresh','webhook_resync') NOT NULL,
    campaign_id VARCHAR(64) NULL,
    member_id_hash BINARY(32) NULL,
    user_id VARCHAR(64) NULL,
    dedupe_key_hash BINARY(32) NOT NULL,
    status ENUM('pending','running','retry','completed','failed','cancelled') NOT NULL DEFAULT 'pending',
    priority TINYINT NOT NULL DEFAULT 5,
    not_before DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    attempts INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 8,
    claimed_by VARCHAR(128) NULL,
    claimed_at DATETIME NULL,
    lease_until DATETIME NULL,
    completed_at DATETIME NULL,
    source ENUM('webhook','scheduled','manual','link_activation','retention','health') NOT NULL,
    last_error_redacted TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    sanitized_metadata JSON NULL,

    active_dedupe_key_hash BINARY(32)
        GENERATED ALWAYS AS (
            CASE WHEN status IN ('pending','running','retry') THEN dedupe_key_hash ELSE NULL END
        ) VIRTUAL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_patreon_sync_active_dedupe (active_dedupe_key_hash),
    INDEX idx_patreon_sync_claim (status, not_before, priority, created_at),
    INDEX idx_patreon_sync_user (user_id, status, created_at),
    INDEX idx_patreon_sync_campaign (campaign_id, status, created_at),
    CONSTRAINT fk_patreon_sync_campaign FOREIGN KEY (campaign_id)
        REFERENCES patreon_campaigns(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_patreon_sync_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== RAW PAYLOAD QUARANTINE ===================
-- Disabled-by-default server-only incident diagnostics. Stores encrypted ciphertext
-- only; triggers enforce purge_at <= received_at + 30 days.
CREATE TABLE IF NOT EXISTS patreon_raw_payload_quarantine (
    id VARCHAR(64) NOT NULL,
    payload_hash BINARY(32) NOT NULL,
    source ENUM('webhook','api_pull','manual') NOT NULL,
    payload_ciphertext LONGBLOB NOT NULL,
    encryption_key_id VARCHAR(128) NOT NULL,
    capture_reason VARCHAR(128) NOT NULL,
    received_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    purge_at DATETIME NOT NULL,
    purged_at DATETIME NULL,
    created_by VARCHAR(64) NULL,
    sanitized_metadata JSON NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_patreon_quarantine_payload_hash (payload_hash),
    INDEX idx_patreon_quarantine_purge (purge_at, purged_at),
    CONSTRAINT fk_patreon_quarantine_created_by FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== OPTIONAL ENCRYPTED PROVIDER TOKEN STATE ===================
-- Global creator-token state only. Never per-user, never raw token columns, and only
-- used when automatic creator-token refresh is explicitly enabled server-side.
CREATE TABLE IF NOT EXISTS patreon_provider_token_state (
    id VARCHAR(64) NOT NULL,
    provider ENUM('patreon') NOT NULL DEFAULT 'patreon',
    token_kind ENUM('creator') NOT NULL DEFAULT 'creator',
    access_token_ciphertext LONGBLOB NULL,
    refresh_token_ciphertext LONGBLOB NULL,
    token_fingerprint CHAR(12) NULL,
    encryption_key_id VARCHAR(128) NOT NULL,
    expires_at DATETIME NULL,
    refreshed_at DATETIME NULL,
    rotated_at DATETIME NULL,
    status ENUM('disabled','active','refresh_failed','revoked','expired') NOT NULL DEFAULT 'disabled',
    last_error_redacted TEXT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_patreon_provider_token_kind (provider, token_kind),
    INDEX idx_patreon_provider_token_status (status, expires_at)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- ===================================================================================
-- PATREON TABLES COMPLETE
-- ===================================================================================
SELECT 'Patreon entitlement tables created successfully!' AS status,
       '12 tables created: proof, campaigns, tier map, memberships, snapshots/history, current/history, webhooks, sync jobs, quarantine, token state' AS details;
