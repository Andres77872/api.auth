# Patreon Link Reference

Reference for the Patreon account-link and entitlement integration in `api.auth`.

Patreon is **entitlement/link only**. It is not local authentication authority and must not issue local sessions, JWTs, refresh tokens, cookies, API keys, or mutate `/auth/validate`.

## Configuration Reference

All Patreon behavior is disabled by default. Enable only the narrowly required switches after schema, redaction, tier-map, webhook, S2S, sync, retention, and runbook checks pass.

### Kill switches / feature flags

| Env var | Default | Purpose |
| --- | --- | --- |
| `PATREON_LINKING_ENABLED` | `false` | Enables authenticated user link request/confirm/status/unlink behavior. |
| `PATREON_WEBHOOKS_ENABLED` | `false` | Enables verified processing of `POST /webhooks/patreon`. |
| `PATREON_SYNC_ENABLED` | `false` | Enables scheduled/manual source-of-truth sync worker behavior. |
| `PATREON_S2S_ENTITLEMENT_ENABLED` | `false` | Enables internal entitlement reads for Magic Worlds. |
| `PATREON_CREATOR_TOKEN_REFRESH_ENABLED` | `false` | Enables automatic creator-token refresh state. |
| `PATREON_RAW_PAYLOAD_CAPTURE_ENABLED` | `false` | Enables encrypted raw-payload quarantine for approved diagnostics only. |

Disabling these switches must preserve existing local authentication, Google OAuth behavior, sessions, refresh tokens, and `/auth/validate`.

### Creator-owned Patreon API / S2S settings

| Env var | Default | Classification |
| --- | --- | --- |
| `PATREON_API_BASE_URL` | `https://www.patreon.com/api/oauth2/v2` | Server-only provider endpoint config. |
| `PATREON_OAUTH_TOKEN_URL` | `https://www.patreon.com/api/oauth2/token` | Server-only creator-token refresh endpoint config; not a browser login route. |
| `PATREON_CREATOR_ACCESS_TOKEN` | empty | Secret; server-only creator API token. |
| `PATREON_CREATOR_REFRESH_TOKEN` | empty | Secret; server-only creator refresh token when refresh is enabled. |
| `PATREON_CLIENT_ID` | empty | Secret-adjacent provider client config; server-only. |
| `PATREON_CLIENT_SECRET` | empty | Secret; server-only. |
| `PATREON_WEBHOOK_SECRET` | empty | Secret for `X-Patreon-Signature` verification. |
| `PATREON_WEBHOOK_ID` | empty | Server-only webhook management reference. |
| `PATREON_S2S_BEARER_TOKEN` | empty | Secret dedicated internal bearer for Magic Worlds/api.auth S2S. |
| `PATREON_USER_AGENT` | `api.auth-patreon-sync/1.0` | Provider API user-agent value; safe if non-secret. |

Never store creator tokens in per-user rows. Never expose these values in browser responses, activity details, audit details, logs, metrics, or docs with real secrets.

### HMAC / crypto material

| Env var | Purpose |
| --- | --- |
| `PATREON_PROVIDER_SUB_PEPPER` | HMAC pepper for durable Patreon provider user identity authority. |
| `PATREON_EMAIL_HASH_PEPPER` | HMAC pepper for proof email hashing. |
| `PATREON_PROOF_TOKEN_PEPPER` | HMAC pepper for split proof-token hash-at-rest behavior. |
| `PATREON_ID_HMAC_SECRET` | Required HMAC secret for raw Patreon campaign/member/tier IDs. |
| `PATREON_HMAC_SECRET` | Backward-compatible/fallback HMAC secret input; do not use as the production standard. |
| `PATREON_WEBHOOK_DELIVERY_HASH_PEPPER` | Pepper for local webhook delivery idempotency hashes. |
| `PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY` | Encryption key for optional global creator-token state/quarantine use. |
| `PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ID` | Non-secret key identifier if carefully redacted; still server-only by default. |

Generate unique high-entropy values outside source control. Treat HMACs, hashes, fingerprints, and hash prefixes as server-only unless a spec explicitly allows a support-safe fingerprint in an internal-only surface.

### Multi-campaign tier map settings

| Env var | Purpose |
| --- | --- |
| `PATREON_CAMPAIGN_IDS` | Optional coarse allow-list for discovery/sweeps; raw IDs stay server-only and this does not replace the tier map. |
| `PATREON_CAMPAIGN_TIER_MAP` | Preferred inline structured campaign/tier mapping JSON. |
| `PATREON_TIER_MAP_JSON` | Alternate structured tier-map JSON. |
| `PATREON_TIER_MAP_FILE` | Path to server-only tier-map JSON file. |
| `PATREON_ALLOWED_WEBHOOK_EVENTS` | Comma-separated webhook event allow-list. |

Tier-map entries require `campaign_id`, `tier_id`, `plan_code`, and `tier_code`; optional fields include `tier_name`, `priority`, `active`, and `campaign_name`. Ambiguous active mappings block readiness. Production activation should use `PATREON_CAMPAIGN_TIER_MAP`, `PATREON_TIER_MAP_JSON`, or `PATREON_TIER_MAP_FILE` as the source of truth for entitlement projection.

Default allowed webhook events:

- `members:create`
- `members:update`
- `members:delete`
- `members:pledge:create`
- `members:pledge:update`
- `members:pledge:delete`

### Retention settings

| Env var | Default | Cap |
| --- | ---: | ---: |
| `PATREON_PROOF_TOKEN_TTL_SECONDS` | `900` | Operational TTL for proof token validity. |
| `PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS` | `24` | Maximum `24` hours after proof expiry. |
| `PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS` | `90` | Maximum `90` days. |
| `PATREON_RAW_PAYLOAD_RETENTION_DAYS` | `30` | Maximum `30` days. |

Link history, membership/snapshot history, entitlement history, and unlink history are retained indefinitely in privacy-minimized form.

### Provider API, sync, worker, and health settings

| Env var | Default | Purpose |
| --- | ---: | --- |
| `PATREON_API_TIMEOUT_SECONDS` | `15` | Overall provider API timeout. |
| `PATREON_API_CONNECT_TIMEOUT_SECONDS` | `5` | Provider API connect timeout. |
| `PATREON_API_PAGE_SIZE` | `1000` | Campaign member page size; capped at `1000`. |
| `PATREON_API_MAX_PAGES_PER_SYNC` | `0` | Local page cap; `0` means no local cap. |
| `PATREON_API_RETRY_MAX_ATTEMPTS` | `3` | Provider API retry attempts. |
| `PATREON_API_RETRY_BACKOFF_SECONDS` | `1,5,15` | Provider API retry backoff sequence. |
| `PATREON_API_RETRY_JITTER_SECONDS` | `5` | Provider API retry jitter. |
| `PATREON_CREATOR_TOKEN_REFRESH_MARGIN_SECONDS` | `604800` | Refresh margin before creator-token expiry. |
| `PATREON_SYNC_INTERVAL_SECONDS` | `21600` | Scheduled full sync interval. |
| `PATREON_SYNC_JITTER_SECONDS` | `900` | Scheduled sync jitter. |
| `PATREON_SYNC_STALE_AFTER_SECONDS` | `86400` | Snapshot freshness boundary. |
| `PATREON_SYNC_WORKER_POLL_SECONDS` | `30` | Worker loop polling interval. |
| `PATREON_SYNC_WORKER_BATCH_SIZE` | `25` | Worker claimed-job batch size. |
| `PATREON_SYNC_JOB_LEASE_SECONDS` | `300` | Claimed-job lease window. |
| `PATREON_SYNC_MAX_ATTEMPTS` | `8` | Sync job max attempts. |
| `PATREON_SYNC_BACKOFF_SECONDS` | `60,300,900,3600,10800,21600` | Sync retry backoff sequence. |
| `PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_LIMIT` | `1` | Non-secret health alert threshold for signature failures. |
| `PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_WINDOW_SECONDS` | `60` | Signature-failure alert window. |

### Abuse and provider rate-limit settings

| Bucket | Limit env | Window env | Defaults |
| --- | --- | --- | --- |
| Link request | `PATREON_LINK_REQUEST_RATE_LIMIT` | `PATREON_LINK_REQUEST_RATE_WINDOW_SECONDS` | `5` / `3600s` |
| Proof request/send | `PATREON_PROOF_REQUEST_RATE_LIMIT` | `PATREON_PROOF_REQUEST_RATE_WINDOW_SECONDS` | `3` / `3600s` |
| Proof consume | `PATREON_PROOF_CONSUME_RATE_LIMIT` | `PATREON_PROOF_CONSUME_RATE_WINDOW_SECONDS` | `5` / `900s` |
| Unlink | `PATREON_UNLINK_RATE_LIMIT` | `PATREON_UNLINK_RATE_WINDOW_SECONDS` | `5` / `300s` |
| Status read | `PATREON_STATUS_RATE_LIMIT` | `PATREON_STATUS_RATE_WINDOW_SECONDS` | `60` / `60s` |
| S2S read/resync | `PATREON_S2S_RATE_LIMIT` | `PATREON_S2S_RATE_WINDOW_SECONDS` | `120` / `60s` |
| Webhook signature failure | `PATREON_WEBHOOK_SIGNATURE_FAILURE_RATE_LIMIT` | `PATREON_WEBHOOK_SIGNATURE_FAILURE_RATE_WINDOW_SECONDS` | `30` / `60s` |
| Sync enqueue | `PATREON_SYNC_ENQUEUE_RATE_LIMIT` | `PATREON_SYNC_ENQUEUE_RATE_WINDOW_SECONDS` | `30` / `300s` |
| Provider API client edge | `PATREON_API_CLIENT_RATE_LIMIT` | `PATREON_API_CLIENT_RATE_WINDOW_SECONDS` | `100` / `2s` |
| Provider access token | `PATREON_API_ACCESS_TOKEN_RATE_LIMIT` | `PATREON_API_ACCESS_TOKEN_RATE_WINDOW_SECONDS` | `100` / `60s` |
| Provider edge 4xx | `PATREON_API_EDGE_4XX_RATE_LIMIT` | `PATREON_API_EDGE_4XX_RATE_WINDOW_SECONDS` | `2000` / `600s` |

Redis rate-limit keys must use hashed bucket material only. Never use raw IPs, user hashes, emails, campaign IDs, tier IDs, member IDs, proof IDs, tokens, signatures, fingerprints, or hash prefixes in key names.

### Optional test settings

| Env var | Default | Purpose |
| --- | --- | --- |
| `RUN_PATREON_LOCAL_E2E` | `false` | Opt-in local fake Patreon/Mailpit proof flow. |
| `RUN_PATREON_E2E` | `false` | Opt-in live Patreon smoke only. |
| `PATREON_LIVE_TEST_USER_HASH` | empty | Live-test local user hash. |
| `PATREON_TEST_CAMPAIGN_ID` | empty | Live-test campaign ID; server-only test config. |
| `PATREON_TEST_MEMBER_EMAIL` | empty | Live-test member email; server-only test config. |
| `PATREON_E2E_CREATOR_TOKEN` | empty | Live-test creator token; secret. |

## Route Contracts

### `POST /auth/patreon/link/request`

| Item | Contract |
| --- | --- |
| Caller | Authenticated local user. |
| Authority | Existing local bearer/session plus recent local reauthentication. |
| Body | `patreon_email_hint` optional lookup hint, `explicit_user_intent`, `confirm_email_match` where needed. |
| Success posture | `202` generic accepted response. |
| Safe response fields | `success`, `message`, `accepted`, `link_status`, `retry_after_seconds`. |
| Forbidden | Proof token, raw/hashed provider IDs, raw or masked Patreon email, sessions, local tokens, payloads, signatures. |

### `POST /auth/patreon/link/confirm`

| Item | Contract |
| --- | --- |
| Caller | Authenticated local user. |
| Authority | Existing local bearer/session plus recent local reauthentication plus email-loop proof. |
| Body | `token` or `lookup_id` + `secret`, plus explicit user intent. |
| Success posture | `200` linked status when link activates; otherwise generic `202`/rate-limited posture. |
| Safe response fields | `success`, `message`, `link_status`, `entitlement`, `retry_after_seconds`. |
| Forbidden | Local credential issuance, provider internals, proof material echo, local email activation side effects. |

### `GET /auth/patreon/link/status`

| Item | Contract |
| --- | --- |
| Caller | Authenticated local user. |
| Authority | Existing local bearer/session for the owning user only. |
| Body | None. |
| Success posture | `200` with safe normalized link status and entitlement. |
| Safe response fields | `success`, `message`, `link_status`, `entitlement`, `retry_after_seconds`. |
| Forbidden | Any caller-supplied user selector; raw provider internals; audit rows. |

### `DELETE /auth/patreon/link`

| Item | Contract |
| --- | --- |
| Caller | Authenticated local user. |
| Authority | Existing local bearer/session plus recent local reauthentication. |
| Body | Optional explicit unlink confirmation if clients send JSON. |
| Success posture | `200` safe unlink response; generic `202` if unlink cannot be confirmed publicly. |
| Safe response fields | `success`, `message`, `link_status`, `entitlement`. |
| Forbidden | Session revocation caused by Patreon, raw provider internals, destructive history deletion. |

### `POST /webhooks/patreon`

| Item | Contract |
| --- | --- |
| Caller | Patreon webhook sender. |
| Authority | `X-Patreon-Signature` HMAC-MD5 over exact raw request body using server-only webhook secret. |
| Headers | `X-Patreon-Event`, `X-Patreon-Signature`. |
| Body | Raw JSON:API bytes; parse only after signature verification. |
| Success posture | `200` accepted/ignored/duplicate safe response after durable decision. |
| Failure posture | `401` invalid signature; `429` excessive signature failures; `500` only for retryable post-verification processing failure. |
| Forbidden | Browser session authority, raw body audit capture, raw signature/payload exposure. |

### `GET /internal/users/{user_hash}/entitlements`

| Item | Contract |
| --- | --- |
| Caller | Magic Worlds/internal service. |
| Authority | Dedicated `Authorization: Bearer <PATREON_S2S_BEARER_TOKEN>` only. |
| Body | None. |
| Success posture | `200` safe S2S entitlement response; no current Patreon row returns normalized free/no-Patreon. |
| Failure posture | Generic `401`, `404`, or `429` for unauthorized, degraded, or rate-limited reads without provider disclosure. |
| Forbidden | Browser cookies/session authority; credential issuance; raw provider internals. |

### `POST /internal/users/{user_hash}/entitlements/patreon/resync`

| Item | Contract |
| --- | --- |
| Caller | Magic Worlds/internal service or operator S2S workflow. |
| Authority | Dedicated `Authorization: Bearer <PATREON_S2S_BEARER_TOKEN>` only. |
| Body | Optional `force` and redacted `reason`. |
| Success posture | `202` accepted/queued/disabled/degraded/rate-limited safe response. |
| Safe response fields | `success`, `message`, `accepted`, `status`, `user_hash`, `retry_after_seconds`, `not_before`, `correlation_id`, `contract_version`. |
| Forbidden | Raw member/campaign/tier selectors; do not expose provider payloads; hashes/fingerprints; secrets. |

## Forbidden and Absent Route Names

The following Patreon routes are intentionally forbidden and absent:

- `/auth/patreon/login` — forbidden and absent.
- `/auth/patreon/authorize` — forbidden and absent.
- `/auth/patreon/callback` — forbidden and absent.
- `/auth/patreon/token` — forbidden and absent.

Do not add equivalent Patreon OAuth-session routes under another name. Patreon proof, webhooks, creator API reads, and resync jobs are not local login paths.

## Safe S2S Fields

`GET /internal/users/{user_hash}/entitlements` may return only the versioned response envelope and the allow-listed entitlement fields.

### Envelope

- `success`
- `message`
- `user_hash`
- `entitlement`
- `contract_version`

### Entitlement object

- `external_source`
- `status`
- `plan_code`
- `tier_code`
- `tier_name`
- `link_status`
- `next_renewal_at`
- `grace_period_until`
- `last_synced_at`
- `stale_after`
- `classification_version`

Allowed normalized statuses include `active`, `free`, `pending`, `former`, `revoked`, and `stale`. Allowed safe link statuses include `none`, `pending`, `linked`, `unlinked`, `revoked`, and blocked-safe statuses where explicitly normalized by the route layer.

## Activity Catalog Reference

Patreon activity events are reserved in `act-cat-075` through `act-cat-090`.

| Code | Activity type | Typical use |
| --- | --- | --- |
| `act-cat-075` | `patreon_link_proof_requested` | Link proof request accepted/enqueued. |
| `act-cat-076` | `patreon_link_proof_consumed` | Email-loop proof consumed exactly once. |
| `act-cat-077` | `patreon_linked` | Provider identity linked and initial entitlement classified/pending. |
| `act-cat-078` | `patreon_link_rejected` | Generic rejection, hidden/null email, conflict, malformed proof, feature not-ready. |
| `act-cat-079` | `patreon_unlinked` | Soft unlink completed. |
| `act-cat-080` | `patreon_webhook_received` | Verified webhook accepted/ignored/resync-required. |
| `act-cat-081` | `patreon_webhook_rejected` | Signature failure or unsafe webhook rejection. |
| `act-cat-082` | `patreon_webhook_replay_ignored` | Duplicate/replayed delivery ignored without repeated side effects. |
| `act-cat-083` | `patreon_sync_started` | Scheduled/manual sync job started or queued. |
| `act-cat-084` | `patreon_sync_completed` | Sync job completed. |
| `act-cat-085` | `patreon_sync_failed` | Sync failed, retrying, disabled, or degraded. |
| `act-cat-086` | `patreon_entitlement_changed` | Current normalized entitlement changed. |
| `act-cat-087` | `patreon_tier_map_miss` | Active tier had no configured mapping. |
| `act-cat-088` | `patreon_token_refreshed` | Creator token refresh/rotation succeeded. |
| `act-cat-089` | `patreon_token_revoked` | Creator token invalid/revoked/degraded. |
| `act-cat-090` | `patreon_retention_purged` | Bounded retention purge completed. |

Activity details must use redacted safe values only: reason codes, status transitions, counts, route/method/status, sync source, and correlation IDs. Do not place raw provider data in activity details.

## Schema Concepts

| Concept | Tables / procedures | Notes |
| --- | --- | --- |
| External provider authority | `user_external_accounts(provider='patreon')` | Durable link authority by provider-sub HMAC/fingerprint; no per-user Patreon token columns. |
| Email-loop proof | `patreon_link_proofs`, `sp_patreon_proof_create`, `sp_patreon_proof_consume` | Hash-only split proof; proof email sent through `email_messages` purpose/template `patreon_link_proof`. |
| Campaign registry | `patreon_campaigns` | Stores HMAC/fingerprint campaign references and enabled status. |
| Tier mapping | `patreon_tier_map` | Campaign-scoped tier HMAC/fingerprint mapped to internal `plan_code`/`tier_code` with priority. |
| Membership authority | `patreon_memberships` | Per linked provider/campaign membership state, HMAC/fingerprint IDs, soft unlink states. |
| Member snapshots | `patreon_member_snapshots`, `patreon_member_snapshot_history` | Append-only observation evidence; privacy-minimized. |
| Current entitlement | `patreon_entitlements_current` | One current normalized projection per user. |
| Entitlement history | `patreon_entitlement_history` | Append-only entitlement changes and unlink/relink evidence. |
| Webhook idempotency | `patreon_webhook_deliveries`, `sp_patreon_webhook_delivery_record` | Local delivery hash because Patreon has no native delivery ID. |
| Sync queue | `patreon_sync_jobs`, `sp_patreon_sync_job_enqueue`, `sp_patreon_sync_job_claim`, `sp_patreon_sync_job_complete` | Full campaign, member, user, retention, token refresh, and webhook resync jobs. |
| Raw-payload quarantine | `patreon_raw_payload_quarantine` | Disabled by default, encrypted/server-only, 30-day maximum. |
| Creator-token state | `patreon_provider_token_state` | Optional global provider-token state only; never per-user. |
| Retention purge | `sp_patreon_retention_purge` | Purges bounded proof/webhook/quarantine artifacts, preserves history. |

## Retention Windows

| Data bucket | Window | Enforcement notes |
| --- | --- | --- |
| Proof requests | 24 hours after proof expiry | Purge or irreversible stripping; no recoverable proof secret remains. |
| Webhook hashes / delivery ledger | 90 days | Purge/anonymize delivery hash/idempotency records; current snapshots/history remain. |
| Raw provider payload quarantine | 30 days maximum | Disabled by default; if enabled, encrypted/server-only and purged within cap; do not expose externally. |
| Link history | Indefinite | Privacy-minimized; no indefinite raw payload/email requirement. |
| Membership/snapshot history | Indefinite | Append-only normalized evidence for audit/dispute/resync reasoning. |
| Entitlement history | Indefinite | Preserves prior/current normalized state transitions. |
| Unlink/relink history | Indefinite | Required for non-destructive rollback and dispute investigation. |

## Forbidden Browser-Visible Fields

Browser-visible responses, Magic Worlds browser projection, and public errors must not expose server-only Patreon fields. The list below is intentionally explicit; if a field is not allow-listed, it stays server-only.

Required forbidden field examples:

- `raw_patreon_email`
- `masked_patreon_email`
- `hash_prefix`
- `audit_rows`
- raw IDs: `patreon_user_id`, `patreon_member_id`, `patreon_campaign_id`, `patreon_tier_id`, `provider_sub_raw`
- raw ID hashes/fingerprints by default: `patreon_user_id_hash`, `patreon_member_id_hash`, `patreon_campaign_id_hash`, `patreon_tier_id_hash`, `provider_sub_hash`, `provider_sub_fingerprint`, `member_id_hash`, `campaign_id_hash`, `tier_id_hash`
- signatures: `x-patreon-signature`, `patreon_signature`, webhook signatures, `body_digest`, body digests
- payloads: `webhook_payload`, `patreon_payload`, `patreon_raw_payload`, `provider_payload`, `provider_response`, `raw_payload`, `raw_body` must not be exposed
- tokens/secrets: `creator_token`, `creator_access_token`, `creator_refresh_token`, `patreon_access_token`, `patreon_refresh_token`, `proof_token_raw`, `proof_token`, `proof_secret`, `token_hash`, `s2s_token`, `s2s_bearer_token`, `webhook_secret`, `patreon_client_secret`, HMAC secrets, encryption keys
- raw Patreon provider statuses and charge internals: `patron_status`, `currently_entitled_tiers`, `last_charge_status`
- delivery/audit internals: `delivery_hash`, `raw_body_sha256`, `payload_hash`, audit/activity rows, sync-job internals

Do not add Patreon fields to JWT claims, Redis session payloads, refresh-token state, browser cookies, local login/register/switch-project responses, or `/auth/validate`.

## Safe Error Posture

| Surface | Error principle |
| --- | --- |
| Link request/confirm | Generic public messages; no disclosure of membership, email, proof, campaign, tier, conflict owner, or credential state. |
| Status | Owning user only; fallback to safe `none/free` when status cannot be read safely. |
| Unlink | Generic if unlink cannot be completed; no provider internals and no local session revocation. |
| Webhook | Invalid signature rejected before mutation; response does not disclose secret-validation detail. |
| S2S | Dedicated bearer only; authorized no-row reads return safe free/no-Patreon, while unauthorized/degraded/rate-limited reads use generic `401`/`404`/`429`. |
| Sync/worker | Coarse degraded reasons only; no raw provider payloads or secrets in logs/activity/health. |

## Related Documentation

- [Overview](README.md)
- [Architecture](architecture.md)
- [Request Flow](request-flow.md)
- [Scenarios](scenarios.md)
- [Troubleshooting](troubleshooting.md)
- [Runbook](../../RUNBOOKS/patreon-link.md)

---

**Document Version**: 1.0
