# Patreon link architecture

`api.auth` stays the only identity and session authority and adds Patreon as a
server-owned entitlement source: link, prove, classify, sync, and expose a normalized
entitlement over S2S. Patreon never authenticates anyone.

## Design decisions

| Decision | Why |
| --- | --- |
| `api.auth` owns link authority, proofs, webhook verification, sync, snapshots and classification | It already owns external-account identity, audit, redaction, the e-mail outbox and the session boundary. Splitting provider secrets or link authority into the companion would create two sources of truth. |
| Entitlement and link only, never login | Sessions, refresh tokens, cookies and `/auth/validate` stay free of Patreon-derived fields; no Patreon proof, webhook or read can create a session. |
| Link authority is an HMAC of the Patreon user id, not the e-mail | Patreon e-mail is mutable and can be hidden. Raw ids stay server-side. |
| Ownership is proven by an e-mail-loop token | The creator API returns the member's e-mail to the creator; a one-time token sent only there proves the user controls it. A hidden or empty e-mail blocks linking rather than falling back to anything weaker. |
| Campaign-scoped tier map with priorities | Classification must handle several campaigns and several tiers deterministically instead of hard-coding one campaign. |
| Webhooks are a fast path; the worker is the source of truth | Patreon webhooks can be partial, retried, duplicated or out of order and carry no delivery id or event time. Full reads correct them. |
| The companion reads a dedicated S2S contract | Entitlements change after sign-in, so they must not be frozen into JWTs, sessions or `/auth/validate`. |
| Allow-listed DTOs | A response model can only serialize fields on its allow-list; a forbidden field name fails at start-up. |

## Components

```text
                        ┌───────────────────────────────┐
                        │            Patreon            │
                        │ creator API + signed webhooks │
                        └───────┬───────────────▲───────┘
              signed member     │               │ creator API reads
              events            │               │ (creator token)
┌─────────────┐  link/status/   ▼               │
│ Browser/SPA │  unlink  ┌──────────────────────┴──────────────────────┐
│ signed-in   │─────────▶│ api.auth                                    │
│ consumer    │          │  auth_patreon routes   (link lifecycle)     │
└─────────────┘          │  patreon_webhooks      (fast path)          │
                         │  internal_patreon      (S2S read, resync)   │
┌─────────────┐  proof   │  admin_patreon         (root dashboard)     │
│ Member      │◀─────────│  e-mail outbox + worker (proof delivery)    │
│ mailbox     │          │  patreon_sync_worker   (sweeps, queue,      │
└─────────────┘          │                         retention, token)   │
                         └──────────────────────┬──────────────────────┘
                                                │ normalized S2S only
                                                ▼
                                   ┌─────────────────────────┐
                                   │ Companion service       │
                                   │ (membership projection) │
                                   └─────────────────────────┘
```

| Owner | Responsibilities |
| --- | --- |
| `api.auth` | Link lifecycle, provider identity HMACs, proofs, webhook verification, creator API sync, tier classification, snapshots and history, retention, redaction, health, the S2S contract. |
| Patreon | Membership data and signed webhooks. Never trusted for login. |
| Companion service | Calls the S2S read and projects normalized fields in its own product. It holds no provider secrets and no raw Patreon data. |
| Browser | Starts link, status and unlink calls with the user's session and receives only normalized status. |

## Link and proof

1. A signed-in, recently authenticated consumer sends the e-mail of their Patreon account
   as a hint.
2. `api.auth` pages through the members of every configured campaign with the creator
   token and selects the member whose Patreon e-mail equals the hint. The hint only
   selects; it proves nothing.
3. If the member's e-mail is present, a proof is created and e-mailed to that address
   through the transactional e-mail outbox.
4. The user follows the link; the front end posts the token to `link/confirm` from the
   same signed-in session. The proof is consumed atomically, only for the user who
   requested it.
5. The link is created unless the Patreon account is linked to someone else or the user
   already has a Patreon link. The first entitlement is classified from a fresh read of
   the member; if that read fails, the entitlement is `pending` and a resync is queued.

Proof tokens are `<lookup_id>.<secret>` (a 12-character lookup id and a 256-bit random
secret), stored only as an HMAC under
`PATREON_PROOF_TOKEN_PEPPER`, purpose-scoped, bound to the requesting user, valid for
`PATREON_PROOF_TOKEN_TTL_SECONDS`, blocked after 8 wrong secrets, and never echoed in
responses, logs or activity. The proof e-mail uses the `patreon_link_proof` template.

## Classification

For each linked member the classifier considers every campaign membership:

1. Only `active_patron` (or `active`) memberships can grant.
2. Only campaigns in the configuration count; a mapped tier in an unconfigured campaign
   grants nothing.
3. Each entitled tier is looked up by `(campaign, tier)` in the tier map. Of all active
   matches, the one with the highest `priority` wins; ties break on `plan_code`,
   `tier_code` and `tier_name`.
4. An active member whose tiers are all unmapped gets `pending` with a resync request, and
   a paid plan already on record is kept meanwhile; nothing is granted from an unmapped
   tier.
5. A complete read with no active mapped tier (declined, former, no tier) gives `former`
   with plan `free`.
6. A partial read never downgrades: the current entitlement is kept and a resync is
   requested.

```text
Linked member ── campaign A / tier 1 ─┐
               ├ campaign A / tier 2 ─┼─ tier map ─▶ highest priority ─▶ plan_code, tier_code
               └ campaign B / tier 7 ─┘
```

## Webhook fast path and source of truth

A webhook delivery is verified on its exact raw bytes (HMAC-MD5 with the webhook secret)
before it is parsed. A local delivery hash over the event, member, campaign and body
digest makes redeliveries idempotent. For a Patreon user linked to a local account:

- a complete signed member document from a create or update event is applied directly,
  downgrades included, because it is Patreon's own statement of the member's state;
- a partial document, a `*:delete` event or an unmapped tier queues a resync of that
  member instead.

Deliveries for Patreon users linked to nobody are acknowledged and ignored. When
processing fails after the delivery was recorded, a resync is queued and the delivery is
still acknowledged, so repeated errors do not make Patreon pause the webhook.

The worker corrects everything else: scheduled full sweeps of every configured campaign,
queued member and user resyncs, and reconciliation. After a complete sweep, linked
memberships that Patreon no longer returns become `former`/free; the link stays, so the
user can pledge again without relinking. Provider errors write nothing, so an outage never
downgrades anyone; entitlements simply age into `stale`.

## S2S boundary

```text
Companion ── GET /internal/users/{user_hash}/entitlements
             Authorization: Bearer <PATREON_S2S_BEARER_TOKEN>
                  │ constant-time bearer check; cookies and user tokens ignored
                  ▼
             current entitlement row ──▶ allow-listed DTO ──▶ companion projection
```

The companion learns `user_hash` from its own session validation and asks for that user's
entitlement. A wrong bearer learns nothing: unauthorized reads answer `401` without
revealing whether the user, the link or the entitlement exists, and authorized reads for
users without data answer the free projection.

## Data classification

| Class | Contents | May reach |
| --- | --- | --- |
| Server-only | Raw Patreon ids, raw or masked Patreon e-mail, creator and refresh tokens, client and webhook secrets, the S2S bearer, peppers and keys, signatures, payloads, proof secrets and hashes, id hashes and fingerprints, delivery and body hashes, sync-job internals, audit rows | Nothing outside `api.auth` |
| S2S-safe | `external_source`, `status`, `plan_code`, `tier_code`, `tier_name`, `link_status`, `next_renewal_at`, `grace_period_until`, `last_synced_at`, `stale_after`, `classification_version`, `contract_version` | The companion service |
| Browser-safe | `link_status` and the same entitlement fields, for the user's own account | The signed-in user |

The full forbidden-field list is in the
[reference](reference.md#forbidden-browser-visible-fields).

## Persistence

```text
user_external_accounts (provider='patreon')   link authority, HMAC of the Patreon user id
patreon_link_proofs                           hash-only proofs, expiry, attempts
patreon_campaigns + patreon_tier_map          HMAC mirror of the configured tier map
patreon_memberships                           member per campaign, HMAC ids
patreon_member_snapshots (+ _history)         append-only observations
patreon_entitlements_current                  one normalized projection per user
patreon_entitlement_history                   every transition, including unlink
patreon_webhook_deliveries                    idempotency ledger
patreon_sync_jobs                             resync queue
patreon_provider_token_state                  global, encrypted creator token
patreon_raw_payload_quarantine                optional encrypted API pages
```

Rollback disables behavior through the switches, ingress and the worker; it never deletes
link, snapshot, entitlement, webhook or audit history.

## Module map

| Area | Code |
| --- | --- |
| Link request, confirm, status, unlink | `src/routes/auth_patreon.py` |
| Webhook receiver | `src/routes/patreon_webhooks.py` |
| S2S read and resync | `src/routes/internal_patreon.py` |
| Root dashboard | `src/routes/admin_patreon.py` |
| Configuration and readiness | `src/Util/patreon/config.py` |
| HMACs, proofs, signatures, S2S bearer | `src/Util/patreon/security.py` |
| Creator API client | `src/Util/patreon/client.py` |
| Classification | `src/Util/patreon/classifier.py` |
| Tier-map mirror | `src/Util/patreon/catalog.py` |
| Sync helpers and job queue | `src/Util/patreon/sync.py` |
| Rate limits | `src/Util/patreon/rate_limit.py` |
| Database wrappers | `src/Util/db/db_patreon.py` |
| Sync worker | `src/workers/patreon_sync_worker.py`, started by `scripts/run_patreon_worker.sh` |
| Response allow-lists | `src/Util/Models.py` |

## Current limitations

These are gaps in the code, documented so operators do not rely on them:

- A provider failure does not mark entitlements stale: readers compute `stale` from
  `stale_after`, and the retry is recorded in the sync-job ledger and as
  `patreon_sync_failed`. The worker heartbeat lives in Redis only (read by
  `worker.status`); there is no database heartbeat or provider-health table.
- Sync jobs are always created with `max_attempts` `8`; `PATREON_SYNC_MAX_ATTEMPTS` has
  no effect.
- No `EXT_81xx` error code is ever returned.
