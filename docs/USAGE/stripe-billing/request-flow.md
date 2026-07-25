# Stripe Billing Request Flow

This document describes request flows for provider-agnostic billing with Stripe in `api.auth`.

Stripe is not local authentication authority and does not create sessions.
Provider facts stay out of JWTs, refresh-token state, Redis session payloads,
and browser cookies. Project-scoped identity responses expose only the
subscription-only `SessionPlanStatus` projection.

## Route Map

| Flow | Route | Caller | Authority |
| --- | --- | --- | --- |
| Catalog read | `GET /internal/projects/{project_hash}/billing/catalog` | Consuming service | Dedicated billing S2S bearer |
| Billing read | `GET /internal/users/{user_hash}/billing` | Consuming service | Dedicated billing S2S bearer |
| Checkout | `POST /internal/users/{user_hash}/billing/checkout` | Consuming service | Dedicated billing S2S bearer + idempotency |
| Portal | `POST /internal/users/{user_hash}/billing/portal` | Consuming service | Dedicated billing S2S bearer + restricted Portal readiness |
| Purchase read | `GET /internal/users/{user_hash}/billing/purchases/{purchase_ref}` | Consuming service | Dedicated billing S2S bearer |
| Resync | `POST /internal/users/{user_hash}/billing/resync` | Consuming service / operator S2S | Dedicated billing S2S bearer |
| Group webhook | `POST /webhooks/stripe/{billing_group_hash}` | Stripe | That billing group's Stripe signing secret |
| Global webhook fallback | `POST /webhooks/stripe` | Stripe | Global migration signing secret |
| Administration | `/admin/billing...` | Admin/root dashboard | Access session; credential mutations ROOT-only |

Browser cookies, user JWTs, and `/auth/validate` output are not authority for billing S2S.

## 1. Checkout Flow

Checkout creates a hosted Stripe session from trusted S2S intent. The consumer
owns product choice/benefit interpretation; `api.auth` owns catalog persistence
and server-side provider execution.

```text
Consumer service
  │ POST /internal/users/{user_hash}/billing/checkout
  │ Authorization: Bearer <billing-s2s-token>
  │ Idempotency-Key: <consumer-idempotency-ref>
  │ body: project_hash, intent_type, price_ref, consumer labels, return URLs
  ▼
api.auth internal_billing route
  │ validate dedicated bearer and User-Agent
  │ reject browser/session/JWT fallback
  │ validate return URL origin allow-list
  │ resolve user/project -> billing group scope
  │ begin idempotency record
  │ create opaque checkout_ref and optional subscription_ref / purchase_ref
  ▼
Stripe adapter
  │ get/create billing-group-scoped customer using encrypted operational ref
  │ use that group's Stripe account credentials
  │ call Stripe Checkout with pinned API version
  │ stamp safe metadata with opaque api.auth refs and consumer-owned labels
  ▼
Consumer service
  │ receives hosted URL + opaque refs only
  │ redirects browser through its own UX
```

### Checkout rules

- `intent_type="subscription"` requires `plan_code` and `tier_code` as consumer-owned labels.
- `intent_type="credit_purchase"` requires `credit_product_code` as consumer-owned evidence.
- `price_ref` is request-only and must come from the trusted catalog selector
  (normally `provider_price_lookup_key`); it must not be logged or returned.
- The route currently validates the request shape but does not bind
  `price_ref`/labels back to a local catalog row. The trusted caller must source
  them from `GET /internal/projects/{project_hash}/billing/catalog`.
- Same idempotency key + same canonical request returns the prior safe result.
- Same idempotency key + different canonical request returns a neutral conflict.
- The response returns only hosted URL plus opaque local refs.
- Checkout completion does not issue local sessions or grant product credits by itself.

## 2. Customer Portal Flow

Portal is S2S-only and MVP-limited.

```text
Consumer service
  │ POST /internal/users/{user_hash}/billing/portal
  │ Authorization: Bearer <billing-s2s-token>
  │ body: project_hash, return_url
  ▼
api.auth internal_billing route
  │ validate dedicated bearer and User-Agent
  │ validate return URL origin allow-list
  │ resolve project -> billing group -> billing customer
  │ load that group's Portal configuration
  │ verify Portal configuration readiness
  ▼
Stripe adapter
  │ create restricted Portal Session
  ▼
Consumer service
  │ receives hosted Portal URL + opaque portal_ref only
```

### Portal rules

- Portal may allow cancellation and payment-method maintenance.
- Portal plan changes, upgrades, downgrades, and subscription item changes are disabled for MVP.
- If the configured Portal cannot be verified as restricted, Portal creation fails closed.
- Plan changes must flow through consumer-owned Checkout intent.

## 3. Webhook Ingestion Flow

Stripe webhooks are the fast path for provider-fact updates. Verification precedes trust.

```text
Stripe
  │ POST /webhooks/stripe/{billing_group_hash}
  │ Stripe-Signature + exact raw body
  ▼
api.auth stripe_webhooks route
  │ read raw bytes before JSON parsing
  │ verify signature and timestamp tolerance
  │ reject invalid signatures before mutation
  │ ensure Stripe config/readiness is not fail-closed
  │ record delivery ledger by privacy-preserving evidence
  ├─ duplicate delivery → 200 accepted/no-op
  ├─ unsupported signed event → 200 ignored/no mutation
  ├─ complete approved event → normalize and persist current/history
  └─ partial/out-of-order/destructive uncertainty → enqueue source-of-truth resync
```

### Webhook rules

- Body normalization, whitespace changes, reserialization, or parsing before verification must not be trusted.
- Invalid signatures reject before billing or purchase mutation.
- Unsupported event types are safe no-ops.
- Duplicate deliveries do not repeat side effects.
- Raw webhook body is excluded from unsafe audit capture.
- Raw signatures, raw payloads, provider secrets, and provider refs are never logged or returned.
- The global `/webhooks/stripe` route is a single-account migration fallback;
  normal multi-account delivery uses the path-scoped route and a single
  deterministic secret lookup.

## 4. Pull-Only Billing Read Flow

Consumers pull current billing facts when they need to project membership.

```text
Consumer service
  │ validates user identity and reads neutral plan through /auth/validate
  │ reads project catalog through /internal/projects/{project_hash}/billing/catalog
  │
  │ GET /internal/users/{user_hash}/billing?project_hash=<project-hash>
  │ Authorization: Bearer <billing-s2s-token>
  ▼
api.auth billing S2S route
  │ validate dedicated bearer and User-Agent
  │ resolve project -> billing group
  │ read current billing snapshot by user/group/provider
  │ synthesize free default if no billing row exists
  ▼
Consumer service
  │ projects plan/tier/status into local membership policy
```

### Pull-only rules

- No outbound signed callback is sent from `api.auth` to consumers in the MVP.
- No current row returns a project-scoped `free` default.
- Project A billing state must never leak into project B reads.
- Consumers decide stale/unknown behavior locally.
- `/auth/validate` exposes only the neutral subscription `plan`; detailed facts
  and purchase state remain S2S-only.

## 5. Purchase Read Flow

One-time credit purchases are facts only. `api.auth` does not own credit fulfillment.

```text
Consumer service
  │ GET /internal/users/{user_hash}/billing/purchases/{purchase_ref}?project_hash=<project-hash>
  │ Authorization: Bearer <billing-s2s-token>
  ▼
api.auth billing S2S route
  │ validate dedicated bearer and User-Agent
  │ read normalized purchase fact
  ▼
Consumer service
  │ if status=paid, fulfill credits in its own idempotent ledger
  │ if refund/dispute status appears, apply product-owned reversal/hold policy
```

### Purchase rules

- `paid` is a provider fact, not an automatic credit grant.
- `refunded`, `partially_refunded`, `disputed`, `dispute_won`, and `dispute_lost` are provider facts only.
- Credit amounts, balances, ledger entries, and reversal decisions belong to the consuming project.

## 6. Resync Flow

Resync repairs partial, stale, out-of-order, or disputed provider evidence through a worker.

```text
Consumer/operator S2S
  │ POST /internal/users/{user_hash}/billing/resync
  │ body: project_hash, reason?, force?
  ▼
api.auth route
  │ validate dedicated bearer and rate limits
  │ enqueue billing_sync_jobs with redacted metadata
  ▼
src/workers/billing_sync_worker.py
  │ claim/lease jobs
  │ dispatch Stripe source-of-truth read first
  │ decrypt operational refs only in memory
  │ complete/retry/fail with redacted reason
  │ optionally run bounded retention purge cadence
```

### Resync rules

- Sync jobs never mutate local sessions or consumer-owned product ledgers.
- Decrypt failures are fail-closed and redacted.
- Provider outages retry/back off and preserve last safe state as stale or unknown.
- Worker heartbeats and counters use billing-specific Redis prefixes only.

## 7. Free-Default Flow

When an authorized consumer reads a valid user/project with no current billing row, `api.auth` returns a safe default.

```text
No billing row for (user, billing group, provider)
  ▼
GET /internal/users/{user_hash}/billing?project_hash=<project-hash>
  ▼
BillingSafeStatus(status="free", plan_code="free", link_status="none")
```

### Free-default rules

- The request is project-scoped, while the subscription default is resolved
  through the project's billing group.
- Free default does not imply a product benefit.
- Free default does not expose historical provider records.
- Free default does not grant credits.

## 8. Retention Flow

Billing retention is bounded for sensitive operational evidence and durable for normalized history.

```text
billing_sync_worker retention pass
  │
  ▼
sp_billing_retention_purge
  ├─ purge webhook delivery ledger after 90 days
  ├─ purge encrypted raw quarantine within 30 days
  └─ preserve normalized billing and purchase history indefinitely
```

### Retention rules

- Raw payload quarantine is disabled by default.
- Retention purge is not a mechanism to erase normalized billing history.
- Incident evidence must stay redacted and preserved according to policy.

## 9. Failure and Rollback Flow Summary

| Condition | Flow behavior |
| --- | --- |
| Billing disabled | Billing health reports disabled; auth/session health remains independent. |
| Missing/inactive group Stripe credentials | Stripe actions for that billing group fail closed with neutral errors. |
| SDK/API mismatch | Stripe provider readiness is not-ready; no provider mutation. |
| Invalid webhook signature | Reject before mutation and record redacted failure evidence. |
| Portal config unverified | Portal creation fails closed. |
| Decrypt failure | Affected provider operation fails closed; sync records redacted failure. |
| Rollback | Disable flags, block webhook ingress, stop worker, preserve schema/history/evidence. |

## Related Documentation

- [Overview](README.md)
- [Architecture](architecture.md)
- [Scenarios](scenarios.md)
- [Reference](reference.md)
- [Troubleshooting](troubleshooting.md)
- [Runbook](../../RUNBOOKS/stripe-billing.md)

---

**Document Version**: 1.0
