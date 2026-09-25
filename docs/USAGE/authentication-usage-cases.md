# Authentication

The server-side contract of the `/auth` routes: how to sign in, register, recover and change a
password, validate and rotate tokens, switch projects, log out, and validate API keys. Every
example uses `API=http://localhost:8000` and relies on curl's default `User-Agent`.

- First-time setup (configuration, first root, first project and user):
  [Getting started](getting-started.md).
- Building a browser, mobile or server client on top of this contract:
  [Client integration guide](client-authentication-guide.md).
- Error envelope and codes: [standard error envelope](errors.md#standard-error-envelope) and
  [error code catalog](errors.md#error-code-catalog). Platform rules (`User-Agent`, 8 MiB POST
  limit, content types): [platform-wide contracts](README.md#platform-wide-contracts).

## Endpoints at a glance

"Access token" means `Authorization: Bearer <access_token>` or the `session_token` cookie.

| Method | Path | Credential | Body | Purpose |
| --- | --- | --- | --- | --- |
| `POST` | `/auth/login` | none | form | Project-scoped sign-in for every user type |
| `POST` | `/auth/platform/login` | none | form | Project-less sign-in for root and admin |
| `POST` | `/auth/register` | none | form | Create a consumer account in a user group |
| `POST` | `/auth/check-availability` | none | form | Check whether a username or email is taken |
| `POST` | `/auth/email/verify` | emailed link token | JSON or form | Activate an added email address |
| `POST` | `/auth/password/forgot` | none | JSON or form | Request a password reset email |
| `POST` | `/auth/password/reset` | emailed link token | JSON or form | Set a new password from the emailed link |
| `POST` | `/auth/password/change` | access token | JSON or form | Change the signed-in user's password |
| `GET` | `/auth/validate` | access token | none | Inspect the current session |
| `POST` | `/auth/refresh` | refresh token | form or cookie | Rotate the access/refresh pair |
| `POST` | `/auth/switch-project` | access + refresh token, recent sign-in | form | Move the session to another project |
| `POST` | `/auth/logout` | access token | none | Revoke the session's refresh family and clear cookies |
| `POST` | `/auth/validate-api-key` | `X-API-Key` | none | Resolve the owner and project of a user API key |

OAuth sign-in (`/auth/oauth/*`) and the deprecated `/auth/google/*` aliases are covered in
[OAuth sign-in](#oauth-sign-in).

## Tokens and sessions

A successful sign-in (password login, platform login, registration or OAuth callback) starts a
**refresh family**: a chain of access/refresh pairs that share one `family_id`. Each refresh or
project switch retires the current pair and issues the next one.

- **Access token** — HS256 JWT (`type: access_token`) sent on every protected request. The server
  also stores it in Redis as `session:{jti}`. Only the family's newest access token is valid: a
  refresh or project switch invalidates the previous one immediately, even before it expires.
- **Refresh token** — HS256 JWT (`type: refresh_token`). Single use, accepted only by
  `POST /auth/refresh` and `POST /auth/switch-project`.
- **`session_token`** — deprecated alias: the JSON field has the same value as `access_token`, and
  the access cookie carries this name. It is never a refresh credential.
- **Scope** — `project` sessions are bound to one project (login, registration, OAuth, switch);
  `platform` sessions come from `/auth/platform/login` and have no project.
- **Sign-in time** — the access token's `auth_time` claim records when the user last proved
  credentials. Refresh and project switch carry it forward unchanged, so rotating never counts as
  a new sign-in.

On every request that presents an access token, the server checks the signature, `exp`, token
type and required claims, the Redis session and family state, and then rebuilds the user's
context from the database: the user must be active, the project active and not archived, a
consumer must still reach the project through a user group, and an admin must still be assigned to
it. If the context check fails, the whole family is revoked and the request gets `401`.

### Lifetimes

| Item | Default | Configured by | Behavior |
| --- | --- | --- | --- |
| Access token and `session_token` cookie | `900` seconds | `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (default `15`) | Fixed per token |
| Refresh family, `remember_me=false` | `259200` seconds (72 hours) | fixed | Sliding: every successful refresh restarts the 72-hour window |
| Refresh family, `remember_me=true` | `2592000` seconds (30 days) | fixed | Absolute: ends 30 days after sign-in; `refresh_expires_in` counts down |
| Refresh replay grace | `10` seconds | `REFRESH_REPLAY_GRACE_SECONDS` (`0` disables) | See [Refresh the token pair](#refresh-the-token-pair) |
| Recent sign-in window | `300` seconds | `OAUTH_RECENT_REAUTH_SECONDS` (falls back to `GOOGLE_OAUTH_RECENT_REAUTH_SECONDS`) | Gates `/auth/switch-project` and other sensitive operations |

### Where each credential is accepted

| Credential | Transport | Accepted by |
| --- | --- | --- |
| Access token | `Authorization: Bearer <token>` (exact `Bearer ` prefix), or the `session_token` cookie. The header wins when both are sent. | Every protected route, including `/auth/validate`, `/auth/logout`, `/auth/switch-project`, `/auth/password/change` |
| Refresh token | `refresh_token` cookie (`Path=/auth`) and/or `refresh_token` form field. If both are sent they must be identical. `Authorization` is ignored. | `/auth/refresh`, `/auth/switch-project` |
| User API key | `X-API-Key: sk_<public_id>.<secret>` | `/auth/validate-api-key`, plus `POST /auth/oauth/init` and `GET /auth/oauth/providers` ([OAuth suite](oauth/README.md)). No other route treats it as a credential. |

The cookie names, attributes and lifetimes set by the server are listed in the
[client integration guide](client-authentication-guide.md).

### Token-pair responses

Login, platform login, registration, refresh and OAuth sign-in return a `LoginResponse`
(registration: `RegisterResponse`); project switching returns a `SwitchProjectResponse`. All three
share these top-level token fields:

| Field | Type | Meaning |
| --- | --- | --- |
| `access_token` | string | Access JWT |
| `refresh_token` | string | Refresh JWT |
| `session_token` | string | Deprecated alias; same value as `access_token` |
| `token_type` | string | Always `Bearer` |
| `expires_in` | integer | Access-token lifetime in seconds |
| `refresh_expires_in` | integer | Seconds until the refresh family expires |
| `expires_at` | datetime | Access-token expiry (UTC) |
| `refresh_expires_at` | datetime | Refresh-family expiry (UTC) |
| `remember_me` | boolean | Refresh mode of the family |

`LoginResponse` adds:

| Field | Meaning |
| --- | --- |
| `user` | `user_hash`, `username`, `email` (the account's legacy email field), `user_type` |
| `project` | `project_hash`, `project_name`, `project_description`; `null` for platform sessions |
| `accessible_projects` | Projects the user can target later with `/auth/switch-project` |
| `user_groups` | `{group_hash, group_name, description}` objects; empty for root and admin |
| `plan` | Subscription projection for project-scoped consumers; `null` otherwise |
| `user_id` | Internal user ID, present because the model carries it for logging. Identify users by `user.user_hash`. |

Nested objects also serialize `created_at`, `updated_at` and similar optional keys as `null`;
examples on this page omit them.

### Session plan projection

Consumer login, consumer refresh, `GET /auth/validate` for a consumer project session, and
`POST /auth/validate-api-key` for a consumer-owned key return `plan`. The server resolves it at
response time from the project's billing group; it is not stored in tokens, cookies or Redis, and it
is not an authorization input.

| Field | Values |
| --- | --- |
| `state` | `none` (no billing group or billing disabled), `free`, `trial`, `active`, `past_due`, `canceled` |
| `active` | `true` only for `trial` and `active` |
| `provider` | Provider name (default `stripe`) |
| `plan_code`, `tier_code` | Opaque catalog labels; `null` for `none` and `free` |
| `current_period_end`, `trial_end`, `cancel_at_period_end` | Subscription dates and flag |

A lookup failure degrades to `state: "none"` instead of failing the request. Registration, project
switching, platform login and root/admin sessions return `plan: null` or omit it; call
`GET /auth/validate` after a switch when you need the new project's plan.

## Log in

### Project login

`POST /auth/login` — form fields:

| Field | Required | Notes |
| --- | --- | --- |
| `username` | yes | Username, or an activated email address |
| `password` | yes | |
| `project_hash` | yes | Required for every user type, root included |
| `remember_me` | no | `true` selects the 30-day absolute refresh family (default `false`) |

Who can target which project:

| User type | Allowed projects | `message` on success |
| --- | --- | --- |
| Consumer | Projects reachable through the user's groups (user group → project group → project) | `Login successful` |
| Admin | Projects the admin is assigned to administer | `Login successful` |
| Root | Any active, non-archived project; group checks are skipped | `Root user login successful` |

```bash
curl -s -X POST "$API/auth/login" \
  --data-urlencode "username=alice" \
  --data-urlencode "password=$ALICE_PASSWORD" \
  --data-urlencode "project_hash=$PROJECT_HASH"
```

The response sets the `session_token` and `refresh_token` cookies and returns:

```jsonc
{
  "success": true,
  "message": "Login successful",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_expires_in": 259200,
  "expires_at": "2026-09-24T12:15:00.482113Z",
  "refresh_expires_at": "2026-09-27T12:00:00.482113Z",
  "remember_me": false,
  "user": {"user_hash": "usr-3f6c...", "username": "alice", "email": null, "user_type": "consumer"},
  "project": {"project_hash": "9F2C...", "project_name": "My Project", "project_description": "First project"},
  "accessible_projects": [
    {"project_hash": "9F2C...", "project_name": "My Project", "project_description": "First project"}
  ],
  "user_groups": [{"group_hash": "UG-7D1E...", "group_name": "user_proj-2b7c...", "description": "Regular users"}],
  "plan": {"provider": "stripe", "state": "none", "active": false, "plan_code": null, "tier_code": null,
           "current_period_end": null, "trial_end": null, "cancel_at_period_end": false},
  "user_id": "usr-8a41..."
}
```

Root and admin responses have `user_groups: []` and `plan: null`. The admin's
`accessible_projects` lists its assigned projects.

| Status | Code | When |
| --- | --- | --- |
| `400` | `VAL_3001`, `VAL_3002` | `username`, `password` or `project_hash` missing (`project_hash` is checked after the password) |
| `401` | `AUTH_1001` | Wrong password, unknown identifier, or inactive account; the response does not say which |
| `403` | `AUTHZ_2001` | Consumer reaches no project at all |
| `403` | `AUTHZ_2003` | Project not reachable by this user, admin not assigned, or project inactive or archived |
| `404` | `NF_4002` | Root or admin: project hash does not exist (consumers get `403` instead) |
| `429` | `INT_7005` | Failed-login limit reached; see [Login rate limits](#login-rate-limits) |

### Log in with an activated email

Send the email in the `username` field. The server resolves an exact username first, then an
**activated** address from the user's email list. Pending, removed or unknown addresses, and the
legacy `email` given at registration, fail with the same `401 AUTH_1001` as a wrong password. Add
and activate addresses with `/users/me/emails` ([email management](users/email-management.md)).

### Platform login

`POST /auth/platform/login` — form fields `username`, `password`, optional `remember_me`. Only root
and admin accounts can complete it; it needs no `project_hash` and issues a `platform`-scoped pair.

```bash
curl -s -X POST "$API/auth/platform/login" \
  --data-urlencode "username=root" \
  --data-urlencode "password=$ROOT_PASSWORD"
```

The response is a `LoginResponse` with `message: "Platform login successful"`, `project: null`,
`accessible_projects: []`, `user_groups: []` and `plan: null`, and it sets the same two cookies.
Refreshing a platform pair keeps platform scope. Errors match project login, plus `403 AUTHZ_2002`
when the account is a consumer (checked after the password).

### Remember me

`remember_me=true` on `/auth/login`, `/auth/platform/login` (or on OAuth init/start) switches the
new family from a 72-hour sliding window to a fixed 30-day window that ends 30 days after sign-in,
however often it is refreshed. The flag is echoed as top-level `remember_me` on login, refresh and
switch responses and as `session.remember_me` on `/auth/validate`. Registration always issues a
default family.

### Login rate limits

Both login routes count **failed** credential checks in Redis and refuse further attempts, before
checking the password, once a bucket is full:

| Bucket | Default limit | Window | Variables |
| --- | --- | --- | --- |
| Client IP + identifier | `10` failures | `900` seconds | `EMAIL_LOGIN_IDENTIFIER_FAILURE_LIMIT`, `EMAIL_LOGIN_IDENTIFIER_FAILURE_WINDOW_SECONDS` |
| Identifier, any IP | `30` failures | `900` seconds | `EMAIL_LOGIN_ACCOUNT_FAILURE_LIMIT`, `EMAIL_LOGIN_ACCOUNT_FAILURE_WINDOW_SECONDS` |

The identifier is compared trimmed and lower-cased. A blocked attempt returns `429 INT_7005` with a
`Retry-After` header and `error.details.retry_after_seconds`. Windows are fixed, so a successful
login does not reset them. The client IP is the first `X-Forwarded-For` entry, then `X-Real-IP`,
then the socket address; strip or overwrite those headers at your proxy. If Redis is unavailable,
the check fails closed with `429` and `Retry-After: 1`.

## Register

### Check availability

`POST /auth/check-availability` — form fields `username` and/or `email` (at least one, else
`400 VAL_3002`). Each value is compared against active accounts' usernames and legacy `email`
fields.

```bash
curl -s -X POST "$API/auth/check-availability" \
  --data-urlencode "username=alice" \
  --data-urlencode "email=alice@example.com"
```

```json
{"success": true, "message": null, "username_available": true, "email_available": true}
```

A field is `null` when it was not sent. Use this only as a registration helper: it does not tell you
whether an email is activated, and it must not drive activation or recovery logic.

### Create an account

`POST /auth/register` — form fields:

| Field | Required | Notes |
| --- | --- | --- |
| `username` | yes | Must not match any active account's username or email |
| `password` | yes | Checked by the [password policy](#password-policy) with the username and email as context |
| `user_group_hash` | yes | User group the consumer joins; anyone who knows the hash can register into it |
| `email` | no | Stored in the account's legacy `email` field only (see below) |

```bash
curl -s -X POST "$API/auth/register" \
  --data-urlencode "username=alice" \
  --data-urlencode "password=$ALICE_PASSWORD" \
  --data-urlencode "user_group_hash=$GROUP_HASH"
```

The account is always a consumer. When the group reaches at least one active project, the new
session is scoped to the first one by name, the token fields are filled and both cookies are set;
otherwise the token fields are `null` and no cookie is set.

```jsonc
{
  "success": true,
  "message": "User registered successfully",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_expires_in": 259200,
  "expires_at": "2026-09-24T12:15:00.482113Z",
  "refresh_expires_at": "2026-09-27T12:00:00.482113Z",
  "remember_me": false,
  "user": {"user_hash": "usr-3f6c...", "username": "alice", "email": null, "user_type": "consumer"},
  "project": {"project_hash": "9F2C...", "project_name": "My Project"},
  "user_id": "usr-8a41..."
}
```

`RegisterResponse` has no `accessible_projects`, `user_groups` or `plan`; call
`GET /auth/validate` or log in when you need them.

| Status | Code | When |
| --- | --- | --- |
| `400` | `VAL_3001`, `VAL_3002` | A required field is missing |
| `400` | `VAL_3007` | Password rejected by the policy |
| `404` | `NF_4003` | User group not found |
| `409` | `CONF_5001` | Username already in use |
| `409` | `CONF_5002` | Email already in use |

> [!IMPORTANT]
> The `email` sent at registration is not an activated address: it cannot be used to log in and
> does not receive recovery email. Email is optional; to use one, add it with `POST /users/me/emails`
> and activate it through the emailed link ([email management](users/email-management.md)).

### Password policy

Registration, reset, change and root/admin creation share one server-side policy. A rejected
password returns `400 VAL_3007`.

| Rule | Reason code | Configured by |
| --- | --- | --- |
| Minimum length, default `8` | `too_short` | `PASSWORD_POLICY_MIN_LENGTH` |
| Not on the common-password list | `common_password` | `PASSWORD_POLICY_WEAK_DENYLIST` (comma-separated; replaces the built-in list) |
| Does not contain the username or email (3+ characters) | `obvious_identifier_derivation` | — |
| Not one repeated character or a straight letter/digit run (8+ characters) | `repeated_or_sequential` | — |

There is no character-class rule. The reason codes and `min_length` appear under
`error.details.context` only when `DEBUG_MODE` is on; in production the client sees the code and
the message `Weak password (VAL_3007)`, so show general guidance and let the server decide.

## Email activation and password reset

These public routes serve the links sent by email. Adding, listing and resending addresses is part of
[email management](users/email-management.md); delivery (templates, provider, worker) is in the
[email suite](email/README.md).

### Rules for the public email routes

- Send JSON (`Content-Type: application/json`); `application/x-www-form-urlencoded` and
  `multipart/form-data` are also read.
- Every processable request returns the same `202` body, whether or not the account, address or
  link exists. Treat it as "accepted", never as proof:

  ```json
  {"success": true, "message": "If the request can be processed, it has been accepted."}
  ```

- `429 INT_7005` carries `Retry-After` and `error.details.retry_after_seconds`; wait before retrying.
- An optional `Idempotency-Key` header makes retries safe: a repeat with the same key replays the
  stored `202` without repeating side effects. Malformed keys are ignored.
- None of these routes creates a session. After a successful activation or reset, send the user to
  a normal login.
- Emailed links point at `/auth/email/verify?token=...` and `/auth/password/reset?token=...` on the
  public base URL; the frontend must serve those pages and POST the token here. The link token has
  the form `<lookup_id>.<secret>`. Never log full links or link tokens.

| Rate limit | Default | Variable |
| --- | --- | --- |
| Link consumption per lookup ID (verify, reset) | `5` per hour | `EMAIL_CONSUME_LOOKUP_HOURLY_LIMIT` |
| Link consumption per client IP (verify, reset) | `30` per hour | `EMAIL_CONSUME_IP_HOURLY_LIMIT` |
| Reset requests per identifier (forgot) | `3` per hour, `10` per day | `EMAIL_SEND_RECIPIENT_HOURLY_LIMIT`, `EMAIL_SEND_RECIPIENT_DAILY_LIMIT` |
| Reset requests per client IP (forgot) | `20` per hour | `EMAIL_SEND_IP_HOURLY_LIMIT` |

### Activate an email

`POST /auth/email/verify` — body `token` (or `lookup_id` + `secret`).

```bash
curl -s -X POST "$API/auth/email/verify" \
  -H "Content-Type: application/json" \
  -d "{\"token\":\"$LINK_TOKEN\"}"
```

A missing or malformed token also returns `202`. When the activation changes the account's
sign-in identity, all of the user's sessions and refresh families are revoked. Activation links
expire after `EMAIL_ACTIVATION_TOKEN_TTL_SECONDS` (default `86400`).

### Request a password reset email

`POST /auth/password/forgot` — body `email_or_username` (aliases `identifier`, `email`,
`username`). A missing identifier is the only non-`202` validation error (`400 VAL_3002`).

```bash
curl -s -X POST "$API/auth/password/forgot" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: $(uuidgen)" \
  -d '{"email_or_username":"alice@example.com"}'
```

A message is queued only when the identifier matches an active account's **activated** email, or
its username (the message then goes to the primary activated email). Pending, removed or unknown
addresses and legacy-only `email` values get the same `202` and no message.

The emailed link is built from, in order: a pinned base URL (`AUTH_EMAIL_PUBLIC_BASE_URL`, then
`PUBLIC_AUTH_BASE_URL` or `BASE_URL`); the `X-Public-Base-Url` request header, when it is an http(s)
origin listed in `ALLOWED_ORIGINS`; otherwise the API's own origin. A BFF, or the browser app itself,
should send its frontend origin in `X-Public-Base-Url` unless the deployment pins one.

### Reset the password

`POST /auth/password/reset` — body `new_password` (alias `password`) and `token` (or `lookup_id` +
`secret`). Links from `POST /auth/password/forgot` and admin-issued reset links are both accepted.

```bash
curl -s -X POST "$API/auth/password/reset" \
  -H "Content-Type: application/json" \
  -d "{\"token\":\"$LINK_TOKEN\",\"new_password\":\"$NEW_PASSWORD\"}"
```

`new_password` is validated before the link: a missing value returns `400 VAL_3002` and a weak one
`400 VAL_3007`, whatever the link state. Every link outcome (reset, unknown, expired, already used)
then returns `202`. A successful reset revokes all of the user's sessions and refresh families.
A reset link works once, and not after `EMAIL_PASSWORD_RESET_TOKEN_TTL_SECONDS` (default `3600`).

## Change the password

`POST /auth/password/change` — access token plus `current_password` and `new_password` as a JSON
object or form fields. The current password is the step-up proof, so no recent sign-in is needed.
Do not send password fields to `PUT /users/profile`; it rejects them with `400 VAL_3001` and points
here.

```bash
curl -s -X POST "$API/auth/password/change" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"current_password\":\"$CURRENT_PASSWORD\",\"new_password\":\"$NEW_PASSWORD\"}"
```

```json
{"success": true, "message": "Password changed successfully"}
```

No new tokens are issued. Every other session and refresh family of the user is revoked. The
calling session stays valid: keep using the same access token, and the refresh token keeps working
too.

| Status | Code | When |
| --- | --- | --- |
| `400` | `VAL_3002` | A field is missing |
| `400` | `VAL_3007` | New password rejected by the policy (checked with the username as context) |
| `401` | `AUTH_1003` | Access token missing, expired or revoked |
| `401` | `AUTH_1001` | Wrong current password (same generic posture as login) |
| `429` | `INT_7005` | Attempt limit reached; `Retry-After` is set |

Attempts that pass the field and policy checks are counted, successful or not: by default `5` per
user per hour (`AUTH_CHANGE_PASSWORD_USER_HOURLY_LIMIT`), `5` per session per hour
(`AUTH_CHANGE_PASSWORD_SESSION_HOURLY_LIMIT`) and `20` per client IP per hour
(`AUTH_CHANGE_PASSWORD_IP_HOURLY_LIMIT`).

## Validate an access token

`GET /auth/validate` — access token only. API keys are not accepted here; use
[`POST /auth/validate-api-key`](#validate-an-api-key).

```bash
curl -s "$API/auth/validate" -H "Authorization: Bearer $ACCESS_TOKEN"
```

```jsonc
{
  "success": true,
  "message": null,
  "valid": true,
  "auth_method": "session",
  "user": {"user_hash": "usr-3f6c...", "username": "alice", "email": null, "user_type": "consumer"},
  "project": {"project_hash": "9F2C...", "project_name": "My Project"},
  "session": {
    "created_at": null,
    "scope": "project",
    "expires_at": "2026-09-24T12:15:00+00:00",
    "refresh_expires_at": "2026-09-27T12:00:00.482113+00:00",
    "remember_me": false
  },
  "user_groups": ["user_proj-2b7c..."],
  "plan": {"provider": "stripe", "state": "active", "active": true, "plan_code": "pro", "tier_code": "monthly",
           "current_period_end": "2026-10-24T00:00:00Z", "trial_end": null, "cancel_at_period_end": false}
}
```

- `user.email` is always `null` here; `project` is `null` for platform sessions.
- `session.expires_at` is the access-token expiry; `session.refresh_expires_at` is the family's
  absolute deadline for `remember_me` families and the current sliding expiry otherwise.
- `user_groups` holds group **names**: the user's groups in the project for consumers, and fixed
  labels such as `root_users`, `project_admins` or `platform_root_users` for root and admin.
- The response carries an `X-Auth-Process-Time` header (milliseconds).
- Any missing, malformed, expired or revoked token, or a failed context check, returns `401`.

## Refresh the token pair

`POST /auth/refresh` — refresh token only, from the `refresh_token` cookie and/or the
`refresh_token` form field. JSON bodies are not read and `Authorization` is ignored, so an access
token can never refresh itself.

```bash
curl -s -X POST "$API/auth/refresh" --data-urlencode "refresh_token=$REFRESH_TOKEN"
```

The response is a `LoginResponse` (`message: "Token refreshed successfully"`) for the same scope and
project, with new cookies. `user_groups` contains consumers' groups with real hashes (empty for root
and admin), `project` has only `project_hash` and `project_name`, and consumers get `plan`.

Rotation rules:

1. The presented refresh token becomes `used`, and the family's previous access token stops
   working immediately.
2. Without `remember_me`, the family window restarts at 72 hours; with it, the original 30-day
   deadline is kept and `refresh_expires_in` shrinks.
3. Presenting the token that was **just** rotated again within the replay grace (default `10`
   seconds) returns `401 AUTH_1022` and leaves the family alive: the earlier refresh succeeded, so
   continue with its tokens (a browser already has them as cookies).
4. Presenting any older token, or the just-rotated one after the grace, is treated as theft:
   `401 AUTH_1015` and the whole family, including its current access token, is revoked. Later
   attempts get `401 AUTH_1017`.
5. The user's context is re-checked; if it no longer holds (inactive user, lost project access,
   inactive project), the family is revoked with `401 AUTH_1020`.

| Status | Code | When | Client action |
| --- | --- | --- | --- |
| `401` | `AUTH_1014` | No refresh token in cookie or form | Log in |
| `401` | `AUTH_1016` | Cookie and form values differ | Send one transport |
| `401` | `AUTH_1018` | An access token was sent as the refresh token | Send the refresh token |
| `401` | `AUTH_1019` | Refresh JWT expired | Log in |
| `401` | `AUTH_1013` | Unknown, tampered or otherwise invalid refresh token | Log in |
| `401` | `AUTH_1022` | Just-rotated token replayed within the grace | Use the newer pair; do not retry with this token |
| `401` | `AUTH_1015` | Reuse detected; family revoked | Clear credentials and log in |
| `401` | `AUTH_1017` | Family already revoked (logout, reuse, password reset, admin action) | Log in |
| `401` | `AUTH_1020` | User or project context no longer valid | Log in; contact an admin if it persists |

Client-side handling of these codes is in [refresh failures](errors.md#refresh-failures) and the
[client integration guide](client-authentication-guide.md#refresh-strategy).

## Switch project

`POST /auth/switch-project` — access token, plus the current refresh token of the **same** family
(cookie or `refresh_token` form field), plus form field `project_hash`.

```bash
curl -s -X POST "$API/auth/switch-project" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode "project_hash=$OTHER_PROJECT_HASH" \
  --data-urlencode "refresh_token=$REFRESH_TOKEN"
```

The switch rotates the family into a pair scoped to the new project (same `family_id`, same
`remember_me` mode) and sets new cookies. The same user-type rules as login apply: root may target
any active project, admins their assigned projects, consumers projects reachable through their
groups.

> [!IMPORTANT]
> Switching requires a **recent sign-in**: the session's `auth_time` must be at most 300 seconds
> old, or the session must have completed an OAuth reauth
> (`POST /auth/oauth/{connection}/reauth/start`) within that window. Refreshing and switching keep
> the original `auth_time`, so they never renew it. After the window, log in again with the target
> `project_hash` instead.

```jsonc
{
  "success": true,
  "message": "Successfully switched to project: Second Project",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_expires_in": 259200,
  "expires_at": "2026-09-24T12:19:00.105339Z",
  "refresh_expires_at": "2026-09-27T12:04:00.105339Z",
  "remember_me": false,
  "project": {"project_hash": "41AB...", "project_name": "Second Project", "project_description": null},
  "user_groups": ["user_proj-9c0d..."]
}
```

`SwitchProjectResponse` has no `user`, `accessible_projects` or `plan`, and `user_groups` holds
names.

| Status | Code | When |
| --- | --- | --- |
| `401` | `AUTH_1003` | Access token missing, expired or revoked |
| `401` | `AUTH_1008` | No recent sign-in or OAuth reauth |
| `401` | `AUTH_1014`, `AUTH_1016`, `AUTH_1022`, other refresh codes | Refresh token missing, from another family, or already rotated (see [Refresh the token pair](#refresh-the-token-pair)) |
| `403` | `AUTHZ_2003` | No access to the project, or project inactive or archived |
| `404` | `NF_4002` | Project not found |

## Log out

`POST /auth/logout` — access token only, no body.

```bash
curl -s -X POST "$API/auth/logout" -H "Authorization: Bearer $ACCESS_TOKEN"
```

```json
{"success": true, "message": "Logged out successfully"}
```

Logout revokes the caller's refresh family and its access session and clears the `session_token`
(`Path=/`) and `refresh_token` (`Path=/auth`) cookies. The user's other sessions are untouched.

The access token must still be valid: an expired or revoked one gets `401` before the handler runs,
and the family then stays alive until its refresh window ends. To log out an idle session, refresh
first and log out with the new access token.

## Validate an API key

`POST /auth/validate-api-key` — the user API key in `X-API-Key` (`sk_<public_id>.<secret>`), no
body. It is the API-key counterpart of `GET /auth/validate`, for services that receive a user's key
and need its owner, project and permissions. Keys are created and revoked through the
[API keys suite](api-keys/README.md).

```bash
curl -s -X POST "$API/auth/validate-api-key" -H "X-API-Key: $API_KEY"
```

```jsonc
{
  "success": true,
  "message": null,
  "valid": true,
  "auth_method": "api_key",
  "user": {"user_hash": "usr-3f6c...", "username": "alice", "email": "alice@example.com", "user_type": "consumer"},
  "project": {"project_hash": "9F2C...", "project_name": "My Project"},
  "api_key": {"key_id": "Qm9vbXNoYWth", "public_id": "Qm9vbXNoYWth"},
  "user_groups": ["user_proj-2b7c..."],
  "permissions": [],
  "plan": {"provider": "stripe", "state": "free", "active": false, "plan_code": null, "tier_code": null,
           "current_period_end": null, "trial_end": null, "cancel_at_period_end": false}
}
```

- Keys are always project-scoped, so `project` is set. `plan` is set for consumer-owned keys only.
- `permissions` comes from the owner's global roles for consumers; root and admin owners get fixed
  labels (`admin`, `global_admin` or `project_admin`).
- The raw key and its secret are never echoed; `api_key` holds only `key_id` and `public_id`.
- The response carries an `X-Auth-Process-Time` header.

| Status | `error.code` | When |
| --- | --- | --- |
| `400` | `VAL_3001` | Both `Authorization` and `X-API-Key` were sent (`error.message` is `ambiguous_credentials`) |
| `401` | `AUTH_1003` | Key missing, malformed, unknown, revoked or expired, or owner inactive; `error.message` ends with the specific code (`AUTH_1010`, `AUTH_1011`, `AUTH_1012`, `NF_4010`) |
| `403` | `AUTHZ_2001` | The key owner no longer has access to the key's project (message may end with `AUTHZ_2008`) |

The message suffixes are listed in [codes carried only in the message](errors.md#codes-carried-only-in-the-message).

## OAuth sign-in

Signing in through an external identity provider is documented in the [OAuth suite](oauth/README.md):
the project's backend mints a single-use `init_token` with `POST /auth/oauth/init` (user API key),
the browser posts it to `POST /auth/oauth/start`, and `GET /auth/oauth/callback` completes the
login. The callback returns the same `LoginResponse` and sets the same cookies as
`POST /auth/login`; only active consumer accounts can sign in this way. Everything on this page
(validation, refresh, switching, logout) then applies unchanged. The deprecated `/auth/google/*`
aliases run on the same pipeline; see the [Google OAuth suite](google-oauth/README.md).

## Session revocation

| Event | Revoked |
| --- | --- |
| `POST /auth/logout` | The caller's family |
| `POST /auth/password/change` | Every family of the user except the caller's; the caller's access token keeps working |
| Successful `POST /auth/password/reset` | Every family of the user |
| `POST /auth/email/verify` that changes the sign-in identity | Every family of the user |
| Refresh-token reuse outside the grace | That family |
| User deactivated, deleted, bulk-deactivated or bulk-deleted by an admin | Every family of the user |
| User type changed by root (any type-change route or bulk update) | Every family of the user |
| User group or project group deleted, project-group grant revoked, or project removed from a project group | Sessions whose project is no longer reachable |
| Context check fails on a later request (user inactive, project inactive or archived, user removed from the granting group, admin unassigned) | That family, at that request |

Email removal and primary-email changes also revoke the user's other sessions; see
[email management](users/email-management.md).

## Scenarios

### Sign in, call an API, refresh, log out

```bash
API=http://localhost:8000
LOGIN=$(curl -s -X POST "$API/auth/login" \
  --data-urlencode "username=alice" \
  --data-urlencode "password=$ALICE_PASSWORD" \
  --data-urlencode "project_hash=$PROJECT_HASH")
ACCESS_TOKEN=$(jq -r '.access_token' <<<"$LOGIN")
REFRESH_TOKEN=$(jq -r '.refresh_token' <<<"$LOGIN")

curl -s "$API/users/profile" -H "Authorization: Bearer $ACCESS_TOKEN"

# Rotate: both values change, and the old access token stops working at once.
REFRESHED=$(curl -s -X POST "$API/auth/refresh" --data-urlencode "refresh_token=$REFRESH_TOKEN")
ACCESS_TOKEN=$(jq -r '.access_token' <<<"$REFRESHED")
REFRESH_TOKEN=$(jq -r '.refresh_token' <<<"$REFRESHED")

curl -s -X POST "$API/auth/logout" -H "Authorization: Bearer $ACCESS_TOKEN"
```

### Work in two projects

Within 300 seconds of signing in, switch with the current pair:

```bash
SWITCHED=$(curl -s -X POST "$API/auth/switch-project" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  --data-urlencode "project_hash=$OTHER_PROJECT_HASH" \
  --data-urlencode "refresh_token=$REFRESH_TOKEN")
ACCESS_TOKEN=$(jq -r '.access_token' <<<"$SWITCHED")
REFRESH_TOKEN=$(jq -r '.refresh_token' <<<"$SWITCHED")
```

Later in the session the switch returns `401 AUTH_1008`; log in again with
`project_hash=$OTHER_PROJECT_HASH`. A client that needs both projects at once can hold one family
per project by logging in twice.

### Administer the platform

Root and admin dashboards that are not tied to one project use `/auth/platform/login` and refresh
the platform pair with `/auth/refresh` as usual. `GET /auth/validate` reports
`session.scope: "platform"` and `project: null` for these sessions.

### Detect a stolen refresh token

If an attacker and the legitimate client both hold the same refresh token, whichever presents it
second (after the grace) gets `401 AUTH_1015`, and the family is revoked for both. The legitimate
client must then log in again; the attacker's tokens are dead.

## Troubleshooting

| Symptom | Cause | Fix |
| --- | --- | --- |
| `400 VAL_3002` "Project identifier is required for login" | `/auth/login` without `project_hash` | Send `project_hash`; root and admin can use `/auth/platform/login` |
| `401 AUTH_1001` with a correct-looking email | The address is not activated for this account (for example the registration `email`) | Log in with the username, or add and activate the address |
| `401 AUTH_1001` for an account that used to work | Account deactivated, or password changed or reset | Check the account state as an admin; use password recovery |
| `403 AUTHZ_2003` on consumer login | No user group of the user reaches the project, or the project is inactive or archived | Check `GET /admin/user-groups/users/{user_hash}/groups` and `GET /admin/user-groups/{group_hash}/project-groups` ([groups suite](groups/README.md)) |
| `403 AUTHZ_2002` on platform login | The account is a consumer | Use `/auth/login` with a `project_hash` |
| Every protected call returns `401` right after a refresh | The client kept using the previous access token | Replace both tokens from every refresh or switch response |
| `401 AUTH_1014` from `/auth/refresh` | JSON body, or the refresh cookie was not sent (cookie path is `/auth`) | Send the `refresh_token` form field, or call the API at its root path so the cookie applies |
| `401 AUTH_1015`, then `AUTH_1017` | Two refreshes used the same token, or a token was replayed later | Serialize refreshes per family; log in again |
| `401 AUTH_1008` on switch-project | Sign-in older than the recent sign-in window | Log in again with the target `project_hash` |
| `401` on logout | Access token already expired | Refresh, then log out with the new access token |
| `401` right after an admin changed groups | The user no longer reaches the session's project, which revokes the session | Log in to a project the user can still reach |
| `429 INT_7005` on login | Failed-login bucket full | Wait for `Retry-After`; the window does not reset on success |
| Forgot password returns `202` but no email arrives | No activated address matches the identifier, or delivery is disabled or the email worker is not running | Confirm an activated address exists; check `EMAIL_DELIVERY_ENABLED` and the email worker ([email suite](email/README.md)) |

## Related

- [Getting started](getting-started.md) — configuration, first root, first project and user
- [Client integration guide](client-authentication-guide.md) — cookies, storage, refresh strategy, code
- [Error reference](errors.md) — envelope and code catalog
- [OAuth suite](oauth/README.md) — external identity sign-in, linking and reauth
- [API keys suite](api-keys/README.md) — key lifecycle and format
- [Users email management](users/email-management.md) — adding and activating addresses
- [Groups suite](groups/README.md) — how users reach projects
