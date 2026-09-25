# 10 — Consumer Guide: Integrating Any Project

How a project other than Magic Worlds would use OAuth login once the target design exists, and what Magic Worlds itself has to change. Everything in this document describes a **proposed** contract.

## 1. Today's consumer contract, as implemented by Magic Worlds

Reviewed in the sibling repository (`magic-worlds-api`). File names are given relative to that repository and are prefixed with its name.

| Step | Consumer responsibility today | Where |
| --- | --- | --- |
| Mint provider-init token | 256-bit random; store only its SHA-256 digest in Redis with `SET NX EX`; TTL at most 600 s; binding = provider, purpose, `project_hash`, `user_group_hash`, return origin, issuer, audience, fingerprints | `magic-worlds-api/src/services/provider_init.py` |
| Refuse browser-supplied scope | Reject bodies containing `project_hash`, `user_group_hash`, `group_hash`, `project`, `user_group` | `magic-worlds-api/src/routes/user/route_auth.py` |
| Start shim | Browser top-level GET → server-to-server `POST /auth/google/start` → relay the `303` | same, plus `magic-worlds-api/src/services/auth_adapter.py` |
| Redeem endpoint | `POST /internal/auth/provider-init/redeem`, static bearer compared in constant time, single use via `GETDEL` plus replay marker; status mapping 401 / 403 / 404 / 410 | same |
| Callback return | Receive `code` and `state` from Google, forward server-to-server to `GET /auth/google/callback`, receive `LoginResponse` | same |
| Browser delivery | One-time 256-bit delivery code (default TTL 120 s, `GETDEL`), `303` to the SPA with only that code, HttpOnly refresh cookie; SPA exchanges the code for a sanitised payload | `magic-worlds-api/src/services/oauth_delivery.py` |
| Configuration | One `PROJECT_HASH`, one `USER_GROUP_HASH`, `AUTH_API_URL`, `BFF_GOOGLE_CALLBACK_URL`, `FRONTEND_GOOGLE_RETURN_URL`, `PROVIDER_INIT_*`, `OAUTH_DELIVERY_*` | `magic-worlds-api/src/main.py` |
| Client library | `magic_auth_client` with compiled-in `/auth/google/start` and `/auth/google/callback` | external package |

Observations that matter for a second project:

- The consumer side is roughly two thousand lines of security-sensitive code that exists **only** inside Magic Worlds. There is no reusable package, template or specification for it.
- It is well built (digest-only storage, replay markers, byte-compared records, sanitised delivery payload), which makes it a good *reference*, but a second team re-implementing it is a second chance to get it wrong.
- The same return origin must be present in two separate consumer allow-lists (`CORS_ORIGINS` for the shim, `PROVIDER_INIT_RETURN_ORIGINS` for issue and redeem) **and** in `api.auth`'s environment. The BFF callback URL must match byte-for-byte in three places.
- The consumer can represent exactly one project.
- When neither `Origin` nor `Referer` is present, the consumer's origin check is skipped. With `SameSite=None` cookies this is the weakest link on that side and worth tightening independently.

## 2. Proposed contract for any project

### 2.1 One-time onboarding (administrator)

1. Create or choose the **project** and a **default user group** that reaches it.
2. At the identity provider's console, create an OAuth client. Register the redirect URI: the project backend's callback URL (BFF mode) or `api.auth`'s callback URL (hosted mode, when available).
3. In `api.auth`: create a **connection** (provider type, client id, scopes, restrictions), submit the client secret through the write-only credentials endpoint, run the connection test, activate it.
4. Create the **binding** for the project: connection key (for example `google`), provisioning mode, default group, existing-user policy; add the exact redirect URI and return origin rows; enable it.
5. Issue a project-scoped credential for the project's backend.
6. Check the readiness endpoint reports every layer green.

Nothing in these steps touches `api.auth`'s environment or requires a restart.

### 2.2 Runtime, BFF mode

```text
SPA            Project backend                         api.auth                      IdP
 | click "Sign in with X"  |                               |                           |
 |------------------------>| POST /auth/oauth/init  ------>| project := credential     |
 |                         |   (project credential)        | binding, origin, group    |
 |                         |<----- init_token -------------| stored single-use in Redis|
 |                         | POST /auth/oauth/start ------>| consume init, mint state  |
 |<------- 303 Location: IdP authorize URL ----------------|                           |
 |------------------------------------------------------------------------------------>|
 |<------------------ 302 to project backend callback --------------------------------|
 |------------------------>| GET /auth/oauth/callback ---->| exchange, verify, resolve |
 |                         |<----- LoginResponse ----------| issue local token pair    |
 |<-- project's own session delivery (cookie, one-time code, …)                        |
```

Init request and response:

```json
{
  "connection": "google",
  "purpose": "login",
  "return_origin": "https://app.example.com",
  "remember_me": false
}
```

```json
{
  "success": true,
  "init_token": "REPLACE_ME_OPAQUE_TOKEN",
  "expires_in": 300,
  "connection": "google",
  "provider_type": "google"
}
```

What the project backend no longer has to build: token minting and storage, the internal redeem endpoint, its bearer secret, replay markers, binding fingerprints, and any knowledge of its own `user_group_hash`. What it still owns: the start shim, the callback relay, and delivering its own session to its own front end — which is legitimately application-specific.

### 2.3 Listing providers for the login page

`GET /auth/oauth/providers` with the project credential returns the enabled bindings as connection key, provider type and display name. The front end renders buttons from data; enabling a provider for a project becomes an administrative action with no front-end release.

### 2.4 Error handling

All failures use the existing neutral codes (`EXT_8010` … `EXT_8030`) plus one proposed addition for user cancellation. Consumers should map codes, not provider names, to messages; the Magic Worlds slugs `google_start_failed`, `google_denied` and so on become `oauth_start_failed`, `oauth_denied`, with the connection key available separately when the UI wants to name the provider.

### 2.5 Hosted mode (later)

For projects with no backend: the front end obtains an init token through a public-client variant (PKCE-style verifier bound at init), `api.auth` hosts the callback, redirects to an allow-listed `return_to` with a one-time delivery code, and the front end exchanges that code together with the verifier. This is the delivery mechanism Magic Worlds implements privately today, offered by `api.auth` for everyone. Not part of the first iterations.

## 3. What Magic Worlds has to change, and when

| When (plan phase) | Change | Required? |
| --- | --- | --- |
| Phases 0–3 | Nothing. Alias routes, legacy redeem bridge and imported configuration keep the current contract intact. | — |
| Phase 4 | Nothing, **provided** the binding imported into `api.auth` records the same project and default group that Magic Worlds sends in its redeem response. A mismatch is rejected by design. Verify in staging before production. | Verification only |
| Phase 6 | `magic_auth_client`: add connection-parameterised `oauth_init`, `oauth_start`, `oauth_callback`, `list_oauth_providers`; keep Google-named wrappers for one release. | Yes |
| Phase 6 | Replace provider-init issue and redeem with one call to `/auth/oauth/init`; delete the internal redeem route, its bearer, and the `PROVIDER_INIT_*` settings. | Yes |
| Phase 6 | Parameterise routes (`/auth/provider-init/{connection}`, `/auth/oauth/{connection}/start/shim`, `…/callback/return`, `…/exchange`) and error slugs; keep the Google paths as aliases for the front end's benefit. | Yes |
| Phase 6 | Replace `BFF_GOOGLE_CALLBACK_URL` and `FRONTEND_GOOGLE_RETURN_URL` with a per-connection map, since every provider client registers its own redirect URI. | When a second provider is enabled |
| Any time | Render login buttons from the providers listing. | Optional |
| Any time | Tighten the origin check when both `Origin` and `Referer` are absent. | Recommended, independent |

The delivery-code mechanism, the refresh cookie and the local shadow-user projection are unaffected: they sit after `LoginResponse`, which does not change shape.

### 3.1 Concrete inventory for Magic Worlds

Measured in the consumer repository at review time. The net effect is that the consumer gets **smaller**: it stops owning a security protocol it currently implements itself.

**Removed in Phase 6**

| Item | Size | Why it goes |
| --- | --- | --- |
| `POST /internal/auth/provider-init/redeem` route and its handler | — | `api.auth` no longer calls the consumer; nothing redeems. |
| The token-minting, digest-storage, replay-marker, fingerprint and redeem-validation logic in `magic-worlds-api/src/services/provider_init.py` | most of about 1,250 lines | Replaced by one authenticated POST to `/auth/oauth/init`. |
| `PROVIDER_INIT_REDEEM_BEARER_TOKEN`, `PROVIDER_INIT_TTL_SECONDS`, `PROVIDER_INIT_ISSUER`, `PROVIDER_INIT_AUDIENCE`, `PROVIDER_INIT_REDIS_URL`, `PROVIDER_INIT_REDIS_PREFIX` | 6 variables | The token now lives in `api.auth`'s Redis under its own TTL and audience rules. |
| `PROVIDER_INIT_RETURN_ORIGINS` | 1 variable | Moves to the binding's allow-list rows in `api.auth`. |

**Kept unchanged**

| Item | Size | Why it stays |
| --- | --- | --- |
| `magic-worlds-api/src/services/oauth_delivery.py` | about 620 lines | Delivering a session to your own front end is legitimately application-specific. `api.auth` does not take this over in BFF mode. |
| The three browser-facing routes — start shim, callback return, exchange | — | Still yours; only their paths and error slugs get parameterised by connection. |
| `AUTH_API_URL`, `PROJECT_HASH`, `OAUTH_DELIVERY_*` | 5 variables | Still needed. |
| `USER_GROUP_HASH` | 1 variable | **Still required.** It is used for every ordinary registration, and by notifications and adventure-session scope checks — not only by OAuth. What disappears is its *OAuth* role: the provisioning group now comes from the binding in `api.auth`, not from the consumer's assertion. |

**Changed**

| Item | When |
| --- | --- |
| `BFF_GOOGLE_CALLBACK_URL`, `FRONTEND_GOOGLE_RETURN_URL` become a per-connection map | Only when a second provider is enabled; each provider client registers its own redirect URI. |
| `magic_auth_client` gains connection-parameterised methods | Phase 6, before the consumer change. |

## 4. Checklist for a brand-new project

- [ ] Project and default group exist; the group reaches the project.
- [ ] OAuth client created at the provider; redirect URI registered exactly.
- [ ] Connection created, secret submitted, test passed, activated.
- [ ] Binding created: provisioning mode and existing-user policy chosen deliberately; redirect URI and return origin rows added; enabled.
- [ ] Project credential issued to the backend and stored in its secret manager.
- [ ] Backend implements: init call, start shim, callback relay, own session delivery.
- [ ] Backend rejects browser-supplied project or group identifiers.
- [ ] Readiness endpoint green; first login tested with a fresh account **and** with an account that already exists at another project.
- [ ] Link, re-authentication and unlink tested for a password-first user.
- [ ] Cancel-at-consent path shows a friendly message.
