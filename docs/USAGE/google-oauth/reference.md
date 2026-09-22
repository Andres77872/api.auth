# Google OAuth Reference

Reference for environment keys, endpoints, response models, OAuth error taxonomy, activity catalog, redaction fields, and allowlist behavior.

> Provider boundary: this reference covers Google OAuth login/link contracts. Patreon is entitlement/link only and has separate route, S2S, retention, activity, and forbidden-browser-field references in [Patreon account linking](../patreon-link/README.md). Do not reuse Google `LoginResponse`, cookie, refresh-token, or callback semantics for Patreon.

## Configuration Keys

Values below are names only. Do not paste real secrets into docs. Use localhost examples in local smoke only.

| Key | Purpose | Notes |
| --- | --- | --- |
| `GOOGLE_OAUTH_ENABLED` | Runtime kill switch | Keep false/disabled until rollout gate passes. |
| `GOOGLE_OAUTH_CLIENT_ID` | Google OAuth client identifier | Use deployment secret/config management. |
| `GOOGLE_OAUTH_CLIENT_SECRET` | Google OAuth client credential | Rotate via runbook; never log or document the value. |
| `GOOGLE_OAUTH_DISCOVERY_URL` | OIDC discovery metadata URL | **Optional override.** Leave unset; `load_google_oauth_config` defaults to `https://accounts.google.com/.well-known/openid-configuration`. |
| `GOOGLE_OAUTH_AUTHORIZE_ENDPOINT` | Authorization endpoint | **Optional override.** Defaults to `https://accounts.google.com/o/oauth2/v2/auth`. |
| `GOOGLE_OAUTH_TOKEN_ENDPOINT` | Token endpoint | **Optional override.** Defaults to `https://oauth2.googleapis.com/token`. Used for exactly-once code exchange. |
| `GOOGLE_OAUTH_JWKS_URI` | JWKS endpoint | **Optional override.** Defaults to `https://www.googleapis.com/oauth2/v3/certs`. Cache TTL capped at `3600` seconds. |
| `GOOGLE_OAUTH_ISSUERS` | Accepted issuers | **Optional override.** Defaults to `https://accounts.google.com` and `accounts.google.com`. |
| `GOOGLE_OAUTH_SCOPES` | OAuth scopes | Must be exactly `openid email`. |
| `GOOGLE_OAUTH_ALLOWED_HOSTED_DOMAINS` | Optional Google Workspace `hd` restriction | Comma-separated domain list; empty (the default) allows **all** accounts, and `*` also allows all. A non-empty list restricts Workspace sign-in to those domains (case-insensitive); a non-matching `hd` is rejected with `OAUTH_WORKSPACE_DENIED` (`EXT_8023`). Consumer Gmail carries no `hd` and is always allowed. |
| `GOOGLE_OAUTH_REDIRECT_URIS` | Exact callback URI allowlist | Local examples: `http://localhost:8000/auth/google/callback`, `http://127.0.0.1:8000/auth/google/callback`. |
| `GOOGLE_OAUTH_RETURN_ORIGINS` | Exact frontend return-origin allowlist | Local examples: `http://localhost:3000`, `http://localhost:5173`. |
| `GOOGLE_OAUTH_PROVISIONING_MODE` | `disabled`, `link_only`, `auto_create`, or `both` | Production default must be `disabled` or `link_only`. |
| `GOOGLE_OAUTH_STATE_TTL_SECONDS` | OAuth state TTL | Max `600`. |
| `GOOGLE_OAUTH_RECENT_REAUTH_SECONDS` | Recent step-up lifetime | Default design value `300`. |
| `GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS` | JWKS cache cap | Max `3600`. |
| `GOOGLE_OAUTH_LEEWAY_SECONDS` | Exp/iat clock leeway | Max `30`. |
| `GOOGLE_OAUTH_STATE_PEPPER` | HMAC key for state Redis keys | Secret value, never printed. |
| `GOOGLE_OAUTH_PROVIDER_SUB_PEPPER` | HMAC key for Google `sub` authority | Secret value, never printed. |
| `GOOGLE_OAUTH_EMAIL_HASH_PEPPER` | HMAC key for email snapshot hash | Secret value, never printed. |
| `GOOGLE_OAUTH_FAIL_CLOSED_ON_REDIS_ERROR` | Redis failure policy | Should remain fail closed. |
| `PROVIDER_INIT_REDEEM_URL` | Server-to-server companion redeem endpoint | Local/test only in docs; production value omitted. |
| `PROVIDER_INIT_REDEEM_TOKEN` | Bearer trust-boundary credential | Secret value, never printed. |
| `PROVIDER_INIT_RETURN_ORIGINS` | Provider-init return-origin allowlist | Exact match; defaults can mirror return origins. |

The five Google endpoint keys — `GOOGLE_OAUTH_DISCOVERY_URL`,
`GOOGLE_OAUTH_AUTHORIZE_ENDPOINT`, `GOOGLE_OAUTH_TOKEN_ENDPOINT`,
`GOOGLE_OAUTH_JWKS_URI`, and `GOOGLE_OAUTH_ISSUERS` — are **optional
overrides**, not required settings. `src/Util/google_oauth_config.py` already
carries the correct Google values as built-in defaults, so leave all five unset
unless a deployment deliberately points at a different endpoint. Setting them to
placeholder values overrides the working defaults with garbage and breaks
sign-in. What a deployment actually must supply to enable the feature is
`GOOGLE_OAUTH_ENABLED`, `GOOGLE_OAUTH_CLIENT_ID`, `GOOGLE_OAUTH_CLIENT_SECRET`,
the redirect/return-origin allowlists, and the peppers/secrets above.

Rate-limit keys:

- `GOOGLE_OAUTH_START_RATE_LIMIT`, `GOOGLE_OAUTH_START_RATE_WINDOW_SECONDS`
- `GOOGLE_OAUTH_CALLBACK_RATE_LIMIT`, `GOOGLE_OAUTH_CALLBACK_RATE_WINDOW_SECONDS`
- `GOOGLE_OAUTH_PROVIDER_INIT_RATE_LIMIT`, `GOOGLE_OAUTH_PROVIDER_INIT_RATE_WINDOW_SECONDS`
- `GOOGLE_OAUTH_STATE_CONSUME_RATE_LIMIT`, `GOOGLE_OAUTH_STATE_CONSUME_RATE_WINDOW_SECONDS`
- `GOOGLE_OAUTH_SUB_COLLISION_RATE_LIMIT`, `GOOGLE_OAUTH_SUB_COLLISION_RATE_WINDOW_SECONDS`
- `GOOGLE_OAUTH_UNLINK_RATE_LIMIT`, `GOOGLE_OAUTH_UNLINK_RATE_WINDOW_SECONDS`

## Exact Allowlist Behavior

Redirect URI and return-origin checks are exact string matches. No suffix matching, wildcard matching, implicit scheme upgrades, or production-domain defaults are allowed.

Local examples only:

- `http://localhost:8000/auth/google/callback`
- `http://127.0.0.1:8000/auth/google/callback`
- `http://localhost:3000`
- `http://localhost:5173`

## Endpoints

> **Deprecated aliases.** `/auth/google/*` delegates to the provider-agnostic pipeline with the connection key `google` and stays available for existing consumers. New integrations should use [`/auth/oauth/*`](../oauth/reference.md). Linking and re-authentication complete inside the callback; the former `POST /auth/google/link/finish` route has been removed because nothing could ever satisfy it.

| Endpoint | Method | Request | Success | Failure |
| --- | --- | --- | --- | --- |
| `/auth/google/start` | POST | `GoogleOAuthStartRequest` | `303` redirect to Google, OAuth binding cookie | Disabled provider returns `OAUTH_PROVIDER_DISABLED` / `EXT_8011` with explicit `403`; otherwise neutral `EXT_8xxx` (`EXT_8012` redeem, `EXT_8013` allowlist, `EXT_8014` state, `EXT_8030` rate-limit); no strict hash leakage |
| `/auth/google/callback` | GET | `code`, `state`, optional `error`/`error_description` | For a login state: existing `LoginResponse` + existing cookies. For a link state: `ExternalIdentityLinkResponse` (no new session). For a reauth state: `{"reauthenticated": true}` and the recent-reauth marker is recorded. The purpose comes from the server-side state record only. | Neutral `EXT_8xxx`; no provider/local enumeration. `error=access_denied` returns `OAUTH_USER_CANCELLED` / `EXT_8031` (`400`) and consumes the state. A verified-e-mail collision with an existing local account returns `OAUTH_ACCOUNT_LINK_REQUIRED` / `EXT_8032` (`409`). |
| `/auth/google/link/start` | POST | Local session + recent reauth (`require_recent_reauthentication`, op `google_oauth_link`); provisioning `link_only`/`both` | `303` redirect to Google | `OAUTH_PROVISIONING_DENIED` / `EXT_8024` (`401`) neutral denial on any failure |
| `/auth/google/reauth/start` | POST | Local session (no provisioning gate, no pre-required recent reauth) | `303` redirect to Google with `prompt=login` step-up intent | `OAUTH_PROVISIONING_DENIED` / `EXT_8024` (`401`) on failure |
| `/auth/google/unlink` | DELETE | Local session + recent reauth (op `google_oauth_unlink`) | `ExternalIdentityUnlinkResponse` (with `sessions_revoked`) | `EXTERNAL_IDENTITY_NOT_LINKED` / `EXT_8028` (`404`), `OAUTH_PASSWORD_REQUIRED_FOR_UNLINK` / `EXT_8029` (`409`), or `OAUTH_RATE_LIMITED` / `EXT_8030` (`429`, unlink-specific) |

## Models

`GoogleOAuthStartRequest`:

- `provider_init_token`: required opaque token from companion.
- `redirect_uri`: optional, exact-match allowlisted.
- `return_origin`: optional, exact-match allowlisted.
- `remember_me`: optional local session preference.

`GoogleOAuthStartResponse` is for explicit non-browser/test negotiation only. Browser flow redirects by default.

`ExternalIdentityInfo` returns only secret-safe provider metadata: provider, masked subject fingerprint, masked email snapshot, verification snapshot, linked/last-seen timestamps, and status.

Callback success uses `LoginResponse`, not an OAuth-specific success model.

## Error Codes

OAuth provider/protocol/external identity errors use enum symbols whose values stay in the `EXT_8xxx` family.

| Symbol | Value | Typical Status | Public Posture |
| --- | --- | --- | --- |
| `OAUTH_PROVIDER_NOT_CONFIGURED` | `EXT_8010` | 503 | Provider unavailable |
| `OAUTH_PROVIDER_DISABLED` | `EXT_8011` | 403 (start) / 404 (map default) | Provider unavailable |
| `OAUTH_PROVIDER_INIT_INVALID` | `EXT_8012` | 401 | Neutral OAuth failure |
| `OAUTH_REDIRECT_URI_NOT_ALLOWED` | `EXT_8013` | 400 | Neutral OAuth failure |
| `OAUTH_STATE_INVALID` | `EXT_8014` | 401 | Neutral OAuth failure |
| `OAUTH_STATE_EXPIRED` | `EXT_8015` | 401 | Neutral OAuth failure |
| `OAUTH_STATE_REUSED` | `EXT_8016` | 401 | Neutral OAuth failure |
| `OAUTH_NONCE_MISMATCH` | `EXT_8017` | 401 | Neutral OAuth failure |
| `OAUTH_CODE_EXCHANGE_FAILED` | `EXT_8018` | 502 | Provider unavailable |
| `OAUTH_ID_TOKEN_INVALID` | `EXT_8019` | 401 | Neutral OAuth failure |
| `OAUTH_ISSUER_MISMATCH` | `EXT_8020` | 401 | Neutral OAuth failure |
| `OAUTH_AUDIENCE_MISMATCH` | `EXT_8021` | 401 | Neutral OAuth failure |
| `OAUTH_TOKEN_EXPIRED` | `EXT_8022` | 401 | Neutral OAuth failure |
| `OAUTH_WORKSPACE_DENIED` | `EXT_8023` | 401 | Neutral OAuth failure |
| `OAUTH_PROVISIONING_DENIED` | `EXT_8024` | 401 | Neutral OAuth failure |
| `OAUTH_PROJECT_ACCESS_DENIED` | `EXT_8025` | 403 | Neutral access denial |
| `EXTERNAL_IDENTITY_ALREADY_LINKED` | `EXT_8026` | 409 | External identity action denied |
| `EXTERNAL_IDENTITY_SUB_CONFLICT` | `EXT_8027` | 409 | External identity action denied |
| `EXTERNAL_IDENTITY_NOT_LINKED` | `EXT_8028` | 404 | External identity action denied |
| `OAUTH_PASSWORD_REQUIRED_FOR_UNLINK` | `EXT_8029` | 409 | Establish fallback auth first |
| `OAUTH_RATE_LIMITED` | `EXT_8030` | 429 | Retry later |

`EXTERNAL_IDENTITY_ALREADY_LINKED` / `EXT_8026` is defined in the enum but is **not currently emitted**. Linking an identity that already belongs to another user returns `EXTERNAL_IDENTITY_SUB_CONFLICT` / `EXT_8027` (`409`) from the callback; treat `EXT_8026` as a reserved code.

## Activity Catalog `act-cat-064..074`

| ID | ActivityType | Meaning |
| --- | --- | --- |
| `act-cat-064` | `GOOGLE_OAUTH_STARTED` | Provider-init redeemed and authorization URL created. |
| `act-cat-065` | `GOOGLE_OAUTH_PROVIDER_INIT_REJECTED` | Provider-init missing, expired, replayed, or redeem failed. |
| `act-cat-066` | `GOOGLE_OAUTH_CALLBACK_RECEIVED` | Callback entered after basic query parsing. |
| `act-cat-067` | `GOOGLE_OAUTH_STATE_REJECTED` | State missing, expired, replayed, or mismatched. |
| `act-cat-068` | `GOOGLE_OAUTH_NONCE_REJECTED` | ID-token nonce mismatch. |
| `act-cat-069` | `GOOGLE_OAUTH_TOKEN_EXCHANGE_FAILED` | Google token endpoint or invalid-grant failure. |
| `act-cat-070` | `GOOGLE_OAUTH_ID_TOKEN_REJECTED` | Signature, `kid`, issuer, audience, `hd`, time, or google-auth cross-check failure. |
| `act-cat-071` | `GOOGLE_OAUTH_LOGIN_SUCCEEDED` | Local session issued. |
| `act-cat-072` | `GOOGLE_OAUTH_LOGIN_DENIED` | Provisioning, project access, consumer policy, or collision denial. |
| `act-cat-073` | `GOOGLE_OAUTH_EXTERNAL_ACCOUNT_LINKED` | Google external account linked. |
| `act-cat-074` | `GOOGLE_OAUTH_EXTERNAL_ACCOUNT_UNLINKED` | Google external account soft-unlinked. |

## Redacted Audit Fields

At minimum, audit/error/logging redacts or omits:

```text
provider_init_token, authorization_code, oauth_code, code, state, oauth_state,
nonce, code_verifier, pkce_verifier, id_token, google_id_token,
google_id_token_claims, access_token, refresh_token, google_access_token,
google_refresh_token, google_sub, provider_sub, google_email, google_hd,
oauth_link_token, project_hash, user_group_hash
```

`/auth/google/callback` remains audited with redaction. `/auth/google/*` uses `auth_method='oauth'` and tags `authentication`, `google_oauth`, and `external_idp`; 4xx/5xx outcomes are security events.

## Redis Namespaces

- `google_oauth_state:*`
- `google_oauth_state_consumed:*`
- `google_oauth_link:*`
- `google_oauth_reauth:*`
- `google_oauth_jwks:*`
- `google_oauth_rate:*` and bucket-specific rate prefixes
- `provider_init_redeem:*`

Raw state is not embedded in keys; HMAC/fingerprint material is used.
