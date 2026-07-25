# Patreon Link Architecture

Patreon account linking keeps `api.auth` as the identity/session authority while adding Patreon as a server-owned entitlement source. The feature is intentionally narrow: link, prove, classify, sync, and expose normalized entitlement over S2S. It does not authenticate users through Patreon.

## Architectural Decisions

| Decision | Why |
| --- | --- |
| `api.auth` owns Patreon link authority, proof state, webhook verification, sync, snapshots/history, and classification | The auth repo already owns external-account identity authority, audit, redaction, email outbox, and local session boundaries. Splitting provider secrets or link authority into Magic Worlds would create two sources of truth. |
| Patreon is entitlement/link only, never local login | Local credentials, sessions, refresh tokens, cookies, and `/auth/validate` remain free of Patreon-derived fields. Patreon proof or webhook data cannot create a session. |
| Provider identity is stored through HMAC/fingerprint authority | Patreon email is mutable/hidden and must not be durable link authority. Raw Patreon IDs are server-only. |
| v1 secondary proof is an email-loop token | User-resolved v1 proof requires sending a single-use token only to the Patreon member email returned by the creator API. Hidden/null email blocks automated v1 activation. |
| Multi-campaign tier mapping is first-class from day one | Entitlement classification must evaluate configured campaigns and campaign-scoped tiers with deterministic priority instead of hard-coding one campaign. |
| Webhooks are a fast path; scheduled/manual resync is source of truth | Patreon webhooks can be partial, retried, duplicated, or out of order. Source-of-truth API reads reconcile final entitlement state. |
| Magic Worlds reads a dedicated S2S contract | Entitlement is mutable and must not be embedded in JWTs, sessions, refresh-token state, or `/auth/validate`. |
| Safe DTOs are allow-listed | Server-only provider data must never reach browser-visible responses or Magic Worlds S2S payloads. |

## Ownership Split

| Owner | Responsibilities |
| --- | --- |
| `api.auth` | Local auth boundary, Patreon link lifecycle, provider identity HMACs, email-loop proof, webhook verification, creator API sync, tier classification, entitlement snapshots/history, retention, audit/activity redaction, health, and S2S entitlement endpoint. |
| Patreon | External membership data source and signed webhook sender. It is not trusted for local login. |
| Magic Worlds | Companion consumer that calls `api.auth` S2S entitlement read and projects only normalized membership fields in its own domain. |
| Browser/SPA | Initiates local authenticated link/status/unlink interactions and receives only safe normalized status. It never receives raw Patreon internals. |

`api.auth` owns the source of truth for Patreon link and entitlement state. Magic Worlds consumes; it does not own provider secrets, webhook verification, tier-map authority, or raw Patreon data.

## High-Level System Diagram

```text
                         ┌──────────────────────────────┐
                         │           Patreon            │
                         │ creator API + signed webhooks │
                         └──────────────┬───────────────┘
                                        │
               creator API reads        │ signed member events
                                        │
┌──────────────┐ local session  ┌───────▼────────────────────────────────────┐
│ Browser/SPA  │───────────────▶│               api.auth                     │
│ local user   │ link/status/   │ - local auth boundary                      │
│              │ unlink only    │ - link/proof owner                         │
└──────────────┘                │ - webhook verifier                         │
                                │ - sync worker                              │
                                │ - tier classifier                          │
                                │ - snapshots/history/retention              │
                                │ - safe S2S entitlement endpoint            │
                                └──────────────┬─────────────────────────────┘
                                               │ normalized S2S only
                                               ▼
                                ┌──────────────────────────────┐
                                │        Magic Worlds          │
                                │ membership projection/cache  │
                                └──────────────────────────────┘
```

## Link and Email-Loop Proof

The link lifecycle starts from an already-authenticated local user. Patreon never starts a local session.

```text
Authenticated local user
  │
  │ POST /auth/patreon/link/request
  │ - local session required
  │ - recent local reauth required
  │ - explicit user intent required
  ▼
api.auth link route
  │
  │ creator API member discovery across configured campaigns
  │ email hint may narrow lookup, but is not authority
  ▼
Patreon member data
  │
  ├─ non-null member email matches local email + explicit confirmation
  │      → provider identity proof conditions satisfied
  │
  ├─ non-null member email differs
  │      → send email-loop token only to Patreon-returned email
  │
  └─ null/hidden member email
         → blocked-safe v1 status; no entitlement grant
```

Email-loop token properties:

- cryptographically random,
- split-token or equivalent hash-only at rest,
- purpose-scoped to Patreon linking,
- single-use,
- short-lived,
- bound to the initiating local user and pending link request,
- delivered only to the Patreon member email returned by the creator API,
- never echoed in responses, audit rows, logs, or activity details.

After proof succeeds, `api.auth` creates or updates provider identity authority using HMAC/fingerprint material and creates an initial normalized entitlement snapshot. The proof response must not include access tokens, refresh tokens, session cookies, API keys, or authenticated user payloads.

## Multi-Campaign Tier Mapping

Patreon classification supports multiple campaigns from day one.

```text
Patreon memberships for one linked provider identity
  │
  ├─ campaign A / tier 1 ─┐
  ├─ campaign A / tier 2 ─┼─ campaign-scoped tier map
  └─ campaign B / tier 7 ─┘
                           │
                           ▼
                deterministic priority resolution
                           │
                           ▼
              normalized plan/tier entitlement
```

Tier-map rules:

1. Each mapping is scoped by campaign and tier.
2. Raw campaign/tier IDs are used only server-side and stored by HMAC/fingerprint where persisted.
3. Classification evaluates all configured campaigns for the linked Patreon identity.
4. The highest-priority active mapping wins.
5. Unknown tiers fail safe: no paid entitlement is granted from an unmapped tier.
6. Ambiguous mappings block readiness/enablement with a non-secret operator error.
7. Observed evidence for all memberships remains server-side for audit/resync reasoning.

Fixture terminology currently used by tests and docs includes plan code `magic_worlds_plus`, tier codes `artisan` and `pro`, campaign fixture `campaign-mw-alpha`, and tier fixture `tier-mw-alpha-artisan`. These are examples, not browser-visible raw Patreon IDs.

## Webhook Fast Path and Resync Source of Truth

Patreon webhook delivery is useful for latency but is not the final source of truth.

```text
Patreon webhook
  │ POST /webhooks/patreon
  │ X-Patreon-Event
  │ X-Patreon-Signature = HMAC-MD5(raw body, webhook secret)
  ▼
api.auth webhook route
  │ read exact raw bytes
  │ verify signature before parsing JSON
  │ allow only configured member/pledge events
  │ derive local delivery hash because Patreon has no native delivery ID
  ▼
delivery ledger
  │ duplicate → safe 200, no repeated side effects
  ▼
classification decision
  ├─ complete trusted payload + known tier map → update snapshot/current entitlement
  └─ partial/ambiguous/unknown/out-of-order → enqueue scheduled/manual resync
```

Scheduled and manual resync are source-of-truth correction paths:

- full configured campaign sweeps,
- per-member/user resync jobs,
- Patreon API pagination,
- provider 429 backoff and jitter,
- creator-token failure degraded posture,
- stale snapshot preservation instead of destructive downgrade,
- tier-map miss health/activity signals.

Partial webhooks must not downgrade paid entitlement by themselves. Provider outages and rate limits preserve last-known snapshots as stale/degraded and fail closed for new grants.

## S2S Contract Boundary

Magic Worlds reads normalized entitlement from `api.auth` through a dedicated internal bearer credential.

```text
Magic Worlds
  │ existing local auth validation flow obtains/knows user_hash
  │
  │ GET /internal/users/{user_hash}/entitlements
  │ Authorization: Bearer <PATREON_S2S_BEARER_TOKEN>
  ▼
api.auth internal route
  │ constant-time bearer verification
  │ cookies and browser sessions ignored
  │ current normalized snapshot read
  ▼
safe S2S DTO
  │ external_source, plan_code, tier_code, status,
  │ link_status, renewal/grace/staleness timestamps,
  │ contract_version
  ▼
Magic Worlds projection
```

The S2S endpoint must not accept browser cookies as authority and must not issue sessions. Unauthorized requests must not reveal whether the user hash, Patreon link, campaign, tier, or entitlement exists.

### Safe S2S entitlement envelope

Allowed normalized fields:

- `user_hash`,
- `contract_version`,
- `external_source`,
- `status`,
- `plan_code`,
- `tier_code`,
- `tier_name`,
- `link_status`,
- `next_renewal_at`,
- `grace_period_until`,
- `last_synced_at`,
- `stale_after`,
- `classification_version`.

No raw Patreon identifiers, raw campaign/tier IDs, emails, payloads, signatures, hashes, fingerprints, audit rows, or secrets are part of the S2S payload.

## No-Login and Auth-State Boundary

Patreon routes and workers do not own local authentication. Forbidden and absent Patreon auth routes are:

- `/auth/patreon/login` — forbidden and absent.
- `/auth/patreon/authorize` — forbidden and absent.
- `/auth/patreon/callback` — forbidden and absent.
- `/auth/patreon/token` — forbidden and absent.

The integration must not write Patreon fields into:

- JWT claims,
- session Redis values,
- refresh-token family state,
- local auth cookies,
- `/auth/validate` response models,
- local login/register/switch-project response models.

Unlinking Patreon also must not revoke local sessions. Google may login/link in the separate Google OAuth flow; Patreon remains entitlement/link only.

## Data Classification

Patreon data is classified by release surface. The safe posture is allow-list first, not deny-list after the fact.

### Server-only

Server-only fields include:

- raw Patreon IDs,
- raw campaign IDs,
- raw tier IDs,
- raw or masked Patreon emails by default,
- creator access/refresh tokens,
- client secrets,
- webhook secrets,
- S2S bearer token or token hash,
- HMAC peppers and encryption keys,
- signatures,
- raw webhook/provider payloads must not be exposed,
- proof token raw values and token hashes,
- HMAC hashes,
- delivery hashes,
- body hashes,
- support fingerprints,
- hash prefixes,
- sync-job internals,
- audit rows,
- provider API responses.

Server-only values may be processed inside `api.auth`; they must not cross into browser-visible responses or Magic Worlds S2S DTOs.

### Internal S2S safe

S2S may include only normalized fields needed for server-side membership projection:

- `external_source`,
- normalized entitlement `status`,
- `plan_code`,
- `tier_code`,
- `tier_name`,
- normalized `link_status`,
- `next_renewal_at`,
- `grace_period_until`,
- `last_synced_at`,
- `stale_after`,
- `classification_version`,
- `contract_version`.

### Client-visible after companion projection

Client-visible fields, if Magic Worlds chooses to expose them, must remain product-safe and classified:

- plan/tier display or code,
- normalized entitlement status,
- normalized link status where product-approved,
- renewal/grace/staleness timestamps only when product-approved,
- `external_source="patreon"` or equivalent classified source marker.

Client-visible data must not contain raw Patreon IDs, campaign/tier IDs, emails, signatures, provider payloads, tokens, hash prefixes, fingerprints, audit rows, or secrets.

## Persistence Model

```text
user_external_accounts(provider='patreon')
  │ provider_sub_hash / provider_sub_fingerprint
  │ no per-user provider tokens
  ▼
patreon_link_proofs
  │ hash-only proof lifecycle, expiry, attempts
  ▼
patreon_campaigns + patreon_tier_map
  │ campaign-scoped mappings and priorities
  ▼
patreon_memberships
  │ member/campaign identity by HMAC/fingerprint
  ▼
patreon_member_snapshots + patreon_entitlement_history
  │ append-only normalized evidence
  ▼
patreon_entitlements_current
  │ current safe entitlement projection
  ▼
patreon_webhook_deliveries + patreon_sync_jobs
  │ idempotency and source-of-truth reconciliation
```

Provider-token state, if automatic creator-token refresh is enabled, is global provider state and never per-user external-account state.

## Retention Architecture

| Data bucket | Retention behavior |
| --- | --- |
| Link history, snapshot history, unlink history | Indefinite, privacy-minimized, non-destructive. |
| Proof requests | Purged or irreversibly stripped 24 hours after expiry. |
| Webhook delivery hashes | Purged/anonymized after 90 days. |
| Raw payload quarantine | Disabled by default; encrypted/server-only and purged within 30 days maximum if explicitly enabled. |

Rollback must disable new behavior through flags, ingress controls, worker stop, S2S disablement, and Redis namespace cleanup. It must not destructively delete live link, snapshot, webhook, proof, unlink, or audit history.

## Route and Module Map

| Area | Artifact |
| --- | --- |
| Link request/confirm/status/unlink | `src/routes/auth_patreon.py` |
| Webhook receiver | `src/routes/patreon_webhooks.py` |
| Internal S2S entitlement/resync | `src/routes/internal_patreon.py` |
| Provider config/readiness | `src/Util/patreon/config.py` |
| HMAC/proof/signature/S2S security | `src/Util/patreon/security.py` |
| Creator API client | `src/Util/patreon/client.py` |
| Entitlement classification | `src/Util/patreon/classifier.py` |
| Rate limits | `src/Util/patreon/rate_limit.py` |
| Sync helpers | `src/Util/patreon/sync.py` |
| DB wrappers | `src/Util/db/db_patreon.py` |
| Sync worker | `src/workers/patreon_sync_worker.py` |
| DTO allow-lists | `src/Util/Models.py` |
| Activity catalog | `act-cat-075` through `act-cat-090` |

## Related Documentation

- [Patreon Overview](README.md)
- [Request Flow](request-flow.md)
- [Scenarios](scenarios.md)
- [Reference](reference.md)
- [Troubleshooting](troubleshooting.md)
- [Runbook](../../RUNBOOKS/patreon-link.md)

---

**Document Version**: 1.0
