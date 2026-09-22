# Google OAuth/OIDC Usage Guide (Deprecated Aliases)

> **Deprecated.** `/auth/google/*` now delegates to the provider-agnostic OAuth
> pipeline with the connection key `google`. The routes are still registered and
> still served, and FastAPI marks all five `deprecated=True` in the OpenAPI
> document. New integrations should use the **[OAuth suite](../oauth/README.md)**
> and the `/auth/oauth/*` routes, which reach Google plus GitHub, Discord,
> Microsoft and generic OIDC from the same contract.
>
> This suite remains the reference for the Google-specific alias behavior: the
> `GOOGLE_OAUTH_*` environment configuration that is still authoritative while
> `OAUTH_CONFIG_SOURCE=env`, the provider-init redemption contract, and the
> `act-cat-064..074` activity codes the aliases emit.

Operator and integrator index for the consumer-only Google OAuth/OIDC login
surface in `api.auth`.

This guide is intentionally strict. Google OAuth is an additive login path that
reuses the existing local project-scoped session lifecycle; it is **not** a
replacement identity system and it is **not** a place to leak project/group scope.

> Provider boundary: Google may login/link and can issue the existing local
> `LoginResponse` after OAuth/OIDC plus local authorization succeeds. Patreon is
> entitlement/link only, never starts a local login/session, and is documented
> separately in [Patreon account linking](../patreon-link/README.md).

## Quick Navigation

| Document | Purpose |
| --- | --- |
| [OAuth suite](../oauth/README.md) | **Canonical** provider-agnostic sign-in: `/auth/oauth/*`, database-backed connections and project bindings, readiness checks. |
| [Architecture](architecture.md) | Decisions, data flow, storage boundaries, identity tree, and session reuse. |
| [Request Flow](request-flow.md) | Start, callback, link, reauth, unlink, success/failure surfaces, and cookie notes. |
| [Scenarios](scenarios.md) | Returning user, auto-create, collision/ATO block, Workspace denial, project denial, unlink refusal, outage. |
| [Troubleshooting](troubleshooting.md) | State replay, nonce mismatch, JWKS `kid` miss, token exchange, provider-init, redirects, Redis fail-closed. |
| [Reference](reference.md) | Env vars, endpoints, models, `EXT_8xxx` errors, `act-cat-064..074`, redaction, exact allowlists. |

## Route Status

| Route | Method | Provider-agnostic equivalent |
| --- | --- | --- |
| `/auth/google/start` | POST | `POST /auth/oauth/start` |
| `/auth/google/callback` | GET | `GET /auth/oauth/callback` |
| `/auth/google/link/start` | POST | `POST /auth/oauth/{connection}/link/start` |
| `/auth/google/reauth/start` | POST | `POST /auth/oauth/{connection}/reauth/start` |
| `/auth/google/unlink` | DELETE | `DELETE /auth/oauth/{connection}/link` |

The aliases keep their original request and response shapes. The difference is
where configuration comes from: the aliases read the `GOOGLE_OAUTH_*`
environment, while `/auth/oauth/*` resolves a connection and a project binding
from the database. Identity storage is shared, so an account linked through an
alias resolves identically through the agnostic routes and the reverse.

## Scope and Token-Minimization Rules

- Google authorization requests use **scope = `openid email`** only.
- The flow must not request `profile`, `offline_access`, `access_type=offline`, or Google refresh-token consent.
- Google authorization `code`, Google `access token`, Google `refresh token`, and Google `id token` material are **not persisted** in MySQL, durable audit, activity rows, browser-visible responses, cookies, or logs.
- The Google ID token is validated, reduced to sanitized claims, and discarded before local identity/session work continues.
- Successful login returns the existing local `LoginResponse` shape and existing `session_token` / `refresh_token` cookies. Those are `api.auth` local session tokens, not Google tokens.

## Provider-Init Contract

The alias flow is BFF-mediated: a companion backend holds the strict scope and
issues an opaque `provider_init_token` for the browser. `magic-worlds-api` is the
companion in the original deployment and is used as the example name throughout
this suite; any backend can fill the role, and nothing in `api.auth` is bound to
that name.

The browser may send only:

```json
{
  "provider_init_token": "REPLACE_ME_OPAQUE_LOCAL_TOKEN",
  "redirect_uri": "http://localhost:8000/auth/google/callback",
  "return_origin": "http://localhost:3000"
}
```

Strict `project_hash` and `user_group_hash` values stay server-side between the
companion backend and `api.auth`. They must not appear in browser URLs, request
bodies, response bodies, cookies, headers, logs, audit records, or activity details.

Provider-init tokens are:

- opaque random values,
- single-use,
- TTL-limited to no more than `600` seconds,
- bound to provider `google`, purpose, target project, optional user group, return origin, issuer, and audience,
- not privilege grants; local project/group authorization still runs after Google identity succeeds.

The provider-agnostic `/auth/oauth/init` route replaces this handshake: the
project backend calls `api.auth` directly with its project API key and receives a
300-second `init_token`, so no companion-side provider-init store is needed. A
backend that still redeems provider-init tokens can be bridged per binding with
`PUT /admin/oauth/projects/{project_hash}/bindings/{connection_key}/legacy-redeem`.

### Companion in-memory limitation

The companion provider-init store in the original deployment is in-memory:
process-local, cleared on restart, and not shared across replicas. Multi-instance
deployments require sticky routing or a shared store before production traffic
can rely on it. This limitation belongs to the companion, not to `api.auth`, and
it disappears with `/auth/oauth/init`.

## Provisioning Modes

While `OAUTH_CONFIG_SOURCE=env`, `GOOGLE_OAUTH_PROVISIONING_MODE` selects the mode
for the whole deployment:

| Mode | Behavior |
| --- | --- |
| `disabled` | Google OAuth is effectively off. No local account creation or linking. Safe default. |
| `link_only` | Existing local consumers can link Google after recent reauth/proof. No auto-create. Recommended first staging/production mode. |
| `auto_create` | New eligible Google consumers can be created only from provider-init-bound project/group scope. No client-selected group. |
| `both` | Linking and auto-create are both enabled. Treat as highest-risk rollout mode. |

Production defaults must remain `disabled` or `link_only`; `auto_create`/`both`
require an explicit operational decision.

Under `OAUTH_CONFIG_SOURCE=db` the same four modes are set **per project binding**
instead, so one project can stay `link_only` while another runs `both`. The
binding also carries the default user group that auto-create provisions into, and
`auto_create`/`both` are refused unless that group actually reaches the project.

## Local Email Activation Boundary

Google `email_verified` is stored only as an external-account snapshot. It must not activate, primary-mark, recover, or otherwise authorize a local email address.

When auto-create stores a local email row, that row remains **pending** until the existing local email activation flow succeeds. Pending local email must not grant login or password recovery authority.

## Responsibility Split

The companion backend owns:

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
