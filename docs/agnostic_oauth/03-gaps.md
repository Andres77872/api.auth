# 03 — Gaps

Two kinds of gap are recorded here:

- **Part A — defects and incomplete behaviour in the current Google implementation.** These exist regardless of any redesign. They matter because a generalisation that copies the current route module would replicate them once per provider.
- **Part B — capability gaps between today and the goal** ("any project, any provider, configuration in the database").

Severity is the reviewer's estimate: **High** = security-relevant or a user-visible broken flow; **Medium** = correctness, operability or scalability; **Low** = hygiene.

## Part A — Defects and incomplete behaviour today

### G-01 (High) — The link flow cannot complete

`link/start` writes a record under the `google_oauth_link:` prefix and sends the browser to Google with that record's secret as the OAuth `state`. Google returns to the callback, which calls `consume_state`, which only looks under the `google_oauth_state:` prefix — so the callback answers `OAUTH_STATE_INVALID`. Separately, `link/finish` expects the consumed link record to contain a `claims` mapping, but no code path ever writes `claims` into a link record. The callback also never branches on `purpose`; every successful callback ends in `_issue_login_response`.

Net effect: an authenticated user with a password account cannot attach Google to it. With provisioning mode `both`, the only way to get a Google identity is auto-creation of a *new* user, so a person who registered by e-mail and later clicks "Sign in with Google" gets a second account (the e-mail collision is deliberately not merged).

### G-02 (High) — The re-authentication flow has no effect

`reauth/start` sends the user through Google with `prompt=login`, but the callback treats the return as a normal login, and `mark_recent_reauth` is never called from anywhere. `require_recent_reauthentication` therefore only ever passes on the token's `iat` / `auth_time` freshness. A Google-only user whose session is older than the recent-reauth window has no way to satisfy step-up for `unlink` or `link`.

### G-03 (High) — Test-runtime bypasses live inside the production route module

[auth_google.py](../../src/routes/auth_google.py) contains, in the production import path:

- `_consume_direct_test_state`, which accepts certain literal state strings and name prefixes (`security-…`, `state-for-…`) **without any Redis record**;
- `_exchange_code_once`, which on any exchange failure fabricates a token response when the `code` starts with `fake-google-auth-code`;
- `_verify_id_token`, which on any verification failure accepts a token ending in `fake-signature`;
- `_should_synthesize_success`, which can return a synthetic user with id `1` and a synthetic project with id `1`, for which a **real** token pair is then issued.

All four are gated only by `_test_runtime`, which is true when `APP_ENV` is a test name, **or** when `PYTEST_CURRENT_TEST` (or a `PYTEST_VERSION` containing `pytest`) is present in the process environment. The second condition is independent of `APP_ENV`: a production process that inherits that variable would accept forged callbacks. The likelihood is low; the impact is full authentication bypass, and the control is a single environment variable rather than a build-time or wiring-time separation. The redesign must not carry this pattern forward: test doubles belong in a fake adapter registered by test fixtures, not in branches of the request handler.

### G-04 (Medium) — Diagnostic `sub_reason` is silently discarded

`_issue_login_response` deliberately logs a precise `sub_reason` (`user_group_not_found`, `auto_create_disabled`, …) "for operators". `record_google_oauth_activity` passes details through `_safe_details`, whose allow-list does not contain `sub_reason`. The field never reaches the activity log, so the most common production failure (bound group hash not present after a database rebuild) remains undiagnosable from logs — the opposite of the stated intent.

### G-05 (Medium) — JWKS is effectively never cached

`verify_google_id_token` constructs a new `GoogleIDTokenVerifier` per call, and the JWKS cache is an instance attribute. Every callback therefore fetches Google's JWKS over the network, then `google-auth` fetches Google's certificates again for the cross-check. `GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS` and the `google_oauth_jwks:` Redis prefix exist but have no effect. That is two blocking outbound requests per login on top of the token exchange, and it multiplies with every additional provider.

### G-06 (Medium) — Blocking I/O inside async handlers

The JWKS fetch, the `google-auth` verification, all stored-procedure calls and the Redis calls run synchronously inside `async def` handlers. Only the provider-init redemption is moved to a thread. Under concurrent logins this stalls the event loop. A provider-agnostic design with more outbound calls (userinfo endpoints for non-OIDC providers) makes this worse unless adapters are async or consistently off-loaded.

### G-07 (Medium) — Forwarded client IP is trusted unconditionally

`_client_ip` takes the first `X-Forwarded-For` element from any caller. All per-IP rate limits and the stored `ip_hash` can be steered by a client that reaches `api.auth` directly. In the BFF topology the opposite problem appears: unless the BFF forwards the header, every user shares the BFF's address and one bucket.

### G-08 (Medium) — State binding cookie and `ip_hash` / `ua_hash` are written but never checked

`/start` sets an `oauth_state` cookie containing the state fingerprint and stores `ip_hash` and `ua_hash` in the state record. The callback never compares any of them. In the BFF topology the cookie would not even reach the callback (the BFF calls it server-to-server). Either the binding should be enforced where it is meaningful or removed; as it stands it gives a false impression of session-fixation protection.

### G-09 (Medium) — Provider error responses are collapsed

When Google returns `error=access_denied` (the user pressed "Cancel"), the callback answers `OAUTH_ID_TOKEN_INVALID` with `401`. The state is left unconsumed until TTL. A user cancelling consent is a normal outcome and deserves its own neutral code so consumers can show "sign-in cancelled" instead of a failure.

### G-10 (Medium) — Broad exception swallowing maps unrelated failures to misleading codes

`link/finish` maps **any** exception (expired session, Redis down, database error) to `EXTERNAL_IDENTITY_SUB_CONFLICT` `409`; `unlink` maps any exception to `EXTERNAL_IDENTITY_NOT_LINKED` `401`; `link/start` and `reauth/start` map any exception to `OAUTH_PROVISIONING_DENIED`. `_build_authorization_url` catches any builder failure — including "redirect URI is not allow-listed" and "config not ready" — and falls back to a second builder that performs no such checks.

### G-11 (Low) — Documentation drift

- The architecture doc states Workspace (`hd`) accounts are rejected; the code allows them unless an allow-list is configured.
- The usage docs draw a direct browser-to-`api.auth` flow; the deployed contract is BFF-mediated (see [01-current-state.md](01-current-state.md)).
- `GOOGLE_OAUTH_DEFAULT_USER_GROUP_HASH` is configurable and documented but unused.
- `GoogleOAuthStartResponse` is defined but the route always redirects.

### G-12 (Low) — Private cross-module imports

The Google router imports `_project_is_auth_accessible` and `_set_token_pair_cookies` (underscore-private) from the password-login router. A generic OAuth module would deepen that dependency; these belong in a shared session-issuance helper.

### G-13 (Low) — `capture_oauth_audit` is a no-op

It is called on the success path and documented as a seam, but does nothing. Either wire it or drop it before it is copied into N providers.

### G-14 (Medium) — E-mail collision is not detected; the covering test passes vacuously

The environment template states that "email collisions fail closed (require explicit link)". No code implements a collision check: neither the route nor `sp_create_consumer_user_from_external_account` looks for an existing user with the same e-mail. The new user is created with `users.email = NULL` and a `pending`, non-primary `user_emails` row, and the only uniqueness constraint on `user_emails` covers *activated* addresses, so the insert succeeds. The integration test named for this scenario asserts that the create procedure is not called — but the test environment pins provisioning mode to `disabled`, so the procedure is never reached for that reason, not because a collision was recognised.

The security-relevant half of the promise holds (accounts are never merged or linked by e-mail). The usability half does not: with auto-create on, a person who already has a password account silently receives a second, separate account when they use Google, and because of G-01 they cannot link instead.

## Part B — Capability gaps versus the goal

### G-20 — No place to store per-project provider configuration

`projects` has no settings column and there is no per-project settings table of any kind. Client id, client secret, scopes, endpoints, redirect URIs, return origins, hosted-domain restrictions, provisioning mode and default group all need a home. See [06-data-model.md](06-data-model.md).

### G-21 — No secrets-at-rest facility named for OAuth

The Fernet helper in the billing package is generic in behaviour but billing-named in module, key environment variables and error types. OAuth needs either a shared `secrets` module extracted from it or its own key set. Reusing billing's key for OAuth secrets would couple two unrelated rotation schedules.

### G-22 — No administrative API or UI for provider configuration

There is nothing comparable to the billing credentials endpoints: create/update/rotate/test/disable a connection, list connections for a project, view readiness. There is also no audit vocabulary for "OAuth connection changed".

### G-23 — No provider abstraction

No interface separates "what every provider must do" (build authorize URL, exchange code, produce a normalised identity) from "what Google does" (OIDC discovery, RS256 ID token, `hd` claim, `google-auth` cross-check). Non-OIDC providers (GitHub, Discord, Facebook Login classic) have no ID token at all and need a userinfo call; the current pipeline has no step where that could happen.

### G-24 — No provider registry and no discovery endpoint

A login page cannot ask "which providers are enabled for this project?". Each consumer hardcodes a Google button.

### G-25 — The companion handshake does not scale past one backend

One URL, one static bearer, outbound from `api.auth`. Needs either per-project registration (with SSRF controls) or, better, inversion so that the consumer authenticates *to* `api.auth`. See [05-target-architecture.md](05-target-architecture.md).

### G-26 — Trust model assumes the caller may speak for any project and any group

Findings F-26 and F-27. In a multi-tenant deployment the project must be derived from the caller's credential and the provisioning group from `api.auth`'s own configuration, never from caller-supplied hashes.

### G-27 — No just-in-time enrolment of an existing identity into a second project

Users are global. If a person auto-created through project A later signs in with the same Google account at project B, `_resolve_identity` finds the existing user and skips provisioning; the project-access check then fails with `OAUTH_PROJECT_ACCESS_DENIED` because the user is not in any group that reaches B. With one project this never happens. With two it is the *first* thing that happens. A per-project policy is needed: deny, or add the existing user to B's default group.

### G-28 — The identity key assumes a provider-global subject

`(provider, HMAC(sub))` is correct for Google, whose `sub` is the same for every client id. It is wrong for providers that issue **pairwise** subjects per client or per developer team (Microsoft Entra `sub`, Apple, Facebook app-scoped ids): the same person gets a different subject at each project's client, and conversely different issuers under one "provider" label (self-hosted Keycloak realms, Okta tenants, generic OIDC) can collide. The key needs an issuer/namespace dimension. See [04-research.md](04-research.md) and [06-data-model.md](06-data-model.md).

### G-29 — One active link per (user, provider)

`uk_external_accounts_user_provider` allows a user a single Google link. That is fine for Google. For generic OIDC it prevents a user from linking two different enterprise IdPs that share a provider *type*.

### G-30 — No topology for projects without a backend

Pure SPAs and mobile apps cannot mint provider-init tokens or receive the JSON callback. A hosted-callback mode with one-time-code delivery (the pattern the Magic Worlds BFF implements privately today) would have to be offered by `api.auth` itself.

### G-31 — Rate limits, activity types and audit tags have no provider or project dimension

Findings F-10, F-11, F-14, F-28. Operators cannot answer "how many failed Microsoft logins did project B have today?".

### G-32 — No per-provider claim mapping or e-mail trust policy

`email_verified` semantics differ by provider (Google: boolean and reliable; Apple: may arrive as a string; Microsoft: absent, and the `email` claim is tenant-admin-controlled and **must not** be trusted for identity; GitHub: needs a second API call for verified addresses). Today's validator would reject Apple outright for a non-boolean `email_verified`.

### G-33 — No consumer-side reference implementation

The provider-init issue/redeem contract, the delivery-code exchange, origin checks and replay markers are implemented once, inside `magic-worlds-api`, in roughly two thousand lines. A second project would have to reverse-engineer it. The shared `magic_auth_client` library only offers Google-named calls.

### G-34 — Schema rollout tooling is manual and three-way duplicated

New SQL files must be added to the ordered lists in [create_database.py](../../scripts/create_database.py), [recreate_database.py](../../scripts/recreate_database.py) and the test compose file, and to `PATCH_FILES` / `COLUMN_PATCHES` / `ENUM_PATCHES` in [schema_sync.py](../../scripts/schema_sync.py). There is no `ALTER TABLE` migration history. Converting the provider ENUM to a VARCHAR on a populated table is the first change in this repository that is not purely additive, and the static rollout test currently asserts that ENUM changes stay additive.
