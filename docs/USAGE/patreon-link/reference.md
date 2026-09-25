# Patreon link reference

The contract for Patreon account linking: settings, routes, response fields, statuses,
activity codes, schema and retention. Concepts are in the [README](README.md); what each
request does step by step is in [request-flow.md](request-flow.md).

## Settings

All values are read from the environment by `src/Util/patreon/config.py`. A value that
fails validation (a bad integer, a retention value above its cap, an ambiguous tier map)
makes the whole Patreon configuration invalid: the webhook answers `503`, the S2S routes
`401`, the link routes their neutral answer, admin resync `disabled`, and the worker
idles. Secrets are server-only and never appear in responses, logs, activity or health.

### Feature switches

| Variable | Default | Enables |
| --- | --- | --- |
| `PATREON_LINKING_ENABLED` | `false` | `POST /auth/patreon/link/request` and `/link/confirm`. Status and unlink work regardless, so a user can always see and remove a link. |
| `PATREON_WEBHOOKS_ENABLED` | `false` | Processing of `POST /webhooks/patreon` (also needs `PATREON_WEBHOOK_SECRET`). |
| `PATREON_SYNC_ENABLED` | `false` | Worker sweeps and the resync queue, and resync requests from S2S and the dashboard. |
| `PATREON_S2S_ENTITLEMENT_ENABLED` | `false` | The internal S2S routes (also needs `PATREON_S2S_BEARER_TOKEN`). |
| `PATREON_CREATOR_TOKEN_REFRESH_ENABLED` | `false` | Worker refresh of the creator token and its encrypted storage. |
| `PATREON_RAW_PAYLOAD_CAPTURE_ENABLED` | `false` | Encrypted quarantine of raw Patreon API pages read by the worker, for approved diagnostics only. |

Turning a switch off leaves local authentication, OAuth sign-in, sessions and
`/auth/validate` unchanged.

### Provider credentials

| Variable | Default | Notes |
| --- | --- | --- |
| `PATREON_API_BASE_URL` | `https://www.patreon.com/api/oauth2/v2` | Creator API base. |
| `PATREON_OAUTH_TOKEN_URL` | `https://www.patreon.com/api/oauth2/token` | Used only to refresh the creator token; not a login route. |
| `PATREON_CREATOR_ACCESS_TOKEN` | empty | Creator API token. Required for linking and sync. |
| `PATREON_CREATOR_REFRESH_TOKEN` | empty | Required when token refresh is on. |
| `PATREON_CLIENT_ID` | empty | Used only in the token-refresh request. |
| `PATREON_CLIENT_SECRET` | empty | Used only in the token-refresh request. |
| `PATREON_WEBHOOK_SECRET` | empty | Key of the `X-Patreon-Signature` HMAC. |
| `PATREON_WEBHOOK_ID` | empty | Parsed but not used by any code path. |
| `PATREON_S2S_BEARER_TOKEN` | empty | The dedicated internal bearer. |
| `PATREON_USER_AGENT` | `api.auth-patreon-sync/1.0` | `User-Agent` sent to Patreon. |

Creator tokens are global provider state, never stored per user.

### HMAC and encryption material

| Variable | Purpose |
| --- | --- |
| `PATREON_PROVIDER_SUB_PEPPER` | HMAC key of the Patreon user id, the durable link key. |
| `PATREON_EMAIL_HASH_PEPPER` | HMAC key of the proof recipient's e-mail. |
| `PATREON_PROOF_TOKEN_PEPPER` | HMAC key of proof tokens at rest. |
| `PATREON_ID_HMAC_SECRET` | HMAC key of campaign, member and tier ids. Required for linking. |
| `PATREON_HMAC_SECRET` | Legacy alias, read only when `PATREON_ID_HMAC_SECRET` is empty. |
| `PATREON_WEBHOOK_DELIVERY_HASH_PEPPER` | HMAC key of webhook delivery hashes; plain SHA-256 is used when empty. |
| `PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY` | Encryption of the stored creator token and of quarantined payloads. Required for token refresh and payload capture. |
| `PATREON_PROVIDER_TOKEN_ENCRYPTION_KEY_ID` | Id stored with each ciphertext. |

### Tier map

The tier map is the only classification authority. The first non-empty source wins; the
sources are never merged:

1. `PATREON_CAMPAIGN_TIER_MAP` — inline JSON.
2. `PATREON_TIER_MAP_JSON` — inline JSON.
3. `PATREON_TIER_MAP_FILE` — path to a server-only JSON file.

Accepted shapes: an array of entries, `{"entries": [...]}`, or
`{"campaigns": [{"campaign_id": "...", "campaign_name": "...", "tiers": [...]}]}`.

| Entry field | Required | Notes |
| --- | --- | --- |
| `campaign_id` | yes | Non-empty string (a JSON number is rejected). Taken from the parent in the `campaigns` shape. |
| `tier_id` | yes | Non-empty string. |
| `plan_code` | yes | Internal plan, for example `magic_worlds_plus`. |
| `tier_code` | yes | Internal tier, for example `artisan`. |
| `tier_name` | no | Display name returned to readers. |
| `priority` | no | Integer, default `0`. The highest value wins when a member holds several mapped tiers. |
| `active` | no | Boolean, default `true`. |
| `campaign_name` | no | Operator label. |

The configuration is rejected as ambiguous when the same campaign and tier appear with a
different plan, tier code, priority or `active` flag, or when two active tiers of one
campaign share a priority. Exact duplicates are ignored.

`PATREON_CAMPAIGN_IDS` (comma-separated) adds campaigns to the ones named by the tier
map. The merged list is what link discovery and worker sweeps read; a campaign without
mapped tiers never grants anything. It is not an allow-list.

`patreon_campaigns` and `patreon_tier_map` hold an HMAC and fingerprint mirror of the tier
map. The mirror is refreshed when the configuration changes (once per process), from the
worker's pass, before a proof is e-mailed, before a webhook update is stored, and before
`GET /admin/patreon/tier-map` lists entries. Entries removed from the configuration are
deactivated, never deleted. `scripts/migrations/patreon_tier_map_seed.py` can pre-seed the
mirror but is not required.

`PATREON_ALLOWED_WEBHOOK_EVENTS` (comma-separated) defaults to `members:create`,
`members:update`, `members:delete`, `members:pledge:create`, `members:pledge:update`,
`members:pledge:delete`.

### Retention

| Variable | Default | Allowed range |
| --- | --- | --- |
| `PATREON_PROOF_TOKEN_TTL_SECONDS` | `900` | Proof validity. |
| `PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS` | `24` | `0`–`24` |
| `PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS` | `90` | `0`–`90` |
| `PATREON_RAW_PAYLOAD_RETENTION_DAYS` | `30` | `0`–`30`; `0` disables capture |

What each window purges is in [Retention windows](#retention-windows).

### API, sync and worker

| Variable | Default | Notes |
| --- | --- | --- |
| `PATREON_API_TIMEOUT_SECONDS` | `15` | Request timeout. |
| `PATREON_API_CONNECT_TIMEOUT_SECONDS` | `5` | Connect timeout. |
| `PATREON_API_PAGE_SIZE` | `1000` | Campaign member page size, `1`–`1000`. |
| `PATREON_API_MAX_PAGES_PER_SYNC` | `0` | `0` means no cap. A sweep that hits the cap fails and is retried; it is not truncated. |
| `PATREON_CREATOR_TOKEN_REFRESH_MARGIN_SECONDS` | `604800` | The worker refreshes the creator token this long before it expires (checked hourly). |
| `PATREON_SYNC_INTERVAL_SECONDS` | `21600` | Interval between scheduled full sweeps; `0` or less disables them. |
| `PATREON_SYNC_JITTER_SECONDS` | `900` | Random delay added to the sweep interval and to job backoff. |
| `PATREON_SYNC_STALE_AFTER_SECONDS` | `86400` | Freshness window written as `stale_after`. |
| `PATREON_SYNC_WORKER_POLL_SECONDS` | `30` | Worker loop interval. |
| `PATREON_SYNC_WORKER_BATCH_SIZE` | `25` | Jobs claimed per pass. |
| `PATREON_SYNC_JOB_LEASE_SECONDS` | `300` | Lease on a claimed job. |
| `PATREON_SYNC_BACKOFF_SECONDS` | `60,300,900,3600,10800,21600` | Retry delay by attempt; the last value repeats. |
| `PATREON_SYNC_MAX_ATTEMPTS` | `8` | Parsed, but jobs are always created with `max_attempts` `8`. |
| `PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_LIMIT` | `1` | Health only: failures in the window that mark webhooks degraded. |
| `PATREON_WEBHOOK_SIGNATURE_FAILURE_ALERT_WINDOW_SECONDS` | `60` | Health only. |
| `PATREON_API_RETRY_MAX_ATTEMPTS` | `3` | Parsed but not used; the client does not retry requests. |
| `PATREON_API_RETRY_BACKOFF_SECONDS` | `1,5,15` | Not used; the `PATREON_SYNC_*` backoff applies. |
| `PATREON_API_RETRY_JITTER_SECONDS` | `5` | Not used. |

### Rate limits

Fixed windows in Redis under `patreon_rate:<bucket>:`, keyed on SHA-256 digests only.

| Bucket | Limit / window variables | Default | Counted per |
| --- | --- | --- | --- |
| Link request | `PATREON_LINK_REQUEST_RATE_LIMIT`, `PATREON_LINK_REQUEST_RATE_WINDOW_SECONDS` | `5` per `3600` s | User, IP, e-mail hint |
| Proof send | `PATREON_PROOF_REQUEST_RATE_LIMIT`, `PATREON_PROOF_REQUEST_RATE_WINDOW_SECONDS` | `3` per `3600` s | User, IP, recipient (the hint) |
| Proof consume | `PATREON_PROOF_CONSUME_RATE_LIMIT`, `PATREON_PROOF_CONSUME_RATE_WINDOW_SECONDS` | `5` per `900` s | User, IP, proof lookup id |
| Unlink | `PATREON_UNLINK_RATE_LIMIT`, `PATREON_UNLINK_RATE_WINDOW_SECONDS` | `5` per `300` s | User, IP |
| Status | `PATREON_STATUS_RATE_LIMIT`, `PATREON_STATUS_RATE_WINDOW_SECONDS` | `60` per `60` s | User, IP |
| S2S | `PATREON_S2S_RATE_LIMIT`, `PATREON_S2S_RATE_WINDOW_SECONDS` | `120` per `60` s | One counter for user hash, calling client (`X-Internal-Client`, else `User-Agent`) and IP |
| Webhook signature failure | `PATREON_WEBHOOK_SIGNATURE_FAILURE_RATE_LIMIT`, `PATREON_WEBHOOK_SIGNATURE_FAILURE_RATE_WINDOW_SECONDS` | `30` per `60` s | Source IP |
| Sync enqueue | `PATREON_SYNC_ENQUEUE_RATE_LIMIT`, `PATREON_SYNC_ENQUEUE_RATE_WINDOW_SECONDS` | `30` per `300` s | Job kind and user; S2S and the dashboard keep separate budgets |
| Provider client, access token, edge 4xx | `PATREON_API_CLIENT_RATE_LIMIT`, `PATREON_API_ACCESS_TOKEN_RATE_LIMIT`, `PATREON_API_EDGE_4XX_RATE_LIMIT` and their windows | `100`/`2` s, `100`/`60` s, `2000`/`600` s | Declared but not enforced; provider throttling is handled by honoring Patreon's `429` |

User-facing buckets keep one counter per dimension and refuse the request when any is
exhausted, so changing one dimension (another IP header, another hint) never resets the
budget. The IP counter allows five times the per-user limit for shared egress addresses.
The proof-send bucket is spent on every link request before Patreon is contacted, so
neither the budget nor the timing reveals whether an e-mail belongs to a patron. A Redis
error refuses the request (`429`).

### Test settings

| Variable | Default | Purpose |
| --- | --- | --- |
| `RUN_PATREON_LOCAL_E2E` | `false` | Opt-in local fake-Patreon and Mailpit proof flow. |
| `RUN_PATREON_E2E` | `false` | Opt-in live Patreon smoke test. |
| `PATREON_LIVE_TEST_USER_HASH` | empty | Local user for the live test. |
| `PATREON_TEST_CAMPAIGN_ID` | empty | Campaign for the live test. |
| `PATREON_TEST_MEMBER_EMAIL` | empty | Member e-mail for the live test. |

## Routes

Browser and dashboard routes:

| Path | Method | Auth | Success |
| --- | --- | --- | --- |
| `/auth/patreon/link/request` | POST | Access token plus recent authentication | `202` neutral body, always |
| `/auth/patreon/link/confirm` | POST | Access token plus recent authentication | `200` linked, or `202` neutral |
| `/auth/patreon/link/status` | GET | Access token | `200` link status and entitlement |
| `/auth/patreon/link` | DELETE | Access token plus recent authentication | `200` unlinked, or `202` neutral |
| `/admin/patreon/status` | GET | Root | `200` operational status |
| `/admin/patreon/entitlements` | GET | Root | `200` entitlement list |
| `/admin/patreon/entitlements/{user_hash}` | GET | Root | `200` one entitlement |
| `/admin/patreon/entitlements/{user_hash}/history` | GET | Root | `200` entitlement transitions |
| `/admin/patreon/tier-map` | GET | Root | `200` tier-map mirror |
| `/admin/patreon/sync-jobs` | GET | Root | `200` sync job ledger |
| `/admin/patreon/webhooks` | GET | Root | `200` webhook delivery ledger |
| `/admin/patreon/resync` | POST | Root | `200` queued or refused |

Machine-to-machine routes:

| Route | Auth | Success |
| --- | --- | --- |
| `POST /webhooks/patreon` | `X-Patreon-Signature` | `200` accepted |
| `GET /internal/users/{user_hash}/entitlements` | S2S bearer | `200` entitlement |
| `POST /internal/users/{user_hash}/entitlements/patreon/resync` | S2S bearer | `202` accepted or refused |

"Access token" means `Authorization: Bearer <access JWT>` or the `session_token` cookie.
"Recent authentication" means a sign-in, or an OAuth reauth of the same session, within
`OAUTH_RECENT_REAUTH_SECONDS` (default `300`); without it the answer is `401` `AUTH_1008`.
Unknown body fields on the link routes are `400` `VAL_3001`. Rate-limited link routes
answer `429` with their usual neutral body and a `Retry-After` header; request, confirm
and status bodies also carry `retry_after_seconds`.

### Link request

`POST /auth/patreon/link/request` — JSON body:

| Field | Notes |
| --- | --- |
| `patreon_email_hint` | The e-mail on the user's Patreon account, 3–320 characters; a value that is not an e-mail address is `400`. Required in practice: without it no member is looked up and nothing is sent. |
| `explicit_user_intent` | Must be `true`; otherwise nothing is sent. |
| `confirm_email_match` | Accepted and ignored. |

Every outcome — proof e-mailed, no matching member, hidden e-mail, feature off,
non-consumer account, provider error — answers:

```json
{
  "success": true,
  "message": "If the Patreon link can be processed, a proof request has been accepted.",
  "accepted": true
}
```

### Link confirm

`POST /auth/patreon/link/confirm` — JSON body with either `token` (`<lookup_id>.<secret>`,
as carried in the e-mailed link's `token` query parameter) or `lookup_id` and `secret`.
`explicit_user_intent` is accepted and not checked. The proof must have been requested by
the same user.

`200` when the link is activated:

```json
{
  "success": true,
  "message": "Patreon link confirmed.",
  "link_status": "linked",
  "entitlement": {
    "external_source": "patreon",
    "status": "active",
    "plan_code": "magic_worlds_plus",
    "tier_code": "artisan",
    "tier_name": "Artisan",
    "link_status": "linked",
    "last_synced_at": "2026-09-24T10:00:00Z",
    "stale_after": "2026-09-25T10:00:00Z",
    "classification_version": 1
  }
}
```

If Patreon could not be read right after linking, the link is still active, the
entitlement is `pending` and a resync is queued. Every unsuccessful outcome (malformed,
unknown, expired, reused or blocked proof, another user's proof, a conflict, feature off)
answers `202`:

```json
{
  "success": true,
  "message": "If the Patreon link can be confirmed, the request has been processed.",
  "link_status": "pending"
}
```

A proof is blocked after 8 wrong secrets.

### Link status

`GET /auth/patreon/link/status` — no body, no recent authentication. Only the caller's own
state is readable. Answers `200` with `link_status` and `entitlement`, message
`"Patreon link status retrieved."`. When the state cannot be read it answers
`link_status: none` with the free entitlement instead of an error.

### Unlink

`DELETE /auth/patreon/link` — no body. `200` with `link_status: unlinked` and a free
entitlement:

```json
{
  "success": true,
  "message": "Patreon link unlinked.",
  "link_status": "unlinked",
  "entitlement": {
    "status": "free",
    "plan_code": "free",
    "link_status": "unlinked",
    "last_synced_at": "2026-09-24T10:00:00Z",
    "classification_version": 1
  }
}
```

When nothing is linked or the unlink fails, the answer is `202` with `link_status: none`
and message `"If the Patreon link can be unlinked, the request has been processed."`.
Sessions, tokens, cookies and API keys are not touched.

### Webhook

`POST /webhooks/patreon` — the raw JSON:API body exactly as Patreon sent it, with headers
`X-Patreon-Event` and `X-Patreon-Signature` (32 lower-case hex characters: HMAC-MD5 of the
raw body keyed with `PATREON_WEBHOOK_SECRET`). The raw body is excluded from API audit
capture.

| Status | Body | When |
| --- | --- | --- |
| `200` | `{"success": true, "status": "accepted"}` | Every verified delivery: applied, ignored (event not allowed, Patreon user linked to nobody), duplicate, resync queued, or processing failed with a resync queued. |
| `401` | `{"success": false, "message": "Webhook rejected."}` | Signature missing or invalid. Nothing is recorded in the ledger. |
| `429` | Same as `401`, with `Retry-After` | More than the signature-failure limit from one IP. |
| `503` | `{"success": false, "message": "Webhook unavailable."}` | Webhooks off, no secret, or invalid configuration. |
| `500` | `{"success": false, "message": "Webhook processing failed."}` | The delivery could not be recorded, or processing failed and no resync could be queued. Patreon redelivers. |

### Internal entitlement read

`GET /internal/users/{user_hash}/entitlements` — `Authorization: Bearer
<PATREON_S2S_BEARER_TOKEN>`, compared in constant time. Cookies, user tokens and API keys
are not accepted.

```json
{
  "success": true,
  "message": "Patreon entitlement retrieved.",
  "user_hash": "8F3A2C1B9D7E6F50",
  "entitlement": {
    "external_source": "patreon",
    "status": "active",
    "plan_code": "magic_worlds_plus",
    "tier_code": "artisan",
    "tier_name": "Artisan",
    "link_status": "linked",
    "last_synced_at": "2026-09-24T10:00:00Z",
    "stale_after": "2026-09-25T10:00:00Z",
    "classification_version": 1
  },
  "contract_version": 1
}
```

| Case | Answer |
| --- | --- |
| Linked user | `200` as above. `status` reads `stale` when it is `active` and `stale_after` has passed. |
| User without Patreon data, or unknown or inactive `user_hash` | `200` free projection: `status: free`, `plan_code: free`, `link_status: none`. |
| S2S off, no bearer configured, bearer missing or wrong, invalid configuration | `401` `{"success": false, "message": "Unauthorized."}` |
| Rate limited | `429` `{"success": false, "message": "Request could not be processed."}` with `Retry-After` |
| Read failure | `404` with the same generic body |

### Internal resync

`POST /internal/users/{user_hash}/entitlements/patreon/resync` — same bearer. Optional
JSON body `{"force": bool, "reason": str}`: `force` queues at priority `1` instead of `5`;
`reason` is 1–128 characters. Unknown fields are `400` `VAL_3001`.

| Case | Answer |
| --- | --- |
| Queued | `202` `accepted: true`, `status: queued`, `user_hash`, `correlation_id` (the job id; an identical queued job is reused and its id returned). |
| Sync off | `202` `accepted: false`, `status: disabled` |
| Unknown or inactive user, or the job could not be queued | `202` `accepted: false`, `status: degraded` |
| Enqueue budget exhausted | `429` `accepted: false`, `status: rate_limited`, `retry_after_seconds`, `Retry-After` |
| S2S request limit | `429` generic body |
| Bearer missing or wrong, S2S off | `401` generic body |

A user without a Patreon link is still queued; the worker finds nothing and changes
nothing.

### Admin dashboard routes

Root only; other callers get `403` `AUTHZ_2001`. Responses pass through an allow-list and
a redaction pass: fingerprints, codes and counts, never creator tokens, raw ids,
plaintext e-mails or payloads. List routes take `limit` and `offset` (`offset` ≥ 0) and
return `items` and `pagination` (`limit`, `offset`, `total`, `has_more`).

| Route | Query | Returns |
| --- | --- | --- |
| `GET /admin/patreon/status` | — | Overall `status`, `generated_at`, and groups `readiness`, `creator_token`, `webhooks`, `snapshots`, `tier_map`, `database_clock`, `proof_delivery`, `s2s`, `worker`, `sync_queue`, `metrics`. |
| `GET /admin/patreon/entitlements` | `limit` (1–500, default `50`), `status`, `plan_code`, `link_status`, `search` (exact `user_hash`, or username/e-mail prefix) | `user_hash`, `display_name`, `status`, `link_status`, `plan_code`, `tier_code`, `tier_name`, `next_renewal_at`, `last_synced_at`, `stale_after`, `updated_at`. |
| `GET /admin/patreon/entitlements/{user_hash}` | — | The S2S shape; active users without data get the free projection; `404` `NF_4004` for an unknown or inactive user. |
| `GET /admin/patreon/entitlements/{user_hash}/history` | `limit` (1–200, default `50`) | Newest first: `history_id`, previous and new status, plan and tier codes, `link_status`, `reason`, `sync_source`, `observed_at`. |
| `GET /admin/patreon/tier-map` | `refresh_catalog` (default `true`), `limit` (1–500, default `100`), `active` | Campaign and tier fingerprints, `campaign_name`, `plan_code`, `tier_code`, `tier_name`, `priority`, `active`, effective window. |
| `GET /admin/patreon/sync-jobs` | `limit` (1–500, default `50`), `status` | `job_id`, `job_type`, `status`, `priority`, `attempts`, `max_attempts`, `not_before`, `source`, timestamps, `has_error`. |
| `GET /admin/patreon/webhooks` | `limit` (1–500, default `50`), `status` | `delivery_id`, `event_type`, `status`, `signature_valid`, `received_at`, `processed_at`. Only verified deliveries are recorded. |
| `POST /admin/patreon/resync` | — | See below. |

Filters match exact strings. `POST /admin/patreon/resync` takes a JSON object with
`scope` (`user`, the default, or `all`), `user_hash` (at most 255), `reason` (at most 128)
and `force`:

| Case | Answer |
| --- | --- |
| Sync off, or invalid configuration | `200` `accepted: false`, `status: disabled` (checked first) |
| `scope: user` without `user_hash`, or a field too long | `400` `VAL_3001` |
| Enqueue budget exhausted (same variables as S2S, separate counter) | `429` `INT_7005` with `Retry-After` |
| Unknown user | `404` |
| User without an active Patreon membership | `200` `accepted: false`, `status: not_linked`; nothing queued |
| Queued | `200` `accepted: true`, `status: queued`, `correlation_id`; a request identical to a queued job is merged into it and the message says so |

`scope: all` queues one full sweep over every configured campaign. Jobs run only while the
sync worker is running.

## Entitlement fields

| Field | Notes |
| --- | --- |
| `external_source` | `patreon`, or omitted when the user has no Patreon data. |
| `status` | `active` (a mapped tier grants a plan), `free` (no Patreon data, or unlinked), `pending` (link just made or classification waiting for a resync), `former` (a complete read found no paid tier), `revoked` (link revoked), `stale` (`active` past `stale_after`, computed at read time). |
| `plan_code`, `tier_code`, `tier_name` | From the tier map; `plan_code` is `free` without a paid grant. |
| `link_status` | `none`, `pending`, `linked`, `unlinked`, `revoked`, `blocked`. |
| `next_renewal_at`, `grace_period_until` | Copied from Patreon member data when present; there is no local grace logic. |
| `last_synced_at`, `stale_after` | When the entitlement was last classified and when it becomes stale. |
| `classification_version` | Contract version of the classification, currently `1`. |

Serialized responses omit `null` fields. The S2S envelope adds `user_hash` and
`contract_version`.

## Error codes

No Patreon route returns an `EXT_81xx` code today. The family (`EXT_8100`–`EXT_8116`,
listed in the [error reference](../errors.md)) is defined but not returned.
What callers actually receive:

| Surface | Errors |
| --- | --- |
| Link routes | Neutral `202` bodies for refusals; `401` platform envelope (`AUTH_1008` when recent authentication is missing); `400` `VAL_3001`; `429` neutral body with `Retry-After`. |
| Webhook | Generic bodies with `401`, `429`, `500`, `503` (see [Webhook](#webhook)). |
| S2S | Generic bodies with `401`, `404`, `429`; resync refusals as `202` or `429` with `accepted: false`. |
| Admin | `403` `AUTHZ_2001`, `400` `VAL_3001`, `404` `NF_4004`, `429` `INT_7005` with `Retry-After`. |

## Activity codes

Patreon activity types are `act-cat-075` to `act-cat-090`. Details carry reason codes,
statuses and counts only.

| ID | Activity type | Recorded by |
| --- | --- | --- |
| `act-cat-075` | `patreon_link_proof_requested` | Link request, when a proof is queued. |
| `act-cat-076` | `patreon_link_proof_consumed` | Link confirm, when the proof is consumed. |
| `act-cat-077` | `patreon_linked` | Link confirm, when the link is active. |
| `act-cat-078` | `patreon_link_rejected` | Any refusal on request, confirm or unlink; `reason` names it (for example `patreon_email_hidden_or_null`, `provider_identity_unavailable`, `active_patreon_link_exists`, `recent_reauth_required`). |
| `act-cat-079` | `patreon_unlinked` | Unlink. |
| `act-cat-080` | `patreon_webhook_received` | Verified webhook deliveries (applied, ignored, resync required, processing failed); duplicates record `act-cat-082` instead. |
| `act-cat-081` | `patreon_webhook_rejected` | Webhook signature failures. |
| `act-cat-082` | `patreon_webhook_replay_ignored` | Verified deliveries the ledger already holds; answered `200` without reprocessing. |
| `act-cat-083` | `patreon_sync_started` | Resync queued from S2S or the dashboard. |
| `act-cat-084` | `patreon_sync_completed` | Worker, after each campaign sweep, with page, member, miss and downgrade counts. |
| `act-cat-085` | `patreon_sync_failed` | S2S resync refused (disabled, degraded, rate limited), and worker provider failures with `retry_after_seconds`. |
| `act-cat-086` | `patreon_entitlement_changed` | Webhook updates, and worker downgrades of members a complete sweep no longer returns. |
| `act-cat-087` | `patreon_tier_map_miss` | Webhook deliveries and worker syncs that meet an unmapped tier. Health counts misses from entitlement history. |
| `act-cat-088` | `patreon_token_refreshed` | Worker, after a successful creator-token refresh. |
| `act-cat-089` | `patreon_token_revoked` | Worker, when Patreon answers `401` to the creator token. |
| `act-cat-090` | `patreon_retention_purged` | Worker, after each retention pass, with purge counts. |

## Schema

Tables are in `schemas/tables/11_patreon_entitlements.sql`, procedures in
`schemas/stored_procedures/16_patreon_entitlements.sql`.

| Concept | Tables and procedures | Notes |
| --- | --- | --- |
| Link | `user_external_accounts` (`provider='patreon'`); `sp_patreon_link_conflict_check`, `sp_patreon_link_account`, `sp_patreon_relink_account`, `sp_patreon_unlink_account` | Keyed on the Patreon user-id HMAC. No per-user provider tokens. |
| Proof | `patreon_link_proofs`; `sp_patreon_proof_create`, `sp_patreon_proof_consume` | Hash-only token; the e-mail is queued in `email_messages` with purpose and template `patreon_link_proof`. |
| Catalog mirror | `patreon_campaigns`, `patreon_tier_map`; `sp_patreon_catalog_campaign_upsert`, `sp_patreon_catalog_tier_upsert`, `sp_patreon_catalog_retire_missing` | HMAC and fingerprint copy of the configured tier map. |
| Membership | `patreon_memberships`; `sp_patreon_membership_observe`, `sp_patreon_list_active_memberships` | Per linked member and campaign. |
| Snapshots | `patreon_member_snapshots`, `patreon_member_snapshot_history`; `sp_patreon_entitlement_snapshot_upsert` | Append-only observations. |
| Entitlement | `patreon_entitlements_current`, `patreon_entitlement_history`; `sp_patreon_get_entitlement_by_user_hash` | One current row per user, plus history. |
| Webhook ledger | `patreon_webhook_deliveries`; `sp_patreon_webhook_delivery_record`, `sp_patreon_webhook_delivery_mark` | Local delivery hash; Patreon sends no delivery id. |
| Sync queue | `patreon_sync_jobs`; `sp_patreon_sync_job_enqueue`, `sp_patreon_sync_job_claim`, `sp_patreon_sync_job_complete` | Enqueue returns the job actually queued (`deduplicated` when merged). |
| Creator token | `patreon_provider_token_state`; `sp_patreon_provider_token_state_upsert`, `sp_patreon_provider_token_state_get`, `sp_patreon_provider_token_state_get_encrypted` | Global, encrypted. |
| Quarantine | `patreon_raw_payload_quarantine`; `sp_patreon_raw_payload_quarantine_insert` | Encrypted raw API pages when capture is on. |
| Retention | `sp_patreon_retention_purge(proof_hours, webhook_days, sync_job_days)` | See below. |
| Dashboard | `sp_patreon_admin_list_entitlements`, `sp_patreon_admin_entitlement_history`, `sp_patreon_admin_list_tier_map`, `sp_patreon_admin_list_sync_jobs`, `sp_patreon_admin_list_webhooks` | Read-only listings. |

## Retention windows

The sync worker runs the purge at start-up and then every 24 hours, whether or not sync
is enabled.

| Data | Window |
| --- | --- |
| Proof requests | Purged `PATREON_PROOF_RETENTION_AFTER_EXPIRY_HOURS` (at most `24`) after expiry. |
| Webhook delivery ledger | `PATREON_WEBHOOK_DELIVERY_RETENTION_DAYS` (at most `90`). |
| Finished sync jobs (`completed`, `failed`, `cancelled`) | `30` days. Active jobs are never purged. |
| Raw-payload quarantine | Ciphertext blanked at the row's purge time (at most `30` days after capture); the row is kept. |
| Links, memberships, snapshots, entitlement and unlink history | Kept indefinitely, privacy-minimized. |

## Forbidden browser-visible fields

Browser-visible responses, S2S responses and public errors carry only the allow-listed
fields above. These are always server-only:

- raw ids: `patreon_user_id`, `patreon_member_id`, `patreon_campaign_id`, `patreon_tier_id`, `provider_sub_raw`
- id hashes and fingerprints: `patreon_user_id_hash`, `patreon_member_id_hash`, `patreon_campaign_id_hash`, `patreon_tier_id_hash`, `provider_sub_hash`, `provider_sub_fingerprint`, `member_id_hash`, `campaign_id_hash`, `tier_id_hash`, `hash_prefix`
- e-mail: `raw_patreon_email`, `masked_patreon_email`
- signatures: `x-patreon-signature`, `patreon_signature`, `body_digest`
- payloads, which are never exposed: `webhook_payload`, `patreon_payload`, `patreon_raw_payload`, `provider_payload`, `provider_response`, `raw_payload`, `raw_body`
- tokens and secrets: `creator_token`, `creator_access_token`, `creator_refresh_token`, `patreon_access_token`, `patreon_refresh_token`, `proof_token_raw`, `proof_token`, `proof_secret`, `token_hash`, `s2s_token`, `s2s_bearer_token`, `webhook_secret`, `patreon_client_secret`, HMAC secrets, encryption keys
- raw Patreon statuses: `patron_status`, `currently_entitled_tiers`, `last_charge_status`
- internals: `delivery_hash`, `raw_body_sha256`, `payload_hash`, `audit_rows`, activity rows, sync-job internals
- local auth material: `access_token`, `refresh_token`, `session_token`, `api_key`, `token_type`, `expires_in` and their variants
