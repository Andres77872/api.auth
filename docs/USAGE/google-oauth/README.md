# Google OAuth/OIDC Usage Guide

Operator and integrator index for the consumer-only Google OAuth/OIDC login surface in `api.auth`.

This guide is intentionally strict. Google OAuth is an additive login path that reuses the existing local project-scoped session lifecycle; it is **not** a replacement identity system and it is **not** a place to leak project/group scope.

> Provider boundary: Google may login/link and can issue the existing local `LoginResponse` after OAuth/OIDC plus local authorization succeeds. Patreon is entitlement/link only, never starts a local login/session, and is documented separately in [Patreon account linking](../patreon-link/README.md).

## Quick Navigation

| Document | Purpose |
| --- | --- |
| [Architecture](architecture.md) | Decisions, data flow, storage boundaries, identity tree, and session reuse. |
| [Request Flow](request-flow.md) | Start, callback, link, reauth, unlink, success/failure surfaces, and cookie notes. |
| [Scenarios](scenarios.md) | Returning user, auto-create, collision/ATO block, Workspace denial, project denial, unlink refusal, outage. |
| [Troubleshooting](troubleshooting.md) | State replay, nonce mismatch, JWKS `kid` miss, token exchange, provider-init, redirects, Redis fail-closed. |
| [Reference](reference.md) | Env vars, endpoints, models, `EXT_8xxx` errors, `act-cat-064..074`, redaction, exact allowlists. |
| [Runbook](../../RUNBOOKS/google-oauth.md) | Rollout, kill switch, staging `link_only`, auto-create gates, secret rotation, rollback. |
| [External Account Schema](../../../schemas/docs/external-accounts.md) | `user_external_accounts`, HMAC provider-sub authority, no-token columns, link/unlink semantics. |
| [Patreon Account Linking](../patreon-link/README.md) | Entitlement/link-only provider model; no local login/session authority. |

## Scope and Token-Minimization Rules

- Google authorization requests use **scope = `openid email`** only.
- The flow must not request `profile`, `offline_access`, `access_type=offline`, or Google refresh-token consent.
- Google authorization `code`, Google `access token`, Google `refresh token`, and Google `id token` material are **not persisted** in MySQL, durable audit, activity rows, browser-visible responses, cookies, or logs.
- The Google ID token is validated, reduced to sanitized claims, and discarded before local identity/session work continues.
- Successful login returns the existing local `LoginResponse` shape and existing `session_token` / `refresh_token` cookies. Those are `api.auth` local session tokens, not Google tokens.

## Provider-Init Contract

`magic-worlds-api` is the BFF that issues an opaque `provider_init_token` for the browser.

The browser may send only:

```json
{
  "provider_init_token": "REPLACE_ME_OPAQUE_LOCAL_TOKEN",
  "redirect_uri": "http://localhost:8000/auth/google/callback",
  "return_origin": "http://localhost:3000"
}
```

Strict `project_hash` and `user_group_hash` values stay server-side between `magic-worlds-api` and `api.auth`. They must not appear in browser URLs, request bodies, response bodies, cookies, headers, logs, audit records, or activity details.

Provider-init tokens are:

- opaque random values,
- single-use,
- TTL-limited to no more than `600` seconds,
- bound to provider `google`, purpose, target project, optional user group, return origin, issuer, and audience,
- not privilege grants; local project/group authorization still runs after Google identity succeeds.

### Companion in-memory limitation

The current companion provider-init store is in-memory: process-local, cleared on restart, and not shared across replicas. Multi-instance deployments require sticky routing or a future shared store before production traffic can rely on it.

## Provisioning Modes

`GOOGLE_OAUTH_PROVISIONING_MODE` supports:

| Mode | Behavior |
| --- | --- |
| `disabled` | Google OAuth is effectively off. No local account creation or linking. Safe default. |
| `link_only` | Existing local consumers can link Google after recent reauth/proof. No auto-create. Recommended first staging/production mode. |
| `auto_create` | New eligible Google consumers can be created only from provider-init-bound project/group scope. No client-selected group. |
| `both` | Linking and auto-create are both enabled. Treat as highest-risk rollout mode. |

Production defaults must remain `disabled` or `link_only`; `auto_create`/`both` require an explicit operational decision.

## Local Email Activation Boundary

Google `email_verified` is stored only as an external-account snapshot. It must not activate, primary-mark, recover, or otherwise authorize a local email address.

When auto-create stores a local email row, that row remains **pending** until the existing local email activation flow succeeds. Pending local email must not grant login or password recovery authority.

## Companion Responsibilities

`magic-worlds-api` owns:

1. public provider-init issuance,
2. server-side reading of strict project/group scope,
3. provider-init issuance audit,
4. returning only `provider_init_token`, `expires_in`, and `provider` to the browser,
5. keeping strict hashes and Google tokens out of browser-visible surfaces.

`api.auth` owns:

1. server-to-server provider-init redemption,
2. OAuth state/nonce/PKCE storage in Redis,
3. Google ID-token validation,
4. external-account resolution/link/create/unlink,
5. local project-scoped session issuance,
6. OAuth audit/activity/error taxonomy.

## Known Residual Verification Caveats

- Full-stack e2e currently reaches callback success, but `/auth/validate` has a residual local test caveat for OAuth-issued synthetic tokens until the test DB migration/session-validation path is resolved.
- Local MySQL test DB trigger installation can be skipped when binary logging requires trigger privileges the test user does not have; source/bootstrap validation still covers trigger SQL.
- Existing admin project-auth regression failures are pre-existing and not owned by the Google OAuth docs phase.

## Manual Smoke

Use [`../../../test_google_oauth.http`](../../../test_google_oauth.http) only with fake/local values. Never paste real Google tokens, real client credentials, raw strict hashes, or production origins into that file.
