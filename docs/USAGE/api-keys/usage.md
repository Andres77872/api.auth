# API Keys Usage

Day-to-day flows for issuing and managing API keys in `api.auth`. Two families are covered:
the **self-service** family (`/users/api-keys`, the caller's own keys) and the **admin** family
(`/api-keys`, keys for other users within scope).

> Conventions for this whole suite:
> - API version `2.2.0`; every request needs a `User-Agent` header (missing → `422`).
> - All write endpoints (`POST`, `PUT`, `DELETE`) take **form fields**
>   (`application/x-www-form-urlencoded`), not JSON.
> - `{key_id}` in a path is always the key's **`public_id`** (the ~12-char base64url segment),
>   never the numeric DB id and never the full token.
> - Create / update / delete require **recent re-authentication** (step-up). Reads do not.

---

## Self-Service Lifecycle (`/users/api-keys`)

All five endpoints require a logged-in session (`verify_session`) and operate **only** on keys
the caller owns. Source: `src/routes/user_api_keys.py`.

### 1. Create a key — `POST /users/api-keys`

Form fields:

| Field | Required | Notes |
|-------|----------|-------|
| `project_hash` | yes | Must be a project the caller can access (else `403 PROJECT_ACCESS_DENIED`) |
| `name` | no | Defaults to `API Key - YYYY-MM-DD` if omitted |
| `description` | no | Free text |
| `expires_at` | no | ISO 8601, **future-only** (else `400 INVALID_INPUT`) |

Requires step-up re-auth. The response includes the **one-time** full token at `data.api_key`
and the message *"API key created successfully. Save this token — it will not be shown again."*

```bash
curl -X POST "http://localhost:8000/users/api-keys" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: my-app/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$PROJECT_HASH&name=ci-runner&expires_at=2026-12-31T00:00:00Z"
```

Capture `data.api_key` immediately. It is the only time the secret is shown.

### 2. List your keys — `GET /users/api-keys`

Query params: `project_hash` (optional), `active_only` (bool, default `false`),
`limit` (1–200, default `50`), `offset` (≥0, default `0`).

```bash
curl -X GET "http://localhost:8000/users/api-keys?active_only=true&limit=50" \
  -H "Authorization: Bearer $TOKEN" -H "User-Agent: my-app/1.0"
```

**Paginate-then-filter caveat:** the underlying fetch is paged first, then `project_hash` and
`active_only` are applied in Python and `total` is recomputed as the length of the filtered slice.
So `total` is a post-filter count while pagination is pre-filter. See
[troubleshooting.md](troubleshooting.md).

### 3. Get one key — `GET /users/api-keys/{key_id}`

`{key_id}` is the `public_id`. Ownership is enforced; a missing **or** non-owned key both return
`404 API_KEY_NOT_FOUND` (existence is not leaked). The secret / `secret_hash` is never returned.

```bash
curl -X GET "http://localhost:8000/users/api-keys/$PUBLIC_ID" \
  -H "Authorization: Bearer $TOKEN" -H "User-Agent: my-app/1.0"
```

### 4. Update a key — `PUT /users/api-keys/{key_id}`

Form fields (all optional, but **at least one** is required or `400 INVALID_INPUT`): `name`,
`description`, `expires_at`. Requires step-up re-auth. Ownership enforced (`404` otherwise).

```bash
curl -X PUT "http://localhost:8000/users/api-keys/$PUBLIC_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: my-app/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "description=rotated&expires_at=2027-01-01T00:00:00Z"
```

**Reactivation:** extending `expires_at` past `NOW()` on an already-expired key reactivates it.

### 5. Revoke a key — `DELETE /users/api-keys/{key_id}`

Requires step-up re-auth. Ownership enforced. Revocation **immediately invalidates the Redis
cache** so the key stops authenticating at once. Re-revoking an already-revoked or nonexistent key
returns `API_KEY_REVOKED`. The user route has **no** `revoke_reason` field.

```bash
curl -X DELETE "http://localhost:8000/users/api-keys/$PUBLIC_ID" \
  -H "Authorization: Bearer $TOKEN" -H "User-Agent: my-app/1.0"
```

---

## Admin Lifecycle (`/api-keys`)

All seven endpoints require `verify_admin_access` (root **or** admin). Root is unrestricted;
admins are limited to projects they administer (via `check_admin_project_access`). Source:
`src/routes/api_keys.py`.

### Create on behalf of a user — `POST /api-keys`

Form fields:

| Field | Required | Notes |
|-------|----------|-------|
| `user_hash` | yes | The key owner |
| `project_hash` | yes | Admin must administer it (root bypasses) |
| `name` | no | Defaults to `API Key - {username}` |
| `description` | no | Free text |
| `expires_at` | no | ISO 8601, future-only |

Requires step-up re-auth. Scope rules: root unrestricted; admin must have project access **and**
the `manage_users` effective permission when the target is **another** user (creating a key for
**yourself** is always allowed). Response includes the one-time token at `data.api_key`.

```bash
curl -X POST "http://localhost:8000/api-keys" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: ops/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hash=$USER_HASH&project_hash=$PROJECT_HASH&name=service-key"
```

### List within scope — `GET /api-keys`

Query params: `user_hash`, `project_hash`, `active_only` (default `false`), `limit` (1–200,
default `50`), `offset` (≥0).

- **Root must supply `user_hash` or `project_hash`** — there is no list-all path. Omitting both →
  `400 INVALID_INPUT` *"Root users must provide at least user_hash or project_hash filter"*.
- An admin **without** a project filter aggregates keys across all their accessible projects
  (results are truncated to `limit`; `total` is the summed per-project counts).
- A `project_hash` filter is scope-checked; a `user_hash` filter additionally verifies the target
  user shares at least one project with the admin (`ACCESS_DENIED` otherwise).

```bash
curl -X GET "http://localhost:8000/api-keys?project_hash=$PROJECT_HASH&active_only=true" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "User-Agent: ops/1.0"
```

### Get one — `GET /api-keys/{key_id}`

`{key_id}` is the `public_id`. The admin must have scope over the key's project (root bypasses);
missing → `404 API_KEY_NOT_FOUND`. No `secret_hash`.

### Update — `PUT /api-keys/{key_id}`

Form fields `name` / `description` / `expires_at`; at least one required. Requires step-up re-auth.
Admin must have project scope. Extending `expires_at` reactivates an expired key.

### Revoke — `DELETE /api-keys/{key_id}`

Requires step-up re-auth. Admin must have project scope. Takes an **optional** `revoke_reason`
form field (the user route has none). Immediate Redis cache invalidation; re-revoking returns
`API_KEY_REVOKED`.

```bash
curl -X DELETE "http://localhost:8000/api-keys/$PUBLIC_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: ops/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "revoke_reason=employee offboarded"
```

### Audit by user — `GET /api-keys/users/{user_hash}`

Lists all keys for a specific user. Admin must share at least one project with the target (root
bypasses); for non-root, returned keys are filtered to the admin's projects and `total` is
recomputed. Response includes `user_hash` and `username`. Query params: `active_only`, `limit`,
`offset`.

### Audit by project — `GET /api-keys/projects/{project_hash}`

Lists all keys scoped to a project. Admin must administer the project (root bypasses). Response
includes `project_hash` and `project_name`. Query params: `active_only`, `limit`, `offset`.

---

## Validating a Key (cross-link)

Issued keys are consumed via `POST /auth/validate-api-key`, which is **header-based**: send the
raw token in `X-API-Key` (not `Authorization: Bearer`). Sending **both** `Authorization` and
`X-API-Key` returns `400 ambiguous_credentials`. This endpoint is part of the **auth suite** — see
[Authentication Usage Cases](../authentication-usage-cases.md) and the example in
[scenarios.md](scenarios.md).

---

**Document Version**: 1.0
