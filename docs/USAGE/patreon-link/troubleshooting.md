# Patreon link troubleshooting

Symptom, cause and fix. Start from the health data: `GET /system/health` (valid access
session required) under `components.patreon`, or the same groups from
`GET /admin/patreon/status` (root). Then read the activity log for `act-cat-075` to
`act-cat-090` and the `reason` recorded with them.

Never paste raw Patreon ids, member e-mails, signatures, payloads, creator, proof or S2S
tokens, HMACs, fingerprints or audit rows into tickets. Use correlation ids, activity
codes, counts and the health fields below.

## Health fields

| Field | Meaning |
| --- | --- |
| `readiness.status` | `disabled`, `not_ready`, `partially_disabled` or `ready`; `readiness.missing` lists missing settings by name. |
| `creator_token.status` | From the stored token when refresh is on (`active`, `refresh_failed`, `revoked`, `expired`); otherwise `configured`, `not_ready` or `disabled`. `unknown` when unreadable. |
| `webhooks.paused`, `webhooks.status: degraded` | Signature failures in the last `PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_WINDOW_SECONDS` reached `PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_LIMIT`. This is not Patreon's own webhook pause. |
| `webhooks.retrying_deliveries` | Deliveries marked `failed` within the same window. |
| `snapshots.stale_snapshot_count`, `snapshots.max_stale_age_seconds` | Entitlements past `stale_after`. |
| `tier_map.misses_24h` | Entitlement history rows with reason `tier_map_miss` in the last 24 hours. |
| `proof_delivery` | `in_flight`, `delivered_24h`, `failed_24h`, `oldest_in_flight_age_seconds` of proof e-mails. |
| `s2s.status`, `s2s.enabled`, `s2s.ready` | Whether the S2S routes can answer. |
| `worker.status`, `sync_queue.status` | Worker `healthy`, `stale`, `disabled` or `unknown`; queue `healthy`, `retrying` or `degraded`. |

## Linking

| Symptom | Cause | Fix |
| --- | --- | --- |
| Every link request answers `202` but no proof e-mail arrives | Linking off or not ready (creator token, peppers, `PATREON_ID_HMAC_SECRET`, no configured campaign); `explicit_user_intent` not `true`; no `patreon_email_hint`; the hint is not the member's Patreon e-mail; the member is in no configured campaign; non-consumer account | Check `readiness`; read the `patreon_link_rejected` reason (`explicit_intent_or_feature_not_ready`, `member_not_available`, `non_consumer_account`, `member_context_incomplete`). Ask the user for the e-mail of their Patreon account. |
| `patreon_link_rejected` with `patreon_email_hidden_or_null` | Patreon returns no e-mail for the member | Linking cannot complete. Do not offer another address or a login fallback. |
| `patreon_link_proof_requested` recorded but the e-mail never arrives | The transactional e-mail worker is down, e-mail delivery is off, or the provider rejected the message | Check `proof_delivery.failed_24h` and the e-mail worker (`src/workers/email_worker.py`). The proof expires after `PATREON_PROOF_TOKEN_TTL_SECONDS`; request a new one after fixing delivery. |
| Link request or confirm `429` | Link-request, proof-send or proof-consume bucket exhausted for the user, IP, hint or proof | Wait `Retry-After`. The proof-send bucket (`3` per hour) is spent on every request, matched or not. |
| Confirm `401` `AUTH_1008` | The recent-authentication window (`OAUTH_RECENT_REAUTH_SECONDS`, default `300`) passed since sign-in | Sign in again or run an OAuth reauth, then post the same token while it is valid. |
| Confirm `202` `link_status: pending` | The proof is expired, already used, blocked after 8 wrong secrets, or was requested by another user; linking is off; the Patreon account is linked to someone else (`provider_identity_unavailable`); the user already has a link (`active_patreon_link_exists`) | Read the `patreon_link_rejected` reason. Request a new proof, or unlink the existing link first. |
| Opening the e-mailed link returns `405` | The link is `<public base URL>/auth/patreon/link/confirm?token=...`, and the public base URL resolved to `api.auth`, whose confirm route is `POST`-only | Point the e-mail base URL at the front end (`AUTH_EMAIL_PUBLIC_BASE_URL`, or the BFF's `X-Public-Base-Url`); the front end serves that path, reads `token` and posts it to `POST /auth/patreon/link/confirm`. |
| Linked but the entitlement stays `pending` | The member read after linking failed and a resync was queued, or the member's tier is unmapped | Make sure the worker runs with `PATREON_SYNC_ENABLED=true`; check `tier_map.misses_24h`. |
| Unlink `202` with `link_status: none` | Nothing was linked | Nothing to do. |

## Webhooks

| Symptom | Cause | Fix |
| --- | --- | --- |
| `503` to every delivery | `PATREON_WEBHOOKS_ENABLED` off, no `PATREON_WEBHOOK_SECRET`, or invalid Patreon configuration | Fix configuration; `readiness.missing` names it. An invalid tier map disables every Patreon surface. |
| `401` to deliveries, `patreon_webhook_rejected` | Wrong or rotated secret, a proxy re-serialized the JSON body, or the request is not from Patreon | The HMAC-MD5 covers the exact raw bytes: forward the body untouched. Compare secret versions by name, never by value. |
| `429` to deliveries | More than `PATREON_WEBHOOK_SIGNATURE_FAILURE_RATE_LIMIT` signature failures from one IP in the window | Fix the signature problem; the counter expires with the window. |
| Patreon shows the webhook paused | Repeated non-`2xx` answers (usually `401`, `500` or `503`) | Fix the receiver, re-enable the webhook in Patreon, then queue a full resync (`POST /admin/patreon/resync` with `scope: all`), since missed deliveries are not replayed. |
| `200` but the entitlement did not change | Duplicate delivery; event not allowed; Patreon user linked to nobody; partial document, delete event or unmapped tier (a resync was queued instead) | Check `GET /admin/patreon/webhooks` for the delivery status and `GET /admin/patreon/sync-jobs` for the queued job; the worker must be running. |
| `500` to deliveries | The ledger could not be written, or processing failed and no resync could be queued (database or Redis trouble) | Fix the database; Patreon redelivers and the ledger lets the delivery be processed again. |

## Sync and staleness

| Symptom | Cause | Fix |
| --- | --- | --- |
| Entitlements read `stale` | No successful sync of the member within `PATREON_SYNC_STALE_AFTER_SECONDS` | Check the worker is running (`scripts/run_patreon_worker.sh`) with `PATREON_SYNC_ENABLED=true`, and `sync_queue.status`. Stale entitlements keep their last plan; they are never downgraded by an outage. |
| Resync requests answer `disabled` | `PATREON_SYNC_ENABLED` off, or invalid configuration | Enable sync; fix configuration. |
| Resync queued but nothing happens | The worker is not running, or the job is backing off | `GET /admin/patreon/sync-jobs` shows `status`, `attempts`, `not_before` and `has_error`. |
| Jobs fail after 8 attempts | Persistent provider error (creator token, outage) | Fix the cause and queue a new resync. The attempt limit is fixed at 8 regardless of `PATREON_SYNC_MAX_ATTEMPTS`. |
| `creator_token.status` `revoked` or `refresh_failed` | Patreon answered `401`, or the refresh failed | With refresh on, check `PATREON_CREATOR_REFRESH_TOKEN`, `PATREON_CLIENT_ID`, `PATREON_CLIENT_SECRET` and the encryption key. Otherwise rotate `PATREON_CREATOR_ACCESS_TOKEN` and restart. |
| A full sweep never finishes | `PATREON_API_MAX_PAGES_PER_SYNC` is lower than the campaign's page count: hitting the cap fails the sweep | Raise the cap or set `0`. |
| Members who left still read `active` | No complete sweep since they left: reconciliation runs only after a full sweep with no member failures | Fix sweep failures; queue `scope: all`. |
| `tier_map.misses_24h` above zero | Active members hold tiers missing from the tier map | Add the mappings, restart the API and the worker, and queue a resync. |
| Sync activity (`act-cat-084`, `-086`, `-087`, `-090`) is missing from the activity log | The worker is not running, has not completed a sweep or retention pass yet, or the activity-log write failed (it is best effort and never fails the sync) | Check `worker.status` and the worker logs; the sync-job ledger and entitlement history remain authoritative. |
| `patreon_token_revoked` (`act-cat-089`) in the activity log | Patreon answered `401` to the creator token during sync | See the `creator_token.status` row above; a successful refresh records `patreon_token_refreshed` (`act-cat-088`). |

## Server-to-server

| Symptom | Cause | Fix |
| --- | --- | --- |
| `401` on `/internal/users/...` | `PATREON_S2S_ENTITLEMENT_ENABLED` off, `PATREON_S2S_BEARER_TOKEN` unset or different between services, the caller sent cookies or a user token instead of the bearer, or invalid configuration | Send `Authorization: Bearer <PATREON_S2S_BEARER_TOKEN>`; compare token versions by name. |
| `429` generic body | More than `PATREON_S2S_RATE_LIMIT` calls per window for one user hash, client and IP | Cache reads in the companion using `stale_after`; honor `Retry-After`. |
| `200` free projection for a linked user | Wrong `user_hash` (unknown users also get the free projection), or the entitlement row was never written | Check the hash; check `GET /admin/patreon/entitlements/{user_hash}`. |
| `404` generic body | The entitlement could not be read (database error) | Check database health. |
| Resync `202` `status: degraded` | Unknown or inactive `user_hash`, or the job could not be queued | Check the hash and the database. |

## Admin dashboard

| Symptom | Cause | Fix |
| --- | --- | --- |
| `403` `AUTHZ_2001` | The caller is not a root user | Use a root account. |
| Resync `429` `INT_7005` | Sync-enqueue budget exhausted for this user (or `all`) | Wait the `Retry-After` seconds; the window is `PATREON_SYNC_ENQUEUE_RATE_WINDOW_SECONDS` (default `300`). |
| Resync `not_linked` | The user has no active Patreon membership | Nothing to resync. |

## Related

- [Patreon runbook](../../RUNBOOKS/patreon-link.md) — incident procedures, token rotation,
  webhook registration, rollback.
- [reference.md](reference.md) — settings, bodies and status codes.
