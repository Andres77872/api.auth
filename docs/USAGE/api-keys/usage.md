# API keys usage

One task per section. Field tables, defaults and error codes are in [reference.md](reference.md);
suite-wide rules (form bodies, recent authentication, expiry) are in
[README.md](README.md#rules-and-caveats).

The examples use `$TOKEN` for an access token and `$PUBLIC_ID` for a key's `public_id`.

## Manage your own keys

Any signed-in user can manage the keys they own under `/users/api-keys`.

### Create a key

`POST /users/api-keys` — form fields `project_hash` (required), `name`, `description`,
`expires_at`. Needs recent authentication.

```bash
curl -X POST "http://localhost:8000/users/api-keys" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$PROJECT_HASH" \
  -d "name=ci-runner" \
  -d "expires_at=2027-01-01T00:00:00Z"
```

The response message is "API key created successfully. Save this token — it will not be shown
again." Store `data.api_key` (the full token) now; later responses never include it. Keep
`data.public_id` to address the key.

```json
{
  "success": true,
  "message": "API key created successfully. Save this token — it will not be shown again.",
  "data": {
    "id": "Xk3pQ9aL2mNb",
    "public_id": "Xk3pQ9aL2mNb",
    "name": "ci-runner",
    "description": null,
    "project_id": "7c1e4f0a-2b1d-4c55-9a8e-0f2b6d3e9a11",
    "owner_user_id": "2f9d1c3b-5e7a-4b8c-9d0e-1a2b3c4d5e6f",
    "is_active": true,
    "expires_at": "2027-01-01T00:00:00",
    "last_used_at": null,
    "created_at": "2026-09-24T10:00:00",
    "updated_at": null,
    "revoked_at": null,
    "revoke_reason": null,
    "fingerprint": "a1b2c3d4e5f6",
    "secret_last4": "Wq7Z",
    "hash_algorithm": "hmac-sha256-v1",
    "api_key": "sk_Xk3pQ9aL2mNb.<43-character secret>"
  }
}
```

A project you do not reach returns `403` `AUTHZ_2003`; an unknown `project_hash` returns `404`.

### List your keys

`GET /users/api-keys` — query `project_hash`, `active_only`, `limit` (1–200, default `50`),
`offset`.

```bash
curl "http://localhost:8000/users/api-keys?limit=50&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `data.keys`, `data.total`, `data.limit`, `data.offset`. Revoked and expired keys are
included.

> [!WARNING]
> `project_hash` and `active_only` are applied to the page after `limit`/`offset`, and `total`
> then counts only that filtered page. To see every key of one project, page through the
> unfiltered list and filter on the client.

### Get one key

`GET /users/api-keys/{key_id}`

```bash
curl "http://localhost:8000/users/api-keys/$PUBLIC_ID" \
  -H "Authorization: Bearer $TOKEN"
```

A key you do not own returns the same `404` `NF_4010` as a missing key.

### Rename a key or change its expiry

`PUT /users/api-keys/{key_id}` — form fields `name`, `description`, `expires_at`; send at least
one. Needs recent authentication.

```bash
curl -X PUT "http://localhost:8000/users/api-keys/$PUBLIC_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -d "expires_at=2027-06-30T00:00:00Z"
```

Returns the updated key object. A future `expires_at` makes an expired key usable again. A revoked
key returns `400` `AUTH_1012`.

### Revoke a key

`DELETE /users/api-keys/{key_id}` — no body. Needs recent authentication.

```bash
curl -X DELETE "http://localhost:8000/users/api-keys/$PUBLIC_ID" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `data.key_id` and `data.revoked_at`. The key stops validating immediately. A key that is
already inactive returns `400` `AUTH_1012`.

## Manage keys as an administrator

Root and admin users manage keys under `/api-keys`. Admins are limited to projects they administer.

### Create a key for a user

`POST /api-keys` — form fields `user_hash` and `project_hash` (required), `name`, `description`,
`expires_at`. Needs recent authentication.

```bash
curl -X POST "http://localhost:8000/api-keys" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hash=$USER_HASH" \
  -d "project_hash=$PROJECT_HASH" \
  -d "name=billing-sync"
```

The token is in `data.api_key`, once. Hand it to the owner over a secure channel.

An admin needs `manage_users` in the project to create a key for someone else (`403` `AUTHZ_2002`
otherwise). If the owner is inactive or does not reach the project, or the project is inactive or
archived, the database refuses the key with `409` `CONF_5005`. Root skips the owner-access check,
not the owner and project state checks.

### List keys by user or project

`GET /api-keys` — query `user_hash`, `project_hash`, `active_only`, `limit`, `offset`.

```bash
curl "http://localhost:8000/api-keys?project_hash=$PROJECT_HASH&active_only=true" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Root must pass `user_hash` or `project_hash` (`400` otherwise). An admin with no filter gets keys
from every project they administer. See [admin list filters](reference.md#admin-list-filters) for
how each combination pages and counts.

### List one user's keys

`GET /api-keys/users/{user_hash}` — query `limit`, `offset`. `active_only` is accepted but ignored.

```bash
curl "http://localhost:8000/api-keys/users/$USER_HASH?limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Returns `data.user_hash`, `data.username`, `data.keys`, `data.total`. An admin sees only keys in
projects they administer, and the user must reach at least one of them (`403` `AUTHZ_2001`
otherwise).

### List one project's keys

`GET /api-keys/projects/{project_hash}` — query `active_only`, `limit`, `offset`.

```bash
curl "http://localhost:8000/api-keys/projects/$PROJECT_HASH?active_only=true" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Returns `data.project_hash`, `data.project_name`, and keys with `owner_username` and
`owner_user_hash`.

### Inspect, update or revoke any key in scope

- `GET /api-keys/{key_id}` returns the key with project and owner details.
- `PUT /api-keys/{key_id}` takes the same form fields as the self-service update. It has no
  `manage_users` check.
- `DELETE /api-keys/{key_id}` takes an optional `revoke_reason` (up to 255 characters).

```bash
curl -X DELETE "http://localhost:8000/api-keys/$PUBLIC_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "revoke_reason=employee offboarded"
```

Update and revoke need recent authentication.

## Validate a key

A service that receives a key sends it in `X-API-Key`, with no `Authorization` header:

```bash
curl -X POST "http://localhost:8000/auth/validate-api-key" \
  -H "X-API-Key: $API_KEY"
```

A valid key returns `valid: true` with the owner, project, `api_key.public_id`, groups and
permissions. Failure statuses are listed in [reference.md](reference.md#validation-endpoint); the
full contract is in
[Authentication usage cases](../authentication-usage-cases.md#validate-an-api-key).
