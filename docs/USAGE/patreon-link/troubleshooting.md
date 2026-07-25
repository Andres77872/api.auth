# Patreon Link Troubleshooting

Troubleshooting for Patreon account linking, email-loop proof delivery, webhook ingestion, resync, and the Magic Worlds server-to-server entitlement read.

## Safety Rules

- Patreon is **entitlement/link only**. It is not a local login provider, does not issue local sessions, and must not change JWT, refresh-token, cookie, API-key, or `/auth/validate` behavior.
- Patreon is disabled by default. Check the feature/kill switches before assuming a failure is an outage: `PATREON_LINKING_ENABLED`, `PATREON_WEBHOOKS_ENABLED`, `PATREON_SYNC_ENABLED`, and `PATREON_S2S_ENTITLEMENT_ENABLED`.
- Never paste raw Patreon IDs, campaign IDs, tier IDs, member emails, signatures, raw payloads, creator tokens, refresh tokens, proof tokens, S2S bearer tokens, HMAC hashes, hash prefixes, fingerprints, or audit rows into tickets, docs, chat, logs, or screenshots.
- Use safe evidence only: correlation IDs, activity codes, aggregate counts, safe status values, non-secret health output, and redacted operator notes.
- Retention windows are fixed by the SDD: proof requests are purged or stripped **24h after expiry**; webhook delivery hashes are retained **90d**; raw payload quarantine is disabled by default and **30d max** when explicitly enabled; link, snapshot, entitlement, unlink, and audit history are retained **indefinitely**.

## Fast Triage Table

| Symptom | Likely Cause | Safe First Action |
| --- | --- | --- |
| User cannot complete link because Patreon email is hidden/null | Patreon did not return a member email, so v1 email-loop proof cannot be delivered | Keep link blocked/pending-safe; do not request a replacement email; tell the user linking cannot be completed automatically in v1. |
| Proof email not received | Email outbox/provider issue, suppression, proof rate limit, disabled linking, or provider discovery failure | Check proof-delivery health and `patreon_link_proof_requested` evidence without exposing recipient email or proof token. |
| Proof token expired/invalid/replayed | Proof TTL elapsed, token already consumed, malformed token, wrong request, or consume rate limit | Return generic posture; create a new request only after rate limits allow it. Never reveal which condition occurred. |
| Creator token expired/revoked | Patreon creator token refresh failed, token was invalidated, or refresh config is missing | Mark Patreon degraded, preserve last known snapshots as stale, and rotate/refresh server-only credentials. |
| Webhook signature mismatch | Wrong webhook secret, body changed before HMAC, missing header, proxy/middleware mutation, or non-Patreon request | Reject before mutation; check exact raw-body handling and secret deployment by name only. |
| Patreon webhook auto-paused | Repeated non-2xx/timeouts caused Patreon retries to exhaust and pause the webhook | Fix receiver health, verify signatures, then unpause/redeliver from Patreon; run resync because webhooks are a fast path only. |
| Tier-map miss | Patreon returned an active tier with no active campaign-scoped internal mapping | Do not grant paid entitlement; add/validate mapping, then resync. |
| Stale sync | Scheduled worker down, provider outage/rate limit, token failure, webhook partial payload, or retry queue backlog | Preserve current snapshot as stale/degraded; repair worker/API health and resync. |
| Provider rate-limit backoff | Patreon API 429 or edge block; local API/token/client rate limits exceeded | Honor `retry_after_seconds` when present; back off with jitter; do not downgrade users solely because of rate limits. |
| Magic Worlds S2S entitlement read fails | S2S disabled/not-ready, missing bearer, wrong `user_hash`, rate limit, stale snapshot, or api.auth outage | Check `GET /internal/users/{user_hash}/entitlements` health from api.auth side; do not use browser cookies or local sessions as S2S authority. |

## Hidden or Null Patreon Email

Expected behavior:

1. The link may remain pending or blocked-safe.
2. No active Patreon link is created.
3. No Patreon-backed entitlement is granted.
4. No proof token is sent to a user-supplied, local, replacement, or guessed email.

Operator checks:

- Confirm `patreon_link_rejected` / `act-cat-078` or equivalent blocked-safe activity exists with redacted reason metadata.
- Check only safe link status (`pending`, `proof_required`, `blocked`, or `none`) and safe entitlement status (`pending`/`free`) in user-visible or S2S surfaces.
- If product/support needs manual review later, open a new spec. Do not improvise an email-equality or OAuth fallback.

Do not do this:

- Do not ask the user to type their Patreon email and send proof there.
- Do not activate the local email address from Patreon data.
- Do not grant entitlement because the local email matches a Patreon email hint.
- Do not introduce Patreon login/session behavior to solve proof delivery.

## Proof Delivery Failure

Common causes:

- `PATREON_LINKING_ENABLED=false` or readiness is `disabled` / `not_ready`.
- Creator API discovery failed before a proof request could be created.
- Email outbox worker is down or `EMAIL_DELIVERY_ENABLED=false`.
- Provider delivery failed, bounced, complained, or recipient is suppressed.
- Proof request rate limit was reached: `PATREON_PROOF_REQUEST_RATE_LIMIT` / `PATREON_PROOF_REQUEST_RATE_WINDOW_SECONDS`.
- Proof delivery payload failed template/render validation.

Safe checks:

1. With a valid access session, check `/system/health` and inspect only `components.patreon.proof_delivery` and email outbox aggregate status.
2. Confirm `email_messages.purpose='patreon_link_proof'` by aggregate counts or message IDs only; do not expose recipient plaintext or render payload.
3. Check `patreon_link_proof_requested` (`act-cat-075`) and `patreon_sync_failed` (`act-cat-085`) counts.
4. Check worker status for `src/workers/email_worker.py`; proof delivery reuses the transactional auth email worker.

Recovery:

- Fix email worker/provider readiness first.
- Allow rate limits and cooldowns to expire naturally.
- Ask the user to retry link request only after readiness is healthy.
- If proof rows are expired, create a new proof request; do not redrive an expired proof token.

## Token Expired or Invalid

There are two token classes. Treat them differently.

### Email-loop proof token

Expected behavior:

- Malformed, unknown, expired, already-consumed, wrong-purpose, or wrong-request proof tokens return a generic non-enumerating response.
- The system must not reveal which condition occurred.
- No link, entitlement, local email activation, session, or token issuance occurs.

Safe response:

1. Check rate-limit posture for `proof_consume`.
2. Let the user start a new link request only after rate limits allow it.
3. Keep evidence redacted: lookup IDs, proof token hashes, token fingerprints, raw secrets, and emails are server-only.

### Patreon creator token

Symptoms:

- Creator API returns unauthorized/degraded status.
- Sync jobs retry or fail with a non-secret token-invalid reason.
- `components.patreon.creator_token.status` is `expired`, `revoked`, `refresh_failed`, or `unknown`.

Recovery:

1. Keep `PATREON_SYNC_ENABLED` or `PATREON_LINKING_ENABLED` disabled if new grants cannot be safely confirmed.
2. Refresh/rotate the creator token using secret management.
3. If auto-refresh is enabled, confirm `PATREON_CREATOR_REFRESH_TOKEN`, `PATREON_CLIENT_ID`, and `PATREON_CLIENT_SECRET` are present by key name only.
4. Confirm refreshed token state is encrypted server-side and never stored in per-user rows.
5. Run a controlled resync after health returns.

Do not downgrade paid users solely because the creator token failed. Existing snapshots must become stale/degraded until source-of-truth sync succeeds.

## Webhook Signature Mismatch

Patreon sends `X-Patreon-Signature` as an HMAC-MD5 hex digest over the **exact raw request body** using the webhook secret. Any body normalization breaks verification.

Common causes:

- Wrong `PATREON_WEBHOOK_SECRET` deployed.
- Secret rotated in Patreon but not in api.auth, or vice versa.
- Proxy/middleware parsed and reserialized JSON before verification.
- Whitespace, Unicode, NBSP, key ordering, or newline changed before HMAC.
- Request is not from Patreon.
- Header is missing or malformed.

Safe checks:

1. Confirm `/webhooks/patreon` is excluded from unsafe raw-body audit capture.
2. Confirm the route reads `await request.body()` before JSON parsing.
3. Check `patreon_webhook_rejected` / `act-cat-081` aggregate counts and signature-failure health, not raw signatures.
4. Compare deployed secret versions by key/version label only. Never print the secret.
5. Use sanitized fixture bodies for local verification; do not paste live webhook payloads.

Recovery:

- Fix the secret or raw-body path.
- Keep webhook processing disabled if mismatch rate is high.
- Run manual/scheduled resync after receiver health is restored because missed webhooks are not the source of truth.

## Webhook Auto-Pause

Patreon retries failed deliveries approximately after `30s`, `5m`, `15m`, `1h`, `3h`, `1d`, and `1w`, then requires manual retry. Repeated failures can pause the webhook (`paused=true`) in Patreon.

Symptoms:

- No recent `patreon_webhook_received` / `act-cat-080` events.
- `components.patreon.webhooks.retrying_deliveries` or `paused`/degraded signal is non-zero.
- Patreon developer portal shows the webhook paused or consecutive failures.

Recovery:

1. Fix api.auth receiver health first: route online, secret correct, raw body preserved, DB reachable.
2. Keep `PATREON_WEBHOOKS_ENABLED=false` or ingress blocked until verification passes if failures are still active.
3. Unpause/redeliver from Patreon only after the receiver returns safe 2xx for valid signed payloads.
4. Run source-of-truth resync. Webhooks are fast path, scheduled/manual resync is final authority.

Do not delete webhook delivery history to make the dashboard look clean. Delivery hashes retain for 90 days by policy.

## Tier-Map Miss

Expected behavior:

- Unknown active Patreon tiers do **not** grant paid entitlement.
- The system records a non-secret tier-map miss activity (`act-cat-087`).
- Current entitlement may remain free, pending, or stale depending on prior snapshot and source completeness.

Safe checks:

1. Inspect `components.patreon.tier_map.misses_24h`.
2. Check `patreon_tier_map_miss` activity counts.
3. Validate that the tier map is campaign-scoped and unambiguous.
4. Use server-only tooling for raw campaign/tier IDs; do not expose those IDs to browser clients or tickets.

Recovery:

1. Add or correct the internal mapping for the configured campaign/tier.
2. Validate ambiguity and priority ordering before enabling projection.
3. Run per-member or campaign resync.
4. Confirm S2S response contains only normalized `plan_code`, `tier_code`, status, link status, and freshness fields.

## Stale Sync

Symptoms:

- Safe status shows `stale` or degraded.
- `components.patreon.snapshots.stale_snapshot_count` or `patreon_max_stale_snapshot_age_seconds` is non-zero.
- Sync queue has retry/failed jobs.
- Worker heartbeat is stale or unknown.

Common causes:

- `PATREON_SYNC_ENABLED=false`.
- `src/workers/patreon_sync_worker.py` is not running.
- Patreon API outage, timeout, token failure, or 429 backoff.
- Webhook was partial/out-of-order and queued resync.
- Tier map not ready.

Recovery:

1. Check readiness and worker heartbeat.
2. Restart or run the sync worker only after config is ready.
3. Respect queued job `not_before` / retry metadata.
4. Run manual resync for the affected user/member if urgent.
5. Do not downgrade active users solely because a sync is stale; preserve last known snapshot as stale/degraded.

## Rate-Limit Backoff

Patreon provider limits are documented as `100` requests per `2s` per client and `100` requests per `60s` per access token. Edge rate limiting may block after many bad 4xx responses in a 10-minute window. Provider 429 responses may include `retry_after_seconds`; rate-limit fields are optional, so local policy must remain conservative.

Local knobs:

- Link request: `PATREON_LINK_REQUEST_RATE_LIMIT` / `PATREON_LINK_REQUEST_RATE_WINDOW_SECONDS`.
- Proof request: `PATREON_PROOF_REQUEST_RATE_LIMIT` / `PATREON_PROOF_REQUEST_RATE_WINDOW_SECONDS`.
- Proof consume: `PATREON_PROOF_CONSUME_RATE_LIMIT` / `PATREON_PROOF_CONSUME_RATE_WINDOW_SECONDS`.
- S2S reads: `PATREON_S2S_RATE_LIMIT` / `PATREON_S2S_RATE_WINDOW_SECONDS`.
- Sync enqueue: `PATREON_SYNC_ENQUEUE_RATE_LIMIT` / `PATREON_SYNC_ENQUEUE_RATE_WINDOW_SECONDS`.
- Provider client/token/edge controls: `PATREON_API_CLIENT_RATE_LIMIT`, `PATREON_API_ACCESS_TOKEN_RATE_LIMIT`, `PATREON_API_EDGE_4XX_RATE_LIMIT`, and their window settings.

Recovery:

1. Honor provider `retry_after_seconds` if present.
2. Keep sync jobs in retry/degraded state with jittered backoff.
3. Preserve existing snapshots as stale instead of revoked.
4. Reduce full-campaign sweeps, page counts, or manual resync volume until the window clears.
5. Fix repeated 401s quickly; expired/invalid tokens can contribute to edge blocking.

## Companion S2S Failures

Magic Worlds is a companion dependency. api.auth owns the link, proof, webhook, sync, snapshot, and entitlement classification. Magic Worlds reads normalized entitlement from api.auth; it does not receive raw Patreon internals from this repo.

Contract:

- `GET /internal/users/{user_hash}/entitlements`
- `POST /internal/users/{user_hash}/entitlements/patreon/resync`
- Dedicated S2S bearer only.
- Browser cookies, user sessions, JWTs, and `/auth/validate` are not authority for this endpoint.

Common failures:

- `PATREON_S2S_ENTITLEMENT_ENABLED=false`.
- `PATREON_S2S_BEARER_TOKEN` missing/rotated in only one service.
- Companion sends browser cookies instead of dedicated bearer.
- S2S read is rate limited.
- An authorized `user_hash` has no current Patreon row and returns a safe free/no-Patreon projection.
- Unauthorized, degraded, or rate-limited S2S reads return a generic denial/no-entitlement posture.
- Snapshot is stale/degraded because sync is unhealthy.

Safe checks:

1. Check `components.patreon.s2s.status`, `ready`, and rate counters.
2. Confirm bearer secret presence by version/key name only in both services.
3. Confirm route is called server-to-server with no browser cookie authority.
4. Inspect only safe S2S DTO fields: `external_source`, normalized `status`, `plan_code`, `tier_code`, `link_status`, renewal/grace timestamps, `last_synced_at`, `stale_after`, and `contract_version`.

Do not add Patreon fields to `/auth/validate` as a shortcut. That is a contract violation.

## Evidence Checklist

Use this checklist for incidents:

- [ ] Feature flags / kill switches checked.
- [ ] `/system/health` Patreon component captured without secrets.
- [ ] Activity counts captured for relevant `act-cat-075` through `act-cat-090` codes.
- [ ] No raw secrets, payloads, provider IDs, emails, hashes, hash prefixes, fingerprints, or audit rows pasted into the incident.
- [ ] Retention windows preserved: proof `24h after expiry`, webhook hashes `90d`, raw payload quarantine `30d max`, link/snapshot/unlink history `indefinite`.
- [ ] If rollback is needed, use non-destructive kill switches and ingress/worker controls; do not drop Patreon schema/history.
