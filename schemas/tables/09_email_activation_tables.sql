-- ===================================================================================
-- Email Activation and Transactional Auth Email Tables
-- ===================================================================================
-- Canonical stores for user email identity, hash-only link tokens, durable email
-- outbox messages, delivery attempts, suppressions, idempotency, and transactional
-- auth templates.
--
-- Source of truth: user_emails. users.email remains a deprecated compatibility shadow.
-- Token posture: split-token lookup_id.secret in URLs; only BINARY(32) HMAC hashes are
-- persisted in user_email_link_tokens.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- =================== USER_EMAILS TABLE ===================
-- Authoritative account email identity and lifecycle state.
CREATE TABLE IF NOT EXISTS user_emails (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    email_normalized VARCHAR(255) NOT NULL,
    email_hash BINARY(32) NOT NULL,
    email_masked VARCHAR(255) NOT NULL,
    status ENUM('pending','activated','removed','suppressed') NOT NULL DEFAULT 'pending',
    is_primary BOOLEAN NOT NULL DEFAULT FALSE,
    added_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    activated_at DATETIME NULL,
    removed_at DATETIME NULL,
    last_activation_sent_at DATETIME NULL,
    created_by VARCHAR(64) NULL,
    updated_at DATETIME NULL,

    -- MySQL unique indexes permit multiple NULLs. These generated columns enforce:
    -- - global uniqueness only for active activated normalized email identities;
    -- - at most one active primary email per user.
    -- They MUST be VIRTUAL (not STORED): user_id carries an ON DELETE/UPDATE CASCADE
    -- foreign key, and MySQL forbids cascade/SET NULL referential actions on a base
    -- column of a STORED generated column (errno 1215). InnoDB still supports the
    -- UNIQUE indexes below on virtual columns, so the invariants are preserved.
    active_activated_email VARCHAR(255)
        GENERATED ALWAYS AS (
            CASE
                WHEN status = 'activated' AND removed_at IS NULL THEN email_normalized
                ELSE NULL
            END
        ) VIRTUAL,
    primary_user_id VARCHAR(64)
        GENERATED ALWAYS AS (
            CASE
                WHEN status = 'activated' AND removed_at IS NULL AND is_primary = TRUE THEN user_id
                ELSE NULL
            END
        ) VIRTUAL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_user_emails_active_activated_email (active_activated_email),
    UNIQUE KEY uk_user_emails_one_primary (primary_user_id),
    INDEX idx_user_emails_user_status (user_id, status, removed_at),
    INDEX idx_user_emails_hash (email_hash),
    INDEX idx_user_emails_normalized (email_normalized),
    CONSTRAINT fk_user_emails_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_user_emails_created_by FOREIGN KEY (created_by)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== USER_EMAIL_LINK_TOKENS TABLE ===================
-- Hash-only split tokens for email activation and password reset links.
CREATE TABLE IF NOT EXISTS user_email_link_tokens (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    user_email_id VARCHAR(64) NULL,
    purpose ENUM('email_activation','password_reset','admin_password_reset') NOT NULL,
    lookup_id VARCHAR(32) NOT NULL,
    token_hash BINARY(32) NOT NULL,
    token_fingerprint CHAR(12) NOT NULL,
    expires_at DATETIME NOT NULL,
    consumed_at DATETIME NULL,
    consumed_ip_hash BINARY(32) NULL,
    consumed_user_agent_hash BINARY(32) NULL,
    revoked_at DATETIME NULL,
    revocation_reason VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    created_ip_hash BINARY(32) NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_email_link_tokens_lookup (lookup_id),
    INDEX idx_email_link_tokens_user_purpose (user_id, purpose, expires_at),
    INDEX idx_email_link_tokens_email_purpose (user_email_id, purpose, expires_at),
    INDEX idx_email_link_tokens_hash (token_hash),
    CONSTRAINT fk_email_link_tokens_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_email_link_tokens_email FOREIGN KEY (user_email_id)
        REFERENCES user_emails(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== EMAIL_MESSAGES TABLE ===================
-- Durable transactional-auth email outbox. Redis may wake workers, but this table is
-- the canonical delivery ledger.
CREATE TABLE IF NOT EXISTS email_messages (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NULL,
    user_email_id VARCHAR(64) NULL,
    token_id VARCHAR(64) NULL,
    purpose ENUM('email_activation','password_reset','admin_password_reset','security_notification','delivery_operation','patreon_link_proof') NOT NULL,
    template_code VARCHAR(100) NOT NULL,
    recipient_email VARCHAR(255) NULL,
    recipient_hash BINARY(32) NOT NULL,
    recipient_masked VARCHAR(255) NOT NULL,
    provider VARCHAR(50) NOT NULL DEFAULT 'resend',
    provider_message_id VARCHAR(255) NULL,
    provider_idempotency_key VARCHAR(128) NOT NULL,
    status ENUM('pending','processing','sent','delivered','bounced','complained','suppressed','retry','dead','cancelled') NOT NULL DEFAULT 'pending',
    priority TINYINT NOT NULL DEFAULT 5,
    attempt_count INT NOT NULL DEFAULT 0,
    max_attempts INT NOT NULL DEFAULT 8,
    next_attempt_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    claimed_by VARCHAR(128) NULL,
    claimed_at DATETIME NULL,
    lease_until DATETIME NULL,
    sent_at DATETIME NULL,
    terminal_at DATETIME NULL,
    last_error_code VARCHAR(100) NULL,
    last_error_message TEXT NULL,
    render_payload_ciphertext LONGBLOB NULL,
    payload_purge_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_email_messages_provider_idem (provider, provider_idempotency_key),
    INDEX idx_email_messages_claim (status, next_attempt_at, priority, created_at),
    INDEX idx_email_messages_recipient_hash (recipient_hash, created_at),
    INDEX idx_email_messages_provider_message (provider, provider_message_id),
    INDEX idx_email_messages_user (user_id, created_at),
    CONSTRAINT fk_email_messages_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_email_messages_user_email FOREIGN KEY (user_email_id)
        REFERENCES user_emails(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_email_messages_token FOREIGN KEY (token_id)
        REFERENCES user_email_link_tokens(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== EMAIL_DELIVERY_ATTEMPTS TABLE ===================
-- Append-only sanitized worker/provider attempt and webhook-event ledger.
CREATE TABLE IF NOT EXISTS email_delivery_attempts (
    id VARCHAR(64) NOT NULL,
    email_message_id VARCHAR(64) NOT NULL,
    attempt_no INT NOT NULL,
    provider VARCHAR(50) NOT NULL,
    status ENUM('sent','temporary_failure','permanent_failure','suppressed','cancelled','webhook_event') NOT NULL,
    provider_message_id VARCHAR(255) NULL,
    provider_event_id VARCHAR(255) NULL,
    error_code VARCHAR(100) NULL,
    error_message TEXT NULL,
    response_metadata JSON NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_email_attempt_no (email_message_id, attempt_no),
    INDEX idx_email_attempt_provider_event (provider, provider_event_id),
    INDEX idx_email_attempt_message_time (email_message_id, created_at),
    CONSTRAINT fk_email_attempt_message FOREIGN KEY (email_message_id)
        REFERENCES email_messages(id) ON DELETE CASCADE ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== EMAIL_SUPPRESSIONS TABLE ===================
-- Hashed suppression ledger for bounces, complaints, and operational blocks. No
-- plaintext recipient email is stored here.
CREATE TABLE IF NOT EXISTS email_suppressions (
    id VARCHAR(64) NOT NULL,
    email_hash BINARY(32) NOT NULL,
    reason ENUM('hard_bounce','complaint','manual','provider','role_address_block') NOT NULL,
    source VARCHAR(50) NOT NULL,
    provider VARCHAR(50) NULL,
    provider_event_id VARCHAR(255) NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    lifted_at DATETIME NULL,
    metadata JSON NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_email_suppression_active (email_hash, reason, is_active),
    INDEX idx_email_suppressions_hash_active (email_hash, is_active),
    INDEX idx_email_suppressions_provider_event (provider, provider_event_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== EMAIL_IDEMPOTENCY_KEYS TABLE ===================
-- Durable local replay authority for public/authenticated email send and consume flows.
CREATE TABLE IF NOT EXISTS email_idempotency_keys (
    id VARCHAR(64) NOT NULL,
    scope VARCHAR(128) NOT NULL,
    key_hash BINARY(32) NOT NULL,
    request_hash BINARY(32) NOT NULL,
    user_id VARCHAR(64) NULL,
    recipient_hash BINARY(32) NULL,
    email_message_id VARCHAR(64) NULL,
    status ENUM('in_progress','complete','conflict','expired') NOT NULL DEFAULT 'in_progress',
    replay_status_code INT NOT NULL DEFAULT 202,
    replay_body JSON NOT NULL,
    expires_at DATETIME NOT NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    completed_at DATETIME NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_email_idempotency_scope_key (scope, key_hash),
    INDEX idx_email_idempotency_expiry (expires_at),
    INDEX idx_email_idempotency_user (user_id, created_at),
    INDEX idx_email_idempotency_recipient (recipient_hash, created_at),
    CONSTRAINT fk_email_idem_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_email_idem_message FOREIGN KEY (email_message_id)
        REFERENCES email_messages(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== EMAIL_TEMPLATE_CATALOG TABLE ===================
-- One row per known template code. Dynamic codes are limited by app validation to
-- internal delivery purposes; built-in codes are seeded here and may fall back to
-- in-code defaults when no DB-managed version exists.
CREATE TABLE IF NOT EXISTS email_template_catalog (
    template_code VARCHAR(100) NOT NULL,
    purpose ENUM('email_activation','password_reset','admin_password_reset','security_notification','delivery_operation','patreon_link_proof') NOT NULL,
    allowed_variables JSON NOT NULL,
    required_variables JSON NOT NULL,
    is_builtin BOOLEAN NOT NULL DEFAULT FALSE,
    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    revision INT NOT NULL DEFAULT 1,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    disabled_at DATETIME NULL,
    disabled_by VARCHAR(64) NULL,

    PRIMARY KEY (template_code),
    INDEX idx_email_template_catalog_enabled (is_enabled, purpose),
    INDEX idx_email_template_catalog_builtin (is_builtin)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- =================== EMAIL_TEMPLATES TABLE ===================
-- Versioned subject/body rows. The catalog owns template availability, dynamic
-- metadata, and revision; this table preserves editable version history.
CREATE TABLE IF NOT EXISTS email_templates (
    id VARCHAR(64) NOT NULL,
    template_code VARCHAR(100) NOT NULL,
    version INT NOT NULL,
    subject_template VARCHAR(255) NOT NULL,
    html_template TEXT NOT NULL,
    text_template TEXT NOT NULL,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,

    PRIMARY KEY (id),
    UNIQUE KEY uk_email_template_version (template_code, version),
    INDEX idx_email_template_active (template_code, is_active)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

INSERT INTO email_template_catalog (
    template_code, purpose, allowed_variables, required_variables,
    is_builtin, is_enabled, revision, created_at, updated_at
) VALUES
    ('email_activation', 'email_activation',
     JSON_ARRAY('activation_link','app_name','expires_in','recipient_masked','support_email'),
     JSON_ARRAY('activation_link'), TRUE, TRUE, 1, NOW(), NOW()),
    ('password_reset', 'password_reset',
     JSON_ARRAY('app_name','expires_in','recipient_masked','reset_link','support_email'),
     JSON_ARRAY('reset_link'), TRUE, TRUE, 1, NOW(), NOW()),
    ('admin_password_reset', 'admin_password_reset',
     JSON_ARRAY('app_name','expires_in','recipient_masked','reset_link','support_email'),
     JSON_ARRAY('reset_link'), TRUE, TRUE, 1, NOW(), NOW()),
    ('security_notification', 'security_notification',
     JSON_ARRAY('app_name','event_title','message','support_email'),
     JSON_ARRAY('message'), TRUE, TRUE, 1, NOW(), NOW()),
    ('delivery_operation', 'delivery_operation',
     JSON_ARRAY('app_name','status_summary','support_email'),
     JSON_ARRAY('status_summary'), TRUE, TRUE, 1, NOW(), NOW()),
    ('patreon_link_proof', 'patreon_link_proof',
     JSON_ARRAY('app_name','expires_at','expires_in','lookup_id','patreon_link_proof_url','proof_token','recipient_masked','support_email'),
     JSON_ARRAY('patreon_link_proof_url','proof_token'), TRUE, TRUE, 1, NOW(), NOW()),
    ('email_credit_grant_notification', 'delivery_operation',
     JSON_ARRAY('action_url','app_name','credits','expires_at','expires_in','recipient_masked','support_email'),
     JSON_ARRAY('credits','action_url','expires_at'), TRUE, TRUE, 1, NOW(), NOW())
ON DUPLICATE KEY UPDATE
    purpose = VALUES(purpose),
    allowed_variables = VALUES(allowed_variables),
    required_variables = VALUES(required_variables),
    is_builtin = TRUE,
    updated_at = NOW();

-- Patreon proof template metadata. Render payloads and proof tokens remain in the
-- durable outbox/proof tables; local email activation semantics are untouched.
INSERT INTO email_templates (
    id, template_code, version, subject_template, html_template, text_template,
    is_active, created_at
) VALUES (
    'tmpl-patreon-link-proof-v1',
    'patreon_link_proof',
    1,
    'Confirm your Patreon link',
    '<p>Use this one-time proof link to confirm your Patreon membership link for $recipient_masked:</p><p><a href="$patreon_link_proof_url">Confirm Patreon link</a></p><p>Proof code: $proof_token</p><p>This proof expires at $expires_at. If you did not request this, ignore this email.</p>',
    'Use this one-time proof link to confirm your Patreon membership link for $recipient_masked: $patreon_link_proof_url Proof code: $proof_token This proof expires at $expires_at. If you did not request this, ignore this email.',
    TRUE,
    NOW()
) ON DUPLICATE KEY UPDATE
    subject_template = VALUES(subject_template),
    html_template = VALUES(html_template),
    text_template = VALUES(text_template),
    is_active = VALUES(is_active);

INSERT INTO email_templates (
    id, template_code, version, subject_template, html_template, text_template,
    is_active, created_at
) VALUES (
    'tmpl-email-credit-grant-notification-v1',
    'email_credit_grant_notification',
    1,
    'You have $credits Magic Worlds credits',
    '<p>A Magic Worlds administrator sent $credits credits to $recipient_masked.</p><p>If this email is already linked to your account, the credits have been added. Otherwise, open Magic Worlds and create or activate an account with this email to receive them.</p><p><a href="$action_url">Open Magic Worlds</a></p><p>Expiration: $expires_at</p>',
    'A Magic Worlds administrator sent $credits credits to $recipient_masked. If this email is already linked to your account, the credits have been added. Otherwise, open Magic Worlds and create or activate an account with this email to receive them: $action_url Expiration: $expires_at',
    TRUE,
    NOW()
) ON DUPLICATE KEY UPDATE
    subject_template = VALUES(subject_template),
    html_template = VALUES(html_template),
    text_template = VALUES(text_template),
    is_active = VALUES(is_active);

-- ===================================================================================
-- EMAIL ACTIVATION TABLES COMPLETE
-- ===================================================================================
SELECT 'Email activation tables created successfully!' AS status,
       '8 tables created: user_emails, user_email_link_tokens, email_messages, email_delivery_attempts, email_suppressions, email_idempotency_keys, email_template_catalog, email_templates; catalog-backed latest-template delivery supported' AS details;
