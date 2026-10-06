# OAuth reference

The contract for `/auth/oauth/*` and `/admin/oauth/*`. Concepts are in the
[README](README.md), step-by-step behavior in [request-flow.md](request-flow.md).

## Sign-in endpoints

| Path | Method | Auth | Request | Success |
| --- | --- | --- | --- | --- |
| `/auth/oauth/init` | POST | User API key in `X-API-Key` | JSON: `connection`, `return_origin`, optional `purpose`, `remember_me` | `200` init token |
| `/auth/oauth/providers` | GET | User API key in `X-API-Key` | — | `200` providers enabled for the key's project |
| `/auth/oauth/start` | POST | Public; the init token is the credential | JSON: `init_token`, optional `redirect_uri`, `remember_me` | `303` to the provider, `oauth_state` cookie |
| `/auth/oauth/callback` | GET | Public; the state is the credential | Query: `code`, `state`, optional `error`, `iss` | `200` login, link or reauth result |
| `/auth/oauth/callback` | POST | Public; the state is the credential | Form: `code`, `state`, optional `error`, `iss` | Same as `GET` |
| `/auth/oauth/{connection}/link/start` | POST | Access token plus recent authentication | Optional JSON `return_origin` | `303` to the provider |
| `/auth/oauth/{connection}/reauth/start` | POST | Access token | Optional JSON `return_origin` | `303` to the provider with `prompt=login` |
| `/auth/oauth/{connection}/link` | DELETE | Access token plus recent authentication | — | `200` unlink result; all sessions revoked |
| `/auth/oauth/links` | GET | Access token | — | `200` the caller's linked identities, masked |

"Access token" means `Authorization: Bearer <access JWT>` or the `access_token` cookie.
"Recent authentication" means a sign-in, or an OAuth reauth of the same session, within
`OAUTH_RECENT_REAUTH_SECONDS` (default `300`); refreshing the session does not renew it.
`{connection}` is a binding's `connection_key` in the caller's session project,
case-insensitive.

### Init fields

`POST /auth/oauth/init` — JSON body:

| Field | Required | Notes |
| --- | --- | --- |
| `connection` | yes | A binding's `connection_key` in the key's project, case-insensitive. |
| `return_origin` | yes | Must equal one of the binding's return origins exactly. |
| `purpose` | no | Only `login` (the default) is accepted. |
| `remember_me` | no | Boolean, default `false`. `start` may override it. |
| `project_hash`, `user_group_hash`, `project`, `user_group` | — | Rejected with `400` `EXT_8012`. |

```json
{
  "success": true,
  "init_token": "q9V2mB7xR4tY1uI8oP3aS6dF0gH5jK2lZ9xC4vB7nM1",
  "expires_in": 300,
  "connection": "google",
  "provider_type": "google"
}
```

The response carries `Cache-Control: no-store`. The token is 32 random bytes, stored in
Redis under an HMAC key and consumed once by `start`.

### Providers response

`GET /auth/oauth/providers` lists the bindings of the key's project whose provider type,
adapter, connection, credentials, binding and project are all usable and whose
`login_enabled` (binding and catalog) is on. A binding still missing a redirect URI or
return origin is listed, but `init` refuses it. The list is empty when `OAUTH_ENABLED` is
off. `display_name` falls back to the capitalized provider type.

```json
{
  "success": true,
  "providers": [
    {"connection": "google", "provider_type": "google", "display_name": "Google"},
    {"connection": "github", "provider_type": "github", "display_name": "GitHub"}
  ]
}
```

### Start fields

`POST /auth/oauth/start` — JSON body:

| Field | Required | Notes |
| --- | --- | --- |
| `init_token` | yes | At most `512` characters. |
| `redirect_uri` | no | Must equal one of the binding's redirect URIs. Required when the binding lists more than one. |
| `remember_me` | no | Boolean; overrides the value given at init. Non-boolean values are ignored. |
| `project_hash`, `user_group_hash` | — | Rejected with `400` `EXT_8012`. |

The `303` response sets `oauth_state`: HttpOnly, Secure, `SameSite=Lax`, path
`/auth/oauth`, lifetime equal to the state TTL. Its value is a fingerprint of the state,
never token material.

### Callback results

`GET` and `POST /auth/oauth/callback` answer by the purpose stored in the state record.
They always answer JSON and never redirect.

| Purpose | Body | Side effects |
| --- | --- | --- |
| `login` | `LoginResponse`, the same shape as `POST /auth/login` | `access_token` and `refresh_token` cookies set for the project fixed at init |
| `link` | `ExternalIdentityLinkResponse` | Identity linked to the user who started the link; the session is marked recently authenticated |
| `reauth` | `{"success": true, "message": "Reauthentication succeeded", "reauthenticated": true}` | The session that started the reauth is marked recently authenticated |

`iss` is accepted and checked only for adapters that require it; none of the built-in
adapters do.

```json
{
  "success": true,
  "message": "External identity linked",
  "external_identity": {
    "provider": "github",
    "provider_subject_masked": "3f9a1c2b7d4e",
    "provider_email_masked": "a***e@example.com",
    "provider_email_verified_at_link": true,
    "linked_at": null,
    "last_seen_at": null,
    "status": "linked"
  }
}
```

`provider_subject_masked` is a 12-character fingerprint of the subject, not the subject.

### Link, reauth and unlink

`link/start` and `reauth/start` take an optional JSON body `{"return_origin": "..."}`.
A database binding must list exactly one redirect URI; when it lists several return
origins the caller must name one. `link/start` also needs `link_enabled` and provisioning mode
`link_only` or `both`.

`DELETE /auth/oauth/{connection}/link` returns:

```json
{
  "success": true,
  "message": "External identity unlinked",
  "remaining_auth_methods": ["password"],
  "sessions_revoked": 3
}
```

`GET /auth/oauth/links` returns every active link of the caller, for all providers:

```json
{
  "success": true,
  "links": [
    {
      "provider": "google",
      "provider_subject_masked": "8c2e61f0a9d4",
      "provider_email_masked": "j***n@example.com",
      "status": "linked",
      "linked_at": "2026-09-01 10:00:00"
    }
  ]
}
```

### Error body

OAuth sign-in routes answer errors in this shape. `correlation_id` is set on most `start`
and callback errors and is `null` elsewhere; quote it when reporting a failure.

```json
{
  "success": false,
  "status": "error",
  "correlation_id": "4c1d9e2a7b30",
  "error": {
    "code": "EXT_8031",
    "category": "external",
    "message": "Sign-in was cancelled at the provider."
  }
}
```

A missing or invalid API key on `init` and `providers`, and a missing access token on the
session routes, use the platform error envelope described in [errors.md](../errors.md).

## Error codes by endpoint

The codes and their public messages are catalogued in
[errors.md](../errors.md#oauth--external-identity-ext_80xx). This table is where each is
emitted and with which status.

| Code | Status | Emitted by |
| --- | --- | --- |
| `EXT_8010` | `503` | Connection or binding not configured (`init`, `start`, callback, link/reauth start); authorization URL could not be built, for example an unreachable discovery document (`start`); signing keys endpoint not resolvable (callback). |
| `EXT_8011` | `403` | `OAUTH_ENABLED` off (`init`, `start`); binding has `login_enabled` off (`init`); connection disabled (`start`). |
| `EXT_8011` | `404` | Connection or binding disabled (`init`, link/reauth start); disabled since the round trip started (callback). |
| `EXT_8012` | `400` | Body not an object, missing field, forbidden field or `purpose` other than `login` (`init`); missing, oversized or forbidden-field body (`start`). |
| `EXT_8012` | `401` | Init token unknown, expired or already used, or Redis unavailable (`start`). |
| `EXT_8013` | `400` | `init`: return origin not on the binding. `start`: redirect URI not on the binding, or not named when several exist. Link/reauth start: the binding does not have exactly one redirect URI, or `return_origin` is not on the binding or not named when several exist. |
| `EXT_8014` | `400` | Callback without `state`, or without both `code` and `error`. |
| `EXT_8014` | `401` | State unknown, expired or malformed, Redis unavailable, or `oauth_state` cookie mismatch (callback); state could not be created (`start`, link/reauth start). |
| `EXT_8016` | `401` | State already consumed (callback). |
| `EXT_8017` | `401` | ID-token nonce mismatch. |
| `EXT_8018` | `502` | Provider returned an `error` other than a cancellation, or the code exchange failed (including missing or undecryptable credentials). |
| `EXT_8019` | `401` | ID token or profile invalid, subject missing, or the identity key could not be derived. |
| `EXT_8020` | `401` | Issuer not allowed, including a Microsoft tenant outside `tenant_ids`. |
| `EXT_8021` | `401` | Audience or `azp` mismatch. |
| `EXT_8022` | `401` | ID token expired, or `iat` in the future. |
| `EXT_8023` | `401` | Connection restriction not met: Google `hosted_domains`, GitHub `orgs`. |
| `EXT_8024` | `401` | Login refused (binding `login_enabled` off, unknown identity without auto-create, e-mail collision on a provider whose e-mail is not trusted, no usable provisioning group, inactive or non-consumer account); link refused (session invalid, linking not allowed, no recent authentication); reauth start with an invalid session. |
| `EXT_8025` | `403` | The user does not reach the project fixed at init, or the project is inactive or archived (callback). |
| `EXT_8027` | `409` | Link callback: the identity belongs to another user, or the user already has an identity in this namespace. |
| `EXT_8028` | `401` | Reauth callback: the identity is not linked to the session's user. Unlink: invalid session or no recent authentication. |
| `EXT_8028` | `404` | Unlink: connection not available in the project, or nothing linked. |
| `EXT_8029` | `409` | Unlink: the account has no usable password. |
| `EXT_8030` | `429` | Rate limited (`start`, callback, link collisions, unlink). `Retry-After` is set. |
| `EXT_8031` | `400` | The provider returned `access_denied`, `user_cancelled_authorize` or `user_cancelled_login`. |
| `EXT_8032` | `409` | Login: a local account already uses this provider-verified e-mail (Google, GitHub, Discord). |

`EXT_8015` (`OAUTH_STATE_EXPIRED`) and `EXT_8026` (`EXTERNAL_IDENTITY_ALREADY_LINKED`) are
defined but never emitted: an expired state answers `EXT_8014`, a taken identity `EXT_8027`.

## Administration endpoints

All bodies are JSON and reject unknown fields (`400` `VAL_3001`). Secrets are write-only:
responses carry presence flags, 12-character fingerprints, the encryption key id and
timestamps. Every write records an activity event naming the changed fields, never values.

| Path | Method | Guard | Purpose |
| --- | --- | --- | --- |
| `/admin/oauth/providers` | GET | Admin | Provider catalog: `status`, catalog `login_enabled` / `link_enabled`, `default_scopes`, `adapter_registered`, adapter `capabilities`, `connection_count`, plus `oauth_enabled` |
| `/admin/oauth/providers/{provider_type}` | PUT | Root | Set catalog `status` (`enabled`, `degraded`, `disabled`, `archived`), `login_enabled`, `link_enabled`. `login_enabled: true` on `patreon` is `400`. |
| `/admin/oauth/connections` | GET | Admin | List connections. Query `provider_type`, `status`, `search` (display name, max 120), `limit` (1–200, default `50`), `offset` |
| `/admin/oauth/connections` | POST | Root | Create a connection in `draft` status, without credentials |
| `/admin/oauth/connections/{connection_hash}` | GET | Admin | Non-secret configuration, credential status, `namespace_locked` |
| `/admin/oauth/connections/{connection_hash}` | PUT | Root | Partial update of non-secret fields; `null` clears a field |
| `/admin/oauth/connections/{connection_hash}` | DELETE | Root | Delete (`outcome: deleted`), or archive and erase credentials when identities reference it (`outcome: archived`). `409` while bindings use it. |
| `/admin/oauth/connections/{connection_hash}/activate` | POST | Root | Set `active`. `400` without active credentials or when the stored configuration fails validation. |
| `/admin/oauth/connections/{connection_hash}/disable` | POST | Root | Set `disabled`; credentials and bindings are kept |
| `/admin/oauth/connections/{connection_hash}/credentials` | GET | Admin | Credential status only |
| `/admin/oauth/connections/{connection_hash}/credentials` | PUT | Root | Store `client_secret` and/or `signing_key`, encrypted |
| `/admin/oauth/connections/{connection_hash}/credentials/test` | POST | Root | Validate the stored configuration and fingerprint a candidate secret; saves nothing |
| `/admin/oauth/connections/{connection_hash}/bindings` | GET | Admin | Bindings using the connection (admins see only their projects' bindings) |
| `/admin/oauth/projects/{project_hash}/bindings` | GET | Project | The project's bindings with URLs and readiness |
| `/admin/oauth/projects/{project_hash}/readiness` | GET | Project | Per-binding readiness checks |
| `/admin/oauth/projects/{project_hash}/bindings/{connection_key}` | PUT | Project | Create or update a binding |
| `/admin/oauth/projects/{project_hash}/bindings/{connection_key}` | DELETE | Project | Remove the binding and its URLs; the connection is kept |
| `/admin/oauth/projects/{project_hash}/bindings/{connection_key}/urls` | POST | Project | Add one redirect URI or return origin |
| `/admin/oauth/projects/{project_hash}/bindings/{connection_key}/urls/{url_id}` | DELETE | Project | Remove one allow-list row |

Guards:

- **Admin** — access token of a root or admin user whose session has the `admin`
  permission. A consumer whose global role grants `admin` still gets `403` `AUTHZ_2002`.
  Admin users read shared connections (no owner project) and connections owned by
  projects they administer; another project's connection is `403` `AUTHZ_2003`.
- **Root** — access token of a root user.
- **Project** — root, or an admin assigned to the project. An unknown project is `404`
  (checked before access); a project the caller does not administer is `403` `AUTHZ_2003`.

Changes invalidate this instance's connection cache at once; other instances pick them
up within `30` seconds.

### Connection fields

`POST /admin/oauth/connections` and `PUT /admin/oauth/connections/{connection_hash}`:

| Field | Create | Notes |
| --- | --- | --- |
| `provider_type` | required | `google`, `github`, `discord`, `microsoft` or `oidc`; lowercased. Not accepted on update. `patreon`, archived types and types whose catalog allows neither login nor link are `400`. |
| `display_name` | required | 1–120 characters. |
| `client_id` | required | 1–512 characters. |
| `scopes` | optional | Space-separated; defaults to the catalog's `default_scopes`. Checked by the adapter (see [Provider types](#provider-types)). |
| `owner_project_hash` | optional | Create only. Makes the connection project-owned: only root can bind it to other projects. Unknown hash is `404`. |
| `issuer`, `discovery_url`, `authorize_endpoint`, `token_endpoint`, `jwks_uri`, `userinfo_endpoint` | optional | Accepted only for `oidc`; the other types reject them with `400`. |
| `restrictions` | optional | JSON object, provider-specific. |
| `provider_params` | optional | JSON object, provider-specific. |

The adapter validates the merged configuration on every write; with debug mode on, the
individual problems are returned in `error.details.problems`. Changing a field that moves
the identity namespace (issuer, Microsoft tenant) of a connection with linked identities
is `409` `CONF_5005`.

`status` values: `draft`, `active`, `disabled`, `archived`. Status changes go through
`activate`, `disable` and `DELETE`, never through `PUT`.

### Credential fields

`PUT .../credentials` and `POST .../credentials/test`:

| Field | Notes |
| --- | --- |
| `client_secret` | Up to 4,096 characters. Omitted or `null` keeps the stored value (re-encrypted under the active key); `""` clears it. |
| `signing_key` | Up to 16,384 characters. Same keep/clear rules. Ignored by `test`. |

`PUT` needs at least one field and must leave at least one secret stored; it answers the
credential status with `credential_status: active` and does not change the connection
status. `400` when the server has no `OAUTH_SECRET_*` keys, or a kept secret cannot be
decrypted with the configured keys.

`test` answers `{"success": true, "result": {"valid": ..., "problems": [...],
"client_secret_fingerprint": ...}}`. It validates the stored configuration (for `oidc`
with a `discovery_url` it also fetches the discovery document and compares issuers) and
returns the fingerprint the submitted secret would be stored under. It does not check the
secret against the provider.

Credential status fields: `credential_status` (`absent`, `active`, `rotating`, `revoked`),
`has_client_secret`, `has_signing_key`, `client_secret_fingerprint`,
`signing_key_fingerprint`, `credential_key_id`, `credentials_set_at`.

### Binding fields

`PUT /admin/oauth/projects/{project_hash}/bindings/{connection_key}` — the path's
`connection_key` is lowercased and at most 64 characters. Omitted fields keep their value.

| Field | New-binding default | Notes |
| --- | --- | --- |
| `connection_hash` | — | Required. On an existing binding it re-points the key. A connection owned by another project can be bound only by root. |
| `enabled` | `false` | Master switch for the binding. |
| `login_enabled` | `true` | ANDed with the catalog's `login_enabled`. |
| `link_enabled` | `true` | ANDed with the catalog's `link_enabled`. |
| `provisioning_mode` | `disabled` | `disabled`, `link_only`, `auto_create`, `both`. Linking needs `link_only` or `both`; creating accounts needs `auto_create` or `both`. |
| `default_user_group_hash` | none | Group auto-created users join. Must be active and reach the project. `null` clears it. Unknown hash is `404`. |
| `existing_user_policy` | `deny` | `join_default_group` adds an existing user who does not reach the project to the default group at sign-in. Needs a default group. |
| `state_ttl_seconds` | none | 30–600, or `null` for the deployment ceiling. |

Errors: `auto_create` or `both` without a default group is `400` `VAL_3001`; a group that is
inactive or does not reach the project, or `join_default_group` without a group, is `409`
`CONF_5005`; binding the same connection twice in one project is `409` `CONF_5004`.

The response (`binding`, also used by the list routes) carries `connection_key`,
`connection_hash`, `provider_type`, `connection_display_name`, `connection_status`,
`credential_status`, `project_hash`, `project_name`, `enabled`, `login_enabled`,
`link_enabled`, `provisioning_mode`, `default_user_group_hash`,
`default_user_group_name`, `existing_user_policy`, `delivery_mode`, `state_ttl_seconds`, `urls[]`
(`id`, `kind`, `url`, `created_at`), `ready` and `readiness[]` (`check`, `ok`, `message`).

### Allow-list fields

`POST .../bindings/{connection_key}/urls` — JSON `{"kind": ..., "url": ...}` (URL up to
2,048 characters):

| `kind` | Accepted `url` |
| --- | --- |
| `redirect_uri` | Absolute `https` URL with no wildcard, fragment or embedded credentials. |
| `return_origin` | `scheme://host[:port]` only: no path, query, fragment or trailing slash. |

Outside production (`APP_ENV` not `prod`/`production`) `http://` is also accepted for
`localhost`, `127.0.0.1` and `[::1]`. Adding a URL that is already listed returns the
existing row. Removing an unknown `url_id` is `404`.

## Readiness checks

`GET /admin/oauth/projects/{project_hash}/readiness` answers `oauth_enabled` and, per
binding, `connection_key`, `provider_type`, `ready` and `checks[]`. Every check is always
reported, in this order; a failing one carries a readable `message`.

| Check | Fails when |
| --- | --- |
| `oauth_globally_disabled` | `OAUTH_ENABLED` is off, or the OAuth settings cannot be loaded. |
| `provider_type_disabled` | The catalog status is not `enabled` or `degraded`. |
| `adapter_not_registered` | The running backend has no adapter for the provider type. |
| `connection_not_active` | The connection is `draft`, `disabled` or `archived`. |
| `credentials_not_active` | No secret is stored, or the credentials were revoked. |
| `binding_disabled` | The binding's `enabled` is off. |
| `project_inactive` | The project is inactive or archived. |
| `no_redirect_uri` | The binding has no redirect URI. |
| `no_return_origin` | The binding has no return origin. |
| `default_group_missing` | `auto_create` or `both`, and the default group is missing or inactive. |
| `default_group_does_not_reach_project` | `auto_create` or `both`, and the default group does not reach the project. |

`ready` ignores the per-purpose `login_enabled` and `link_enabled` flags. Readiness
evaluates the database configuration used by every OAuth request.

## Provider types

Every type uses PKCE (`S256`). OIDC types also send and verify a `nonce`. Endpoints are
compiled in except for `oidc`.

| Type | Subject | Identity namespace | Default scopes | Scope rule | Options | E-mail |
| --- | --- | --- | --- | --- | --- | --- |
| `google` | `sub` | `google` | `openid email` | Exactly `openid email` | `restrictions.hosted_domains` (Workspace `hd` allow-list; empty or `*` allows every account); `provider_params.google_auth_cross_check` (default `true`) | Verified |
| `github` | Numeric account `id` | `github` | `read:user user:email` | Must include `read:user` and `user:email`; `read:org` when `restrictions.orgs` is set | `restrictions.orgs` (organization logins) | Verified: primary and verified address only |
| `discord` | `id` | `discord` | `identify email` | Must include `identify` | — | Verified when Discord marks it verified |
| `microsoft` | `oid` | `microsoft:<tid>` | `openid profile email` | Must include `openid` and `profile` | `provider_params.tenant` (tenant GUID, `common`, `organizations` or `consumers`; default `common`); `restrictions.tenant_ids` | Administrator-controlled, never trusted |
| `oidc` | `sub` | `oidc:<issuer>` | `openid email` | Must include `openid` | `issuer` (required); `discovery_url`, or `authorize_endpoint` + `token_endpoint` + `jwks_uri`; `userinfo_endpoint` | Administrator-controlled, never trusted |

ID tokens are verified for signature (Google and Microsoft `RS256`; generic OIDC RS, PS
or ES 256/384/512, never `none` or HS), `kid`, issuer, audience, `azp`, `exp`/`iat` with
leeway, and nonce. JWKS and discovery documents are cached in process memory, honoring
provider cache headers up to `OAUTH_JWKS_CACHE_TTL_SECONDS`; a `kid` miss triggers exactly
one refetch, then fails closed. Outbound calls to configuration-supplied URLs must be
HTTPS and resolve to public addresses unless `OAUTH_ALLOW_PRIVATE_IDP_HOSTS` is on.

## Identity key

`user_external_accounts` is keyed on `(identity_namespace, provider_sub_hash)`, where
`provider_sub_hash = HMAC-SHA256(OAUTH_PROVIDER_SUB_PEPPER, raw subject)`. The namespace
is a separate column, never part of the hashed input. Two unique keys hold: one active
link per `(identity_namespace, subject)` and one active link per `(user, identity_namespace)`.
A connection's namespace-defining fields are frozen once identities are linked through it
(`namespace_locked: true`). Changing the pepper orphans every link. Schema notes:
[external accounts](../../../schemas/docs/external-accounts.md).

## Deployment settings

Only deployment-wide values live in the environment. Provider credentials, project
bindings and URL allow-lists live in MySQL. Invalid bounded settings fail closed.

| Variable | Default | Purpose |
| --- | --- | --- |
| `OAUTH_ENABLED` | `false` | Deployment-wide OAuth enablement gate. |
| `OAUTH_STATE_PEPPER` | — | HMAC key for state, init-token and reauth Redis keys. Required. |
| `OAUTH_PROVIDER_SUB_PEPPER` | — | HMAC key of the identity key. Never change it. |
| `OAUTH_EMAIL_HASH_PEPPER` | — | HMAC key of the stored e-mail snapshot. |
| `OAUTH_MAX_STATE_TTL_SECONDS` | `600` | State TTL ceiling, 1–600. A binding may only lower it. |
| `OAUTH_RECENT_REAUTH_SECONDS` | `300` | Recent-authentication window and reauth-marker lifetime. |
| `OAUTH_JWKS_CACHE_TTL_SECONDS` | `3600` | JWKS cache cap, 1–3600. |
| `OAUTH_LEEWAY_SECONDS` | `30` | Clock leeway for `exp`/`iat`, 0–30. |
| `OAUTH_FAIL_CLOSED_ON_REDIS_ERROR` | `true` | When `false`, rate limits are skipped on a Redis error. State and init tokens always fail closed. |
| `OAUTH_TRUSTED_PROXY_CIDRS` | empty | `X-Forwarded-For` is honored only from peers in these networks; empty ignores the header. |
| `OAUTH_ALLOW_PRIVATE_IDP_HOSTS` | `false` | Development only: lets configuration-supplied endpoints resolve to private hosts. |
| `OAUTH_SECRET_ENCRYPTION_KEY` | — | Active Fernet key for connection secrets . Required to store secrets. |
| `OAUTH_SECRET_ENCRYPTION_KEY_ID` | — | Id recorded with each ciphertext. |
| `OAUTH_SECRET_DECRYPTION_KEYS_JSON` | — | JSON object `{key_id: key}` of previous keys, for rotation. |
| `OAUTH_SECRET_HMAC_KEY` | — | Row-binding HMAC stored beside each ciphertext. |

### Rate limits

Fixed windows in Redis, shared by every provider.

| Bucket | Limit / window variables | Default | Keyed on |
| --- | --- | --- | --- |
| Start | `OAUTH_START_RATE_LIMIT`, `OAUTH_START_RATE_WINDOW_SECONDS` | `20` per `60` s | Client IP and init-token fingerprint |
| Callback | `OAUTH_CALLBACK_RATE_LIMIT`, `OAUTH_CALLBACK_RATE_WINDOW_SECONDS` | `30` per `60` s | Client IP and state fingerprint |
| State consume | `OAUTH_STATE_CONSUME_RATE_LIMIT`, `OAUTH_STATE_CONSUME_RATE_WINDOW_SECONDS` | `60` per `60` s | Client IP and state fingerprint |
| Subject collision | `OAUTH_SUB_COLLISION_RATE_LIMIT`, `OAUTH_SUB_COLLISION_RATE_WINDOW_SECONDS` | `10` per `300` s | Subject fingerprint and client IP (link to a taken identity) |
| Unlink | `OAUTH_UNLINK_RATE_LIMIT`, `OAUTH_UNLINK_RATE_WINDOW_SECONDS` | `10` per `300` s | User and client IP |

`init` and `providers` have no OAuth bucket. The client IP is the TCP peer unless
`OAUTH_TRUSTED_PROXY_CIDRS` trusts it; behind a BFF every request shares the BFF's
address.

## Redis keys

| Key prefix | Holds | TTL |
| --- | --- | --- |
| `oauth_init:` | Init-token record (connection, binding, project, return origin, `remember_me`) | `300` s |
| `oauth_init_consumed:` | Replay tombstone for a consumed init token | `600` s |
| `oauth_state:` | State record: connection, binding, purpose, project, redirect URI, nonce, PKCE verifier, user and session for link/reauth | State TTL |
| `oauth_state_consumed:` | Replay tombstone for a consumed state | `600` s |
| `oauth_reauth:` | Recent-reauthentication marker for one user and session | `OAUTH_RECENT_REAUTH_SECONDS` |
| `oauth_rate:` | Rate-limit counters for every provider, one sub-prefix per bucket | Bucket window |

Key suffixes are HMACs or SHA-256 digests; raw state, tokens, user ids and IPs never
appear in key names.

## Activity codes

Routes under `/auth/oauth/*` and `/admin/oauth/*` record these activity types.
Details carry only fingerprints, reason codes and the changed field names.

| ID | Activity type | Recorded when |
| --- | --- | --- |
| `act-cat-107` | `oauth_started` | A provider round trip starts. |
| `act-cat-108` | `oauth_init_rejected` | An init token is rejected, or the authorization start fails. |
| `act-cat-109` | `oauth_callback_received` | A callback arrives. |
| `act-cat-110` | `oauth_state_rejected` | State is unknown, reused, cookie-mismatched, or its connection became unavailable. |
| `act-cat-111` | `oauth_token_exchange_failed` | The provider returned an error or the code exchange failed. |
| `act-cat-112` | `oauth_identity_rejected` | ID token, nonce, restriction or identity-key checks failed. |
| `act-cat-113` | `oauth_login_succeeded` | A local session was issued. |
| `act-cat-114` | `oauth_login_denied` | Login refused; `sub_reason` names the cause. |
| `act-cat-115` | `oauth_external_account_linked` | An identity was linked. |
| `act-cat-116` | `oauth_external_account_unlinked` | An identity was unlinked. |
| `act-cat-117` | `oauth_reauth_succeeded` | A reauth round trip marked the session. |
| `act-cat-118` | `oauth_user_cancelled` | The user cancelled at the provider. |
| `act-cat-119` | `oauth_connection_created` | Admin created a connection. |
| `act-cat-120` | `oauth_connection_updated` | Admin updated a connection. |
| `act-cat-121` | `oauth_connection_credentials_set` | Admin stored credentials. |
| `act-cat-122` | `oauth_connection_status_changed` | Admin activated, disabled, deleted or archived a connection. |
| `act-cat-123` | `oauth_binding_updated` | Admin created or changed a binding, . |
| `act-cat-124` | `oauth_binding_removed` | Admin removed a binding. |
| `act-cat-125` | `oauth_binding_url_added` | Admin added an allow-list row. |
| `act-cat-126` | `oauth_binding_url_removed` | Admin removed an allow-list row. |
| `act-cat-127` | `oauth_provider_catalog_updated` | Root changed the provider catalog. |

The API audit log tags every OAuth route with `auth_method='oauth'` and the tags
`authentication`, `oauth` and `external_idp`;
responses of `400` and above are security events. It redacts these fields wherever they
appear, in addition to the Patreon ones: `provider_init_token`, `init_token`,
`authorization_code`, `oauth_code`, `code`, `state`, `oauth_state`, `nonce`,
`code_verifier`, `pkce_verifier`, `id_token`, `google_id_token`, `google_id_token_claims`,
`access_token`, `refresh_token`, `google_access_token`, `google_refresh_token`,
`google_sub`, `provider_sub`, `google_email`, `google_hd`, `provider_email`,
`oauth_link_token`, `client_secret`, `signing_key`, `project_hash`, `user_group_hash`.

## Provisioning a Google connection

Use the root `/admin/oauth/*` endpoints to create the connection, store its credentials,
and bind it to a project with exact redirect URI and return-origin allow-lists. The
operator helper `scripts/provision_google_oauth.py` accepts `SETUP_GOOGLE_OAUTH_*`
inputs and is a dry run by default. Run with `--apply` only against the intended database.
It stores encrypted credentials and the binding; runtime requests read those database rows.
See the [OAuth runbook](../../RUNBOOKS/oauth.md).
