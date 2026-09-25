# 12 — Implementation Status

What has been built from the plan in [07-migration-plan.md](07-migration-plan.md), what was verified and how, what was deliberately left for later, and what an operator must do to roll it out. Nothing described here has been committed or deployed.

## Decisions taken

The plan's open questions ([09-open-questions.md](09-open-questions.md)) were resolved with the documented recommendations:

| # | Decision |
| --- | --- |
| 1 | Identity is **global**: one person is one user across projects. `existing_user_policy` defaults to `deny`. |
| 2 | Connections are **shareable, with an optional owner project**. |
| 3 | Anything that accepts a secret, creates a connection or flips the catalog is **root only**. |
| 4 | The provider column stays an **ENUM, widened by appending**; the VARCHAR conversion is not done. |
| 5 | **Inverted init handshake**, authenticated with the existing project-scoped API key; legacy redeem kept as a bridge. |
| 6 | Hosted callback is **not built**; `delivery_mode` exists on the binding and in the state record so it stays additive. |
| 7 | E-mail collision: **never merge**; a provider-verified collision answers "sign in and link". |
| 8 | Patreon is **not** moved under the adapter contract; it has a catalog row with `login_enabled = FALSE`. |
| 12 | The term is **connection**. |

## Phase status

| Phase | Status | Notes |
| --- | --- | --- |
| 0 — Fix and fence | **Done** | Every gap `G-01` to `G-14` addressed; see below. |
| 1 — Adapter seam | **Done** | Protocol, registry, generic OIDC adapter, Google adapter on top of the existing verifier. |
| 2 — Generic pipeline and routes | **Done** | `/auth/oauth/*`; `/auth/google/*` are aliases on the same pipeline. |
| 3 — Database configuration | **Done** | Schema, encryption, database source, import command, admin API, readiness. Default source remains `env`. |
| 4 — Trust model and init API | **Done** | Bridge equality check, policy inside the create procedure, init and providers endpoints, existing-user policy, trusted proxies, SSRF guard. |
| 5 — Second provider | **Done** for GitHub, Discord, Microsoft and generic OIDC. **Apple not built.** |
| 6 — Consumer migration | **Additive part done**, behind a switch that defaults to legacy. **Deletions deliberately not done** — see "Left for a later release". |
| 7 — Optional extensions | Not started (hosted callback, self-service, AES-GCM). |
| Dashboard | **Done** | Connections, credentials, project assignment, sign-in tab, readiness, catalog panel; see the dashboard section. |

## What changed in `api.auth`

New package `src.Util.oauth`: deployment settings, provider contract, identity keys, guarded HTTP and process-wide caches, generic OIDC verifier, connection sources (environment and database), secrets at rest, init tokens, the start handshakes, the shared pipeline, admin DTOs, and adapters for Google, Microsoft, GitHub, Discord and generic OIDC.

New routes: [auth_oauth.py](../../src/routes/auth_oauth.py) and [admin_oauth.py](../../src/routes/admin_oauth.py). [auth_google.py](../../src/routes/auth_google.py) shrank from about 1,500 lines to about 250 and contains no flow logic.

New schema: [13_oauth_connections.sql](../../schemas/tables/13_oauth_connections.sql), [19_oauth_connections.sql](../../schemas/stored_procedures/19_oauth_connections.sql), [08_oauth_connections_triggers.sql](../../schemas/triggers/08_oauth_connections_triggers.sql); changes to [10_external_accounts.sql](../../schemas/tables/10_external_accounts.sql) and [05_external_accounts_triggers.sql](../../schemas/triggers/05_external_accounts_triggers.sql). The provider-keyed procedures in [15_external_accounts.sql](../../schemas/stored_procedures/15_external_accounts.sql) are untouched, so Patreon is unaffected.

Tooling: [schema_sync.py](../../scripts/schema_sync.py) gained data and index patches; [oauth_env_import.py](../../scripts/migrations/oauth_env_import.py) imports the environment configuration; both bootstrap scripts and the test compose file list the new files.

Shared extractions: [secret_box.py](../../src/Util/secret_box.py) (cipher primitives, now used by billing and OAuth) and [session_issue.py](../../src/Util/session_issue.py) (cookie and project-accessibility helpers, previously private names in the password router).

Documentation: [OAuth usage](../USAGE/oauth/README.md), [OAuth reference](../USAGE/oauth/reference.md), [OAuth runbook](../RUNBOOKS/oauth.md); the Google documents were corrected.

### Gaps closed

| Gap | Resolution |
| --- | --- |
| G-01 link cannot complete | The callback branches on the state record's purpose; a link completes there against the user who started it. The unimplementable `link/finish` route was removed. |
| G-02 reauth has no effect | The callback records the recent-reauth marker, only when the returned identity belongs to the session's user. |
| G-03 test bypasses in production code | Removed entirely. Tests issue genuine state through the production store and inject doubles through seams or a registered adapter. A regression test asserts the formerly accepted literal states are now plain unknown states. |
| G-04 `sub_reason` dropped | Added to the safe-details allow-list. |
| G-05 JWKS never cached | Process-wide cache keyed by URI, honouring provider cache headers; one forced refetch on a `kid` miss. |
| G-06 blocking I/O | Provider HTTP and token verification run off the event loop. Database and Redis calls remain synchronous, as everywhere else in the service. |
| G-07 forwarded IP trusted blindly | `X-Forwarded-For` is honoured only from `OAUTH_TRUSTED_PROXY_CIDRS`; empty means ignored. **Behaviour change** — see rollout notes. |
| G-08 unchecked binding cookie | Enforced when present (direct browser round trips); absent behind a BFF. `ip_hash` / `ua_hash` are documented as diagnostic only. |
| G-09 cancel collapsed into a token error | `OAUTH_USER_CANCELLED` / `EXT_8031`; the state is consumed. |
| G-10 broad exception swallowing | Failures are classified by a closed enum; the second, unchecked URL builder is gone. |
| G-11 documentation drift | Corrected. |
| G-12 private cross-module imports | Helpers moved to a shared module. |
| G-13 no-op audit hook | Receives the same redacted details as the activity log. |
| G-14 e-mail collision undetected | Detected before auto-create; `OAUTH_ACCOUNT_LINK_REQUIRED` / `EXT_8032` when the provider verified the address, neutral denial otherwise. The test now runs with auto-create on. |

## Verification

| What | Result |
| --- | --- |
| Baseline before any change | 155 test files, 1,809 passed, 0 failed |
| Full per-file run after the change | 162 test files, 1,978 passed, 0 failed. The 52 skipped are the real-infrastructure tests, run separately below |
| Schema on **real MySQL 8.0.46** | All 40 canonical files load cleanly; 20 stored-procedure and trigger checks behave as designed |
| **Upgrade path** on real MySQL | A database built from the previous schema, holding a linked Google identity and a Patreon identity, was upgraded with `schema_sync.py --apply`. Both identities still resolve, through the new namespace-keyed procedure and the old provider-keyed one; `--verify` passes; a second run plans nothing |
| Environment import on real MySQL | Idempotent; no secret in its output; no plaintext in the stored ciphertext |
| Secret round trip through real MySQL | Encrypt, store, resolve, decrypt; a ciphertext moved to another row is rejected |
| Real-infrastructure lifecycle tests | start → callback → validate → refresh → logout, and link/unlink, against real MySQL and Redis: pass. All 39 pre-existing real-database tests pass on the new schema |
| Golden tests | Subject HMAC pinned to a literal digest; Google authorize URL byte-identical to the original builder for every prompt variant |
| Mutation check | The "only two procedures may select ciphertext" test fails when a leak is introduced |

A finding surfaced by removing the test bypass: the "strict hashes never leave the server" test had been passing vacuously, because its synthetic state never carried the sentinel hash. `LoginResponse` names the session's project by contract, exactly as password login does. The test now asserts precisely that the project hash appears only in those documented fields and nowhere in headers, cookies, logs, audit or activity, and that the provisioning group hash appears nowhere.

## Consumer workstream (`magic-worlds-api` and `magic_auth_client`)

Built behind a switch, so it can be deployed before or after `api.auth` moves to database configuration.

- `magic_auth_client` 0.4.0 (unreleased): `oauth_init`, `oauth_start`, `oauth_callback`, `list_oauth_providers`; the project API key is sent as `X-API-Key`, excluded from `repr` and never logged. Every Google-named method is unchanged.
- `magic-worlds-api`: new setting `OAUTH_INIT_MODE`, **default `legacy`**, in which behaviour is byte-for-byte what it was. In `api` mode the provider-init route calls `/auth/oauth/init` and returns the same public shape, so the front end needs no change; the start shim and callback relay use the generic endpoints and forward `iss`. `AUTH_PROJECT_API_KEY` is required only in `api` mode. If the installed client library predates the new methods, the adapter falls back to the library's own HTTP transport, so the repository stays importable with the currently pinned version.
- Routes are parameterised by connection (`/auth/provider-init/{connection}`, `/auth/oauth/{connection}/start/shim`, `…/callback/return`, `…/exchange`); the four Google paths remain as aliases. The provider singleton became an allow-list (`OAUTH_CONNECTIONS`, default `google`); additional connections need their own callback and return URLs (`OAUTH_CONNECTION_URLS`) and fail closed without them. Google's scope fingerprint is byte-identical to before.
- `EXT_8031` and `EXT_8032` map to `*_cancelled` and `*_link_required` slugs in `api` mode, so the front end can say "sign-in cancelled" or "sign in and link" instead of a generic failure.
- `oauth_delivery.py` is untouched.
- Verified: client library 156 passed (137 before); `magic-worlds-api` 5,136 passed (5,052 before). Its 3 failures are pre-existing, in the chat agent flow, identical before and after.
- Reported, deliberately not changed: on credentialed routes the origin check is skipped when both `Origin` and `Referer` are absent. Requiring one would break existing non-browser clients and tests that the consumer's own documentation describes as supported.

`remember_me` needed a fix on the `api.auth` side: the front end sends it at start, the new handshake read it only at init, so it would silently have become `false`. `POST /auth/oauth/start` now accepts an optional boolean `remember_me` — a user preference, not security scope — and the consumer forwards it on both transports (typed client method and raw HTTP fallback). The start shim forwards the flag only when the browser actually sent it: an absent flag is not `false`, so it never overrides a value bound at init. With that, the two modes have no client-visible difference.

Before switching a consumer to `api` mode: `OAUTH_CONFIG_SOURCE=db` in `api.auth`, an enabled binding for the project with `init_mode = api`, and a project-scoped API key.

## Dashboard workstream (`magic-auth-dashboard`)

Built as a structural sibling of the billing admin area, following that repository's own conventions document.

- New OAuth area at `/oauth` (connections list) and `/oauth/:connectionHash` with `?tab=overview|projects|credentials`; navigation entry in the operations section for root and admin.
- **Assigning projects to a connection**: a searchable checkbox-list modal cloned from the billing attach modal — sequential per-project calls, a per-row result badge, a distinct badge for "already uses another connection", and it stays open on partial failure. New bindings are created disabled, and the summary says a redirect URI and return origin are still required.
- **Project-first view**: a `sign-in` tab on the project page with the project's bindings, readiness, URL allow-lists and an "enable a provider" dialog grouped by provider type.
- **Credentials**: write-only. Non-root users see a warning panel instead of the form; password inputs are never seeded from the server and are cleared on success; "Test connection" before save; the button verb flips between save and rotate; only the fingerprint and set-at are displayed.
- Binding editor (provisioning mode with consequences, default group from the project's groups, auto-create blocked until a group is chosen, warning on "join default group"), one-row-per-URL allow-lists with validation and copy buttons, a readiness panel that names the failing layer, and a root-only provider catalog panel on the system page that flags "enabled without a registered adapter".
- The connection form branches per provider type from the start (hosted domains, tenant and tenant ids, organisations, OIDC issuer and endpoints), and disables namespace-affecting inputs with a visible reason once identities are linked.
- Verified independently: type-check clean; 337 tests pass (279 before, 58 new). Every service call uses JSON and matches a backend route exactly.
- Lint: the repository's lint was already failing before this work (about 1,500 pre-existing errors in untouched files). The change adds exactly one, the same `set-state-in-effect` finding that the hook it was modelled on already has.

Deviations from [11-admin-dashboard.md](11-admin-dashboard.md): no activity tab on the connection page (no per-connection activity endpoint exists yet); save and rotate share the single credentials endpoint the backend exposes; the legacy redeem bridge is API-only, with no screen; the owner project is a hash input rather than a picker.

## Rollout notes for operators

1. **Nothing changes until you opt in.** `OAUTH_CONFIG_SOURCE` defaults to `env`; the Google aliases behave as before.
2. **Two behaviour changes ship immediately**, both security fixes:
   - `X-Forwarded-For` is ignored unless `OAUTH_TRUSTED_PROXY_CIDRS` lists the proxy. Per-IP rate limits then key on the direct peer. Set the variable to your reverse-proxy or BFF network to keep per-end-user limits.
   - A callback for a provider that was disabled after the round trip started is refused.
3. **`env` mode has no dependency on the new schema.** While `OAUTH_CONFIG_SOURCE=env` the pipeline keys identities through the historical provider-keyed procedures, which are functionally identical for Google, so deploying the code before running the schema catch-up cannot break sign-in. Run `schema_sync.py --apply` before moving to `db`; the runbook has the expected plan.
4. Moving to the database is three steps and one variable; rollback is `OAUTH_CONFIG_SOURCE=env`. See the [runbook](../RUNBOOKS/oauth.md).
5. Never change a pepper value. Introducing the `OAUTH_*` pepper names with different values stops the service at start-up on purpose.

## Live rollout: pre-flight of the shared database

The development and production environments point at the same MySQL database, so the schema step is a single apply. It was prepared and reviewed before anything was run against it.

- **What the apply contains.** The dry run shows the OAuth changes plus a catch-up of areas where that database is behind the committed schema: three `billing_groups` columns, four billing procedures, and a re-execution of the e-mail and Patreon files. All of that catch-up is already in git history; only the OAuth set is new.
- **Old code against the new schema.** Reproduced on a throwaway MySQL 8: previous-release schema with existing Google and Patreon identities, the working-tree migrator applied, then the previous release's code and tests run against the result. No incompatibility: the provider-keyed procedures are byte-identical, nothing references the dropped column or key names, 3,530 concurrent old-code operations during the apply produced no error, and a second apply is a no-op. Services do not need to stop.
- **Confirmed operational hazards**, each survived two independent attempts to refute it: the apply is forward-only (DDL commits implicitly, so `rollback()` undoes nothing); procedures and triggers are replaced by `DROP` then `CREATE`, leaving each absent for milliseconds; the namespace backfill goes through the new update trigger, so one invalid legacy row aborts it. One finding was refuted: the backup does contain the routines.
- **Hardening made as a result** in `scripts/schema_sync.py`: a session `lock_wait_timeout` so a blocked `ALTER` fails instead of queueing logins behind it; `--verify` now checks outcomes (index swap, stale column, backfill, catalog coverage, activity rows) instead of object names only; a failed statement reports where the run stopped; the dry run states how many rows the backfill will touch instead of printing "skip"; an already-deactivated stale template no longer appears in every plan. The procedure is in the [OAuth runbook](../RUNBOOKS/oauth.md).
- **Read-only checks on the target**: server 8.1 (column adds are instant), three identity rows, none violating a trigger invariant, no duplicates under the new keys, no live object referencing the dropped column, no metadata locks from other sessions, no e-mail in flight, no activity-catalog id collisions. A logical backup with routines, triggers and hex-encoded binary columns was taken first.

- **Outcome.** The operator applied the schema on 2026-09-21. The apply log matched the throwaway run statement for statement, the backfill touched the three existing rows, and `--verify` passed with the outcome checks. The services stayed up; the only server errors near the apply were the new development build asking for OAuth procedures seconds before they existed, none afterwards. The environment import was then applied from the production environment file: one active `google` connection, one enabled binding in `legacy_redeem` mode, six allow-list rows. A read-only check through the application's own resolution path confirmed exactly one legacy binding, no readiness failure (the default group is active and reaches the project), allow-lists equal to the environment lists, and that the client secret and the companion redeem URL and token are stored as ciphertext, decrypt with the new key set, pass the row-binding digest and equal the environment values. The rows stay inert until a deployment sets `OAUTH_CONFIG_SOURCE=db`.

Two things follow from the shared database. A binding holds one legacy redeem URL, and the two environments use different ones, so the environment import must be run from the production environment file; the development service stays on `OAUTH_CONFIG_SOURCE=env`, where imported rows are inert. And the OAuth secret key set must be identical wherever a service can write connection credentials to that database.

## Environment cleanup after the rollout

A review of every name in `.env.example` against the code (AST-based: direct reads, constants, name collections, and whether each loaded setting is consumed anywhere) found 257 of 278 names genuinely read. The rest were removed rather than left as documentation of nothing:

- **Loaded but never consumed.** `GOOGLE_OAUTH_LINK_TOKEN_TTL_SECONDS` (link tokens went away with `link/finish`), the `GOOGLE_OAUTH_LINK_TOKEN_RATE_*` and `GOOGLE_OAUTH_JWKS_FETCH_RATE_*` buckets (their limiter methods had no caller, before or after the refactor), `GOOGLE_OAUTH_DEFAULT_USER_GROUP_HASH` (the group comes from the binding), and the passwordless hash secret under both spellings. That last one was *required* by the readiness check although nothing ever derived anything from it; auto-created users get a random unusable password hash. It is no longer required, so three peppers remain, not four. A deployment that still sets any of these is unaffected: the variables are simply ignored.
- **Documentation of things the code never reads.** `PYTEST_VERSION` with a paragraph describing the test-only sign-in paths that no longer exist, `JWT_ALGORITHM` (fixed to HS256 in code), and the commented compose and Dockerfile variables that those files hard-code.

The config fields, constants, limiter methods and their tests went with them, and the static dead-key guard now lists the names so they cannot return. The development environment file lost the passwordless secret and two Patreon e2e flags, which only tests read and tests load their own environment file; its readiness was confirmed through the application's own loaders afterwards.

## Left for a later release, deliberately

The plan's rule 5 is that legacy routes outlive their replacement by at least one consumer release cycle. Deleting them in the same change that introduces the replacement would violate it, and would make deployment order matter. So these are **not** done:

- Removing the `/auth/google/*` aliases and the legacy redeem bridge.
- Removing the `GOOGLE_OAUTH_*` and `PROVIDER_INIT_*` variables and `oauth_clients.py`, which is no longer used by any route (it is kept because a differential test compares the new URL builder against it).
- Removing the consumer's provider-init issue and redeem path.
- ENUM to VARCHAR conversion.

Not built: the Apple adapter (needs POST callback handling, already routed, plus a generated ES256 client secret), hosted-callback delivery, self-service for project administrators, per-binding rate-limit overrides (the column exists; the limiter does not read it yet), and Redis pub/sub cache invalidation (a 30-second TTL bounds staleness).

## Found along the way, outside this change

The billing admin routes reference an error code that does not exist, so two conflict paths would answer `500` instead of `409`. It is pre-existing and unrelated; it was reported separately rather than fixed here.
