# 05 — Target Architecture: Provider Adapters and Per-Project Connections

This is a design proposal. Nothing here is implemented. New modules are written in dotted form (`src.Util.oauth.registry`) because they do not exist yet.

## 1. Design goals

1. **Any project**: every OAuth setting that differs between projects lives in the database and is resolved from the project — never from the process environment, never from the browser.
2. **Any provider**: adding a standards-compliant OIDC provider is a data operation; adding a non-standard provider is one new adapter class and one catalog row, with no change to routes, state store, identity resolution or session issuance.
3. **No regression of the security properties** listed at the end of [01-current-state.md](01-current-state.md).
4. **Magic Worlds keeps working** throughout, without a coordinated big-bang release.
5. The environment keeps only what is genuinely deployment-wide: encryption keys, peppers, global kill switch, global ceilings for TTLs and rate limits.

## 2. The three-level model

```text
PROVIDER TYPE  (code + catalog row)      "google", "microsoft", "apple", "github", "discord", "oidc"
      |  implemented by an adapter class; declares capabilities; kill switch in the catalog
      v
CONNECTION     (database row)             credentials + endpoints + restrictions for one client
      |  client_id, encrypted client_secret, issuer/discovery, scopes, domain/tenant restrictions
      v
PROJECT BINDING (database row)            policy for one project using one connection
         enabled, connection key, redirect URIs, return origins, provisioning mode,
         default user group, JIT enrolment policy, delivery mode, rate-limit overrides
```

Why two data levels instead of one "project OAuth config" row: client credentials and project policy have different owners and lifecycles. One company with three projects normally wants one Google Cloud client (one consent screen) but three different default groups and origin lists. It is the same split the billing subsystem uses (`billing_groups` versus `billing_group_projects`). A project that wants full isolation simply owns a connection used by no other project.

## 3. Adapter contract

```python
# Proposed: src.Util.oauth.provider  (shape only)

@dataclass(frozen=True)
class ProviderCapabilities:
    protocol: Literal["oidc", "oauth2"]
    pkce: bool                  # S256 sent when True; never configurable per connection
    nonce: bool                 # OIDC nonce bound in state and checked in the ID token
    issuer_response_param: bool # RFC 9207 `iss` validated when the IdP supports it
    callback_methods: frozenset[str]   # {"GET"} or {"GET", "POST"} (Apple form_post)
    subject_scope: Literal["global", "issuer", "tenant", "team", "client"]
    email_trust: Literal["verified_by_provider", "unverified", "admin_controlled"]
    supports_login: bool        # False => link-only provider type
    tenant_configurable_endpoints: bool  # True only for the generic "oidc" type


@dataclass(frozen=True)
class ExternalIdentity:
    provider_type: str          # "google"
    identity_namespace: str     # "google" | "microsoft:<tid>" | "apple:<team>" | "oidc:<issuer>"
    subject: str                # raw, never persisted, never logged
    email: str | None           # untrusted display data
    email_verified: bool
    email_trust: str
    display_name: str | None
    attributes: Mapping[str, str]      # small allow-listed extras, e.g. {"hd": "example.com"}


class OAuthProviderAdapter(Protocol):
    provider_type: str
    capabilities: ProviderCapabilities

    def validate_connection(self, connection: ConnectionConfig) -> list[str]:
        """Static validation at admin-write time. Returns human-readable problems."""

    async def probe_connection(self, connection: ConnectionSecrets) -> ProbeResult:
        """Optional live check (fetch discovery, check issuer pin). Never persists."""

    def build_authorization_url(self, connection: ConnectionConfig, tx: OAuthTransaction) -> str: ...

    async def exchange_code(
        self, connection: ConnectionSecrets, tx: OAuthTransaction, callback: CallbackParams
    ) -> TokenResponse: ...

    async def resolve_identity(
        self, connection: ConnectionConfig, tx: OAuthTransaction, tokens: TokenResponse
    ) -> ExternalIdentity:
        """OIDC: verify the ID token. OAuth2: call the user API. Must raise OAuthIdentityError
        with a neutral reason code on any failure. Must not return provider tokens."""

    def enforce_restrictions(self, connection: ConnectionConfig, identity: ExternalIdentity) -> None:
        """Hosted-domain / tenant / organisation allow-lists."""
```

Rules the contract enforces by construction:

- **Adapters never touch the database, Redis, sessions or HTTP responses.** They turn a connection plus a callback into an `ExternalIdentity`, nothing else. Everything downstream is shared and provider-blind.
- **Provider tokens never leave the adapter.** `resolve_identity` returns identity only. A future provider that needs stored tokens (entitlement sync, like Patreon) is a different capability with its own encrypted store, not part of login.
- **Security capabilities are code, not data.** A tenant can choose scopes and domains; it cannot turn off PKCE, nonce or signature checks.
- **Failures are classified by a closed enum**, not by substring-matching exception messages as `_id_token_error_code` does today.

### Adapter classes

| Class | Covers | Specifics |
| --- | --- | --- |
| `GenericOIDCAdapter` | Any compliant IdP; base for the next three | Discovery with issuer pin and cache; JWKS via a process-wide cached client keyed by URI; algorithm allow-list; `iss`, `aud`, `azp`, `exp`, `iat`, `nonce` checks (the existing `validate_google_claims` logic generalised); namespace `oidc:<issuer>`. |
| `GoogleAdapter(GenericOIDCAdapter)` | Google | Compiled-in endpoints (tenant cannot override); two accepted issuer strings; `hd` allow-list from the connection; optional `google-auth` cross-check; namespace constant `google`. |
| `MicrosoftAdapter(GenericOIDCAdapter)` | Entra ID, personal accounts | Issuer template validation against the `tid` claim; tenant allow-list; subject is `oid`; namespace `microsoft:<tid>`; e-mail trust `admin_controlled`. |
| `AppleAdapter(GenericOIDCAdapter)` | Sign in with Apple | Generates the ES256 client-secret JWT per exchange from an encrypted private key, team id and key id; accepts POST callback; coerces string `email_verified`; namespace `apple:<team_id>`. |
| `OAuth2UserInfoAdapter` | Base for non-OIDC | No ID token; calls a user endpoint with the access token; declarative mapping for subject / e-mail / verified / name. |
| `GitHubAdapter`, `DiscordAdapter` | GitHub, Discord | Compiled-in endpoints and mappings; GitHub makes the second e-mails call and selects primary + verified. |
| `FakeAdapter` | Tests only | Registered by test fixtures, never importable from the production registry. Replaces the in-route test branches (gap G-03). |

### Registry

```python
# Proposed: src.Util.oauth.registry  (shape only)
_REGISTRY: dict[str, OAuthProviderAdapter] = {}

def register(adapter: OAuthProviderAdapter) -> None: ...
def get_adapter(provider_type: str) -> OAuthProviderAdapter:  # raises OAuthProviderUnknown
```

Registration is explicit at application start-up (a list in one module), not import-time side effects or entry-point discovery — consistent with how routers are included in [main.py](../../src/main.py). A provider type is usable only when it is **both** registered in code **and** `enabled` in the catalog table; the catalog is the run-time kill switch, the registry is the capability.

## 4. Connection resolution

```text
resolve(project_id, connection_key)
  1. binding  = project_oauth_bindings[(project_id, connection_key)]   else OAUTH_PROVIDER_NOT_CONFIGURED
  2. binding.enabled and connection.status == 'active'
     and catalog[provider_type].status == 'enabled'
     and global kill switch on                                          else OAUTH_PROVIDER_DISABLED
  3. connection.credential_status == 'active'                           else OAUTH_PROVIDER_NOT_CONFIGURED
  4. adapter = registry[connection.provider_type]                       else OAUTH_PROVIDER_NOT_CONFIGURED
  -> ResolvedConnection(config, binding, adapter)       # no secret yet
```

- Non-secret configuration may be cached in-process for a short TTL (30–60 s) with explicit invalidation on admin writes, mirroring `load_google_oauth_config()`'s "cheap to call per request" property.
- The client secret is decrypted **only inside the callback**, immediately before the token exchange, onto a `repr`-suppressed object that goes out of scope with the request.
- Both error codes already exist (`EXT_8010`, `EXT_8011`) with neutral public messages.

## 5. Init handshake (replaces the single global redeem URL)

Recommended option B from [04-research.md](04-research.md):

```text
consumer backend --> api.auth   POST /auth/oauth/init
    Authorization: project-scoped API key (or project client credential)
    body: { "connection": "google", "purpose": "login",
            "return_origin": "https://app.example", "remember_me": false }

api.auth:
    project        := from the authenticated credential        (never from the body)
    binding        := resolve(project, connection)
    return_origin  := must be in binding.return_origins        (exact match)
    user_group     := binding.default_user_group_id            (never from the body)
    writes init record to Redis: single use, TTL <= 600 s, keyed by HMAC of the token
    --> { "init_token": "<opaque 256-bit>", "expires_in": 300 }

browser / BFF --> api.auth      POST /auth/oauth/start  { "init_token", "redirect_uri" }
    consumes the init record (GETDEL + replay marker), creates state, 303 to the IdP
```

What this changes relative to today:

| Today | Proposed |
| --- | --- |
| Consumer mints and stores the token, implements redeem endpoint, replay markers, fingerprints | Consumer makes one authenticated POST |
| `api.auth` makes an outbound call to a URL from the environment | No outbound call; no SSRF surface; no availability coupling |
| Project and group are **asserted by the caller** | Project is **derived from the credential**; group comes from `api.auth`'s own binding row |
| One static bearer for the deployment | Existing per-project API keys with rotation, expiry, revocation and audit |
| Provider literal `"google"` in request and response | `connection` key chosen by the consumer from its project's bindings |

**Compatibility bridge.** A binding may carry `init_mode = 'legacy_redeem'` with an encrypted redeem URL and bearer. `/auth/google/start` keeps accepting `provider_init_token` and uses the legacy path for that one binding. The bridge is removed once Magic Worlds moves to `/auth/oauth/init`. While the bridge exists, the redeemed `project_hash` **must equal** the binding's project and the redeemed `user_group_hash` **must equal** the binding's default group; a mismatch is rejected. That closes findings F-26 and F-27 even before the consumer migrates.

## 6. Routes

| New route | Replaces | Notes |
| --- | --- | --- |
| `POST /auth/oauth/init` | consumer-side provider-init issue + redeem | Server-to-server, project credential. |
| `GET /auth/oauth/providers` | — | Project credential. Returns `[{connection, provider_type, display_name}]` for enabled bindings so login pages render buttons from data. |
| `POST /auth/oauth/start` | `POST /auth/google/start` | Body carries only `init_token`, `redirect_uri`. Connection and project come from the init record. |
| `GET` and `POST /auth/oauth/callback` | `GET /auth/google/callback` | Connection comes from the **state record only**. POST accepted for `form_post` providers. Branches on `purpose`: `login`, `link`, `reauth`. |
| `POST /auth/oauth/{connection}/link/start` | `/auth/google/link/start` | Session + recent reauth. Project from the session. |
| `POST /auth/oauth/{connection}/reauth/start` | `/auth/google/reauth/start` | Session. |
| `DELETE /auth/oauth/{connection}/link` | `DELETE /auth/google/unlink` | Session + recent reauth. |
| `GET /auth/oauth/links` | — | Session. Lists the caller's linked identities (masked). |
| `/auth/google/*` | — | Thin aliases that call the generic handlers with `connection="google"`; deprecated, removed after consumers migrate. |
| `/admin/oauth/*` | — | See [06-data-model.md](06-data-model.md). |

`link/finish` disappears: once the callback branches on `purpose`, a link completes inside the callback (it already has the verified identity and the state record holds the initiating `user_id`). This removes the unimplementable hand-off that gap G-01 describes. `reauth` likewise completes in the callback by calling `mark_recent_reauth` after verifying that the returned identity is linked to the state's `user_id` (gap G-02).

## 7. Shared pipeline (provider-blind)

```text
callback(code, state, [iss], [error])
  1  rate limit (ip, state fingerprint, project, connection)
  2  tx := state_store.consume(state)              # single use; yields connection_id, project_id,
                                                   #   purpose, nonce, verifier, redirect_uri, user_id?
  3  if error == access_denied -> OAUTH_USER_CANCELLED (new neutral code)
  4  rc := resolve(tx.project_id, tx.connection_id)  # re-checked: may have been disabled meanwhile
  5  if rc.adapter.capabilities.issuer_response_param: require iss == rc.config.issuer
  6  secrets := decrypt(rc)                          # scoped to steps 7-8
  7  tokens  := await rc.adapter.exchange_code(secrets, tx, callback)
  8  ident   := await rc.adapter.resolve_identity(rc.config, tx, tokens); drop tokens
  9  rc.adapter.enforce_restrictions(rc.config, ident)
 10  key := HMAC(pepper, ident.subject) under namespace ident.identity_namespace
 11  branch tx.purpose:
       login  -> find user by (namespace, key)
                   found     -> active consumer?  -> JIT enrolment per binding policy
                   not found -> binding.provisioning allows auto-create? -> create in binding.default group
                 -> project pin (unchanged logic) -> issue token pair
       link   -> require tx.user_id; link (namespace, key) to it; conflict -> EXTERNAL_IDENTITY_SUB_CONFLICT
       reauth -> require (namespace, key) linked to tx.user_id; mark_recent_reauth
 12  activity + audit with provider_type, connection fingerprint, project id (redacted as today)
```

Steps 1–6 and 10–12 are written once. Only steps 7–9 vary by provider. Compare with today, where all twelve live in one Google-named module.

## 8. Proposed package layout

```text
src.Util.oauth
    provider        Protocol, dataclasses, error enum
    registry        register / get_adapter, start-up registration list
    connections     ConnectionConfig, ProjectBinding, resolve(), cache + invalidation
    secrets         thin OAuth-named wrapper over the shared encryption helper
    state           today's oauth_state, neutral prefixes, connection-aware records
    init_tokens     mint / consume for POST /auth/oauth/init (+ legacy redeem bridge)
    identity        namespace + HMAC + fingerprints + masking (moved out of the Google verifier)
    pipeline        the 12-step shared flow
    rate_limit      today's limiter with project/connection dimensions
    jwks            process-wide cached JWKS + discovery clients
    adapters
        oidc, google, microsoft, apple, oauth2_userinfo, github, discord
src.routes.auth_oauth         generic routes + /auth/google aliases
src.routes.admin_oauth        connection and binding administration
src.Util.db.db_oauth_connections   stored-procedure wrappers
```

The shared encryption helper would be extracted from [security.py](../../src/Util/billing/security.py) into a neutral module that both billing and OAuth import, leaving billing's public function names in place as aliases.

## 9. What stays in the environment

The dividing line is **deployment-wide security posture stays; anything a project or a provider could reasonably want to differ moves to the database**. Of the 43 variables in use today (24 `GOOGLE_OAUTH_*` plus 3 `PROVIDER_INIT_*` plus 16 rate-limit variables), 17 move to the database, 1 disappears, and 25 remain as deployment-level settings — but **every remaining one loses its `GOOGLE_` prefix**, because none of them is Google-specific once there are several providers.

### 9.1 Stays in the environment (deployment level)

| Variable (proposed) | Purpose | Replaces |
| --- | --- | --- |
| `OAUTH_ENABLED` | Global kill switch, ANDed with the catalog row and the binding flags. **Not** per provider any more — per-provider enablement is the catalog, per-project is the binding | `GOOGLE_OAUTH_ENABLED` |
| `OAUTH_STATE_PEPPER`, `OAUTH_PROVIDER_SUB_PEPPER`, `OAUTH_EMAIL_HASH_PEPPER`, `OAUTH_PASSWORDLESS_HASH_SECRET` | Deployment-wide HMAC keys. Must fall back to the existing `GOOGLE_OAUTH_*` names **with identical values** — see risk R-01 | same-named Google variables |
| `OAUTH_SECRET_ENCRYPTION_KEY`, `…_KEY_ID`, `OAUTH_SECRET_DECRYPTION_KEYS_JSON`, `OAUTH_SECRET_HMAC_KEY` | Encrypt and row-bind connection secrets; rotation map | new |
| `OAUTH_FAIL_CLOSED_ON_REDIS_ERROR` | Fail-closed posture when Redis is unavailable | `GOOGLE_OAUTH_FAIL_CLOSED_ON_REDIS_ERROR` |
| `OAUTH_LEEWAY_SECONDS` | Clock-skew tolerance for token validation — a property of this host's clock, not of a project | `GOOGLE_OAUTH_LEEWAY_SECONDS` |
| `OAUTH_JWKS_CACHE_TTL_SECONDS` | Cache tuning for a process-wide cache | `GOOGLE_OAUTH_JWKS_CACHE_TTL_SECONDS` |
| `OAUTH_RECENT_REAUTH_SECONDS` | Step-up freshness window; a platform-wide security policy shared with non-OAuth reauth | `GOOGLE_OAUTH_RECENT_REAUTH_SECONDS` |
| `OAUTH_MAX_STATE_TTL_SECONDS` | **Ceiling** a binding may lower but never exceed | `GOOGLE_OAUTH_STATE_TTL_SECONDS` |
| 8 pairs of `OAUTH_*_RATE_LIMIT` / `*_RATE_WINDOW_SECONDS` | **Ceilings**; `rate_limit_overrides` on a binding may only lower them | the 16 `GOOGLE_OAUTH_*_RATE_*` variables |
| `OAUTH_TRUSTED_PROXY_CIDRS` | When to honour `X-Forwarded-For` (gap G-07) | new |
| `OAUTH_ALLOW_PRIVATE_IDP_HOSTS` | Development-only SSRF relaxation for local IdPs | new |

### 9.2 Moves to the database

| Today | Goes to | Level |
| --- | --- | --- |
| `GOOGLE_OAUTH_CLIENT_ID` | `oauth_connections.client_id` | connection |
| `GOOGLE_OAUTH_CLIENT_SECRET` | `oauth_connections.client_secret_ciphertext`, encrypted | connection |
| `GOOGLE_OAUTH_SCOPES` | `oauth_connections.scopes` | connection |
| `GOOGLE_OAUTH_DISCOVERY_URL`, `…_AUTHORIZE_ENDPOINT`, `…_TOKEN_ENDPOINT`, `…_JWKS_URI`, `…_ISSUERS` | compiled into `GoogleAdapter`; the `oauth_connections` endpoint columns are honoured **only** for the generic `oidc` type | code / connection |
| `GOOGLE_OAUTH_ALLOWED_HOSTED_DOMAINS` | `oauth_connections.restrictions` | connection |
| `GOOGLE_OAUTH_REDIRECT_URIS` | `project_oauth_allowed_urls`, one row per URI | binding |
| `GOOGLE_OAUTH_RETURN_ORIGINS`, `PROVIDER_INIT_RETURN_ORIGINS` | `project_oauth_allowed_urls`, one row per origin | binding |
| `GOOGLE_OAUTH_PROVISIONING_MODE` | `project_oauth_bindings.provisioning_mode` | binding |
| `GOOGLE_OAUTH_DEFAULT_USER_GROUP_HASH` | `project_oauth_bindings.default_user_group_id` — and it finally does something (it is dead today, finding F-30) | binding |
| `GOOGLE_OAUTH_STATE_TTL_SECONDS` | `project_oauth_bindings.state_ttl_seconds`, capped by the env ceiling | binding |
| `PROVIDER_INIT_REDEEM_URL`, `PROVIDER_INIT_REDEEM_TOKEN` | `project_oauth_bindings.legacy_redeem_*`, encrypted — and both disappear entirely once the consumer moves to `POST /auth/oauth/init` in Phase 6 | binding, temporary |

### 9.3 Disappears

`GOOGLE_OAUTH_LINK_TOKEN_TTL_SECONDS` — separate link tokens stop existing once the callback branches on `purpose` (section 6); a link transaction is ordinary OAuth state and uses the same TTL.

### 9.4 The rule for judging a new setting

Ask: *could two projects on this deployment legitimately want different values?* If yes it belongs in the binding. Could two providers? Then the connection or the adapter. If it is a cryptographic key, a fail-closed posture, or a ceiling that protects the host, it stays in the environment — and a binding may only ever move a ceiling downwards, never upwards.

## 10. Bootstrap from the environment

On start-up, when `GOOGLE_OAUTH_CLIENT_ID` is set and no connection exists yet, an **explicit, operator-run** command (not an implicit start-up side effect) imports the environment configuration as: one `google` connection, plus one binding for the project the operator names, with `init_mode = 'legacy_redeem'` carrying the current redeem URL and bearer. After that, the `GOOGLE_OAUTH_*` client variables are ignored with a logged deprecation warning, following the precedent in [config.py](../../src/Util/stripe/config.py) where global Stripe keys became "migration-only".

Making it explicit avoids a class of surprise where a stale environment variable silently re-creates a connection that an administrator deleted.
