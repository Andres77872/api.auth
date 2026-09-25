# 01 — Current State: How Google OAuth Works Today

This document describes the implementation as it exists in the repository at the time of the review. It is descriptive only; problems are catalogued in [02-findings-hardcoding.md](02-findings-hardcoding.md) and [03-gaps.md](03-gaps.md).

## 1. One-paragraph summary

`api.auth` implements a single, deployment-wide **Google OIDC authorization-code + PKCE** login. All configuration comes from process environment variables (`GOOGLE_OAUTH_*`, `PROVIDER_INIT_*`). The browser never tells `api.auth` which project it is logging in to; instead a **companion backend (BFF)** — today exclusively `magic-worlds-api` — mints an opaque *provider-init token*, and `api.auth` calls **one globally configured URL** on that BFF to "redeem" the token into a `project_hash` + `user_group_hash` binding. After Google returns, `api.auth` verifies the ID token, resolves (or auto-creates) a global consumer user by an HMAC of the Google `sub`, checks the user can reach the bound project, and issues the normal local token pair.

## 2. Component map

| Concern | Module | Notes |
| --- | --- | --- |
| Routes | [auth_google.py](../../src/routes/auth_google.py) | Router prefix `/auth/google`; six endpoints; also contains test-runtime synthetic paths. |
| Config | [google_oauth_config.py](../../src/Util/google_oauth_config.py) | Frozen dataclass `GoogleOAuthConfig` built from `os.environ` on every call to `load_google_oauth_config()`. |
| Env var names | [auth_constants.py](../../src/Util/auth_constants.py) | ~45 `GOOGLE_OAUTH_*` names, 3 `PROVIDER_INIT_*` names, Redis key prefixes `google_oauth_*`. |
| OAuth client | [oauth_clients.py](../../src/Util/oauth_clients.py) | Authlib registry with one client named `"google"`; deterministic authorize-URL builder; module-level singleton `google_oauth_client`. |
| State / nonce / PKCE | [oauth_state.py](../../src/Util/oauth_state.py) | Redis-only, HMAC-keyed, single-use (`GETDEL` + consumed marker), TTL capped at 600 s. |
| Provider-init redemption | [provider_init.py](../../src/Util/provider_init.py) | One outbound `POST` to `PROVIDER_INIT_REDEEM_URL` with static bearer `PROVIDER_INIT_REDEEM_TOKEN`. |
| ID-token verification | [google_id_token_verifier.py](../../src/Util/google_id_token_verifier.py) | RS256 + JWKS via PyJWT, claim checks, then a second verification through `google-auth`, and the two results must agree. |
| Rate limiting | [oauth_rate_limit.py](../../src/Util/oauth_rate_limit.py) | Redis buckets for start, callback, provider-init, state-consume, sub-collision, link-token, JWKS-fetch, unlink. |
| Project pinning | [auth_flow.py](../../src/Util/auth_flow.py) | `resolve_provider_init_bound_project` — never falls back to another accessible project. |
| Identity persistence | [db_external_accounts.py](../../src/Util/db/db_external_accounts.py) | Thin wrappers over five stored procedures. |
| Schema | [10_external_accounts.sql](../../schemas/tables/10_external_accounts.sql), [15_external_accounts.sql](../../schemas/stored_procedures/15_external_accounts.sql), [05_external_accounts_triggers.sql](../../schemas/triggers/05_external_accounts_triggers.sql) | `user_external_accounts` with `provider ENUM('google','patreon')`. |
| Session issuance | [auth_lifecycle.py](../../src/Util/auth_lifecycle.py) | `issue_project_token_pair` — identical to password login. |
| Activity catalog | [08_activity_logging_tables.sql](../../schemas/tables/08_activity_logging_tables.sql), [activity_logger.py](../../src/Util/activity_logger.py) | `google_oauth_*` activity types pinned to catalog ids `act-cat-064` … `act-cat-074`. |
| Audit / middleware | [api_audit_logger.py](../../src/Util/api_audit_logger.py), [auth_context.py](../../src/middleware/auth_context.py) | Path-based detection of `/auth/google/*`. |
| Existing docs | [Google OAuth usage docs](../USAGE/google-oauth/README.md), [runbook](../RUNBOOKS/google-oauth.md) | Describe a direct-browser topology; the deployed topology is BFF-mediated (see section 4). |

## 3. Endpoints

| Endpoint | Auth | What it does |
| --- | --- | --- |
| `POST /auth/google/start` | Public, rate limited | Validates body (`provider_init_token`, optional `redirect_uri`, `return_origin`, `remember_me`); rejects browser-supplied `project_hash` / `user_group_hash`; checks exact-match allow-lists; redeems provider-init; creates Redis state; returns `303` to Google. |
| `GET /auth/google/callback` | Public, rate limited | Consumes state **before** code exchange; exchanges code with PKCE verifier; verifies ID token; drops Google token material; resolves/creates user; pins project; returns `LoginResponse` JSON and sets session cookies. |
| `POST /auth/google/link/start` | Session + recent reauth | Creates a *link token* record and redirects to Google. |
| `POST /auth/google/link/finish` | Session + recent reauth | Consumes a link token and calls `sp_link_external_account`. See gap G-01: nothing populates the claims it expects. |
| `POST /auth/google/reauth/start` | Session | Starts a `prompt=login` round trip. See gap G-02: nothing records the reauth marker. |
| `DELETE /auth/google/unlink` | Session + recent reauth | Refuses if no usable password fallback; soft-unlinks; revokes sessions. |

## 4. Deployed topology ("Option B", BFF-mediated)

The usage docs draw the browser talking to `api.auth` directly. The environment template and the consumer code show the topology that is actually wired: `api.auth` sits entirely behind the consumer backend.

```text
SPA                      magic-worlds-api (BFF)                 api.auth                     Google
 |  POST /auth/provider-init/google  |                              |                           |
 |---------------------------------->| mint opaque token (Redis,    |                           |
 |<----------------------------------| digest key, TTL<=600, NX)    |                           |
 |  GET /auth/google/start/shim?pit= |                              |                           |
 |---------------------------------->| POST /auth/google/start ---->|                           |
 |                                   |<--- POST /internal/auth/provider-init/redeem (Bearer)    |
 |                                   |---- binding: project_hash, user_group_hash, origin ---->|
 |                                   |                              | state+nonce+PKCE -> Redis |
 |<----------- 303 Location: Google authorize URL -----------------|                           |
 |------------------------------------------------------------------------------------------->|
 |<---------------- 302 to BFF callback (registered redirect_uri) ----------------------------|
 |  GET /auth/google/callback/return?code&state                     |                           |
 |---------------------------------->| GET /auth/google/callback -->| code exchange ----------->|
 |                                   |                              |<--------- id_token -------|
 |                                   |<-------- LoginResponse ------| verify, resolve, issue    |
 |<-- 303 FRONTEND_RETURN?code=<one-time delivery code> + HttpOnly refresh cookie               |
 |  POST /auth/google/exchange {code}|                              |                           |
 |---------------------------------->| GETDEL delivery record       |                           |
 |<--------- sanitized session ------|                              |                           |
```

Consequences of this topology that matter for the redesign:

1. The `redirect_uri` registered at Google is the **BFF's** callback, not `api.auth`'s. `GOOGLE_OAUTH_REDIRECT_URIS` therefore lists consumer URLs.
2. `api.auth`'s callback returns JSON plus cookies to a **server**, not to a browser. The BFF owns browser delivery (one-time code, 120 s TTL).
3. `api.auth` must make an **outbound** HTTP call to the consumer during `/start`.
4. Client IP and User-Agent seen by `api.auth` are the BFF's unless it forwards headers; the `ip_hash` / `ua_hash` stored in state and every per-IP rate-limit bucket inherit that.
5. A project with no backend of its own (pure SPA, mobile app) cannot use this flow at all.

## 5. Step-by-step: login

### 5.1 Start

1. Parse JSON body; reject if it contains `project_hash` or `user_group_hash`.
2. `load_google_oauth_config()`; if `GOOGLE_OAUTH_ENABLED` is false return `OAUTH_PROVIDER_DISABLED`.
3. `redirect_uri` and `return_origin` default to the **first** entry of the global CSV lists and must exactly match an entry.
4. Rate-limit by IP and provider-init fingerprint.
5. `redeem_provider_init_token` posts `{provider_init_token, provider: "google", audience: "api.auth"}` to the single configured URL with the single configured bearer.
6. `validate_provider_init_binding` requires: `active`, `provider == "google"`, `audience == "api.auth"` when present, purpose in `{login, link, reauth, auto_create}`, non-empty `project_hash`, `return_origin` in the global allow-list and equal to the requested one, TTL at most 600 s.
7. `OAuthStateStore.create_state` writes `google_oauth_state:<hmac>` with nonce, PKCE verifier/challenge, the binding, `remember_me`, `ip_hash`, `ua_hash`.
8. Build authorize URL (`scope=openid email`, `S256`, no `access_type`, no `prompt=consent`) and answer `303` with an `oauth_state` cookie scoped to path `/auth/google`.

### 5.2 Callback

1. Rate-limit; atomically consume state (replay raises `OAUTH_STATE_REUSED`).
2. Exchange the code at the token endpoint through Authlib `fetch_access_token` with the stored verifier and `redirect_uri`.
3. Verify the ID token: header `alg == RS256` and `kid` present, JWKS lookup with one forced refetch, signature + `aud`, then `iss`, `azp`, `exp`, `iat`, `nonce`, optional hosted-domain allow-list, `sub` present, `email_verified` boolean. Then `google-auth` verifies again and critical claims must match.
4. Zero the token response variables.
5. `provider_sub_hmac = HMAC-SHA256(GOOGLE_OAUTH_PROVIDER_SUB_PEPPER, sub)`; same for e-mail with its own pepper; 12-char SHA-256 fingerprints for support.
6. `sp_get_user_by_external_account('google', hash)`; when found and an active consumer, touch last-seen.
7. Otherwise, when provisioning mode is `auto_create` or `both` **and** the binding carried a `user_group_hash` that resolves, `sp_create_consumer_user_from_external_account` creates the user, a pending non-primary e-mail row, the group membership and the external-account row in one transaction.
8. `resolve_provider_init_bound_project` requires the bound project to be in the user's accessible projects, and the project must be active and not archived.
9. `issue_project_token_pair`, set cookies, return `LoginResponse`.

## 6. Storage

| Store | Keys / rows | Content |
| --- | --- | --- |
| Redis | `google_oauth_state:<hmac32>` | State record incl. raw nonce, raw PKCE verifier, strict hashes. TTL at most 600 s. |
| Redis | `google_oauth_state_consumed:<hmac32>` | Replay marker, 600 s. |
| Redis | `google_oauth_link:<hmac32>` | Link-token record. |
| Redis | `google_oauth_reauth:<hmac32>` | Recent-reauth marker (never written today). |
| Redis | `google_oauth_rate:*` | Rate-limit buckets. |
| MySQL | `user_external_accounts` | `provider`, 32-byte subject HMAC, fingerprint, e-mail HMAC + mask, status, audit columns, JSON metadata. One active row per `(provider, subject)` and per `(user, provider)` enforced by generated columns. |
| MySQL | `activity_logs`, `api_audit_log` | Redacted events; `auth_method = 'oauth'`. |

No Google access, refresh or ID token is persisted anywhere. That property is worth preserving for login-only providers.

## 7. Configuration surface (names only)

Feature and client: `GOOGLE_OAUTH_ENABLED`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`, `GOOGLE_OAUTH_SCOPES` (validated to be exactly `openid email`).

Endpoints (defaults compiled in): `GOOGLE_OAUTH_DISCOVERY_URL`, `GOOGLE_OAUTH_AUTHORIZE_ENDPOINT`, `GOOGLE_OAUTH_TOKEN_ENDPOINT`, `GOOGLE_OAUTH_JWKS_URI`, `GOOGLE_OAUTH_ISSUERS`.

Allow-lists and policy: `GOOGLE_OAUTH_REDIRECT_URIS`, `GOOGLE_OAUTH_RETURN_ORIGINS`, `GOOGLE_OAUTH_ALLOWED_HOSTED_DOMAINS`, `GOOGLE_OAUTH_PROVISIONING_MODE` (`disabled` | `link_only` | `auto_create` | `both`), `GOOGLE_OAUTH_DEFAULT_USER_GROUP_HASH` (parsed, unused).

Timing: `GOOGLE_OAUTH_STATE_TTL_SECONDS`, `GOOGLE_OAUTH_LINK_TOKEN_TTL_SECONDS`, `GOOGLE_OAUTH_RECENT_REAUTH_SECONDS`, `GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS`, `GOOGLE_OAUTH_LEEWAY_SECONDS`.

Secrets: `GOOGLE_OAUTH_STATE_PEPPER`, `GOOGLE_OAUTH_PROVIDER_SUB_PEPPER`, `GOOGLE_OAUTH_EMAIL_HASH_PEPPER`, `GOOGLE_OAUTH_PASSWORDLESS_HASH_SECRET`, `GOOGLE_OAUTH_FAIL_CLOSED_ON_REDIS_ERROR`.

Companion handshake: `PROVIDER_INIT_REDEEM_URL`, `PROVIDER_INIT_REDEEM_TOKEN`, `PROVIDER_INIT_RETURN_ORIGINS`.

Rate limits: eight `GOOGLE_OAUTH_*_RATE_LIMIT` / `*_RATE_WINDOW_SECONDS` pairs.

Every one of these is a single value for the whole deployment. None of them is keyed by project, by provider, or stored in the database.

## 8. What is already good and should survive the redesign

- State consumed before code exchange; single-use with replay detection; Redis failure fails closed.
- PKCE S256 and nonce on every transaction; exact-match redirect and origin allow-lists (no prefix or wildcard matching).
- Identity keyed on provider subject, never on e-mail; e-mail collisions fail closed rather than merging accounts.
- Provider `email_verified` never activates the local e-mail.
- Provider tokens are discarded immediately; nothing provider-issued is stored for login.
- Project pinning: the callback can only ever issue a session for the project bound at start.
- Error codes are already provider-neutral (`OAUTH_*`, `EXTERNAL_IDENTITY_*`, `EXT_8010` … `EXT_8030`) with neutral public messages.
- Redaction discipline: fingerprints and masks only in logs, activity and audit.
