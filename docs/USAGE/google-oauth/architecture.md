# Google OAuth Architecture

Google OAuth/OIDC is an additive, consumer-only authentication path. It validates Google identity, then hands control back to the existing `api.auth` local identity, project access, session, audit, and refresh-token lifecycle.

## Architecture Decisions

| Decision | Why |
| --- | --- |
| Provider-init is issued by `magic-worlds-api` as an opaque token | The companion already owns strict project/group scope. The browser must not receive raw `project_hash` or `user_group_hash`. |
| OAuth state is Redis-only | State, nonce, and PKCE verifier are ephemeral security material. Redis provides TTL and atomic consume; MySQL is for durable identity, not temporary OAuth state. |
| Google identity authority is provider `sub`, stored as HMAC | Email is mutable and unsafe for primary linking. Raw provider `sub` is not persisted. |
| Local email activation remains authoritative | Google `email_verified` is a snapshot only and must not activate local email. |
| Successful Google login reuses local `LoginResponse` | Existing `/auth/validate`, `/auth/refresh`, `/auth/logout`, cookies, and project-scoped session semantics stay consistent. |
| Activity fits `act-cat-064..074` | Keeps audit/activity catalog drift under control and uses generic `auth_method='oauth'`. |

## System Data Flow

```text
Browser/SPA
  |
  | 1. POST /auth/provider-init/google
  |    body contains no project_hash/user_group_hash
  v
magic-worlds-api BFF
  |-- reads strict project/group scope server-side
  |-- creates opaque provider_init_token, single-use, TTL <= 600 seconds
  |-- audit owner for issuance
  |
  | 2. returns provider_init_token only
  v
Browser/SPA
  |
  | 3. POST http://localhost:8000/auth/google/start
  |    provider_init_token + localhost redirect/return origin
  v
api.auth
  |-- redeems provider_init_token server-to-server
  |-- validates provider/purpose/audience/return origin
  |-- creates Redis state, nonce, PKCE verifier
  |-- redirects to Google with scope=openid email
  v
Google Authorization Server
  |
  | 4. GET /auth/google/callback?code=<opaque>&state=<random>
  v
api.auth
  |-- consumes state before code exchange
  |-- exchanges code once using PKCE verifier
  |-- validates ID token using RS256/JWKS + google-auth cross-check
  |-- rejects Workspace hd accounts
  |-- discards Google token material
  |-- resolves or creates local consumer according to policy
  |-- checks group-derived access to provider-init-bound project
  |-- issues local token pair and existing cookies
  v
Existing local session lifecycle
```

## Storage Boundaries

| Surface | Allowed | Forbidden |
| --- | --- | --- |
| Browser request/response | opaque `provider_init_token`, random OAuth `state`, local session cookies after success | raw `project_hash`, raw `user_group_hash`, Google code verifier, nonce, access token, refresh token, id token |
| Redis | HMAC-keyed OAuth state, raw nonce, raw PKCE verifier, strict binding from provider-init, short TTL | durable identity authority, Google tokens past callback processing |
| MySQL | `user_external_accounts` with provider-sub HMAC, masked email snapshot, link/unlink metadata | Google access token, Google refresh token, Google id token, authorization code, state, nonce, code verifier |
| Audit/activity/logs | redacted reason, correlation ID, fingerprints, masked snapshots | provider-init token, raw Google subject/email, raw strict hashes, OAuth code/state/nonce/verifier/token material |

## Identity Decision Tree

```text
valid state + valid ID token?
  no  -> neutral EXT_8xxx failure; no identity mutation
  yes -> Workspace hd present?
           yes -> neutral consumer-only denial
           no  -> active provider-sub link exists?
                    yes -> returning linked consumer path
                    no  -> email-only collision?
                             yes -> block ATO; require credential-first local proof before linking
                             no  -> provisioning mode allows auto_create/both and provider-init group exists?
                                      yes -> create consumer + pending local email + external link
                                      no  -> neutral provisioning denial
```

Every successful branch still verifies access to the provider-init-bound project. A provider-init token never overrides group-derived project authorization.

## Why Local Session Issuance Is Reused

Google authenticates the external identity; `api.auth` authorizes local access.

After a successful callback, route code reuses:

1. local project access resolution,
2. `issue_project_token_pair(...)`,
3. `_set_token_pair_cookies(...)`,
4. the existing `LoginResponse`,
5. existing `session_token` and `refresh_token` cookie names.

This avoids a parallel OAuth session model. `/auth/validate`, `/auth/refresh`, `/auth/logout`, and project switching continue to operate on local JWT/session state. Google access, refresh, and id token material is not persisted and is not needed after local session issuance.

## Cookie Boundary

- The short-lived OAuth transaction binding uses `SameSite=Lax` so browser redirects can complete.
- Existing local `session_token` and `refresh_token` cookies are unchanged by this change.
- No `__Host-` cookie rename is introduced here.

## Companion Provider-Init Limitation

The current `magic-worlds-api` provider-init implementation is in-memory. It is process-local, cleared on restart, and not safe across multiple stateless replicas unless routing is sticky or the store is replaced by a shared backend.

## Residual Verification Caveats

- Full-stack local e2e has a known `/auth/validate` caveat for OAuth-issued synthetic tokens until the test DB migration/session-validation path is resolved.
- Trigger installation may be skipped on local MySQL when the test user lacks binlog trigger privileges; source/bootstrap validation still covers trigger definitions.
- Pre-existing admin project-auth test failures are outside the Google OAuth docs scope.
