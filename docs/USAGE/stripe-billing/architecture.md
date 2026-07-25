# Stripe Billing Architecture

Provider-agnostic billing adds a dedicated provider-facts boundary beside the identity/session system. Stripe is the first adapter, but the MVP still keeps the generic core intentionally small.

The important concept is simple: **billing is not authentication**. `api.auth` validates provider facts and exposes safe server-to-server facts; consuming projects decide product membership and credits.

`api.auth` is also the **centralized source of truth for the per-project billing catalog**, while staying agnostic of product meaning (catalog rows carry opaque `features`/`metadata` JSON it never interprets). Billing is owned by a **billing group** — one Stripe account + one catalog — that can span multiple projects; a standalone project is a group of one. A neutral subscription `plan` object is projected into `/auth/validate`/login/validate-api-key for the session's project.

## Architectural Decisions

| Decision | Why |
| --- | --- |
| Billing facts live behind dedicated S2S routes | Mutable financial/provider state must not be embedded in JWTs, cookies, Redis sessions, or login DTOs. The only identity projection is a neutral subscription `plan` object on `/auth/validate` (state + plan_code/tier_code/expiry; subscriptions only). |
| Billing group is the billing unit | One group owns one Stripe account (credentials encrypted in the DB) + one catalog and maps to ≥1 project. Facts are keyed by `(user, billing_group, provider)` so one subscription covers all of a group's projects; credit purchases keep both `project_id` and `billing_group_id`. |
| Generic `billing_*` persistence is additive | Existing Patreon artifacts remain compatible. Stripe billing does not destructively generalize or rename `patreon_*` tables/routes. |
| Per-account Stripe under one organization | Each billing group has its own standalone Stripe account; its secret + webhook secret are stored as Fernet ciphertext per group and selected at request time. Webhooks are path-scoped (`/webhooks/stripe/{billing_group_hash}`). |
| api.auth owns the catalog and provisions Stripe | Creating a plan/package writes the catalog row and provisions the Stripe `Product`+`Price` on the group's account. Prices are immutable, so a price change creates a new `Price` and archives the old. |
| api.auth stays agnostic of product meaning | Catalog `features`/`metadata` are opaque passthrough; consumers interpret credits/limits. |
| Consumers own projection | Benefits, quotas, memberships, credit balances, and credit ledgers are product-domain concerns; consumers read the catalog (`GET /internal/projects/{project_hash}/billing/catalog`) and the `plan` rather than hard-coding them. |
| Raw operational provider refs are encrypted only when required | Some provider operations need server-side refs. They stay encrypted at rest, decrypted only in memory, and never appear in DTOs/logs/audit/metrics. |
| HMAC/fingerprints are support/idempotency internals | Non-reversible companions support joins, dedupe, and redacted operations. They are not exposed to consumers in the MVP. |
| Checkout handles subscribe/upgrade/credit purchase; Portal is restricted | Customer Portal is limited to cancellation/payment-method maintenance. Plan changes require consumer-owned Checkout intent. |
| Webhooks are verified before mutation | Exact raw request bytes and the Stripe signature are verified before parsing/trusting event content. |
| Consumer sync is pull-only | `api.auth` does not push outbound callbacks in the MVP. Consumers call S2S reads when they need current facts. |

## Ownership Split

| Owner | Responsibilities |
| --- | --- |
| `api.auth` | Billing groups + per-account encrypted Stripe credentials, the centralized product-agnostic catalog and its Stripe `Product`/`Price` provisioning, the dedicated S2S boundary, Stripe Checkout/Portal calls, webhook verification, provider fact normalization, the `plan` projection on validation, encrypted operational refs, HMAC/fingerprint companions, idempotency, sync jobs, retention, redacted audit/activity/metrics/health. |
| Stripe | External payment processor and signed webhook sender (one account per billing group, under one Stripe Organization). |
| Consuming project | Benefit/quota rules, membership projection, credit fulfillment and ledgers, UI copy, stale/unknown policy; interprets opaque catalog `features`/`credits` it reads back. Admins manage groups/catalog/credentials via the dashboard (`/admin/billing`). |
| Browser/SPA | Interacts with the consuming project. It should not call billing S2S endpoints directly and should not receive raw provider evidence. |

## High-Level System Diagram

```text
Browser / SPA
  │
  ▼
Consuming service / BFF
  ├─ identity call: /auth/validate ───────────────▶ api.auth identity routes
  │                                                   identity + neutral `plan` object
  │
  ├─ catalog read: GET /internal/projects/{p}/billing/catalog ▶ api.auth (per-project,
  │                                                   resolved project → billing group)
  │
  ├─ billing S2S calls ───────────────────────────▶ api.auth billing routes
  │                                                   safe provider facts only
  │                                                   Checkout/Portal creation (group acct)
  │                                                   purchase-status read
  │
  ├─ local product projection ─────────────────────▶ consumer membership tables
  │                                                   consumer credit ledger
  │
  └─ browser response ─────────────────────────────▶ product-safe fields only

Admin dashboard ── /admin/billing (groups, catalog, credentials) ▶ api.auth admin routes

Stripe API ─────── per-group Checkout/Portal/Product/Price/source-of-truth ◀── api.auth adapter
Stripe webhooks ── signed exact raw body ───────────────────▶ /webhooks/stripe/{billing_group_hash}
                   (legacy single-account fallback: /webhooks/stripe)
```

## Module Layout

| Area | Artifact |
| --- | --- |
| Route wiring | `src/main.py`, `src/routes/__init__.py` |
| Admin billing routes | `src/routes/admin_billing.py` |
| Billing S2S routes | `src/routes/internal_billing.py` |
| Stripe webhook routes | `src/routes/stripe_webhooks.py` |
| Session plan projection | `src/Util/session_plan.py` |
| Billing config/readiness | `src/Util/billing/config.py` |
| Billing security | `src/Util/billing/security.py` |
| Billing idempotency | `src/Util/billing/idempotency.py` |
| Billing status model | `src/Util/billing/status.py` |
| Billing redaction | `src/Util/billing/redaction.py` |
| Billing sync helpers | `src/Util/billing/sync.py` |
| Stripe config/readiness | `src/Util/stripe/config.py` |
| Stripe client adapter | `src/Util/stripe/client.py` |
| Per-group account selection | `src/Util/stripe/account.py` |
| Credential validation | `src/Util/stripe/credentials.py` |
| Catalog provisioning/reconcile | `src/Util/stripe/provisioning.py`, `src/Util/stripe/catalog_sync.py` |
| Checkout adapter | `src/Util/stripe/checkout.py` |
| Portal adapter | `src/Util/stripe/portal.py` |
| Webhook verifier | `src/Util/stripe/webhooks.py` |
| Event classifier | `src/Util/stripe/classifier.py` |
| Source-of-truth sync | `src/Util/stripe/sync.py` |
| Rate limits | `src/Util/stripe/rate_limit.py` |
| DB wrappers | `src/Util/db/db_billing.py` |
| Sync worker | `src/workers/billing_sync_worker.py` |
| Tables | `schemas/tables/12_billing_provider_facts.sql` |
| Procedures | `schemas/stored_procedures/17_billing_provider_facts.sql`, `18_billing_groups.sql` |
| Triggers | `schemas/triggers/07_billing_provider_facts_triggers.sql` |
| Bootstrap | `scripts/migrations/billing_provider_bootstrap.py`, `billing_group_bootstrap.py` |
| DTO allow-lists | `src/Util/Models.py` |
| Activity catalog | `act-cat-091` through `act-cat-106` |

## Route Surface

All S2S billing routes require the dedicated billing bearer token, `User-Agent`, route-local rate limits, constant-time token validation, and no browser/session fallback.

| Method | Path | Purpose | Response model |
| --- | --- | --- | --- |
| `GET` | `/internal/projects/{project_hash}/billing/catalog` | Resolve project → billing group and return active plans/packages. Missing group/catalog returns empty lists. | `PublicCatalogResponse` |
| `GET` | `/internal/users/{user_hash}/billing?project_hash=...&provider=stripe` | Read current billing facts. Missing row returns project-scoped free default. | `BillingS2SResponse` |
| `POST` | `/internal/users/{user_hash}/billing/checkout` | Create Checkout from consumer-owned intent. | `BillingCheckoutSessionResponse` |
| `POST` | `/internal/users/{user_hash}/billing/portal` | Create restricted Portal Session. | `BillingPortalSessionResponse` |
| `GET` | `/internal/users/{user_hash}/billing/purchases/{purchase_ref}?project_hash=...&provider=stripe` | Read a normalized purchase fact. | `BillingPurchaseStatusResponse` |
| `POST` | `/internal/users/{user_hash}/billing/resync` | Queue source-of-truth provider resync. | `BillingResyncAcceptedResponse` |
| `POST` | `/webhooks/stripe/{billing_group_hash}` | Preferred per-account webhook; verify with exactly that group's secret. | Neutral accepted/rejected JSON |
| `POST` | `/webhooks/stripe` | Global-secret single-account/migration fallback. | Neutral accepted/rejected JSON |

The session `plan` projection is returned by project-scoped consumer login,
`/auth/validate`, and consumer API-key validation. It is deliberately not stored
in JWT/cookie/Redis auth state. Current refresh and switch-project responses omit
it; validate the newly issued access token when a client needs the projection.

The separate `/admin/billing` surface registers 22 operations for group CRUD,
project attachment, capability gates, root-only credentials, catalog
CRUD/archive/reconcile/sync/import, and aggregate metrics. See
[reference.md](reference.md#admin-billing-contracts).

## Data Flow

### Checkout Session Creation

```text
Consumer service
  │ POST /internal/users/{user_hash}/billing/checkout
  │ Authorization: Bearer <billing-s2s-token>
  │ body: project_hash, intent_type, price_ref, labels, return URLs
  ▼
internal_billing.py
  │ verify dedicated S2S bearer and User-Agent
  │ validate project scope and return URL allow-list
  │ derive internal idempotency key and opaque refs
  │ resolve project -> billing group
  │ resolve/create one customer per (user, billing group, provider)
  ▼
Stripe adapter
  │ use that billing group's decrypted-in-memory Stripe secret + pinned API version
  │ stamp safe metadata with opaque api.auth refs only
  ▼
Consumer service
  │ hosted Checkout URL + opaque checkout_ref / purchase_ref / subscription_ref
```

### Webhook Ingestion

```text
Stripe
  │ POST /webhooks/stripe/{billing_group_hash}
  │ Stripe-Signature header + exact raw bytes
  ▼
stripe_webhooks.py
  │ read raw bytes before parsing
  │ verify signature and timestamp tolerance
  │ reject invalid signatures before mutation
  │ record privacy-preserving delivery ledger
  │ ignore unsupported events without mutation
  │ classify approved events into normalized facts
  │ enqueue source-of-truth resync when evidence is partial/out-of-order
  ▼
billing_* persistence
  │ current snapshot + append-only normalized history
```

### Pull-Only Consumer Projection

```text
Consumer request lifecycle
  1. Validate local identity and read the neutral subscription plan from /auth/validate.
  2. Pull the billing-group catalog through S2S.
  3. Pull detailed billing/purchase facts through S2S when product policy needs them.
  4. Interpret opaque plan/tier/feature/credit labels locally.
  5. Project membership and benefits locally.
  6. Fulfill/reverse credits in the consumer ledger only.
```

## Persistence Model

```text
billing_providers
  │
  └─ billing_groups                     one Stripe account + catalog
       ├─ billing_group_projects        each project belongs to at most one active group
       └─ billing_catalog_items         plans/packages; opaque features/metadata
              │
              ▼
billing_customers                       one provider customer per (user, billing group, provider)
  │
  ├─ billing_checkout_intents           consumer-owned intent + idempotency
  ├─ billing_subscriptions              provider subscription operational refs
  │    ├─ billing_subscription_snapshots append-only observations
  │    ├─ billing_entitlements_current  current safe S2S read model
  │    └─ billing_entitlement_history   indefinite normalized history
  ├─ billing_purchase_events            current one-time purchase facts
  │    └─ billing_purchase_history      indefinite normalized purchase history
  ├─ billing_webhook_deliveries         90-day delivery ledger
  ├─ billing_sync_jobs                  source-of-truth repair queue
  └─ billing_raw_payload_quarantine     encrypted, disabled by default, max 30 days
```

## Status Model

### Subscription statuses

| Status | Meaning |
| --- | --- |
| `free` | Billing-group-scoped safe default or no paid current fact. |
| `pending` | Checkout or provider transition is not yet final. |
| `incomplete` | Provider evidence indicates incomplete subscription setup. |
| `trialing` | Provider indicates trial state; consumer decides trial benefits. |
| `active` | Provider evidence supports active subscription fact. |
| `past_due` | Payment failure or subscription evidence indicates past-due status. |
| `unpaid` | Provider evidence indicates unpaid status. |
| `paused` | Provider evidence indicates paused status. |
| `canceled` | Provider evidence indicates cancellation. |
| `former` | Historical paid relationship exists but current paid access is not active. |
| `stale` | Fresh source-of-truth confirmation is overdue. |
| `unknown` | Evidence is incomplete, mismatched, or unsafe to classify. |

### Purchase statuses

| Status | Meaning |
| --- | --- |
| `pending` | Checkout intent exists, but paid evidence is not final. |
| `paid` | Provider evidence supports paid one-time purchase fact. |
| `refunded` | Provider evidence supports full refund fact. |
| `partially_refunded` | Provider evidence supports partial refund fact. |
| `disputed` | Provider evidence supports active dispute fact. |
| `dispute_won` | Provider evidence supports dispute won fact. |
| `dispute_lost` | Provider evidence supports dispute lost fact. |
| `stale` | Purchase evidence needs source-of-truth refresh. |
| `unknown` | Purchase evidence is unsafe or incomplete. |

`api.auth` never decides product-specific grace, benefits, quotas, or credit amounts from these statuses.

## Encryption / HMAC / Fingerprint Policy

Rules:

1. Raw Stripe operational refs are stored encrypted only when required for provider operations.
2. Decryption occurs only in memory inside server-side provider operations.
3. HMAC digests and 12-hex fingerprints support joins, idempotency, redacted support correlation, and uniqueness.
4. Consumer DTOs do not include raw provider refs, HMAC digests, fingerprints, secrets, signatures, raw payloads, payment-method details, or receipt links.
5. Missing decrypt keys make Checkout/Portal/sync fail closed for the affected operation.
6. Rotation keeps old decrypt keys available until no rows require them and rollback windows expire.

## Health and Metrics

Billing health is additive. Disabled or not-ready billing must not degrade unrelated local auth/session health.

Expected components:

- `billing`,
- `billing_provider_stripe`,
- `billing_webhooks`,
- `billing_sync`.

Safe signals include provider readiness, SDK/API version labels, missing config key names, webhook signature failure counts, webhook lag, duplicate events, idempotency conflicts, stale snapshots, sync backlog, decrypt failures, retention health, and worker heartbeat. Metrics must not use raw provider refs or consumer-owned credit amounts as labels.

## Patreon Compatibility Notes

Existing Patreon behavior remains separate and compatible:

- no destructive `patreon_*` schema migration,
- no forced migration of Patreon consumers to billing S2S,
- no change to existing Patreon S2S/webhook DTOs,
- no change to Patreon retention posture,
- no weakening of Patreon no-login boundaries.

Stripe billing borrows the operational posture from Patreon: default-off flags, exact raw-body webhook verification, safe S2S DTOs, redacted audit/activity, source-of-truth resync, bounded raw payload retention, and non-destructive rollback.

## Related Documentation

- [Overview](README.md)
- [Request Flow](request-flow.md)
- [Scenarios](scenarios.md)
- [Reference](reference.md)
- [Troubleshooting](troubleshooting.md)
- [Runbook](../../RUNBOOKS/stripe-billing.md)

---

**Document Version**: 1.0
