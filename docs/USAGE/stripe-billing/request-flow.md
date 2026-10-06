# Stripe billing request flow

What each billing route does, in order, from the first check to the response. Status codes are
listed where a step can end the request. Field and error details are in the
[reference](reference.md).

## S2S pipeline

Every `/internal/.../billing` route runs these steps first.

1. Platform middleware checks run first
   ([platform contracts](../README.md#platform-wide-contracts)).
2. FastAPI validates the path, query, and JSON body against the request model (`400`, standard
   envelope). This happens before any credential is read.
3. The handler reads `Authorization: Bearer ...` itself. It returns `401` unless
   `BILLING_ENABLED`, `BILLING_S2S_ENABLED`, `BILLING_S2S_BEARER_TOKEN`, and
   `BILLING_ID_HMAC_SECRET` are all set and the token matches in constant time. No session,
   cookie, or API-key dependency is involved.
4. A blank `User-Agent` returns `422`.
5. Route-specific pre-checks (below), then the route's rate-limit bucket (`429` with
   `Retry-After`; skipped when Redis is unavailable).
6. The handler runs.
7. The response model is dumped with only its allow-listed fields, passed through the
   [redaction step](reference.md#response-redaction), and checked for forbidden field names.

```text
platform middleware -> schema (400) -> bearer + flags (401) -> blank UA (422)
  -> route pre-checks -> rate limit (429) -> handler -> allow-list + redaction -> response
```

## Catalog read

1. S2S pipeline with the S2S bucket, counted without a user.
2. `sp_billing_catalog_list_for_project` joins the project's active group mapping to catalog
   items that are `active` with `provisioning_status` `active`, filtered by `item_type`.
3. Rows are split into `subscriptions` and `credit_packs`; `features.credits` becomes `credits`.
   A database error yields empty lists.

## Billing status read

1. S2S pipeline with the S2S bucket.
2. `sp_billing_get_current_by_user_project` checks the user's access to the project, resolves the
   project's billing group, and reads the current subscription fact for the user and group,
   with the customer and subscription refs.
3. The row is normalized: a passed `stale_after` turns an active-like status into `stale`, and
   `plan_code` becomes `free` for non-paying statuses.
4. Any error while reading or building the model returns the free default instead.
5. The response passes the [redaction step](reference.md#response-redaction); `user_hash` and
   `project_hash` come back as sent.

## Checkout

1. S2S pipeline.
2. Label check (`plan_code` and `tier_code` for `subscription`, `credit_product_code` for
   `credit_purchase`): `422`. Return-URL check: `503` while the allowlist is empty, `422` for an
   origin outside it.
3. Checkout rate-limit bucket: `429`.
4. Scope: `sp_billing_resolve_user_billing_group`, falling back to
   `sp_billing_resolve_user_project`. An unresolved user or project gets a placeholder scope that
   fails the group check in step 8.
5. New refs are generated: `bco-...`, plus `bsub-...` or `bpur-...`.
6. Idempotency key from `Idempotency-Key` or `client_intent_ref`: malformed gives `422`. The
   in-process cache returns `409` for a different body or the stored response with `200`.
7. `sp_billing_checkout_intent_begin` records the intent with HMACs of the key and the price
   ref: `409` on conflict, `200` with the stored response on replay. If the database call fails,
   the request continues without the database record.
8. Gates: `BILLING_ENABLED`, `BILLING_CHECKOUT_ENABLED`, `STRIPE_BILLING_ENABLED`,
   `STRIPE_CHECKOUT_ENABLED` (`503`); then the group must exist and be `active`, with `active`
   credentials, a stored secret key, and `checkout_enabled` (`422`).
9. A Stripe client is built with the group's decrypted secret key and `STRIPE_API_VERSION`:
   `503` on failure.
10. The user's Stripe customer for the group is loaded, or created with metadata `user_hash`,
    `project_hash`, and `api_auth_customer_ref`; its id is stored encrypted through
    `sp_billing_customer_upsert`.
11. A lookup key is resolved to the account's active price, and the Checkout Session is created
    with mode `subscription` or `payment`, the customer, one line item, the return URLs,
    `client_reference_id` set to the checkout ref, and metadata carrying `user_hash`,
    `project_hash`, the `api_auth_*` refs, and the `consumer_*` labels. The same metadata goes
    into `subscription_data.metadata` (subscription) or `payment_intent_data.metadata`
    (payment), so the Subscription or PaymentIntent, and the charges it makes, carry it too.
    Stripe errors return `503` or the Stripe status.
12. The response is cached in memory and stored with the encrypted session id through
    `sp_billing_checkout_intent_complete`.
13. `202` with `url` and the refs.

## Portal

1. S2S pipeline.
2. Return-URL check: `503` while the allowlist is empty, `422` for an origin outside it.
3. Portal rate-limit bucket: `429`.
4. Scope as in Checkout; a new `bpo-...` ref.
5. `Idempotency-Key` check against the in-process cache only: `422`, `409`, or `200`.
6. Gates: `BILLING_ENABLED`, `BILLING_PORTAL_ENABLED`, `STRIPE_BILLING_ENABLED`,
   `STRIPE_PORTAL_ENABLED` (`503`); then the group checks as in Checkout plus `portal_enabled`
   and a stored portal configuration id (`422`).
7. The user's existing Stripe customer and the group's decrypted secrets are loaded: `422` when
   the customer does not exist yet or the secrets cannot be decrypted.
8. The portal configuration is fetched from Stripe and must pass the
   [restricted-portal check](reference.md#restricted-portal-configuration): `503` otherwise.
9. The Portal session is created with the customer, the configuration, and `return_url`.
10. `202` with `url` and `portal_ref`.

## Purchase read

1. S2S pipeline with the S2S bucket.
2. `sp_billing_get_purchase_status_by_ref` matches `purchase_ref`, the user, and the project the
   purchase was made in.
3. `pending` or `paid` past `stale_after` reads `stale`.
4. `200` with `purchase`, or `404` for no row or any error.

## Resync

1. S2S pipeline; the body is any JSON object.
2. Missing `project_hash`: `422`.
3. Resync rate-limit bucket (keyed with `reason`): `429`.
4. `BILLING_SYNC_ENABLED` off: `202` `disabled`.
5. `sp_billing_sync_job_enqueue` adds a `webhook_resync` job (priority `1` with `force`, else
   `5`) with a dedupe HMAC over user, project, group, and reason.
6. `202` `queued` with `correlation_id`, or `degraded` when the insert failed. The job carries
   the user, project, and billing group; the [sync worker](#sync-worker) resolves what to fetch
   from them.

## Stripe webhook

### Path-scoped route

1. Read the raw body and `Stripe-Signature` before any parsing.
2. `BILLING_ENABLED` and `STRIPE_WEBHOOKS_ENABLED` on, `BILLING_ID_HMAC_SECRET` set: else `503`.
3. Load the group by `billing_group_hash`. It must be `active` with `webhooks_enabled`, and its
   credentials must be `active` and decrypt to a webhook secret: else `503`, with nothing
   recorded.
4. Verify with the Stripe SDK against that one secret and the timestamp tolerance; require an
   event `id` and, when present, `api_version` `2026-05-27.dahlia`. Any failure: `401`, counted
   per IP (`429` over the limit).
5. Resolve the user and project from the event object's metadata (an invoice's from its
   subscription's), then match the Checkout ref and the HMACs of the event's subscription,
   payment intent, charge, customer, and price ids against stored rows through
   `sp_billing_resolve_event_scope` ([attribution](reference.md#attribution)).
6. Record the delivery through `sp_billing_webhook_delivery_record`, keyed by group and an HMAC of
   the event id. A repeat returns `200` `duplicate_replay_accepted`.
7. A type not listed in `STRIPE_ALLOWED_WEBHOOK_EVENTS` returns `200` `ignored_noop`. Classify
   the event ([event handling](reference.md#event-handling)). An unhandled type returns `200`
   `ignored_noop`; a classifier error queues a resync and returns `200` `accepted`.
8. Write the fact when a user was resolved, under the refs and labels from the metadata or the
   matched rows:
   - subscription: upsert the customer (encrypted id), then `sp_billing_subscription_observe`
     writes the subscription row, a snapshot, the current fact, and a history row in one
     transaction (period dates the event does not carry keep their stored values); the user's
     `session_full:*` validation cache is dropped (access sessions are kept);
   - purchase (needs the project too): upsert the customer, then
     `sp_billing_purchase_event_record` writes the current purchase and a history row.
9. When the classification asks for a resync, or a resolved user's fact was not written, queue
   a sync job (priority `3`). An event resolved to no user queues nothing.
10. `200` `accepted`.

## Admin routes

1. `HTTPBearerOrCookie` reads the access token from the header or the `access_token` cookie;
   the session must be valid (`401`).
2. The session needs `admin` or `manage_billing` (`403`).
3. Group routes resolve the caller's scope: root, or an admin user with assigned projects;
   consumers get `403`. The group is loaded by hash (`404`), then checked against the scope
   (`403`). Credential writes instead require a root user.
4. The handler calls the stored procedures in `schemas/stored_procedures/18_billing_groups.sql`.

### Credential save

1. Encryption material present (`400` otherwise).
2. Omitted optional values are decrypted from the stored credentials (`400` if they cannot be).
3. Prefix checks, a live `retrieve account` call to Stripe with the new key, and, when a portal
   configuration id will be stored, a fetch and restricted-portal check (`400`).
4. Each value is encrypted with the active key and HMACed; `sp_billing_group_set_credentials`
   stores them and sets `credential_status` `active`.

### Catalog item create and reprice

1. `item_type`, `features`, and `metadata` validation (`400`).
2. `sp_billing_catalog_item_create` stores the item as `pending`.
3. If `BILLING_ENABLED` is on and the group has `provisioning_enabled` and `active` credentials,
   the Stripe Product and Price are created on the group's account with idempotency keys derived
   from the item id, and `sp_billing_catalog_item_set_provisioned` stores their encrypted ids
   and activates the item. Failures call `sp_billing_catalog_item_set_failed`.
4. A reprice (`PUT` with a price field) uses fresh idempotency keys, adds a Price to the stored
   Product, stores it, then deactivates the old Price.

### Capability change

Each flag being turned on is checked against its [prerequisites](reference.md#capabilities)
(`400`). `sp_billing_group_set_capabilities` then updates the flags; a database trigger forces
all four off while the group or its credentials are not `active`.

## Session plan projection

1. Consumer login, refresh, `/auth/validate`, or `/auth/validate-api-key` builds its response
   for a project-scoped consumer.
2. `BILLING_ENABLED` off: `state` `none`.
3. `sp_billing_get_session_plan` takes the internal user and project ids, joins the project's
   active group mapping, and reads the current subscription fact.
4. The row is mapped to a [state](reference.md#session-plan-projection). Any error gives `none`;
   authentication never fails because of billing.

## Sync worker

Run with `python -m src.workers.billing_sync_worker`, optionally `--once`,
`--mode queued|retention_only`, `--limit`, and `--worker-id`. Each pass:

1. `retention_only` mode runs only the retention purge.
2. With neither `BILLING_SYNC_ENABLED` nor `STRIPE_SYNC_ENABLED` on, the pass records `disabled`
   and does nothing else.
3. `sp_billing_sync_job_claim` leases up to 25 due jobs for 300 seconds.
4. For each job: `sp_billing_get_sync_context` returns the encrypted Stripe ids and the local
   rows they belong to (for a user-level job, the user's customer and current subscription in
   the group); the group's Stripe client is built.
5. Fetch from Stripe: a subscription job retrieves its subscription; a purchase job its charge,
   or its payment intent and that intent's latest charge; a user-level job (`webhook_resync` or
   `customer`, as the S2S resync route queues) lists the customer's subscriptions and picks
   the current one (live over ended, newest first). No customer and no subscription on record:
   the job completes with `no_provider_refs`.
6. Write the fetched object back with `sync_source` `api_pull`: a subscription through
   `sp_billing_subscription_observe` (row, ref, and labels matched by the subscription HMAC
   through `sp_billing_resolve_event_scope`, else the job's row, else the subscription's
   metadata or its catalog price), after which the user's `session_full:*` validation cache
   is dropped (access sessions are kept); a purchase through `sp_billing_purchase_event_record`
   (`dispute_won` and `dispute_lost` are kept when the charge only says `disputed`).
7. `sp_billing_sync_job_complete` marks it `completed`, `retry` (backoff 60, 300, 900, 3600,
   10800, 21600 seconds, or Stripe's `Retry-After`, up to 8 attempts; a failed write-back
   retries too), or `failed` (for example a subscription already recorded for another
   user).
8. Every `BILLING_RETENTION_PURGE_INTERVAL_SECONDS`, `sp_billing_retention_purge` runs.
9. A heartbeat is written to Redis at `billing_sync_job:heartbeat:<worker_id>` with a 300-second
   TTL. The long-running worker then sleeps 30 seconds.
