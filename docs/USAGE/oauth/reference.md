# OAuth Reference

Provider-agnostic OAuth sign-in. Configuration is per project and lives in the database; providers are adapters. Integration walkthrough: [OAuth overview](README.md). The deprecated Google aliases are documented in the [Google OAuth reference](../google-oauth/reference.md).

## Model

| Level | What it is | Managed by |
| --- | --- | --- |
| Provider type | Adapter code plus a row in `oauth_provider_catalog` (kill switch). Built in: `google`, `github`, `discord`, `microsoft`, `oidc` (generic, seeded disabled). | Root |
| Connection | One OAuth client at one provider: client id, **encrypted** client secret, scopes, restrictions. May be shared by several projects. | Root |
| Project binding | One project using one connection: enabled flags, provisioning mode, default user group, existing-user policy, exact-match redirect URIs and return origins. | Project admin |

Effective availability is the AND of: `OAUTH_ENABLED`, catalog status, connection status, credential status and the binding's `enabled`.

## Sign-in Endpoints

| Endpoint | Method | Auth | Request | Success | Failure |
| --- | --- | --- | --- | --- | --- |
| `/auth/oauth/init` | POST | Project API key (`X-API-Key`) | JSON `connection`, `return_origin`, optional `remember_me`. `project_hash` / `user_group_hash` are rejected. | `init_token` (single use, 300 s), `expires_in`, `connection`, `provider_type`; `Cache-Control: no-store` | `401` invalid key; `EXT_8012` (`400`) malformed or caller-supplied scope; `EXT_8013` (`400`) origin not allow-listed for this project; `EXT_8010`/`EXT_8011` unavailable |
| `/auth/oauth/providers` | GET | Project API key | — | Enabled sign-in providers of the key's project: `connection`, `provider_type`, `display_name` | `401` invalid key |
| `/auth/oauth/start` | POST | Public, rate limited | JSON `init_token`, `redirect_uri` (optional only when the binding has exactly one), optional boolean `remember_me` (a user preference; overrides the value bound at init) | `303` to the provider, OAuth binding cookie | `EXT_8012` (`401`) unknown, expired or replayed token; `EXT_8013` (`400`) redirect URI not allow-listed; `EXT_8030` (`429`) |
| `/auth/oauth/callback` | GET | Public, rate limited | `code`, `state`, optional `iss`, optional `error` | Login: `LoginResponse` + session cookies. Link: `ExternalIdentityLinkResponse`. Reauth: `reauthenticated: true`. | Neutral `EXT_8xxx`; `EXT_8031` (`400`) user cancelled; `EXT_8032` (`409`) sign in and link required |
| `/auth/oauth/callback` | POST | Public, rate limited | Same fields as a form body (`response_mode=form_post` providers) | Same as GET | Same as GET |
| `/auth/oauth/{connection}/link/start` | POST | Session + recent reauth | — | `303` to the provider | `EXT_8024` (`401`) |
| `/auth/oauth/{connection}/reauth/start` | POST | Session | — | `303` to the provider with `prompt=login` | `EXT_8024` (`401`) |
| `/auth/oauth/{connection}/link` | DELETE | Session + recent reauth | — | `ExternalIdentityUnlinkResponse` | `EXT_8028` (`404`), `EXT_8029` (`409`), `EXT_8030` (`429`) |
| `/auth/oauth/links` | GET | Session | — | The caller's linked identities (masked) | `401` |

Rules that hold for every provider:

- The project comes from the API key, the provisioning group from the binding. Neither is ever accepted from a request body.
- The connection is chosen from the init token at start and from the state record at callback — never from the browser. A connection or binding disabled while the user is at the provider stays disabled at the callback.
- State is consumed before the code exchange, exactly once. A cancelled or failed round trip also consumes it.
- Identity is the provider subject, never the e-mail. Nothing is merged by e-mail. Provider tokens are dropped before any identity or session work and are never stored.
- Redirect URIs and return origins match by exact string equality.

## Administration Endpoints

All bodies are JSON. Secrets are write-only: responses carry presence flags, a 12-character fingerprint and timestamps only.

| Endpoint | Method | Guard | Purpose |
| --- | --- | --- | --- |
| `/admin/oauth/providers` | GET | admin | Provider catalog, whether an adapter is registered, capabilities |
| `/admin/oauth/providers/{provider_type}` | PUT | root | Kill switch and login/link flags. Patreon can never be login-enabled. |
| `/admin/oauth/connections` | GET | admin | List with status, credential status, fingerprint |
| `/admin/oauth/connections` | POST | root | Create as `draft`. Built-in types reject endpoint and issuer fields. |
| `/admin/oauth/connections/{connection_hash}` | GET | admin | Non-secret configuration and `namespace_locked` |
| `/admin/oauth/connections/{connection_hash}` | PUT | root | Update non-secret fields. Issuer, tenant or team cannot change once identities are linked (`409`). |
| `/admin/oauth/connections/{connection_hash}` | DELETE | root | Refused while bound to projects; archived instead of deleted when identities exist |
| `/admin/oauth/connections/{connection_hash}/activate` | POST | root | Requires stored credentials and a valid configuration |
| `/admin/oauth/connections/{connection_hash}/disable` | POST | root | Takes effect on in-flight transactions |
| `/admin/oauth/connections/{connection_hash}/credentials` | GET | admin | Credential status and fingerprints |
| `/admin/oauth/connections/{connection_hash}/credentials` | PUT | root | Store `client_secret` and/or `signing_key` (encrypted; never echoed) |
| `/admin/oauth/connections/{connection_hash}/credentials/test` | POST | root | Validate without saving; returns the fingerprint the secret would be stored under |
| `/admin/oauth/connections/{connection_hash}/bindings` | GET | admin | Projects using this connection |
| `/admin/oauth/projects/{project_hash}/bindings` | GET | project admin | This project's bindings with readiness |
| `/admin/oauth/projects/{project_hash}/bindings/{connection_key}` | PUT | project admin | Create or update a binding. New bindings are disabled. `auto_create`/`both` require a default user group that reaches the project. |
| `/admin/oauth/projects/{project_hash}/bindings/{connection_key}` | DELETE | project admin | Remove the binding |
| `/admin/oauth/projects/{project_hash}/bindings/{connection_key}/urls` | POST | project admin | Add one `redirect_uri` or `return_origin` row (validated on entry) |
| `/admin/oauth/projects/{project_hash}/bindings/{connection_key}/urls/{url_id}` | DELETE | project admin | Remove one row |
| `/admin/oauth/projects/{project_hash}/bindings/{connection_key}/legacy-redeem` | PUT | root | Compatibility bridge for a backend that still redeems provider-init tokens |
| `/admin/oauth/projects/{project_hash}/readiness` | GET | project admin | One answer to "why is the button not working": the failing layer per provider |

## Readiness Checks

| Check | Meaning when failing |
| --- | --- |
| `oauth_globally_disabled` | `OAUTH_ENABLED` is off for the deployment |
| `provider_type_disabled` | Catalog kill switch |
| `adapter_not_registered` | The running backend has no adapter for this type |
| `connection_not_active` | Connection is draft, disabled or archived |
| `credentials_not_active` | No secret stored, or revoked |
| `binding_disabled` | Provider not enabled for this project |
| `project_inactive` | Project inactive or archived |
| `no_redirect_uri`, `no_return_origin` | Allow-list is empty |
| `default_group_missing`, `default_group_does_not_reach_project` | Auto-create is on but the provisioning group is unusable |

## Deployment Settings

Only deployment-wide values stay in the environment; each `OAUTH_*` name falls back to its `GOOGLE_OAUTH_*` predecessor.

- `OAUTH_CONFIG_SOURCE`: `env` (default, historical single Google connection) or `db`.
- `OAUTH_ENABLED`: global kill switch.
- `OAUTH_STATE_PEPPER`, `OAUTH_PROVIDER_SUB_PEPPER`, `OAUTH_EMAIL_HASH_PEPPER`: must carry the **same values** as the Google-named variables. The service refuses to start when both are set and differ, because a different subject pepper orphans every linked identity.
- `OAUTH_SECRET_ENCRYPTION_KEY`, `OAUTH_SECRET_ENCRYPTION_KEY_ID`, `OAUTH_SECRET_DECRYPTION_KEYS_JSON`, `OAUTH_SECRET_HMAC_KEY`: encryption of connection secrets; a key set separate from billing.
- `OAUTH_MAX_STATE_TTL_SECONDS`, `OAUTH_RECENT_REAUTH_SECONDS`, `OAUTH_JWKS_CACHE_TTL_SECONDS`, `OAUTH_LEEWAY_SECONDS`, `OAUTH_FAIL_CLOSED_ON_REDIS_ERROR`: ceilings and posture.
- `OAUTH_TRUSTED_PROXY_CIDRS`: `X-Forwarded-For` is honoured only from these networks; empty means the header is ignored.
- `OAUTH_ALLOW_PRIVATE_IDP_HOSTS`: development only; disables the SSRF guard for tenant-supplied OIDC endpoints.

## Identity Key

`user_external_accounts` is keyed on `(identity_namespace, provider_sub_hash)`. The hash is `HMAC-SHA256(provider-sub pepper, raw subject)`; the namespace is a separate column and is never part of the hashed input.

| Provider type | Subject | Namespace |
| --- | --- | --- |
| `google` | `sub` | `google` |
| `github` | numeric account `id` | `github` |
| `discord` | `id` | `discord` |
| `microsoft` | `oid` (not the pairwise `sub`) | `microsoft:<tenant id>` |
| `oidc` | `sub` | `oidc:<issuer>` |

A connection's namespace-defining fields are frozen once identities are linked through it.

## Migrating From Environment Configuration

```text
1. python scripts/schema_sync.py --env-file .env --dry-run     # review
2. python scripts/schema_sync.py --env-file .env --apply
3. set OAUTH_SECRET_ENCRYPTION_KEY, OAUTH_SECRET_ENCRYPTION_KEY_ID, OAUTH_SECRET_HMAC_KEY
4. python scripts/migrations/oauth_env_import.py --env-file .env \
       --project-hash <project> --default-user-group-hash <group> --dry-run
5. ... --apply
6. OAUTH_CONFIG_SOURCE=db          # rollback: OAUTH_CONFIG_SOURCE=env
```

The import keeps the companion backend working through the legacy redeem bridge. A database binding never trusts a caller-asserted project or group: the imported project and default group must be the ones the companion backend sends, otherwise its redemptions are rejected. Verify in staging first.
