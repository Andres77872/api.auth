# Google OAuth architecture

Google OAuth is a consumer-only sign-in path: Google authenticates the external identity,
`api.auth` authorizes local access and issues its own session. Since the provider-agnostic
pipeline landed, Google is one adapter among several; this page records what is specific
to Google and to the legacy BFF handshake behind `/auth/google/*`. The shared design
(state, PKCE and nonce, identity resolution, sessions) is in the
[OAuth request flow](../oauth/request-flow.md).

## Decisions

| Decision | Why |
| --- | --- |
| Scope is exactly `openid email` | The ID token's `sub` and `email` are all sign-in needs. No profile data, no offline access, no Google refresh token. |
| Identity is the HMAC of Google's `sub`, namespace `google` | E-mail is mutable and unsafe as a link key; the raw `sub` is never stored. Google's `sub` is the same for every client id, so a person is the same user at every project. |
| `email_verified` is a snapshot only | Local e-mail ownership is proven only by the local activation flow. |
| Successful sign-in reuses the local `LoginResponse` | `/auth/validate`, `/auth/refresh`, `/auth/logout` and project switching work unchanged; there is no parallel OAuth session model. |
| Endpoints are compiled in | A `google` connection can never point the server at configuration-supplied URLs. |
| Verification cross-checks `google-auth` | Local RS256/JWKS verification and the `google-auth` library must agree on the critical claims (can be switched off per database connection with `provider_params.google_auth_cross_check: false`). |
| The alias handshake is BFF-mediated (legacy) | The companion backend owned the project and group; the browser received only an opaque `provider_init_token`. `/auth/oauth/init` now makes the companion-side token store unnecessary. |
| Aliases keep their own activity codes | Existing dashboards and alerts on `act-cat-064..074` keep working. |

## Legacy BFF topology

```text
Browser/SPA
  | 1. asks the companion to start Google sign-in (no project_hash, no user_group_hash)
  v
Companion backend (magic-worlds-api in the original deployment)
  |-- reads project and group server-side
  |-- mints an opaque, single-use provider_init_token (lifetime <= 600 seconds)
  | 2. POST /auth/google/start {provider_init_token, redirect_uri, return_origin}
  v
api.auth
  |-- redeems the token server-to-server at the companion (bearer, no redirects)
  |-- validates provider, audience, project, return origin and lifetime
  |-- stores state, nonce and PKCE verifier in Redis (TTL <= 600 seconds)
  | 3. 303 Location: Google authorization URL, scope=openid email
  v
Google
  | 4. redirects to the companion's callback with code and state
  v
Companion backend
  | 5. GET /auth/google/callback?code&state (server-to-server)
  v
api.auth
  |-- consumes state, exchanges the code once with the PKCE verifier
  |-- verifies the ID token, applies the hosted-domain allow-list, drops Google tokens
  |-- resolves or creates the local consumer, checks access to the bound project
  | 6. LoginResponse + local session cookies
  v
Companion backend -> delivers its own session to the browser
```

Steps 3 to 6 are the shared pipeline; only steps 1 and 2 are specific to the alias. With
`/auth/oauth/*` the companion calls `init` with its project API key instead of minting and
redeeming a token.

## Storage boundaries

| Surface | Allowed | Forbidden |
| --- | --- | --- |
| Browser request and response | Opaque `provider_init_token`, the OAuth `state` in the redirect, the `oauth_state` cookie (a state fingerprint), local session cookies after success | Raw `project_hash`, raw `user_group_hash`, PKCE verifier, nonce, Google access, refresh and ID tokens |
| Redis | HMAC-keyed state records holding the nonce, PKCE verifier and the redeemed project binding, with short TTLs | Durable identity, Google tokens beyond the callback |
| Process memory | Google's JWKS, cached up to the configured cap | Secrets beyond one code exchange |
| MySQL | `user_external_accounts` with the `sub` HMAC, fingerprint, masked e-mail snapshot and link metadata | Google access, refresh or ID tokens, the authorization code, state, nonce, verifier |
| Audit, activity, logs | Reason codes, correlation ids, fingerprints, masked snapshots | Provider-init tokens, raw `sub` or e-mail, raw strict hashes, code, state, nonce, verifier, token material |

## Cookie boundary

The alias sets the short-lived `oauth_state` browser-binding cookie on path
`/auth/google`: HttpOnly, Secure, `SameSite=Lax` so the provider redirect can return with
it, and valued with a fingerprint of the state, never token material. It is checked at
the callback only when the browser sends it; behind a BFF the callback arrives
server-to-server without it. The local `session_token` and `refresh_token` cookies are the
ordinary ones.

## Provider boundary

Google may sign in and link. Patreon is entitlement and link only: its proof, webhook,
sync and S2S flows never issue local sessions (see
[Patreon account linking](../patreon-link/README.md)). Both store their identity key in
`user_external_accounts`, but only OAuth providers take part in the local session
lifecycle.
