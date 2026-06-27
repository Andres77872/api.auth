# Email Activation & Transactional Auth Email Runbook

Operational runbook for optional activated emails, reset-link delivery, MySQL outbox worker, Resend/Svix webhooks, suppression handling, retention, and rollback.

## Scope

This subsystem is **transactional auth email only**: email activation links, self-service password reset links, admin-triggered reset links, delivery status, bounce, complaint, suppression, and audit events. It is not for marketing, newsletters, broadcast notifications, product updates, or preference-center email.

## Key Safety Rules

- Email is optional for registration, login, admin creation, root creation, and account use.
- Public verify/forgot/reset endpoints return generic `202 Accepted` for syntactically processable requests.
- `429 + Retry-After` is the only detailed public exception for rate limits.
- Activation/reset links never create sessions.
- `user_emails` is authoritative; `users.email` is only a compatibility shadow.
- Real provider sends must stay disabled in tests unless an explicit smoke-test opt-in is set.
- Webhooks must verify raw request bytes; do not parse and reserialize before Svix verification.
- A hard bounce or complaint flips the matching `user_emails` row to `status='suppressed'` (and clears `is_primary`), which removes that address from email login and password-reset resolution. Username login is unaffected. The `email_suppressions` hashed ledger blocks the worker from sending; the status flip is what excludes the address from the auth flows.
- Transactional templates are catalog-backed. `email_template_catalog` owns enabled/dynamic metadata and `email_templates` stores version history. Built-in templates may use in-code defaults only when enabled and no DB version exists.
- The worker resolves the latest enabled template immediately before rendering each claimed message. Any template change committed before render starts is honored; sends already rendering may finish with the version they resolved.
- Template DB lookup failures fail closed in the worker: the message retries with `EMAIL_TEMPLATE_LOOKUP_FAILED`, rather than falling back and possibly bypassing a disabled/dynamic template state.
- `DELETE /admin/email-templates/{template_code}` means disable, not hard-delete. Pending/retry messages for that code are finalized `cancelled` with `EMAIL_TEMPLATE_DISABLED` when claimed.
- Activation-resend cooldown (`EMAIL_RESEND_COOLDOWN_SECONDS`) is enforced both at the route via Redis and inside `sp_user_email_resend_and_enqueue` (returns lifecycle `cooldown` and enqueues nothing) so a resend cannot be replayed within the window even if the Redis check is bypassed.

## Required Configuration

Production enablement requires `EMAIL_DELIVERY_ENABLED=true`, `EMAIL_PROVIDER=resend`, `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, sender address/domain verification, token/hash/idempotency peppers, payload key, MySQL 8.0+, Redis, and SPF/DKIM/DMARC.

Local/test defaults should remain fake or Mailpit-safe: `EMAIL_DELIVERY_ENABLED=false`, `EMAIL_PROVIDER=fake`, and `EMAIL_ALLOW_REAL_SEND_IN_TESTS=false`.

**Dev-box-that-sends posture:** a development box may deliberately send real Resend mail for end-to-end testing. In that case set `APP_ENV=development` (not `production`) — `development` is a non-test runtime, so the no-real-send guard stays inactive and real sends still work, while keeping `DEBUG_MODE=true` coherent and avoiding the production debug-leak contradiction. Keep `EMAIL_DELIVERY_ENABLED=true`, `EMAIL_PROVIDER=resend`, and real credentials. The no-real-send guard only blocks real sends in explicit test runtimes (`APP_ENV` in `test`/`testing`/`pytest`, or under pytest).

`EMAIL_RETENTION_PURGE_INTERVAL_SECONDS` controls how often the long-running worker invokes `sp_email_retention_purge` (default `3600`; `0` disables in-worker purging). All other `EMAIL_*` tuning vars (TTLs, rate limits, worker backoff) default from `auth_constants.py`/`email/config.py` when unset; set them explicitly per deployment for auditability.

Before rollout, confirm:

- MySQL is 8.0+ so worker claims can use `FOR UPDATE SKIP LOCKED`.
- Redis is reachable for rate limits, idempotency cache, webhook event fast-dedupe, and worker wake/heartbeat keys.
- Sender domain SPF/DKIM/DMARC records are verified by the provider.
- The worker process is deployed independently from the API: `python -m src.workers.email_worker`.
- Operators can access `/system/health` and `/admin/email/logs` without exposing recipient PII.

## Health Checks

```bash
curl -X GET "${BASE_URL}/system/health" -H "User-Agent: ops/1.0"
```

Check `email_provider`, `email_outbox`, and `email_worker`. Disabled email delivery should not make unrelated auth health fail.

## Queue Growth / Worker Down

Symptoms: `email_outbox.queue_depth` grows, oldest pending age rises, or `email_worker.status` is `unknown` while delivery is enabled.

Actions:

1. Verify `python -m src.workers.email_worker` is running.
2. Verify Redis is reachable for wake/rate/idempotency support.
3. Verify MySQL 8 can execute `sp_claim_email_messages` with `FOR UPDATE SKIP LOCKED`.
4. Check `EMAIL_DELIVERY_ENABLED`; disabled delivery leaves rows durable but unsent.

## Provider Outage

Keep API routes up; public routes enqueue durable outbox rows and return generic posture. If the outage is prolonged, set `EMAIL_DELIVERY_ENABLED=false`, stop the worker, and leave outbox rows for inspection/redrive after recovery.

## DLQ / Dead Letters

If `email_outbox.dlq_depth > 0`, inspect sanitized attempts by message ID. Determine whether the cause is provider outage, template/render failure, bad recipient, suppression, or config. Redrive only after fixing the root cause.

Redrive guidance:

1. Do not edit recipient plaintext, body, token, link, or provider payload into logs.
2. If suppression caused the terminal state, do not redrive unless suppression was proven wrong and policy allows removal.
3. If provider outage/config caused the terminal state, fix provider readiness first, then requeue only the affected durable message IDs.
4. If render/template caused the failure, deploy the template fix first; otherwise the worker will dead-letter again.

## Template Catalog Operations

- Use `POST /admin/email-templates` only for internal dynamic templates (`delivery_operation` or `security_notification`). Auth/reset/Patreon purposes remain built-in.
- Use `PUT /admin/email-templates/{template_code}` to save a new active version. If the template was disabled, a successful PUT re-enables it.
- Use `DELETE /admin/email-templates/{template_code}` to disable. Do not delete rows manually; version history is audit evidence and rollback material.
- Use rollback only after the target version validates. Rollback re-enables the template and bumps catalog `revision`.
- Monitor worker attempts for `EMAIL_TEMPLATE_DISABLED`, `EMAIL_TEMPLATE_LOOKUP_FAILED`, and `EMAIL_RENDER_FAILED` to distinguish intentional disablement, transient catalog unavailability, and invalid active content.

## Password Recovery / Change Delta

Password recovery and authenticated password change are a delta on this runbook, not a separate provider/outbox system.

Operational facts:

- `POST /auth/password/forgot`, `POST /auth/password/reset`, and admin reset-link requests reuse `user_emails`, `user_email_link_tokens`, `email_outbox`, rate limits, idempotency, and provider delivery from this subsystem.
- Recovery is activated-email-only; pending, removed, suppressed, unknown, or legacy-only email identifiers keep generic public posture and do not enqueue recovery mail.
- `POST /auth/password/change` is authenticated, requires `current_password`, creates no replacement session, preserves the authorizing session, and revokes other sessions/families after success.
- Reset-link consumption creates no session and revokes existing sessions only after a successful password update.

Schema posture for password recovery (post-cleanup):

The canonical schema in `schemas/` is the single source of truth, applied with
`python scripts/recreate_database.py` (fresh/reset) or `scripts/create_database.py`. The one-off
`migrate_*` scripts have been retired.

1. The fresh schema uses only hash-backed `user_email_link_tokens` for password recovery.
   Retired plaintext recovery storage must not reappear in fresh bootstrap or docs.
2. Confirm the modern reset objects exist after setup: `user_email_link_tokens` plus the
   password reset enqueue and consume procedures.
3. If recovery must be paused, disable the public reset/change routes at ingress/router; the hash-only
   reset-link storage stays intact regardless.

Monitor after rollout:

- reset outbox queue depth and oldest pending age
- `password_changed` activity volume
- `INT_7005` rates for change-password and email-link flows
- session/family revocation metrics after successful password changes and resets

## Bounce / Complaint Spike

Confirm webhook signatures, sender DNS/authentication, and recipient source changes. Respect suppressions; do not manually bypass complaint or hard-bounce suppression. If the spike continues, disable delivery and investigate.

## Webhook Secret Rotation

1. Create/update the Resend webhook endpoint secret.
2. Deploy new `RESEND_WEBHOOK_SECRET`.
3. Verify valid Svix-signed `POST /webhooks/email/resend` events are accepted.
4. Verify invalid/missing signatures return `400` and do not mutate state.

## Resend API Key Rotation

Create a new least-privilege send key, deploy `RESEND_API_KEY`, restart workers, verify `/system/health`, prove a worker send, then revoke the old key.

## SPF / DKIM / DMARC

Configure the sender domain in Resend, add SPF/DKIM records exactly as provided, roll out DMARC conservatively, and set `EMAIL_SENDER_DOMAIN_VERIFIED=true` only after provider/domain checks pass.

### DKIM Selector Rotation

When rotating DKIM selectors, publish the new selector before removing the old one. Keep both selectors valid until provider verification and successful test delivery pass, then remove the retired selector after DNS TTL has elapsed. Do not enable production sends during an uncertain selector state.

## Retention / Anonymization

Use `sp_email_retention_purge` and `sp_anonymize_user_email_data`. Token rows and render payloads should be purged/anonymized after terminal/expiry windows; delivery attempts keep PII-stripped metadata; suppressions store hashed recipients only.

The long-running worker (`python -m src.workers.email_worker` via `run_forever`) now invokes `sp_email_retention_purge` automatically on the `EMAIL_RETENTION_PURGE_INTERVAL_SECONDS` cadence (default hourly), so transient render payloads and plaintext `recipient_email` are redacted, expired link tokens deleted, old delivery-attempt metadata stripped, and expired idempotency keys retired without an external cron. The purge is idempotent and safe under concurrent workers. If you run the worker only with `--once` (batch mode), it does **not** auto-purge — schedule `sp_email_retention_purge` separately (cron/systemd timer) in that deployment. `sp_anonymize_user_email_data(user_id)` remains the on-demand GDPR erasure path.

## Rollback

1. Set `EMAIL_DELIVERY_ENABLED=false`.
2. Stop `python -m src.workers.email_worker`.
3. Keep additive email tables for inspection.
4. Disable new email routes at ingress only if public API rollback is required.
5. Do not destructively drop email tables until retention/legal review is complete.
6. Do not restore plaintext reset tokens or temporary passwords as live recovery behavior during password-recovery rollback.
