# Google OAuth (deprecated aliases)

> [!IMPORTANT]
> `/auth/google/*` is deprecated. The five routes are still served (OpenAPI marks them
> `deprecated`) and delegate to the provider-agnostic OAuth pipeline with the connection
> key `google`. New integrations use the [OAuth suite](../oauth/README.md): `init` from the
> backend with a project API key, then `/auth/oauth/start` and `/auth/oauth/callback`.

This suite covers only what is specific to the aliases and to Google: the legacy
provider-init handshake of `POST /auth/google/start`, the `GOOGLE_OAUTH_*` environment
configuration used while `OAUTH_CONFIG_SOURCE=env`, the `act-cat-064..074` activity codes,
and the Google scope and token rules. Everything else — state, PKCE and nonce handling,
login, link, reauth and unlink, error codes, rate limits — is the shared pipeline
documented in the OAuth suite.

## Route status

| Alias | Method | Provider-agnostic equivalent |
| --- | --- | --- |
| `/auth/google/start` | POST | `POST /auth/oauth/init` (backend) + `POST /auth/oauth/start` |
| `/auth/google/callback` | GET | `GET /auth/oauth/callback` |
| `/auth/google/link/start` | POST | `POST /auth/oauth/google/link/start` |
| `/auth/google/reauth/start` | POST | `POST /auth/oauth/google/reauth/start` |
| `/auth/google/unlink` | DELETE | `DELETE /auth/oauth/google/link` |

What differs from `/auth/oauth/*`:

- `start` takes an opaque `provider_init_token` minted by a companion backend and redeems
  it server-to-server, instead of an init token minted by `api.auth`.
- The callback is `GET` only, has no `iss` parameter and ignores `error_description`.
- Link, reauth and unlink always use the `google` binding of the session's project.
- The `oauth_state` cookie is scoped to path `/auth/google`.
- Activity uses the `google_oauth_*` types `act-cat-064..074`; reauth and cancellation
  use the generic `oauth_reauth_succeeded` and `oauth_user_cancelled`.
- `OAUTH_ENABLED` is not checked by the alias `start`; the Google connection's own switch
  is (`GOOGLE_OAUTH_ENABLED` under the environment source, the catalog, connection and
  binding under the database source).

Identity storage, sessions and state are shared: an account linked through an alias
signs in through `/auth/oauth/*` and the reverse, and a round trip started on one route
family can finish on the other's callback.

## Scope and token-minimization rules

- Google authorization requests use **scope = `openid email`** only. Both the
  environment configuration and a database connection of type `google` refuse any other
  scope.
- The flow must not request `profile`, `offline_access`, `access_type=offline`, or Google refresh-token consent.
- The Google authorization `code`, Google `access token`, Google `refresh token` and Google
  `id token` are **not persisted**: not in MySQL, audit, activity, responses, cookies or
  logs.
- The ID token is verified (RS256, `kid`, issuer, audience, `azp`, expiry, nonce, hosted
  domain, and a `google-auth` cross-check), reduced to its claims, and discarded before
  any identity or session work.
- A successful login returns the ordinary local `LoginResponse` and the local
  `session_token` / `refresh_token` cookies. Those are `api.auth` tokens, never Google's.

## Provider-init contract

The alias handshake is BFF-mediated: a companion backend holds the project and group
server-side and gives the browser only an opaque `provider_init_token`.
`magic-worlds-api` is the companion in the original deployment and is used as the example
name in this suite; any backend can fill the role, and nothing in `api.auth` depends on
that name.

The start request may carry only:

```json
{
  "provider_init_token": "REPLACE_ME_OPAQUE_LOCAL_TOKEN",
  "redirect_uri": "http://localhost:5000/auth/google/callback/return",
  "return_origin": "http://localhost:3000",
  "remember_me": false
}
```

Strict `project_hash` and `user_group_hash` values stay server-side between the companion
backend and `api.auth`. They must not appear in browser URLs, request bodies, response
bodies, cookies, headers, logs, audit records or activity details; a start body that
contains either is rejected with `400` `EXT_8012`.

Provider-init tokens are opaque random values, minted and made single-use by the
companion. For each start request `api.auth` makes one server-to-server redeem call and
accepts the answer only if it is active and names provider `google`, audience `api.auth`
(when present), a known
purpose, a `project_hash`, the return origin being used, and a lifetime of no more than
`600` seconds. A provider-init token is not a privilege grant: the user's group-derived
access to the project is still checked after Google identity succeeds. The redemption
fields are in the [reference](reference.md#provider-init-redemption).

Under `OAUTH_CONFIG_SOURCE=db` the redeemed project and group must equal the binding's own
project and default group, or the start is refused. The provider-agnostic `init` route
replaces this handshake entirely: the project comes from the backend's API key and the
group from the binding, so no companion-side token store is needed.

The companion's provider-init store in the original deployment is in-memory: process-local,
cleared on restart and not shared across replicas. Multi-instance deployments need sticky
routing or a shared store. This limitation belongs to the companion, not to `api.auth`,
and disappears with `/auth/oauth/init`.

## Provisioning modes

| Mode | Behavior |
| --- | --- |
| `disabled` | No account is created or linked through Google. The default. |
| `link_only` | Existing local consumers can link Google (with recent authentication) and then sign in with it. No auto-create. The recommended first mode. |
| `auto_create` | New Google identities become local consumers in the provisioning group. No client-selected group. |
| `both` | Linking and auto-create. The highest-risk mode. |

While `OAUTH_CONFIG_SOURCE=env`, `GOOGLE_OAUTH_PROVISIONING_MODE` sets the mode for the
whole deployment and auto-create uses the group named in the redeemed provider-init
token. Under `OAUTH_CONFIG_SOURCE=db` the mode and the default user group are set per
project binding, and `auto_create`/`both` are refused unless that group is active and
reaches the project. Start new deployments at `disabled` or `link_only`; enable
`auto_create` or `both` deliberately.

## Local email activation boundary

Google `email_verified` is stored only as a snapshot on the external account. It must not
activate, primary-mark, recover or otherwise authorize a local email address.

When auto-create stores the Google e-mail as a local email row, that row stays **pending**
and non-primary until the local email activation flow succeeds. A pending local email
grants no login and no password recovery. The auto-created account has no usable password
either, so it cannot unlink Google until the user sets one.

## Responsibility split

| Owner | Responsibilities |
| --- | --- |
| Companion backend | Issuing provider-init tokens to its own browser, reading project and group server-side, making tokens single-use, answering the redeem call, keeping strict hashes and Google tokens out of browser-visible surfaces, relaying the callback and delivering the session to its front end. |
| `api.auth` | Redeeming provider-init tokens, OAuth state, nonce and PKCE in Redis, Google ID-token verification, external-account resolution, link, create and unlink, local session issuance, OAuth audit, activity and error taxonomy. |

## In this suite

| Document | Purpose |
| --- | --- |
| [README.md](README.md) | Deprecation status, differences from `/auth/oauth/*`, Google rules (this page). |
| [architecture.md](architecture.md) | The legacy BFF topology, storage boundaries and Google-specific decisions. |
| [request-flow.md](request-flow.md) | The legacy start with provider-init redemption, step by step. |
| [scenarios.md](scenarios.md) | Google cases: returning user, auto-create, e-mail collision, Workspace denial, outage, replay. |
| [troubleshooting.md](troubleshooting.md) | Provider-init redemption failures, environment allow-lists, JWKS problems. |
| [reference.md](reference.md) | `GOOGLE_OAUTH_*` settings, alias request fields, the redemption contract, `act-cat-064..074`. |

## Related

- [OAuth suite](../oauth/README.md) — the pipeline, endpoints, errors and settings shared
  by every provider.
- [Google OAuth runbook](../../RUNBOOKS/google-oauth.md) — rollout, kill switch, JWKS
  outage, secret rotation, rollback.
- [OAuth runbook](../../RUNBOOKS/oauth.md) — migrating the environment configuration to
  the database.
- [Patreon account linking](../patreon-link/README.md) — Patreon is entitlement and link
  only, never a Google-style login.
