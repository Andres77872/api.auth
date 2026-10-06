# Stripe billing architecture

How billing is built: the modules, the tables, how secrets and Stripe ids are protected, how
retries are made safe, the design decisions, and the gaps in the current code. The route
contract is in the [reference](reference.md).

## Components

| Area | Module |
| --- | --- |
| Admin routes (groups, credentials, catalog) | `src/routes/admin_billing.py` |
| S2S routes (catalog, status, Checkout, Portal, purchase, resync) | `src/routes/internal_billing.py` |
| Stripe webhook routes | `src/routes/stripe_webhooks.py` |
| Session `plan` projection | `src/Util/session_plan.py` |
| Billing config, flags, readiness, return URLs | `src/Util/billing/config.py` |
| Encryption, HMAC, fingerprints, bearer compare | `src/Util/billing/security.py`, `src/Util/secret_box.py` |
| Idempotency keys and request hashes | `src/Util/billing/idempotency.py` |
| Status normalization and freshness | `src/Util/billing/status.py` |
| Response redaction | `src/Util/billing/redaction.py` |
| Sync job helpers and backoff | `src/Util/billing/sync.py` |
| Stripe config and readiness | `src/Util/stripe/config.py` |
| Stripe SDK wrapper | `src/Util/stripe/client.py` |
| Per-group account and secrets | `src/Util/stripe/account.py` |
| Credential validation | `src/Util/stripe/credentials.py` |
| Checkout and Portal sessions | `src/Util/stripe/checkout.py`, `src/Util/stripe/portal.py` |
| Catalog provisioning, reconcile, import | `src/Util/stripe/provisioning.py`, `src/Util/stripe/catalog_sync.py` |
| Webhook verification and classification | `src/Util/stripe/webhooks.py`, `src/Util/stripe/classifier.py` |
| Source-of-truth reads | `src/Util/stripe/sync.py` |
| Rate limits | `src/Util/stripe/rate_limit.py` |
| Stored-procedure wrappers | `src/Util/db/db_billing.py` |
| Sync worker | `src/workers/billing_sync_worker.py` |
| Request and response models | `src/Util/Models.py` |
| Schema | `schemas/tables/12_billing_provider_facts.sql`, `schemas/stored_procedures/17_billing_provider_facts.sql`, `schemas/stored_procedures/18_billing_groups.sql`, `schemas/triggers/07_billing_provider_facts_triggers.sql` |
| Bootstrap | `scripts/migrations/billing_provider_bootstrap.py`, `scripts/migrations/billing_group_bootstrap.py` |

```text
Consuming service ── S2S bearer ──> internal_billing ──┐
Admin UI ── access token ──> admin_billing ────────────┼──> db_billing ──> MySQL billing_* tables
Stripe ── signed webhook ──> stripe_webhooks ──────────┘
   ^                                   │
   └── per-group Stripe client <───────┴── internal_billing, admin_billing, sync worker
Consumer login / validate ──> session_plan ──> sp_billing_get_session_plan
```

## Data model

Fifteen `billing_*` tables and the `v_user_billing_group_access` view.

| Table | Holds | Key |
| --- | --- | --- |
| `billing_providers` | Provider registry (`stripe`), seeded by the bootstrap script | Provider code |
| `billing_groups` | Group, status, capabilities, encrypted credentials, catalog sync status | `billing_group_hash`; a webhook secret HMAC is unique per provider |
| `billing_group_projects` | Project to group mapping, `active` or `removed` | One row per project |
| `billing_catalog_items` | Plans and packages, encrypted Stripe Product and Price ids, `features`, `metadata` | `catalog_item_hash`; one active item per plan code in a group |
| `billing_customers` | Encrypted Stripe customer id | One active customer per user, group, provider; `customer_ref` |
| `billing_checkout_intents` | Checkout requests with key HMAC, request hash, stored response | `checkout_ref`; one active key per scope |
| `billing_subscriptions` | Encrypted Stripe subscription id and its latest status | `subscription_ref`; one active per user, group, provider |
| `billing_subscription_snapshots` | Each observation of a subscription | Subscription and payload hash |
| `billing_entitlements_current` | The current subscription fact read by S2S and the plan | User, group, provider |
| `billing_entitlement_history` | Every subscription transition | Append-only |
| `billing_purchase_events` | Current one-time purchase fact with encrypted payment ids | `purchase_ref` |
| `billing_purchase_history` | Every purchase transition | Append-only |
| `billing_webhook_deliveries` | Delivery ledger: event id HMAC, body SHA-256, status | Provider, group, event id HMAC |
| `billing_sync_jobs` | Resync queue with leases and backoff | Active dedupe HMAC |
| `billing_raw_payload_quarantine` | Encrypted raw evidence; nothing writes to it today | Provider and payload hash |

Subscriptions and customers are scoped to the billing group, so one subscription covers every
project in the group. Purchases keep both the project and the group, and the purchase read
matches on the project.

Database triggers keep the invariants the routes rely on: group hash and provider cannot
change, `active` credentials need a secret-key ciphertext and key id, and all four capability
flags are forced off while the group or its credentials are not `active`.

## Secrets and Stripe ids

- Stripe ids (customer, subscription, Price, Product, payment intent, charge, Checkout Session)
  and group credentials are stored as Fernet ciphertext with the key id that encrypted them.
  Decryption happens in memory for one request; decrypted secrets are not cached.
- Each Stripe id also gets an HMAC-SHA256 with `BILLING_ID_HMAC_SECRET` over provider, kind, and
  id. The HMAC supports uniqueness and joins; its first 12 hex characters are the fingerprint
  that admin responses show (`provider_price_fingerprint`, `secret_key_fingerprint`).
- Consumers only ever see opaque refs (`bcust-`, `bco-`, `bsub-`, `bpur-`, `bpo-`); responses
  are also passed through the [redaction step](reference.md#response-redaction).
- Server-only lookups match a Stripe id to a stored row by its HMAC (webhook attribution, and
  the sync worker labelling a fetched subscription), so no Stripe id is ever stored or
  compared in clear.
- New writes use `BILLING_PROVIDER_REF_ENCRYPTION_KEY`; older ciphertext is read with the key
  named by its key id from `BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON`. A missing key fails the
  operation closed. The repository ships no bulk re-encryption job; saving credentials
  re-encrypts that group's kept values. Procedure:
  [runbook](../../RUNBOOKS/stripe-billing.md#key-rotation).
- Changing `BILLING_ID_HMAC_SECRET` changes every HMAC, which breaks webhook dedupe, idempotency,
  and ref matching for existing rows.
- `src/Util/secret_box.py` is the shared cipher; OAuth uses it with its own keys.

## Per-group Stripe accounts

Each group has its own Stripe account. Every Stripe call (Checkout, Portal, provisioning,
reconcile, import, worker reads) builds a client from that group's decrypted secret key and
`STRIPE_API_VERSION`. Webhook URLs select exactly one group and its stored signing secret.

## Idempotency and deduplication

| Layer | Mechanism |
| --- | --- |
| Checkout | In-process cache plus `billing_checkout_intents`: HMAC of the scoped key, SHA-256 of the canonical body, stored safe response |
| Portal | In-process cache only |
| Stripe API | Idempotency keys derived from internal refs and the operation name; price rotations add a nonce so repricing twice within Stripe's 24-hour key window works |
| Webhooks | `billing_webhook_deliveries` keyed by group and event id HMAC, plus an in-process set |
| Sync jobs | Unique active dedupe HMAC per job scope |

The in-process caches are per server process. With several workers or replicas, only the
database layers deduplicate.

## Webhook processing

Verification runs on the exact raw bytes before any parsing. Every verified event is written to
the delivery ledger before classification, so duplicates are cheap to detect. The classifier is
pure (no I/O) and maps only the 9 handled event types (narrowed by
`STRIPE_ALLOWED_WEBHOOK_EVENTS`); everything else is acknowledged without writes. Checkout puts
the user, project, and `api_auth_*` refs on the Checkout Session and copies them onto the
Subscription or PaymentIntent it creates, so subscription, invoice, and refund events carry
them too. Events without them (disputes, objects created before that copy existed) are
attributed through rows already stored, matched by the Checkout ref or by the HMAC of the
subscription, payment intent, charge, or customer id
([reference](reference.md#attribution)). An event that matches no user writes nothing.
Subscription writes run in one transaction that updates the subscription row, appends a
snapshot, upserts the current fact, and appends history; the user's derived `session_full:*`
validation cache is then dropped so the next validation recomputes the `plan`. The `session:*`
access sessions are kept, so a plan change does not sign the user out.

## Sync worker

The worker claims due jobs, reads the job's local context (`sp_billing_get_sync_context`: the
encrypted Stripe ids and the rows they belong to), fetches the object from Stripe with the
group's key, and writes it back through the same procedures webhooks use, with
`sync_source` `api_pull` ([request flow](request-flow.md#sync-worker)). A subscription job
fetches its subscription; a purchase job fetches its charge (or payment intent and its latest
charge). A user-level job, which is what the S2S resync route queues, lists the user's Stripe
customer's subscriptions and writes the current one (live over ended, newest first). A user
with no Stripe customer has nothing to repair and the job completes. The worker runs jobs
when `BILLING_SYNC_ENABLED` or `STRIPE_SYNC_ENABLED` is on, and runs the retention purge on
its interval only while it is processing jobs; use `--mode retention_only` otherwise.

## Retention

| Data | Retention |
| --- | --- |
| Webhook delivery ledger | Deleted after 90 days by `sp_billing_retention_purge` |
| Raw payload quarantine | Ciphertext cleared after at most 30 days; nothing writes it today |
| Subscription and purchase history, snapshots | Kept indefinitely |
| Catalog, customers, intents | Kept until the group is deleted |

The purge windows are fixed in SQL; the env values are only validated against the caps.

## Health

`GET /system/health` (valid access session) reports `billing`, `billing_provider_stripe`,
`billing_webhooks`, and `billing_sync` components with key names and counts only.
`billing_provider_stripe.per_group` counts groups by credential state; it is `not_ready`
(`no_group_credentials_active`) when groups exist but none has active credentials, and
`degraded` (`group_webhook_secret_missing`) when an active group with `webhooks_enabled` has no
webhook secret. Stripe readiness requires `stripe==15.2.1` and `STRIPE_API_VERSION`
`2026-05-27.dahlia`; the routes themselves do not consult readiness. Disabled billing never
degrades the overall status.

## Design decisions

| Decision | Reason |
| --- | --- |
| Billing facts live behind S2S routes, not in tokens or sessions | Payment state changes independently of login; only the small `plan` projection is added to identity responses, computed at response time |
| The billing group is the unit | Several apps can share one Stripe account and one subscription |
| `api.auth` owns the catalog and creates Stripe Products and Prices | One source of truth for prices; consumers read it instead of hard-coding Stripe ids |
| `features` and labels are opaque | `api.auth` stays out of product rules; consumers interpret them |
| Credentials are write-only, per group, and checked against Stripe before storing | A wrong or foreign key is caught at save time and secrets never leave the server |
| The Portal is restricted to cancellation and payment-method updates | Plan changes go through Checkout, where the consumer controls eligibility |
| Consumers pull; there are no outbound callbacks | Consumers read facts when they need them and own their retries |
| Billing tables are separate from the Patreon tables | Patreon routes and data are unaffected |

## Known gaps

Behavior of the current code that consumers and operators must plan around.

| Gap | Effect |
| --- | --- |
| Checkout does not bind `price_ref` and labels to the catalog | A trusted caller can charge any price in the group's Stripe account under any label |
| Billing activity is not persisted | `act-cat-091` to `act-cat-106` exist in the runtime constants but not in the SQL seed, and no billing code path writes activity rows |
| Nothing sets `stale_after` | Facts never go `stale` by time; a missed webhook is repaired only by a resync |
| A webhook whose facts cannot be written (database down) is still answered `200` | Stripe does not redeliver it; the resync job that would repair it is lost with the same outage. Resend the event from Stripe or request a resync |
| A credit purchase whose `checkout.session.completed` was never recorded has no purchase row | Its later refund or dispute cannot be attributed. Resending the Checkout event recreates the row ([runbook](../../RUNBOOKS/stripe-billing.md#repairing-facts-recorded-before-the-webhook-fixes)) |
| The S2S resync repairs the subscription only | Purchase facts are repaired by the purchase jobs webhooks queue |
