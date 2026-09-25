# OAuth usage

One task per section. Field tables, response shapes and error codes are in
[reference.md](reference.md); what happens inside each request is in
[request-flow.md](request-flow.md).

The examples use `$AUTH` for the `api.auth` base URL, `$ROOT_TOKEN` for a root access
token, `$ADMIN_TOKEN` for a root or project-admin access token, `$PROJECT_API_KEY` for a
project-scoped user API key (`sk_...`) and `$ACCESS_TOKEN` for a signed-in consumer's
access token.

## Enable a provider for a project

Needs `OAUTH_ENABLED=true`, `OAUTH_CONFIG_SOURCE=db` and the `OAUTH_SECRET_*` keys set on
the deployment (see [Deployment settings](reference.md#deployment-settings)). Nothing
below requires a restart.

### Register the client at the provider

Create an OAuth client in the provider's console. Register as redirect URI the exact
callback URL of the project backend that will relay the callback to `api.auth` (for
example `https://app.example.com/oauth/google/callback`). Scopes must satisfy the
[provider type](reference.md#provider-types); Google needs exactly `openid email`.

### Create the connection

Root only. `POST /admin/oauth/connections` — JSON body, no secret:

```bash
curl -X POST "$AUTH/admin/oauth/connections" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"provider_type": "google", "display_name": "Google", "client_id": "1234.apps.googleusercontent.com"}'
```

The response carries `connection.connection_hash` and `status: draft`. Add
`restrictions` or `provider_params` when the provider type supports them, for example
`{"restrictions": {"orgs": ["acme"]}}` for GitHub (which then also needs the `read:org`
scope).

### Store and test the client secret

Root only. Test first: nothing is saved and the answer contains the fingerprint the
secret will be stored under.

```bash
curl -X POST "$AUTH/admin/oauth/connections/$CONNECTION_HASH/credentials/test" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"client_secret": "'"$CLIENT_SECRET"'"}'

curl -X PUT "$AUTH/admin/oauth/connections/$CONNECTION_HASH/credentials" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"client_secret": "'"$CLIENT_SECRET"'"}'
```

The `PUT` answer shows `credential_status: active` and `client_secret_fingerprint`; it
must match the fingerprint from the test. The secret is never returned.

### Activate the connection

Root only.

```bash
curl -X POST "$AUTH/admin/oauth/connections/$CONNECTION_HASH/activate" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

`400` means no active credentials are stored or the configuration no longer validates.

### Bind the project

Root, or an admin assigned to the project. `PUT
/admin/oauth/projects/{project_hash}/bindings/{connection_key}` — the key (`google` here)
is what sign-in clients send as `connection`.

```bash
curl -X PUT "$AUTH/admin/oauth/projects/$PROJECT_HASH/bindings/google" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"connection_hash": "'"$CONNECTION_HASH"'", "enabled": true, "provisioning_mode": "both", "default_user_group_hash": "'"$GROUP_HASH"'"}'
```

Choose `provisioning_mode` deliberately: `link_only` lets existing users link and sign in,
`auto_create` creates accounts for new identities in the default group, `both` does
both. `auto_create` and `both` need a default user group that is active and reaches the
project. Set `existing_user_policy: join_default_group` only if signing in here should
give existing users of other projects access to this one.

### Add the redirect URI and return origin

```bash
curl -X POST "$AUTH/admin/oauth/projects/$PROJECT_HASH/bindings/google/urls" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind": "redirect_uri", "url": "https://app.example.com/oauth/google/callback"}'

curl -X POST "$AUTH/admin/oauth/projects/$PROJECT_HASH/bindings/google/urls" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"kind": "return_origin", "url": "https://app.example.com"}'
```

The redirect URI must be byte-identical to the one registered at the provider. Keep one
redirect URI per binding: link and reauth refuse a binding with several.

### Check readiness

```bash
curl "$AUTH/admin/oauth/projects/$PROJECT_HASH/readiness" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Every entry in `checks` must be `ok: true`. The first failing check names the layer to
fix; see [Readiness checks](reference.md#readiness-checks).

## Sign users in from a project backend

The backend needs one credential, a user API key scoped to the project (see
[API keys](../api-keys/README.md)), stored as a server-side secret.

### Render the login page from data

```bash
curl "$AUTH/auth/oauth/providers" -H "X-API-Key: $PROJECT_API_KEY"
```

Render one button per entry and send its `connection` back unchanged. An empty list means
no provider is usable for the project; check readiness instead of showing a broken
button.

### Mint an init token

When the user clicks a button, call `init` from the backend:

```bash
curl -X POST "$AUTH/auth/oauth/init" \
  -H "X-API-Key: $PROJECT_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"connection": "google", "return_origin": "https://app.example.com"}'
```

The answer carries `init_token` (single use, `expires_in: 300`). Treat it as a
credential: keep it out of URLs, logs and third parties. Never send `project_hash` or
`user_group_hash`; they are rejected.

### Start the round trip

Post the token to `start` without following the redirect, and send the browser to the
`Location` it returns:

```bash
curl -si -X POST "$AUTH/auth/oauth/start" \
  -H "Content-Type: application/json" \
  -d '{"init_token": "'"$INIT_TOKEN"'", "redirect_uri": "https://app.example.com/oauth/google/callback"}' \
  | grep -i '^location:'
```

`redirect_uri` can be omitted when the binding has exactly one. `start` may also carry
`remember_me` to override the value given at init.

### Relay the callback

The provider sends the browser to your redirect URI with `code` and `state` (or `error`).
Forward them, URL-encoded, to `api.auth`:

```bash
curl -G "$AUTH/auth/oauth/callback" \
  --data-urlencode "code=$CODE" \
  --data-urlencode "state=$STATE"
```

On success the answer is the same `LoginResponse` as a password login, plus
`session_token` and `refresh_token` cookies, for the project the API key belongs to.
Deliver the session to your front end your own way (a cookie on your domain, a one-time
code); `api.auth` never redirects the browser back. From here the session is an ordinary
local session. If the provider answered with `error`, forward that instead of `code` so
the state is consumed and the outcome is reported.

### Handle the outcome

Public messages are neutral; branch on `error.code`:

| Code | What the client should do |
| --- | --- |
| `EXT_8031` | The user cancelled at the provider. Show "sign-in cancelled", not an error. |
| `EXT_8032` | A local account already uses this verified e-mail. Ask the user to sign in with their existing method, then link the provider. |
| `EXT_8024` | Sign-in not permitted for this identity (no auto-create, unusable account). Show a generic failure. |
| `EXT_8025` | The account does not have access to this project. |
| `EXT_8012`, `EXT_8014`, `EXT_8016` | The init token or state was unknown, expired or reused. Start over with a new init token. |
| `EXT_8013` | Redirect URI or return origin not on the binding. Configuration problem. |
| `EXT_8030` | Rate limited. Honor `Retry-After`. |
| `EXT_8010`, `EXT_8011`, `EXT_8018` | Provider unavailable or misconfigured. Check readiness. |

## Link a provider to a signed-in account

Needs recent authentication (a sign-in, or a reauth of this session, within
`OAUTH_RECENT_REAUTH_SECONDS`) and a binding with `link_enabled` on and provisioning mode
`link_only` or `both`.

```bash
curl -si -X POST "$AUTH/auth/oauth/google/link/start" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  | grep -i '^location:'
```

Send the browser to the `Location`, then relay the callback as for sign-in. The callback
answers the linked identity (masked) instead of a session, and marks the session as
recently authenticated. `409` `EXT_8027` means the identity belongs to another user, or
the user already has a different identity for this provider. Pass
`{"return_origin": "..."}` as JSON when the binding lists several return origins.

## Reauthenticate with a provider

Step-up for a session whose user already has this provider linked. No recent
authentication is needed to start.

```bash
curl -si -X POST "$AUTH/auth/oauth/google/reauth/start" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  | grep -i '^location:'
```

The provider is asked to prompt for login again. When the relayed callback returns
`{"reauthenticated": true}`, the session that started the round trip counts as recently
authenticated for `OAUTH_RECENT_REAUTH_SECONDS`, which satisfies every route that
requires recent authentication: `POST /auth/switch-project`, API-key changes, OAuth link
and unlink, and the Patreon link routes. An identity not linked to the user answers
`401` `EXT_8028`.

## Unlink a provider

Needs recent authentication and a usable password on the account.

```bash
curl -X DELETE "$AUTH/auth/oauth/google/link" \
  -H "Authorization: Bearer $ACCESS_TOKEN"
```

Unlinking revokes every session and refresh token of the user, including the current one
(`sessions_revoked`). `409` `EXT_8029` means the account has no password to fall back on:
set one first. `404` `EXT_8028` means nothing is linked for this connection.

## List linked providers

```bash
curl "$AUTH/auth/oauth/links" -H "Authorization: Bearer $ACCESS_TOKEN"
```

Returns every active link of the user (all providers) with masked subject and e-mail.

## Turn a provider off

| Scope | Action | Who |
| --- | --- | --- |
| New sign-ins through `init` and `start` | `OAUTH_ENABLED=false` | Deployment |
| One provider type everywhere (database source) | `PUT /admin/oauth/providers/{provider_type}` with `{"status": "disabled"}` | Root |
| One client | `POST /admin/oauth/connections/{connection_hash}/disable` | Root |
| One project | Binding `{"enabled": false}` | Root or project admin |
| Sign-in only, keep linking | Binding `{"login_enabled": false}` | Root or project admin |
| Google under the environment source | `GOOGLE_OAUTH_ENABLED=false` | Deployment |

`OAUTH_ENABLED` is checked only by `init`, `start` and `providers`: link and reauth
starts, callbacks of round trips already started, and `POST /auth/google/start` under the
database source keep working. The catalog, connection and binding switches are checked on
every request, including the callback, which re-resolves the connection after consuming
the state, so they also stop transactions already at the provider. Other instances follow
within `30` seconds.
