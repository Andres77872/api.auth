# OAuth Sign-in (Provider-agnostic)

Sign-in with external identity providers, configured **per project in the
database** and implemented through **provider adapters**. Any project can enable
Google, GitHub, Discord, Microsoft or a generic OpenID Connect provider without
touching the service's environment or restarting it.

| Document | Contents |
| --- | --- |
| [Reference](reference.md) | Endpoints, administration API, readiness checks, deployment settings, identity key, migration steps |
| [Google OAuth (deprecated aliases)](../google-oauth/README.md) | The original `/auth/google` route family, still served, and the `GOOGLE_OAUTH_*` environment configuration it reads |

## Flow

```text
Project backend --> api.auth   POST /auth/oauth/init      X-API-Key: <project key>
                                 { "connection": "google", "return_origin": "https://app.example" }
                <-- init_token (opaque, single use, 300 s)

Browser / BFF   --> api.auth   POST /auth/oauth/start     { "init_token", "redirect_uri" }
                <-- 303 Location: provider authorize URL

Provider        --> backend callback --> api.auth   GET /auth/oauth/callback?code&state
                <-- LoginResponse + session cookies
```

The project is derived from the API key and the provisioning group from the
project's binding. A caller can never choose either.

## Enabling a Provider for a Project

1. Create an OAuth client at the provider and register the project's redirect URI there.
2. Root: create a connection, store its client secret, test, activate.
3. Project admin: bind the project to the connection, choose the provisioning mode and default user group, add the exact redirect URI and return origin, enable the binding.
4. Check the readiness endpoint; every check must pass.

New bindings are created disabled and unusable until a redirect URI and a return
origin exist.

## Integrating a Project Backend

A consuming backend needs one credential — a project-scoped API key — and three
calls. Nothing about the provider is compiled into the backend: adding a second
provider later is an administration change, not a deployment.

### 1. Render the login page from data

```bash
curl -X GET "https://auth.example/auth/oauth/providers" \
  -H "X-API-Key: $PROJECT_API_KEY" \
  -H "User-Agent: my-backend/1.0"
```

Returns only the connections that are enabled for **this** project and currently
usable for login:

```json
{
  "success": true,
  "providers": [
    {"connection": "google", "provider_type": "google", "display_name": "Google"}
  ]
}
```

Render one button per entry and pass `connection` back verbatim. An empty list
means no provider is ready — show no buttons rather than a broken one, and read
`GET /admin/oauth/projects/{project_hash}/readiness` to find out why.

### 2. Mint an init token when the user clicks a button

```bash
curl -X POST "https://auth.example/auth/oauth/init" \
  -H "X-API-Key: $PROJECT_API_KEY" \
  -H "Content-Type: application/json" \
  -H "User-Agent: my-backend/1.0" \
  -d '{"connection": "google", "return_origin": "https://app.example"}'
```

| Field | Required | Notes |
| --- | --- | --- |
| `connection` | yes | A `connection` value from the providers list. |
| `return_origin` | yes | Must match a return origin on the binding by exact string equality. |
| `purpose` | no | Only `login` is accepted; it is also the default. |
| `remember_me` | no | Boolean default for the session; `/auth/oauth/start` may override it. |

`project_hash`, `user_group_hash`, `project` and `user_group` are **rejected**,
not ignored — the project comes from the API key and the group from the binding.
Sending one returns `EXT_8012` (`400`).

The response carries `Cache-Control: no-store`. Treat `init_token` as a
credential: it is single-use, expires in 300 seconds, and must reach the browser
over the backend's own authenticated response — never a URL parameter, a log, or
a third party.

### 3. Hand the token to the browser

The browser (or the backend acting as a BFF) posts the token to `/auth/oauth/start`
and follows the `303`:

```bash
curl -X POST "https://auth.example/auth/oauth/start" \
  -H "Content-Type: application/json" \
  -H "User-Agent: my-client/1.0" \
  -d '{"init_token": "...", "redirect_uri": "https://app.example/oauth/return"}'
```

`redirect_uri` may be omitted only when the binding has exactly one. The provider
then calls `/auth/oauth/callback`, which completes the exchange and returns the
ordinary `LoginResponse` plus the usual session cookies. From that point the
session is an ordinary local session: refresh, validate, switch-project and
logout all behave exactly as they do after a password login.

### Error handling

Callback failures are deliberately neutral — the public message never says which
check failed. Branch on `error.code`, not on the message:

| Code | What the client should do |
| --- | --- |
| `EXT_8031` | The user cancelled at the provider. Show "sign-in cancelled", not an error. |
| `EXT_8032` | A local account already owns this verified e-mail. Ask the user to sign in with their existing method, then link the provider. Accounts are never merged by e-mail. |
| `EXT_8012` | The init token was unknown, expired, or already used. Mint a new one and restart. |
| `EXT_8013` | The redirect URI or return origin is not on the binding's allow-list. |
| `EXT_8030` | Rate limited. Honor `Retry-After`. |
| `EXT_8010` / `EXT_8011` | The provider is not available for this project. Check readiness. |

The full family is in the [error reference](../errors.md#oauth--external-identity-ext_80xx).

### Checklist for a new project

- [ ] Project API key issued and stored as a server-side secret.
- [ ] Connection active, credentials stored and tested (root).
- [ ] Binding enabled with provisioning mode, default user group, redirect URIs and return origins (project admin).
- [ ] Redirect URI registered identically at the provider — exact string equality, no trailing-slash drift.
- [ ] Readiness endpoint returns no failing check.
- [ ] Login page renders from `GET /auth/oauth/providers` rather than a hardcoded list.
- [ ] `EXT_8031` and `EXT_8032` handled as ordinary outcomes, not crashes.
