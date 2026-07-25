# API Keys Endpoint and Operational Reference

Reference for the API key surface in `api.auth`. API version `2.2.0`. Every request must send a
`User-Agent` header (missing → `422`). All write endpoints take **form fields**
(`application/x-www-form-urlencoded`). In every path, `{key_id}` is the key's **`public_id`**.

Source files: `src/routes/user_api_keys.py`, `src/routes/api_keys.py`, `src/Util/api_key_security.py`.

---

## Self-Service Endpoints (`/users/api-keys`)

Auth dependency: `verify_session` (any authenticated user). Authorization is **ownership-only** —
a non-owned key returns `404 API_KEY_NOT_FOUND`.

| Endpoint | Method | Step-up | Content Type | Params | Purpose |
|----------|--------|---------|--------------|--------|---------|
| `/users/api-keys` | POST | **Yes** | Form | `project_hash` (req), `name?`, `description?`, `expires_at?` | Create a key for the caller's own account; returns one-time `data.api_key` |
| `/users/api-keys` | GET | No | Query | `project_hash?`, `active_only?` (def `false`), `limit?` (1–200, def `50`), `offset?` (≥0) | List the caller's own keys |
| `/users/api-keys/{key_id}` | GET | No | - | path `key_id` (public_id) | Get one of the caller's own keys |
| `/users/api-keys/{key_id}` | PUT | **Yes** | Form | `name?`, `description?`, `expires_at?` (≥1 required) | Update own key; extending `expires_at` reactivates an expired key |
| `/users/api-keys/{key_id}` | DELETE | **Yes** | - | path `key_id` (public_id) | Revoke own key; immediate Redis cache invalidation (no `revoke_reason`) |

---

## Admin Endpoints (`/api-keys`)

Auth dependency: `verify_admin_access` (root **or** admin). Root is unrestricted; admins are scoped
to projects they administer via `check_admin_project_access`, and need the `manage_users` effective
permission to act on **other** users' keys (self-service always allowed).

| Endpoint | Method | Step-up | Content Type | Params | Purpose |
|----------|--------|---------|--------------|--------|---------|
| `/api-keys` | POST | **Yes** | Form | `user_hash` (req), `project_hash` (req), `name?`, `description?`, `expires_at?` | Create a key on behalf of a user; returns one-time `data.api_key` |
| `/api-keys` | GET | No | Query | `user_hash?`, `project_hash?`, `active_only?`, `limit?` (1–200, def `50`), `offset?` | List keys in scope; **root must supply `user_hash` or `project_hash`** |
| `/api-keys/{key_id}` | GET | No | - | path `key_id` (public_id) | Get a key by `public_id`; admin must have project scope |
| `/api-keys/{key_id}` | PUT | **Yes** | Form | `name?`, `description?`, `expires_at?` (≥1 required) | Update a key; extending `expires_at` reactivates an expired key |
| `/api-keys/{key_id}` | DELETE | **Yes** | Form | `revoke_reason?` (optional) | Revoke a key; immediate Redis cache invalidation |
| `/api-keys/users/{user_hash}` | GET | No | Query | path `user_hash`; `active_only?`, `limit?`, `offset?` | List all keys for one user (admin must share a project) |
| `/api-keys/projects/{project_hash}` | GET | No | Query | path `project_hash`; `active_only?`, `limit?`, `offset?` | List all keys for one project (admin must administer it) |

---

## Validation Endpoint (cross-link — owned by the auth suite)

| Endpoint | Method | Auth | Content Type | Purpose |
|----------|--------|------|--------------|---------|
| `/auth/validate-api-key` | POST | `X-API-Key` header (no session/JWT) | - | Validate a raw key; returns owner identity, project, groups, permissions |

- Send the raw token in the `X-API-Key` request header — **not** `Authorization: Bearer`.
- Sending **both** `Authorization` and `X-API-Key` → `400` with detail `ambiguous_credentials`.
- Response model `ValidateApiKeyResponse`: `success`, `valid`, `auth_method` (`"api_key"`),
  `user` (`UserInfo`), `project` (`ProjectInfo`, may be `null`), `api_key`
  (`ApiKeyInfo` → `key_id`, `public_id`), `user_groups[]`, `permissions[]`. The raw key and secret
  are never echoed.
- Full documentation: **[Authentication Usage Cases](../authentication-usage-cases.md)**.

---

## Response Envelope

All owning endpoints return the standard envelope:

```json
{
  "success": true,
  "message": "API key created successfully",
  "data": { "...": "..." }
}
```

### Per-key object (`data` on single-key calls; `data.keys[]` items on lists)

Built by `_format_key_response`. Always present:

| Field | Notes |
|-------|-------|
| `id` | Numeric DB id |
| `public_id` | The ~12-char base64url id — used as `{key_id}` in paths |
| `name` | Label |
| `description` | Free text |
| `project_id` | Owning project (numeric) |
| `owner_user_id` | Key owner (numeric) |
| `is_active` | bool |
| `expires_at` | ISO 8601 or `null` |
| `last_used_at` | ISO 8601 or `null` |
| `created_at` / `updated_at` | timestamps |
| `revoked_at` / `revoke_reason` | set after revocation (`revoke_reason` admin-only) |
| `fingerprint` | 12-hex BLAKE2s fingerprint of the full token |
| `secret_last4` | last 4 chars of the secret, for confirmation |
| `hash_algorithm` | `hmac-sha256-v1` |

Admin list/detail responses additionally surface enrichment columns when the stored procedures
join them in: `project_name`, `project_hash`, `owner_username`, `owner_user_hash`,
`owner_user_type`.

**One-time token:** `api_key` (the full `sk_{public_id}.{secret}`) is present **only** in the
`POST` create response (`include_token=True`). It never appears in list / get / update / delete.
The `secret_hash` is never returned by any endpoint.

### List payload

`GET` list endpoints wrap items as:

```jsonc
{ "keys": [ ... ], "total": 12, "limit": 50, "offset": 0 }
```

`GET /api-keys/users/{user_hash}` adds `user_hash` and `username`;
`GET /api-keys/projects/{project_hash}` adds `project_hash` and `project_name`.

> **Caveat:** on `GET /users/api-keys` (and the per-key filters of the admin user-list path),
> filtering is applied in Python **after** paging, and `total` is recomputed as the filtered
> length. So `total` is a post-filter count while pagination is pre-filter. See
> [troubleshooting.md](troubleshooting.md).

---

## Error Codes

| Code | HTTP | Cause |
|------|------|-------|
| `API_KEY_NOT_FOUND` | 404 | Key missing, or not owned (user routes return this for non-owned keys to avoid leaking existence) |
| `API_KEY_REVOKED` | — | Re-revoking an already-revoked or nonexistent key |
| `INVALID_INPUT` | 400 | Bad/past `expires_at`, no-field update, or root list without a filter |
| `PROJECT_ACCESS_DENIED` | 403 | Self-service create for a project the caller cannot access |
| `ACCESS_DENIED` | 403 | Admin acting outside their project scope / on an out-of-scope user |
| `INSUFFICIENT_PERMISSIONS` | 403 | Admin lacks `manage_users` for another user's key |

See the global **[Errors Reference](../errors.md)** for the envelope and status mapping.

---

## Key Format and Cryptography

Implemented in `src/Util/api_key_security.py`.

- **Token**: `sk_{public_id}.{secret}` — `public_id` ~12 base64url chars (9 bytes),
  `secret` ~43 base64url chars (32 bytes), joined by a single `.`.
- **Stored hash**: `HMAC-SHA-256(API_KEY_PEPPER, "v1:{public_id}:{secret}")` as `BINARY(32)`;
  label `hmac-sha256-v1`. The pepper is server-side and loaded at startup (fail-fast).
- **Fingerprint**: first 6 bytes of `BLAKE2s(full_token)` → 12 hex chars.
- **secret_last4**: last 4 chars of the secret.
- **Verification**: splits on the last `.`, validates the `sk_` prefix and `public_id`, recomputes
  the HMAC, and compares with `hmac.compare_digest` (constant-time). Malformed tokens are compared
  against a dummy hash for timing-attack resistance.

---

**Document Version**: 1.0
