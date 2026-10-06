# Stripe billing troubleshooting

Symptom, cause, and fix. Share only key names, statuses, counts, and opaque refs in tickets;
never paste Stripe keys, webhook secrets, signatures, the S2S bearer, or request bodies.

## S2S calls

### Every S2S call returns 401

The route answers `401` `Unauthorized.` until all of these hold:

- `BILLING_ENABLED` and `BILLING_S2S_ENABLED` are on;
- `BILLING_S2S_BEARER_TOKEN` and `BILLING_ID_HMAC_SECRET` are set;
- the caller sends `Authorization: Bearer <BILLING_S2S_BEARER_TOKEN>` exactly. A user access
  token, a cookie, or an API key is never accepted.

Fix the missing setting or the caller's token, then reload the app.

### An S2S call returns 400

The request failed schema validation before the bearer was checked. Common causes: missing
`project_hash`; an unknown body field; `provider` other than `stripe`; `quantity` outside
1-10000; a `plan_code`, `tier_code`, `tier_name`, `credit_product_code`, or `client_intent_ref`
that contains a Stripe-id-shaped token such as `sub_basic` or `in_app`. Rename such codes in
the catalog.

### S2S calls return 500

- A billing setting fails to parse: a retention value above its cap (`90` or `30`) or a
  non-integer billing number breaks every S2S route; `STRIPE_ALLOWED_WEBHOOK_EVENTS` listing an
  event outside the handled 9 breaks Checkout, Portal, and the webhooks. `/system/health` shows
  the failing component `not_ready` with an `error`.

### Checkout or Portal returns 503

- `BILLING_RETURN_URL_ALLOWLIST` is empty. An
  empty allowlist allows no return URL, so every Checkout and Portal request is refused. Set the
  consuming apps' origins and reload.
- One of the four flags is off. Checkout needs `BILLING_ENABLED`, `BILLING_CHECKOUT_ENABLED`,
  `STRIPE_BILLING_ENABLED`, and `STRIPE_CHECKOUT_ENABLED`; Portal needs `BILLING_PORTAL_ENABLED`
  and `STRIPE_PORTAL_ENABLED` in place of the Checkout pair. `STRIPE_BILLING_ENABLED` is the one
  most often missed, because Stripe health reports `ready` without it.
  `GET /admin/billing/{group_hash}` lists missing flags under `readiness.missing`.
- Checkout only: the group's credentials cannot be decrypted (the key id they were saved under is
  neither the active key id nor in `BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON`); the lookup key
  matches no active price in the group's Stripe account; or `BILLING_PROVIDER_REF_ENCRYPTION_KEY`
  or its id is missing when the user's first customer is created.
- Portal only: the portal configuration in Stripe was changed and now allows subscription
  updates, or no longer allows cancellation or payment-method updates.
- Stripe was unreachable or rejected the call. A Stripe error with its own status (such as `401`
  for a revoked key) is returned with that status.

### Checkout or Portal returns 422

Read `GET /admin/billing/{group_hash}` first; most causes show in `readiness.missing`.

- The project is not attached to a billing group, or the group is `suspended` or `archived`.
- The group's credentials are not `active`, or `checkout_enabled` (`portal_enabled`) is off.
  Suspending a group turns every capability off, and reactivating does not turn them back on.
- The user has no access to the project; the route cannot tell this apart from a missing group.
- Checkout: `plan_code` and `tier_code` missing for `subscription`, or `credit_product_code`
  missing for `credit_purchase`.
- A return URL's origin is not in `BILLING_RETURN_URL_ALLOWLIST` (compare scheme, host, and
  port).
- The `Idempotency-Key` (or `client_intent_ref`) has a character outside `A-Z a-z 0-9 . _ : -`
  or more than 128 characters.
- Portal: the user has never started a Checkout in this group, so there is no Stripe customer;
  the group has no portal configuration id; or its credentials cannot be decrypted.

### Checkout returns 409

The idempotency key was already used with a different body. Any change counts, including the
return URLs and `client_intent_ref`. Send a new key for a new intent; resend the identical body
to get the stored response.

### Status read returns free for a paying user

Compare with the `plan` from `/auth/validate` for the same user and project; both read the same
stored fact.

- Both show `free` (or `pending`): no fact for the paid subscription was written. See
  [subscription stays pending](#subscription-stays-pending-after-checkout), then
  [request a resync](usage.md#queue-a-resync).
- Only the S2S read shows `free`: the server runs a build from before customer refs `bcust-...`
  and `bcustref-...` were accepted by the response model; deploy the current code.
- Both show `none` or `free` and the user never paid: expected.

### Catalog read returns empty lists

- The project is not attached to a group, or was detached.
- No item is both `active` and `provisioning_status` `active`: items saved while provisioning
  was not allowed stay `pending`, failed provisioning leaves `failed`, archived items are hidden.
- `item_type` is misspelled; only `subscription_plan` and `credit_package` match.
- The database call failed; the route returns empty lists instead of an error.

### Values come back as `***FILTERED***`

The S2S redaction step masks Stripe-id-shaped tokens, Stripe secrets, and 64-character hex
tokens outside `user_hash`, `project_hash`, and `billing_group_hash` (which come back
verbatim). Catalog labels, lookup keys, or `features` values starting with `sub_`, `in_`,
`price_`, and the like are masked; rename them. `features` key names are never masked.

### Purchase read returns 404

- Stripe has not delivered `checkout.session.completed` yet, or the webhook failed (check the
  endpoint's deliveries in Stripe).
- `project_hash` is not the project the purchase was made in, or `user_hash` is another user's.
- The purchase was paid in a group whose webhook is not configured, so nothing was recorded.

### Resync never changes anything

- `status` `disabled`: `BILLING_SYNC_ENABLED` is off.
- Nothing processes jobs: `src/workers/billing_sync_worker.py` is not running, or neither
  `BILLING_SYNC_ENABLED` nor `STRIPE_SYNC_ENABLED` is on. Check `billing_sync` in health.
- The job completed with `last_error_redacted` `no_provider_refs`: the user has no Stripe
  customer in the project's billing group (never started a Checkout there), so there is
  nothing to fetch. `no_provider_subscription`: the customer has no subscription in Stripe.
- The job failed with `missing_local_customer` or `missing_local_scope`: the worker could not
  read the job's local context. Usually `schemas/stored_procedures/17_billing_provider_facts.sql`
  was not re-applied after upgrading, so `sp_billing_get_sync_context` and
  `sp_billing_resolve_event_scope` are missing ([runbook](../../RUNBOOKS/stripe-billing.md#repairing-facts-recorded-before-the-webhook-fixes)).
- The job failed with `provider_object_owned_by_another_user`: the Stripe subscription is
  already recorded for a different user. Investigate before changing anything.
- The job is in `retry` with `fact_write_failed`: the database write failed; the worker retries
  with backoff.

### An S2S call returns 429

A fixed-window limit was hit ([rate limits](reference.md#rate-limits)); wait for `Retry-After`.
Checkout counts per `client_intent_ref` as well, and resync per `reason`. If Redis is down, no
limit is applied.

## Webhooks

### Stripe shows 503 from the endpoint

Nothing is recorded; Stripe retries.

- `BILLING_ENABLED` or `STRIPE_WEBHOOKS_ENABLED` is off, or `BILLING_ID_HMAC_SECRET` is empty.
- Path-scoped route: the group hash in the URL is wrong, the group is not `active`,
  `webhooks_enabled` is off, its credentials are not `active`, or it has no webhook secret (or
  the secret cannot be decrypted). These look identical from outside; check the group with
  `GET /admin/billing/{group_hash}`.

### Stripe shows 401 from the endpoint

- The signing secret stored for the group is not the endpoint's current secret. Save the
  endpoint's secret as `webhook_secret` ([usage](usage.md#connect-the-stripe-webhook)).
- A proxy changed the body (re-encoding, reformatting). The signature covers the exact bytes.
- The server clock is more than `STRIPE_WEBHOOK_SIGNATURE_TOLERANCE_SECONDS` off.
- The Stripe endpoint uses an API version other than `2026-05-27.dahlia`; every event is
  rejected. Change the endpoint's API version in Stripe.
- Give each account its group-scoped URL and store its own signing secret.

Repeated failures from one IP turn into `429` for the rest of the window.

### Webhooks return 200 but facts do not change

Read the `status` in the response body that Stripe shows for the delivery:

- `ignored_noop`: the event type is not one of the 9 handled types, or not listed in
  `STRIPE_ALLOWED_WEBHOOK_EVENTS`.
- `duplicate_replay_accepted`: the same event id was already received for this group.
- `accepted`: processed; or the event could not be tied to a user (no usable `user_hash` and
  `project_hash` metadata and no stored row matching its Checkout ref or Stripe ids), in which
  case nothing is written or queued. For `customer.subscription.*`, a bare `plan_code` metadata
  value (set outside api.auth) that does not appear in the price's lookup key writes `unknown`
  instead of the Stripe status.

### Subscription stays pending after checkout

`checkout.session.completed` writes the subscription as `pending`; the following
`customer.subscription.created`/`updated` or `invoice.paid` moves it to its Stripe status.
If it stays `pending`:

- The Stripe endpoint is not subscribed to `customer.subscription.*` and `invoice.*`, or
  `STRIPE_ALLOWED_WEBHOOK_EVENTS` leaves them out (their deliveries answer `ignored_noop`).
- Those deliveries failed in Stripe; resend them from the Stripe Dashboard.
- The subscription was created before Checkout copied its metadata onto subscriptions. Its
  events are then attributed through the user's stored Stripe customer; if that customer row is
  missing too, [request a resync](usage.md#queue-a-resync) or resend the events.

## Admin

### Creating a group returns 503 with `EXT_8200`

The provider registry has no `stripe` row. Run
`scripts/migrations/billing_provider_bootstrap.py --apply` (dry-run first).

### Enabling a capability returns 400

`details.missing` names each unmet prerequisite ([capabilities](reference.md#capabilities)).
Global names (`BILLING_ENABLED`, `STRIPE_BILLING_ENABLED`, ...) need a config change and reload;
group names need a credential save (`stripe_secret_key`, `stripe_webhook_secret`,
`stripe_portal_configuration_id`), a status change (`billing_group_active`), or a provisioned
catalog item (`active_catalog_price`).

### Saving credentials returns 400

- `secret_key` does not start with `sk_` or `rk_`, `webhook_secret` with `whsec_`, or
  `portal_configuration_id` with `bpc_`.
- Stripe rejected the key, or could not be reached; the save fails closed.
- The portal configuration does not exist in that account or is not restricted (`EXT_8211`).
- `BILLING_PROVIDER_REF_ENCRYPTION_KEY`, its id, or `BILLING_ID_HMAC_SECRET` is missing.
- A stored optional value you omitted cannot be decrypted with the configured keys; send it
  again or send `""` to clear it.

### A catalog item is pending or failed

- `pending`: provisioning was not allowed when the item was created (`BILLING_ENABLED` off, or
  the group lacked `provisioning_enabled` or `active` credentials). Allow provisioning, then send
  the item's `amount_cents` again with `PUT .../catalog/{item_hash}`.
- `failed`: read `provisioning_error`. Common causes are a missing `amount_cents` or `currency`,
  missing encryption keys, another active item with the same `plan_code`, or a Stripe error.

### An admin user gets 403 on a group

Admin users manage only groups whose every attached project they administer, or empty groups
they created. A group shared with another admin's project is out of scope; a root user must
manage it. Consumer users get `403` whatever their permissions.

### Deleting a group returns 409

A subscription in the group is `trialing`, `active`, `past_due`, `unpaid`, or `paused`. Suspend
the group instead (`PUT /admin/billing/{group_hash}` with `status=suspended`).

### Attaching a project returns 409

The project is attached to another group. Detach it there first.

## Health and plan

### Health reports Stripe ready but Checkout returns 503

Stripe readiness counts any billing or Stripe flag as enabled. Check `BILLING_ENABLED` and
`STRIPE_BILLING_ENABLED` by name.

### The plan is missing or none

- Missing (`plan` null or absent): the session is not a consumer project session (root, admin,
  platform scope), or the response is `POST /auth/switch-project`, which never carries it.
- `none`: `BILLING_ENABLED` is off, or the project is not attached to an active billing group.
