# OAuth

Sign-in, account linking and step-up reauthentication with external identity providers
(Google, GitHub, Discord, Microsoft Entra ID and generic OpenID Connect). A project's
backend starts a sign-in with its project API key; `api.auth` runs the provider round trip
and answers with the same local session a password login produces. Which providers a
project offers is configuration in the database, managed through `/admin/oauth/*`, so
enabling a provider needs no deployment and no restart.

## Key concepts

| Concept | What it is | Managed by |
| --- | --- | --- |
| Provider type | A kind of provider: adapter code in the service plus a row in the provider catalog, whose `status` is the run-time kill switch. Built in: `google`, `github`, `discord`, `microsoft`, `oidc` (seeded `disabled`). `patreon` is listed as link-only and is configured by the [Patreon integration](../patreon-link/README.md), not here. | Root |
| Connection | One OAuth client registration at one provider: client id, scopes, restrictions, endpoints (generic OIDC only) and an encrypted, write-only client secret. Identified by `connection_hash`. One connection can serve many projects. | Root |
| Project binding | One project using one connection under a project-local `connection_key` (for example `google`): `enabled`, `login_enabled`, `link_enabled`, provisioning mode, default user group, existing-user policy, optional state TTL, and exact-match redirect URI and return origin allow-lists. | Root, or an admin of the project |
| Configuration source | `OAUTH_CONFIG_SOURCE=env` (default) serves one Google connection built from the `GOOGLE_OAUTH_*` variables; `db` serves connections and bindings from the database. | Deployment |
| Identity key | An external account is stored as `(identity_namespace, HMAC-SHA256(provider-sub pepper, subject))`. Never the e-mail and never the raw subject. | Automatic |

A binding can be used only when every layer allows it: the catalog status, the
connection status, the connection's credentials, the binding's `enabled` flag and the
project itself, checked on every request, plus `OAUTH_ENABLED`, which gates `init` and
`start`. `GET /admin/oauth/projects/{project_hash}/readiness` reports which layer is
missing.

## How a sign-in works

```text
Browser        Project backend                        api.auth                        Provider
   | click "Sign in" |                                     |                               |
   |---------------->| POST /auth/oauth/init  (X-API-Key)  |                               |
   |                 |------------------------------------>| project from key, group from  |
   |                 |<---------------- init_token --------| binding; token single-use     |
   |                 | POST /auth/oauth/start {init_token} |                               |
   |                 |------------------------------------>| consume token, store state,   |
   |                 |<------ 303 Location: authorize URL --| nonce and PKCE verifier       |
   |<-- redirect ----|                                     |                               |
   |------------------------------------------------------------------------------------>|
   |<------------------------------ redirect to the binding's redirect URI ---------------|
   |---------------->| GET /auth/oauth/callback?code&state |                               |
   |                 |------------------------------------>| consume state, exchange code, |
   |                 |<-- LoginResponse + session cookies -| verify identity, issue tokens |
   |<-- your own session delivery (cookie, one-time code, ...)                              |
```

The redirect URI registered at the provider is normally the project backend's callback,
which relays `code` and `state` to `/auth/oauth/callback`. The callback always answers
JSON; it never redirects the browser back to the return origin.

## Route families

| Family | Routes | Caller and authentication |
| --- | --- | --- |
| Server-to-server | `POST /auth/oauth/init`, `GET /auth/oauth/providers` | Project backend, user API key in `X-API-Key` |
| Public round trip | `POST /auth/oauth/start`, `GET` and `POST /auth/oauth/callback` | Anyone holding a valid init token or state; rate limited |
| Signed-in user | `POST /auth/oauth/{connection}/link/start`, `POST /auth/oauth/{connection}/reauth/start`, `DELETE /auth/oauth/{connection}/link`, `GET /auth/oauth/links` | Access token (`Authorization: Bearer` or the `session_token` cookie); link and unlink also need recent authentication |
| Administration | `/admin/oauth/*` (20 routes) | Root or admin user whose session has the `admin` permission; writes that touch secrets, connections or the catalog are root-only |
| Deprecated aliases | `/auth/google/*` (5 routes) | See the [Google OAuth suite](../google-oauth/README.md) |

## Rules and caveats

- **JSON bodies.** Every `/auth/oauth/*` and `/admin/oauth/*` body is JSON, except
  `POST /auth/oauth/callback`, which takes form fields (`response_mode=form_post`).
- **The caller never chooses scope.** The project comes from the API key and the
  provisioning group from the binding. `init` rejects `project_hash`, `user_group_hash`,
  `project` and `user_group`; `start` rejects `project_hash` and `user_group_hash`.
- **Single-use credentials.** The init token (300 seconds) and the OAuth state (at most
  600 seconds) are each consumed once. State is consumed before the code exchange, so a
  cancelled or failed round trip cannot be replayed.
- **Exact matching.** Redirect URIs and return origins match by exact string equality.
  No prefixes, wildcards or trailing-slash tolerance.
- **Nothing is merged by e-mail.** When a new identity carries the e-mail of an existing
  local account, sign-in is refused. Providers that verify e-mail (Google, GitHub,
  Discord) get `EXT_8032`, telling the user to sign in and link; Microsoft and generic
  OIDC, whose e-mail claim is administrator-controlled, get the neutral `EXT_8024`.
- **Consumers only.** OAuth sign-in resolves only active `consumer` accounts. Root and
  admin users cannot sign in this way.
- **Provider tokens are never stored.** Access, refresh and ID tokens are dropped before
  any identity or session work. The session issued is an ordinary local session:
  refresh, validate, switch-project and logout behave as after a password login.
- **One identity per provider namespace.** A user can hold at most one active link per
  identity namespace (for example one Google account).
- **Unlink signs the user out everywhere** and is refused unless the account has a usable
  password to fall back on.
- **Environment source limits.** With `OAUTH_CONFIG_SOURCE=env` only the `google`
  connection exists, and its binding has no default user group: `/auth/oauth/init` then
  signs in and links existing users but cannot auto-create new ones. Use
  `OAUTH_CONFIG_SOURCE=db` for per-project provisioning.
- **Neutral errors.** Public messages never say which check failed. Branch on
  `error.code`; operators read the `sub_reason` in the activity log.

## In this suite

| Document | Purpose |
| --- | --- |
| [README.md](README.md) | Concepts, route families and rules (this page). |
| [usage.md](usage.md) | Tasks: enable a provider for a project, integrate a backend, link, reauthenticate, unlink. |
| [request-flow.md](request-flow.md) | What each request does step by step: init, start, callback, link, reauth, unlink. |
| [reference.md](reference.md) | Endpoints, fields, response shapes, provider types, readiness checks, error codes, settings, Redis keys, activity codes. |
| [troubleshooting.md](troubleshooting.md) | Symptom, cause and fix for failed sign-ins and configuration problems. |

## Related

- [Google OAuth (deprecated aliases)](../google-oauth/README.md) — `/auth/google/*`, the
  legacy provider-init handshake and the `GOOGLE_OAUTH_*` configuration.
- [Patreon account linking](../patreon-link/README.md) — entitlement linking, never sign-in.
- [API keys](../api-keys/README.md) — the credential a project backend uses for `init`.
- [OAuth runbook](../../RUNBOOKS/oauth.md) — migration to the database source, key and
  secret rotation, emergency switches.
- [Error reference](../errors.md#oauth--external-identity-ext_80xx) — the `EXT_80xx` catalog.
- [Design record](../../agnostic_oauth/README.md) — why the feature is shaped this way.
