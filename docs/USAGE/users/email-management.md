# Users Email Management

Operational guide for the per-user email lifecycle endpoints in `src/routes/users.py`.

Email is a **separate identity from the user record**: `user_emails` is the
authoritative multi-email store and `users.email` is only a deprecated
compatibility shadow that never grants login by itself. These endpoints let a
user manage their own email addresses (add, list, resend activation, remove,
choose primary), and let root/admin operators inspect or re-trigger activation
for another user's emails. The data-model, token, and worker internals are in
[architecture.md](architecture.md#email-identity-lifecycle) and the
[Email Activation Runbook](../../RUNBOOKS/email-activation.md).

---

## Endpoint Summary

| Endpoint | Method | Auth | Purpose |
|----------|--------|------|---------|
| `/users/me/emails` | GET | Any authenticated user | List the caller's own email rows (owner view) |
| `/users/me/emails` | POST | Any authenticated user | Add/reuse a pending email and enqueue an activation link |
| `/users/me/emails/{email_id}/resend` | POST | Any authenticated user | Resend activation for an owned pending email |
| `/users/me/emails/{email_id}` | DELETE | Any authenticated user | Soft-remove an owned email |
| `/users/me/emails/{email_id}/primary` | POST | Any authenticated user | Set an owned activated email as primary |
| `/users/{user_hash}/emails` | GET | Root or admin | List a target user's emails (masked/hash-only view) |
| `/users/{user_hash}/emails/{email_id}/resend` | POST | Root or admin | Re-trigger activation for a target user's email |

The `/users/me/emails*` group only requires a valid session (`get_current_user`)
and always acts on the authenticated caller's `user_id`. The two
`/users/{user_hash}/emails*` routes additionally enforce
`_require_admin_or_root(current_user)` — the caller must be `root` or have
`user_type == 'admin'`.

---

## Multi-Email Model

A user can hold multiple `user_emails` rows. Each row has a `status`:

| Status | Meaning |
|--------|---------|
| `pending` | Added but not yet activated through a link token |
| `activated` | Activated via a hash-only token; usable login/recovery identity |
| `removed` | Soft-removed by the owner (`removed_at` set) |
| `suppressed` | Hard-bounced/complained per provider webhook |

At most one **activated, non-removed** row may exist per normalized address
globally, and at most one active **primary** row exists per user (both enforced
by DB-level `VIRTUAL` generated columns). Only an `activated` email can be made
primary, and only the primary activated email is eligible for password recovery
and admin reset-link delivery.

---

## Generic Response Posture

The send-side endpoints (`POST /users/me/emails`, both resend routes) follow the
same non-enumerating posture as the public email endpoints:

- They return a generic `202 Accepted` for any syntactically processable request,
  whether or not a deliverable row actually changed. Enqueue failures are caught
  internally and still return the generic `202`, so the response body never
  reveals whether an email exists, is owned, or was actually queued.
- The only detailed public exception is rate limiting: `429` with a
  `Retry-After` header (see below).
- `GET` routes return a normal `200` JSON body with the email list.
- `DELETE` and `POST .../primary` return a normal `200` JSON body describing the
  state change (these act on a row the caller already owns, so they are not
  subject to the generic-202 posture).

---

## Rate Limiting, Resend Cooldown, and Idempotency

### Rate limiting (`429 + Retry-After`)

Every send-side route runs `EmailRateLimiter().check_send_request(...)` keyed by
purpose (`email_activation`), a recipient hash, the user id, and the client IP.
When a bucket is exceeded the route returns:

```json
HTTP/1.1 429 Too Many Requests
Retry-After: 60

{ "error": { "code": "...", "details": { "retry_after_seconds": 60 } } }
```

Clients **must** back off for at least `Retry-After` seconds before retrying.

### Resend cooldown

The resend routes additionally enforce a per-recipient resend cooldown via
`EmailRateLimiter().check_resend_cooldown(...)`. The cooldown window is
`EMAIL_RESEND_COOLDOWN_SECONDS` (default **60s**, overridable by environment).
A resend issued inside the cooldown returns `429 + Retry-After`. A successful
resend marks the cooldown so an immediate repeat is throttled.

### Idempotency-Key

`POST /users/me/emails` and `POST /users/me/emails/{email_id}/resend` honor an
optional `Idempotency-Key` request header. When a key replays a previously
completed request, the route returns the same generic `202` body without
enqueuing a second activation. The admin-triggered resend
(`POST /users/{user_hash}/emails/{email_id}/resend`) does **not** read an
idempotency key; it relies on the rate limiter and resend cooldown for repeat
suppression.

---

## Owner Endpoints (`/users/me/emails*`)

### List own emails

```bash
curl -X GET "http://localhost:8000/users/me/emails" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: ops-tool/1.0"
```

Returns the caller's `user_emails` rows in the **owner view**, which includes the
normalized plaintext `email` plus `email_masked`:

```json
{
  "success": true,
  "emails": [
    {
      "id": "uem-...",
      "email": "user@example.com",
      "email_masked": "u***@example.com",
      "status": "activated",
      "is_primary": true,
      "added_at": "...",
      "activated_at": "...",
      "removed_at": null,
      "last_activation_sent_at": "...",
      "updated_at": "..."
    }
  ]
}
```

### Add a new email (enqueue activation)

```bash
curl -X POST "http://localhost:8000/users/me/emails" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: ops-tool/1.0" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=new@example.com"
```

The body field `email` may be sent as form data **or** JSON
(`Content-Type: application/json`); `read_request_payload` parses either. The
route validates basic email shape, adds/reuses a `pending` row, generates a
hash-only activation link token, enqueues the activation email through the
durable outbox, and returns a generic `202`. An invalid email shape is rejected
with a validation error before any enqueue.

### Resend activation for a pending email

```bash
curl -X POST "http://localhost:8000/users/me/emails/$EMAIL_ID/resend" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: ops-tool/1.0"
```

Use this when the original activation email was lost. Subject to the rate limit
and the resend cooldown; returns a generic `202`.

### Remove an email

```bash
curl -X DELETE "http://localhost:8000/users/me/emails/$EMAIL_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: ops-tool/1.0"
```

Soft-removes an owned email and returns the id of the replacement primary, if
the DB selected one:

```json
{
  "success": true,
  "message": "Email removed successfully",
  "email_id": "uem-...",
  "new_primary_email_id": "uem-..."
}
```

Removing an email **revokes the user's other sessions** (reason
`email_removed`) while preserving the current authenticated session when
possible.

### Set the primary email

```bash
curl -X POST "http://localhost:8000/users/me/emails/$EMAIL_ID/primary" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: ops-tool/1.0"
```

Promotes an owned **activated** email to primary. Like removal, this **revokes
the user's other sessions** (reason `email_primary_changed`) while keeping the
current session when possible. Response:

```json
{
  "success": true,
  "message": "Primary email updated successfully",
  "email_id": "uem-...",
  "status": "primary_changed"
}
```

> Session note: because changing or removing the primary email alters the
> account's recovery identity, the route deliberately invalidates every other
> session so any compromised or stale session loses its foothold. Clients on
> other devices must re-authenticate.

---

## Admin / Root Endpoints (`/users/{user_hash}/emails*`)

Both routes require `root` or `admin` (`_require_admin_or_root`).

### List a target user's emails (masked/hash view)

```bash
curl -X GET "http://localhost:8000/users/$USER_HASH/emails" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: ops-tool/1.0"
```

The **admin view** never returns the plaintext address. It exposes
`email_masked` and `email_hash` only, alongside lifecycle metadata:

```json
{
  "success": true,
  "user_hash": "usr-...",
  "emails": [
    {
      "id": "uem-...",
      "user_id": "...",
      "email_hash": "…",
      "email_masked": "u***@example.com",
      "status": "activated",
      "is_primary": true,
      "added_at": "...",
      "activated_at": "...",
      "removed_at": null,
      "last_activation_sent_at": "...",
      "updated_at": "..."
    }
  ]
}
```

### Re-trigger activation for a target user's email

```bash
curl -X POST "http://localhost:8000/users/$USER_HASH/emails/$EMAIL_ID/resend" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: ops-tool/1.0"
```

Lets an operator re-send an activation link for a target user's pending email.
Subject to the same rate limit and resend cooldown as the owner resend, and
returns a generic `202`. It does **not** read an `Idempotency-Key`.

> For admin-triggered **password** reset links (not activation), use
> `POST /users/{user_hash}/reset-password`, documented in
> [usage.md](usage.md#queue-an-admin-password-reset-link) and
> [reference.md](reference.md).

---

## Operator Notes

- Email is optional for registration and account use; a user with no activated
  email simply cannot use email login or email recovery, but username login and
  account access still work.
- These routes do not return a token, activation/reset URL, or email body, and
  do not expose provider payload. Admin list views additionally withhold the plaintext address.
- Add/resend success cannot be inferred from the `202` body — confirm delivery
  through the outbox/worker and audit log as described in the runbook.
- Removing or re-pointing the primary email is a security-relevant action that
  intentionally fans out a session revocation.

---

## Related Documentation

- **[Users Overview](README.md)**
- **[Usage](usage.md)**
- **[Operational Reference](reference.md)**
- **[Architecture — Email Identity Lifecycle](architecture.md#email-identity-lifecycle)**
- **[Email Activation & Transactional Auth Email Runbook](../../RUNBOOKS/email-activation.md)**
- **[User Types](user-types.md)**
- **[Bulk Operations](bulk-operations.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: June 2026
**Document Version**: 1.0
</content>
</invoke>
