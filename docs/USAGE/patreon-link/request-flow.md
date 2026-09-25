# Patreon link request flow

What each Patreon request and worker pass does, in order. Fields, response bodies and
status codes are in [reference.md](reference.md); the design behind the steps is in
[architecture.md](architecture.md).

## Link request

`POST /auth/patreon/link/request`, from the signed-in user.

1. The access session is validated; there must be a local user (`401` otherwise).
2. Recent authentication is required: a sign-in or an OAuth reauth of this session
   within `OAUTH_RECENT_REAUTH_SECONDS`. Otherwise `401` `AUTH_1008`.
3. The link-request bucket is spent (user, IP, hint): `429` with the neutral body.
4. The proof-send bucket is spent (user, IP, recipient), on every request and before
   Patreon is contacted: `429` with the neutral body.
5. The Patreon configuration is loaded. Linking must be on and ready (creator token, the
   four peppers and secrets, at least one configured campaign) and
   `explicit_user_intent` must be `true`; otherwise the neutral `202` is returned.
6. Non-consumer accounts get the neutral `202`.
7. Without a `patreon_email_hint`, no member is looked up and the neutral `202` is
   returned. Otherwise every configured campaign is paged through the creator API and the
   member whose Patreon e-mail equals the hint is selected.
8. No member, or a member without an e-mail (hidden or empty): neutral `202`, recorded as
   `patreon_link_rejected` (`member_not_available`, `patreon_email_hidden_or_null`).
9. The member must belong to a configured campaign and carry user and member ids. The
   tier-map mirror is refreshed, then a proof is created in `patreon_link_proofs` and its
   e-mail queued in `email_messages` (template `patreon_link_proof`) to the member's
   Patreon e-mail. The link in the e-mail is
   `<public base URL>/auth/patreon/link/confirm?token=<lookup_id>.<secret>`.
10. `patreon_link_proof_requested` is recorded and the neutral `202` is returned.

Any provider, database or e-mail failure also ends in the neutral `202`. The proof is
delivered by the transactional e-mail worker, not by this request.

## Link confirm

`POST /auth/patreon/link/confirm`, from the same signed-in user, with the token from the
e-mail. The e-mailed URL points at a `POST`-only route, so the front end reads `token`
from it and posts it.

1. Session and recent authentication as for the request: `401`, `401` `AUTH_1008`.
2. The proof-consume bucket is spent (user, IP, lookup id; never the secret): `429`.
3. Linking must be on with a proof pepper, and the token must parse into lookup id and
   secret; otherwise the neutral `202` (`link_status: pending`).
4. The proof is consumed in the database, bound to this user: it must be pending,
   unexpired and match the secret. A wrong secret counts an attempt; 8 wrong attempts
   block the proof. Anything but a fresh consumption returns the neutral `202`.
5. `patreon_link_proof_consumed` is recorded.
6. The conflict check refuses, with the neutral `202`, when the Patreon account is
   linked to another user (`provider_identity_unavailable`) or this user already has a
   Patreon link (`active_patreon_link_exists`).
7. The link is created (`user_external_accounts`, membership row).
8. The member is read again from Patreon and classified; the snapshot, current
   entitlement and history are stored. If that fails, a `pending` entitlement is stored
   and a resync of this user is queued. The link is never undone at this point.
9. `patreon_linked` is recorded and `200` is returned with `link_status: linked` and the
   entitlement.

Linking never activates or changes a local e-mail address and never issues credentials.

## Link status

`GET /auth/patreon/link/status`, from the signed-in user.

1. The access session is validated (no recent authentication needed).
2. The status bucket is spent (user, IP): `429` with `link_status: none` and the free
   entitlement.
3. The caller's current entitlement row is read and normalized. `stale` is computed
   here from `stale_after`. A read failure answers `link_status: none` with the free
   entitlement, still `200`.

There is no user selector: only the caller's own state is readable.

## Unlink

`DELETE /auth/patreon/link`, from the signed-in user.

1. Session and recent authentication: `401`, `401` `AUTH_1008`.
2. The unlink bucket is spent (user, IP): `429`.
3. `sp_patreon_unlink_account` marks the external account and membership `unlinked`,
   sets the current entitlement to `free` with `link_status: unlinked`, and appends a
   history row.
4. `patreon_unlinked` is recorded and `200` is returned. If nothing was linked or the
   procedure refused, the answer is the neutral `202` with `link_status: none`.

Sessions, refresh tokens, cookies and API keys are untouched.

## Webhook

`POST /webhooks/patreon`, from Patreon.

1. The raw body is read before anything else.
2. Invalid configuration, webhooks off or no secret: `503`.
3. `X-Patreon-Signature` must be the HMAC-MD5 of the exact raw bytes with
   `PATREON_WEBHOOK_SECRET`, compared in constant time. On failure the signature-failure
   bucket for the source IP is spent (`429` once exhausted, else `401`) and
   `patreon_webhook_rejected` is recorded. Nothing reaches the ledger.
4. An event outside `PATREON_ALLOWED_WEBHOOK_EVENTS` is recorded in the ledger as
   `ignored` and answered `200`.
5. The body is parsed; member, campaign and user ids are hashed; the delivery hash is
   computed over event, member, campaign and body digest.
6. The delivery is recorded as `received`. If it cannot be recorded: `500` (Patreon
   redelivers). A duplicate is answered `200` without reprocessing, unless the earlier
   attempt `failed` or has been `received`/`processing` for over 10 minutes.
7. A body without a member document queues a resync where possible and is answered
   `200`.
8. The Patreon user must be linked to a local account; otherwise the delivery is
   `ignored`.
9. A complete member document from a create or update event is classified and stored
   directly (snapshot, entitlement, history), downgrades included, and
   `patreon_entitlement_changed` or `patreon_tier_map_miss` is recorded. A partial
   document, a `*:delete` event or an unmapped tier queues a `webhook_resync` job
   instead.
10. The ledger row is marked `processed` or `ignored` and `200` is returned. If
    processing throws, a resync is queued, the row is marked `failed`, and the answer is
    `200` when the resync was queued, `500` when it was not.

## Worker pass

`src/workers/patreon_sync_worker.py` (started by `scripts/run_patreon_worker.sh`) loops
every `PATREON_SYNC_WORKER_POLL_SECONDS`. With `PATREON_SYNC_ENABLED` off it only runs
maintenance.

1. The tier-map mirror is refreshed if the configuration changed.
2. Up to `PATREON_SYNC_WORKER_BATCH_SIZE` due jobs are claimed with a lease of
   `PATREON_SYNC_JOB_LEASE_SECONDS`, lowest `priority` number first (forced resyncs use
   `1`, others `5`), and processed:
   - `full_campaign` — page through every configured campaign (or the one named);
   - `user_member` — scan configured campaigns for the member linked to the user;
   - `webhook_resync` — re-read one member by its hash;
   - `campaign_member`, `retention`, `token_refresh` are supported but nothing queues
     them.
3. If no job was claimed and a sweep is due, a full sweep of every configured campaign
   runs inline. The first sweep runs at start-up; the next is due
   `PATREON_SYNC_INTERVAL_SECONDS` plus up to `PATREON_SYNC_JITTER_SECONDS` later.
4. Every member read is classified and stored like a webhook update. After a complete
   sweep with no member failures, linked memberships Patreon no longer returned become
   `former`/free with the link kept.
5. Failures: a Patreon `429` retries after Patreon's own retry hint; other failures
   retry after `PATREON_SYNC_BACKOFF_SECONDS[attempt]` plus jitter; a `401` marks the
   stored creator token revoked and, with refresh on, refreshes it at once. After 8
   attempts the job fails. Nothing is written on failure, so entitlements keep their last
   value and age into `stale`.
6. Maintenance: with token refresh on, the creator token is checked hourly and refreshed
   `PATREON_CREATOR_TOKEN_REFRESH_MARGIN_SECONDS` before it expires (the first check after
   start-up refreshes once to learn the expiry); the retention purge runs at start-up and
   every 24 hours.

Enqueueing is idempotent: a request identical to a queued job returns that job
(`deduplicated`) and can pull it forward; a request that arrives while the job runs makes
it run once more after it completes successfully.

## Manual resync

`POST /internal/users/{user_hash}/entitlements/patreon/resync` (S2S) and
`POST /admin/patreon/resync` (root dashboard) both queue a job for the worker; neither
reads Patreon itself.

S2S, in order: bearer check (`401`), S2S bucket (`429` generic), sync-enqueue bucket
(`429` `status: rate_limited`), sync off (`202` `disabled`), unknown or inactive user
(`202` `degraded`), then a `user_member` job is queued (`202` `queued`) and
`patreon_sync_started` is recorded.

Dashboard, in order: root check (`403`), sync off or invalid configuration (`200`
`disabled`), `user_hash` required for `scope: user` (`400`), sync-enqueue bucket with its
own counter (`429` `INT_7005`), unknown user (`404`), no active membership (`200`
`not_linked`), then a `user_member` job or, for `scope: all`, one `full_campaign` job is
queued (`200` `queued`).

## S2S entitlement read

`GET /internal/users/{user_hash}/entitlements`, from the companion service.

1. The Patreon configuration is loaded; the S2S switch must be on, a bearer configured,
   and the presented bearer must match in constant time. Otherwise `401`. Cookies and
   user tokens are never considered.
2. The S2S bucket is spent (user hash, calling client, IP): `429`.
3. The current entitlement row for `user_hash` is read and normalized through the
   allow-listed DTO; `stale` is computed from `stale_after`.
4. No row, or an unknown or inactive user: the free projection, `200`. A read error:
   `404`.

The read never issues sessions and never changes local authentication state.

## Retention

The worker's purge (`sp_patreon_retention_purge`) deletes expired proofs, old webhook
ledger rows and finished sync jobs, and blanks expired quarantined payloads. Links,
memberships, snapshots and entitlement history are never purged. Windows are in
[Retention windows](reference.md#retention-windows).
