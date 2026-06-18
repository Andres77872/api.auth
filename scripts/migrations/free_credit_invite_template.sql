-- ===================================================================================
-- Additive Migration: Magic Worlds Free-Credit Invite Email Template
-- ===================================================================================
-- Installs only the DB-managed template metadata used by the generic internal
-- email sender. Free-credit invite rows, grant state, and idempotency remain in
-- magic-worlds-api; api.auth stores no free-credit domain records.
-- ===================================================================================

USE magic_auth;

SET NAMES utf8mb4 COLLATE utf8mb4_unicode_ci;

INSERT INTO email_templates (
    id, template_code, version, subject_template, html_template, text_template,
    is_active, created_at
) VALUES (
    'tmpl-free-credit-invite-v1',
    'free_credit_invite',
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

SELECT id, template_code, version, is_active
FROM email_templates
WHERE template_code = 'free_credit_invite';
