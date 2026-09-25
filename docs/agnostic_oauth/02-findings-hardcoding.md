# 02 — Findings: What Is Hardcoded, and To What

The question asked was: *is Google OAuth forced or hardcoded to a single project?* The precise answer has three parts.

| Axis | Verdict | Short reason |
| --- | --- | --- |
| Hardcoded to **one provider** (Google) | **Yes, at every layer** | Literal `"google"` in routes, config, client, state store, provider-init, stored procedures, triggers, column ENUM, activity catalog, audit path detection. |
| Hardcoded to **one OAuth client** per deployment | **Yes** | One `GOOGLE_OAUTH_CLIENT_ID` / `GOOGLE_OAUTH_CLIENT_SECRET` from the environment. No database row, no per-project lookup. |
| Hardcoded to **one project** | **Not in the login flow, but effectively yes in deployment** | The flow is project-scoped (the binding carries `project_hash` and the callback pins to it). But there is exactly one companion backend (`PROVIDER_INIT_REDEEM_URL` + one static bearer), one set of redirect URIs / return origins, and one provisioning policy. Only projects fronted by that single backend can use it. Today that backend is `magic-worlds-api`, which itself holds exactly one `PROJECT_HASH`. |

So the design *intends* to be project-agnostic (the environment template even says "magic-worlds or ANY OTHER PROJECT"), and the identity/project-pinning logic really is. What blocks a second project is **configuration tenancy**: everything a second project would need to supply — its own Google client, its own callback URL, its own origins, its own backend handshake, its own provisioning policy — has nowhere to live except a single global environment.

Findings are numbered `F-nn` and referenced from the plan and risk documents.

## A. Provider coupling (Google literal)

| ID | Where | What |
| --- | --- | --- |
| F-01 | [auth_google.py](../../src/routes/auth_google.py) | Router prefix `/auth/google`; cookie path `/auth/google`; `provider="google"` passed literally to every DB call (`get_user_by_external_account`, `touch_external_account_last_seen`, `create_consumer_user_from_external_account`, `link_external_account`, `unlink_external_account`); metadata sources `google_oauth_auto_create`, `google_oauth_link`; username seed `google_user`; revoke reason `google_oauth_account_unlinked`. |
| F-02 | [oauth_clients.py](../../src/Util/oauth_clients.py) | Authlib registration name `"google"`; class `GoogleOAuthClient`; singleton `google_oauth_client`; scope literal `openid email` in the URL builder independent of config; readiness check requires exactly `{openid, email}`. |
| F-03 | [google_oauth_config.py](../../src/Util/google_oauth_config.py) | Google endpoints compiled in as defaults; scopes validated to be exactly `openid email`; `GoogleOAuthReadiness.provider = "google"`. |
| F-04 | [provider_init.py](../../src/Util/provider_init.py) | `PROVIDER_INIT_PROVIDER = "google"` is both sent in the redeem request and required in the response. `PROVIDER_INIT_AUDIENCE = "api.auth"`. |
| F-05 | [oauth_state.py](../../src/Util/oauth_state.py) | Defaults `provider="google"` when reading and writing state; `create_link_token` forces `provider: "google"`; all Redis prefixes are `google_oauth_*`; store constructor reads the Google config for pepper and fail-closed flag. |
| F-06 | [google_id_token_verifier.py](../../src/Util/google_id_token_verifier.py) | Only `RS256`; issuer tuple defaults to Google; mandatory second verification through the `google-auth` library, which only understands Google-issued tokens; `sanitize_google_claims` stamps `provider: "google"`. |
| F-07 | [10_external_accounts.sql](../../schemas/tables/10_external_accounts.sql) | `provider ENUM('google','patreon')`. Adding a provider is a DDL change. |
| F-08 | [15_external_accounts.sql](../../schemas/stored_procedures/15_external_accounts.sql) | Four procedures guard with `p_provider NOT IN ('google','patreon')`; `sp_create_consumer_user_from_external_account` guards with `p_provider <> 'google'`. |
| F-09 | [05_external_accounts_triggers.sql](../../schemas/triggers/05_external_accounts_triggers.sql) | Insert and update triggers repeat the `('google','patreon')` allow-list. |
| F-10 | [activity_logger.py](../../src/Util/activity_logger.py), [08_activity_logging_tables.sql](../../schemas/tables/08_activity_logging_tables.sql) | Eleven `GOOGLE_OAUTH_*` activity types pinned to `act-cat-064` … `act-cat-074`, with a drift assertion that fails startup/tests when they diverge. |
| F-11 | [api_audit_logger.py](../../src/Util/api_audit_logger.py), [api_audit.py](../../src/middleware/api_audit.py), [auth_context.py](../../src/middleware/auth_context.py) | `is_google_oauth_path` does literal prefix matching on `/auth/google`; the auth-context skip set lists `/auth/google/start` and `/auth/google/callback` by exact string; audit tag `google_oauth`. |
| F-12 | [Models.py](../../src/Util/Models.py) | `GoogleOAuthStartRequest`, `GoogleOAuthStartResponse`. The rest (`ExternalIdentityInfo`, `ExternalIdentityLinkResponse`, `LoginResponse`) is already neutral. |
| F-13 | [auth_constants.py](../../src/Util/auth_constants.py) | Every env var name, Redis prefix, provisioning-mode constant and default scope is `GOOGLE_OAUTH_*`. |
| F-14 | [oauth_rate_limit.py](../../src/Util/oauth_rate_limit.py) | Class names are neutral (`OAuthRateLimiter`) but every limit is read from a `GOOGLE_OAUTH_*` variable and every bucket prefix is `google_oauth_rate:`; bucket keys have no provider or project dimension. |
| F-15 | [tests/static/test_google_oauth_docs_static.py](../../tests/static/test_google_oauth_docs_static.py), [tests/integration/test_google_oauth_migration_rollout.py](../../tests/integration/test_google_oauth_migration_rollout.py) | Static tests assert the Google-only wording, the two-value ENUM and that auto-create "stays Google-only". These are guard rails that a generalisation must consciously rewrite, not accidentally break. |

**Already neutral, reusable as-is:** the `OAUTH_*` / `EXTERNAL_IDENTITY_*` error codes and their public-message and HTTP-status maps in [error_handler.py](../../src/Util/error_handler.py); `auth_method = 'oauth'` in the audit ENUM; `OAuthStateStore` mechanics; PKCE helpers; `resolve_provider_init_bound_project`; the `user_external_accounts` column design (HMAC subject, fingerprint, masked e-mail, no token columns).

## B. Single-client / single-tenant configuration coupling

| ID | What | Why it blocks a second project |
| --- | --- | --- |
| F-20 | One `client_id` / `client_secret` from env. | A second project usually needs its own Google Cloud project (its own consent-screen brand, its own verification status, its own redirect URIs, its own quota and abuse blast radius). |
| F-21 | `GOOGLE_OAUTH_REDIRECT_URIS` is a global CSV and `/start` defaults to its **first** element. | In the BFF topology redirect URIs are per-consumer callback URLs. With two consumers the default is wrong for one of them, and any consumer may request any other consumer's callback URL because the list is not partitioned by project. |
| F-22 | `GOOGLE_OAUTH_RETURN_ORIGINS` and `PROVIDER_INIT_RETURN_ORIGINS` are global CSVs. | Same partitioning problem: origin A is acceptable for project B. |
| F-23 | `PROVIDER_INIT_REDEEM_URL` and `PROVIDER_INIT_REDEEM_TOKEN` are single values. | This is the hardest single-tenant coupling. `api.auth` can call back exactly one companion backend. A second backend cannot redeem its tokens. The bearer is a static shared secret with no key id and no rotation path. |
| F-24 | `GOOGLE_OAUTH_PROVISIONING_MODE` is global. | The environment template itself notes "Provisioning is GLOBAL to this api.auth instance". Project A wanting `both` forces auto-create on for project B. |
| F-25 | `GOOGLE_OAUTH_ALLOWED_HOSTED_DOMAINS` is global. | A B2B project restricting to its Workspace domain would lock every other project to that domain. |
| F-26 | The user group for auto-created users is whatever `user_group_hash` the companion backend asserted. It is only checked for existence and `is_active`, **not** for any relationship to the bound project, and not against an allow-list. | Safe while there is one trusted backend. With several tenants it is a privilege-escalation primitive: backend A can assert project B's hash with any group hash it knows, or a privileged group. See risk R-02. |
| F-27 | `project_hash` in the redeemed binding is accepted from the companion backend without cross-checking that this backend is entitled to speak for that project. | Same trust-model issue as F-26. Identity of the caller is "whoever holds the one bearer". |
| F-28 | Rate-limit buckets are keyed by IP and token fingerprints only. | Behind a BFF the IP is the BFF's. One busy project can exhaust the shared `start` and `callback` budgets for everyone sharing that egress, and there is no per-project dial. |
| F-29 | Pepper and secret names are Google-branded (`GOOGLE_OAUTH_PROVIDER_SUB_PEPPER`, …) and the state store and verifier read them through the Google config object. | Not a tenancy bug (peppers *should* be deployment-wide), but any second provider must reach into "Google" config to hash its subjects. |
| F-30 | `GOOGLE_OAUTH_DEFAULT_USER_GROUP_HASH` is parsed, documented as unused, and never read. | Dead configuration that suggests a per-deployment default that does not exist. |

## C. Magic-Worlds-specific leakage into a supposedly generic service

| ID | Where | What |
| --- | --- | --- |
| F-40 | [architecture.md](../USAGE/google-oauth/architecture.md), [request-flow.md](../USAGE/google-oauth/request-flow.md) | Flow diagrams name `magic-worlds-api` as *the* issuer of provider-init tokens. |
| F-41 | Environment template (Google section comments) | "the companion BFF (magic-worlds-api) is registered as Google's redirect target"; "magic-worlds wants `both`". |
| F-42 | [auth_google.py](../../src/routes/auth_google.py) | Operator comment refers to a row "in magic_auth" (the database name). Every schema file starts with `USE magic_auth;`. The database name is not configurable from SQL files. |
| F-43 | Consumer: `magic-worlds-api/src/services/provider_init.py` | Default issuer literal `magic-worlds-api`, Redis prefixes `mw:provinit` and `mw:oauthret`, cookie `mw_refresh_token`. These are consumer-side and legitimately project-specific, but there is **no reference implementation or SDK-level helper** a second project could reuse; the contract exists only as this one implementation plus `api.auth`'s validator. |
| F-44 | Consumer: `magic_auth_client` package | Endpoint constants `/auth/google/start` and `/auth/google/callback` are compiled into the client library; the only override is two full-URL settings. The shared client library is therefore also Google-only. |
| F-45 | Consumer: `magic-worlds-api/src/main.py` | Exactly one `PROJECT_HASH` and one `USER_GROUP_HASH` in application state. The consumer cannot itself act for two projects. |
| F-46 | Consumer route names and error slugs | `/auth/provider-init/google`, `/auth/google/start/shim`, `/auth/google/callback/return`, `/auth/google/exchange`; slugs `google_start_failed`, `google_denied`, … |

## D. Repository precedent that proves the target is reachable

The billing subsystem already made exactly this journey (global env credentials → per-tenant encrypted database credentials + provider adapter + kill switches). It is the template to copy, not a new invention:

| Need | Existing precedent |
| --- | --- |
| Provider registry in the database with a master kill switch | `billing_providers` in [12_billing_provider_facts.sql](../../schemas/tables/12_billing_provider_facts.sql) (`provider_code VARCHAR`, not an ENUM). |
| Tenant unit that owns credentials and can span projects | `billing_groups` + `billing_group_projects` (unique on `project_id`). |
| Secrets encrypted at rest with key id and rotation | `encrypt_provider_ref` / `decrypt_provider_ref` / `rotate_provider_ref` in [security.py](../../src/Util/billing/security.py); Fernet, `credential_key_id`, `credential_encryption_alg`, decrypt-key map for rotation. |
| Safe display and equality lookup of secrets | `hmac_provider_ref` + 12-char fingerprint in the same module. |
| Credential lifecycle | `credential_status ENUM('absent','active','rotating','revoked')`. |
| Never-cached decrypted secrets | `StripeAccountSecrets` in [account.py](../../src/Util/stripe/account.py): frozen dataclass, `repr=False`, built per request. |
| Validate before store, plus a non-persisting test endpoint | [credentials.py](../../src/Util/stripe/credentials.py) and the `credentials/test` route in [admin_billing.py](../../src/routes/admin_billing.py). |
| Two-tier admin guard (admin may read status, only root may submit secrets) | `require_billing_admin` / `require_billing_root` in [admin_billing.py](../../src/routes/admin_billing.py). |
| Adapter contract | `BillingProviderAdapter` Protocol in [provider.py](../../src/Util/billing/provider.py); `EmailProvider` Protocol and `DisabledEmailProvider` null object in [provider.py](../../src/Util/email/provider.py). |
| Database triggers as fail-closed backstop | [07_billing_provider_facts_triggers.sql](../../schemas/triggers/07_billing_provider_facts_triggers.sql). |
| Global env demoted to "migration-only, kill switch" | Documented in [config.py](../../src/Util/stripe/config.py). |

Two things the precedents do **not** provide and that must be built: a Python-side provider registry/factory keyed by provider code (billing hardcodes `_SUPPORTED_PROVIDERS = {"stripe"}`; e-mail uses an if/elif on one env var), and any per-project settings table (`projects` has no settings or JSON column).

One framing correction worth recording: **Patreon is not a second OAuth provider.** It has no authorize/callback flow; it is a creator-token integration with an e-mail-proof link loop, and its router asserts at import time that no login/authorize/callback route exists. Google and Patreon share only the `user_external_accounts` table. There is therefore no existing second implementation to generalise from — the abstraction has to be designed from the protocol, which [04-research.md](04-research.md) does.
