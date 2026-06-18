-- ===================================================================================
-- Additive Migration: Patreon Account Link and Entitlement Foundation
-- ===================================================================================
-- Change: patreon-account-link / Phase 2
--
-- Install order for existing environments:
--   1. Widen existing provider/email outbox enums additively.
--   2. Re-run idempotent seed/table files for activity and email template metadata.
--   3. Install Patreon tables, stored procedures, and triggers.
--   4. Seed campaign/tier map with scripts/migrations/patreon_tier_map_seed.py using
--      server-only raw IDs/secrets. That script must not print raw IDs or secrets.
--
-- Runtime remains disabled-by-default after this migration. Operators must keep:
--   PATREON_LINKING_ENABLED=false
--   PATREON_WEBHOOKS_ENABLED=false
--   PATREON_SYNC_ENABLED=false
--   PATREON_S2S_ENTITLEMENT_ENABLED=false
-- until later rollout phases validate config, redaction, routes, sync, and S2S.
--
-- Non-destructive rollback policy:
--   Destructive rollback is forbidden after live Patreon links, proof rows,
--   snapshots/history, webhook deliveries, memberships, or audit/activity evidence
--   exist. Disable feature flags and preserve schema/history instead.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

-- -----------------------------------------------------------------------------------
-- 1. Existing additive enum widening. These statements preserve Google rows and local
--    email activation/reset semantics while allowing Patreon link-proof outbox rows.
-- -----------------------------------------------------------------------------------
ALTER TABLE user_external_accounts
    MODIFY provider ENUM('google','patreon') NOT NULL;

ALTER TABLE email_messages
    MODIFY purpose ENUM(
        'email_activation',
        'password_reset',
        'admin_password_reset',
        'security_notification',
        'delivery_operation',
        'patreon_link_proof'
    ) NOT NULL;

-- -----------------------------------------------------------------------------------
-- 2. Idempotent file install order.
--    Run from repository root with a MySQL client that supports SOURCE, or execute the
--    files through the existing bootstrap runner in the same order.
-- -----------------------------------------------------------------------------------
-- SOURCE schemas/tables/08_activity_logging_tables.sql;
-- SOURCE schemas/tables/09_email_activation_tables.sql;
-- SOURCE schemas/tables/10_external_accounts.sql;
-- SOURCE schemas/tables/11_patreon_entitlements.sql;
-- SOURCE schemas/stored_procedures/14_email_activation.sql;
-- SOURCE schemas/stored_procedures/15_external_accounts.sql;
-- SOURCE schemas/stored_procedures/16_patreon_entitlements.sql;
-- SOURCE schemas/triggers/05_external_accounts_triggers.sql;
-- SOURCE schemas/triggers/06_patreon_entitlements_triggers.sql;

-- -----------------------------------------------------------------------------------
-- 3. Destructive rollback preflight / refusal block.
--    This block is intentionally written as executable refusal logic. Do not turn it
--    into DROP statements unless this preflight returns zero live/history evidence in a
--    disposable environment.
-- -----------------------------------------------------------------------------------
DELIMITER $$

DROP PROCEDURE IF EXISTS sp_patreon_destructive_rollback_preflight$$
CREATE PROCEDURE sp_patreon_destructive_rollback_preflight()
BEGIN
    DECLARE v_live_rows BIGINT DEFAULT 0;

    SELECT
        (
            (SELECT COUNT(*) FROM user_external_accounts WHERE provider = 'patreon') +
            (SELECT COUNT(*) FROM patreon_link_proofs) +
            (SELECT COUNT(*) FROM patreon_memberships) +
            (SELECT COUNT(*) FROM patreon_member_snapshots) +
            (SELECT COUNT(*) FROM patreon_member_snapshot_history) +
            (SELECT COUNT(*) FROM patreon_entitlements_current) +
            (SELECT COUNT(*) FROM patreon_entitlement_history) +
            (SELECT COUNT(*) FROM patreon_webhook_deliveries) +
            (SELECT COUNT(*) FROM patreon_sync_jobs) +
            (SELECT COUNT(*) FROM patreon_raw_payload_quarantine) +
            (SELECT COUNT(*) FROM activity_logs WHERE activity_type LIKE 'patreon_%')
        )
    INTO v_live_rows;

    IF v_live_rows > 0 THEN
        SIGNAL SQLSTATE '45000'
            SET MESSAGE_TEXT = 'Refuse destructive Patreon rollback: live/history Patreon rows exist. Use non-destructive disable/archive rollback.';
    END IF;

    SELECT 'destructive_rollback_preflight_passed_only_for_empty_dev_schema' AS rollback_status;
END$$

DELIMITER ;

-- Non-destructive rollback checklist when preflight refuses:
--   1. Set PATREON_LINKING_ENABLED=false, PATREON_WEBHOOKS_ENABLED=false,
--      PATREON_SYNC_ENABLED=false, PATREON_S2S_ENTITLEMENT_ENABLED=false.
--   2. Stop Patreon sync workers and block /webhooks/patreon at ingress or rotate the
--      webhook secret.
--   3. Leave user_external_accounts(provider='patreon'), patreon_link_proofs,
--      patreon_memberships, patreon_entitlements_current, patreon_entitlement_history,
--      patreon_webhook_deliveries, and snapshot/unlink history intact for audit.
--   4. Clear only Patreon Redis namespaces. Never clear local auth sessions as a
--      Patreon rollback side effect.
-- ===================================================================================
