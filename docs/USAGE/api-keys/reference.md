# API keys reference

The contract for the API key routes. Rules shared by the whole suite (auth, recent
authentication, form bodies, expiry) are in [README.md](README.md#rules-and-caveats).

## Self-service endpoints

Prefix `/users/api-keys`, dependency `verify_session`. Every route checks ownership; a key owned by
someone else returns `404` `NF_4010`.

| Path | Method | Recent auth | Input | Purpose |
| --- | --- | --- | --- | --- |
| `/users/api-keys` | POST | Yes | Form: [create fields](#create-fields) without `user_hash` | Create a key owned by the caller; returns the token once |
| `/users/api-keys` | GET | No | Query: [list parameters](#list-parameters) | List the caller's keys |
| `/users/api-keys/{key_id}` | GET | No | Path only | Get one of the caller's keys |
| `/users/api-keys/{key_id}` | PUT | Yes | Form: [update fields](#update-fields) | Change name, description or expiry |
| `/users/api-keys/{key_id}` | DELETE | Yes | No body | Revoke one of the caller's keys |

## Admin endpoints

Prefix `/api-keys`, dependency `verify_admin_access`. Root may act on any key. An admin must
administer the key's project (`403` `AUTHZ_2001` otherwise).

| Path | Method | Recent auth | Input | Purpose |
| --- | --- | --- | --- | --- |
| `/api-keys` | POST | Yes | Form: [create fields](#create-fields) | Create a key owned by `user_hash`; returns the token once |
| `/api-keys` | GET | No | Query: `user_hash`, `project_hash`, [list parameters](#list-parameters) | List keys by user and/or project ([filter rules](#admin-list-filters)) |
| `/api-keys/{key_id}` | GET | No | Path only | Get any key in scope, with project and owner details |
| `/api-keys/{key_id}` | PUT | Yes | Form: [update fields](#update-fields) | Change name, description or expiry. No `manage_users` check. |
| `/api-keys/{key_id}` | DELETE | Yes | Form: optional `revoke_reason` | Revoke any key in scope |
| `/api-keys/users/{user_hash}` | GET | No | Query: [list parameters](#list-parameters) | List one user's keys |
| `/api-keys/projects/{project_hash}` | GET | No | Query: [list parameters](#list-parameters) | List one project's keys |

## Validation endpoint

| Path | Method | Auth | Purpose |
| --- | --- | --- | --- |
| `/auth/validate-api-key` | POST | `X-API-Key: sk_{public_id}.{secret}`; no `Authorization` header | Resolve a key to its owner context |

The response (`ValidateApiKeyResponse`) has `success`, `valid`, `auth_method` (`"api_key"`),
`user` (`user_hash`, `username`, `email`, `user_type`), `project` (`project_hash`,
`project_name`), `api_key` (`key_id`, `public_id`), `user_groups[]`, `permissions[]` and, for
consumer owners, `plan`. The key and secret are never echoed. The header `X-Auth-Process-Time`
carries the handling time in milliseconds.

Failures use the standard error envelope. `error.code` is the generic code for the status
(`VAL_3001`, `AUTH_1003` or `AUTHZ_2001`); the specific reason is in `error.message`:

| Status | `error.message` | Cause |
| --- | --- | --- |
| `400` | `ambiguous_credentials` | Both `Authorization` and `X-API-Key` were sent |
| `401` | `Missing API key` | No `X-API-Key` header |
| `401` | `Malformed API key: AUTH_1010` | Not `sk_{public_id}.{secret}` |
| `401` | `API key not found: NF_4010` | Unknown `public_id` |
| `401` | `Invalid API key: AUTH_1010` | The secret does not match |
| `401` | `API key has been revoked: AUTH_1012` | `is_active` is false |
| `401` | `API key has expired: AUTH_1011` | Past `expires_at` |
| `401` | `API key owner is inactive: AUTH_1010` | The owner account is deactivated |
| `403` | `API key owner lost project access: AUTHZ_2008` | The owner no longer reaches the project |

Permissions are resolved live: root owners get `admin` and `global_admin`; admin owners get `admin`
and `project_admin` while they administer the project; consumers get their group names and
global-role permissions. A valid result is cached in Redis under `apikey:{public_id}` for `60`
seconds. The entry holds the key's `secret_hash`, never the secret, and a cache hit is used only
after the presented secret matches it; a wrong secret, or an entry without a hash, goes through
the full database check. Full walkthrough:
[Authentication usage cases](../authentication-usage-cases.md#validate-an-api-key).

## Request fields

### Create fields

| Field | Required | Default | Notes |
| --- | --- | --- | --- |
| `user_hash` | Admin route only, yes | — | Owner of the new key |
| `project_hash` | Yes | — | Project the key is scoped to. Self-service: the caller must reach it (root: any active project). |
| `name` | No | Self-service: `API Key - YYYY-MM-DD` (UTC date). Admin: `API Key - {owner username}` | Up to 100 characters |
| `description` | No | `null` | Free text |
| `expires_at` | No | Never expires | ISO 8601 in the future; no timezone means UTC |

### Update fields

Send at least one of `name`, `description`, `expires_at`; otherwise `400` `VAL_3001`. An empty
value counts as absent, so a field cannot be cleared. `expires_at` must be in the future. A
future `expires_at` on an expired key makes it usable again (the trigger logs
`api_key_reactivated` when the key had been deactivated). A revoked key cannot be updated
(`400` `AUTH_1012`).

### Revoke field

| Field | Route | Notes |
| --- | --- | --- |
| `revoke_reason` | `DELETE /api-keys/{key_id}` only | Optional, up to 255 characters. Stored on the key and in the `api_key_revoked` activity row. |

### List parameters

| Parameter | Default | Range | Notes |
| --- | --- | --- | --- |
| `limit` | `50` | 1–200 | Page size |
| `offset` | `0` | ≥ 0 | Keys to skip |
| `active_only` | `false` | — | Keep keys with `is_active: true`. Ignored by `GET /api-keys/users/{user_hash}` and by `GET /api-keys` with `user_hash`. |
| `project_hash` | — | — | `GET /users/api-keys` only: keep keys of this project |

Results are ordered newest first.

### Admin list filters

`GET /api-keys` chooses its source from the filters:

| Filters | Result |
| --- | --- |
| `user_hash` and `project_hash` | That user's keys in that project. Admin must administer the project. |
| `user_hash` only | That user's keys; for an admin, only keys in projects they administer. The user must reach at least one of those projects (`403` `AUTHZ_2001` otherwise). |
| `project_hash` only | That project's keys. Admin must administer the project. |
| Neither, root caller | `400` `VAL_3001` "Root users must provide at least user_hash or project_hash filter" |
| Neither, admin caller | Each administered project is read with the same `limit` and `offset`, the pages are concatenated and cut to `limit`; `total` is the sum of the project totals |

## Responses

All routes return `{"success": true, "message": "...", "data": {...}}`.

### Key object

`data` on create, get and update; each item of `data.keys` on lists. Built by
`_format_key_response`; `secret_hash` is never included.

| Field | Notes |
| --- | --- |
| `id` | Same value as `public_id` |
| `public_id` | Use as `{key_id}` |
| `name`, `description` | Labels |
| `project_id`, `owner_user_id` | Internal IDs |
| `is_active` | `false` after revocation, or within 5 minutes of `expires_at` passing, when the expiry sweep deactivates the key |
| `expires_at` | `null` means the key never expires |
| `last_used_at` | Set by `sp_validate_api_key` when the key passes its state checks (before the secret is compared); cache hits do not update it |
| `created_at`, `updated_at` | Timestamps |
| `revoked_at`, `revoke_reason` | Set by revocation |
| `fingerprint` | First 6 bytes of `BLAKE2s(token)` as 12 hex characters |
| `secret_last4` | Last 4 characters of the secret |
| `hash_algorithm` | `hmac-sha256-v1` |
| `api_key` | Create response only: the full `sk_{public_id}.{secret}` token |

The create response omits values the insert does not return, so `last_used_at`, `updated_at`,
`revoked_at` and `revoke_reason` are `null` there.

Admin routes add the enrichment columns their procedure returns:

| Route | Extra fields per key |
| --- | --- |
| `GET /api-keys/{key_id}` | `project_name`, `project_hash`, `owner_username`, `owner_user_hash`, `owner_user_type` |
| `GET /api-keys/projects/{project_hash}`, `GET /api-keys` with `project_hash` only or no filter | `project_name`, `project_hash`, `owner_username`, `owner_user_hash` |
| `GET /api-keys/users/{user_hash}`, `GET /api-keys` with `user_hash` | `project_name`, `project_hash` |

### List payload

```json
{
  "success": true,
  "message": "API keys retrieved successfully",
  "data": { "keys": [], "total": 0, "limit": 50, "offset": 0 }
}
```

`GET /api-keys/users/{user_hash}` adds `data.user_hash` and `data.username`.
`GET /api-keys/projects/{project_hash}` adds `data.project_hash` and `data.project_name`.

How `total` is counted differs by route:

| Route | `total` |
| --- | --- |
| `GET /users/api-keys` without filters | All keys the caller owns |
| `GET /users/api-keys` with `project_hash` or `active_only` | Only the matching keys **on the fetched page**. Filters run after `limit`/`offset`, so a page can be short even when more matches exist. |
| Admin routes with `user_hash` | Every matching key the caller may see (filtering happens before paging) |
| Admin project routes | All keys of the project that match `active_only` |

### Revoke response

```json
{
  "success": true,
  "message": "API key revoked successfully",
  "data": { "key_id": "Xk3pQ9aL2mNb", "revoked_at": "2026-09-24T10:15:00.123456+00:00" }
}
```

## Error codes

| Code | HTTP | Cause |
| --- | --- | --- |
| `AUTH_1008` | 401 | Recent authentication required for create, update or revoke |
| `VAL_3001` | 400 | Malformed or past `expires_at`, update with no fields, or root `GET /api-keys` without a filter |
| `AUTH_1012` | 400 | Update of a revoked key, or revoke of a key that is already inactive |
| `AUTHZ_2003` | 403 | Self-service create for a project the caller does not reach |
| `AUTHZ_2001` | 403 | Admin route: project or user outside the admin's scope |
| `AUTHZ_2002` | 403 | Admin create for another user without `manage_users`; or a caller that is neither root nor admin on `GET /api-keys` and `GET /api-keys/users/{user_hash}` |
| `NF_4010` | 404 | Unknown `key_id`, or (self-service) a key the caller does not own |
| `NF_4004` | 404 | Unknown `user_hash` or `project_hash` |
| `CONF_5005` | 409 | The database refused the create: owner inactive, project inactive or archived, or (non-root creator) owner without access to the project |

A caller that is not root or admin and holds no `admin` permission is stopped earlier by
`verify_admin_access` with `403` "Admin access required". See [Errors](../errors.md) for the
envelope.

## Token format and cryptography

Implemented in `src/Util/api_key_security.py`.

| Item | Value |
| --- | --- |
| Token | `sk_{public_id}.{secret}` |
| `public_id` | 9 random bytes, base64url without padding: 12 characters |
| `secret` | 32 random bytes, base64url without padding: 43 characters |
| Stored hash | `HMAC-SHA-256(API_KEY_PEPPER, "v1:{public_id}:{secret}")`, `BINARY(32)` |
| `hash_algorithm` label | `hmac-sha256-v1` |
| `fingerprint` | `BLAKE2s(token, digest_size=6)` as 12 hex characters |
| `secret_last4` | Last 4 characters of `secret` |
| Verification | Split on the last `.`, check the `sk_` prefix and `public_id`, recompute the HMAC, compare with `hmac.compare_digest`. Malformed tokens are compared against a dummy hash so rejection takes the same time. |

| Env var | Notes |
| --- | --- |
| `API_KEY_PEPPER` | Required. Read when `src/Util/api_key_security.py` is imported; the process fails to start without it. Changing it invalidates every existing key. |

## Stored procedures

| Procedure | Used by |
| --- | --- |
| `sp_create_api_key` | Both create routes. Re-checks owner and project state and, for non-root creators, the owner's project access. |
| `sp_get_api_key_by_prefix` | Get, update and revoke lookups by `public_id` |
| `sp_list_user_api_keys` | Self-service list and admin user listings |
| `sp_list_project_api_keys` | Admin project listings |
| `sp_update_api_key` | Both update routes. Refuses revoked keys; reactivates a deactivated expired key. |
| `sp_revoke_api_key` | Both revoke routes. Only changes active keys. |
| `sp_validate_api_key` | Key validation; returns the stored hash and a `validation_status` |
| `sp_cleanup_expired_api_keys` | Deactivates expired keys. Run every 5 minutes by each API process (`src/Util/api_key_expiry.py`); the update trigger records `api_key_expired` per key. |
