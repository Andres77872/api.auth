-- Initial accounts are created by scripts/bootstrap_root_user.py with Argon2id.
-- No credential or account is seeded by SQL.
USE magic_auth;
SELECT 'Schema initialized; root account must be provisioned by the setup script' AS status;
