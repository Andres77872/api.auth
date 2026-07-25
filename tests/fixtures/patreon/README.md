# Patreon test fixtures

Synthetic fixture set for SDD task `patreon-account-link` 1.1.

- All provider IDs, emails, campaign names, tier names, hashes, and timestamps are fake.
- Use `example.test` emails only; do not replace these fixtures with production Patreon payloads.
- Webhook signatures use fixture secret `patreon_webhook_secret_fixture_do_not_use`.
- Webhook signatures are HMAC-MD5 over the exact raw fixture file bytes, including the final LF byte.
- The NBSP fixture intentionally contains literal UTF-8 non-breaking spaces. Do not pretty-print or normalize it before verification.

Canonical layout:

- `manifest.json` — stable fixture index for tests.
- `members/*.json` — sanitized JSON:API campaign-member payloads returned by the creator-owned Patreon API.
- `webhooks/*.raw.json` — exact raw webhook request bodies for signature/body-preservation tests.
- `webhooks/expected_signatures.json` — expected `X-Patreon-Signature` and body SHA-256 values.
- `s2s/*.json` — safe entitlement response contract examples for Magic Worlds server-to-server consumption.
