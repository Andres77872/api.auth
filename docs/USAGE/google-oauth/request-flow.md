# Google OAuth Request Flow

All examples use localhost-only placeholders. Do not paste real Google codes, tokens, client credentials, raw `project_hash`, raw `user_group_hash`, or production origins into docs or smoke files.

## Route Family

| Endpoint | Auth | Purpose |
| --- | --- | --- |
| `POST /auth/google/start` | Public, rate-limited | Redeem provider-init and redirect to Google. |
| `GET /auth/google/callback` | Public redirect, rate-limited | Consume state, exchange code, validate ID token, issue local session. |
| `POST /auth/google/link/start` | Existing local session + recent reauth | Start a Google link flow for a local consumer. |
| `POST /auth/google/link/finish` | Existing local session + recent reauth | Finish linking by consuming an OAuth link token. |
| `POST /auth/google/reauth/start` | Existing local session | Start Google step-up/reauth round-trip. |
| `DELETE /auth/google/unlink` | Existing local session + recent reauth | Soft-unlink Google if fallback auth exists. |

> Unlike `link/start`, the `reauth/start` handler is **not** gated by provisioning mode and does **not** pre-require recent reauth (`require_recent_reauthentication`); it only initiates a Google step-up round-trip (`prompt=login`). Any failure returns `OAUTH_PROVISIONING_DENIED` / `EXT_8024` (`401`). The `link/start` and `link/finish` handlers both call `require_recent_reauthentication` (op `google_oauth_link`) and require provisioning mode `link_only`/`both`.

## Login Start

```text
Browser -> magic-worlds-api
  POST /auth/provider-init/google
  no strict hashes in request

magic-worlds-api -> Browser
  provider_init_token only

Browser -> api.auth
  POST /auth/google/start
  provider_init_token, redirect_uri, return_origin

api.auth -> magic-worlds-api
  server-to-server redeem with bearer trust boundary

api.auth -> Redis
  state + nonce + PKCE verifier, TTL <= 600 seconds

api.auth -> Browser
  303 Location: Google authorization URL
```

Start request body:

```json
{
  "provider_init_token": "REPLACE_ME_OPAQUE_LOCAL_TOKEN",
  "redirect_uri": "http://localhost:8000/auth/google/callback",
  "return_origin": "http://localhost:3000",
  "remember_me": false
}
```

The Google authorization URL includes:

- `response_type=code`
- `scope=openid email`
- `state=<random>`
- `nonce=<random>`
- `code_challenge=<S256 verifier challenge>`
- `code_challenge_method=S256`

It must not include `profile`, `offline_access`, `access_type=offline`, or refresh-token consent parameters.

## Callback

```text
Google -> api.auth
  GET /auth/google/callback?code=<opaque>&state=<random>

api.auth
  1. audit callback with redacted query
  2. rate-limit callback/state consume
  3. consume Redis state before code exchange
  4. exchange code once with PKCE verifier
  5. validate ID token: RS256, JWKS, iss, aud, azp, exp/iat, nonce, no hd
  6. discard token response and raw id token
  7. resolve local consumer by provider-sub HMAC
  8. enforce provisioning and project access policy
  9. issue existing local token pair and cookies
```

Success surface:

- Existing `LoginResponse` shape.
- Existing `session_token` access cookie and `refresh_token` cookie.
- Local session tokens only; Google access, refresh, and id token material is not persisted or returned.

Failure surface:

- Neutral `EXT_8xxx` response.
- Optional correlation ID.
- No account existence, provider-sub ownership, project/group membership, strict hash, Google token, code, state, nonce, or verifier disclosure.

## Link Existing Local Account

```text
Authenticated consumer + recent reauth
  -> POST /auth/google/link/start
  -> Google round-trip
  -> POST /auth/google/link/finish with oauth_link_token/state
  -> sp_link_external_account(...)
```

Linking is allowed only when provisioning mode is `link_only` or `both`. The Google provider-sub must not already be actively linked to another user. Google `email_verified` does not activate local email.

## Reauth / Step-up

`POST /auth/google/reauth/start` starts a Google round-trip for operations that require recent proof. The implementation may request `prompt=login`; it still must not request `offline_access`, `access_type=offline`, or Google refresh tokens.

Recent reauth applies consistently to sensitive operations regardless of whether the original local session was created by password login or Google OAuth.

## Unlink

```text
Authenticated consumer + recent reauth
  -> DELETE /auth/google/unlink
  -> verify fallback auth method exists
  -> sp_unlink_external_account(status='unlinked')
  -> revoke affected local auth state
  -> ExternalIdentityUnlinkResponse
```

If Google is the only usable auth method, unlink is refused until fallback local authentication exists. The response must not expose raw provider identifiers.

## Cookie and Session Notes

- OAuth transaction cookie: short-lived, `SameSite=Lax`, no Google token material.
- Local session cookies: existing `session_token` and `refresh_token` names/semantics.
- `/auth/google/start` and `/auth/google/callback` skip normal session extraction in `AuthContextMiddleware`, but API audit remains active and records `auth_method='oauth'`.

## No Strict-Hash Browser Leakage

Never send these fields from the browser to `api.auth`:

```json
{
  "project_hash": "<do-not-send>",
  "user_group_hash": "<do-not-send>"
}
```

If a browser payload contains those fields, route handling must reject or ignore them safely and must not create OAuth state from them.
