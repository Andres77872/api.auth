# Stripe billing usage

Task-by-task calls for setting up billing and for using it from a consuming service. Field rules,
statuses, and every error are in the [reference](reference.md).

The examples use these shell variables:

| Variable | Value |
| --- | --- |
| `BASE_URL` | The `api.auth` base URL |
| `ADMIN_TOKEN` | Access token of a root or admin user whose session has `admin` or `manage_billing` |
| `ROOT_TOKEN` | Access token of a root user (credential writes only) |
| `BILLING_TOKEN` | The value of `BILLING_S2S_BEARER_TOKEN` |
| `GROUP_HASH`, `PROJECT_HASH`, `USER_HASH`, `ITEM_HASH`, `PURCHASE_REF` | Values from earlier responses |

## Prepare the server

1. Set the secrets: `BILLING_S2S_BEARER_TOKEN`, `BILLING_ID_HMAC_SECRET`,
   `BILLING_PROVIDER_REF_ENCRYPTION_KEY`, `BILLING_PROVIDER_REF_ENCRYPTION_KEY_ID`, and
   `BILLING_RETURN_URL_ALLOWLIST` ([secrets and keys](reference.md#secrets-and-keys)). With the
   allowlist empty, Checkout and Portal refuse every request with `503`.
2. Turn on the flags you need. Checkout with webhooks needs:

   ```env
   BILLING_ENABLED=true
   BILLING_S2S_ENABLED=true
   BILLING_CHECKOUT_ENABLED=true
   STRIPE_BILLING_ENABLED=true
   STRIPE_CHECKOUT_ENABLED=true
   STRIPE_WEBHOOKS_ENABLED=true
   ```

   Portal adds `BILLING_PORTAL_ENABLED` and `STRIPE_PORTAL_ENABLED`.
3. Seed the provider registry once. Creating a group fails with `503` `EXT_8200` until this runs:

   ```bash
   ./.venv/bin/python scripts/migrations/billing_provider_bootstrap.py --dry-run
   ./.venv/bin/python scripts/migrations/billing_provider_bootstrap.py --apply
   ```

The [runbook](../../RUNBOOKS/stripe-billing.md) has the full deployment order.

## Create a billing group

`POST /admin/billing`, form fields.

```bash
curl -X POST "$BASE_URL/admin/billing" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "group_name=Magic Worlds" \
  -d "description=Plans shared by the Magic Worlds apps"
```

The response carries `billing_group.group_hash`, with `status` `active`, `credential_status`
`absent`, and every capability off. An admin user keeps managing the group only while every
project attached to it is one it administers.

## Store the group's Stripe credentials

Root only, JSON. Test first; the test calls Stripe and stores nothing:

```bash
curl -X POST "$BASE_URL/admin/billing/$GROUP_HASH/credentials/test" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"secret_key": "<stripe-secret-key>", "portal_configuration_id": "<portal-configuration-id>"}'
```

It returns `valid`, `secret_key_valid`, `portal_configuration_valid`, `livemode`, and
`account_fingerprint`. Then save:

```bash
curl -X PUT "$BASE_URL/admin/billing/$GROUP_HASH/credentials" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"secret_key": "<stripe-secret-key>", "portal_configuration_id": "<portal-configuration-id>", "stripe_account_label": "Magic Worlds"}'
```

- `secret_key` starts with `sk_` or `rk_`, `webhook_secret` with `whsec_`, and
  `portal_configuration_id` with `bpc_`.
- The response shows presence flags and fingerprints only; `credential_status` becomes `active`.
- On later saves, omit a field to keep it and send `""` to clear it. You add the webhook secret
  after creating the Stripe endpoint, in [connect the Stripe webhook](#connect-the-stripe-webhook).

## Attach projects

`POST /admin/billing/{group_hash}/projects`, form field `project_hash`. Repeat for each project
that shares the plans.

```bash
curl -X POST "$BASE_URL/admin/billing/$GROUP_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "project_hash=$PROJECT_HASH"
```

A project attached to another group returns `409`; detach it there first with
`DELETE /admin/billing/{group_hash}/projects/{project_hash}`.

## Build the catalog

1. Allow provisioning, so new items are created in Stripe:

   ```bash
   curl -X PUT "$BASE_URL/admin/billing/$GROUP_HASH/capabilities" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"provisioning_enabled": true}'
   ```

   A `400` lists what is missing in `details.missing`.
2. Create a subscription plan. `features` is a JSON object sent as a string:

   ```bash
   curl -X POST "$BASE_URL/admin/billing/$GROUP_HASH/catalog" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d "item_type=subscription_plan" \
     -d "plan_code=pro" \
     -d "display_name=Pro" \
     -d "tier_code=pro" \
     -d "tier_name=Pro" \
     -d "amount_cents=1500" \
     -d "currency=usd" \
     -d "recurring_interval=month" \
     -d "lookup_key=pro_monthly" \
     --data-urlencode 'features={"max_projects": 5}'
   ```

3. Create a credit package the same way with `item_type=credit_package`, no
   `recurring_interval`, and the credit count in `features`:

   ```bash
   curl -X POST "$BASE_URL/admin/billing/$GROUP_HASH/catalog" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d "item_type=credit_package" \
     -d "plan_code=payg_100" \
     -d "display_name=100 credits" \
     -d "amount_cents=500" \
     -d "lookup_key=payg_100" \
     --data-urlencode 'features={"credits": 100}'
   ```

Each response returns `item` with `provisioning_status` `active` when Stripe accepted it,
`pending` when provisioning was not allowed, or `failed` with a redacted `provisioning_error`.

> [!TIP]
> Keep codes, lookup keys, and `features` values free of Stripe-id-shaped tokens such as
> `sub_...` or `in_...`; the S2S responses mask them
> ([response redaction](reference.md#response-redaction)). `features` key names are free-form.

## Import prices that already exist in Stripe

1. Compare without writing: `GET /admin/billing/{group_hash}/catalog/reconcile`. Unmatched
   Stripe prices are listed in `result.candidates`, each with a `price_fingerprint`.
2. Import the ones you want, optionally renaming their plan codes:

   ```bash
   curl -X POST "$BASE_URL/admin/billing/$GROUP_HASH/catalog/import" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"price_fingerprints": ["<price-fingerprint>"], "plan_code_overrides": {"<price-fingerprint>": "pro"}}'
   ```

3. `POST /admin/billing/{group_hash}/catalog/sync` adopts Stripe prices for local items that
   share a lookup key but lack stored Stripe references, and records `catalog_sync_status`.

## Change a price

Send the new amount to `PUT /admin/billing/{group_hash}/catalog/{item_hash}`. Stripe prices are
immutable, so a new Price is created and the old one is deactivated after the new one is stored.

```bash
curl -X PUT "$BASE_URL/admin/billing/$GROUP_HASH/catalog/$ITEM_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "amount_cents=1900"
```

The same call provisions an item left `pending` earlier: send its current `amount_cents` once
provisioning is allowed. To withdraw an item, archive it with
`DELETE /admin/billing/{group_hash}/catalog/{item_hash}`; nothing changes in Stripe.

## Connect the Stripe webhook

1. Read `readiness.webhook_endpoint_path` from `GET /admin/billing/{group_hash}`. It is
   `/webhooks/stripe/<group_hash>`.
2. In the group's Stripe account, create a webhook endpoint at `$BASE_URL` plus that path, with
   API version `2026-05-27.dahlia` and the 9 [handled events](reference.md#event-handling).
3. Save its signing secret. Omitted fields keep their stored values, but `secret_key` is always
   required:

   ```bash
   curl -X PUT "$BASE_URL/admin/billing/$GROUP_HASH/credentials" \
     -H "Authorization: Bearer $ROOT_TOKEN" \
     -H "Content-Type: application/json" \
     -d '{"secret_key": "<stripe-secret-key>", "webhook_secret": "<stripe-webhook-signing-secret>"}'
   ```

4. Enable the capability: `PUT .../capabilities` with `{"webhooks_enabled": true}`. Until then
   the endpoint answers `503` and Stripe retries.

## Enable Checkout and Portal

```bash
curl -X PUT "$BASE_URL/admin/billing/$GROUP_HASH/capabilities" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"checkout_enabled": true, "portal_enabled": true}'
```

Checkout needs at least one active, provisioned catalog item; Portal needs a stored portal
configuration id. `GET /admin/billing/{group_hash}` lists anything still missing under
`readiness.missing`. Suspending or archiving the group turns every capability off; enable them
again after reactivating it.

## Read the catalog from a consuming service

```bash
curl "$BASE_URL/internal/projects/$PROJECT_HASH/billing/catalog" \
  -H "Authorization: Bearer $BILLING_TOKEN"
```

Render `subscriptions` and `credit_packs`. Send an item's `provider_price_lookup_key` and codes
to Checkout unchanged. The response also carries `project_hash` and the group's
`billing_group_hash`.

## Start a checkout

```bash
curl -X POST "$BASE_URL/internal/users/$USER_HASH/billing/checkout" \
  -H "Authorization: Bearer $BILLING_TOKEN" \
  -H "Content-Type: application/json" \
  -H "Idempotency-Key: upgrade-7f3a" \
  -d '{"project_hash": "'"$PROJECT_HASH"'", "intent_type": "subscription", "price_ref": {"ref_type": "lookup_key", "value": "pro_monthly"}, "plan_code": "pro", "tier_code": "pro", "success_url": "https://app.example.com/billing/success", "cancel_url": "https://app.example.com/billing/cancel"}'
```

- `202` returns `url`, `checkout_ref`, and `subscription_ref` (or `purchase_ref` for
  `intent_type` `credit_purchase` with `credit_product_code`). Redirect the user to `url`.
- Retrying with the same key and body returns the stored response with `200`; a different body
  with the same key returns `409`.
- The outcome arrives later by webhook; read it with the status or purchase routes.

## Open the customer portal

The user needs a Stripe customer in the group, which the first checkout creates.

```bash
curl -X POST "$BASE_URL/internal/users/$USER_HASH/billing/portal" \
  -H "Authorization: Bearer $BILLING_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_hash": "'"$PROJECT_HASH"'", "return_url": "https://app.example.com/account"}'
```

`202` returns `url` and `portal_ref`. The portal allows cancellation and payment-method updates
only.

## Read a user's plan and billing status

For request-time gating, read the `plan` object that `GET /auth/validate` already returns for a
consumer's project session (`state`, `active`, `plan_code`, `tier_code`, period dates). For
detail, call the S2S status route:

```bash
curl "$BASE_URL/internal/users/$USER_HASH/billing?project_hash=$PROJECT_HASH" \
  -H "Authorization: Bearer $BILLING_TOKEN"
```

It returns `billing.status`, `plan_code`, period dates, `cancel_at_period_end`, and the opaque
`customer_ref` and `subscription_ref`. It reads the same stored fact as the `plan`. Read the
[known gaps](architecture.md#known-gaps) before relying on it.

## Grant credits for a purchase

After Checkout for a credit package, poll the purchase with the `purchase_ref` from the
checkout response:

```bash
curl "$BASE_URL/internal/users/$USER_HASH/billing/purchases/$PURCHASE_REF?project_hash=$PROJECT_HASH" \
  -H "Authorization: Bearer $BILLING_TOKEN"
```

`404` means Stripe has not reported it yet. When `purchase.status` is `paid`, grant the credits
from your copy of the catalog item's `credits`, keyed on `purchase_ref` so a repeat read never
grants twice. Watch later reads for `refunded`, `partially_refunded`, `disputed`, and
`dispute_lost`.

## Queue a resync

```bash
curl -X POST "$BASE_URL/internal/users/$USER_HASH/billing/resync" \
  -H "Authorization: Bearer $BILLING_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_hash": "'"$PROJECT_HASH"'", "reason": "support_ticket", "force": true}'
```

`202` with `status` `queued` and a `correlation_id`, or `disabled` while `BILLING_SYNC_ENABLED`
is off. When the billing sync worker runs the job, it reads the user's subscriptions from Stripe
and writes the current one, so a later status read reflects Stripe. It does not resync
purchases ([sync worker](architecture.md#sync-worker)).
