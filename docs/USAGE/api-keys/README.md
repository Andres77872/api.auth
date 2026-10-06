# API keys

API keys are long-lived credentials that belong to one user and are scoped to one project. Users
manage their own keys; root and admin users manage keys for other users within their scope. A
service that receives a key checks it with `POST /auth/validate-api-key`, which returns the owner,
project, groups and permissions.

## Key concepts

- **Token format**: `sk_{public_id}.{secret}`. `public_id` is 12 base64url characters (9 random
  bytes); `secret` is 43 base64url characters (32 random bytes).
- **What the server stores**: `public_id` in clear, plus
  `HMAC-SHA-256(API_KEY_PEPPER, "v1:{public_id}:{secret}")`. The secret itself is never stored, so
  the full token is shown once, in the create response, and cannot be retrieved later.
- **Key identifier**: `{key_id}` in every path is the `public_id`. The key object's `id` field has
  the same value. Passing the full token as `{key_id}` returns `404`.
- **Identification without the secret**: `fingerprint` (12 hex characters) and `secret_last4` let a
  person recognise a key in a UI or log.
- **State**: a key is usable while `is_active` is true, it is not past `expires_at`, the owner is
  active and the owner still reaches the project. Revocation is permanent.
- **Audit trail**: database triggers write `api_key_created`, `api_key_updated`,
  `api_key_revoked` and `api_key_reactivated` rows to `activity_logs`.

Storage is the `user_project_api_keys` table and the procedures in
`schemas/stored_procedures/13_api_keys.sql`. Token generation and verification live in
`src/Util/api_key_security.py`.

## Route families

| Family | Prefix | Auth | Acts on |
| --- | --- | --- | --- |
| Self-service | `/users/api-keys` | Access token (`verify_session`), any user type | The caller's own keys. A key owned by someone else returns `404`. |
| Admin | `/api-keys` | Access token of a root or admin user (`verify_admin_access`) | Keys of any user (root) or keys in projects the admin administers |
| Validation | `/auth/validate-api-key` | `X-API-Key` header only | Resolves a raw key to its owner context. Documented in [Authentication usage cases](../authentication-usage-cases.md#validate-an-api-key). |

Full endpoint tables are in [reference.md](reference.md).

## Rules and caveats

These rules apply to the whole suite. Platform-wide rules (User-Agent, body size, error envelope)
are in [Platform-wide contracts](../README.md#platform-wide-contracts).

- **Management routes do not accept API keys.** Send an access token (`Authorization: Bearer` or
  the `access_token` cookie). `X-API-Key` is honoured only by `POST /auth/validate-api-key`.
- **Writes take form fields** (`application/x-www-form-urlencoded` or `multipart/form-data`), not
  JSON.
- **Create, update and revoke need recent authentication**: a sign-in or an OAuth reauth of the
  current session within `OAUTH_RECENT_REAUTH_SECONDS` (default `300` seconds). Refreshing the
  session does not renew it. Otherwise the call fails with `401` `AUTH_1008`. Reads do not need it.
- **Admin scope**: root is unrestricted. An admin works only in projects they administer, and
  creating a key for another user also needs the `manage_users` permission in that project. Users
  whose only admin power is an `admin` permission from a global role pass the dependency but have
  no scope, so they get `403`.
- **`expires_at` must be in the future.** It is ISO 8601; a value without a timezone is read as UTC.
  Omit it for a key that never expires. Fields cannot be cleared once set.
- **Expired keys are deactivated by a sweep.** Validation rejects a key by date as soon as
  `expires_at` passes. The API process runs `sp_cleanup_expired_api_keys` every 5 minutes, which
  sets `is_active` to false and records `api_key_expired`; until then an expired key can still
  show `is_active: true`. A future `expires_at` makes an expired key usable again (recorded as
  `api_key_reactivated`). To retire a key for good, revoke it.
- **Revocation takes effect at once.** The Redis validation cache entry (`apikey:{public_id}`,
  `60` seconds) is dropped when a key is revoked or its expiry changes.

## Handling keys safely

- Issue one key per consumer and project, and set an `expires_at`.
- Store the token in a secret manager when it is created. Log only `public_id`, `fingerprint` or
  `secret_last4`, never the token.
- Rotate by creating a new key, validating it, deploying it, then revoking the old one
  ([rotation scenario](scenarios.md#rotate-a-key-without-downtime)).
- Use the admin `revoke_reason` field so the audit trail explains the revocation.

## In this suite

| Document | Purpose |
| --- | --- |
| [usage.md](usage.md) | One task per section: create, list, inspect, update, revoke, validate |
| [scenarios.md](scenarios.md) | End-to-end workflows: issue and use, provision, audit, rotate, respond to a leak |
| [reference.md](reference.md) | Endpoint tables, fields, key object, token format, error codes |
| [troubleshooting.md](troubleshooting.md) | Symptom, cause and fix for common failures |

## Related

- [Authentication usage cases](../authentication-usage-cases.md#validate-an-api-key) — `POST /auth/validate-api-key`
- [Users](../users/README.md) — user hashes and admin scope
- [Projects](../projects/README.md) — project hashes and project reach
- [Permissions](../permissions/README.md) — `manage_users` and effective permissions
- [Audit logs](../audit_logs/README.md) — where the `api_key_*` activity rows appear
- [Errors](../errors.md) — error envelope and code catalog
