# Patreon Link Runbook

Operational runbook for Patreon account linking, creator-token access, webhooks, tier-map seeding, source-of-truth resync, Magic Worlds S2S entitlement reads, retention, incident response, rollout, and non-destructive rollback.

This runbook includes the Phase 11 deployment-order and rollback-readiness checklist. It is intentionally non-destructive: rollout enables one narrow behavior at a time, and rollback disables behavior without deleting Patreon link, snapshot, webhook, proof, unlink, audit, or activity history.

## Scope and Safety Rules

- Patreon is **entitlement/link only**. It is not a local login provider, must not issue local sessions, and must not mutate JWTs, refresh-token state, cookies, API keys, or `/auth/validate`.
- `api.auth` owns Patreon link authority, proof lifecycle, webhook verification, source-of-truth resync, normalized snapshots, entitlement classification, retention, and redacted audit/activity evidence.
- Magic Worlds is a companion consumer: it calls api.auth S2S entitlement endpoints and receives only normalized allow-listed fields.
- The feature is disabled by default. Enable only the narrow switch required for the current rollout step.
- Never paste real Patreon IDs, real campaign/tier IDs, real member emails, real tokens, raw secrets, raw webhook payloads, signatures, HMAC hashes, hash prefixes, fingerprints, or audit rows into this runbook, tickets, logs, docs, or chat.

## Kill Switches

Primary switches:

- `PATREON_LINKING_ENABLED=false` — disables new user link/proof/unlink behavior.
- `PATREON_WEBHOOKS_ENABLED=false` — disables webhook processing behavior.
- `PATREON_SYNC_ENABLED=false` — disables scheduled/source-of-truth provider sync work.
- `PATREON_S2S_ENTITLEMENT_ENABLED=false` — disables companion S2S entitlement reads.

Secondary switches:

- `PATREON_CREATOR_TOKEN_REFRESH_ENABLED=false` — disables automatic creator-token refresh/persistence.
- `PATREON_RAW_PAYLOAD_CAPTURE_ENABLED=false` — keeps raw payload quarantine disabled; this should be the normal state.
- Ingress controls can block `/webhooks/patreon` during incidents.
- Stop `src/workers/patreon_sync_worker.py` to pause sync jobs.
- Disable Magic Worlds S2S consumption in the companion service if api.auth needs isolation.

Do not use destructive schema rollback after live Patreon data exists.

## Prerequisites

- Additive Patreon schema, stored procedures, triggers, activity catalog, email outbox purpose, runtime routes, worker, and health metrics are deployed.
- Secret management exists for creator token material, webhook secret, S2S bearer token, HMAC peppers, proof-token pepper, and optional token encryption key.
- Redis is available for rate limits, proof/replay guards, sync locks, and worker heartbeat.
- The transactional auth email worker is available for `patreon_link_proof` delivery.
- Authenticated operators can inspect `/system/health` without exposing secrets.
- No production domains, real Patreon IDs, or real tokens are stored in docs or smoke examples.

## Server-Only Configuration

Keep values in secret/config management, not source control.

Feature flags:

```text
PATREON_LINKING_ENABLED=false
PATREON_WEBHOOKS_ENABLED=false
PATREON_SYNC_ENABLED=false
PATREON_S2S_ENTITLEMENT_ENABLED=false
PATREON_CREATOR_TOKEN_REFRESH_ENABLED=false
PATREON_RAW_PAYLOAD_CAPTURE_ENABLED=false
```

Server-only credential/config keys:

```text
PATREON_CREATOR_ACCESS_TOKEN
PATREON_CREATOR_REFRESH_TOKEN
PATREON_CLIENT_ID
PATREON_CLIENT_SECRET
PATREON_WEBHOOK_SECRET
PATREON_WEBHOOK_ID
PATREON_S2S_BEARER_TOKEN
PATREON_PROVIDER_SUB_PEPPER
PATREON_EMAIL_HASH_PEPPER
PATREON_PROOF_TOKEN_PEPPER
PATREON_ID_HMAC_SECRET
PATREON_WEBHOOK_DELIVERY_HASH_PEPPER
PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY
PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ID
```

Tier-map keys:

```text
PATREON_CAMPAIGN_TIER_MAP
PATREON_TIER_MAP_JSON
PATREON_TIER_MAP_FILE
PATREON_CAMPAIGN_IDS
```

Use `PATREON_CAMPAIGN_TIER_MAP`, `PATREON_TIER_MAP_JSON`, or `PATREON_TIER_MAP_FILE` as the production source of truth for raw campaign/tier IDs and normalized plan/tier codes. `PATREON_CAMPAIGN_IDS` is only an optional server-only allow-list for campaign discovery/sweeps; it does not replace the tier map and does not make entitlement projection ready by itself.

Retention defaults:

```text
PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS=24
PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS=90
PATREON_RAW_PAYLOAD_RETENTION_DAYS=30
```

Link, snapshot, entitlement history, unlink history, and audit/activity evidence are retained indefinitely in privacy-minimized form.

## Setup Baseline

1. Deploy code and additive schema with all Patreon feature flags disabled.
2. Confirm existing local auth, Google OAuth, sessions, refresh, and `/auth/validate` remain unaffected.
3. Configure server-only secrets by key name. Do not print values.
4. Configure tier maps using secret/config management or `PATREON_TIER_MAP_FILE`.
5. Using a valid access session, confirm `/system/health` reports Patreon as `disabled` or `not_ready`, not as an unrelated local-auth failure.
6. Seed/validate tier maps before enabling entitlement projection.
7. Enable only one behavior at a time during rollout. Use the deployment order below; do not skip directly from disabled config to public linking, webhook processing, or scheduled sync.

## Creator Token Storage and Rotation

Patreon does not provide a separate machine/service-account model. The creator registers a client in the Patreon developer portal and receives creator-owned token material for that creator account/campaign.

Storage rules:

- Store creator access/refresh token material only in server-side secret management or the optional encrypted global provider-token state.
- Never store creator tokens in `user_external_accounts`, user rows, membership rows, audit rows, activity details, browser-visible responses, or S2S DTOs.
- Never store per-user Patreon access or refresh tokens. This integration is creator-owned, not member OAuth.

Rotation/refresh checklist:

1. Prepare new creator token material in secret management.
2. If automatic refresh is enabled, verify `PATREON_CREATOR_REFRESH_TOKEN`, `PATREON_CLIENT_ID`, `PATREON_CLIENT_SECRET`, `PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY`, and `PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ID` are present by key name only.
3. Deploy/reload api.auth workers with the new secret version.
4. Check `components.patreon.creator_token.status`, `configured`, `degraded`, `expires_at`, `refreshed_at`, and `rotated_at`.
5. Run a controlled resync after token health is healthy.
6. Revoke old token material only after validation passes.

If token refresh fails, preserve last known snapshots as stale/degraded. Do not downgrade users solely because creator-token health is degraded.

## Webhook Registration

Register only the api.auth webhook receiver:

```text
POST /webhooks/patreon
```

Required posture:

- Store `PATREON_WEBHOOK_SECRET` in secret management.
- Subscribe only to allowed member/pledge events needed for entitlement: `members:create`, `members:update`, `members:delete`, `members:pledge:create`, `members:pledge:update`, `members:pledge:delete`.
- Verify `X-Patreon-Signature` with HMAC-MD5 over exact raw request bytes before JSON parsing.
- Reject invalid signatures before any mutation.
- Keep raw body excluded from unsafe audit capture.
- Treat webhooks as fast path. Scheduled/manual resync is source of truth.

Validation:

1. Send only sanitized signed fixtures or a controlled live smoke when explicitly approved.
2. Confirm valid signed webhook returns safe success and creates `patreon_webhook_received` / `act-cat-080` evidence.
3. Confirm invalid signature returns rejection and creates `patreon_webhook_rejected` / `act-cat-081` evidence without raw signature/payload leakage.
4. Confirm duplicate delivery is idempotent and creates `patreon_webhook_replay_ignored` / `act-cat-082` where applicable.

Auto-pause recovery:

1. Fix receiver health first.
2. Validate signature handling with exact raw bytes.
3. Unpause/redeliver from Patreon only after api.auth can accept valid webhooks.
4. Run source-of-truth resync after recovery.

## Tier-Map Seeding

Patreon tier mapping is campaign-scoped and supports multiple campaigns from day one. Raw campaign/tier IDs are server-only inputs. Browser-visible and S2S responses receive only normalized plan/tier codes.

Use the seeder in dry-run mode first:

```bash
PATREON_ID_HMAC_SECRET="<secret-managed-value>" \
  ./.venv/bin/python scripts/migrations/patreon_tier_map_seed.py \
  --config-json '<server-only-json>'
```

Operational rules:

- Do not paste real IDs into this runbook or tickets.
- `PATREON_ID_HMAC_SECRET` is required for stable campaign/member/tier HMACs; `PATREON_HMAC_SECRET` exists only as backward-compatible fallback and should not be the production standard.
- Validate ambiguity before enabling entitlement projection.
- Unknown active tiers must fail safe and produce `patreon_tier_map_miss` / `act-cat-087`.
- Do not expose raw Patreon campaign or tier IDs to Magic Worlds or the browser.

Fixture names such as `magic_worlds_plus`, `artisan`, `pro`, `campaign-mw-alpha`, and `tier-mw-alpha-artisan` are synthetic fixtures, not production values.

## Health Checks

Use the existing system health endpoint:

Any valid access session is sufficient; this endpoint is not admin-only.

```bash
curl -X GET "${BASE_URL}/system/health" \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "User-Agent: ops/1.0"
```

Inspect the Patreon component only for non-secret posture:

- `readiness` — feature flags, configured campaign/tier-map count, retention settings, missing config key names.
- `creator_token` — configured/degraded/expiry/refresh status without token values.
- `webhooks` — signature failure counts, retrying deliveries, paused/degraded signal.
- `snapshots` — current/stale counts and stale age.
- `tier_map` — miss count and degraded status.
- `proof_delivery` — aggregate proof email delivery status.
- `s2s` — enablement, ready status, S2S rate counters.
- `worker` — sync worker heartbeat and latest safe counters.
- `sync_queue` — pending/running/retry/failed jobs and retention status.

Disabled Patreon should not degrade unrelated local authentication health. Enabled but not-ready/degraded Patreon should be visible as a separate component.

## Resync Operations

Resync is the final correction path for entitlement. Webhooks are fast path only.

Manual S2S resync enqueue:

```text
POST /internal/users/{user_hash}/entitlements/patreon/resync
Authorization: Bearer <server-side-s2s-token>
```

ROOT admin dashboard (cookie/session, `is_root_user` gated) management surface:

```text
GET  /admin/patreon/status                      # operational health (existing)
GET  /admin/patreon/entitlements?limit&offset&status&plan_code
GET  /admin/patreon/entitlements/{user_hash}
GET  /admin/patreon/tier-map?limit&offset&active
GET  /admin/patreon/sync-jobs?limit&offset&status
GET  /admin/patreon/webhooks?limit&offset&status
POST /admin/patreon/resync                       # body {scope:'user'|'all', user_hash?, reason}
```

These power the magic-auth-dashboard Patreon management tabs (Overview, Entitlements,
Tier Map, Sync & Webhooks). They are sanitized read surfaces plus an admin-triggered
resync; `scope='user'` enqueues a per-user member resync, `scope='all'` enqueues a
single full-campaign job that the worker drains as a full sweep.

> IMPORTANT: A dashboard/S2S resync only **enqueues** a job. Jobs are processed only
> while `src/workers/patreon_sync_worker.py` is running as a separate process (it is not
> wired into the API). If the worker is stopped, queued resyncs accumulate and entitlements
> will not advance. Watch the worker heartbeat on the dashboard Overview tab
> (`GET /admin/patreon/status` → `worker`) and keep the worker running in any environment
> where sync is enabled.

Worker one-shot modes:

```bash
./.venv/bin/python -m src.workers.patreon_sync_worker --once --mode queued
./.venv/bin/python -m src.workers.patreon_sync_worker --once --mode full_campaign_sweep
./.venv/bin/python -m src.workers.patreon_sync_worker --once --mode manual_resync_queue --limit 25
./.venv/bin/python -m src.workers.patreon_sync_worker --once --mode per_member_sync --member-id-hash "<server-only-hex-hash>"
./.venv/bin/python -m src.workers.patreon_sync_worker --once --mode retention_only
```

Rules:

- Respect provider rate limits and local retry `not_before` metadata.
- Preserve last known paid snapshots as stale/degraded on provider outage, timeout, token failure, or 429.
- Fail closed for new paid grants when source-of-truth data cannot be confirmed.
- Do not log raw member IDs, campaign IDs, tier IDs, emails, tokens, payloads, hashes, hash prefixes, or fingerprints.

## Incident Response

### Creator token expired, revoked, or refresh failed

1. Disable new linking/sync if new grants cannot be confirmed safely.
2. Rotate/refresh token material in secret management.
3. Check `components.patreon.creator_token`.
4. Run controlled resync.
5. Preserve stale snapshots; do not downgrade solely due to credential failure.

### Webhook signature mismatch spike

1. Keep invalid deliveries rejected before mutation.
2. Check raw-body preservation and secret deployment by version label only.
3. Use `PATREON_WEBHOOKS_ENABLED=false` or ingress block if the spike is active.
4. After fix, validate with signed sanitized fixtures and resync.

### Webhook auto-pause

1. Repair api.auth receiver health.
2. Confirm valid signatures pass and invalid signatures fail.
3. Unpause/redeliver from Patreon.
4. Run source-of-truth resync for affected campaigns/members.

### Tier-map miss

1. Keep paid entitlement ungranted for unmapped tiers.
2. Add/validate campaign-scoped mapping.
3. Run per-member or full-campaign resync.
4. Verify only normalized plan/tier codes appear in S2S/browser-visible surfaces.

### Stale sync

1. Check worker heartbeat and sync queue.
2. Check provider token/rate-limit health.
3. Restart worker or run one-shot resync once safe.
4. Preserve stale/degraded status until source-of-truth read succeeds.

### Companion S2S failures

1. Check `PATREON_S2S_ENTITLEMENT_ENABLED` and `PATREON_S2S_BEARER_TOKEN` presence by key name only.
2. Confirm Magic Worlds is using dedicated bearer auth, not browser cookies or `/auth/validate` entitlement fields.
3. Check S2S rate counters.
4. Confirm response DTO contains only normalized allow-listed fields.

### PII or secret leak suspicion

1. Stop further capture: keep `PATREON_RAW_PAYLOAD_CAPTURE_ENABLED=false` and disable affected ingress/worker paths if needed.
2. Preserve audit evidence; do not delete history casually.
3. Rotate exposed secret material.
4. Purge raw payload quarantine within the configured max window and document only sanitized evidence.

## Retention and Purge

Required windows:

| Artifact | Retention |
| --- | --- |
| Proof requests | Purge/strip 24h after expiry |
| Webhook delivery hashes / idempotency ledger | 90d |
| Raw payload quarantine | Disabled by default; 30d max when explicitly enabled |
| Link, snapshot, entitlement, unlink history | Indefinite, privacy-minimized |

Run retention-only worker pass when needed:

```bash
./.venv/bin/python -m src.workers.patreon_sync_worker --once --mode retention_only
```

Never use retention purge to erase live link/snapshot/unlink history or audit evidence.

## Deployment Order

Run these steps in order. Do not enable broad production exposure until static no-login checks, S2S safe-field checks, webhook verification checks, sync/retention checks, and rollback rehearsal pass.

1. **Deploy disabled**: deploy api.auth code, additive schema, docs, worker artifact, and health metrics with every primary Patreon flag disabled: `PATREON_LINKING_ENABLED=false`, `PATREON_WEBHOOKS_ENABLED=false`, `PATREON_SYNC_ENABLED=false`, and `PATREON_S2S_ENTITLEMENT_ENABLED=false`.
2. **Validate disabled/not-ready health**: confirm `/system/health` reports Patreon as `disabled` or `not_ready` in the Patreon component only. Existing local auth, Google OAuth, sessions, refresh, and `/auth/validate` must remain unaffected and must not receive Patreon entitlement fields.
3. **Seed and validate tier map**: configure server-only creator credentials, HMAC peppers, S2S token material, webhook secret, and campaign/tier map inputs by key name only. Dry-run and then seed the tier map with `scripts/migrations/patreon_tier_map_seed.py`; validate ambiguity/unknown-tier behavior without printing raw campaign IDs, tier IDs, member IDs, hashes, fingerprints, tokens, or secrets.
4. **Enable S2S for no linked users**: set only `PATREON_S2S_ENTITLEMENT_ENABLED=true` in a controlled environment. Verify Magic Worlds S2S reads use the dedicated bearer credential, not browser cookies, sessions, or `/auth/validate`, and that users with no current Patreon entitlement row receive a safe free/no-Patreon normalized response.
5. **Enable test linking**: set `PATREON_LINKING_ENABLED=true` only for a controlled test account or constrained rollout cohort. Complete the email-loop proof path, confirm no local session/token/API key is issued by Patreon proof, and verify status responses expose only normalized link/entitlement fields.
6. **Register webhook while processing stays disabled**: register `POST /webhooks/patreon` with Patreon using only allowed member/pledge events. Keep `PATREON_WEBHOOKS_ENABLED=false` until signed sanitized fixtures or explicitly approved live smoke prove exact raw-body HMAC-MD5 verification and invalid-signature rejection.
7. **Enable webhooks**: set `PATREON_WEBHOOKS_ENABLED=true` only after receiver health, signature validation, idempotent replay behavior, and redacted activity/audit evidence are confirmed. Treat webhooks as a fast path; scheduled/manual resync remains the source of truth.
8. **Enable scheduled sync last**: set `PATREON_SYNC_ENABLED=true` and start `src/workers/patreon_sync_worker.py` only after creator-token health, tier-map validation, webhook behavior, S2S contract checks, rate-limit settings, and rollback drill evidence are acceptable. Confirm provider 429/outage/token failures mark snapshots stale/degraded instead of destructive downgrade.

At every step, keep Patreon entitlement/link only. Do not add Patreon login routes, do not issue local sessions from Patreon proof/webhooks/API reads, do not mutate JWTs or refresh-token state, and do not expose raw Patreon internals to Magic Worlds or browser-visible responses.

## Non-Destructive Rollback

Preferred rollback disables behavior and preserves evidence:

1. **Flip kill switches closed**: set `PATREON_LINKING_ENABLED=false`, `PATREON_WEBHOOKS_ENABLED=false`, `PATREON_SYNC_ENABLED=false`, and `PATREON_S2S_ENTITLEMENT_ENABLED=false`. Keep `PATREON_RAW_PAYLOAD_CAPTURE_ENABLED=false` unless an approved incident process explicitly requires bounded quarantine.
2. **Disable ingress/webhook intake**: block `/webhooks/patreon` at ingress and/or rotate/revoke the Patreon webhook secret. Invalid or paused deliveries must not mutate entitlement state, and received delivery/snapshot evidence remains preserved.
3. **Stop sync execution**: stop `src/workers/patreon_sync_worker.py` and any scheduler/one-shot job that can claim Patreon sync, retention, manual resync, creator-token refresh, or full-campaign sweep work.
4. **Disable companion consumption**: disable Magic Worlds S2S entitlement pulls and any companion cache refresh that depends on `GET /internal/users/{user_hash}/entitlements`; Magic Worlds should fall back to existing local membership behavior without reading Patreon entitlement from api.auth.
5. **Clear only Patreon Redis namespaces when approved**: remove Patreon proof/rate/dedupe/sync lock keys only if immediate cleanup is required in local/test or approved incident response. Never clear local auth session, refresh-token, user-session, or unrelated Redis namespaces as part of Patreon rollback.
6. **Preserve additive schema and history**: leave Patreon schema, link rows, current snapshots, entitlement history, webhook delivery history, proof rows within retention policy, unlink history, audit evidence, and activity rows intact once live data exists. Destructive schema rollback is refused unless preflight/dev checks prove no Patreon data or evidence exists.

Redis cleanup scope, when approved:

```text
patreon_link_request:*
patreon_proof_request:*
patreon_proof_token:*
patreon_proof_consume:*
patreon_unlink:*
patreon_link_status:*
patreon_s2s_entitlement:*
patreon_webhook_delivery:*
patreon_webhook_signature_failure:*
patreon_sync_enqueue:*
patreon_sync_job:*
patreon_sync_lock:*
patreon_creator_token_refresh:*
patreon_rate:*
```

Do not clear unrelated `session:*`, `refresh_family:*`, `refresh_token:*`, `user_sessions:*`, or local auth namespaces as part of Patreon rollback.

Destructive schema rollback is allowed only in preflight/dev environments where checks prove no Patreon links, snapshots, webhook deliveries, proof rows, unlink history, audit records, or activity records exist.

Destructive rollback refusal scope must include live/history evidence in
`user_external_accounts` where provider is Patreon, `patreon_link_proofs`,
`patreon_memberships`, `patreon_member_snapshots`,
`patreon_member_snapshot_history`, `patreon_entitlements_current`,
`patreon_entitlement_history`, `patreon_webhook_deliveries`,
`patreon_sync_jobs`, `patreon_raw_payload_quarantine`, and `activity_logs`
where activity type starts with `patreon_`. If any row exists, refuse the
destructive path and use the non-destructive disable/archive rollback above.

## Evidence Checklist

- [ ] Feature flags captured by key name only.
- [ ] `/system/health` Patreon component captured without secrets.
- [ ] Activity evidence captured from `act-cat-075` through `act-cat-090` as counts/statuses only.
- [ ] Tier-map validation captured without raw IDs.
- [ ] Webhook signature validation captured without signatures or payloads.
- [ ] S2S response reviewed for normalized allow-listed fields only.
- [ ] Retention windows preserved.
- [ ] Rollback, if used, was non-destructive.
