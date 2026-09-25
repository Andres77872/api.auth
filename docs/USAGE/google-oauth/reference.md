# Google OAuth reference

Settings, request fields and activity codes specific to the deprecated `/auth/google/*`
aliases and the environment-configured Google connection. Responses, error codes, rate
limits, Redis keys and audit redaction are shared with `/auth/oauth/*` and documented in
the [OAuth reference](../oauth/reference.md).

## Configuration keys

Values below are names only; never paste real secrets into docs or tickets. The Google
client, allow-list, provisioning, hosted-domain and `PROVIDER_INIT_*` keys configure the
single Google connection served while `OAUTH_CONFIG_SOURCE=env`; with `db` they are
ignored and the connection and binding come from the database. The pepper, TTL, leeway,
cache and fail-closed keys are also the fallbacks of the `OAUTH_*` deployment settings
under both sources.

| Key | Default | Notes |
| --- | --- | --- |
| `GOOGLE_OAUTH_ENABLED` | `false` | Enables the environment Google connection; off answers `403` or `404` `EXT_8011` on every Google route. Also the fallback of `OAUTH_ENABLED`. |
| `GOOGLE_OAUTH_CLIENT_ID` | — | Required once enabled; missing answers `503` `EXT_8010`. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | — | Used for the code exchange. Rotate through secret management; never log it. |
| `GOOGLE_OAUTH_AUTHORIZE_ENDPOINT` | `https://accounts.google.com/o/oauth2/v2/auth` | Optional override. |
| `GOOGLE_OAUTH_TOKEN_ENDPOINT` | `https://oauth2.googleapis.com/token` | Optional override. |
| `GOOGLE_OAUTH_JWKS_URI` | `https://www.googleapis.com/oauth2/v3/certs` | Optional override. |
| `GOOGLE_OAUTH_ISSUERS` | `https://accounts.google.com,accounts.google.com` | Optional override. |
| `GOOGLE_OAUTH_DISCOVERY_URL` | `https://accounts.google.com/.well-known/openid-configuration` | Parsed but not used: Google endpoints come from the keys above or the built-in values. |
| `GOOGLE_OAUTH_SCOPES` | `openid email` | Must be exactly `openid email`; any other value makes the Google configuration fail to load. |
| `GOOGLE_OAUTH_REDIRECT_URIS` | empty | Comma-separated exact allow-list. `start` uses the requested URI if listed, else the first. |
| `GOOGLE_OAUTH_RETURN_ORIGINS` | empty | Comma-separated exact allow-list. `start` uses the requested origin, else the first. |
| `GOOGLE_OAUTH_ALLOWED_HOSTED_DOMAINS` | empty | Workspace `hd` allow-list, comma-separated, case-insensitive. Empty or `*` allows every account; consumer Gmail carries no `hd` and is always allowed. A non-matching `hd` answers `401` `EXT_8023`. |
| `GOOGLE_OAUTH_PROVISIONING_MODE` | `disabled` | `disabled`, `link_only`, `auto_create` or `both`, for the whole deployment. |
| `GOOGLE_OAUTH_STATE_TTL_SECONDS` | `600` | 1–600. State TTL of the environment connection; fallback of `OAUTH_MAX_STATE_TTL_SECONDS`. |
| `GOOGLE_OAUTH_RECENT_REAUTH_SECONDS` | `300` | Fallback of `OAUTH_RECENT_REAUTH_SECONDS`. |
| `GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS` | `3600` | 1–3600. JWKS cache cap of the environment connection; fallback of `OAUTH_JWKS_CACHE_TTL_SECONDS`. |
| `GOOGLE_OAUTH_LEEWAY_SECONDS` | `30` | 0–30. Clock leeway of the environment connection; fallback of `OAUTH_LEEWAY_SECONDS`. |
| `GOOGLE_OAUTH_STATE_PEPPER` | — | Fallback of `OAUTH_STATE_PEPPER`. Secret. |
| `GOOGLE_OAUTH_PROVIDER_SUB_PEPPER` | — | Fallback of `OAUTH_PROVIDER_SUB_PEPPER`. Keys every linked identity; never change it. |
| `GOOGLE_OAUTH_EMAIL_HASH_PEPPER` | — | Fallback of `OAUTH_EMAIL_HASH_PEPPER`. Secret. |
| `GOOGLE_OAUTH_FAIL_CLOSED_ON_REDIS_ERROR` | `true` | Fallback of `OAUTH_FAIL_CLOSED_ON_REDIS_ERROR`. |
| `PROVIDER_INIT_REDEEM_URL` | — | The companion's redeem endpoint. Must be `https://` (plain `http://` only to `localhost`, `127.0.0.1` or `::1`) without credentials; private hosts are allowed. |
| `PROVIDER_INIT_REDEEM_TOKEN` | — | Bearer sent to the redeem endpoint. Secret. |
| `PROVIDER_INIT_RETURN_ORIGINS` | `GOOGLE_OAUTH_RETURN_ORIGINS` | Origins a redeemed token may name. |

The four endpoint keys, `GOOGLE_OAUTH_ISSUERS` and `GOOGLE_OAUTH_DISCOVERY_URL` are
optional overrides, not required settings: `src/Util/google_oauth_config.py` carries the
correct Google values as built-in defaults. Leave them unset unless a deployment
deliberately points somewhere else; setting them to placeholder values overrides the
working defaults and breaks sign-in. What a deployment must supply to enable the
environment connection is `GOOGLE_OAUTH_ENABLED`, `GOOGLE_OAUTH_CLIENT_ID`,
`GOOGLE_OAUTH_CLIENT_SECRET`, the redirect and return-origin allow-lists, the three
peppers and, for the alias handshake, `PROVIDER_INIT_REDEEM_URL` and
`PROVIDER_INIT_REDEEM_TOKEN`.

The `GOOGLE_OAUTH_*_RATE_LIMIT` and `GOOGLE_OAUTH_*_RATE_WINDOW_SECONDS` keys are the
fallback names of the shared OAuth rate limits; see
[Rate limits](../oauth/reference.md#rate-limits).

Redirect URIs and return origins match by exact string equality: no suffix or wildcard
matching, no implicit scheme upgrade, no production-domain defaults. Local examples:
`http://localhost:5000/auth/google/callback/return` (a BFF callback),
`http://localhost:3000`, `http://localhost:5173`.

## Endpoints

| Path | Method | Auth | Request | Success |
| --- | --- | --- | --- | --- |
| `/auth/google/start` | POST | Public; the provider-init token is the credential | JSON, see below | `303` to Google, `oauth_state` cookie (path `/auth/google`) |
| `/auth/google/callback` | GET | Public; the state is the credential | Query `code`, `state`, optional `error` (`error_description` ignored) | `200` login, link or reauth result, as for `/auth/oauth/callback` |
| `/auth/google/link/start` | POST | Access token plus recent authentication | Optional JSON `return_origin` | `303` to Google |
| `/auth/google/reauth/start` | POST | Access token | Optional JSON `return_origin` | `303` to Google with `prompt=login` |
| `/auth/google/unlink` | DELETE | Access token plus recent authentication | — | `200` `ExternalIdentityUnlinkResponse` with `sessions_revoked` |

`POST /auth/google/start` — JSON body:

| Field | Required | Notes |
| --- | --- | --- |
| `provider_init_token` | yes | Opaque token from the companion, at most 4,096 characters. |
| `redirect_uri` | no | Must be on the allow-list. |
| `return_origin` | no | Must be on the allow-list and equal the origin the redeemed token names. |
| `remember_me` | no | Boolean, default `false`. |
| `project_hash`, `user_group_hash` | — | Rejected with `400` `EXT_8012`. |

Alias start errors:

| Status | Code | When |
| --- | --- | --- |
| `400` | `EXT_8012` | Body not a JSON object, forbidden field, or missing or oversized token. |
| `400` | `EXT_8013` | The redirect URI and return origin pair does not match exactly one Google binding. |
| `401` | `EXT_8012` | Redemption failed or the redeemed binding was rejected. |
| `401` | `EXT_8014` | State storage unavailable. |
| `403` | `EXT_8011` | Google connection disabled, or no usable `legacy_redeem` binding (database source). |
| `429` | `EXT_8030` | Start or provider-init redeem bucket exhausted; `Retry-After` is set. |
| `503` | `EXT_8010` | Google connection not configured, or the authorization URL could not be built. |

The callback, link, reauth and unlink aliases answer exactly as their `/auth/oauth/*`
equivalents; see [Error codes by endpoint](../oauth/reference.md#error-codes-by-endpoint).
`EXT_8015` and `EXT_8026` are defined but never emitted. Linking an identity that already
belongs to another user answers `409` `EXT_8027`.

## Provider-init redemption

`api.auth` calls the redeem endpoint once per start request: `POST` to
`PROVIDER_INIT_REDEEM_URL` (or the binding's encrypted redeem URL under the database
source), with `Authorization: Bearer <redeem token>`, a 5-second timeout and redirects
not followed. Request body:

```json
{
  "provider_init_token": "REPLACE_ME_OPAQUE_LOCAL_TOKEN",
  "provider": "google",
  "audience": "api.auth"
}
```

A `2xx` JSON object is expected, for example:

```json
{
  "active": true,
  "provider": "google",
  "audience": "api.auth",
  "purpose": "login",
  "project_hash": "REPLACE_ME_SERVER_SIDE_PROJECT_HASH",
  "user_group_hash": "REPLACE_ME_SERVER_SIDE_GROUP_HASH",
  "return_origin": "http://localhost:3000",
  "expires_in": 540
}
```

| Field | Rule |
| --- | --- |
| `active` | Must not be `false`. `signature_valid: false` or `signature_mismatch` also rejects. |
| `provider` | Must be `google`. |
| `audience` | When present, must be `api.auth`. |
| `purpose` | One of `login`, `link`, `reauth`, `auto_create`. The alias start always runs a login. |
| `project_hash` | Required. Under the database source it must equal the binding's project. |
| `user_group_hash` | Optional. Under the environment source it is the auto-create group; under the database source, when present, it must equal the binding's default group. |
| `return_origin` | Required; must be in `PROVIDER_INIT_RETURN_ORIGINS` (database source: the binding's return origins) and equal the origin of the start request. |
| `expires_in`, `expires_at` | At least one; the remaining lifetime must be above `0` and at most `600` seconds. |

Any failure answers `401` `EXT_8012` and records `google_oauth_provider_init_rejected`
with one of these `reason` values: `provider_init_not_configured`,
`provider_init_redeem_url_unsafe`, `provider_init_timeout_or_unavailable`,
`provider_init_http_rejected`, `provider_init_malformed_response`,
`provider_init_signature_mismatch`, `provider_init_inactive`,
`provider_init_provider_mismatch`, `provider_init_audience_mismatch`,
`provider_init_purpose_invalid`, `provider_init_binding_missing_project`,
`provider_init_return_origin_denied`, `provider_init_return_origin_mismatch`,
`provider_init_expired_or_ttl_invalid`, `provider_init_project_not_bound`,
`provider_init_group_not_bound`, `provider_init_redeem_failed`.

## Activity catalog `act-cat-064..074`

Recorded by the `/auth/google/*` routes only; `/auth/oauth/*` records `act-cat-107..127`
for the same events. A reauth and a cancellation on an alias record the generic
`oauth_reauth_succeeded` (`act-cat-117`) and `oauth_user_cancelled` (`act-cat-118`).

| ID | Activity type | Recorded when |
| --- | --- | --- |
| `act-cat-064` | `google_oauth_started` | A Google round trip starts (login, link or reauth). |
| `act-cat-065` | `google_oauth_provider_init_rejected` | The start body or the provider-init redemption is rejected, or the authorization start fails. |
| `act-cat-066` | `google_oauth_callback_received` | A callback arrives. |
| `act-cat-067` | `google_oauth_state_rejected` | State unknown, expired, reused, cookie-mismatched, or its connection became unavailable. |
| `act-cat-068` | `google_oauth_nonce_rejected` | ID-token nonce mismatch. |
| `act-cat-069` | `google_oauth_token_exchange_failed` | Google returned an error other than a cancellation, or the code exchange failed. |
| `act-cat-070` | `google_oauth_id_token_rejected` | Signature, `kid`, issuer, audience, `hd`, time or cross-check failure, or the identity key could not be derived. |
| `act-cat-071` | `google_oauth_login_succeeded` | A local session was issued. |
| `act-cat-072` | `google_oauth_login_denied` | Login refused; `sub_reason` names the cause. |
| `act-cat-073` | `google_oauth_external_account_linked` | Google identity linked. |
| `act-cat-074` | `google_oauth_external_account_unlinked` | Google identity soft-unlinked. |

Details carry fingerprints, reason codes and masked values only. The audit log tags alias
requests `authentication`, `oauth`, `google_oauth` and `external_idp` with
`auth_method='oauth'`; the redacted field list is in the
[OAuth reference](../oauth/reference.md#activity-codes).

## Redis keys

The aliases use the shared keys listed in the
[OAuth reference](../oauth/reference.md#redis-keys). Of the historical Google prefixes,
`google_oauth_rate:` is still written (by every provider), and `google_oauth_state:`,
`google_oauth_state_consumed:` and `google_oauth_reauth:` are only read, so round trips
started before the rename complete. `google_oauth_link:`, `google_oauth_jwks:` and
`provider_init_redeem:` are no longer used: link tokens are gone and JWKS documents are
cached in process memory.
