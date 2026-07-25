# Stripe Billing Runbook

Operational runbook for provider-agnostic billing with Stripe: deploy-disabled rollout, schema/bootstrap checks, fixture validation, sandbox enablement, Checkout/Portal gates, monitoring, incident response, key rotation, retention, rollback, ingress blocking, secret rotation, evidence preservation, and optional live smoke gates.

This runbook is intentionally non-destructive. Rollout enables one narrow behavior at a time, and rollback disables behavior without deleting normalized billing history, purchase history, webhook ledger evidence still under retention, encrypted operational refs required for evidence, audit rows, or activity history.

## Scope and Safety Rules

- Stripe billing is **provider-facts only** for raw provider state. It must not issue local sessions or mutate JWTs, refresh-token state, cookies, or API keys. The one intentional identity projection: project-scoped consumer login, `/auth/validate`, and consumer API-key validation carry a neutral subscription `plan` object (state `none|free|trial|active|past_due|canceled` + `plan_code`/`tier_code`/expiry) resolved through the session project's billing group. Current refresh and switch-project response bodies omit it. Subscriptions only.
- **Billing unit = billing group.** A billing group owns one standalone Stripe account (credentials encrypted in the DB) and one catalog, and can span multiple projects (a standalone project is a group of one). Facts (customers/subscriptions/entitlements) are keyed by `(user, billing_group, provider)`; one subscription applies to every project in the group. Credit purchases keep both `project_id` and `billing_group_id`.
- `api.auth` owns per-group Stripe secret usage, **the centralized product-agnostic catalog** (plans/packages with opaque `features` JSON it never interprets) and its Stripe `Product`/`Price` provisioning, Checkout/Portal session creation, webhook verification, provider fact normalization, encrypted operational refs, idempotency, sync, retention, and redacted audit/activity/metrics.
- Consuming projects own benefits, quotas, membership projection, credit balances, and credit ledgers, and interpret the opaque `features`/`credits` they read back. They no longer hard-code the catalog: they read it from `GET /internal/projects/{project_hash}/billing/catalog`.
- Billing is disabled by default. Enable only the narrow switch required for the current rollout step.
- Never paste real Stripe secrets, webhook secrets, raw provider refs, signed webhook payloads, signatures, idempotency keys, HMACs, fingerprints, card/payment-method details, receipt links, S2S bearer tokens, or real customer data into this runbook, tickets, logs, docs, or chat.

## Kill Switches

Primary generic billing switches:

- `BILLING_ENABLED=false`
- `BILLING_S2S_ENABLED=false`
- `BILLING_CHECKOUT_ENABLED=false`
- `BILLING_PORTAL_ENABLED=false`
- `BILLING_SYNC_ENABLED=false`
- `BILLING_RAW_PAYLOAD_CAPTURE_ENABLED=false`

Stripe provider switches:

- `STRIPE_BILLING_ENABLED=false`
- `STRIPE_WEBHOOKS_ENABLED=false`
- `STRIPE_CHECKOUT_ENABLED=false`
- `STRIPE_PORTAL_ENABLED=false`
- `STRIPE_SYNC_ENABLED=false`

Operational isolation controls:

- Block `/webhooks/stripe` at ingress during active webhook incidents.
- Stop `src/workers/billing_sync_worker.py` to pause source-of-truth repair and retention cadence.
- Disable consumer S2S pulls in the companion service if `api.auth` billing needs isolation.

Do not use destructive schema rollback after live or test billing evidence exists.

## Billing Groups, Catalog & Per-Account Credentials

A billing group is the unit that owns one Stripe account + one catalog and maps to one or
more projects. Provision a group in this order (all behind disabled-by-default flags):

1. **Create the group** — `POST /admin/billing` (dashboard → Billing → New billing
   group), or seed the first one with `scripts/migrations/billing_group_bootstrap.py`
   (`--apply`, dry-run by default, redacted output).
2. **Attach project(s)** — `POST /admin/billing/{hash}/projects` with `project_hash`.
   A project belongs to exactly one group; re-attaching to a different group is rejected
   (409). One subscription then applies to every project in the group.
3. **Set the group's Stripe credentials (root only)** — `PUT /admin/billing/{hash}/credentials`
   with the group's own `secret_key` + `webhook_secret` (+ optional portal config). Sent as
   JSON, encrypted server-side immediately, never echoed (responses show presence flags +
   fingerprints only). Requires `BILLING_PROVIDER_REF_ENCRYPTION_KEY/_ID` +
   `BILLING_ID_HMAC_SECRET`.
4. **Author the catalog** — `POST /admin/billing/{hash}/catalog` (subscription_plan /
   credit_package). When the group is enabled + has active credentials, this provisions a
   Stripe `Product`+`Price` on the group's account and stores encrypted refs; otherwise the
   row stays `pending` and provisions on a later enable. `features` JSON is opaque (api.auth
   never interprets it). Price changes create a new Stripe `Price` and archive the old one.
5. **Point Stripe at the per-account webhook endpoint** — each account's webhook destination
   is `POST /webhooks/stripe/{billing_group_hash}` (its own signing secret is selected by the
   URL; verification is single-attempt). The legacy global `POST /webhooks/stripe` remains as
   a single-account migration fallback that resolves the group from event metadata.
6. **Enable group capabilities** — `checkout_enabled`/`portal_enabled`/`provisioning_enabled`/
   `webhooks_enabled` are gated server-side: they only take effect when the group is `active`
   with `credential_status='active'`. Effective enablement =
   global provider flag AND global config flag AND group flag AND active credentials.

Consumers read the catalog from `GET /internal/projects/{project_hash}/billing/catalog`
(S2S bearer) and the subscription `plan` from `/auth/validate`. After checkout, consumers
should call their reconcile path (a direct S2S read) for credit-grant fulfillment rather
than trusting the cached `plan`.

## Prerequisites

- Additive `billing_*` schema, stored procedures, triggers, DB wrapper, routes, worker, health, metrics, audit, activity, and redaction code are deployed.
- Stripe SDK package is pinned to `15.2.1` and runtime readiness can verify it.
- Stripe API version is pinned to `2026-05-27.dahlia`.
- Secret management exists for Stripe secret key, Stripe webhook secret, billing S2S bearer token, HMAC secret, provider-ref encryption key, provider-ref key id, decrypt key map, and optional raw payload quarantine key.
- Redis is available for rate limits, replay/idempotency helpers, sync locks, and billing worker heartbeat.
- Authenticated operators can inspect `/system/health` without exposing secrets.
- No production secrets or real provider refs are stored in docs, tests, examples, or smoke logs.

## Server-Only Configuration

Keep values in secret/config management, not source control.

Feature flags:

```text
BILLING_ENABLED=false
BILLING_S2S_ENABLED=false
BILLING_CHECKOUT_ENABLED=false
BILLING_PORTAL_ENABLED=false
BILLING_SYNC_ENABLED=false
BILLING_RAW_PAYLOAD_CAPTURE_ENABLED=false
STRIPE_BILLING_ENABLED=false
STRIPE_WEBHOOKS_ENABLED=false
STRIPE_CHECKOUT_ENABLED=false
STRIPE_PORTAL_ENABLED=false
STRIPE_SYNC_ENABLED=false
```

Server-only credential/config key names:

```text
BILLING_S2S_BEARER_TOKEN
BILLING_ID_HMAC_SECRET
BILLING_PROVIDER_REF_ENCRYPTION_KEY
BILLING_PROVIDER_REF_ENCRYPTION_KEY_ID
BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON
BILLING_RAW_PAYLOAD_ENCRYPTION_KEY
BILLING_RAW_PAYLOAD_ENCRYPTION_KEY_ID
STRIPE_SECRET_KEY                 # OPTIONAL — single-account/migration only; not a readiness gate
STRIPE_WEBHOOK_SECRET             # OPTIONAL — global /webhooks/stripe endpoint only
STRIPE_PORTAL_CONFIGURATION_ID    # OPTIONAL — global portal fallback REMOVED; set per-group
```

### Per-group credentials vs. the env secrets (readiness is per group)

Each billing group owns its own Stripe account: its **secret key, webhook secret, and portal
configuration id** are stored encrypted on `billing_groups` and set via
`PUT /admin/billing/{hash}/credentials`. Every real Stripe call (checkout, portal, catalog
provisioning, reconcile, source-of-truth reads, and the path-scoped webhook endpoint) uses the
**per-group** key, fail-closed, with **no fallback to the env secret**.

- `STRIPE_SECRET_KEY` / `STRIPE_WEBHOOK_SECRET` / `STRIPE_PORTAL_CONFIGURATION_ID` are **optional,
  single-account/migration only** and **no longer gate readiness**. SDK/API version pins remain
  fail-closed.
- **Operational readiness is per group.** With a valid access session, read `/system/health` →
  `billing_provider_stripe.per_group` for the true state: `credentials_active` /
  `credentials_absent` / `credentials_rotating` / `credentials_revoked`, `groups_with_webhook_secret`,
  and `webhook_secret_missing_active_groups`. When billing features are enabled but
  `credentials_active == 0`, health reports `not_ready` (reason `no_group_credentials_active`); when
  `webhooks_enabled` and `webhook_secret_missing_active_groups > 0`, health reports `degraded`.
- **Webhook routing.** Multi-account deployments MUST point each Stripe account's webhook at the
  path-scoped `POST /webhooks/stripe/{billing_group_hash}` endpoint (it selects that group's own
  signing secret from the URL — single-attempt verification). The global `POST /webhooks/stripe`
  verifies only against the env `STRIPE_WEBHOOK_SECRET` and is single-account/migration only.
- **Portal config has no env fallback:** a group that offers the Customer Portal must set its own
  `portal_configuration_id`, or portal sessions return the neutral unavailable seam.

### Catalog reconcile + import (pull from Stripe)

The catalog is owned by api.auth (it provisions Product/Price on the group's account). To detect
drift or adopt an existing Stripe catalog, admins can pull from Stripe:

- `GET  /admin/billing/{group_hash}/catalog/reconcile` — read-only: list the group's Stripe
  products/prices, match to local items by HMAC fingerprint (and `lookup_key`), report
  `in_sync` / drift (`price_archived`/`amount_mismatch`/`interval_mismatch`/`unresolved`) and orphan
  import candidates. No writes.
- `POST /admin/billing/{group_hash}/catalog/sync` — reconcile and repair: adopt missing provider refs
  onto existing rows (never overwrites local money/`plan_code`) and record `last_catalog_synced_at` /
  `catalog_sync_status`.
- `POST /admin/billing/{group_hash}/catalog/import` — adopt selected orphan Stripe prices as
  already-provisioned catalog items (idempotent by price fingerprint; `plan_code` derived from
  `lookup_key` → product metadata → product name slug, with conflicts flagged for an override).

All catalog reconcile/import reads use only native Stripe SDK list calls and surface fingerprints
only — never raw `prod_`/`price_` ids.

Safe public configuration values:

```text
STRIPE_API_VERSION=2026-05-27.dahlia
BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS=90
BILLING_RAW_PAYLOAD_RETENTION_DAYS=30
BILLING_SYNC_STALE_AFTER_SECONDS=86400
STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS=300
```

Return-origin allow-list values are not secrets, but keep them environment-specific and exact. Do not use wildcard production origins.

## Setup Baseline

1. Deploy code and additive schema with all billing and Stripe flags disabled.
2. Confirm local auth authority, Google OAuth, email, sessions, refresh tokens,
   API keys, and Patreon remain unaffected. Confirm the intentional
   project-scoped `plan` projection is `none` while billing is disabled.
3. Configure server-only secrets by key name. Do not print values.
4. Run schema/bootstrap checks in dry-run mode first.
5. Using a valid access session, confirm `/system/health` reports billing/Stripe as `disabled` or `not_ready` in billing components only.
6. Enable only one behavior at a time using the deployment order below.

## Schema and Bootstrap Checks

Dry-run bootstrap:

```bash
./.venv/bin/python scripts/migrations/billing_provider_bootstrap.py --dry-run
```

Optional DB readiness check in a controlled environment:

```bash
./.venv/bin/python scripts/migrations/billing_provider_bootstrap.py --dry-run --check-db
```

Apply seed only after readiness review:

```bash
./.venv/bin/python scripts/migrations/billing_provider_bootstrap.py --apply
```

Rules:

- Bootstrap must seed Stripe disabled by default.
- Bootstrap output must remain redacted and operationally opaque.
- Additive schema registration must follow existing Patreon artifacts.
- Do not alter or drop `patreon_*` artifacts.
- Do not widen identity/external-account provider semantics to make Stripe a login provider.

## Fixture Validation Gate

Use sanitized byte-exact fixtures only. Fixture validation should prove:

- no real secrets in fixture files,
- exact raw-body preservation,
- valid signature accepts only unchanged bytes,
- tampered/normalized bodies fail verification,
- unsupported events are safe no-ops,
- approved events map to normalized facts,
- logs/audit/activity do not retain raw body or signature values.

Reference fixture docs: `tests/fixtures/stripe/README.md`.

Suggested targeted validation before enabling webhooks:

```bash
./.venv/bin/python -m pytest tests/unit/test_stripe_security.py tests/integration/test_stripe_webhooks.py -q
```

Do not run live provider tests unless the explicit live smoke gate below is approved.

## Health Checks

Use system health:

Any valid access session is sufficient; this endpoint is not admin-only.

```bash
curl -X GET "${BASE_URL}/system/health" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "User-Agent: ops/1.0"
```

Inspect only non-secret billing components:

- `billing` — generic enablement, S2S, Checkout, Portal, sync readiness.
- `billing_provider_stripe` — provider status, SDK/API version labels, missing key names, mismatch labels.
- `billing_webhooks` — signature failure rate, delivery lag, duplicate delivery count.
- `billing_sync` — pending/running/retry/failed jobs, oldest pending age, worker heartbeat, decrypt failures, retention health.

Disabled billing should not degrade unrelated local authentication health. Enabled but not-ready billing should be visible as a separate component.

## Deployment Order

Run these steps in order. Do not skip from disabled config to broad production exposure.

1. **Deploy disabled**: deploy code, additive schema, docs, worker artifact, and health metrics with every billing and Stripe flag disabled.
2. **Validate auth boundary**: confirm JWTs, cookies, Redis session payloads,
   refresh authority, Google OAuth, email, and Patreon remain free of provider
   state. Confirm project-scoped login/validation/API-key responses expose only
   the allowed subscription `plan`.
3. **Bootstrap provider registry**: run bootstrap dry-run and apply disabled provider seed only after review.
4. **Enable generic S2S read for controlled projects**: set `BILLING_ENABLED=true` and `BILLING_S2S_ENABLED=true` only after S2S bearer/HMAC readiness. Verify projects resolve to the intended billing group, catalog reads are correct, and users without billing rows receive the group-scoped free default.
5. **Enable webhook route in not-mutating posture**: configure each Stripe
   account for `/webhooks/stripe/{billing_group_hash}`; reserve
   `/webhooks/stripe` for explicit single-account migration use. Keep processing
   disabled until signed sanitized fixture validation and raw-body audit
   exclusion pass.
6. **Enable Stripe webhook processing in test mode**: set `STRIPE_BILLING_ENABLED=true` and `STRIPE_WEBHOOKS_ENABLED=true` only in a controlled test environment. Process only approved MVP events.
7. **Enable Checkout for one controlled project**: set `BILLING_CHECKOUT_ENABLED=true` and `STRIPE_CHECKOUT_ENABLED=true` after encryption/HMAC/redaction/idempotency/return-origin checks pass. Require the trusted consumer to select `price_ref` and opaque labels from the project catalog; the current route does not enforce that binding server-side.
8. **Enable Portal after restricted-config proof**: set `BILLING_PORTAL_ENABLED=true` and `STRIPE_PORTAL_ENABLED=true` only after Portal configuration verification proves plan changes are disabled.
9. **Enable sync worker**: set `BILLING_SYNC_ENABLED=true` and `STRIPE_SYNC_ENABLED=true`; start `src/workers/billing_sync_worker.py` after provider readiness, decrypt key map, rate limits, and rollback drills pass.
10. **Coordinate consumers separately**: consuming projects update their own S2S
    client, membership projection, and credit ledger. `api.auth` owns catalog
    Product/Price mappings; consumers own their interpretation and benefits.
11. **Gradual project enablement**: expand by project while monitoring signature failures, webhook lag, stale reads, idempotency conflicts, decrypt failures, sync backlog, and consumer projection errors.

At every step, keep billing out of authentication contracts.

## Sandbox Enablement Gate

For Stripe test-mode/sandbox validation:

1. Use isolated test-mode Stripe credentials from secret management.
2. Use exact test return origins.
3. Configure a test webhook endpoint for
   `/webhooks/stripe/{billing_group_hash}` using that test group's signing
   secret.
4. Enable only the controlled project/cohort.
5. Validate Checkout returns hosted URL plus opaque refs only.
6. Validate Portal returns hosted URL plus opaque `portal_ref` only and plan changes are disabled.
7. Validate webhook events update normalized facts or enqueue resync.
8. Validate consumer projection uses `/auth/validate.plan` only for the narrow
   subscription summary and pulls catalog/detailed purchase facts through S2S.

## Optional Live Smoke Gate

Live/sandbox smoke is opt-in only.

Required gates:

- `RUN_STRIPE_E2E=true` set explicitly for that run only.
- Isolated Stripe test-mode credentials in secret management.
- Test user/project hashes supplied through environment-specific config.
- No real customer data.
- Logs reviewed for no secret/raw provider leaks.
- Rollback path rehearsed before smoke.

Suggested command when approved:

```bash
RUN_STRIPE_E2E=true ./.venv/bin/python -m pytest tests/e2e/test_stripe_live_opt_in.py -q
```

Keep the default `RUN_STRIPE_E2E=false` outside deliberate smoke windows.

## Worker Operations

Queued sync one-shot:

```bash
./.venv/bin/python -m src.workers.billing_sync_worker --once --mode queued --limit 25
```

Retention-only pass:

```bash
./.venv/bin/python -m src.workers.billing_sync_worker --once --mode retention_only
```

Long-running worker:

```bash
./.venv/bin/python -m src.workers.billing_sync_worker
```

Rules:

- Do not run sync when decrypt key map or Stripe readiness is not safe.
- Respect retry/backoff metadata.
- Decrypt operational refs only in memory.
- Log only redacted status/reason/counts.
- Worker heartbeat keys must stay in billing namespace, never auth/session namespace.

## Monitoring

Monitor these safe signals:

| Signal | Why |
| --- | --- |
| Billing readiness status | Confirms default-off/not-ready/ready posture. |
| Stripe SDK/API mismatch labels | Prevents version drift provider mutation. |
| Webhook signature failures | Detects bad secret, proxy mutation, or hostile traffic. |
| Webhook lag | Detects receiver/DB/provider retry issues. |
| Duplicate deliveries | Expected with retries, but spikes may indicate instability. |
| Idempotency conflicts | Consumer retry or idempotency-key misuse. |
| Stale snapshot count | Provider/source-of-truth freshness risk. |
| Sync pending/running/retry/failed jobs | Worker and provider repair health. |
| Decrypt failures | Key rotation/config incident. |
| Retention purge counts | Confirms bounded evidence cleanup. |

Metrics must not contain raw provider refs, secrets, signatures, idempotency keys, payment-method details, receipt links, HMACs, fingerprints, or consumer-owned credit amounts.

## Incident Response

### Webhook signature failure spike

1. Keep invalid deliveries rejected before mutation.
2. Check exact raw-body handling and secret deployment by version label only.
3. Temporarily set `STRIPE_WEBHOOKS_ENABLED=false` or block `/webhooks/stripe` at ingress if active failures continue.
4. Validate with sanitized signed fixtures.
5. Re-enable and run source-of-truth resync for affected scopes if needed.

### SDK/API version mismatch

1. Keep Stripe behavior not-ready.
2. Deploy supported Stripe SDK and API version config.
3. Run targeted Stripe readiness/security tests.
4. Re-enable only after health reports no critical mismatches.

### Decrypt failure

1. Disable affected Checkout/Portal/sync paths.
2. Restore previous decrypt key map through secret management.
3. Verify decryption in controlled maintenance without printing decrypted refs.
4. Run key rotation/re-encryption.
5. Preserve evidence and document only sanitized counts/reasons.

### Checkout/Portal incident

1. Disable `STRIPE_CHECKOUT_ENABLED` and/or `STRIPE_PORTAL_ENABLED` first.
2. Preserve S2S read if safe; otherwise disable `BILLING_S2S_ENABLED` for isolation.
3. Check return-origin allow-list, provider readiness, idempotency conflicts, and Portal restricted configuration.
4. Resume one project/cohort at a time.

### Sync backlog or provider outage

1. Check worker heartbeat and queue counts.
2. Confirm provider readiness and rate limits.
3. Restart worker only after config is safe.
4. Preserve stale/unknown facts until source-of-truth confirmation succeeds.
5. Do not downgrade product membership in `api.auth`; consumer policy decides local behavior.

### PII, secret, or raw evidence leak suspicion

1. Stop further capture: keep `BILLING_RAW_PAYLOAD_CAPTURE_ENABLED=false` and disable affected ingress/worker paths if needed.
2. Preserve audit/activity evidence; do not delete normalized history casually.
3. Rotate exposed Stripe/billing secrets.
4. Purge encrypted raw quarantine within policy once evidence handling is complete.
5. Document only sanitized counts, key names, and timestamps.

## Key Rotation

Provider-ref key rotation:

1. Add new `BILLING_PROVIDER_REF_ENCRYPTION_KEY` and `BILLING_PROVIDER_REF_ENCRYPTION_KEY_ID` in secret management.
2. Keep prior keys available in `BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON`.
3. New writes use the new key id.
4. Run a controlled rotation job that decrypts in memory, re-encrypts with the new key id, verifies HMAC stability, and updates ciphertext/key id.
5. Confirm no rows reference the old key id.
6. Remove old key only after rollback window expires.

Secret rotation after suspected disclosure:

1. Disable Checkout, Portal, webhooks, sync, and raw payload capture.
2. Rotate Stripe secret key and webhook secret in Stripe and secret manager.
3. Rotate billing S2S bearer with coordinated consumer deployment.
4. Rotate HMAC/encryption material only with migration planning; HMAC rotation can affect joins/idempotency.
5. Preserve evidence and run source-of-truth resync after recovery.

## Retention and Purge

Required windows:

| Artifact | Retention |
| --- | --- |
| Webhook delivery ledger | 90 days |
| Encrypted raw payload quarantine | Disabled by default; max 30 days when enabled |
| Normalized billing history | Indefinite |
| Normalized purchase history | Indefinite |

Retention-only worker pass:

```bash
./.venv/bin/python -m src.workers.billing_sync_worker --once --mode retention_only
```

Never use retention purge to erase normalized billing status, purchase history, audit evidence, or activity history.

## Non-Destructive Rollback

Preferred rollback disables behavior and preserves evidence:

1. **Stop new provider actions**: set `STRIPE_CHECKOUT_ENABLED=false`, `STRIPE_PORTAL_ENABLED=false`, `STRIPE_WEBHOOKS_ENABLED=false`, and `STRIPE_SYNC_ENABLED=false`.
2. **Close generic billing if needed**: set `BILLING_CHECKOUT_ENABLED=false`, `BILLING_PORTAL_ENABLED=false`, `BILLING_SYNC_ENABLED=false`, `BILLING_S2S_ENABLED=false`, and finally `BILLING_ENABLED=false` if isolation requires it.
3. **Disable ingress/webhook intake**: block `/webhooks/stripe` at ingress and/or rotate Stripe webhook secret to stop new deliveries.
4. **Stop sync execution**: stop `src/workers/billing_sync_worker.py` and any scheduler/one-shot job that can claim billing sync jobs.
5. **Disable consumer consumption**: consuming projects stop billing S2S pulls and fall back to local product behavior/free-default policy.
6. **Clear only billing/Stripe Redis namespaces when approved**: clean rate-limit, replay, idempotency, sync lock, and heartbeat keys in billing/Stripe namespaces only. Never clear local auth/session/refresh namespaces.
7. **Preserve additive schema and history**: leave `billing_*` schema, normalized current/history, purchase history, webhook ledger within retention, encrypted refs needed for evidence, raw quarantine until retention, audit, and activity rows intact once evidence exists.
8. **Rotate secrets if security-related**: rotate Stripe/billing secrets through secret management.

Redis cleanup scope, when approved:

```text
billing_rate:*
billing_s2s_read:*
billing_checkout_intent:*
billing_portal_session:*
billing_purchase_status:*
billing_resync:*
billing_webhook_delivery:*
billing_sync_job:*
billing_sync_lock:*
billing_retention_lock:*
stripe_rate:*
```

Do not clear unrelated `session:*`, `refresh_family:*`, `refresh_token:*`, `user_sessions:*`, API-key, Google OAuth, email, or Patreon namespaces as part of Stripe billing rollback.

Destructive schema rollback is refused in environments with any billing provider, customer, checkout intent, subscription, current entitlement, entitlement history, purchase event, purchase history, webhook delivery, sync job, raw quarantine, audit, or billing activity evidence.

## Evidence Checklist

- [ ] Feature flags captured by key name only.
- [ ] `/system/health` billing components captured without secrets.
- [ ] SDK/API version readiness captured.
- [ ] Bootstrap/schema readiness captured without raw provider refs.
- [ ] Fixture/webhook signature validation captured without signatures or payloads.
- [ ] S2S response reviewed for allow-listed fields only.
- [ ] Checkout/Portal responses reviewed for hosted URLs plus opaque local refs only.
- [ ] Activity evidence captured from `act-cat-091` through `act-cat-106` as counts/statuses only.
- [ ] Retention windows preserved.
- [ ] Rollback, if used, was non-destructive.
- [ ] No raw provider refs, secrets, signatures, payloads, HMACs, fingerprints, idempotency keys, payment-method details, receipt links, or consumer-owned credit amounts were pasted into incident records.

---

**Document Version**: 1.0
