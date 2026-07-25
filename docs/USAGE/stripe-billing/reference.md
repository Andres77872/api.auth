# Stripe Billing Reference

Reference for the provider-agnostic billing S2S surface and Stripe provider adapter in `api.auth`.

Stripe is not login authority and must not issue local sessions, JWTs, refresh
tokens, cookies, or API keys. Project-scoped identity responses intentionally
include the narrow `SessionPlanStatus` projection documented below; mutable
provider facts still require the S2S surface.

## Configuration Reference

All billing behavior is disabled by default. Enable only the narrow switches required for the current rollout gate.

### Kill switches / feature flags

| Env var | Default | Purpose |
| --- | --- | --- |
| `BILLING_ENABLED` | `false` | Master generic billing switch. |
| `BILLING_S2S_ENABLED` | `false` | Enables internal billing route family after bearer readiness. |
| `BILLING_CHECKOUT_ENABLED` | `false` | Enables Checkout flow readiness. |
| `BILLING_PORTAL_ENABLED` | `false` | Enables restricted Portal flow readiness. |
| `BILLING_SYNC_ENABLED` | `false` | Enables billing sync worker behavior. |
| `BILLING_RAW_PAYLOAD_CAPTURE_ENABLED` | `false` | Enables encrypted raw-evidence quarantine for approved diagnostics only. |
| `STRIPE_BILLING_ENABLED` | `false` | Enables Stripe adapter readiness. |
| `STRIPE_WEBHOOKS_ENABLED` | `false` | Enables signed Stripe webhook processing. |
| `STRIPE_CHECKOUT_ENABLED` | `false` | Enables Stripe Checkout adapter calls. |
| `STRIPE_PORTAL_ENABLED` | `false` | Enables Stripe Portal adapter calls. |
| `STRIPE_SYNC_ENABLED` | `false` | Enables Stripe source-of-truth sync. |

Disabling these switches must preserve existing local authentication, Google OAuth, email, sessions, refresh tokens, API keys, and Patreon behavior.

### Server-only billing crypto / S2S settings

| Env var | Purpose |
| --- | --- |
| `BILLING_S2S_BEARER_TOKEN` | Dedicated internal bearer. Required for billing S2S routes. |
| `BILLING_ID_HMAC_SECRET` | HMAC secret for provider refs, delivery refs, and idempotency. |
| `BILLING_PROVIDER_REF_ENCRYPTION_KEY` | Active Fernet-compatible key for raw operational provider refs. |
| `BILLING_PROVIDER_REF_ENCRYPTION_KEY_ID` | Active key id for new encrypted provider refs. |
| `BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON` | JSON key-id map for active and previous decrypt keys. |
| `BILLING_RAW_PAYLOAD_ENCRYPTION_KEY` | Optional encrypted raw-evidence quarantine key. |
| `BILLING_RAW_PAYLOAD_ENCRYPTION_KEY_ID` | Key id for raw-evidence quarantine. |
| `BILLING_RETURN_URL_ALLOWLIST` / `BILLING_ALLOWED_RETURN_ORIGINS` | Allowed Checkout/Portal return origins. |

Generate high-entropy values outside source control. Use placeholders in docs/tickets only; never paste real secrets.

### Stripe adapter settings

| Env var | Default / requirement | Purpose |
| --- | --- | --- |
| `STRIPE_SECRET_KEY` | Optional | Global single-account/migration fallback; normal multi-account operations use encrypted per-group credentials. |
| `STRIPE_WEBHOOK_SECRET` | Optional | Signing secret for the global `/webhooks/stripe` migration fallback only. |
| `STRIPE_API_VERSION` | `2026-05-27.dahlia` | Pinned API version. Mismatch fails closed. |
| `STRIPE_PORTAL_CONFIGURATION_ID` | Optional/legacy | No runtime Portal fallback; set the Portal configuration id on each billing group. |
| `STRIPE_ALLOWED_WEBHOOK_EVENTS` | Approved MVP allow-list | May narrow, but must not widen, the MVP event list. |
| `STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS` | `300` | Signature timestamp tolerance. |

The supported Stripe SDK package version is `15.2.1`. SDK/API mismatch is `not_ready`; it must not silently enable Checkout, Portal, webhooks, or sync.

Each billing group stores its own Stripe secret key, webhook secret, and
optional Portal configuration id as encrypted database values through
`PUT /admin/billing/{group_hash}/credentials`. The API never echoes these
values; reads expose presence/status/fingerprints only.

### Approved webhook events

Only these MVP event types may mutate billing or purchase facts:

- `checkout.session.completed`
- `customer.subscription.created`
- `customer.subscription.updated`
- `customer.subscription.deleted`
- `invoice.paid`
- `invoice.payment_failed`
- `charge.refunded`
- `charge.dispute.created`
- `charge.dispute.closed`

Validly signed unsupported events are ignored or recorded safely without current-fact mutation.

### Retention settings

| Env var | Default | Cap |
| --- | ---: | ---: |
| `BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS` | `90` | `90` days. |
| `BILLING_RAW_PAYLOAD_RETENTION_DAYS` | `30` | `30` days. |
| `BILLING_SYNC_STALE_AFTER_SECONDS` | `86400` | Product-specific stale policy stays consumer-owned. |

Normalized billing entitlement history and purchase history are retained indefinitely in privacy-minimized form.

### Rate-limit settings

| Bucket | Limit env | Window env | Default |
| --- | --- | --- | --- |
| Billing S2S read/action | `BILLING_S2S_RATE_LIMIT` | `BILLING_S2S_RATE_WINDOW_SECONDS` | `120` / `60s` |
| Checkout | `BILLING_CHECKOUT_RATE_LIMIT` | `BILLING_CHECKOUT_RATE_WINDOW_SECONDS` | `30` / `60s` |
| Portal | `BILLING_PORTAL_RATE_LIMIT` | `BILLING_PORTAL_RATE_WINDOW_SECONDS` | `30` / `60s` |
| Resync enqueue | `BILLING_RESYNC_RATE_LIMIT` | `BILLING_RESYNC_RATE_WINDOW_SECONDS` | `30` / `300s` |
| Webhook signature failures | `STRIPE_WEBHOOK_SIGNATURE_FAILURE_RATE_LIMIT` | `STRIPE_WEBHOOK_SIGNATURE_FAILURE_RATE_WINDOW_SECONDS` | `30` / `60s` |

Redis keys must use hashed bucket material. Do not use raw provider refs, signatures, idempotency keys, user PII, or consumer-owned credit amounts in key names.

### Optional test settings

| Env var | Default | Purpose |
| --- | --- | --- |
| `RUN_STRIPE_E2E` | `false` | Opt-in Stripe sandbox smoke only. |
| `RUN_STRIPE_LOCAL_E2E` | `false` | Opt-in local Stripe-style fixture smoke. |
| `STRIPE_LIVE_TEST_USER_HASH` | Empty | Test-only local user hash. |
| `STRIPE_LIVE_TEST_PROJECT_HASH` | Empty | Test-only local project hash. |
| `STRIPE_LIVE_TEST_LOOKUP_KEY` | Empty | Test-only provider lookup key. |

Never commit live provider credentials or webhook secrets.

## Route Contracts

### Session `plan` projection

`LoginResponse`, `ValidateSessionResponse`, and `ValidateApiKeyResponse` may
carry a `plan` for project-scoped consumers. Platform sessions and non-consumer
API keys leave it unset. The current refresh and switch-project response bodies
omit `plan`; clients can call `/auth/validate` with the new access token when
they need a fresh projection.

Allowed fields are `provider`, `state`, `active`, `plan_code`, `tier_code`,
`current_period_end`, `trial_end`, and `cancel_at_period_end`. States collapse
internal subscription facts into `none`, `free`, `trial`, `active`,
`past_due`, or `canceled`. Credits/packages and raw Stripe state are never
represented. Lookup failure degrades to `state="none"` and never fails local
authentication.

### Shared S2S requirements

| Item | Contract |
| --- | --- |
| Authority | `Authorization: Bearer <billing-s2s-token>` only. Constant-time validation. |
| Required header | `User-Agent`. |
| Rejected authority | Browser cookies, local sessions, user JWTs, regular API keys, `/auth/validate` output. |
| Errors | Neutral and enumeration-safe. Do not reveal user/project/provider existence. |
| Redaction | Responses, errors, logs, audit, activity, and metrics must exclude raw provider refs, secrets, signatures, idempotency keys, payloads, payment-method details, receipt links, HMACs, and fingerprints. |

### `GET /internal/projects/{project_hash}/billing/catalog`

| Item | Contract |
| --- | --- |
| Caller | Trusted internal service using the billing S2S bearer. |
| Query | Optional `provider` (`stripe`) and `item_type`. |
| Success posture | `200`; a missing billing group or active catalog returns empty `subscriptions`/`credit_packs`. |
| Safe response | Project/group hashes, provider, version, and consumer-safe catalog rows: plan/product codes, tier/display labels, amount/currency/interval, credits, lookup key, opaque `features`, active flag. |
| Forbidden | Raw Stripe Product/Price ids, ciphertext, credential material, admin-only metadata. |

### `GET /internal/users/{user_hash}/billing`

| Item | Contract |
| --- | --- |
| Caller | Trusted internal service. |
| Query | `project_hash` required; `provider` optional and currently `stripe`. |
| Success posture | `200` with safe billing envelope. Missing row returns project-scoped free default. |
| Safe response fields | `success`, `message`, `user_hash`, `project_hash`, `provider`, `billing`, `purchases`, `contract_version`. |
| Forbidden | Browser auth, raw provider internals, product benefits, credit balances, credit ledgers. |

Minimal safe response shape:

```json
{
  "success": true,
  "message": "Billing status returned.",
  "user_hash": "<user-hash>",
  "project_hash": "<project-hash>",
  "provider": "stripe",
  "billing": {
    "provider": "stripe",
    "status": "free",
    "plan_code": "free",
    "link_status": "none",
    "cancel_at_period_end": false,
    "classification_version": 2
  },
  "purchases": [],
  "contract_version": 2
}
```

### `POST /internal/users/{user_hash}/billing/checkout`

| Item | Contract |
| --- | --- |
| Caller | Trusted internal service. |
| Body | `project_hash`, `provider`, `intent_type`, `price_ref`, `quantity`, return URLs, and consumer-owned evidence labels. |
| Subscription intent requires | `plan_code` and `tier_code`. |
| Credit-purchase intent requires | `credit_product_code`. |
| Success posture | `202` with hosted Checkout URL and opaque local refs only. Replay may return the previous safe result. |
| Idempotency | `Idempotency-Key` header and/or `client_intent_ref`; same key + same canonical request replays, same key + different request conflicts. |
| Forbidden | Product-benefit definitions, credit amounts, raw provider refs, provider API idempotency keys. |

The current route does not cross-check `price_ref`, `plan_code`, `tier_code`, or
`credit_product_code` against a local catalog row. The S2S caller must select
them from the project catalog; server-side catalog binding remains an open
hardening item.

Request shape:

```json
{
  "project_hash": "<project-hash>",
  "provider": "stripe",
  "intent_type": "subscription",
  "price_ref": { "ref_type": "lookup_key", "value": "<catalog-lookup-key>" },
  "quantity": 1,
  "plan_code": "<consumer-plan-code>",
  "tier_code": "<consumer-tier-code>",
  "tier_name": "<consumer-tier-name>",
  "success_url": "https://consumer.example.test/billing/success",
  "cancel_url": "https://consumer.example.test/billing/cancel",
  "client_intent_ref": "<consumer-idempotency-ref>"
}
```

Safe response fields: `success`, `message`, `checkout_ref`, `purchase_ref`, `subscription_ref`, `url`, `contract_version`.

### `POST /internal/users/{user_hash}/billing/portal`

| Item | Contract |
| --- | --- |
| Caller | Trusted internal service. |
| Body | `project_hash`, `provider`, `return_url`. |
| Success posture | `202` with hosted Portal URL and opaque `portal_ref`. |
| Portal limits | Cancellation and payment-method maintenance only. Plan changes are disabled. |
| Readiness | Fails closed when Portal configuration cannot be verified as restricted. |

Safe response fields: `success`, `message`, `portal_ref`, `url`, `contract_version`.

### `GET /internal/users/{user_hash}/billing/purchases/{purchase_ref}`

| Item | Contract |
| --- | --- |
| Caller | Trusted internal service. |
| Query | `project_hash` required; `provider` optional and currently `stripe`. |
| Success posture | `200` with safe purchase fact. |
| Not found/degraded | Generic not-found posture; no provider disclosure. |
| Consumer responsibility | Grant, hold, reverse, or ignore credits in the consumer ledger. |

Safe response fields: `success`, `message`, `user_hash`, `project_hash`, `provider`, `purchase`, `contract_version`.

### `POST /internal/users/{user_hash}/billing/resync`

| Item | Contract |
| --- | --- |
| Caller | Trusted internal service or operator S2S flow. |
| Body | `project_hash` required; optional `reason` and `force`. |
| Success posture | `202` accepted/queued/disabled/degraded/rate-limited safe response. |
| Forbidden | Raw provider selectors, payloads, HMACs, fingerprints, secrets. |

Safe response fields: `success`, `message`, `accepted`, `status`, `user_hash`, `project_hash`, `provider`, `retry_after_seconds`, `not_before`, `correlation_id`, `contract_version`.

### `POST /webhooks/stripe/{billing_group_hash}`

This is the preferred multi-account webhook. The URL selects exactly one
billing group and its encrypted webhook secret; verification is single-attempt
and never scans/trial-verifies other groups.

### `POST /webhooks/stripe`

| Item | Contract |
| --- | --- |
| Caller | Stripe webhook sender. |
| Authority | Stripe signature over exact raw request bytes using the global fallback secret. |
| Success posture | `200` accepted/ignored/duplicate after durable decision. |
| Failure posture | `401` invalid signature; `429` excessive signature failures; `503` not-ready configuration. |
| Forbidden | Browser session authority, raw-body audit capture, raw signature/payload exposure. |

Webhook body is parsed only after signature verification. Invalid signatures are rejected before mutation.

## Admin Billing Contracts

All 22 `/admin/billing` operations require an access session with `admin` or
`manage_billing`. Credential set/rotate/test routes additionally require a
ROOT user. Form fields are used for group/project/catalog CRUD; capability,
credential, and catalog-import bodies are JSON.

| Operations | Routes | Notes |
| --- | --- | --- |
| Group list/create/detail/update/delete | `GET|POST /admin/billing`, `GET|PUT|DELETE /admin/billing/{group_hash}` | One group owns one Stripe account/catalog; delete refuses active subscriptions. |
| Metrics | `GET /admin/billing/metrics` | Aggregate counts only; no secrets or per-user financial data. |
| Capabilities | `PUT /admin/billing/{group_hash}/capabilities` | Partial JSON flags for Checkout, Portal, provisioning, and webhooks; enablement is readiness-gated. |
| Projects | `GET|POST /admin/billing/{group_hash}/projects`, `DELETE .../projects/{project_hash}` | Each project may belong to only one billing group. |
| Credentials | `GET|PUT .../credentials`, `POST .../credentials/rotate`, `POST .../credentials/test` | GET is status/fingerprints; write/test JSON contains secrets and is ROOT-only. |
| Catalog read/create/update/archive | `GET|POST .../catalog`, `PUT|DELETE .../catalog/{item_hash}`, `POST .../{item_hash}/archive` | `DELETE` archives. Form `features`/`metadata` are JSON objects treated as opaque. |
| Catalog reconcile/sync/import | `GET .../catalog/reconcile`, `POST .../catalog/sync`, `POST .../catalog/import` | Read-only drift view, repair/adopt missing refs, and explicit selected-price import. |

The public catalog S2S DTO is intentionally broader than the normalized
provider-facts DTO: it exposes catalog amount/currency/interval, credits, lookup
key, and opaque features so consuming projects can render and interpret the
catalog without raw Stripe ids.

## Safe Field Allow-Lists

### `BillingSafeStatus`

- `provider`
- `status`
- `plan_code`
- `tier_code`
- `tier_name`
- `link_status`
- `current_period_end`
- `cancel_at_period_end`
- `trial_end`
- `grace_period_until`
- `last_synced_at`
- `stale_after`
- `classification_version`
- `customer_ref`
- `subscription_ref`

`customer_ref` and `subscription_ref` are opaque local refs only.

### `BillingSafePurchaseStatus`

- `provider`
- `purchase_ref`
- `status`
- `credit_product_code`
- `quantity`
- `paid_at`
- `refunded_at`
- `disputed_at`
- `last_synced_at`
- `stale_after`
- `classification_version`

Purchase facts do not contain credit amounts or ledger entries.

## Forbidden Fields and Data Classes

The following must never appear in billing provider-fact DTOs, public errors,
audit details, activity details, metrics, tickets, or logs:

- local auth material: access tokens, refresh tokens, session tokens, cookies, API keys,
- raw Stripe operational identifiers or any field intended to carry them,
- Stripe signatures and webhook secrets,
- Stripe secret keys and billing S2S bearer tokens,
- must never include raw provider payloads, raw request bodies, or raw provider JSON,
- card or payment-method details,
- receipt URLs and client secrets,
- idempotency keys,
- provider HMAC digests, provider fingerprints, key material, encryption keys,
- consumer-owned balances, ledger mutations, interpreted benefits, or quotas.

Catalog prices/credits/features are allowed only on the explicit admin/public
catalog models. If a field is not allow-listed for the response model in use,
keep it server-only.

## Normalized Statuses

Subscription statuses: `free`, `pending`, `incomplete`, `trialing`, `active`, `past_due`, `unpaid`, `paused`, `canceled`, `former`, `stale`, `unknown`.

Link statuses: `none`, `pending`, `linked`, `revoked`, `stale`.

Purchase statuses: `pending`, `paid`, `refunded`, `partially_refunded`, `disputed`, `dispute_won`, `dispute_lost`, `stale`, `unknown`.

## Error Codes

Billing/Stripe errors use the `EXT_82xx` namespace.

| Code | Meaning |
| --- | --- |
| `EXT_8200` | Stripe provider not configured. |
| `EXT_8201` | Stripe provider disabled. |
| `EXT_8202` | Stripe configuration invalid. |
| `EXT_8203` | Stripe SDK version mismatch. |
| `EXT_8204` | Stripe API version mismatch. |
| `EXT_8205` | Stripe webhook signature invalid. |
| `EXT_8206` | Billing S2S unauthorized. |
| `EXT_8207` | Billing project scope denied. |
| `EXT_8208` | Billing idempotency conflict. |
| `EXT_8209` | Stripe Checkout unavailable. |
| `EXT_8210` | Stripe Portal unavailable. |
| `EXT_8211` | Stripe Portal configuration invalid. |
| `EXT_8212` | Billing provider-ref decrypt failed. |
| `EXT_8213` | Billing sync degraded. |
| `EXT_8214` | Billing rate limited. |
| `EXT_8215` | Billing security event. |

Public messages are neutral. They must not reveal customer, subscription, purchase, project, secret, mapping, or provider-existence details.

## Idempotency Semantics

| Surface | Semantics |
| --- | --- |
| Checkout / Portal | Dedicated S2S idempotency uses `Idempotency-Key` and/or request reference. Same key + same canonical request returns stored safe response; same key + different request returns neutral conflict. |
| Stripe API calls | Provider API idempotency keys are derived from internal opaque refs, never raw consumer input. |
| Webhooks | Delivery ledger deduplicates by privacy-preserving provider event evidence. Duplicate delivery returns safe success/no-op. |
| Sync jobs | Active dedupe key prevents repeated in-flight source-of-truth repair for the same scope/reason. |
| Consumer credit fulfillment | Product service owns idempotency using `purchase_ref` or its own projection key. |

## Redaction Guarantees

Billing redaction applies recursively to:

- S2S DTO serialization,
- public errors,
- route-local audit metadata,
- activity details,
- metrics labels,
- worker result payloads,
- log messages,
- webhook failure paths.

Hosted Checkout/Portal URLs may be returned only to trusted S2S callers. Raw provider refs, signatures, secrets, raw payloads, provider hashes/fingerprints, and payment-method details are not returned separately.

## Related Documentation

- [Overview](README.md)
- [Architecture](architecture.md)
- [Request Flow](request-flow.md)
- [Scenarios](scenarios.md)
- [Troubleshooting](troubleshooting.md)
- [Runbook](../../RUNBOOKS/stripe-billing.md)

---

**Document Version**: 1.0
