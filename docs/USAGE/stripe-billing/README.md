# Stripe Billing Usage Guide

Operator and integrator index for the provider-agnostic billing surface in `api.auth`, with Stripe as the first provider adapter.

Stripe is not login authority and never creates local sessions. Mutable provider
facts stay out of JWTs, refresh-token state, Redis session payloads, and browser
cookies. The current identity contract intentionally exposes one narrow,
provider-neutral subscription `plan` projection on project-scoped login,
`/auth/validate`, and consumer API-key validation.

## Quick Navigation

| Document | Purpose |
| --- | --- |
| [Architecture](architecture.md) | Provider-facts boundary, module layout, data flow, status model, encryption/HMAC policy, and Patreon compatibility. |
| [Request Flow](request-flow.md) | Checkout, Portal, webhook ingestion, pull-only reads, purchase reads, resync, free default, and retention flows. |
| [Scenarios](scenarios.md) | Subscribe, upgrade/downgrade, cancel, payment-method update, payment failure/recovery, credit purchase, refund, dispute, stale/unknown, and consumer projection behavior. |
| [Reference](reference.md) | S2S route contracts, safe DTO allow-lists, forbidden fields, normalized statuses, error codes, idempotency, and redaction guarantees. |
| [Troubleshooting](troubleshooting.md) | Redacted operations troubleshooting for signatures, config, decrypt failures, idempotency conflicts, webhook lag, stale snapshots, sync backlog, and Portal readiness. |
| [Runbook](../../RUNBOOKS/stripe-billing.md) | Deploy-disabled rollout, bootstrap checks, sandbox gates, monitoring, incident response, key rotation, retention, rollback, and optional live smoke gates. |

## What This Integration Does

`api.auth` validates Stripe provider evidence, normalizes billing and purchase facts, and exposes those facts only to trusted server-to-server consumers.

The integration supports:

1. billing groups that map one Stripe account and one catalog to one or more projects,
2. an admin API for billing groups, per-group encrypted credentials, capability gates, catalog provisioning/reconciliation/import, and metrics,
3. a public-to-trusted-services catalog read resolved from project to billing group,
4. dedicated billing S2S reads for one `(user_hash, project_hash)` request resolved to group-scoped subscription state,
5. Checkout Session creation from trusted subscription or credit-purchase intent,
6. restricted Customer Portal Session creation for cancellation and payment-method updates,
7. signed Stripe webhook ingestion over exact raw bytes through per-group endpoints plus a global migration fallback,
8. normalized subscription and purchase status snapshots/history,
9. source-of-truth resync through a billing worker,
10. bounded webhook/raw-evidence retention with indefinite normalized history,
11. additive health, metrics, audit, activity, and redaction posture.

`api.auth` owns the product-agnostic billing catalog and Stripe Product/Price
provisioning. It does **not** own product benefits, membership policy, credit
balances, or a credit ledger.

Current limitation: Checkout accepts a trusted S2S caller's `price_ref` and
product labels but does not yet look up and enforce that they match the local
catalog row. Consumers must select them from the S2S catalog; treat server-side
catalog binding as an open hardening item.

## Ownership Boundary

| Owner | Owns | Does not own |
| --- | --- | --- |
| `api.auth` | Billing groups, centralized product-agnostic catalog, per-account encrypted Stripe credentials, Product/Price provisioning, Checkout/Portal calls, webhook verification, provider fact normalization, the neutral session `plan`, S2S DTOs, sync, retention. | Product benefits, membership policy, credit balances/ledgers, browser billing UI. |
| Consuming project | Interpretation of catalog `features`/`credits`, benefits, quotas, membership projection, credit fulfillment/reversal, UI policy, stale/unknown handling. | Stripe secrets, webhook verification, raw provider evidence, catalog persistence/provisioning, `api.auth` sessions. |
| Stripe | External payment platform and signed webhook sender. | Local login/session authority. |

Catalog labels such as `plan_code`, `tier_code`, `tier_name`, and
`credit_product_code` are persisted by `api.auth` but remain opaque product
meaning. Consuming projects interpret them.

## Disabled-by-Default Setup

Every billing switch is default-off. Enable one narrow behavior at a time after the runbook gates pass.

| Switch | Default | Effect |
| --- | --- | --- |
| `BILLING_ENABLED` | `false` | Master generic billing switch. |
| `BILLING_S2S_ENABLED` | `false` | Enables dedicated internal billing reads and action endpoints after S2S token readiness. |
| `BILLING_CHECKOUT_ENABLED` | `false` | Enables Checkout creation when Stripe and crypto readiness pass. |
| `BILLING_PORTAL_ENABLED` | `false` | Enables restricted Portal creation after Portal configuration verification. |
| `BILLING_SYNC_ENABLED` | `false` | Enables billing source-of-truth sync worker behavior. |
| `BILLING_RAW_PAYLOAD_CAPTURE_ENABLED` | `false` | Enables encrypted raw-evidence quarantine only for approved diagnostics. Normal state is off. |
| `STRIPE_BILLING_ENABLED` | `false` | Enables the Stripe provider adapter as part of billing readiness. |
| `STRIPE_WEBHOOKS_ENABLED` | `false` | Enables signed `/webhooks/stripe` processing. |
| `STRIPE_CHECKOUT_ENABLED` | `false` | Enables Stripe Checkout adapter calls. |
| `STRIPE_PORTAL_ENABLED` | `false` | Enables Stripe Customer Portal adapter calls. |
| `STRIPE_SYNC_ENABLED` | `false` | Enables Stripe source-of-truth sync. |

Required server-only setup when enabling the feature:

- dedicated billing S2S bearer token,
- billing HMAC secret for provider refs and idempotency,
- Fernet-compatible provider-ref encryption key plus key id,
- decryption-key map for rotation windows,
- one encrypted Stripe secret key/webhook secret set per billing group (plus an optional per-group Portal configuration id),
- pinned Stripe API version `2026-05-27.dahlia`,
- Checkout/Portal return-origin allow-list,
- restricted Stripe Portal configuration id when Portal is enabled,
- retention windows no looser than 90 days for webhook deliveries and 30 days for encrypted raw quarantine.

Use placeholder examples in docs and tickets only, such as `<billing-s2s-token>`, `<secret-managed-stripe-key>`, and `<fernet-key-from-secret-manager>`. Never paste real values.

## Consumer Overview

A consuming service should use three separate reads:

1. `/auth/validate` for local identity/session validation plus the narrow subscription `plan`.
2. `/internal/projects/{project_hash}/billing/catalog` for the active catalog resolved through the project's billing group.
3. `/internal/users/{user_hash}/billing?...` for detailed provider facts over dedicated S2S bearer auth.

The consuming service then projects the safe billing facts into its own membership and credit model.

```text
Browser / SPA
  │
  ▼
Consuming service
  ├─ validates identity via /auth/validate                  -> identity + neutral subscription plan
  ├─ reads project catalog via billing S2S                  -> plans/packages + opaque features
  ├─ pulls provider facts via billing S2S                   -> normalized facts only
  ├─ maps plan/tier/credit labels in its own product domain -> consumer-owned
  └─ grants/reverses credits in its own idempotent ledger   -> consumer-owned
```

There is no outbound signed callback from `api.auth` to consumers in the MVP. Synchronization is pull-only.

## Explicit No-Login / No-Session Boundary

Stripe Checkout, Portal, webhooks, refunds, disputes, and sync jobs must never issue or mutate local authentication material.

Forbidden Stripe auth concepts:

- Stripe login route,
- Stripe OAuth login callback,
- Stripe-created local session,
- Stripe-derived JWT claims,
- Stripe-derived cookies,
- Stripe-derived refresh-token state,
- mutable Stripe/provider facts in `/auth/validate`.

Mutable billing facts must not be added to:

- JWT claims,
- Redis session payloads,
- refresh-token family state,
- browser cookies,
- registration or switch-project responses.

The allowed exception is `SessionPlanStatus`: a small subscription-only
projection (`none|free|trial|active|past_due|canceled`, opaque plan/tier labels,
period/trial end, cancellation flag). It is resolved from the current project
and is not authentication authority. Current refresh and switch-project response
bodies omit it; clients can validate the new access token to read it.

## Route Summary

| Route | Audience | Purpose |
| --- | --- | --- |
| `GET /internal/projects/{project_hash}/billing/catalog` | Trusted internal S2S consumer | Read active subscription plans and credit packages for the project's billing group. |
| `GET /internal/users/{user_hash}/billing?project_hash=...` | Trusted internal S2S consumer | Read current project-scoped billing facts. Missing state returns safe free default. |
| `POST /internal/users/{user_hash}/billing/checkout` | Trusted internal S2S consumer | Create Checkout from consumer-owned subscription or credit-purchase intent. |
| `POST /internal/users/{user_hash}/billing/portal` | Trusted internal S2S consumer | Create restricted Portal Session for cancellation/payment-method updates. |
| `GET /internal/users/{user_hash}/billing/purchases/{purchase_ref}?project_hash=...` | Trusted internal S2S consumer | Read normalized purchase fact for consumer-owned fulfillment/reversal decisions. |
| `POST /internal/users/{user_hash}/billing/resync` | Trusted internal S2S consumer/operator flow | Queue source-of-truth provider resync. |
| `POST /webhooks/stripe/{billing_group_hash}` | Stripe webhook sender | Preferred multi-account endpoint; selects exactly one group's signing secret. |
| `POST /webhooks/stripe` | Stripe webhook sender | Global-secret single-account/migration fallback. |
| `/admin/billing...` | Admin/manage_billing; credential writes root-only | Manage groups/projects/capabilities/catalog/metrics and write-only encrypted credentials. |

All internal billing routes require `Authorization: Bearer <billing-s2s-token>` and `User-Agent`. Browser cookies, local session headers, user JWTs, and regular API keys are not authority for these endpoints.

## Retention Summary

| Artifact | Retention |
| --- | --- |
| Stripe webhook delivery ledger | 90 days. |
| Encrypted raw payload/evidence quarantine | Disabled by default; max 30 days when explicitly enabled. |
| Normalized billing status history | Indefinite. |
| Normalized purchase history | Indefinite. |
| Encrypted operational refs | Retained only while provider operations require them, then purged/rotated per runbook while HMAC/history remain. |

Indefinite history does not mean indefinite raw provider payload retention. Long-term records must remain normalized or redacted.

## Related Boundaries

- Existing Patreon routes, schema, DTOs, and runbook remain compatible and separate.
- Each billing group owns one Stripe account and one catalog. Subscription facts/customers are group-scoped; credit purchases retain project scope.
- Subscription upgrades/downgrades go through consumer-owned Checkout intent. Customer Portal plan changes are disabled.
- One-time credit purchases expose purchase facts only; consuming projects own credit fulfillment and reversal.

---

**Document Version**: 1.0
