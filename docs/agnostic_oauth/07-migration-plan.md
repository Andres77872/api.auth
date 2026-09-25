# 07 — Migration Plan

A phased path from today's Google-only, environment-configured implementation to provider adapters with per-project database configuration. Each phase is independently shippable, leaves Magic Worlds login working, and has an explicit rollback. No phase has been started; this document is a plan only.

## Guiding rules

1. **Refactor before you generalise.** Phases 0–2 change structure with Google as the only provider and the environment as the only configuration source. If behaviour changes in those phases, something went wrong.
2. **Additive schema first.** New tables and new columns before any type change to existing columns.
3. **One switch at a time.** Code path (adapter pipeline), configuration source (database), handshake (init API) and routes (`/auth/oauth/*`) are four separate switches, flipped in four separate releases.
4. **The subject HMAC is sacred.** No phase may change the pepper value, the HMAC input, or the hashing function for existing identities.
5. **Legacy routes outlive their replacement by at least one consumer release cycle.**

## Phase overview

| Phase | Theme | User-visible change | Schema change | Consumer change | Dashboard change |
| --- | --- | --- | --- | --- | --- |
| 0 | Fix and fence | Link and reauth start working; clearer cancel error | none | none | none |
| 1 | Extract the adapter seam | none | none | none | none |
| 2 | Generic pipeline and routes behind aliases | none | none | none | none |
| 3 | Database configuration | none (config imported from env) | additive | none | **the bulk of the UI work** |
| 4 | Trust-model hardening + init API | none | none | optional | small |
| 5 | Second provider | new login button | catalog/ENUM widen | optional | per-provider form branching |
| 6 | Consumer migration and clean-up | none | optional ENUM → VARCHAR | required for Magic Worlds | none |
| 7 | Optional: hosted callback, self-service | new capability | additive | none | optional self-service views |

Three repositories are involved: `api.auth` (phases below), `magic-worlds-api` (see [10-consumer-guide.md](10-consumer-guide.md)) and `magic-auth-dashboard` (see [11-admin-dashboard.md](11-admin-dashboard.md)). The dashboard workstream trails the backend by one phase and is sequenced in section 10 of that document.

## Phase 0 — Fix and fence (prerequisite hygiene)

Goal: do not multiply known defects by N providers.

| Work item | Addresses |
| --- | --- |
| Make the callback branch on `purpose`; complete `link` inside the callback; remove the `claims`-in-link-token hand-off | G-01 |
| Complete `reauth` in the callback; call `mark_recent_reauth` after verifying the identity is linked to the initiating user | G-02 |
| Move every test-runtime branch out of the route module into test fixtures (fake client, fake verifier, fake state store are already patch targets) | G-03 |
| Add `sub_reason` to the safe-details allow-list | G-04 |
| Module-level verifier / JWKS cache honouring the configured TTL | G-05 |
| Distinct neutral code for `error=access_denied`; consume the state on provider error | G-09 |
| Narrow the broad `except Exception` handlers so infrastructure failures are not reported as identity conflicts | G-10 |
| Decide enforce-or-remove for the state cookie and `ip_hash` / `ua_hash` | G-08 |
| Implement or retract the e-mail-collision promise; make its test run with auto-create enabled | G-14 |
| Correct the usage docs to the BFF topology and the real hosted-domain behaviour | G-11 |

Exit criteria: existing test suite green; new tests cover link and reauth end to end against fakes; no `_test_runtime` reference remains under the routes package.

Rollback: revert the release. No data or configuration changed.

## Phase 1 — Extract the adapter seam (Google only)

1. Introduce the provider Protocol, `ExternalIdentity`, capabilities and the closed error enum.
2. Implement `GenericOIDCAdapter` by moving (not rewriting) the logic from the Google verifier and the Google client; implement `GoogleAdapter` on top with compiled-in endpoints, the `hd` rule and the optional `google-auth` cross-check.
3. Introduce `ConnectionConfig` and build it **from `load_google_oauth_config()`**. There is still one connection and it still comes from the environment.
4. Move subject/e-mail HMAC, fingerprint and masking helpers out of the Google verifier into a neutral identity module; keep the old names as re-exports.
5. Registry with a single registered adapter.
6. The Google router calls the adapter instead of the verifier and client directly. Tests that patch `src.routes.auth_google.verify_google_id_token`, `…oauth_client` and friends (about forty patch sites across the suite) keep working through thin compatibility names, or are updated in the same change.

Exit criteria: byte-identical authorize URLs (golden test); identical activity and audit output; identical subject hashes for a fixed fixture (golden test against a hard-coded expected digest).

Rollback: revert. No data changed.

## Phase 2 — Generic pipeline and routes behind aliases

1. Write the shared 12-step pipeline described in [05-target-architecture.md](05-target-architecture.md).
2. Add `/auth/oauth/start`, `/auth/oauth/callback` (GET and POST) and the link / reauth / unlink routes. `/auth/google/*` become aliases that call the same handlers with connection key `google`.
3. Neutral Redis prefixes with dual-read of the legacy prefixes for one state-TTL window.
4. Rate-limit buckets gain project and connection dimensions.
5. Generic `oauth_*` activity types seeded; prefix-based audit and auth-context path detection.
6. Rewrite [test_google_oauth_docs_static.py](../../tests/static/test_google_oauth_docs_static.py) expectations that pin Google-only wording, in the same change as the docs they check.

Exit criteria: the Magic Worlds end-to-end flow passes unchanged against the alias routes; the same flow passes against the generic routes.

Rollback: revert; in-flight states under the new prefix expire within ten minutes.

## Phase 3 — Database configuration

1. Add the three canonical SQL files (catalog, connections, bindings and URLs) and register them in every ordered list named in [06-data-model.md](06-data-model.md). Add `identity_namespace` and `connection_id` to `user_external_accounts` through `COLUMN_PATCHES`, backfilled from `provider`.
2. Extract the encryption helper to a neutral module; add the OAuth key set; add a readiness check that refuses to enable database-sourced connections when no encryption key is configured.
3. `resolve()` reads the database. **Feature flag `OAUTH_CONFIG_SOURCE=env|db`**, default `env`.
4. Operator-run import command: environment → one `google` connection + one binding for the named project, `init_mode='legacy_redeem'`, URLs copied from the CSV variables.
5. Admin API, root-only, including the readiness endpoint.
6. Flip `OAUTH_CONFIG_SOURCE=db` in staging, then production. The environment client variables remain as a fallback until Phase 6.

Exit criteria: login works with `GOOGLE_OAUTH_CLIENT_ID` and `GOOGLE_OAUTH_CLIENT_SECRET` removed from the environment in staging; the secret never appears in logs, audit rows or API responses (extend the existing leak-assertion fixtures); an encryption-key rotation rehearsal succeeds.

The bootstrap import and the admin API are deliberately usable without any UI, so this phase can ship and be verified before the dashboard work lands. The dashboard follows immediately after — until it exists, every subsequent configuration change is a hand-written API call, so do not let the gap run long.

Rollback: set `OAUTH_CONFIG_SOURCE=env`. The new tables are inert. The added columns are nullable or defaulted and ignored by old code.

## Phase 4 — Trust-model hardening and the init API

1. In the legacy redeem bridge, require the redeemed `project_hash` and `user_group_hash` to equal the binding's project and default group (closes F-26 and F-27 without any consumer change, as long as the import in Phase 3 recorded the same values Magic Worlds sends).
2. `sp_create_consumer_user_from_external_account` takes the binding id and reads policy and group from it.
3. Add `POST /auth/oauth/init` and `GET /auth/oauth/providers`, authenticated by project-scoped API key.
4. Implement `existing_user_policy`.
5. Trusted-proxy handling for `X-Forwarded-For`.
6. SSRF guard for every outbound fetch (discovery, JWKS, token, userinfo, legacy redeem).

Exit criteria: a test proves that a redeem response naming a different project or group is rejected; a test proves a second project with its own binding and API key can complete login with **no** `PROVIDER_INIT_*` environment variables.

Rollback: the init API is additive. The bridge equality check can be relaxed by a flag if the imported values turn out not to match production; investigate before relaxing, since a mismatch is exactly what the check is for.

## Phase 5 — Second provider (the proof of agnosticism)

Pick the provider that stresses the abstraction most cheaply. **GitHub** is the recommended first: it is non-OIDC (exercises `OAuth2UserInfoAdapter`), has a global numeric subject (no namespace subtlety), supports PKCE, and needs no paid developer account. **Microsoft** is the recommended second: it exercises issuer templating, the `oid`/`tid` subject and the `admin_controlled` e-mail rule. Apple is third; it needs POST callbacks and generated client secrets.

Work: adapter, catalog seed, ENUM widen (or none, if the VARCHAR conversion has been done), contract tests shared by all adapters (every adapter must pass the same suite: state required, PKCE sent when declared, identity returned without tokens, failures classified by the enum).

Exit criteria: a project can enable Google and GitHub simultaneously; a user can link both to one account; unlinking one leaves the other working.

## Phase 6 — Consumer migration and clean-up

1. `magic_auth_client`: add `oauth_init`, `oauth_start`, `oauth_callback`, `list_oauth_providers`, parameterised by connection key; keep the Google-named methods as wrappers.
2. `magic-worlds-api`: replace provider-init issue/redeem with one call to `/auth/oauth/init`; parameterise its four Google-named routes and error slugs; per-connection callback URL map. Details in [10-consumer-guide.md](10-consumer-guide.md).
3. Flip the Magic Worlds binding to `init_mode='api'`; delete the legacy redeem bridge, the `PROVIDER_INIT_*` variables and the `GOOGLE_OAUTH_*` client variables; keep pepper fallbacks.
4. Deprecate, then remove, the `/auth/google/*` aliases.
5. Optional, isolated: ENUM → VARCHAR with catalog foreign key.

## Phase 7 — Optional extensions

- Hosted-callback delivery mode for projects without a backend.
- Self-service connection management for project administrators (built-in provider types only).
- Tenant-configured generic OIDC for enterprise single sign-on.
- AES-GCM with associated data for secrets.

## Test strategy

| Layer | What to add |
| --- | --- |
| Unit | Adapter contract suite run against every adapter; namespace computation; claim normalisation (string `email_verified`, missing e-mail); issuer-template validation; algorithm allow-list; URL validator and SSRF guard; encryption round trip, wrong key id, row-swap detection. |
| Golden | Fixed `sub` + fixed pepper → expected digest, asserted in Phase 1 and never changed; authorize URL for the Google connection. |
| Integration | Two projects, two connections, two API keys: cross-project redirect URI, origin, init token and state are each rejected; disabled-while-in-flight; existing-user policy both ways; link and reauth. |
| Static | Forbidden-column test extended to the new tables; docs lint already runs over every file under the docs folder, including this directory. |
| Migration | Import command is idempotent; `schema_sync` dry-run shows only additive actions in Phase 3; rollback by flag verified. |
| Security | Leak assertions extended to `client_secret`, signing key, legacy redeem token; mix-up test (state minted for connection A, callback claiming issuer B). |

## Rough sizing

Relative effort, in "Phase 1 = 1" units, to help with ordering rather than scheduling: Phase 0 ≈ 1, Phase 1 ≈ 1, Phase 2 ≈ 1.5, Phase 3 ≈ 2.5 (schema + encryption + admin API), Phase 4 ≈ 1.5, Phase 5 ≈ 0.5 per simple provider and ≈ 1 for Apple, Phase 6 ≈ 1 on the consumer side. The dashboard adds roughly 2 more, almost all of it alongside Phase 3.

Phases 0–2 carry most of the regression risk; Phase 3 carries most of the operational risk.
