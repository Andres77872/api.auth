# API Keys Documentation

Detailed, repo-specific documentation for the API key system implemented in `api.auth`.

---

## 📖 Overview

API keys are long-lived, project-scoped credentials issued to a single user. They use a
**split-token** design — `sk_{public_id}.{secret}` — where only the `public_id` is stored
in clear and the `secret` is never persisted in plaintext. The full token is revealed
**exactly once**, in the response to the create call, and can never be retrieved again.

There are **two route families**, separated by who is acting:

| Family | Prefix | Auth dependency | Who | Acts on |
|--------|--------|-----------------|-----|---------|
| Self-service | `/users/api-keys` | `verify_session` | Any authenticated user | The caller's **own** keys |
| Admin | `/api-keys` | `verify_admin_access` | Root or admin | Keys on behalf of **other** users, within scope |

A separate **validation** endpoint, `POST /auth/validate-api-key`, lets a service exchange a
raw key (sent in the `X-API-Key` header) for the owner's identity, project, groups, and
permissions. That endpoint lives in the **auth suite** and is cross-linked from here; it is not
owned by this suite.

- **`/users/api-keys/*`** — create, list, get, update, delete the caller's own keys. Authorization
  is **ownership-only**: a non-owned key returns `404` (existence is not leaked).
- **`/api-keys/*`** — root/admin management. Root is unrestricted; admins are limited to projects
  they administer and need `manage_users` to act on **other** users' keys (self-service is always
  allowed). Includes two audit views: by user and by project.

Source files (authoritative): `src/routes/user_api_keys.py`, `src/routes/api_keys.py`,
`src/Util/api_key_security.py`. Validation adapter: `src/routes/auth.py`.

---

## 🗂️ Documents in This Suite

| Document | Focus |
|----------|-------|
| [usage.md](usage.md) | Day-to-day self-service and admin lifecycle flows (create, list, get, update, revoke) |
| [reference.md](reference.md) | Endpoint table for both families, response envelope, per-key object fields, query params |
| [scenarios.md](scenarios.md) | Concrete curl workflows: issue + reveal, validate, admin provisioning, audit, rotation |
| [troubleshooting.md](troubleshooting.md) | Failure modes, error codes, the paginate-then-filter caveat, and best practices |

---

## 🔐 Key Format and Security

The token layout and cryptography are implemented in `src/Util/api_key_security.py`.

- **Token format**: `sk_{public_id}.{secret}`
  - prefix `sk_`
  - `public_id` — ~12 base64url chars (9 bytes of entropy); indexed in the DB for lookup
  - `secret` — ~43 base64url chars (32 bytes of entropy); **never** stored in plaintext
  - the two halves are joined by a single `.`
- **Stored hash**: `HMAC-SHA-256(pepper, "v1:{public_id}:{secret}")` stored as `BINARY(32)`. The
  server-side `API_KEY_PEPPER` is loaded at startup (fail-fast if missing). The stored
  `hash_algorithm` label is `hmac-sha256-v1`.
- **Fingerprint**: first 6 bytes of `BLAKE2s(full_token)` → 12 hex chars. Safe to display in a UI.
- **secret_last4**: the last 4 chars of the secret, for human confirmation only.
- **Verification**: splits the presented token on the **last** dot, checks the `sk_` prefix and
  matching `public_id`, recomputes the HMAC, and compares with `hmac.compare_digest`
  (constant-time). Malformed tokens are compared against a **dummy hash** so rejection timing
  matches the valid path (timing-attack resistance).
- **One-time reveal**: the full token appears **only** in the create response, under
  `data.api_key`. List / get / update / delete responses never include `api_key`, the secret, or
  `secret_hash`. A lost token cannot be recovered — issue a new key.

---

## 🚦 Recommended Reading Order

1. Start with this README for the model and key format.
2. Read [usage.md](usage.md) for the self-service then admin lifecycles.
3. Keep [reference.md](reference.md) open while operating the API.
4. Use [scenarios.md](scenarios.md) for end-to-end curl workflows.
5. Use [troubleshooting.md](troubleshooting.md) for failure handling and best practices.

---

## ⚠️ Scope and Caveats

- **API version `2.2.0`.** Every request must send a `User-Agent` header (missing → `422`).
- **All write endpoints take form fields** (`application/x-www-form-urlencoded`), not JSON bodies.
  Create and update use FastAPI `Form(...)` params.
- **`key_id` in every path is the `public_id`** (the ~12-char base64url segment), **not** the
  numeric DB id and **not** the full token. Lookups use `get_api_key_by_public_id`.
- **Step-up re-authentication** (`require_recent_reauthentication`) is required for **create,
  update, and delete** on both families. Read (GET) endpoints do **not** require step-up.
- **`expires_at` is future-only** ISO 8601. A naive timestamp is assumed UTC; a `Z` suffix is
  accepted. A past date → `400 INVALID_INPUT`. Extending `expires_at` past `NOW()` on an expired
  key reactivates it.
- **Root must filter on `GET /api-keys`.** There is no "list all keys" path; root must supply
  `user_hash` or `project_hash`.
- **Pagination is applied before filtering** on some routes (see the paginate-then-filter caveat in
  [troubleshooting.md](troubleshooting.md)); `total` can be a post-filter count.

---

## 🔗 Related Documentation

- **[Usage Documentation Home](../README.md)** — complete usage index
- **[Authentication Usage Cases](../authentication-usage-cases.md)** — `POST /auth/validate-api-key`
  (the `X-API-Key` consumer flow) lives here
- **[Users Documentation Suite](../users/README.md)** — user hashes, `manage_users`, admin scope
- **[Projects Documentation Suite](../projects/README.md)** — project hashes and project reach
- **[Permissions Documentation Suite](../permissions/README.md)** — effective permissions and `manage_users`
- **[Errors Reference](../errors.md)** — global error envelope and codes
- **[Database Schema](../../../schemas/)** — SQL tables and stored procedures

---

**Document Version**: 1.0
