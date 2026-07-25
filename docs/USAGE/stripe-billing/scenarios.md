# Stripe Billing Scenarios

This document describes expected behavior for common and failure scenarios in provider-agnostic billing with Stripe.

Stripe billing is **provider-facts only**. It is not local authentication authority and must not issue local sessions, access tokens, refresh tokens, browser cookies, or API keys.

## Scenario Matrix

| Scenario | Expected posture |
| --- | --- |
| Subscribe | Consumer sends product-owned intent; `api.auth` creates Checkout and later exposes normalized provider facts. |
| Upgrade/downgrade | Consumer decides the product change and initiates Checkout; Portal plan changes remain disabled. |
| Cancellation | Portal may initiate cancellation; verified provider evidence updates normalized status only. |
| Payment-method update | Portal may allow payment-method maintenance; no product membership mutation occurs in `api.auth`. |
| Payment failure/recovery | Provider evidence becomes `past_due`/`unpaid` or returns to `active`/`trialing`; consumer decides grace policy. |
| One-time credit purchase | Purchase status may become `paid`; consumer fulfills credits in its own idempotent ledger. |
| Refund | Purchase status updates; consumer decides product-owned reversal. |
| Dispute | Purchase status updates; consumer decides hold/reversal policy. |
| Stale/unknown | `api.auth` labels facts stale/unknown and may enqueue resync; consumer applies local safe policy. |
| Consumer projection | Consumer reads the `api.auth` catalog and maps its opaque labels/features plus provider statuses into product membership and credits. |
| Rollback | Disable behavior non-destructively and preserve normalized history/evidence. |

## 1. Subscribe Through Checkout

### Given

- The consumer has authenticated the user through its normal identity flow.
- The consumer selected an active subscription from
  `GET /internal/projects/{project_hash}/billing/catalog` and interprets its
  opaque labels/features under product-owned policy.
- The consumer calls `POST /internal/users/{user_hash}/billing/checkout` with dedicated S2S bearer auth.

### Expected behavior

- `api.auth` validates S2S authority, project scope, return URL origin, and idempotency.
- `api.auth` resolves project → billing group and creates or reuses one Stripe
  Customer scoped to `(user, billing group)`.
- `api.auth` creates a Stripe Checkout Session using that group's encrypted
  credentials and the pinned API version.
- The response contains a hosted URL plus opaque local refs only.
- Later verified provider events update normalized billing facts and append history.

### Must not happen

- Do not add detailed provider/purchase facts to `/auth/validate`; only the
  narrow subscription `plan` projection belongs there.
- Do not issue local sessions from Checkout completion.
- Do not store or expose product benefits or quotas in `api.auth`.
- Do not return raw provider refs to the consumer.

## 2. Upgrade or Downgrade Through Checkout

### Given

- The consuming project decides, under its own rules, that a user may upgrade or downgrade.
- The consumer sends a new Checkout intent using the selected catalog lookup
  key and opaque plan/tier labels.

### Expected behavior

- `api.auth` treats the labels and price selector as evidence, not canonical product meaning.
- Checkout is created through the same S2S idempotent path.
- The new billing state is exposed only after allowed provider evidence is verified and normalized.
- The consumer projects the resulting status into local membership.

### Must not happen

- Do not use Customer Portal plan changes for MVP upgrades/downgrades.
- Do not infer a plan from provider price text inside `api.auth`.
- Do not let a provider event without matching consumer-owned evidence create paid product meaning.

## 3. Cancellation

### Given

- A user requests cancellation through the consuming project UX.
- The consumer calls `POST /internal/users/{user_hash}/billing/portal`.
- Portal configuration is verified as restricted.

### Expected behavior

- `api.auth` returns a hosted Portal URL and opaque `portal_ref`.
- Provider events later update `cancel_at_period_end`, `canceled`, `former`, `free`, `stale`, or `unknown` according to verified evidence.
- Cancellation at period end may preserve active provider fact until the effective period ends.
- The consumer decides UI and access policy.

### Must not happen

- Do not revoke local auth sessions because of cancellation.
- Do not mutate consumer membership tables directly.
- Do not expose raw provider evidence in cancellation responses/logs.

## 4. Payment-Method Update

### Given

- A user needs to update the payment method for the customer resolved through
  the project's billing group.
- The consumer requests a Portal Session.

### Expected behavior

- Portal creation uses the same dedicated S2S authority and return URL checks.
- The response includes only a hosted URL and opaque local ref.
- Future provider events update normalized facts if payment recovery or failure occurs.

### Must not happen

- Do not allow Portal plan changes as a side effect.
- Do not expose payment-method details, card fields, receipt links, secrets, or raw provider refs.

## 5. Payment Failure and Recovery

### Given

- Provider evidence indicates a subscription payment failed or recovered.

### Expected behavior

- Failure evidence normalizes to `past_due`, `unpaid`, `stale`, or `unknown` as appropriate.
- Recovery evidence normalizes back to `active`, `trialing`, or another supported safe status.
- Transitions append normalized history.
- The consumer decides product grace, downgrade, lockout, or retry UX.

### Must not happen

- Do not grant new paid access solely from unavailable provider confirmation.
- Do not define consumer-specific grace benefits in `api.auth`.
- Do not change local session validity because payment failed.

## 6. One-Time Credit Purchase

### Given

- The consumer selects an active credit package from the project catalog and
  sends `intent_type="credit_purchase"` with its lookup key/product code.
- Provider evidence later confirms Checkout completion.

### Expected behavior

- `api.auth` records normalized purchase status `paid` for the opaque `purchase_ref`.
- The consumer reads that purchase status through S2S.
- The consumer grants credits in its own idempotent ledger.

### Must not happen

- `api.auth` may expose catalog `credits`/amount/features, but it must not store
  the user's credit balance or fulfillment ledger.
- Do not mutate product-owned credit balances.
- Do not fulfill credits directly from a webhook in `api.auth`.

## 7. Refund

### Given

- Provider evidence indicates a full or partial refund for a purchase.

### Expected behavior

- Purchase fact updates to `refunded` or `partially_refunded` when evidence supports it.
- Purchase history appends the transition.
- The consumer decides whether and how to reverse credits.

### Must not happen

- Do not write negative credits, wallet reversals, or accounting entries in `api.auth`.
- Do not expose provider payment details to the consumer.

## 8. Dispute

### Given

- Provider evidence indicates a dispute was opened or closed.

### Expected behavior

- Purchase fact updates to `disputed`, `dispute_won`, or `dispute_lost` according to normalized evidence.
- The consumer applies product-specific hold, release, or reversal policy.
- Source-of-truth resync may run if evidence is partial or out of order.

### Must not happen

- Do not mutate product credits in `api.auth`.
- Do not expose raw provider dispute evidence outside redacted operations.

## 9. Stale or Unknown Billing Facts

### Given

- Provider source-of-truth validation is unavailable, old, conflicting, or incomplete.

### Expected behavior

- Billing or purchase facts are labeled `stale` or `unknown` rather than guessed.
- Source-of-truth resync may be enqueued.
- Existing last-known state remains visible with freshness metadata when safe.
- The consumer applies local fallback/grace/restriction policy.

### Must not happen

- Do not hide freshness problems by returning active as fresh.
- Do not invent product meaning from raw provider labels.
- Do not add detailed or mutable provider facts to auth state as a shortcut;
  the small `plan` projection is the only allowed identity response.

## 10. Consumer Projection

### Given

- The consumer receives the centralized catalog, normalized billing status,
  opaque labels/features, and purchase facts over S2S.

### Expected behavior

- The consumer maps those facts into its own membership table, benefits, quotas, UI response, credit balance, and ledger.
- The consumer uses local idempotency for credit fulfillment/reversal.
- The consumer treats `stale`/`unknown` according to product risk policy.

### Must not happen

- `api.auth` owns catalog persistence and Stripe Product/Price provisioning;
  do not ask it to interpret benefits/quotas or own credit balances/ledgers.
- Do not pass raw provider evidence through to browsers.
- Do not confuse `plan_code`/`tier_code` evidence with canonical product authority inside `api.auth`.

## 11. Rollback Behavior

### Given

- Billing records, purchase history, webhook delivery rows, encrypted operational refs, or audit/activity evidence may exist.
- Operators need to roll back Stripe billing behavior.

### Expected behavior

Rollback is non-destructive:

1. Disable Checkout, Portal, webhooks, and sync flags first.
2. Disable generic billing flags as needed.
3. Block `/webhooks/stripe` at ingress if deliveries must stop immediately.
4. Stop `src/workers/billing_sync_worker.py`.
5. Clear only billing/Stripe Redis namespaces when approved.
6. Preserve normalized billing history, purchase history, encrypted refs required for evidence, webhook delivery rows still within retention, audit/activity evidence, and raw quarantine until retention says purge.

### Must not happen

- Do not drop additive billing schema in environments with live/test evidence as routine rollback.
- Do not clear auth/session Redis namespaces.
- Do not delete normalized history to hide an incident.

## Scenario-to-Activity Hints

| Scenario | Typical activity code |
| --- | --- |
| S2S read | `act-cat-091` / `billing_s2s_read` |
| Checkout created/rejected | `act-cat-092`..`act-cat-093` |
| Portal created/rejected | `act-cat-094`..`act-cat-095` |
| Webhook received/rejected/replay | `act-cat-096`..`act-cat-098` |
| Billing status changed | `act-cat-099` |
| Purchase status changed | `act-cat-100` |
| Sync started/completed/failed | `act-cat-101`..`act-cat-103` |
| Provider-ref mismatch | `act-cat-104` |
| Retention purge | `act-cat-105` |
| Key rotation completed | `act-cat-106` |

Activity details must stay redacted and must not include raw provider refs, signatures, payloads, secrets, HMACs, fingerprints, idempotency keys, or consumer-owned credit amounts.

## Related Documentation

- [Overview](README.md)
- [Architecture](architecture.md)
- [Request Flow](request-flow.md)
- [Reference](reference.md)
- [Troubleshooting](troubleshooting.md)
- [Runbook](../../RUNBOOKS/stripe-billing.md)

---

**Document Version**: 1.0
