# 04 — Research

Background research that informs the target design. Each section ends with the design consequence for `api.auth`.

## 1. Two protocol families an adapter layer must cover

"OAuth login" in practice means two different things:

| Family | Identity proof | Examples | What varies |
| --- | --- | --- | --- |
| **OpenID Connect (OIDC)** | A signed **ID token** (JWT) returned by the token endpoint, verified locally against the issuer's JWKS. | Google, Microsoft Entra ID, Apple, Okta, Auth0, Keycloak, GitLab, LinkedIn (current API), Twitch, Slack | Discovery URL, issuer validation rules, signing algorithms, extra claims, client authentication method. |
| **Plain OAuth 2.0 + user API** | No ID token. The client calls a provider REST endpoint with the access token to learn who the user is. | GitHub, Discord, Facebook Login (classic), Reddit, Spotify, X | User endpoint URL, response shape, where the stable id lives, how verified e-mail is obtained, PKCE/nonce availability. |

OIDC providers differ from each other mostly in *data* (URLs, claim names). Plain OAuth 2.0 providers differ in *behaviour* (extra HTTP calls, custom JSON shapes).

**Consequence.** Two base adapters — a discovery-driven `GenericOIDCAdapter` configurable purely by database rows, and an `OAuth2UserInfoAdapter` with a declarative field mapping — cover the large majority of providers. Provider-specific subclasses are needed only for genuine quirks (section 2). This is what allows "add a new enterprise OIDC IdP" to be a data operation, not a deployment.

## 2. Provider quirk matrix

| Provider | Family | Stable subject | Subject scope | PKCE | Nonce | E-mail trust | Notable quirks |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Google | OIDC | `sub` | **Global** — same for every client id | Yes | Yes | `email_verified` boolean, reliable | `hd` claim for Workspace; two valid issuer strings; no refresh token unless `access_type=offline`. |
| Microsoft Entra ID | OIDC | `oid` + `tid` (not `sub`) | `sub` is **pairwise per application**; `oid` is tenant-wide | Yes | Yes | **Do not trust** `email` / `upn` for identity or authorization | Issuer is per tenant; the multi-tenant `common` discovery document returns an issuer *template* containing `{tenantid}`, so a plain string comparison fails; personal accounts use a fixed consumer tenant id. |
| Apple | OIDC (partial) | `sub` | Per developer **team** | Yes | Yes | `email_verified` may be the **string** `"true"`; `is_private_email` marks relay addresses | `client_secret` is an ES256 JWT signed with a downloaded key, valid at most six months; callback is an HTTP **POST** (`response_mode=form_post`) whenever `name` or `email` scope is requested; name and e-mail are delivered only on the *first* authorization. |
| GitHub | OAuth 2.0 | numeric `id` from the user API | Global | Yes (S256, optional, added mid-2025) | No | Separate e-mails API call; pick `primary` and `verified` | No ID token, no discovery; token endpoint answers form-encoded unless `Accept: application/json`. |
| Discord | OAuth 2.0 | `id` from `/users/@me` | Global | Yes | No | `verified` boolean | Scopes `identify email`. |
| Facebook Login | OAuth 2.0 (OIDC only in Limited Login) | app-scoped `id` | **Per app** | Partial | Limited Login only | E-mail may be absent | Graph API versioned URLs. |
| Generic OIDC (Okta, Auth0, Keycloak, …) | OIDC | `sub` | Per **issuer**; some IdPs can be configured pairwise | Usually | Yes | Varies by tenant configuration | The same provider *type* appears many times with different issuers. |

**Consequences.**

1. The current validator's rule "`email_verified` must be a boolean" would reject Apple. Claim normalisation belongs in the adapter, before generic validation.
2. The current verifier's mandatory `google-auth` cross-check and RS256-only rule are Google-specific; Apple signs with RS256 today but other IdPs use ES256/PS256. Accepted algorithms must come from discovery metadata intersected with a server-side allow-list that never includes `none` or symmetric algorithms.
3. The callback must accept `POST` with a form body for Apple.
4. "Client secret" is not always a static string; the adapter must own client authentication (static secret, signed JWT, or none for public clients).
5. The subject used for the identity key is adapter-defined (`oid` for Microsoft), and its **namespace** is not the provider type (section 3).

## 3. Identity keys: global versus pairwise subjects

OIDC Core defines the identity of an end user as the pair **(`iss`, `sub`)** and explicitly allows *pairwise* subject identifiers, where the provider gives each client a different `sub` for the same person.

`api.auth` today keys identities on `(provider, HMAC(pepper, sub))`. That is correct for Google only by a property of Google: its `sub` is unique across all Google accounts, never reused, and identical for every client id. The moment configuration becomes per project, each project may have **its own client id**, so the question "does the same human get the same subject at project A's client and project B's client?" decides whether the global-user model still works.

| Case | Same person, two projects, two client ids | What the key must contain |
| --- | --- | --- |
| Google, GitHub, Discord | Same subject | provider-wide namespace (e.g. `google`) |
| Microsoft using `oid` + `tid` | Same `oid` within a tenant | `microsoft:<tid>` |
| Microsoft using `sub`, Facebook | **Different** subject per client | would have to include the client id → the user appears as two people |
| Apple | Same within one developer team, different across teams | `apple:<team_id>` |
| Two unrelated Keycloak realms both typed `oidc` | Subjects may **collide** (`sub = "1001"` in both) | issuer URL |

**Consequence.** Replace the `provider` dimension of the uniqueness key with an **identity namespace** string computed by the adapter from the connection: a constant for global-subject providers, issuer- or tenant- or team-qualified otherwise. Existing rows migrate to namespace `google` with no re-hashing, because the HMAC input (the raw `sub`) and the pepper do not change. See [06-data-model.md](06-data-model.md).

A second consequence: **the subject pepper must stay a single deployment-level secret.** A per-project or per-connection pepper would make the same Google account hash differently per project and silently fork every user. Peppers are not configuration and must not move to the database.

## 4. E-mail is not an identifier

The 2023 "nOAuth" class of account-takeover bugs came from relying parties matching users on the Microsoft `email` claim, which a tenant administrator can set to any value. Microsoft's own claims reference says never to use `email` or `upn` for authorization decisions. The same reasoning applies to any IdP a project administrator can configure themselves — which is exactly what per-project generic OIDC connections enable.

`api.auth` already does the right thing: identity is the subject, e-mail is a masked snapshot, provider verification never activates the local e-mail, and nothing merges by e-mail. This must become an explicit invariant of the adapter contract rather than a property of the Google code path:

- Adapters return e-mail as **untrusted display data** plus a `email_verified` flag and an `email_trust` level declared per provider type (`verified_by_provider`, `unverified`, `admin_controlled`).
- No automatic account linking by e-mail, ever. Linking requires an authenticated local session plus a fresh provider round-trip (the flow that gap G-01 shows is currently broken).
- For self-service generic OIDC connections, `email_trust` is forced to `admin_controlled` regardless of what the token says.

## 5. Security best current practice, re-read for a multi-connection server

RFC 9700 (OAuth 2.0 Security Best Current Practice, January 2025) and the OAuth 2.1 draft set the baseline: authorization code flow only, PKCE for every client, exact redirect-URI matching, no tokens in URLs, state or PKCE for CSRF, nonce for OIDC replay. The current implementation already meets these for one provider.

Becoming a client of **many** authorization servers, some of them configured by tenants, introduces threats that a single-provider client never faces:

| Threat | Why it appears now | Mitigation |
| --- | --- | --- |
| **Mix-up attack** — the client is tricked into sending a code issued by honest IdP A to attacker-controlled IdP B's token endpoint (or vice versa) | Multiple issuers behind one callback; a tenant can register a malicious "generic OIDC" connection | Bind `connection_id` and expected issuer in the state record at start; at callback use **only** the state record to choose the token endpoint; validate the `iss` authorization-response parameter (RFC 9207) when the IdP advertises `authorization_response_iss_parameter_supported`; validate ID-token `iss` against the connection's configured issuer, not against a global list. Optionally one redirect URI per connection. |
| **SSRF through admin-supplied URLs** | Discovery URL, token endpoint, JWKS URI, userinfo URL (and a redeem URL, if that handshake is kept) are fetched server-side | HTTPS only; resolve and reject private, loopback, link-local and metadata ranges; no redirects; short timeouts and response-size caps; for built-in provider types ignore tenant-supplied endpoints entirely and use compiled-in ones. |
| **Cross-tenant configuration access** | Secrets for many tenants in one table | Row ownership checks on every admin route; secrets write-only; encryption with key id; root-only secret submission (the billing pattern). |
| **Cross-tenant redirect/origin confusion** | Allow-lists become per project | Allow-lists are looked up by the project derived from the authenticated init step — never from a union across projects. |
| **Open redirect via `return_to`** in a hosted-callback topology | `api.auth` redirects the browser back to the application | Exact-match allow-list per project; never reflect a caller-supplied URL. |
| **IdP-initiated or unsolicited callbacks** | More callback surface | Already handled: no state record, no processing. |
| **Algorithm confusion in ID tokens** | Arbitrary IdPs | Server-side allow-list of asymmetric algorithms; reject `none` and `HS*`; key selected by `kid` from the connection's JWKS only. |
| **Downgrade of PKCE/nonce for weak providers** | Some OAuth 2.0 providers lack one or both | Capabilities are declared per provider **type in code**, not per connection in data, so a tenant cannot switch PKCE off. `state` is always required. |

## 6. How established identity systems model this

| System | Tenant unit | Provider instance | Provider type | Secrets |
| --- | --- | --- | --- | --- |
| Auth0 | Tenant, with connections enabled per application | **Connection** | Strategy (`google-oauth2`, `oidc`, `github`, …) | Stored server-side, write-only in the management API |
| Keycloak | Realm | **Identity Provider** instance with an alias | Provider id (`google`, `oidc`, `github`) | Realm database, masked in admin API; callback is `…/broker/<alias>/endpoint` |
| Supabase Auth | Project | Per-project provider settings | Built-in list | Project config, write-only |
| Ory Kratos | Deployment | Entry in the OIDC provider list with an `id` | `provider` field (`google`, `generic`, `github`, …) plus a claims **mapper** | Config/secret store |
| Authlib / Auth.js | Application | Registered client | Provider preset | Application config |

The common shape is a three-level model: **provider type (code)** → **connection (data: credentials + endpoints)** → **enablement per application/project (data: policy)**. All of them host the IdP-facing callback themselves and return the user to the application with a short-lived one-time artefact; none of them call out to the application during login. Ory's *claims mapper* is a useful idea for generic providers: a small declarative mapping from provider claims to the normalised identity.

**Consequence.** Adopt the three-level model; it also matches the billing precedent already in this repository (`billing_providers` → `billing_groups` → `billing_group_projects`).

## 7. The init handshake: three options

The provider-init token exists for a good reason: the browser must not choose (or even see) the strict `project_hash` / `user_group_hash`. The problem is only *how* `api.auth` learns the binding.

| | A. Per-project redeem URL (today's shape, multiplied) | B. Inverted: consumer calls `api.auth` to mint the token | C. Self-contained signed token |
| --- | --- | --- | --- |
| Direction | `api.auth` → consumer (outbound) | consumer → `api.auth` (inbound) | none |
| Caller authentication | Static bearer per project, stored encrypted | **Existing project-scoped API key** (`user_project_api_keys`) or a dedicated project client credential | Signature with a per-project key registered in the database |
| How `api.auth` knows the project | Must be told *before* redeeming (public project key in the start request, or a token prefix) | **Derived from the authenticated credential** — cannot be spoofed by another tenant | From the verified key id |
| SSRF exposure | Yes — tenant-supplied URL fetched server-side | None | None |
| Replay protection | Consumer's Redis | `api.auth`'s Redis (already has the single-use store) | Needs a `jti` store anyway |
| Consumer effort | High — every project re-implements issue + redeem + replay markers (about two thousand lines in `magic-worlds-api`) | **Low** — one authenticated POST | Medium — key management and JWT minting |
| Works without a consumer backend | No | No (needs a server-held credential) — see section 8 | No |
| Availability coupling | Login fails when the consumer's redeem endpoint is down | None | None |

**Recommendation: B**, with A kept temporarily as a compatibility bridge for the existing Magic Worlds deployment. B removes findings F-23, F-26 and F-27 at the root: project identity comes from a credential `api.auth` issued, and the provisioning group comes from `api.auth`'s own per-project configuration instead of from a caller-supplied hash.

## 8. Callback topology: two options

| | BFF-mediated (today) | Hosted callback (new) |
| --- | --- | --- |
| Redirect URI registered at the IdP | The consumer backend's URL | `api.auth`'s URL (one per deployment or per connection) |
| Who receives `code` + `state` from the browser | Consumer backend, which forwards server-to-server | `api.auth` directly |
| How the session reaches the app | Backend receives `LoginResponse`, does its own delivery | `api.auth` redirects to an allow-listed `return_to` with a **one-time delivery code** (TTL about 60–120 s, single use, no tokens in URLs); the app exchanges it at `api.auth` — from its backend with the project credential, or from a public client with a PKCE-style verifier bound at init |
| Requires consumer backend | Yes | No — enables SPA and mobile projects |
| Cookie domain | Consumer's | `api.auth`'s unless the app exchanges the code and sets its own |
| IdP console setup per project | Register each consumer callback | One stable callback per connection |

**Recommendation:** keep BFF-mediated as the first-class mode (it is deployed and has the better cookie story), and design the state record and routes so hosted callback is an additive second mode. Do not build it in the first iteration, but do not paint it out: that means the state record stores a `delivery_mode`, and route paths do not assume a server-to-server caller.

## 9. Secrets at rest

| Option | Pros | Cons |
| --- | --- | --- |
| **Fernet with key id** (existing billing helper) | Already implemented, tested, with rotation map and runbook; AES-128-CBC + HMAC-SHA256, authenticated | No associated data: a ciphertext copied from one row to another still decrypts. |
| AES-256-GCM with associated data (`connection_id`, column name, key id) | Binds ciphertext to its row and purpose; `cryptography` is already a dependency | New code to write and review. |
| External KMS / Vault envelope encryption | Keys never in the process environment; central audit | New infrastructure dependency; none exists in this deployment. |

**Recommendation:** extract the billing helper into a neutral shared module and reuse the **mechanism**, with a **separate key set** for OAuth (`OAUTH_SECRET_ENCRYPTION_KEY`, `OAUTH_SECRET_ENCRYPTION_KEY_ID`, `OAUTH_SECRET_DECRYPTION_KEYS_JSON`) so billing and OAuth rotate independently. Compensate for the missing associated data the way billing does — store an HMAC of the plaintext beside the ciphertext and verify it after decryption with a purpose-separated input (`v1:oauth:<connection_id>:client_secret:<value>`), which detects row-swapping. Treat AES-GCM-with-AAD as a later hardening that the `credential_encryption_alg` column already makes possible without a schema change.

Decrypted secrets are never cached in Redis and never logged; they live on a short-lived, `repr`-suppressed object for the duration of the token exchange (the `StripeAccountSecrets` pattern).

## 10. Library notes

- **Authlib** is already a dependency, but the current code uses almost none of it: the authorize URL is built by hand and the exchange uses `fetch_access_token` on a Starlette registry client. The Starlette registry is designed for a *static* set of clients registered at import time. For per-request, per-connection credentials, construct `authlib.integrations.httpx_client.AsyncOAuth2Client` (or a plain `httpx.AsyncClient` POST) per exchange. This also fixes the blocking-I/O gap, since it is natively async. `httpx` would be a new direct dependency.
- **PyJWT** (present) has `PyJWKClient` with built-in key caching and `kid` lookup. A process-level cache keyed by JWKS URI replaces the per-call verifier instance (gap G-05).
- **python-jose** is present but unmaintained upstream for long periods and unused by the OAuth path; do not adopt it for ID-token work.
- **google-auth** cross-verification is defence in depth that only exists for Google. Keep it inside the Google adapter as an optional second check; do not make it part of the generic pipeline.
- OIDC discovery documents should be cached (in-process, TTL about one hour, keyed by URL) and **pinned**: the `issuer` in the fetched document must equal the connection's configured issuer.

## 11. Sources

- [OpenID Connect Core 1.0](https://openid.net/specs/openid-connect-core-1_0.html) — ID-token validation, subject identifier types.
- [RFC 9700 — OAuth 2.0 Security Best Current Practice](https://www.rfc-editor.org/rfc/rfc9700) — PKCE, redirect matching, mix-up.
- [RFC 9207 — Authorization Server Issuer Identification](https://www.rfc-editor.org/rfc/rfc9207) — the `iss` response parameter.
- [RFC 7636 — PKCE](https://www.rfc-editor.org/rfc/rfc7636).
- [Google — OpenID Connect](https://developers.google.com/identity/openid-connect/openid-connect) — `sub`, `hd`, issuer values.
- [Microsoft — ID token claims reference](https://learn.microsoft.com/en-us/entra/identity-platform/id-token-claims-reference) — pairwise `sub`, `oid` + `tid`, e-mail warning.
- [GitHub changelog — PKCE support for OAuth and GitHub App authentication](https://github.blog/changelog/2025-07-14-pkce-support-for-oauth-and-github-app-authentication/).
- [Scott Brady — Implementing Sign in with Apple](https://www.scottbrady.io/openid-connect/implementing-sign-in-with-apple-in-aspnet-core) — ES256 client secret, `form_post`.
