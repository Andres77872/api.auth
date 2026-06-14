# API Keys Troubleshooting, Caveats, and Best Practices

Common failure modes and confusions when working with the API key system in `api.auth`. Codes and
behaviors below are grounded in `src/routes/user_api_keys.py`, `src/routes/api_keys.py`,
`src/Util/api_key_security.py`, and the validation adapter in `src/routes/auth.py`.

---

## Failure Modes

### `401 Unauthorized` on a self-service call

The session is missing or invalid. `/users/api-keys/*` requires a valid session
(`verify_session`) — send a current `Authorization: Bearer <jwt>` (or the session cookie). Also
confirm a `User-Agent` header is present (missing → `422`, not `401`).

### Step-up / recent re-authentication required

`POST`, `PUT`, and `DELETE` on **both** families call `require_recent_reauthentication`. If your
last authentication is too old, the mutation is rejected until you re-authenticate. **Read (GET)
endpoints never require step-up.** Re-authenticate, then retry the write.

### `404 API_KEY_NOT_FOUND`

The key does not exist **or** (on `/users/api-keys/*`) it exists but you do not own it. The user
routes deliberately return the same `404` for non-owned keys so existence is not leaked. On admin
routes, `404` means the key was not found at all. Check that `{key_id}` is the **`public_id`**
(the ~12-char base64url segment), not the numeric DB `id` and not the full token.

### `403 PROJECT_ACCESS_DENIED` on self-service create

You tried to create a key for a `project_hash` your account cannot access. Confirm your project
reach (groups → project groups → projects) first.

### `403 ACCESS_DENIED` / `403 INSUFFICIENT_PERMISSIONS` on admin routes

- `ACCESS_DENIED` — the project (or the target user) is outside your administrative scope
  (`check_admin_project_access` / no shared project). Root bypasses these checks.
- `INSUFFICIENT_PERMISSIONS` — you tried to create or manage **another** user's key without the
  `manage_users` effective permission for that project. Self-service (a key for **yourself**) never
  needs `manage_users`.

### `400 INVALID_INPUT`

Three distinct causes:
1. **Bad or past `expires_at`** — must be valid ISO 8601 and **in the future**. A `Z` suffix is
   accepted; a naive timestamp is assumed UTC. A past date → `"expires_at must be in the future"`.
2. **No-field update** — `PUT` requires at least one of `name`, `description`, `expires_at`.
3. **Root list without a filter** — `GET /api-keys` as root with neither `user_hash` nor
   `project_hash` → `"Root users must provide at least user_hash or project_hash filter"`.

### `API_KEY_REVOKED` when revoking

You revoked a key that was already revoked (or no longer exists). Revocation is idempotent in
effect but the second call signals `API_KEY_REVOKED`. The key is already inactive — no action
needed.

### `400 ambiguous_credentials` when validating

`POST /auth/validate-api-key` rejects requests that carry **both** `Authorization` and `X-API-Key`.
Send the raw token **only** in `X-API-Key` (never `Authorization: Bearer`). This endpoint is owned
by the **[auth suite](../authentication-usage-cases.md)**.

### Lost token — cannot recover

The secret is hashed with HMAC-SHA-256 and never stored in plaintext; the full token is shown
**only** in the create response under `data.api_key`. There is no endpoint that re-reveals it.
If lost, create a new key and revoke the old one (see rotation in [scenarios.md](scenarios.md)).
`fingerprint` and `secret_last4` only help you **identify** a key, not reconstruct it.

---

## Caveats

### Paginate-then-filter: `total` can be a post-filter count

On `GET /users/api-keys`, the underlying fetch is paged **first**, then `project_hash` /
`active_only` are applied in Python and `total` is recomputed as the length of the filtered slice.
The admin user-list path behaves similarly (per-key filtering after the fetch). Consequences:

- `total` reflects the **filtered** rows, while `limit`/`offset` paged the **unfiltered** set.
- A page may contain fewer rows than `limit` after filtering even when more matches exist on later
  pages.

When you need exact counts for a single project or active-only set, prefer the scoped admin views
(`GET /api-keys/projects/{project_hash}`, `GET /api-keys/users/{user_hash}`) or narrow with
`project_hash` and iterate `offset`.

### `{key_id}` is the `public_id`

Every `{key_id}` path segment is the `public_id` resolved via `get_api_key_by_public_id`. Using the
numeric `id` or the full token will return `404`.

### Expired-key reactivation

Extending `expires_at` past `NOW()` via `PUT` on an expired key **reactivates** it. If you intend a
key to stay dead, revoke it (`DELETE`) rather than letting it expire — revocation cannot be undone
by an `expires_at` change.

### Revocation invalidates the Redis cache immediately

Both delete routes call `revoke_api_key_with_cache_invalidation`, so a revoked key stops
authenticating at once rather than waiting for a cache TTL.

### `revoke_reason` is admin-only

`DELETE /api-keys/{key_id}` accepts an optional `revoke_reason` form field;
`DELETE /users/api-keys/{key_id}` does not.

---

## Best Practices

- **Least-privilege scoping** — issue one key per project/service; never share a key across
  projects or consumers.
- **Short expiries** — set a future `expires_at` and rotate before it lapses rather than minting
  non-expiring keys.
- **Prompt revocation** — revoke on offboarding or suspected leak; the cache is invalidated
  immediately. Use the admin `revoke_reason` for an audit trail.
- **Never log raw tokens** — log only `public_id`, `fingerprint`, or `secret_last4`. The full token
  exists in clear exactly once, in the create response.
- **Validate before cutover** — when rotating, validate the new key via `X-API-Key` before revoking
  the old one.

---

## Related

- **[Usage](usage.md)** — lifecycle flows for both families
- **[Reference](reference.md)** — endpoint tables, response shape, and error codes
- **[Scenarios](scenarios.md)** — end-to-end curl workflows including rotation
- **[Authentication Usage Cases](../authentication-usage-cases.md)** — `POST /auth/validate-api-key`
- **[Errors Reference](../errors.md)** — global error envelope and status mapping

---

**Last Updated**: June 2026
**Document Version**: 1.0
