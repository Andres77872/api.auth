# API Keys Scenarios and Examples

Concrete, repo-specific curl workflows for issuing, validating, auditing, and rotating API keys.

> All examples send a `User-Agent` header (required; missing → `422`). `{key_id}` path segments are
> the key's **`public_id`**. Writes are form-encoded. Create / update / delete require recent
> re-authentication (step-up); if step-up has lapsed, re-authenticate first.

---

## Scenario 1: User Issues a Key and Captures the One-Time Token

Goal: a logged-in user creates a key, saves the token, then inspects / updates / revokes it.

```bash
# 1. Create the key (form fields). The full token is shown exactly once.
curl -X POST "http://localhost:8000/users/api-keys" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: my-app/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$PROJECT_HASH&name=ci-runner&expires_at=2026-12-31T00:00:00Z"
# → data.api_key = "sk_<public_id>.<secret>"  ← SAVE THIS NOW; it cannot be retrieved again.
# → data.public_id = "<public_id>"            ← use this as {key_id}

# 2. List your keys (token is NOT included here)
curl -X GET "http://localhost:8000/users/api-keys?active_only=true" \
  -H "Authorization: Bearer $TOKEN" -H "User-Agent: my-app/1.0"

# 3. Inspect one key by public_id
curl -X GET "http://localhost:8000/users/api-keys/$PUBLIC_ID" \
  -H "Authorization: Bearer $TOKEN" -H "User-Agent: my-app/1.0"

# 4. Update name / expiry (at least one field required)
curl -X PUT "http://localhost:8000/users/api-keys/$PUBLIC_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: my-app/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "name=ci-runner-prod"

# 5. Revoke when done (immediate cache invalidation)
curl -X DELETE "http://localhost:8000/users/api-keys/$PUBLIC_ID" \
  -H "Authorization: Bearer $TOKEN" -H "User-Agent: my-app/1.0"
```

---

## Scenario 2: Validate a Key (X-API-Key header)

Goal: a service exchanges a raw key for the owner's identity, project, groups, and permissions.
This calls the **auth suite's** `POST /auth/validate-api-key`.

```bash
# Correct: raw token in X-API-Key, NO Authorization header
curl -X POST "http://localhost:8000/auth/validate-api-key" \
  -H "X-API-Key: sk_<public_id>.<secret>" \
  -H "User-Agent: my-service/1.0"
# → { "success": true, "valid": true, "auth_method": "api_key",
#     "user": {...}, "project": {...},
#     "api_key": { "key_id": "...", "public_id": "..." },
#     "user_groups": [...], "permissions": [...] }
```

Wrong way (do not send both credentials):

```bash
# Sending BOTH Authorization and X-API-Key → 400 ambiguous_credentials
curl -X POST "http://localhost:8000/auth/validate-api-key" \
  -H "Authorization: Bearer $TOKEN" \
  -H "X-API-Key: sk_<public_id>.<secret>" \
  -H "User-Agent: my-service/1.0"
# → 400 { "detail": "ambiguous_credentials" }
```

The raw key and secret are never echoed back. See
[Authentication Usage Cases](../authentication-usage-cases.md).

---

## Scenario 3: Admin Provisions a Key for Another User

Goal: an admin issues a key on behalf of a teammate. Requires the `manage_users` effective
permission for the target's project (root bypasses) and project scope.

```bash
curl -X POST "http://localhost:8000/api-keys" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: ops/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hash=$USER_HASH&project_hash=$PROJECT_HASH&name=service-key&expires_at=2027-01-01T00:00:00Z"
# → data.api_key shown once; hand it to the user over a secure channel.
```

Failure cues:
- `403 ACCESS_DENIED` → the project is not in the admin's scope.
- `403 INSUFFICIENT_PERMISSIONS` → the admin lacks `manage_users` for another user's key.
  (Creating a key for **yourself** as an admin never needs `manage_users`.)

---

## Scenario 4: Admin Audits Keys by User and by Project

```bash
# All keys for one user (response includes user_hash + username).
# Non-root admins see only keys within their own projects; total is recomputed.
curl -X GET "http://localhost:8000/api-keys/users/$USER_HASH?active_only=true" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "User-Agent: ops/1.0"

# All keys for one project (response includes project_hash + project_name).
curl -X GET "http://localhost:8000/api-keys/projects/$PROJECT_HASH?limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN" -H "User-Agent: ops/1.0"

# Root-scoped flat list MUST include a filter (user_hash or project_hash):
curl -X GET "http://localhost:8000/api-keys?user_hash=$USER_HASH" \
  -H "Authorization: Bearer $ROOT_TOKEN" -H "User-Agent: ops/1.0"
# Omitting both as root → 400 INVALID_INPUT
```

---

## Scenario 5: Rotate a Key (create new, validate, revoke old)

Goal: replace a credential with zero downtime.

```bash
# 1. Create the replacement key
curl -X POST "http://localhost:8000/users/api-keys" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: my-app/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$PROJECT_HASH&name=ci-runner-v2"
# → save data.api_key (NEW token) and data.public_id (NEW public_id)

# 2. Validate the new key works before cutting over
curl -X POST "http://localhost:8000/auth/validate-api-key" \
  -H "X-API-Key: sk_<new_public_id>.<new_secret>" \
  -H "User-Agent: my-app/1.0"

# 3. Deploy the new token, then revoke the old key (immediate cache invalidation)
curl -X DELETE "http://localhost:8000/users/api-keys/$OLD_PUBLIC_ID" \
  -H "Authorization: Bearer $TOKEN" -H "User-Agent: my-app/1.0"
```

Tip: instead of revoking immediately, you can set a short future `expires_at` on the old key with
`PUT` to give consumers a grace window — then it deactivates automatically.

---

**Document Version**: 1.0
