# Patreon Link Request Flow

This document describes the request flows for the Patreon account-link and entitlement surface in `api.auth`.

Patreon is **entitlement/link only**. It is not local authentication authority, it does not create sessions, and it does not add Patreon-derived fields to JWTs, refresh-token state, session payloads, cookies, or `/auth/validate`.

## Route Map

| Flow | Route | Caller | Authority |
| --- | --- | --- | --- |
| Link request | `POST /auth/patreon/link/request` | Authenticated local user | Existing local session plus recent local reauthentication |
| Link confirm | `POST /auth/patreon/link/confirm` | Authenticated local user | Existing local session plus recent local reauthentication plus email-loop proof |
| Link status | `GET /auth/patreon/link/status` | Authenticated local user | Existing local session for the owning user only |
| Unlink | `DELETE /auth/patreon/link` | Authenticated local user | Existing local session plus recent local reauthentication |
| Webhook | `POST /webhooks/patreon` | Patreon webhook sender | `X-Patreon-Signature` HMAC-MD5 over exact raw body |
| S2S read | `GET /internal/users/{user_hash}/entitlements` | Magic Worlds/internal service | Dedicated internal bearer credential |
| S2S manual resync | `POST /internal/users/{user_hash}/entitlements/patreon/resync` | Magic Worlds/internal service or operator workflow | Dedicated internal bearer credential |

Forbidden and absent Patreon auth routes remain forbidden:

- `/auth/patreon/login` — forbidden and absent.
- `/auth/patreon/authorize` — forbidden and absent.
- `/auth/patreon/callback` — forbidden and absent.
- `/auth/patreon/token` — forbidden and absent.

## 1. Link Request Flow

`POST /auth/patreon/link/request` starts a local-account-owned link proof. The caller must already be authenticated locally and must satisfy recent local reauthentication. A Patreon request never starts a local login session.

```text
Browser / SPA
  │ local authenticated request
  │ POST /auth/patreon/link/request
  │ body: patreon_email_hint?, explicit_user_intent, confirm_email_match?
  ▼
api.auth auth_patreon route
  │ validate existing local session
  │ require recent local reauthentication
  │ rate-limit link request
  │ require explicit user intent
  │ verify Patreon linking config is ready
  ▼
Patreon creator API lookup
  │ configured campaigns only
  │ optional email hint narrows lookup only
  │ email hint is not durable authority
  ▼
proof decision
  ├─ non-null Patreon member email available
  │    create hash-only proof token and enqueue proof email
  └─ hidden/null Patreon email or unavailable member
       return generic accepted posture; no active link and no entitlement grant
```

### Link request rules

- `patreon_email_hint` is a lookup hint only.
- Proof is delivered only to the Patreon member email returned by the creator-owned Patreon API.
- Hidden or null Patreon email blocks v1 automated activation.
- The response is generic and enumeration-safe: it does not reveal whether the email belongs to a patron, whether the membership exists, or whether another local user is linked.
- The response must not include access tokens, refresh tokens, session cookies, API keys, raw Patreon IDs, emails, signatures, provider payloads, hashes, hash prefixes, or audit rows.

## 2. Link Confirm Flow

`POST /auth/patreon/link/confirm` consumes the email-loop proof and activates the Patreon link only when all authority checks pass.

```text
User receives proof at Patreon-returned member email
  │
  │ POST /auth/patreon/link/confirm
  │ body: token OR lookup_id + secret, explicit_user_intent
  ▼
api.auth auth_patreon route
  │ validate existing local session
  │ require recent local reauthentication
  │ rate-limit proof consumption
  │ parse split proof token
  │ hash submitted proof material
  ▼
DB proof consume
  │ atomically match lookup_id + token_hash
  │ enforce pending, unexpired, single-use proof
  │ enforce proof bound to current local user
  ▼
provider identity conflict check
  ├─ provider identity linked to another user → generic rejection
  ├─ same user already linked to another active identity → relink required
  └─ clear → activate link
       create user_external_accounts(provider='patreon') authority row
       create/update membership row
       classify initial entitlement or mark pending source-of-truth resync
```

### Link confirm rules

- Proof consumption is atomic and single-use.
- Malformed, unknown, expired, already consumed, wrong-purpose, wrong-user, or rate-limited tokens produce a generic response.
- Link authority is the Patreon provider identity represented through HMAC/fingerprint material, not email equality.
- Link activation must not activate local email state.
- Link activation must not issue local sessions or credential material.

## 3. Status Flow

`GET /auth/patreon/link/status` returns the current user's safe normalized link state and entitlement summary.

```text
Browser / SPA
  │ GET /auth/patreon/link/status
  │ existing local session only
  ▼
api.auth auth_patreon route
  │ validate caller's local session
  │ rate-limit status read
  │ read current Patreon status for caller's user_id/user_hash only
  ▼
safe DTO serialization
  │ link_status
  │ entitlement.status
  │ plan_code / tier_code / tier_name when safe
  │ last_synced_at / stale_after when safe
  ▼
Browser-safe response
```

### Status rules

- There is no caller-supplied user selector.
- Another user's Patreon state cannot be probed through the route.
- Stale snapshots must be labeled stale/degraded through normalized fields instead of being presented as fresh.
- The response must not include raw Patreon IDs, campaign IDs, tier IDs, raw or masked Patreon email, signatures, payloads, hashes, hash prefixes, fingerprints, audit rows, tokens, or secrets.

## 4. Unlink Flow

`DELETE /auth/patreon/link` soft-unlinks Patreon for the authenticated local user.

```text
Browser / SPA
  │ DELETE /auth/patreon/link
  │ existing local session + recent reauth
  ▼
api.auth auth_patreon route
  │ validate local session
  │ require recent local reauthentication
  │ rate-limit unlink
  ▼
DB soft unlink
  │ user_external_accounts(provider='patreon') -> unlinked
  │ patreon_memberships -> unlinked
  │ current entitlement -> free/unlinked or revoked/unlinked
  │ append entitlement history
  ▼
safe unlink response
```

### Unlink rules

- Unlink is soft and auditable.
- Unlink stops future Patreon-backed entitlement projection unless a new link lifecycle completes.
- Unlink does not revoke local sessions, JWTs, refresh-token state, cookies, or API keys because Patreon is not local login authority.
- Link, snapshot, entitlement, and unlink history are preserved indefinitely in privacy-minimized form.

## 5. Webhook Flow

`POST /webhooks/patreon` is a fast path for entitlement changes. It is not a browser route and does not require a local user session.

```text
Patreon
  │ POST /webhooks/patreon
  │ headers: X-Patreon-Event, X-Patreon-Signature
  │ body: exact raw JSON:API bytes
  ▼
api.auth webhook route
  │ read exact raw bytes before parsing
  │ verify X-Patreon-Signature with HMAC-MD5(raw_body, webhook_secret)
  │ reject missing/malformed/invalid signatures before mutation
  │ apply configured member/pledge event allow-list
  ▼
delivery ledger
  │ derive local delivery_hash from event/member/campaign/body digest
  │ duplicate/replay -> safe success, no repeated side effects
  ▼
classification / resync decision
  ├─ complete verified payload + known tier map + linked identity
  │    update snapshot/current entitlement and append history
  └─ partial, unsupported, unknown, ambiguous, out-of-order, or unknown tier
       enqueue source-of-truth resync or mark stale; no destructive downgrade
```

### Webhook rules

- Only exact raw-body verification is trusted.
- Body normalization, parsing before verification, altered whitespace, altered encoding, or changed bytes must fail verification.
- Unsupported events are ignored or recorded safely without entitlement mutation.
- Duplicate deliveries are idempotent because Patreon does not provide a native delivery ID.
- Partial or ambiguous webhook payloads must not revoke or downgrade paid entitlement without source-of-truth confirmation.

Configured allowed event defaults:

- `members:create`
- `members:update`
- `members:delete`
- `members:pledge:create`
- `members:pledge:update`
- `members:pledge:delete`

## 6. Scheduled Resync Flow

Scheduled resync is the source-of-truth correction path for all configured campaigns.

```text
PatreonSyncWorker
  │ enabled by PATREON_SYNC_ENABLED
  │ scheduled interval + jitter
  ▼
full configured campaign sweep
  │ fetch campaign member pages through creator API
  │ include user and currently_entitled_tiers evidence
  │ obey API timeout, page cap, retry, and backoff policy
  ▼
classifier
  │ normalize patron status
  │ apply campaign-scoped tier map
  │ resolve highest-priority mapped tier
  │ mark unknown tier as fail-safe/no paid grant
  ▼
persistence
  │ update current entitlement
  │ append snapshot/history
  │ record tier-map misses and health
```

### Scheduled resync rules

- Scheduled resync evaluates each configured campaign.
- Provider 429 responses back off using provider/local retry policy.
- Provider outages, timeouts, and creator-token failures preserve last-known paid snapshots as stale/degraded instead of destructive downgrade.
- With no current trusted snapshot, provider failure fails closed for new paid grants.

## 7. Manual Resync Flow

Manual resync is accepted through the internal S2S endpoint and processed by the worker queue.

```text
Magic Worlds / operator S2S caller
  │ POST /internal/users/{user_hash}/entitlements/patreon/resync
  │ Authorization: Bearer <PATREON_S2S_BEARER_TOKEN>
  ▼
api.auth internal_patreon route
  │ constant-time bearer check
  │ reject cookies/browser sessions as authority
  │ S2S rate-limit
  │ sync enqueue rate-limit
  │ verify sync feature is enabled
  ▼
patreon_sync_jobs
  │ enqueue user_member/manual_resync job
  │ return safe accepted/queued/disabled/rate_limited/degraded response
  ▼
PatreonSyncWorker
  │ claim job
  │ scan configured campaigns or targeted member evidence
  │ classify and persist through same source-of-truth path
```

### Manual resync rules

- The request body may carry only safe controls such as `force` or a redacted `reason`.
- The response may include `accepted`, `status`, `user_hash`, `retry_after_seconds`, `not_before`, `correlation_id`, and `contract_version`.
- It must not expose raw provider selectors, campaign IDs, member IDs, tier IDs, provider payloads, hashes, fingerprints, tokens, or secrets.

## 8. Internal S2S Entitlement Read Flow

`GET /internal/users/{user_hash}/entitlements` is the only v1 contract for Magic Worlds entitlement consumption.

```text
Magic Worlds
  │ existing identity/session validation remains separate
  │ GET /internal/users/{user_hash}/entitlements
  │ Authorization: Bearer <PATREON_S2S_BEARER_TOKEN>
  ▼
api.auth internal_patreon route
  │ constant-time dedicated bearer verification
  │ no cookie/session authority
  │ S2S rate-limit
  │ read current normalized entitlement by user_hash
  ▼
safe S2S DTO
  │ user_hash
  │ contract_version
  │ entitlement.external_source
  │ entitlement.status
  │ entitlement.plan_code / tier_code / tier_name
  │ entitlement.link_status
  │ next_renewal_at / grace_period_until / last_synced_at / stale_after
  │ classification_version
```

### S2S rules

- Unauthorized requests return generic denial and must not reveal whether the user hash, Patreon link, campaign, tier, or entitlement exists.
- The endpoint must not accept browser cookies as authority.
- The endpoint must not issue sessions or mutate local authentication state.
- S2S fields are normalized and allow-listed; raw Patreon internals are server-only.

## 9. Retention Flow

Retention is bounded by artifact sensitivity.

```text
PatreonSyncWorker retention_only mode or retention job
  │
  ▼
sp_patreon_retention_purge / DB wrapper
  ├─ purge proof requests 24h after expiry
  ├─ purge webhook delivery hashes/idempotency ledger after 90d
  ├─ purge encrypted raw-payload quarantine within 30d max
  └─ preserve link, snapshot, entitlement, and unlink history indefinitely
```

### Retention rules

| Artifact | Retention |
| --- | --- |
| Proof requests | 24 hours after expiry, then purged or irreversibly stripped. |
| Webhook hashes / delivery ledger | 90 days. |
| Raw payload quarantine | Disabled by default; if enabled, encrypted/server-only and purged within 30 days maximum. |
| Link history, membership/snapshot history, entitlement history, unlink history | Indefinite, privacy-minimized. |

Indefinite history must not require indefinite raw provider payloads, raw emails, signatures, tokens, or secrets.

## 10. Failure and Rollback Flow Summary

| Condition | Flow behavior |
| --- | --- |
| Missing Patreon config | Keep feature disabled/not-ready; local auth and Google OAuth unaffected. |
| Link proof delivery failure | Generic public posture; no active link; no entitlement grant. |
| Provider 429 | Back off and preserve existing snapshots as stale/degraded. |
| Creator token refresh failure | Degraded health; preserve last-known snapshots; fail closed for new grants. |
| Partial webhook | Enqueue resync or mark stale; no destructive downgrade. |
| Manual rollback | Disable flags/ingress/worker/S2S and clear only Patreon Redis namespaces; preserve DB history. |

## Related Documentation

- [Overview](README.md)
- [Architecture](architecture.md)
- [Scenarios](scenarios.md)
- [Reference](reference.md)
- [Troubleshooting](troubleshooting.md)
- [Runbook](../../RUNBOOKS/patreon-link.md)

---

**Document Version**: 1.0
