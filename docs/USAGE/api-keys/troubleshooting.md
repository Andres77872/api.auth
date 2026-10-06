# API keys troubleshooting

Symptom, cause and fix. Error codes are listed in [reference.md](reference.md#error-codes).

## Management routes

### `401` `AUTH_1008` on create, update or revoke

**Cause:** the session has no recent authentication. The window is `OAUTH_RECENT_REAUTH_SECONDS`
(default `300` seconds) from the last sign-in or OAuth reauth; a token refresh does not count.

**Fix:** sign in again (or complete an OAuth reauth for the session) and retry. Reads do not need
recent authentication.

### `401` when a management route gets only `X-API-Key`

**Cause:** `/users/api-keys` and `/api-keys` accept only an access token (`Authorization: Bearer`
or the `access_token` cookie). An API key cannot manage keys.

**Fix:** call these routes with a user session.

### `404` `NF_4010` for a key you can see elsewhere

**Cause:** one of:

- `{key_id}` is not the `public_id` (for example, the full `sk_...` token was used).
- On `/users/api-keys/{key_id}`, the key belongs to another user. Self-service routes answer `404`
  for keys you do not own.

**Fix:** use `public_id` from a list response. Admins can reach other users' keys through
`/api-keys/{key_id}`.

### `403` `AUTHZ_2003` when creating your own key

**Cause:** your account does not reach the project through its user groups.

**Fix:** ask an admin to add you to a group linked to the project, or use a project you reach.

### `403` on admin routes

| Code | Cause | Fix |
| --- | --- | --- |
| `AUTHZ_2001` | The project, or every project the target user reaches, is outside your administered projects | Use a project you administer, or ask root |
| `AUTHZ_2002` on create | You are creating a key for another user without `manage_users` in that project | Get `manage_users`, or have the user create the key |
| `AUTHZ_2002` on `GET /api-keys` or `GET /api-keys/users/{user_hash}` | You are not a root or admin user; an `admin` permission from a global role is not enough | Use a root or admin account |

### `409` `CONF_5005` on admin create

**Cause:** `sp_create_api_key` refused the key. The message says which check failed: the owner is
not active, the project is not active or is archived, or (non-root creator) the owner does not
have access to the project.

**Fix:** reactivate the owner, restore the project, or grant the owner project access first.

### `400` `VAL_3001`

| Message | Fix |
| --- | --- |
| `Invalid expires_at format: ...` | Send ISO 8601, for example `2027-01-01T00:00:00Z` |
| `expires_at must be in the future` | Send a future time; a value without a timezone is read as UTC |
| `At least one field must be provided to update` | Send `name`, `description` or `expires_at` with a non-empty value |
| `Root users must provide at least user_hash or project_hash filter` | Add a filter to `GET /api-keys` |

### `400` `AUTH_1012` on update or revoke

**Cause:** on update, the key has been revoked; revoked keys cannot change. On revoke, the key is
already inactive (revoked, or deactivated by the expiry sweep).

**Fix:** nothing to undo. Create a new key if one is needed.

### `404` when updating a key that never expires

**Cause:** the database still has an old `sp_update_api_key` that refuses keys with a `NULL`
`expires_at`.

**Fix:** install the current procedures with
`python scripts/schema_sync.py --env-file .env --apply`.

## Listing

### A filtered page has fewer keys than `limit`, and `total` is small

**Cause:** on `GET /users/api-keys`, `project_hash` and `active_only` filter the page after
`limit`/`offset` are applied, and `total` counts only that filtered page.

**Fix:** page through the unfiltered list and filter on the client. Admins can use
`GET /api-keys/projects/{project_hash}`, which filters in the database.

### `active_only=true` still returns revoked or expired keys

**Cause:** `active_only` is ignored by `GET /api-keys/users/{user_hash}` and by `GET /api-keys`
with `user_hash`. On other routes, a key that expired less than 5 minutes ago keeps
`is_active: true` until the next expiry sweep. If expired keys stay active longer, the API
process is not running the sweep (look for `API key expiry sweep failed` in its logs).

**Fix:** check `revoked_at` and compare `expires_at` with the current time on the client.

### An admin list without filters looks incomplete

**Cause:** with no filter, each administered project is read with the same `limit` and `offset`,
then the results are joined and cut to `limit`. `offset` therefore applies per project.

**Fix:** list per project with `GET /api-keys/projects/{project_hash}`.

## Validation

### `400` `ambiguous_credentials`

**Cause:** the request to `POST /auth/validate-api-key` carries both `Authorization` and
`X-API-Key`.

**Fix:** send only `X-API-Key`.

### `401` with `API key has expired: AUTH_1011`

**Cause:** `expires_at` is in the past.

**Fix:** extend it with `PUT` (the key becomes usable again) or issue a new key.

### `401` with `API key owner is inactive: AUTH_1010` or `403` with `AUTHZ_2008`

**Cause:** the owner was deactivated, or no longer reaches the key's project through the group
chain. An admin owner must also still administer the project.

**Fix:** restore the owner's access, or issue a key to an owner who has it.

### A revoked key or removed owner is still accepted for a short time

**Cause:** revocation and expiry changes through the API drop the cache entry at once. Other
changes do not: a key made inactive directly in the database, or an owner who is deactivated or
loses project access, keeps the cached `valid` result for up to `60` seconds. The cache never
skips the secret check: a token with the right `public_id` and a wrong secret gets
`Invalid API key: AUTH_1010` even while the entry is cached.

**Fix:** revoke through `DELETE /users/api-keys/{key_id}` or `DELETE /api-keys/{key_id}`, or
delete the `apikey:{public_id}` Redis key.

### A lost token

**Cause:** only the HMAC of the secret is stored, so no endpoint can show the token again.
`fingerprint` and `secret_last4` identify a key but cannot rebuild it.

**Fix:** create a new key and revoke the old one.
