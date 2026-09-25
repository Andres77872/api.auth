# User email management

A user can hold several email addresses. They live in `user_emails`, and only an **activated**
address can be used to sign in, receive a password-reset link, or become the primary address. The
`users.email` column is a legacy shadow: the database keeps it equal to the primary activated address,
and it never grants login on its own.

Email is optional. The `email` accepted by `POST /auth/register`, `PUT /users/profile`,
`PUT /users/{user_hash}` and `POST /user-types/root|admin` only writes that legacy column; it is not
an address under this lifecycle. To make an address usable, add it with `POST /users/me/emails` and
open the activation link.

Two route groups operate the lifecycle:

- `/users/me/emails*`: any signed-in user, always acting on their own account.
- `/users/{user_hash}/emails*`: root and admin operators, limited to users in their
  [admin scope](reference.md#caller-rules).

The endpoint inventory is in the [reference](reference.md#users-routes). The delivery pipeline (outbox,
worker, provider webhooks) is covered by the [email suite](../email/README.md) and
`docs/RUNBOOKS/email-activation.md`.

## Address lifecycle

| Status | How a row gets there | Sign-in and reset links |
| --- | --- | --- |
| `pending` | `POST /users/me/emails` | No |
| `activated` | The emailed token is submitted to `POST /auth/email/verify` | Yes |
| `removed` | `DELETE /users/me/emails/{email_id}` | No |
| `suppressed` | A provider hard bounce or complaint for that address | No |

Rules the database enforces:

- A user has at most 5 `pending` + `activated` addresses. Further adds are refused silently (the
  route still returns `202`).
- One account at a time can hold an address as `activated`. If another account already activated it,
  the activation link is consumed and the row stays `pending`.
- A user has at most one primary address, and only an `activated` address can be primary. The first
  address a user activates becomes primary automatically.
- `users.email` follows the primary: it is set on first activation and on a primary change. Removing
  the primary promotes the earliest-activated remaining address, or clears `users.email` when none is
  left.
- Suppression clears `is_primary` without promoting another address. Username sign-in keeps working.
- Password-reset links (self-service and `POST /users/{user_hash}/reset-password`) go to the primary
  activated address, else the earliest-activated one.

## Response posture

The send routes (`POST /users/me/emails` and both resend routes) answer every accepted request with
the same `202` body, so the response never reveals whether an address exists, belongs to someone,
or was queued. Enqueue failures are logged and still return `202`.

```json
{
  "success": true,
  "message": "If the request can be processed, it has been accepted."
}
```

Apart from `401` for a bad token and the admin route's scope errors (`403`, `404`), the only other
outcomes are `400` for a missing or malformed `email` on the add route, and `429` when a rate limit
or the resend cooldown applies:

```http
HTTP/1.1 429 Too Many Requests
Retry-After: 42
Content-Type: application/json

{"status": "error", "error": {"code": "INT_7005", "category": "internal", "message": "Rate limit exceeded", "details": {"retry_after_seconds": 42}}}
```

Wait at least `Retry-After` seconds before retrying. The list, remove and primary routes return
ordinary `200` bodies.

## Rate limits and cooldown

Each send consumes four fixed-window buckets for the `email_activation` purpose. The defaults come
from `.env.example`; see [Settings](reference.md#settings).

| Bucket | Default | Key |
| --- | --- | --- |
| Recipient per hour | `3` | Add: the hashed address. Resend: the user and `email_id` |
| Recipient per day | `10` | As above |
| Caller per hour | `5` | The signed-in user (the admin, on the admin resend) |
| Client IP per hour | `20` | The client IP |

The resend routes also enforce a per-address cooldown of `EMAIL_RESEND_COOLDOWN_SECONDS` (default
`60`). Inside the cooldown the route returns `429`; the database applies the same window as a
second check and then sends nothing.

The limiter fails closed: if Redis is unavailable the send routes return `429`.

Rate limits and the cooldown are checked **before** the `Idempotency-Key` replay. A retry therefore
still consumes bucket capacity, and retrying a resend inside the cooldown returns `429` even with the
same key.

## Idempotency-Key

`POST /users/me/emails` and `POST /users/me/emails/{email_id}/resend` accept an optional
`Idempotency-Key` header (1 to 128 characters from `A-Z a-z 0-9 . _ : -`; malformed keys are
ignored). Repeating a completed request with the same key returns the stored `202` without sending
again, for `EMAIL_IDEMPOTENCY_TTL_SECONDS` (default `86400`). The admin resend route does not read the
header.

## Owner routes

### List your addresses

`GET /users/me/emails`

```bash
curl "http://localhost:8000/users/me/emails" \
  -H "Authorization: Bearer $TOKEN"
```

Returns the owner view: the full normalized address plus a masked copy. Removed addresses are
omitted; the primary comes first, then by date added.

```json
{
  "success": true,
  "emails": [
    {
      "id": "uem-5f0c2a9e4b7d4c1e9a3b6d8f0e2c4a61",
      "email": "user@example.com",
      "email_masked": "u***r@example.com",
      "status": "activated",
      "is_primary": true,
      "added_at": "2026-09-01T10:00:00",
      "activated_at": "2026-09-01T10:05:00",
      "removed_at": null,
      "last_activation_sent_at": "2026-09-01T10:00:00",
      "updated_at": "2026-09-01T10:05:00"
    }
  ]
}
```

### Add an address

`POST /users/me/emails` with `email` as a form field or JSON body.

```bash
curl -X POST "http://localhost:8000/users/me/emails" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  --data-urlencode "email=new@example.com"

curl -X POST "http://localhost:8000/users/me/emails" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "new@example.com"}'
```

The address is trimmed and lower-cased. Every outcome below returns the same `202`:

| Situation | What happens |
| --- | --- |
| New address | A `pending` row is created and an activation link is queued |
| Already `pending` on your account | Earlier activation links are revoked and a new one is queued |
| Already `activated` or `suppressed` on your account | Nothing is sent |
| You already have 5 `pending` + `activated` addresses | Nothing is added or sent |
| Activated by another account | A `pending` row and a link are created, but activation will not apply |

The activation link targets `/auth/email/verify` on the configured public base URL (or an
allow-listed `X-Public-Base-Url` header from a BFF, else the request origin) and expires after
`EMAIL_ACTIVATION_TOKEN_TTL_SECONDS` (default `86400`).

### Activate an address

`POST /auth/email/verify` is public: the emailed token is the credential. It returns `202` for every
outcome. When the address becomes `activated`, **all** of the user's sessions and refresh tokens are
revoked, including the session that added the address, so the user signs in again. Request details
are in [Authentication usage](../authentication-usage-cases.md).

### Resend activation

`POST /users/me/emails/{email_id}/resend`

```bash
curl -X POST "http://localhost:8000/users/me/emails/$EMAIL_ID/resend" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $(uuidgen)"
```

Only an own `pending` address gets a new link (earlier links are revoked). An unknown, foreign,
removed or non-pending `email_id` also returns `202` and sends nothing.

### Remove an address

`DELETE /users/me/emails/{email_id}`

```bash
curl -X DELETE "http://localhost:8000/users/me/emails/$EMAIL_ID" \
  -H "Authorization: Bearer $TOKEN"
```

Any own non-removed address can be removed, including the last one. Unused links for it are revoked.
If it was the primary, the earliest-activated remaining address becomes primary.

```json
{
  "success": true,
  "message": "Email removed successfully",
  "email_id": "uem-5f0c2a9e4b7d4c1e9a3b6d8f0e2c4a61",
  "new_primary_email_id": null
}
```

`new_primary_email_id` is set only when a new primary was chosen. An `email_id` that is not one of
your current addresses returns `404` (`NF_4004`) and changes nothing.

### Change the primary address

`POST /users/me/emails/{email_id}/primary`

```bash
curl -X POST "http://localhost:8000/users/me/emails/$EMAIL_ID/primary" \
  -H "Authorization: Bearer $TOKEN"
```

```json
{
  "success": true,
  "message": "Primary email updated successfully",
  "email_id": "uem-5f0c2a9e4b7d4c1e9a3b6d8f0e2c4a61",
  "status": "primary_changed"
}
```

The address must be your own, `activated` and not removed; otherwise the route returns `409`
(`CONF_5005`) with the database's reason in `error.message`. `users.email` becomes this address.

## Admin routes

Root may act on any user. An admin may act on themselves and on non-root users who reach one of the
projects the admin is assigned to; anyone else returns `403` (`AUTHZ_2001`). An unknown or inactive
`user_hash` returns `404`.

### List a user's addresses

`GET /users/{user_hash}/emails`

```bash
curl "http://localhost:8000/users/$USER_HASH/emails" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

The admin view never contains the plain address: it has `email_masked` and `email_hash` (hex of the
peppered hash). Removed addresses are included and sorted last.

```json
{
  "success": true,
  "user_hash": "usr-4d1c9b2e7a6f4e3d8c5b0a9f1e2d3c4b",
  "emails": [
    {
      "id": "uem-5f0c2a9e4b7d4c1e9a3b6d8f0e2c4a61",
      "user_id": "usr-8a7b6c5d-4e3f-4a1b-9c8d-7e6f5a4b3c2d",
      "email_hash": "9F86D081884C7D659A2FEAA0C55AD015A3BF4F1B2B0B822CD15D6C15B0F00A08",
      "email_masked": "u***r@example.com",
      "status": "activated",
      "is_primary": true,
      "added_at": "2026-09-01T10:00:00",
      "activated_at": "2026-09-01T10:05:00",
      "removed_at": null,
      "last_activation_sent_at": "2026-09-01T10:00:00",
      "updated_at": "2026-09-01T10:05:00"
    }
  ]
}
```

### Resend a user's activation

`POST /users/{user_hash}/emails/{email_id}/resend`

```bash
curl -X POST "http://localhost:8000/users/$USER_HASH/emails/$EMAIL_ID/resend" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Same behavior as the owner resend (generic `202`, rate limits, cooldown), except that the caller
bucket is the admin's and `Idempotency-Key` is ignored. Admin password-reset links use a different
route: see [Send a password-reset link](usage.md#send-a-password-reset-link).

## Session effects

| Action | Sessions and refresh tokens revoked |
| --- | --- |
| Add, resend | None |
| Activation through `POST /auth/email/verify` | All of the user's, including the current one |
| Remove an address (`email_removed`) | All except the caller's current session |
| Change the primary (`email_primary_changed`) | All except the caller's current session |
| Suppression by a provider event | None |

If the current session cannot be identified from the access token, remove and primary changes fall
back to revoking every session. A `404` or `409` revokes nothing.

## Auditing

Each route writes an activity record: `user_email_activation_requested` (add),
`user_email_activation_resent` (both resends), `user_email_removed`, `user_email_primary_changed`,
and `user_email_activated` (verify). A `202` does not prove delivery; check the outbox and delivery
logs described in the [email suite](../email/README.md).
