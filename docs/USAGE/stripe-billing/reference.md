# Stripe billing reference

The contract for the billing routes: endpoints, request and response fields, statuses, error
responses, rate limits, and configuration. Step-by-step calls are in [usage](usage.md); what
happens inside each request is in [request flow](request-flow.md).

## Endpoints

### Billing S2S endpoints

All six take `Authorization: Bearer <BILLING_S2S_BEARER_TOKEN>`, the dedicated billing token.
User access tokens, cookies, and API keys are not accepted. Bodies are JSON. Error bodies are
`{"success": false, "message": "..."}` with no error code ([S2S errors](#s2s-errors)).

| Method | Path | Input | Success | Other statuses |
| --- | --- | --- | --- | --- |
| GET | `/internal/projects/{project_hash}/billing/catalog` | Query `provider`, `item_type` | `200`, [catalog](#catalog-read) | `401`, `429` |
| GET | `/internal/users/{user_hash}/billing` | Query `project_hash` (required), `provider` | `200`, [status](#billing-status-read) | `400`, `401`, `429` |
| POST | `/internal/users/{user_hash}/billing/checkout` | [Checkout body](#checkout), optional `Idempotency-Key` header | `202`; `200` on replay | `400`, `401`, `409`, `422`, `429`, `503` |
| POST | `/internal/users/{user_hash}/billing/portal` | [Portal body](#portal), optional `Idempotency-Key` header | `202`; `200` on replay | `400`, `401`, `409`, `422`, `429`, `503` |
| GET | `/internal/users/{user_hash}/billing/purchases/{purchase_ref}` | Query `project_hash` (required), `provider` | `200`, [purchase](#purchase-read) | `400`, `401`, `404`, `429` |
| POST | `/internal/users/{user_hash}/billing/resync` | [Resync body](#resync) | `202` | `401`, `422`, `429` |

`provider` is optional everywhere and `stripe` is the only supported value.

### Stripe webhook endpoints

No user credentials. The `Stripe-Signature` header over the exact raw body is the credential.

| Method | Path | Signature checked with | Statuses |
| --- | --- | --- | --- |
| POST | `/webhooks/stripe/{billing_group_hash}` | The group's stored webhook secret, and only that one | `200`, `401`, `429`, `503` |

Details: [webhook contract](#webhook-contract).

### Admin billing endpoints

22 routes. Access token (`Authorization: Bearer <access JWT>` or the `access_token` cookie)
of a root or admin user whose session has `admin` or `manage_billing`. Rows marked Root also
require a root user. Scope rules: [admin authorization and scope](#admin-authorization-and-scope).

| Path | Method | Access | Input | Does |
| --- | --- | --- | --- | --- |
| `/admin/billing` | GET | Billing admin | Query `limit` (1-1000, default `50`), `offset`, `search` | Lists groups in scope, newest first, with `pagination` |
| `/admin/billing` | POST | Billing admin | Form `group_name` (required), `description`, `provider` | Creates a group with no credentials and every capability off |
| `/admin/billing/metrics` | GET | Billing admin | None | Returns aggregate [counts](#metrics-fields) |
| `/admin/billing/{group_hash}` | GET | Billing admin | None | Returns the group, `projects`, full `catalog`, `credentials`, `readiness` |
| `/admin/billing/{group_hash}` | PUT | Billing admin | Form `group_name`, `description`, `status` | Updates the group; empty fields keep their value |
| `/admin/billing/{group_hash}` | DELETE | Billing admin | None | Deletes the group and its local billing rows |
| `/admin/billing/{group_hash}/capabilities` | PUT | Billing admin | JSON [capabilities](#capabilities) | Turns capabilities on or off |
| `/admin/billing/{group_hash}/projects` | GET | Billing admin | None | Lists attached projects, newest first |
| `/admin/billing/{group_hash}/projects` | POST | Billing admin | Form `project_hash` | Attaches a project |
| `/admin/billing/{group_hash}/projects/{project_hash}` | DELETE | Billing admin | None | Detaches the project from whichever group holds it |
| `/admin/billing/{group_hash}/credentials` | GET | Billing admin | None | Returns credential status, never secrets |
| `/admin/billing/{group_hash}/credentials` | PUT | Root | JSON [credentials](#credentials) | Verifies with Stripe, then stores encrypted |
| `/admin/billing/{group_hash}/credentials/rotate` | POST | Root | JSON [credentials](#credentials) | Identical to the credentials save |
| `/admin/billing/{group_hash}/credentials/test` | POST | Root | JSON [credentials](#credentials) | Verifies with Stripe without storing |
| `/admin/billing/{group_hash}/catalog` | GET | Billing admin | Query `item_type`, `include_archived` (default `false`) | Lists catalog items |
| `/admin/billing/{group_hash}/catalog` | POST | Billing admin | Form [catalog item](#catalog-item-fields) | Creates an item; provisions it in Stripe when allowed |
| `/admin/billing/{group_hash}/catalog/{item_hash}` | PUT | Billing admin | Form [catalog item](#catalog-item-fields) | Updates an item; price fields rotate the Stripe price |
| `/admin/billing/{group_hash}/catalog/{item_hash}` | DELETE | Billing admin | None | Archives the item |
| `/admin/billing/{group_hash}/catalog/{item_hash}/archive` | POST | Billing admin | Form `archived` (default `true`) | Archives, or sets `active` again with `false` |
| `/admin/billing/{group_hash}/catalog/reconcile` | GET | Billing admin | None | Compares the catalog with Stripe; writes nothing |
| `/admin/billing/{group_hash}/catalog/sync` | POST | Billing admin | None | Reconciles and adopts matching Stripe references |
| `/admin/billing/{group_hash}/catalog/import` | POST | Billing admin | JSON [import](#reconcile-and-import) | Imports selected Stripe prices |

Admin errors use the standard error envelope ([admin errors](#admin-errors)).

## S2S contract

### Gates

A call must pass every row before its handler runs. Route-specific checks follow in each
section below.

| Check | Failure |
| --- | --- |
| Path, query, and JSON body match the schema, including unknown-field rejection | `400`, standard envelope ([errors](../errors.md)); runs before the bearer check |
| `BILLING_ENABLED`, `BILLING_S2S_ENABLED`, `BILLING_S2S_BEARER_TOKEN`, and `BILLING_ID_HMAC_SECRET` are all set, and the bearer matches | `401` `Unauthorized.` |
| `User-Agent` is not blank | `422` |
| Route rate limit ([rate limits](#rate-limits)) | `429` with `Retry-After` |

The Checkout and Portal gates (flags and billing group state) are listed in
[checkout](#checkout) and [portal](#portal).

### S2S errors

| Status | `message` | Cause |
| --- | --- | --- |
| `401` | `Unauthorized.` | Bearer missing or wrong, or S2S billing is off or not fully configured |
| `404` | `Resource not found.` | Purchase read only |
| `409` | `Request could not be processed.` | Idempotency key reused with a different body |
| `422` | `Request could not be processed.` | Route-specific; see each route |
| `429` | `Request could not be processed.` | Rate limit; read `Retry-After` |
| `503` | `Request could not be processed.` | A required flag is off, or a Stripe call failed |

A Stripe error that carries its own HTTP status (for example `401` for a revoked key while the
customer is created) is returned with that status and the same neutral body.

### Response redaction

Every S2S response passes a redaction step before it is sent:

- `user_hash`, `project_hash`, and `billing_group_hash` come back verbatim (project and billing
  group hashes are 64-character hex tokens). Any other 64-character hex token is replaced with
  `***FILTERED***`.
- Inside any string, Stripe-id-shaped tokens (`cus_`, `sub_`, `price_`, `prod_`, `in_`, `pi_`,
  `ch_`, `cs_`, `bps_`, or `evt_` at a word start), Stripe secrets, and signatures are replaced
  with `***FILTERED***`. This applies to catalog labels and `features` values too.
- `url` passes through unchanged only when it starts with `https://checkout.stripe.com/` or
  `https://billing.stripe.com/`.
- A key whose name is on the billing forbidden list (for example `card`, `brand`, `last4`,
  `api_key`) or contains `secret`, `signature`, `idempotency`, `fingerprint`, `hmac`,
  `payment_method`, `receipt_url`, `raw_body`, or `raw_payload` makes the response fail with
  `500`. The response models never carry such keys. Catalog `features` is exempt: its key names
  are consumer vocabulary (a `card` or `secret_level` feature is returned as is) and only its
  values are scrubbed.

### Catalog read

`GET /internal/projects/{project_hash}/billing/catalog` returns the active, provisioned items of
the billing group the project is attached to. It is not gated by the Checkout or Portal flags.

| Query | Default | Values |
| --- | --- | --- |
| `provider` | `stripe` | `stripe` |
| `item_type` | Both types | `subscription_plan` or `credit_package`; any other value returns empty lists |

| Response field | Type | Notes |
| --- | --- | --- |
| `success`, `message` | boolean, string | `message` is `Billing catalog returned.` |
| `project_hash` | string | As sent |
| `billing_group_hash` | string or null | The group's hash; null when the project has no group or no active items |
| `provider` | string | `stripe` |
| `subscriptions` | array | Items with `item_type` `subscription_plan` |
| `credit_packs` | array | Items with `item_type` `credit_package` |
| `contract_version` | integer | `2` |

Each item:

| Field | Source (admin item field) | Notes |
| --- | --- | --- |
| `item_type` | `item_type` | `subscription_plan` or `credit_package` |
| `plan_code` | `plan_code` | Subscription plans only; null for packages |
| `credit_product_code` | `plan_code` | Credit packages only; null for plans |
| `tier_code`, `tier_name` | same | Opaque labels |
| `display_name` | `display_name` | |
| `amount_cents` | `unit_amount` | Minor currency unit |
| `currency` | `currency` | |
| `interval` | `recurring_interval` | |
| `credits` | `features.credits` | Integer; null when absent or `0` |
| `provider` | `provider` | `stripe` |
| `provider_price_lookup_key` | `lookup_key` | Send as a `lookup_key` price ref to Checkout |
| `features` | `features` | Opaque JSON object with any key names; string values are scrubbed of Stripe ids and secrets; `metadata` is admin-only and not included |
| `active` | `active` | Always `true` here |

A database failure returns empty lists instead of an error.

### Billing status read

`GET /internal/users/{user_hash}/billing?project_hash=...` returns the user's subscription
facts for the project's billing group. Every project in a group sees the same subscription.

The free default (`status` and `plan_code` `free`, `link_status` `none`) is returned, with
`200`, when there are no facts, the user or project is unknown, the user has no access to the
project, the project has no billing group, or the lookup fails. `purchases` is always an empty
array; read purchases one at a time with the [purchase read](#purchase-read).

| Response field | Type | Notes |
| --- | --- | --- |
| `success`, `message` | boolean, string | `message` is `Billing status returned.` |
| `user_hash` | string | As sent |
| `project_hash` | string | As sent |
| `provider` | string | `stripe` |
| `billing` | object | [Billing fields](#billing-fields) |
| `purchases` | array | Always empty |
| `contract_version` | integer | `2` |

#### Billing fields

| Field | Type | Notes |
| --- | --- | --- |
| `provider` | string | `stripe` |
| `status` | string | [Subscription status](#subscription-statuses) |
| `plan_code` | string | `free` whenever `status` is `free`, `incomplete`, `canceled`, `former`, `stale`, or `unknown` |
| `tier_code`, `tier_name` | string or null | Null whenever `plan_code` is `free` |
| `link_status` | string | [Link status](#link-statuses) |
| `current_period_end`, `trial_end` | datetime or null | From the last Stripe object written |
| `cancel_at_period_end` | boolean | |
| `grace_period_until` | datetime or null | Not written by the current code |
| `last_synced_at` | datetime or null | Time of the last written fact |
| `stale_after` | datetime or null | Past this time an `active`-like status reads as `stale`; the current writers leave it null |
| `classification_version` | integer | `2` |
| `customer_ref`, `subscription_ref` | string or null | Opaque local refs (`bcust-...`, `bsub-...`; customers recorded by older webhook code keep `bcustref-...`), never Stripe ids |

```json
{
  "success": true,
  "message": "Billing status returned.",
  "contract_version": 2,
  "user_hash": "usr-00000000-0000-0000-0000-000000000000",
  "project_hash": "7CCC926F2F5FEB07C973606EB2DF02BC3607C9C5B80A104DF5AAC9A1991F6173",
  "provider": "stripe",
  "billing": {
    "provider": "stripe",
    "status": "free",
    "plan_code": "free",
    "tier_code": null,
    "tier_name": null,
    "link_status": "none",
    "current_period_end": null,
    "cancel_at_period_end": false,
    "trial_end": null,
    "grace_period_until": null,
    "last_synced_at": null,
    "stale_after": null,
    "classification_version": 2,
    "customer_ref": null,
    "subscription_ref": null
  },
  "purchases": []
}
```

### Checkout

`POST /internal/users/{user_hash}/billing/checkout` creates a Stripe-hosted Checkout Session and
returns its URL. The user's Stripe customer in the billing group is created on first use.

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `project_hash` | string | Yes | 1-255 characters; selects the billing group |
| `provider` | string | No | `stripe` |
| `intent_type` | string | Yes | `subscription` (Stripe mode `subscription`) or `credit_purchase` (mode `payment`) |
| `price_ref.ref_type` | string | Yes | `lookup_key` or `price_id` |
| `price_ref.value` | string | Yes | 1-512 characters. A lookup key is resolved to the active price on the group's own Stripe account |
| `quantity` | integer | No | 1-10000, default `1` |
| `plan_code` | string | For `subscription` | 1-128 characters |
| `tier_code` | string | For `subscription` | 1-128 characters |
| `tier_name` | string | No | 1-256 characters |
| `credit_product_code` | string | For `credit_purchase` | 1-128 characters |
| `success_url`, `cancel_url` | string | Yes | 1-2048 characters; origin must be allowed ([return URLs](#return-urls)) |
| `client_intent_ref` | string | No | 1-128 characters; the idempotency key when no `Idempotency-Key` header is sent |

- Unknown fields, a Stripe-id-shaped value in `plan_code`, `tier_code`, `tier_name`,
  `credit_product_code`, or `client_intent_ref`, or a `provider` other than `stripe` fail with
  `400`.
- The price and labels are not checked against the catalog. Take them from the
  [catalog read](#catalog-read). The labels are copied into Stripe metadata as
  `consumer_plan_code`, `consumer_tier_code`, `consumer_tier_name`, and
  `consumer_credit_product_code`, together with `user_hash`, `project_hash`, and the
  `api_auth_*` refs. The same metadata is set on the Checkout Session and on the object it
  creates (`subscription_data.metadata` or `payment_intent_data.metadata`), so later Stripe
  events can be [attributed](#attribution).

```json
{
  "project_hash": "<project-hash>",
  "intent_type": "subscription",
  "price_ref": {"ref_type": "lookup_key", "value": "pro_monthly"},
  "plan_code": "pro",
  "tier_code": "pro",
  "tier_name": "Pro",
  "success_url": "https://app.example.com/billing/success",
  "cancel_url": "https://app.example.com/billing/cancel",
  "client_intent_ref": "upgrade-7f3a"
}
```

| Response field | Notes |
| --- | --- |
| `success`, `message` | `message` is `Checkout session created.` |
| `checkout_ref` | `bco-...` |
| `subscription_ref` | `bsub-...` for `subscription`, else null |
| `purchase_ref` | `bpur-...` for `credit_purchase`, else null; use it with the [purchase read](#purchase-read) |
| `url` | Stripe-hosted Checkout URL |
| `contract_version` | `2` |

| Status | When |
| --- | --- |
| `202` | Session created |
| `200` | Replay: same idempotency key and same body as an earlier completed call; the stored response is returned |
| `409` | Same idempotency key, different body |
| `422` | `plan_code`/`tier_code` missing for `subscription`, or `credit_product_code` missing for `credit_purchase`; a return URL outside the allow-list; a malformed idempotency key; the user has no access to the project; the group is not ready (no group, group or credentials not `active`, no stored secret key, group `checkout_enabled` off) |
| `503` | `BILLING_RETURN_URL_ALLOWLIST` is empty; `BILLING_ENABLED`, `BILLING_CHECKOUT_ENABLED`, `STRIPE_BILLING_ENABLED`, or `STRIPE_CHECKOUT_ENABLED` is off; the group's Stripe account cannot be used; the lookup key matches no active price; encryption keys are missing; or the Stripe call failed |

The label and return-URL checks run before the rate limit, and the idempotency-key check runs
before the flag checks, so a malformed request gets `422` even while Checkout is off (an empty
allowlist answers `503` first).

### Portal

`POST /internal/users/{user_hash}/billing/portal` creates a Stripe Customer Portal session with
the billing group's own stored portal configuration.

| Field | Type | Required | Rules |
| --- | --- | --- | --- |
| `project_hash` | string | Yes | 1-255 characters |
| `provider` | string | No | `stripe` |
| `return_url` | string | Yes | 1-2048 characters; origin must be allowed ([return URLs](#return-urls)) |

| Response field | Notes |
| --- | --- |
| `success`, `message` | `message` is `Portal session created.` |
| `portal_ref` | `bpo-...` |
| `url` | Stripe-hosted Portal URL |
| `contract_version` | `2` |

| Status | When |
| --- | --- |
| `202` | Session created |
| `200` | Replay of the same `Idempotency-Key` and body, from this server process's memory only |
| `409` | Same `Idempotency-Key`, different body |
| `422` | `return_url` outside the allow-list; malformed `Idempotency-Key`; group not ready (as for Checkout, plus group `portal_enabled` off or no stored portal configuration id); the user has no Stripe customer in the group yet |
| `503` | `BILLING_RETURN_URL_ALLOWLIST` is empty; `BILLING_ENABLED`, `BILLING_PORTAL_ENABLED`, `STRIPE_BILLING_ENABLED`, or `STRIPE_PORTAL_ENABLED` is off; the portal configuration fails the [restricted-portal check](#restricted-portal-configuration); or the Stripe call failed |

Without an `Idempotency-Key` header every call creates a new session.

#### Restricted portal configuration

Checked when credentials are saved with a portal configuration id and again on every Portal
call. The Stripe configuration must have `features.subscription_update.enabled` false,
`features.payment_method_update.enabled` true, and `features.subscription_cancel.enabled` true.
Plan changes therefore go through Checkout.

### Purchase read

`GET /internal/users/{user_hash}/billing/purchases/{purchase_ref}?project_hash=...` returns one
one-time purchase. The purchase must belong to `user_hash` and to the project it was bought in;
any other combination, a purchase Stripe has not reported yet, and a lookup failure all return
`404`.

| Response field | Notes |
| --- | --- |
| `success`, `message` | `message` is `Purchase status returned.` |
| `user_hash` | As sent |
| `project_hash` | As sent |
| `provider` | `stripe` |
| `purchase` | [Purchase fields](#purchase-fields) |
| `contract_version` | `2` |

#### Purchase fields

| Field | Notes |
| --- | --- |
| `provider` | `stripe` |
| `purchase_ref` | `bpur-...` |
| `status` | [Purchase status](#purchase-statuses); `pending` or `paid` past `stale_after` reads `stale` |
| `credit_product_code` | From the Checkout request |
| `quantity` | The Checkout request's `quantity` once the purchase is matched to its Checkout ref; otherwise null |
| `paid_at`, `refunded_at`, `disputed_at` | Set when the matching event is written; a resync sets `paid_at` to the charge's creation time |
| `last_synced_at`, `stale_after` | As for billing fields |
| `classification_version` | `2` |

No credit amounts or ledger entries are returned. Credits are the consumer's to grant.

### Resync

`POST /internal/users/{user_hash}/billing/resync` queues a job for the billing sync worker.

| Field | Type | Required | Notes |
| --- | --- | --- | --- |
| `project_hash` | string | Yes | Missing gives `422` |
| `reason` | string | No | Default `internal_manual_resync`; part of the job dedupe key and the rate-limit key |
| `force` | boolean | No | `true` queues at priority `1` instead of `5` |

The response is always `202`; read `status`:

| `status` | `accepted` | Meaning |
| --- | --- | --- |
| `queued` | `true` | Job queued; `correlation_id` is the job id (`bsync-...`) |
| `disabled` | `false` | `BILLING_SYNC_ENABLED` is off; nothing queued |
| `degraded` | `false` | The job could not be queued; `user_hash` and `project_hash` are null |

Response fields: `success`, `message` (`Billing resync request accepted.`), `accepted`,
`status`, `user_hash`, `project_hash`, `provider`, `retry_after_seconds`, `not_before`,
`correlation_id`, `contract_version`. `retry_after_seconds` and `not_before` are not set by the
current route.

The job carries the user and the project's billing group. The worker lists the user's Stripe
customer's subscriptions in that group and writes the current one (live over ended, newest
first) to the billing facts, so a later [status read](#billing-status-read) reflects Stripe.
A user with no Stripe customer in the group has nothing to repair: the job completes without
writing. Purchases are not resynced this way. Details:
[architecture](architecture.md#sync-worker).

### Return URLs

`BILLING_RETURN_URL_ALLOWLIST` (or `BILLING_ALLOWED_RETURN_ORIGINS` when the first is empty)
is a comma-separated list of `http` or `https` origins. A return URL is allowed when its scheme,
host, and port equal an entry's; any other URL gets `422`. While the list is empty no URL is
allowed: Checkout and Portal answer `503`, and health reports `BILLING_RETURN_URL_ALLOWLIST` as
missing if either is enabled.

## Webhook contract

### Webhook gates

Checked before the signature. Failing any row returns `503`
`{"success": false, "message": "Webhook unavailable."}` and records nothing.

| Route | Requires |
| --- | --- |
| Both | `BILLING_ENABLED` and `STRIPE_WEBHOOKS_ENABLED` on; `BILLING_ID_HMAC_SECRET` set |
| `/webhooks/stripe/{billing_group_hash}` | The group exists, is `active`, has `webhooks_enabled` on, has `active` credentials, and a webhook secret that decrypts. Unknown and unconfigured groups are indistinguishable |

### Verification

- The body is read as raw bytes and verified with the Stripe SDK against the one selected
  secret, within `STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS` (default `300`).
- The event must have an `id`, and its `api_version`, when present, must equal
  `2026-05-27.dahlia`. Set the Stripe webhook endpoint to that API version.
- Any verification failure returns `401` `{"success": false, "message": "Webhook rejected."}`
  and counts toward the signature-failure limit for the client IP. Over the limit the response
  is `429` with `Retry-After`.

### Event handling

Every verified event is first recorded in the delivery ledger. A repeat of the same event id
for the same billing group returns `200` `duplicate_replay_accepted` without reprocessing.

| Event | Writes | Result |
| --- | --- | --- |
| `checkout.session.completed`, mode `payment` | Purchase | `paid` when the session is `complete` and `paid`, else `unknown` |
| `checkout.session.completed`, mode `subscription` | Subscription | `pending`, unless a subscription event already recorded a live status (then kept) |
| `checkout.session.completed`, other mode | Subscription | `unknown`, resync queued |
| `customer.subscription.created`, `customer.subscription.updated` | Subscription | Stripe status mapped: `incomplete` and `incomplete_expired` to `incomplete`; `trialing`, `active`, `past_due`, `unpaid`, `paused`, `canceled` kept; anything else `unknown` |
| `customer.subscription.deleted` | Subscription | `canceled` |
| `invoice.paid` | Subscription | `active` |
| `invoice.payment_failed` | Subscription | `past_due`, resync queued |
| `charge.refunded` | Purchase | `refunded` when fully refunded, else `partially_refunded` |
| `charge.dispute.created` | Purchase | `disputed` |
| `charge.dispute.closed` | Purchase | `dispute_won` (`won`, `warning_closed`), `dispute_lost` (`lost`, `lost_evidence`, `charge_refunded`), else `unknown` |
| Any other type | Nothing | `200` `ignored_noop` |

- For `customer.subscription.*`, when the object's metadata has a bare `plan_code` (set outside
  api.auth, for example in the Stripe Dashboard) and its first price has a lookup key, the plan
  code must appear inside the lookup key (case-insensitive, `-` read as `_`). Otherwise the
  event classifies as `unknown` and a resync is queued. The `consumer_plan_code` that Checkout
  writes is not compared, since catalog lookup keys need not contain the plan code.
- `STRIPE_ALLOWED_WEBHOOK_EVENTS` can narrow this table: a type it does not list is answered
  `200` `ignored_noop` without being classified or written; see [Stripe adapter
  settings](#stripe-adapter-settings).
- `current_period_end` is read from the subscription's first item (where API
  `2026-05-27.dahlia` puts it). Invoice and Checkout events carry no period dates; the stored
  ones are kept.

### Attribution

Checkout writes `user_hash`, `project_hash`, the opaque refs (`api_auth_checkout_ref`,
`api_auth_customer_ref`, `api_auth_subscription_ref` or `api_auth_purchase_ref`), and the
`consumer_*` labels into the metadata of the Checkout Session and of the Subscription or
PaymentIntent it creates. Stripe copies PaymentIntent metadata onto its charges, and an
invoice carries its subscription's metadata under `parent.subscription_details.metadata`.

An event is attributed in this order:

1. `user_hash` and `project_hash` in the object's metadata (for an invoice, its subscription's)
   resolve the user, project, and billing group.
2. Rows `api.auth` already stored are matched by the `api_auth_checkout_ref` (or a Checkout
   Session's `client_reference_id`), then by the HMAC of the event's subscription, payment
   intent, charge, or customer id. This attributes disputes, which never carry metadata, and
   objects created before Checkout copied its metadata. A match on a stored row wins over
   metadata that names a different user.
3. An event that matches neither writes no fact and queues nothing; it is answered `200`
   `accepted`.

Refs and labels come from the metadata first (`api_auth_*` names, or the same names without
the prefix; `consumer_*` labels, or the bare `plan_code`, `tier_code`, `tier_name`,
`credit_product_code`), then from the matched row, then, for a subscription, from the catalog
item whose Stripe price the subscription uses.

On the path-scoped route the facts are filed under the group in the URL; on the global route,
under the group resolved from `project_hash`.

### Webhook responses

| Status | Body | When |
| --- | --- | --- |
| `200` | `{"success": true, "status": "accepted"}` | Processed, or not writable and a resync was queued, or the classifier failed |
| `200` | `{"success": true, "status": "ignored_noop"}` | Event type not handled |
| `200` | `{"success": true, "status": "duplicate_replay_accepted"}` | Already received for this group |
| `401` | `{"success": false, "message": "Webhook rejected."}` | Signature, timestamp, JSON, event id, or `api_version` check failed |
| `429` | `{"success": false, "message": "Webhook rejected."}` | Too many failures from this IP; `Retry-After` set |
| `503` | `{"success": false, "message": "Webhook unavailable."}` | A [gate](#webhook-gates) failed; Stripe retries later |

## Admin contract

### Admin authorization and scope

| Caller | Result |
| --- | --- |
| No valid access token | `401` (`AUTH_1003` for an invalid or expired token) |
| Session without `admin` or `manage_billing` | `403` `AUTHZ_2002` |
| Consumer user, whatever its permissions | `403` `AUTHZ_2002` |
| Root user | Every group |
| Admin user | Only groups it fully owns: every active project attached is one of its assigned projects, or the group has no projects and it created the group. Other groups return `403` `AUTHZ_2001`; `404` is checked first |
| Admin user attaching or detaching a project it does not administer | `403` `AUTHZ_2003` |
| Non-root on a Root route | `403` `AUTHZ_2002` |

List and metrics routes return only the groups in scope.

### Group fields

Returned as `billing_group` (and in `billing_groups` of the list).

| Field | Notes |
| --- | --- |
| `group_hash` | 64-character uppercase hex |
| `name`, `description`, `owner_id`, `provider` | `owner_id` is the creating user |
| `status` | `active`, `suspended`, or `archived` |
| `checkout_enabled`, `portal_enabled`, `provisioning_enabled`, `webhooks_enabled` | Capability flags; forced off while `status` or `credential_status` is not `active` |
| `credential_status` | `absent`, `active`, `rotating`, `revoked`; saving credentials sets `active` |
| `has_secret_key`, `has_webhook_secret` | Presence only |
| `project_count`, `catalog_item_count` | |
| `catalog_sync_status`, `last_catalog_synced_at` | `never` until the first successful `POST .../catalog/sync`, then `ok` or `drift` |
| `created_at`, `updated_at` | |

Update rules: omitted or empty form fields keep their value, so a description cannot be
cleared. A `status` outside `active`, `suspended`, `archived` fails with `500`. Deleting a group
that has a subscription in `trialing`, `active`, `past_due`, `unpaid`, or `paused` returns `409`
`CONF_5005`; a successful delete cascades to the group's project mappings, catalog, customers,
subscription and purchase history, checkout intents, and webhook deliveries, and changes nothing
in Stripe.

### Readiness

`GET /admin/billing/{group_hash}` returns `readiness`:

| Field | Notes |
| --- | --- |
| `ready`, `status` | `ready` when `missing` is empty, else `not_ready` |
| `missing` | Unmet prerequisites for checkout, portal, and webhooks together (below) |
| `capabilities` | The four capability flags |
| `webhook_endpoint_path` | `/webhooks/stripe/<group_hash>`; register it in the group's Stripe account |

### Capabilities

`PUT /admin/billing/{group_hash}/capabilities`, JSON. Omitted or null flags keep their value.
Turning a flag off is always allowed. Turning one on checks that capability's prerequisites and
fails with `400` `VAL_3001`, `details.capability`, and `details.missing` otherwise.

```json
{
  "checkout_enabled": true,
  "portal_enabled": null,
  "provisioning_enabled": true,
  "webhooks_enabled": true
}
```

| Capability | Prerequisites (names as they appear in `missing`) |
| --- | --- |
| Every capability | `BILLING_ENABLED`, `STRIPE_BILLING_ENABLED`, `billing_group_active`, `billing_group_credentials_active` |
| `checkout_enabled` | `BILLING_CHECKOUT_ENABLED`, `STRIPE_CHECKOUT_ENABLED`, `stripe_secret_key`, `active_catalog_price` (an active, provisioned item) |
| `portal_enabled` | `BILLING_PORTAL_ENABLED`, `STRIPE_PORTAL_ENABLED`, `stripe_secret_key`, `stripe_portal_configuration_id` |
| `webhooks_enabled` | `STRIPE_WEBHOOKS_ENABLED`, `stripe_secret_key`, `stripe_webhook_secret` |
| `provisioning_enabled` | Only the common row |

### Credentials

`PUT .../credentials`, `POST .../credentials/rotate`, and `POST .../credentials/test` take the
same JSON body. It is never echoed back.

| Field | Required | Rules |
| --- | --- | --- |
| `secret_key` | Yes | Starts with `sk_` or `rk_`; always replaced on save |
| `webhook_secret` | No | Starts with `whsec_` |
| `portal_configuration_id` | No | Starts with `bpc_`; must pass the [restricted-portal check](#restricted-portal-configuration) |
| `stripe_account_label` | No | Free text |

- Save and rotate: an omitted or null optional field keeps its stored value, re-encrypted under
  the current key; an empty string clears it. A stored value that cannot be decrypted fails with
  `400`; resend or clear it. `credential_status` becomes `active` at once.
- Validation calls Stripe: the secret key must authenticate (`400` when Stripe rejects it or
  cannot be reached), and a portal configuration id that will be stored must exist and be
  restricted (`400` `EXT_8211`). A kept webhook secret is not re-checked.
- Save and rotate need `BILLING_PROVIDER_REF_ENCRYPTION_KEY`, `_ID`, and `BILLING_ID_HMAC_SECRET`
  (`400` otherwise).

Status fields (`credentials`): `credential_status`, `has_secret_key`, `has_webhook_secret`,
`secret_key_fingerprint`, `webhook_secret_fingerprint`, `stripe_account_label`,
`stripe_account_fingerprint` (fingerprint of the Stripe account id the key authenticated as),
`credential_key_id`, `credentials_set_at`.

Test response: `valid`, `secret_key_valid`, `portal_configuration_valid` (null when no portal id
was sent), `livemode`, `account_fingerprint`.

### Catalog item fields

| Form field | Create | Update | Notes |
| --- | --- | --- | --- |
| `item_type` | Required | No | `subscription_plan` or `credit_package`; other values `400` |
| `plan_code` | Required | No | One active item per plan code per group |
| `display_name` | Required | Yes | Also the Stripe Product name |
| `tier_code` | Optional | No | |
| `tier_name` | Optional | Yes | |
| `amount_cents` | Optional | Yes | Minor unit; required for provisioning |
| `currency` | Default `usd` | Yes | Three letters |
| `recurring_interval` | Optional | Yes | `day`, `week`, `month`, `year`; used for subscription plans only |
| `lookup_key` | Optional | No | Transferred onto each new Stripe price |
| `features` | Optional | Yes | JSON object as a string; opaque, sent to consumers; `features.credits` becomes `credits` |
| `metadata` | Optional | Yes | JSON object as a string; admin-only |
| `sort_order` | Default `0` | Yes | |

- `features` or `metadata` that is not a JSON object fails with `400`. Values outside the
  database constraints (unknown interval, currency longer than three letters) fail with `500`.
- On create, the item is provisioned when `BILLING_ENABLED` is on and the group has
  `provisioning_enabled` and `active` credentials: a Stripe Product and Price are created and the
  item becomes `active`. Otherwise it is saved `pending` and inactive.
- On update, sending `amount_cents`, `currency`, or `recurring_interval` (even unchanged) while
  provisioning is allowed creates a new Price on the item's Product (a Product too, if it has
  none), then deactivates the old Price. This is also how a `pending` item is provisioned later.
- Provisioning failures never fail the request: the item returns with `provisioning_status`
  `failed` and a redacted `provisioning_error`. A failed reprice leaves the old Price live.
- Archiving sets `provisioning_status` `archived` and `active` false, which removes the item
  from the S2S catalog. `archived=false` sets `active` true without changing
  `provisioning_status`. Neither touches Stripe.

Item response fields (`item`, `catalog`): `item_hash`, `item_type`, `plan_code`, `tier_code`,
`tier_name`, `display_name`, `currency`, `unit_amount`, `recurring_interval`, `lookup_key`,
`provider`, `provider_price_fingerprint`, `features`, `metadata`, `sort_order`, `active`,
`provisioning_status` (`pending`, `active`, `failed`, `archived`), `provisioning_error`,
`provisioned_at`, `created_at`, `updated_at`.

### Reconcile and import

`GET .../catalog/reconcile` and `POST .../catalog/sync` return `result`:

| Field | Notes |
| --- | --- |
| `in_sync` | Count of items whose stored price matches Stripe |
| `drift` | Items that differ: `item_hash`, `plan_code`, `item_type`, `drift_kind` (`amount_mismatch`, `interval_mismatch`, `unresolved`), local and Stripe amount and interval, `price_fingerprint` |
| `candidates` | Active Stripe prices with no local item: `item_type`, `plan_code`, `display_name`, `currency`, `unit_amount`, `recurring_interval`, `lookup_key`, `product_fingerprint`, `price_fingerprint`, `plan_code_conflict` |
| `missing_ref_repaired` | `0` for reconcile; for sync, items that adopted a Stripe price matched by lookup key |
| `gated`, `error` | `gated` with `billing_disabled` (`BILLING_ENABLED` off) or `account_not_ready` (credentials not active or not decryptable); missing encryption keys or a Stripe read failure set `error` only. `success` is false whenever `error` is set |
| `synced_at` | Time of the read |

Sync never overwrites local prices or plan codes and creates nothing in Stripe.

`POST .../catalog/import`, JSON:

```json
{"price_fingerprints": ["a1b2c3d4e5f6"], "plan_code_overrides": {"a1b2c3d4e5f6": "pro"}}
```

Each selected price becomes an active, provisioned item: recurring prices as
`subscription_plan`, one-time prices as `credit_package`. Without an override the plan code is
the price's lookup key, else the product's `plan_code` metadata, else a slug of the product name.
The response lists `imported`, `conflicts` (plan codes already active), and `skipped`. When
billing is off, the account is not ready, keys are missing, or Stripe fails, the response is
still `200` with empty lists.

### Metrics fields

`metrics`: `groups_total`, `groups_active`, `groups_suspended`, `groups_archived`,
`credentials_active`, `credentials_absent`, `credentials_rotating`, `credentials_revoked`,
`subscription_plans`, `credit_packages` (non-archived items), `catalog_active`,
`catalog_pending`, `catalog_failed`, `catalog_archived`, `projects_mapped`,
`groups_with_webhook_secret`, `webhook_secret_missing_active_groups`. Root gets platform-wide
counts; admin users get counts over their groups. A database failure returns zeros.

### Admin errors

| Status | Code | When |
| --- | --- | --- |
| `400` | `VAL_3001` | Capability prerequisites missing; invalid `item_type`, `features`, or `metadata`; credentials invalid or unverifiable; encryption keys missing |
| `400` | `VAL_3012` | Group `provider` other than `stripe` |
| `400` | `EXT_8211` | Portal configuration id not found or not restricted |
| `404` | `NF_4004` | Unknown group, project, or catalog item; an item of another group |
| `409` | `CONF_5005` | Delete with live subscriptions; project attached to another group |
| `503` | `EXT_8200` | `stripe` is missing from `billing_providers`; run `scripts/migrations/billing_provider_bootstrap.py --apply` |

Envelope and the full catalog: [errors](../errors.md).

## Session plan projection

A provider-neutral `plan` object is added to these responses for consumer users in a
project-scoped session:

| Response | Condition |
| --- | --- |
| `POST /auth/login` | Consumer login (root and admin logins omit it) |
| `POST /auth/refresh` | Project-scoped consumer session |
| `GET /auth/validate` | Project-scoped consumer session |
| `POST /auth/validate-api-key` | Consumer key bound to a project |

`POST /auth/switch-project` does not return it; validate the new access token instead. The plan
is computed when the response is built and is not stored in the JWT, cookies, or the Redis
session. A lookup failure yields `state` `none` and never fails authentication.

| Field | Notes |
| --- | --- |
| `provider` | `stripe` |
| `state` | `none`, `free`, `trial`, `active`, `past_due`, `canceled` |
| `active` | `true` only for `trial` and `active` |
| `plan_code`, `tier_code`, `current_period_end`, `trial_end` | Null for `none` and `free` |
| `cancel_at_period_end` | `false` for `none` and `free` |

| Condition or stored status | `state` |
| --- | --- |
| `BILLING_ENABLED` off, or the project has no active billing group | `none` |
| No facts, `free`, `pending`, `incomplete`, or any unlisted status | `free` |
| `trialing` | `trial` |
| `active` | `active` |
| `past_due`, `unpaid`, `paused` | `past_due` |
| `canceled`, `former` | `canceled` |
| `stale` or `unknown` with `current_period_end` in the future | `active` |
| `stale` or `unknown` otherwise | `free` |

Credit packages never appear in the plan.

## Normalized statuses

### Subscription statuses

| Status | Meaning |
| --- | --- |
| `free` | No paid fact; also the default |
| `pending` | Checkout completed; the subscription has not been confirmed by a later event |
| `incomplete` | Stripe `incomplete` or `incomplete_expired` |
| `trialing`, `active`, `past_due`, `unpaid`, `paused` | The Stripe status of the same name |
| `canceled` | Stripe `canceled` or `customer.subscription.deleted` |
| `former` | Reserved; not written by the current code |
| `stale` | Read-time status once `stale_after` has passed |
| `unknown` | Evidence could not be classified |

### Purchase statuses

`pending`, `paid`, `refunded`, `partially_refunded`, `disputed`, `dispute_won`,
`dispute_lost`, `stale`, `unknown`. Mapping: [event handling](#event-handling).

### Link statuses

`none` (no facts, or `free`), `linked` (any other written status). `pending`, `revoked`, and
`stale` are accepted values that the current writers do not produce.

## Error codes

Billing codes are `EXT_8200` to `EXT_8215`. Only two reach a response body; the S2S and webhook
routes answer with the neutral bodies above and never include a code.

| Code | Name | Where it appears |
| --- | --- | --- |
| `EXT_8200` | Stripe provider not configured | `503` from `POST /admin/billing` when the provider registry has no `stripe` row |
| `EXT_8201` | Stripe provider disabled | Not raised by current routes |
| `EXT_8202` | Stripe configuration invalid | Not raised by current routes |
| `EXT_8203` | Stripe SDK version mismatch | Not raised by current routes |
| `EXT_8204` | Stripe API version mismatch | Internal; a webhook event with another `api_version` is answered `401` |
| `EXT_8205` | Stripe webhook signature invalid | Internal; answered `401` `Webhook rejected.` |
| `EXT_8206` | Billing S2S unauthorized | Not raised; S2S answers `401` `Unauthorized.` |
| `EXT_8207` | Billing project scope denied | Not raised by current routes |
| `EXT_8208` | Billing idempotency conflict | Not raised; S2S answers `409` |
| `EXT_8209` | Stripe Checkout unavailable | Internal; answered `503` |
| `EXT_8210` | Stripe Portal unavailable | Internal; answered `503` |
| `EXT_8211` | Stripe Portal configuration invalid | `400` from the admin credential routes; internal on Portal calls (answered `503`) |
| `EXT_8212` | Billing provider-ref decrypt failed | Not raised by current routes |
| `EXT_8213` | Billing sync degraded | Not raised by current routes |
| `EXT_8214` | Billing rate limited | Not raised; answered `429` |
| `EXT_8215` | Billing security event | Not raised by current routes |

## Idempotency

| Surface | Behavior |
| --- | --- |
| Checkout | Key: `Idempotency-Key`, else `client_intent_ref`, matching `^[A-Za-z0-9._:-]{1,128}$` (`422` otherwise). Scoped per user and billing group for subscriptions, per user and project for credit purchases. The whole body is hashed: same key and body replays the stored response (`200`), a different body is `409`. A call that failed before completing leaves no stored response, so retrying it creates a session. Without a key every call is new |
| Portal | Same key format, `Idempotency-Key` header only. Replay and conflict come from this process's memory; a restart or another replica forgets them |
| Stripe API calls | Stripe idempotency keys are derived from internal refs (new per Checkout or Portal call; per group and user for customer creation), never from the caller's key |
| Webhooks | Deduplicated per billing group and Stripe event id (stored as an HMAC) |
| Sync jobs | An active job with the same dedupe key (user, project, group, refs, reason) is not queued twice |
| Credit fulfillment | The consumer's responsibility, keyed on `purchase_ref` |

## Rate limits

Fixed windows in Redis. Keys hold only SHA-256 digests. If Redis is unavailable the S2S and
webhook routes let the request through.

| Bucket | Limit env | Window env | Default | Counted per |
| --- | --- | --- | --- | --- |
| S2S reads | `BILLING_S2S_RATE_LIMIT` | `BILLING_S2S_RATE_WINDOW_SECONDS` | `120` per `60` seconds | User, project, `X-Internal-Client` header (else `User-Agent`), IP. The catalog read uses no user |
| Checkout | `BILLING_CHECKOUT_RATE_LIMIT` | `BILLING_CHECKOUT_RATE_WINDOW_SECONDS` | `30` per `60` seconds | User, project, `client_intent_ref`, IP |
| Portal | `BILLING_PORTAL_RATE_LIMIT` | `BILLING_PORTAL_RATE_WINDOW_SECONDS` | `30` per `60` seconds | User, project, IP |
| Resync | `BILLING_RESYNC_RATE_LIMIT` | `BILLING_RESYNC_RATE_WINDOW_SECONDS` | `30` per `300` seconds | User, project, `reason`, IP |
| Webhook signature failures | `STRIPE_WEBHOOK_SIGNATURE_FAILURE_RATE_LIMIT` | `STRIPE_WEBHOOK_SIGNATURE_FAILURE_RATE_WINDOW_SECONDS` | `30` per `60` seconds | IP |

Non-integer values fall back to the default; values below `1` become `1`.

## Configuration

Every flag defaults to `false`. `.env.example` is the maintained template. A flag is on when its
value is `1`, `true`, `yes`, `y`, or `on`.

### Feature flags

| Env var | Controls |
| --- | --- |
| `BILLING_ENABLED` | Master switch: S2S routes, webhooks, provisioning, reconcile, and the plan projection (`none` while off) |
| `BILLING_S2S_ENABLED` | S2S routes; off gives `401` |
| `BILLING_CHECKOUT_ENABLED` | Checkout; off gives `503` |
| `BILLING_PORTAL_ENABLED` | Portal; off gives `503` |
| `BILLING_SYNC_ENABLED` | Resync queuing (`disabled` while off); the worker runs jobs when this or `STRIPE_SYNC_ENABLED` is on |
| `STRIPE_BILLING_ENABLED` | Required with `BILLING_ENABLED` for Checkout and Portal, and to enable any group capability |
| `STRIPE_WEBHOOKS_ENABLED` | Both webhook routes; off gives `503` |
| `STRIPE_CHECKOUT_ENABLED` | Checkout; off gives `503` |
| `STRIPE_PORTAL_ENABLED` | Portal; off gives `503` |
| `STRIPE_SYNC_ENABLED` | Lets the worker run jobs |

> [!IMPORTANT]
> Checkout and Portal need both `BILLING_ENABLED` and `STRIPE_BILLING_ENABLED`. Stripe
> readiness in `/system/health` treats any one Stripe or billing flag as enabled, so it can
> report `ready` while these routes answer `503`.

### Secrets and keys

| Env var | Purpose |
| --- | --- |
| `BILLING_S2S_BEARER_TOKEN` | The S2S bearer; compared in constant time |
| `BILLING_ID_HMAC_SECRET` | HMAC for provider refs, idempotency keys, webhook event ids, and sync dedupe. Required by the S2S routes and both webhooks |
| `BILLING_PROVIDER_REF_ENCRYPTION_KEY` | Fernet key that encrypts Stripe ids and group credentials |
| `BILLING_PROVIDER_REF_ENCRYPTION_KEY_ID` | Id stored with each ciphertext; 1-128 characters from `A-Z a-z 0-9 . _ : -` |
| `BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON` | JSON object of key id to key for older ciphertext; the active key is added automatically. Default `{}` |
| `BILLING_RETURN_URL_ALLOWLIST` | Allowed return origins ([return URLs](#return-urls)) |

Generate values outside source control and never paste them into tickets or docs.

### Stripe adapter settings

| Env var | Default | Purpose |
| --- | --- | --- |
| `STRIPE_API_VERSION` | `2026-05-27.dahlia` | API version sent to Stripe. Any other value shows as a critical mismatch in health; routes do not block on it |
| `STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS` | `300` | Signature timestamp tolerance; must be positive |
| `STRIPE_ALLOWED_WEBHOOK_EVENTS` | The 9 handled event types | Event types the webhooks process; any other type is answered `ignored_noop` without writes. May list a subset; a type outside the 9 makes Stripe config loading fail. Health reports it as a count |

The installed `stripe` package must be `15.2.1` for health to report the provider ready.

### Retention and worker settings

| Env var | Default | Purpose |
| --- | --- | --- |
| `BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS` | `90` | Must be `0`-`90`. The purge itself always removes deliveries older than 90 days |
| `BILLING_RAW_PAYLOAD_RETENTION_DAYS` | `30` | Must be `0`-`30`. The purge always clears quarantine rows older than 30 days |
| `BILLING_RETENTION_PURGE_INTERVAL_SECONDS` | `3600` | How often the long-running worker purges while sync is enabled; `0` or less disables it |

A retention value outside its range, or any non-integer billing number, makes billing config
loading fail: the S2S routes answer `500` and health reports billing `not_ready`.

### Test and bootstrap settings

| Env var | Purpose |
| --- | --- |
| `RUN_STRIPE_E2E` | Opt-in Stripe sandbox smoke test, default `false` |
| `STRIPE_LIVE_TEST_USER_HASH`, `STRIPE_LIVE_TEST_PROJECT_HASH` | Required once `RUN_STRIPE_E2E` is on |
| `STRIPE_LIVE_TEST_LOOKUP_KEY` | Optional; defaults to `stripe_live_smoke_lookup_key` |
| `PROJECT_HASH`, `BILLING_PROJECT_HASH` | Project the bootstrap script attaches; `BILLING_PROJECT_HASH` wins |
| `BILLING_GROUP_NAME`, `BILLING_GROUP_SEED_JSON`, `BILLING_GROUP_SEED_FILE` | Bootstrap group name and catalog seed |
