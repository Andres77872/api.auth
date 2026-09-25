# OAuth Runbook (Provider-agnostic)

Operations for database-configured OAuth sign-in. Reference: [OAuth reference](../USAGE/oauth/reference.md). The Google-only procedures in the [Google OAuth runbook](google-oauth.md) still apply while `OAUTH_CONFIG_SOURCE=env`.

## Invariants — read before touching anything

1. **Never change a pepper value.** `OAUTH_PROVIDER_SUB_PEPPER` (or `GOOGLE_OAUTH_PROVIDER_SUB_PEPPER`) keys every linked identity. A different value orphans all of them: returning users are locked out, or — with auto-create on — silently receive a new empty account. When introducing the `OAUTH_*` names, copy the values exactly; if both names are set and differ, every OAuth request fails closed (the settings are loaded on first use, so startup does not catch it).
2. **Secrets are write-only.** No API, log line or audit row returns a client secret. Compare fingerprints, never values.
3. **A connection's issuer, tenant or team cannot change once identities are linked.** Create a new connection instead.
4. **Rollback of the configuration source is one variable:** `OAUTH_CONFIG_SOURCE=env`.

## Migrate From Environment to Database

```text
python scripts/schema_sync.py --env-file .env --dry-run
python scripts/schema_sync.py --env-file .env --apply
python scripts/schema_sync.py --env-file .env --verify
```

The plan must show only: widen the provider ENUM by appending, add `identity_namespace` / `connection_id` / `active_user_namespace`, execute the canonical OAuth files, backfill `identity_namespace = provider`, swap the two unique keys, drop the stale generated column. It never rewrites `provider_sub_hash` and never deletes a row. On a database that is behind the canonical schema in other areas the same run also catches those up (for example missing `billing_groups` columns), because the script re-executes every canonical file it owns. A second `--dry-run` afterwards must plan nothing beyond re-executing the canonical files and the two activity-catalog upserts.

### Applying to a live database

The running services may stay up: the previous release works unchanged against the new schema (its provider-keyed procedures keep their signatures, and the insert trigger defaults `identity_namespace` to the provider). The apply is **forward-only** — MySQL commits every DDL statement on its own, so an error leaves a partly applied schema, never a rolled-back one. Every step is idempotent: after any failure fix the cause and run `--apply` again.

1. Take a logical backup that includes routines; a default `mysqldump` omits them, and this schema is procedure-driven:

   ```text
   mysqldump --single-transaction --routines --triggers --events --hex-blob --set-gtid-purged=OFF magic_auth
   ```

2. Check the one data precondition. The backfill updates every existing row through the new update trigger, so a legacy row that violates an invariant aborts it. This must return `0`:

   ```sql
   SELECT COUNT(*) FROM user_external_accounts
    WHERE OCTET_LENGTH(provider_sub_hash) <> 32 OR CHAR_LENGTH(provider_sub_fingerprint) <> 12
       OR (status = 'linked' AND unlinked_at IS NOT NULL)
       OR (unlinked_at IS NOT NULL AND unlinked_at < linked_at)
       OR (last_seen_at IS NOT NULL AND last_seen_at < linked_at);
   ```

3. Check nothing holds a metadata lock on the tables being altered (`performance_schema.metadata_locks`). The apply sets a session `lock_wait_timeout` of 15 seconds (`SCHEMA_SYNC_LOCK_WAIT_TIMEOUT`) so that a blocked `ALTER` fails instead of queueing every later query behind it.
4. `--apply`, then `--verify`. Verification checks outcomes, not only object names: the two namespace unique keys exist, the provider-keyed keys and `active_user_provider` are gone, no row has an empty `identity_namespace`, every provider in use has a catalog row, and the OAuth activity rows are seeded.

Stored procedures and triggers are replaced with `DROP` followed by `CREATE`, so each object is absent for a few milliseconds; prefer a quiet hour. Rows in `oauth_provider_catalog` are schema, not disposable data: the external-account triggers refuse writes for a provider without one.

If the provider-keyed shape is ever needed again, it can be restored without touching data, because `identity_namespace` equals `provider` for every Google and Patreon row:

```sql
ALTER TABLE user_external_accounts ADD COLUMN active_user_provider VARCHAR(160)
  GENERATED ALWAYS AS (CASE WHEN status = 'linked' THEN CONCAT(user_id, ':', provider) ELSE NULL END) VIRTUAL;
ALTER TABLE user_external_accounts ADD UNIQUE KEY uk_external_accounts_active_sub (provider, active_provider_sub_hash);
ALTER TABLE user_external_accounts ADD UNIQUE KEY uk_external_accounts_user_provider (active_user_provider);
```

Generate the OAuth secret key set (separate from billing) and set `OAUTH_SECRET_ENCRYPTION_KEY`, `OAUTH_SECRET_ENCRYPTION_KEY_ID`, `OAUTH_SECRET_HMAC_KEY`, then:

```text
python scripts/migrations/oauth_env_import.py --env-file .env \
    --project-hash <project> --default-user-group-hash <group> --dry-run
python scripts/migrations/oauth_env_import.py ... --apply
```

`PROVIDER_INIT_REDEEM_URL` must be `https://` (plain `http://` only to `localhost`, `127.0.0.1` or `::1`); an internal hostname is fine. api.auth refuses to send the redeem bearer anywhere else, so an imported plain-http URL fails every legacy sign-in with reason `provider_init_redeem_url_unsafe`, and the redeem call never follows redirects.

`--project-hash` and `--default-user-group-hash` must be exactly the project and group the companion backend sends today. Database bindings reject a redeemed scope that differs from their own; a mismatch shows up as `oauth_init_rejected` / `google_oauth_provider_init_rejected` activity with reason `provider_init_project_not_bound` or `provider_init_group_not_bound`. Prove it in staging, then set `OAUTH_CONFIG_SOURCE=db`.

Verification: one successful sign-in; `GET /admin/oauth/projects/{project_hash}/readiness` all green; grep logs and `api_audit_log` for the client secret — zero hits.

## Set Up a Development Environment

Development gets its **own database**. Sharing production's forces one binding to carry both
localhost and production URLs, and nothing downstream can then tell which one it meant.

```bash
cp .env.dev.example .env.dev          # fill the marked values; every URL must be local
python scripts/create_database.py     # against the LOCAL database
python scripts/dev_env_setup.py --env-file .env.dev --dry-run
python scripts/dev_env_setup.py --env-file .env.dev --apply
```

`--apply` seeds a dev project, its default project group, membership and the
admin/user/readonly user groups, then delegates the connection and binding to
`oauth_env_import` so encryption and binding rules stay in one place. It is idempotent:
ids and hashes are deterministic, so re-running converges instead of duplicating. It
prints the `PROJECT_HASH` and `DEFAULT_USER_GROUP_HASH` to wire into the dev BFF.

It refuses to run unless `DB_HOST` is a loopback address, `APP_ENV` is not production, and
every configured URL is local. `--allow-remote-host` lifts the host and URL checks for a
containerised dev database on a LAN address — never to point dev at production.

The schema files hardcode `USE magic_auth`, so the dev database keeps that **name** and is
isolated by **host**. A dev binding should list exactly one redirect URI and one return
origin; with several, `link/start` and `reauth/start` refuse to guess and return 400 unless
the caller names its `return_origin`.

## Diagnose "sign-in does not work"

1. `GET /admin/oauth/projects/{project_hash}/readiness` names the failing layer.
2. Activity log, filtered by `oauth_*` (or `google_oauth_*` for the alias routes). `reason` is the public category; `sub_reason` is the precise operator-only cause:

| `sub_reason` | Meaning |
| --- | --- |
| `auto_create_disabled` | New identity, binding does not allow auto-create |
| `no_bound_user_group` / `user_group_not_found` | No usable provisioning group |
| `email_collision_link_required` / `email_collision` | A local account already has this e-mail; the user must sign in and link |
| `existing_user_not_active_consumer` | Identity belongs to an inactive or non-consumer account |
| `binding_not_found` / `credentials_not_active` | Logged with `reason` `connection_not_configured` (or `connection_disabled`): the binding or connection was removed, disabled or left without active credentials since the round trip started |
| `credentials_undecryptable` | Encryption key for this row's key id is not loaded |

3. `OAUTH_PROJECT_ACCESS_DENIED` for a user who signed up at another project: the binding's `existing_user_policy` is `deny` (default). Switch to `join_default_group` only if signing in here should grant access.

## Rotate a Client Secret

Create the new secret at the provider, then `POST …/credentials/test` and `PUT …/credentials` with only `client_secret`; a stored `signing_key` is kept (send `""` to remove one). The old secret stops being used immediately; the fingerprint in the response must match the one the test reported. No restart.

## Rotate the Encryption Key

1. Add the new key as active (`OAUTH_SECRET_ENCRYPTION_KEY`, new `_KEY_ID`); put the previous key in `OAUTH_SECRET_DECRYPTION_KEYS_JSON`. Deploy.
2. Re-save each connection's credentials (or re-encrypt with `reencrypt_secret`). A save re-encrypts the secret it omits under the new key too, so sending one secret is enough. The row-binding HMAC does not change.
3. When no row references the old key id (`SELECT DISTINCT credential_key_id FROM oauth_connections`), remove it from the map.

Losing every key is an outage, not data loss: re-enter the secrets from the provider consoles.

## Emergency Switches

| Need | Action |
| --- | --- |
| Stop new OAuth sign-ins (`init`, `providers`, `start`) | `OAUTH_ENABLED=false`; link and reauth for signed-in users keep working, so also disable the connections to stop those |
| Stop one provider type everywhere | `PUT /admin/oauth/providers/{provider_type}` with `status: disabled` |
| Stop one client | `POST /admin/oauth/connections/{connection_hash}/disable` |
| Stop one project | Binding `enabled: false` |

Each takes effect on in-flight transactions: the callback re-resolves the connection after consuming state. Cached rows expire within 30 seconds on other instances.

## Add a Provider Type

Needs a deployment: an adapter under the OAuth adapters package, registration in the registry, a catalog seed row, and appending the value to the `user_external_accounts.provider` ENUM (canonical table file plus `ENUM_PATCHES`). New *connections* of an existing type need no deployment.
