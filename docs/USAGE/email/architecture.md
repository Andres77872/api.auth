# Email architecture

How a transactional email moves from a request to the provider, and the design choices behind
each step. Endpoint contracts and configuration are in [reference.md](reference.md); rollout and
recovery procedures are in the [email activation runbook](../../RUNBOOKS/email-activation.md).

## Components

| Component | Location | Role |
| --- | --- | --- |
| Enqueue paths | Activation and reset stored procedures in `schemas/stored_procedures/14_email_activation.sql`; `src/routes/internal_email.py` | Insert an `email_messages` row with an encrypted render payload |
| Outbox tables | `schemas/tables/09_email_activation_tables.sql` | `email_messages`, `email_delivery_attempts`, `email_suppressions`, `email_idempotency_keys`, `email_template_catalog`, `email_templates` |
| Worker | `src/workers/email_worker.py` | Claims, renders, sends, retries, dead-letters, purges |
| Providers | `src/Util/email/resend_provider.py`, `src/Util/email/mailpit.py`, `src/Util/email/fake_provider.py` | Deliver one rendered message |
| Templates | `src/Util/email/templates.py`, `src/Util/email/template_validation.py`, `src/Util/db/db_email_templates.py` | Resolve, validate and render templates |
| Admin template API | `src/routes/email_templates.py` | Edit, preview, test, disable, roll back |
| Webhook | `src/routes/email_webhooks.py` | Apply provider delivery events and suppressions |
| Config and guards | `src/Util/email/config.py` | Parse settings, readiness, no-real-send guard |
| Rate limiter | `src/Util/email/rate_limit.py` | Redis buckets for sends, consumes, resends and failed logins |
| Crypto helpers | `src/Util/email/security.py` | Recipient hashing, masking, link tokens, payload encryption |

## Delivery pipeline

```text
request handler / stored procedure
  INSERT email_messages (status pending, render_payload_ciphertext = Fernet(variables))
        |
        v
EmailWorker.drain_once()                      (skipped entirely while delivery is disabled)
  sp_claim_email_messages(worker_id, batch, lease)
     rows that are pending/retry and due, or processing with an expired lease,
     ordered by priority then age, locked FOR UPDATE SKIP LOCKED, set to processing
  for each message:
     suppressed (row flag or active email_suppressions entry)?
        -> attempt "suppressed", finalize suppressed (EMAIL_SUPPRESSED)
     decrypt payload in memory
     render_email_template(code, variables, fail_closed_on_db_error=True)
     provider.send(...)
        ok                          -> attempt "sent", finalize sent (+ provider_message_id)
        template disabled           -> finalize cancelled (EMAIL_TEMPLATE_DISABLED)
        catalog unreadable          -> retry (EMAIL_TEMPLATE_LOOKUP_FAILED)
        render error                -> finalize dead (EMAIL_RENDER_FAILED)
        provider error              -> retry, or dead if non-retryable (EMAIL_PROVIDER_FAILED)
        anything else               -> retry (EMAIL_WORKER_FAILED)
  write heartbeat to Redis (TTL 120 seconds)
        |
        v
provider webhook -> sp_apply_email_provider_event -> delivered / bounced / complained
```

- **The outbox is the ledger.** Redis only holds rate-limit counters, dedupe markers and
  heartbeats. A message survives restarts, disabled delivery and provider outages.
- **Leases make concurrent workers safe.** A claimed row is `processing` until
  `EMAIL_WORKER_LEASE_SECONDS` expire; a crashed worker's rows are then claimed again.
- **Payloads are transient.** Variables (links, masked addresses) are encrypted with
  `EMAIL_PAYLOAD_KEY`, decrypted only in worker memory, and cleared from the row when the message
  reaches `sent` or a terminal status.
- **Attempts are sanitized.** Each attempt row stores the recipient hash, status, provider
  message ID and a scrubbed error, never the address, links or provider bodies.
- **Suppression lookup fails open.** If the suppression query errors, the worker sends anyway.

### Retries and dead-lettering

A failed attempt increments `attempt_count`. When the new count reaches the row's
`max_attempts` (`8` for every enqueue path), or the error is permanent, the message becomes
`dead`. Otherwise it becomes `retry` with `next_attempt_at` set to a random delay between 0 and
the cap `EMAIL_WORKER_BACKOFF_SECONDS[attempt_count]` (the last cap repeats). Resend send errors
are always treated as retryable.

### Run modes and retention

- `python -m src.workers.email_worker` loops: drain, maybe purge, sleep
  `EMAIL_WORKER_POLL_SECONDS`. SIGTERM and SIGINT stop it after the current batch.
- `--once` drains one batch and exits without purging.
- Every `EMAIL_RETENTION_PURGE_INTERVAL_SECONDS` (default `3600`; `0` disables) the loop calls
  `sp_email_retention_purge`, even while delivery is disabled. It clears render payloads past
  `payload_purge_at` or 30 days old, clears `recipient_email` and `last_error_message` after 30
  days, deletes `user_email_link_tokens` rows (hashed link tokens, never the secrets) 30 days
  after they were consumed, revoked or expired, strips attempt metadata after 365 days, and
  expires old idempotency records. The 30- and 365-day windows are fixed in SQL.

### Deployment

The worker is a separate process; `src/main.py` does not start it.

- **Host**: `scripts/run_email_worker.sh` sources `.env` and runs the worker from `.venv` (used by
  a systemd user service).
- **Container**: `scripts/docker-entrypoint.sh`, the image's `CMD`, starts the email worker, the
  Patreon and billing workers and the API in one container, forwards SIGTERM/SIGINT, and exits
  when any of them exits. The worker ID is `EMAIL_WORKER_ID` or `container-$HOSTNAME`.

Configuration comes from the process environment and is read at import time, so the worker needs
the same database, Redis and email variables as the API. With delivery enabled but readiness
`not_ready`, the worker raises at start.

`GET /system/health` (valid access session) reports `email_provider` readiness and an
`email_worker` status: `disabled`, `not_ready`, `healthy` (a heartbeat exists) or `unknown` (no
heartbeat).

## Providers

`EmailProvider` (`src/Util/email/provider.py`) has `send`, `verify_webhook` and `health_check`.

| `EMAIL_PROVIDER` | Class | Notes |
| --- | --- | --- |
| `resend` | `ResendProvider` | Resend SDK; passes the message's idempotency key; webhooks verified with Svix |
| `mailpit` | `MailpitProvider` | Plain SMTP to `MAILPIT_SMTP_HOST:MAILPIT_SMTP_PORT` for local capture |
| `fake` | `FakeEmailProvider` | Records sends in memory; accepted only in a test runtime |

With delivery disabled the worker holds a `DisabledEmailProvider` and does not claim rows. The
webhook route always verifies with `RESEND_WEBHOOK_SECRET`, whatever `EMAIL_PROVIDER` is.

## Templates

### Storage and resolution

- `email_template_catalog` has one row per code: purpose, allowed and required variables,
  built-in or dynamic, enabled flag, `revision`, and who disabled it.
- `email_templates` keeps every version; one is active per code.
- Built-in codes also have in-code bodies in `src/Util/email/templates.py`.

`resolve_template` reads the catalog and the active version. A built-in code with no stored
version uses its in-code body (`source: code`); a dynamic code must have a stored version. The
worker, the admin API and `send-template` resolve with `fail_closed_on_db_error=True`, so a
catalog read error never falls back to a default that might bypass a disabled flag. Because the
worker resolves right before rendering, any edit, disable or rollback committed before that point
applies to queued messages.

The version-1 rows seeded by `schemas/tables/09_email_activation_tables.sql` are insert-only:
`scripts/schema_sync.py` can re-run the file without overwriting operator versions. A new
built-in body ships as a new version through the template API.

### Rendering

`render_template_parts` is the only render path; the worker, preview and send-test all use it, so
previews match real mail. It:

1. rejects placeholders outside the allowlist;
2. fills the base defaults and checks required variables;
3. HTML-escapes values for the HTML part and substitutes with `string.Template` (no attribute or
   expression access, unlike `str.format`);
4. adds the `X-Transactional-Scope`, `X-Template-*` and `X-Entity-Ref-ID` headers and never a
   `List-Unsubscribe` header.

Saves additionally run `validate_template_draft` (length limits, HTML tag and URL allowlist,
render test). The validator rejects rather than strips, so the stored document is exactly what
the author wrote.

## Idempotency

- **Outbound**: each send passes `provider_idempotency_key` (or the message ID) to the provider,
  so a retried send of the same message is not delivered twice by Resend. The key is unique per
  provider in `email_messages`.
- **Webhook events**: a Redis `SET NX` marker (24 hours) drops repeats quickly; the stored
  procedure also skips an event ID already present in `email_delivery_attempts`. A Redis error
  falls through to the database check. If the database update fails, the marker is deleted
  before the `500`, so the provider's retry is applied rather than dropped as a duplicate.
- **Public email routes** (activation resend, forgot password) store `Idempotency-Key` replays in
  `email_idempotency_keys`, hashed with `EMAIL_IDEMPOTENCY_PEPPER` and kept for
  `EMAIL_IDEMPOTENCY_TTL_SECONDS`.

## Rate limiting

`EmailRateLimiter` uses fixed-window Redis counters whose keys contain only hashes. Send buckets
are per purpose: recipient per hour and per day, user per hour, IP per hour. Consume, resend
cooldown and failed-login buckets protect the public flows. The limiter fails closed: if Redis is
unavailable, the request is refused. Limits are read at import time.

## Safety guards

- **No real sends in tests.** When the runtime is a test runtime (`APP_ENV` in `test`, `testing`,
  `pytest`, or running under pytest), delivery is enabled, the provider is `resend` and
  `RESEND_API_KEY` is set, `load_email_config` raises unless
  `EMAIL_ALLOW_REAL_SEND_IN_TESTS=true`. A development machine that should send real mail sets
  `APP_ENV=development`.
- **Readiness.** `validate_email_readiness` returns `disabled`, `not_ready` (with `missing[]`) or
  `ready` from configuration alone. Send-test and the worker require `ready`.
- **Recipient privacy.** Addresses are hashed with `EMAIL_HASH_PEPPER` (HMAC-SHA-256) for lookups
  and shown masked; the plaintext `recipient_email` is kept only until the retention purge.
