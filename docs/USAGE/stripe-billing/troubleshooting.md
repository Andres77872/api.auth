# Stripe Billing Troubleshooting

Troubleshooting for provider-agnostic billing S2S routes, Stripe Checkout/Portal, webhook ingestion, source-of-truth sync, retention, and pull-only consumer projection.

## Safety Rules

- Stripe is not a local login provider and does not issue local sessions. It
  must not change JWT, refresh-token, cookie, or API-key authority.
  Project-scoped identity responses intentionally carry only the neutral
  subscription `plan` projection.
- Billing is disabled by default. Check feature flags before treating a behavior as an outage.
- Never paste raw provider refs, Stripe signatures, webhook payloads, secret keys, webhook secrets, S2S bearer tokens, idempotency keys, HMAC digests, fingerprints, card/payment-method details, receipt links, audit rows, or real config values into tickets, docs, chat, screenshots, or logs.
- Use safe evidence only: correlation IDs, activity codes, aggregate counts, safe status values, non-secret health output, route names, response codes, and redacted operator notes.
- Retention windows are fixed by the SDD: webhook delivery ledger **90d**, encrypted raw quarantine **30d max**, normalized billing/purchase history **indefinite**.

## Fast Triage Table

| Symptom | Likely cause | Safe first action |
| --- | --- | --- |
| Billing S2S returns unauthorized | Missing/rotated dedicated bearer, feature disabled, browser/session credential used instead of S2S token | Confirm `BILLING_ENABLED`, `BILLING_S2S_ENABLED`, and bearer presence by key name only. |
| Checkout unavailable | Global/group capability disabled, group credentials inactive, SDK/API mismatch, catalog/return URL/DB/crypto not ready | Keep Checkout disabled; inspect the affected group's readiness and non-secret mismatch labels. |
| Portal unavailable | Global/group capability disabled, missing per-group Portal configuration, no group customer | Keep Portal disabled for the group until readiness is verified. |
| Webhook signature failures | Wrong per-group/global fallback secret, wrong endpoint, body changed before verification, timestamp/header failure | Reject before mutation; verify exact raw-body path and secret deployment by version label only. |
| SDK/API version mismatch | Runtime package or configured API version does not match supported pins | Treat Stripe as not-ready; deploy the supported package/config pin before enabling behavior. |
| Missing secrets/config | Secret manager key absent or app not reloaded | Keep flags disabled or not-ready; verify key presence by name only. |
| Decrypt failures | Missing old key, wrong key id, corrupted ciphertext, premature key removal | Disable affected provider operations; restore decrypt key map; preserve evidence; rotate only through runbook. |
| Idempotency conflict | Same idempotency key reused with different canonical request | Return neutral conflict; consumer must use a new idempotency key for a new intent. |
| Webhook lag | Ingress blocked, receiver not-ready, Stripe retry backlog, DB issue, worker backlog | Check health components and delivery counts; do not process raw payloads in tickets. |
| Stale snapshots | Worker down, provider outage, resync backlog, webhook partial/out-of-order evidence | Preserve stale status and run source-of-truth repair when ready. |
| Sync backlog | Worker stopped, DB unavailable, provider retries/backoff, decrypt failures | Inspect `billing_sync` health and worker heartbeat; restart only after readiness is safe. |
| Consumer projection wrong | Stale catalog/fact pull, opaque-feature interpretation bug, local ledger idempotency issue | Verify `api.auth` catalog/facts, then fix consumer-owned interpretation/projection. |

## Billing S2S Unauthorized

Expected behavior:

- Missing or invalid dedicated billing bearer returns a neutral unauthorized response.
- Browser cookies, local sessions, user access tokens, and regular API keys are rejected as billing authority.
- Unauthorized responses must not reveal whether a user, project, customer, subscription, or purchase exists.

Safe checks:

1. Confirm `BILLING_ENABLED` and `BILLING_S2S_ENABLED` are intended to be true in this environment.
2. Confirm the dedicated bearer exists in secret management by key/version label only.
3. Confirm the caller sends `Authorization: Bearer <billing-s2s-token>` server-to-server.
4. Confirm `User-Agent` is present.
5. Check `billing_s2s_read` activity counts only, not raw headers.

Do not solve this by allowing browser sessions or `/auth/validate` to carry
detailed provider or purchase facts. The existing `plan` projection is not S2S
authority.

## Checkout Unavailable

Common causes:

- `BILLING_CHECKOUT_ENABLED=false` or `STRIPE_CHECKOUT_ENABLED=false`.
- Missing/inactive credentials for the resolved billing group.
- SDK/API version mismatch.
- Missing provider-ref encryption key or key id.
- Missing or invalid return URL allow-list.
- DB schema/bootstrap not ready.
- Stripe provider degraded or local rate limit exceeded.

Safe checks:

1. With a valid access session, inspect `/system/health` billing components for non-secret `missing` and `critical_mismatches` key names.
2. Confirm `stripe==15.2.1` and `STRIPE_API_VERSION=2026-05-27.dahlia` are the supported pins.
3. Confirm the return URL origin, not the full secret-bearing request, is allow-listed.
4. Confirm the project resolves to the intended active billing group and its
   Checkout/provisioning capability and catalog item are ready.
5. Confirm no raw provider refs or price selector values are logged.
6. Check idempotency conflict counts and `Retry-After` posture.

Recovery:

- Keep Checkout disabled until all readiness checks pass.
- Fix config through secret management and redeploy/reload.
- Retry with the same idempotency key only for the same canonical request.
- Use a new idempotency key for a changed purchase/subscription intent.

## Portal Configuration Failure

Expected behavior:

- Portal fails closed when configuration cannot be verified as restricted.
- Portal plan changes, upgrades, downgrades, and subscription item changes remain disabled for MVP.

Safe checks:

1. Confirm `BILLING_PORTAL_ENABLED` and `STRIPE_PORTAL_ENABLED` are intentionally enabled.
2. Confirm the affected billing group has an encrypted Portal configuration id
   and active credentials. The global env id is not a runtime fallback.
3. Confirm group readiness reports Portal enabled and ready.
4. Confirm the route returns only hosted URL plus opaque `portal_ref` when successful.

Recovery:

- Disable Portal flags while correcting provider-side configuration.
- Re-run restricted Portal readiness validation.
- Use Checkout S2S intent for plan changes instead of Portal.

## Webhook Signature Failures

Stripe webhook verification requires exact raw request bytes. Any body mutation before verification invalidates trust.

Common causes:

- Wrong webhook secret deployed.
- Secret rotated in Stripe but not in `api.auth`, or vice versa.
- Proxy/middleware parsed and reserialized JSON before verification.
- Timestamp outside configured tolerance.
- Missing or malformed signature header.
- Non-Stripe request hitting the route.

Safe checks:

1. Confirm `/webhooks/stripe/{billing_group_hash}` (or the explicit global
   migration fallback) is excluded from unsafe raw-body audit capture.
2. Confirm the route reads the raw body before JSON parsing.
3. Check `stripe_webhook_rejected` / `act-cat-097` aggregate counts and signature-failure health.
4. Confirm Stripe targets the correct billing-group hash and compare that
   group's deployed secret version by label only. Never print the secret or
   signature.
5. Use sanitized fixtures for local verification; do not paste live webhook payloads.

Recovery:

- Keep invalid deliveries rejected before mutation.
- If failures spike, disable `STRIPE_WEBHOOKS_ENABLED`/the affected group's
  webhook capability or block `/webhooks/stripe` at ingress.
- Fix secret/raw-body path.
- Re-enable only after signed sanitized fixtures pass.
- Run source-of-truth resync for affected scopes if webhooks were missed.

## SDK/API Version Mismatch

Expected behavior:

- Stripe readiness becomes `not_ready`.
- Checkout, Portal, webhook mutation, and sync remain disabled or fail closed.
- Local auth/session health remains independent.

Safe checks:

1. Confirm the installed Stripe package reports the supported version.
2. Confirm the configured Stripe API version matches the supported value.
3. Inspect health `critical_mismatches` labels only.

Recovery:

- Deploy the supported dependency and configuration together.
- Do not override readiness to force provider mutation.
- Re-run targeted Stripe security/config readiness tests before enabling provider behavior.

## Missing Secrets or Config

Symptoms:

- Billing or Stripe health reports `not_ready`.
- Checkout/Portal/webhook/sync returns neutral unavailable/disabled posture for
  the affected group or global migration path.
- Missing key names appear in health, not values.

Recovery:

1. Keep feature flags disabled or not-ready.
2. Add missing global crypto/S2S keys in secret management or set/rotate the
   affected group's Stripe credentials through the ROOT-only admin route.
3. Reload app/workers.
4. Confirm health reports ready/degraded appropriately without printing values.
5. Enable one behavior at a time.

## Decrypt Failures

Common causes:

- Old decrypt key removed before all rows rotated.
- Wrong key id deployed.
- Ciphertext corrupted.
- Provider-ref key map malformed.

Expected behavior:

- Affected Checkout/Portal/sync operation fails closed.
- Sync records redacted failure evidence and increments decrypt-failure metrics.
- Raw provider refs are not logged.

Recovery:

1. Disable affected provider operations if failures are active.
2. Restore previous key id and decrypt key in `BILLING_PROVIDER_REF_DECRYPTION_KEYS_JSON` through secret management.
3. Verify reads can decrypt in a controlled maintenance path without printing decrypted values.
4. Rotate/re-encrypt through the key-rotation runbook.
5. Remove old key only after no rows reference it and rollback window expires.

## Idempotency Conflicts

Expected behavior:

- Same idempotency key + same canonical request replays safely.
- Same idempotency key + different canonical request returns neutral conflict.
- Provider API idempotency keys are derived from internal opaque refs, not raw consumer keys.

Safe checks:

1. Confirm the consumer did not reuse an idempotency key across different products, quantities, return URLs, or intent types.
2. Check conflict counters and generic error code only.
3. Do not log idempotency key values.

Recovery:

- Retry identical request with the same key if the prior response was lost.
- Use a new key for a changed intent.
- Fix consumer retry middleware if it mutates request bodies under the same key.

## Webhook Lag and Duplicate Deliveries

Symptoms:

- `billing_webhooks` reports high lag or duplicate counts.
- Stripe retries deliveries.
- Consumers see stale facts after Checkout or provider lifecycle changes.

Safe checks:

1. Inspect `billing_webhooks` health: signature failures, delivery lag, duplicate counts.
2. Confirm receiver ingress is open and not returning non-2xx for valid signed payloads.
3. Check DB delivery ledger readiness.
4. Check worker backlog if resync is required.

Recovery:

- Fix receiver health first.
- Keep duplicate deliveries idempotent; do not delete delivery rows to hide retries.
- Run source-of-truth resync after receiver health returns.

## Stale Snapshots and Sync Backlog

Common causes:

- `BILLING_SYNC_ENABLED=false` or `STRIPE_SYNC_ENABLED=false`.
- `src/workers/billing_sync_worker.py` is not running.
- Provider API outage or retry backoff.
- Decrypt failures.
- Partial/out-of-order webhook evidence enqueued resync.

Recovery:

1. Check `billing_sync` health and worker heartbeat.
2. Confirm queue counts: pending, running, retrying, failed, oldest pending age.
3. Restart or run the worker only after config is ready.
4. Respect retry `not_before` metadata.
5. Preserve stale/unknown facts until source-of-truth confirmation succeeds.

## Consumer Projection Failures

`api.auth` provides a centralized product-agnostic catalog, a neutral session
`plan`, and detailed safe provider facts. If product membership or credit UI is
wrong, verify both source data and the consuming project's interpretation.

Checklist:

- Does the consumer read the project catalog through S2S and use its lookup
  keys/opaque labels?
- Does every Checkout request use the same catalog row? The route currently
  trusts the S2S `price_ref`/labels and does not enforce that binding itself.
- Does it use `/auth/validate.plan` only for the narrow subscription summary
  and pull detailed billing/purchase facts through S2S?
- Does the consumer interpret `plan_code`, `tier_code`, `features`, and
  `credit_product_code` locally?
- Does the consumer own credit fulfillment/reversal idempotency?
- Does the consumer handle `stale` and `unknown` safely?
- Does the consumer keep raw provider evidence out of browser responses?

Catalog mappings already belong to `api.auth`; do not add interpreted benefits,
membership policy, credit balances, or ledgers as a shortcut.

## Evidence Checklist

Use this checklist for incidents:

- [ ] Feature flags / kill switches captured by key name only.
- [ ] `/system/health` billing components captured without secrets.
- [ ] Activity counts captured for `act-cat-091` through `act-cat-106` as counts/statuses only.
- [ ] Webhook signature evidence captured without signatures or payloads.
- [ ] S2S response reviewed for allow-listed fields only.
- [ ] Idempotency evidence captured without raw idempotency keys.
- [ ] No raw provider refs, payloads, signatures, secrets, HMACs, fingerprints, payment-method details, receipt links, or credit amounts pasted into the incident.
- [ ] Retention windows preserved.
- [ ] Rollback, if used, was non-destructive.

## Related Documentation

- [Overview](README.md)
- [Architecture](architecture.md)
- [Request Flow](request-flow.md)
- [Scenarios](scenarios.md)
- [Reference](reference.md)
- [Runbook](../../RUNBOOKS/stripe-billing.md)

---

**Document Version**: 1.0
