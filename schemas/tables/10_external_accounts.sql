-- ===================================================================================
-- External Account Identity Tables
-- ===================================================================================
-- Durable external identity links for providers that are allowed to bind a local
-- consumer to a provider-owned subject. Google may participate in login flows at the
-- application layer; Patreon is entitlement/link authority only and MUST NOT issue
-- local sessions. The stable provider subject is stored only as an
-- application-computed HMAC plus a short non-reversible fingerprint for support.
-- Provider token material is intentionally absent from this schema.
--
-- Identity key (docs/agnostic_oauth): (identity_namespace, provider_sub_hash).
--   * provider            the provider TYPE. The ENUM is only ever widened by APPENDING a
--                         value, in step with a new adapter; existing values never move.
--   * identity_namespace  scopes the subject. A constant for providers whose subject is
--                         global ('google', 'github'), issuer/tenant/team-qualified otherwise
--                         ('microsoft:<tid>', 'oidc:<issuer>'). It is a separate column and
--                         is NEVER part of the HMAC input, so existing hashes keep resolving.
--   * connection_id       informational "first seen through"; no authority.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS user_external_accounts (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64) NOT NULL,
    provider ENUM('google','patreon','github','discord','microsoft','oidc') NOT NULL,
    identity_namespace VARCHAR(191) NOT NULL DEFAULT '',
    connection_id VARCHAR(64) NULL,
    provider_sub_hash BINARY(32) NOT NULL,
    provider_sub_fingerprint CHAR(12) NOT NULL,
    provider_email_hash BINARY(32) NULL,
    provider_email_masked VARCHAR(255) NULL,
    provider_email_verified_at_link BOOLEAN NOT NULL DEFAULT FALSE,
    status ENUM('linked','unlinked','revoked') NOT NULL DEFAULT 'linked',
    linked_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    linked_by VARCHAR(64) NULL,
    last_seen_at DATETIME NULL,
    unlinked_at DATETIME NULL,
    unlinked_by VARCHAR(64) NULL,
    unlink_reason VARCHAR(64) NULL,
    metadata JSON NULL,

    active_provider_sub_hash BINARY(32)
        GENERATED ALWAYS AS (
            CASE
                WHEN status = 'linked' THEN provider_sub_hash
                ELSE NULL
            END
        ) VIRTUAL,
    active_user_namespace VARCHAR(256)
        GENERATED ALWAYS AS (
            CASE
                WHEN status = 'linked' THEN CONCAT(user_id, ':', identity_namespace)
                ELSE NULL
            END
        ) VIRTUAL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_external_accounts_active_namespace_sub (identity_namespace, active_provider_sub_hash),
    UNIQUE KEY uk_external_accounts_user_namespace (active_user_namespace),
    INDEX idx_external_accounts_user_status (user_id, status, linked_at),
    INDEX idx_external_accounts_provider_fingerprint (provider, provider_sub_fingerprint),
    CONSTRAINT fk_external_accounts_user FOREIGN KEY (user_id)
        REFERENCES users(id) ON DELETE CASCADE ON UPDATE CASCADE,
    CONSTRAINT fk_external_accounts_linked_by FOREIGN KEY (linked_by)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE,
    CONSTRAINT fk_external_accounts_unlinked_by FOREIGN KEY (unlinked_by)
        REFERENCES users(id) ON DELETE SET NULL ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

SELECT 'External account tables created successfully!' AS status,
       '1 table created: user_external_accounts keyed by (identity_namespace, subject HMAC); no token columns' AS details;
