-- Additive migration: select the auth database before sourcing this file.
-- Install before deploying the bounded-password-work API. Existing links and the
-- atomic consumer remain unchanged. Use a migration administrator with routine
-- privileges (and SYSTEM_USER when replacing a system-user-defined routine).
SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;
DELIMITER $$

-- Read-only admission proof. No state changes or locks are retained during Argon2.
-- Keep the v2 binding identical to the issuance and atomic consumption expressions.
DROP PROCEDURE IF EXISTS sp_validate_password_reset_token$$
CREATE PROCEDURE sp_validate_password_reset_token(
    IN p_lookup_id VARCHAR(32),
    IN p_token_hash BINARY(32),
    IN p_admin_token_hash BINARY(32)
)
BEGIN
    DECLARE v_purpose VARCHAR(32) DEFAULT NULL;
    SELECT t.purpose INTO v_purpose
    FROM user_email_link_tokens t
    JOIN users u ON u.id = t.user_id
    WHERE t.lookup_id = p_lookup_id
      AND t.purpose IN ('password_reset', 'admin_password_reset')
      AND t.consumed_at IS NULL
      AND t.revoked_at IS NULL
      AND t.expires_at > NOW()
      AND u.is_active = TRUE
      AND t.token_hash = UNHEX(SHA2(CONCAT(
          'password-reset:v2:',
          HEX(IF(t.purpose = 'password_reset', p_token_hash, p_admin_token_hash)), ':',
          SHA2(CONCAT(HEX(u.id), ':', HEX(u.password_hash)), 256)
      ), 256))
    LIMIT 1;
    SELECT v_purpose IS NOT NULL AS token_valid, v_purpose AS purpose;
END$$

DELIMITER ;
