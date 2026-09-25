# Stripe billing scenarios

End-to-end lifecycles that chain several calls. Each lists the steps, the state they leave
behind, and what the consuming service owns. Requests are in [usage](usage.md); fields and
statuses in the [reference](reference.md).

## Onboard a project for billing

1. Prepare the server and seed the provider registry ([usage](usage.md#prepare-the-server)).
2. Create the group, store its credentials, attach the project
   ([usage](usage.md#create-a-billing-group)).
3. Enable provisioning and create the catalog items ([usage](usage.md#build-the-catalog)).
4. Register the webhook endpoint, save its signing secret, enable `webhooks_enabled`
   ([usage](usage.md#connect-the-stripe-webhook)).
5. Enable `checkout_enabled` and, when a restricted portal configuration is stored,
   `portal_enabled` ([usage](usage.md#enable-checkout-and-portal)).

Check: `GET /admin/billing/{group_hash}` shows `readiness.ready` `true`, and the S2S catalog
read returns the items. Before step 5, a consumer in the project already sees the free default
and `plan.state` `free`; a project without a group sees `plan.state` `none`.

## Subscribe a user

1. The consumer reads the catalog and shows the plans.
2. The user picks one; the consumer calls Checkout with `intent_type` `subscription`, the
   item's lookup key, `plan_code`, `tier_code`, and an `Idempotency-Key`.
3. The consumer redirects the user to `url`.
4. Stripe sends `checkout.session.completed`. The subscription fact is written as `pending` with
   the requested labels; the `plan` reads `free` until a later event sets `trialing` or `active`.
5. `customer.subscription.*` and `invoice.paid` events move the fact to `trialing` or `active`
   and the `plan` to `trial` or `active`. They carry the same metadata as the Checkout Session,
   because Checkout copies it onto the subscription ([attribution](reference.md#attribution)).
   Stripe may deliver `checkout.session.completed` after them; it does not move a live
   subscription back to `pending`.

Each subscription write drops the user's cached `/auth/validate` results so the next validate
recomputes the plan; the user stays signed in. No session, token, or cookie is issued or changed.

## Change plan

The Customer Portal cannot change plans (its configuration must have subscription updates off).
To upgrade or downgrade, the consumer decides eligibility and starts a new Checkout for the new
item with a new idempotency key. `api.auth` does not cancel the previous subscription; handle
that through the Portal or in Stripe.

## Cancel or update the payment method

1. The consumer calls the Portal route and redirects the user to `url`.
2. The user cancels or changes the card in Stripe.
3. `customer.subscription.updated` carries `cancel_at_period_end` `true` while the status stays
   `active`; `customer.subscription.deleted` sets `canceled` and the `plan` to `canceled`.
   Payment-method changes produce no fact of their own.

The consumer decides what access a cancelled user keeps until `current_period_end`.

## Payment failure and recovery

`invoice.payment_failed` sets `past_due` and queues a resync; the `plan` becomes `past_due` with
`active` `false`. A later `invoice.paid` sets `active`. The consumer owns grace periods and
lockout; local authentication is unaffected.

## Sell a credit pack

1. Checkout with `intent_type` `credit_purchase`, the package's lookup key, and
   `credit_product_code` set to the package code. Keep the returned `purchase_ref`.
2. `checkout.session.completed` in `payment` mode records the purchase as `paid` (or `unknown`
   if the session was not complete and paid).
3. The consumer reads the purchase until it is `paid`, then grants the credits in its own
   ledger keyed on `purchase_ref` ([usage](usage.md#grant-credits-for-a-purchase)).

`api.auth` never stores balances or grants credits. Credit packages never appear in the `plan`.

## Refund or dispute a purchase

`charge.refunded` sets `refunded` or `partially_refunded`; `charge.dispute.created` sets
`disputed`; `charge.dispute.closed` sets `dispute_won` or `dispute_lost`. The consumer reads the
new status and applies its own hold or reversal. A refund carries the purchase's metadata
(Checkout sets it on the payment intent, and Stripe copies it onto the charge); a dispute
carries none and is matched to the stored purchase by its charge or payment intent
([attribution](reference.md#attribution)). A purchase must have been recorded from its
`checkout.session.completed` for either to reach it.

## Reprice a plan

1. `PUT /admin/billing/{group_hash}/catalog/{item_hash}` with the new `amount_cents`.
2. A new Stripe Price is created on the same Product with the same lookup key; the old Price is
   deactivated.
3. The catalog read returns the new amount; the lookup key does not change, so consumers need no
   change. `api.auth` does not move existing subscriptions to the new price.

If Stripe rejects the new Price, the item turns `failed` and inactive (it leaves the catalog)
while the old Price stays live. Send the price again to retry.

## Rotate a group's Stripe credentials

1. Roll the key in Stripe.
2. Test it with `POST .../credentials/test`.
3. Save it with `POST .../credentials/rotate` (or `PUT .../credentials`), sending only
   `secret_key`; the stored webhook secret and portal id are kept and re-encrypted under the
   current encryption key.
4. If the webhook signing secret was rolled too, include `webhook_secret`. Until the new secret
   is saved, deliveries fail verification with `401`.

There is no dual-key window: the previous key is discarded at once. Rotating the
`BILLING_PROVIDER_REF_ENCRYPTION_KEY` itself is covered in the
[runbook](../../RUNBOOKS/stripe-billing.md#key-rotation).

## Move a project or retire a group

- Move: detach the project (`DELETE .../projects/{project_hash}`), then attach it to the new
  group. The project's users read the new group's catalog and facts; their subscription in the
  old group is not carried over.
- Pause: set the group `status` to `suspended`. Every capability turns off; webhooks for the
  group get `503`, and Checkout and Portal `422`. Reactivating does not restore capabilities.
- Delete: `DELETE /admin/billing/{group_hash}` succeeds only when no subscription is
  `trialing`, `active`, `past_due`, `unpaid`, or `paused`, and removes the group's local billing
  history. Prefer suspending.

## Roll back billing

Turn off the `STRIPE_*` and `BILLING_*` flags; routes answer `401`, `503`, or `disabled` and
stored facts stay in place. With `BILLING_ENABLED` off every `plan` reads `none`. The
[runbook](../../RUNBOOKS/stripe-billing.md#non-destructive-rollback) has the full procedure.
