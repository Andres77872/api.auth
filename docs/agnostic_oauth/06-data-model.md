# 06 — Data Model, Secrets, Administration

Proposed schema for database-resident, project-related OAuth configuration. SQL is illustrative (MySQL 8, InnoDB, `utf8mb4`), written in the repository's idiom (`CREATE TABLE IF NOT EXISTS`, hash identifiers for external use, generated columns for conditional uniqueness, triggers as a fail-closed backstop). Nothing here has been applied.

## 1. Entity overview

```text
oauth_provider_catalog 1 ───< oauth_connections 1 ───< project_oauth_bindings >─── 1 projects
        (type registry,            (credentials,              (per-project policy)        |
         kill switch)               endpoints)                          |                  |
                                         |                              └──< project_oauth_allowed_urls
                                         |                              └─── default_user_group → user_groups
                                         └ ─ ─ ─ (first seen) ─ ─ ─ ┐
                                                                     v
users 1 ───────────────────────────────────────────────< user_external_accounts
                                                          key: (identity_namespace, subject HMAC)
```

## 2. `oauth_provider_catalog` — provider type registry

Mirror of `billing_providers`. One row per provider type that the code base has an adapter for.

```sql
CREATE TABLE IF NOT EXISTS oauth_provider_catalog (
    id VARCHAR(64) NOT NULL,
    provider_type VARCHAR(32) NOT NULL,              -- 'google', 'microsoft', 'apple', 'github', 'oidc', 'patreon'
    display_name VARCHAR(120) NOT NULL,
    protocol ENUM('oidc','oauth2','custom') NOT NULL,
    status ENUM('disabled','enabled','degraded','archived') NOT NULL DEFAULT 'disabled',
    login_enabled BOOLEAN NOT NULL DEFAULT FALSE,    -- master switch; patreon stays FALSE forever
    link_enabled BOOLEAN NOT NULL DEFAULT FALSE,
    tenant_endpoints_allowed BOOLEAN NOT NULL DEFAULT FALSE,  -- TRUE only for 'oidc'
    default_scopes VARCHAR(512) NULL,
    capability_metadata JSON NULL,                   -- informational mirror of adapter capabilities
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_oauth_provider_type (provider_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

Seeded with `INSERT … ON DUPLICATE KEY UPDATE`. `patreon` is seeded with `protocol='custom'`, `login_enabled=FALSE` so that the external-accounts foreign key (section 5) covers the existing Patreon rows and so that the database itself keeps refusing Patreon logins.

A start-up assertion (like `assert_google_oauth_activity_catalog_alignment`) verifies that every `enabled` catalog row has a registered adapter and that `capability_metadata` matches the code — drift between data and code fails loudly instead of at the first login.

## 3. `oauth_connections` — credentials and endpoints

```sql
CREATE TABLE IF NOT EXISTS oauth_connections (
    id VARCHAR(64) NOT NULL,
    connection_hash VARCHAR(255) NOT NULL,           -- external identifier for admin routes
    provider_type VARCHAR(32) NOT NULL,
    owner_project_id VARCHAR(64) NULL,               -- NULL = platform-owned, shareable across projects
    display_name VARCHAR(120) NOT NULL,
    status ENUM('draft','active','disabled','archived') NOT NULL DEFAULT 'draft',

    client_id VARCHAR(512) NOT NULL,
    client_secret_ciphertext LONGBLOB NULL,
    client_secret_hmac BINARY(32) NULL,
    client_secret_fingerprint CHAR(12) NULL,
    signing_key_ciphertext LONGBLOB NULL,            -- Apple .p8 private key; NULL elsewhere
    signing_key_fingerprint CHAR(12) NULL,
    credential_key_id VARCHAR(128) NULL,
    credential_encryption_alg VARCHAR(32) NOT NULL DEFAULT 'fernet-v1',
    credential_status ENUM('absent','active','rotating','revoked') NOT NULL DEFAULT 'absent',
    credentials_set_at DATETIME NULL,
    credentials_set_by VARCHAR(64) NULL,

    issuer VARCHAR(512) NULL,                        -- pinned; honoured only when tenant_endpoints_allowed
    discovery_url VARCHAR(1024) NULL,
    authorize_endpoint VARCHAR(1024) NULL,
    token_endpoint VARCHAR(1024) NULL,
    jwks_uri VARCHAR(1024) NULL,
    userinfo_endpoint VARCHAR(1024) NULL,

    scopes VARCHAR(512) NOT NULL,
    restrictions JSON NULL,                          -- {"hosted_domains":[...]} / {"tenant_ids":[...]} / {"orgs":[...]}
    provider_params JSON NULL,                       -- {"team_id":"…","key_id":"…"} (Apple), {"tenant":"…"} (Microsoft)
    identity_namespace VARCHAR(191) NOT NULL,        -- computed by the adapter at write time

    created_by VARCHAR(64) NULL,
    updated_by VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,

    PRIMARY KEY (id),
    UNIQUE KEY uk_oauth_connection_hash (connection_hash),
    INDEX idx_oauth_connection_owner (owner_project_id, status),
    INDEX idx_oauth_connection_type (provider_type, status),
    CONSTRAINT fk_oauth_connection_type FOREIGN KEY (provider_type)
        REFERENCES oauth_provider_catalog(provider_type) ON UPDATE CASCADE,
    CONSTRAINT fk_oauth_connection_owner FOREIGN KEY (owner_project_id)
        REFERENCES projects(id) ON DELETE RESTRICT ON UPDATE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

Design notes:

- **`identity_namespace` is immutable once any identity references it.** Changing a connection's issuer, tenant or team changes who its subjects are; silently re-pointing it would let a new IdP impersonate previously linked users. A trigger rejects updates to `identity_namespace` (and to `issuer` / `provider_params` fields that feed it) while linked rows exist. Operators create a new connection instead.
- **`owner_project_id ON DELETE RESTRICT`**: deleting a project must not cascade-delete a connection other projects may be bound to; and must not orphan secrets silently.
- `client_id` is not secret, but it is still excluded from public responses; only the `providers` listing data (connection key, type, display name) is public.
- A trigger mirrors the billing backstop: `status='active'` requires `credential_status='active'`, which requires ciphertext + `credential_key_id`; HMAC columns must be exactly 32 bytes; endpoint columns must be NULL unless the catalog row allows tenant endpoints.

## 4. `project_oauth_bindings` and allow-lists — per-project policy

```sql
CREATE TABLE IF NOT EXISTS project_oauth_bindings (
    id VARCHAR(64) NOT NULL,
    project_id VARCHAR(64) NOT NULL,
    connection_id VARCHAR(64) NOT NULL,
    connection_key VARCHAR(64) NOT NULL,             -- slug used in routes: 'google', 'acme-okta'
    enabled BOOLEAN NOT NULL DEFAULT FALSE,
    login_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    link_enabled BOOLEAN NOT NULL DEFAULT TRUE,
    provisioning_mode ENUM('disabled','link_only','auto_create','both') NOT NULL DEFAULT 'disabled',
    default_user_group_id VARCHAR(64) NULL,
    existing_user_policy ENUM('deny','join_default_group') NOT NULL DEFAULT 'deny',
    init_mode ENUM('api','legacy_redeem') NOT NULL DEFAULT 'api',
    legacy_redeem_url_ciphertext LONGBLOB NULL,
    legacy_redeem_token_ciphertext LONGBLOB NULL,
    delivery_mode ENUM('bff','hosted') NOT NULL DEFAULT 'bff',
    state_ttl_seconds SMALLINT UNSIGNED NULL,        -- NULL = deployment default; capped by env ceiling
    rate_limit_overrides JSON NULL,                  -- may only lower the deployment ceilings
    created_by VARCHAR(64) NULL,
    updated_by VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME NULL,
    PRIMARY KEY (id),
    UNIQUE KEY uk_project_oauth_key (project_id, connection_key),
    UNIQUE KEY uk_project_oauth_connection (project_id, connection_id),
    CONSTRAINT fk_pob_project FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
    CONSTRAINT fk_pob_connection FOREIGN KEY (connection_id) REFERENCES oauth_connections(id) ON DELETE RESTRICT,
    CONSTRAINT fk_pob_group FOREIGN KEY (default_user_group_id) REFERENCES user_groups(id) ON DELETE SET NULL
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

CREATE TABLE IF NOT EXISTS project_oauth_allowed_urls (
    id VARCHAR(64) NOT NULL,
    binding_id VARCHAR(64) NOT NULL,
    kind ENUM('redirect_uri','return_origin','return_to') NOT NULL,
    url VARCHAR(2048) NOT NULL,
    url_hash BINARY(32) NOT NULL,                    -- SHA-256 of the exact string; unique + lookup key
    created_by VARCHAR(64) NULL,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id),
    UNIQUE KEY uk_poau (binding_id, kind, url_hash),
    CONSTRAINT fk_poau_binding FOREIGN KEY (binding_id) REFERENCES project_oauth_bindings(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;
```

Design notes:

- A **row per URL** rather than a CSV or JSON array: exact-match lookup by hash, no parsing, individually auditable add/remove, and no "default to the first element" behaviour (finding F-21). `/start` must always receive an explicit `redirect_uri` unless the binding has exactly one.
- Write-time validation: `https` required outside development; no wildcards; no fragments; origins must be scheme + host + optional port only.
- **`default_user_group_id` must reach the project.** The stored procedure that writes a binding verifies the group → project-group → project chain (`user_group_project_groups`, `project_group_members`). The pipeline re-verifies at use time, since group wiring can change later. This is the structural fix for finding F-26: the group comes from a validated row, not from the caller.
- `existing_user_policy` is the answer to gap G-27. `join_default_group` adds an already-known identity to this project's default group on first login here; `deny` keeps today's behaviour. Default is `deny`.
- If a connection is *owned* by project A, binding it to project B requires the actor to administer both, or root.

## 5. Changes to `user_external_accounts`

| Change | From | To |
| --- | --- | --- |
| `provider` | `ENUM('google','patreon')` | `VARCHAR(32)` with a foreign key to `oauth_provider_catalog(provider_type)` |
| new `identity_namespace` | — | `VARCHAR(191) NOT NULL`; backfilled with the current `provider` value (`google`, `patreon`) |
| new `connection_id` | — | `VARCHAR(64) NULL`, informational "first seen through", `ON DELETE SET NULL` |
| unique subject key | `(provider, active_provider_sub_hash)` | `(identity_namespace, active_provider_sub_hash)` |
| unique per-user key | generated from `user_id : provider` | generated from `user_id : identity_namespace` |

**No re-hashing.** The HMAC input stays the raw provider subject and the key stays the existing pepper value, so every current Google link keeps resolving. This is the single most important migration invariant; see risk R-01.

The five stored procedures and two triggers replace their literal `IN ('google','patreon')` checks with an existence check against the catalog. `sp_create_consumer_user_from_external_account` replaces `p_provider <> 'google'` with: catalog `login_enabled`, **and** takes `p_binding_id` instead of a caller-chosen group — the procedure reads `provisioning_mode` and `default_user_group_id` from the binding itself and refuses when the mode does not permit auto-creation. That moves the provisioning policy check into the same transaction that creates the user.

### The ENUM → VARCHAR conversion

This is the first non-additive schema change in the repository:

- `MODIFY COLUMN` from ENUM to VARCHAR rebuilds the table, and the virtual generated column `active_user_provider` plus its unique index depend on `provider`. Expect: drop the dependent generated column and indexes, modify, add the new column, backfill, recreate generated columns and unique keys — in one maintenance step. The table holds one row per linked identity, so the rebuild is short, but it takes a metadata lock.
- [schema_sync.py](../../scripts/schema_sync.py) knows `ENUM_PATCHES` and `COLUMN_PATCHES`; it has no concept of a type change or of rebuilding generated columns. It needs a new, explicitly ordered patch kind.
- [test_google_oauth_migration_rollout.py](../../tests/integration/test_google_oauth_migration_rollout.py) asserts today that the provider ENUM is only ever widened additively and that auto-create stays Google-only. Those assertions encode the old design and must be rewritten deliberately, together with the change.

**Lower-risk alternative:** keep the ENUM and widen it per provider type through the existing `ENUM_PATCHES` mechanism, adding only `identity_namespace`. Cost: every new provider *type* needs DDL (new *connections* of existing types do not). Since provider types also require a code deployment (an adapter), that coupling is tolerable. **Recommendation:** take the ENUM-widening path in the first release to keep the migration additive, and schedule the VARCHAR + foreign-key conversion as a separate, isolated change once the rest is stable.

## 6. Secrets handling

| Aspect | Rule |
| --- | --- |
| Algorithm | `fernet-v1` via the helper extracted from [security.py](../../src/Util/billing/security.py); column `credential_encryption_alg` allows a later move to AES-GCM with associated data without a schema change. |
| Keys | OAuth-specific: `OAUTH_SECRET_ENCRYPTION_KEY`, `OAUTH_SECRET_ENCRYPTION_KEY_ID`, `OAUTH_SECRET_DECRYPTION_KEYS_JSON`. Not shared with billing. |
| Row binding | `client_secret_hmac = HMAC(OAUTH_SECRET_HMAC_KEY, "v1:oauth:<connection_id>:client_secret:<value>")`, verified after decryption; detects ciphertext moved between rows. |
| Display | 12-character fingerprint and `credentials_set_at` only. No API returns a secret, a ciphertext or an HMAC. |
| Lifetime in memory | Decrypted inside the callback immediately before the token exchange, on a frozen `repr`-suppressed object; never cached, never placed in Redis, never in exception messages. |
| Rotation of the encryption key | Add the new key as active, keep the old one in the decrypt map, run a re-encrypt job (`rotate_provider_ref` equivalent), then remove the old key. Runbook to be modelled on [stripe-billing.md](../RUNBOOKS/stripe-billing.md). |
| Rotation of a client secret | `credential_status='rotating'` allows the new secret to be validated with a live probe before it replaces the old one. |
| What is **not** in the database | Peppers, the state HMAC key and the encryption keys stay in the environment. |
| Redaction | Add `client_secret`, `signing_key`, `legacy_redeem_token` and their ciphertext column names to `OAUTH_SENSITIVE_FIELD_NAMES` in [error_handler.py](../../src/Util/error_handler.py) and to the DTO forbidden-field list pattern used for billing in [Models.py](../../src/Util/Models.py). |
| Static guard | Extend the existing "forbidden token columns" static test so that `user_external_accounts` still can never gain token columns, and so that no plaintext `client_secret` column can be added to the new tables. |

## 7. Administration API (proposed)

Modelled on the billing credentials routes in [admin_billing.py](../../src/routes/admin_billing.py).

| Route | Guard | Purpose |
| --- | --- | --- |
| `GET /admin/oauth/providers` | admin | Catalog with status and whether an adapter is registered. |
| `PUT /admin/oauth/providers/{provider_type}` | root | Enable / disable / degrade a provider type (kill switch). |
| `GET /admin/oauth/connections` | admin (scoped to administered projects) | List with status, fingerprint, readiness. |
| `POST /admin/oauth/connections` | root at first; project admin for owned connections later | Create as `draft`. Generic `oidc` type stays root-only. |
| `GET /admin/oauth/connections/{connection_hash}` | admin | Non-secret config, credential status, fingerprint, bound projects. |
| `PUT /admin/oauth/connections/{connection_hash}` | same as create | Update non-secret fields; namespace-affecting fields rejected once identities are linked. |
| `PUT /admin/oauth/connections/{connection_hash}/credentials` | root (secret-accepting) | Write-only secret submission; validate → probe → store. |
| `POST /admin/oauth/connections/{connection_hash}/credentials/test` | root | Non-persisting validation and live probe. |
| `POST /admin/oauth/connections/{connection_hash}/activate`, `…/disable` | admin | Status transitions; disabling takes effect on in-flight transactions at the callback re-check. |
| `GET /admin/oauth/projects/{project_hash}/bindings` | project admin | List bindings and readiness roll-up. |
| `PUT /admin/oauth/projects/{project_hash}/bindings/{connection_key}` | project admin | Policy: enabled, provisioning mode, default group, existing-user policy, delivery mode. |
| `POST` / `DELETE /admin/oauth/projects/{project_hash}/bindings/{connection_key}/urls` | project admin | Add or remove one allow-listed URL. |
| `GET /admin/oauth/projects/{project_hash}/readiness` | project admin | Single answer to "why is the button not working": which of global switch, catalog, connection status, credential status, binding, URLs, group wiring is failing. |

Starting root-only for anything that accepts a secret copies the billing precedent and keeps the first release's blast radius small. Self-service for project administrators is a later, separate decision (see [09-open-questions.md](09-open-questions.md)).

Every admin write emits a new activity type (`oauth_connection_created`, `oauth_connection_updated`, `oauth_connection_credentials_set`, `oauth_connection_status_changed`, `oauth_binding_updated`, `oauth_binding_url_added`, `oauth_binding_url_removed`) with actor, target hashes and changed **field names** — never values.

## 8. Activity and audit vocabulary

- Keep `google_oauth_*` (`act-cat-064` … `act-cat-074`) untouched for history and for the legacy alias routes.
- Add generic `oauth_*` equivalents under new catalog ids (the highest id in use at review time is 106), emitted by the shared pipeline with `provider_type`, a connection fingerprint and the project id in the details. Extend `_safe_details`' allow-list accordingly — and add `sub_reason`, fixing gap G-04.
- Replace `is_google_oauth_path` with a prefix check covering `/auth/oauth/` and the legacy `/auth/google/` alias; same for the auth-context skip list.
- `auth_method = 'oauth'` already exists in the audit ENUM; no change needed.

## 9. Redis key space

| Today | Proposed | Migration |
| --- | --- | --- |
| `google_oauth_state:` | `oauth_state:` | Callback reads new prefix first, then legacy, for one maximum state TTL (10 minutes) after deploy; then legacy read is removed. |
| `google_oauth_state_consumed:` | `oauth_state_consumed:` | Same. |
| `google_oauth_link:` | removed (link completes in callback) | — |
| `google_oauth_reauth:` | `oauth_reauth:` | Never written today; no migration. |
| `google_oauth_rate:<bucket>:<ip…>` | `oauth_rate:<bucket>:<project>:<connection>:<ip…>` | Counters reset on deploy; acceptable. |
| — | `oauth_init:` | New, for `POST /auth/oauth/init`. |
| — | process-local JWKS and discovery caches | Not in Redis: public data, and keeping it in-process avoids a poisoning path through a shared cache. |

State records gain `connection_id`, `project_id`, `provider_type`, `expected_issuer`, `delivery_mode`, and for link/reauth `user_id` and `session_id`. The record `version` field (already present, value `1`) becomes `2`; the consumer rejects unknown versions.

## 10. Files a schema change must touch

New canonical files (next free numbers): a tables file `13_…`, a stored-procedures file `19_…`, a triggers file `08_…`. Each must be added, in order, to all of:

- the ordered list in [create_database.py](../../scripts/create_database.py),
- the ordered list in [recreate_database.py](../../scripts/recreate_database.py),
- the MySQL init volume list in the test compose file,
- `PATCH_FILES`, and where relevant `COLUMN_PATCHES` / `ENUM_PATCHES`, in [schema_sync.py](../../scripts/schema_sync.py),
- the schema index in [schemas/docs/README.md](../../schemas/docs/README.md), which a static test cross-checks against the SQL files,
- seed rows for the new activity types in [08_activity_logging_tables.sql](../../schemas/tables/08_activity_logging_tables.sql).

Every schema file begins with `USE magic_auth;`. That database name is a Magic-Worlds-era artefact (finding F-42). It is harmless for a single deployment, but a truly project-neutral distribution would parameterise it; that is out of scope for the OAuth work and noted only for completeness.
