# Email Subsystem — Architecture

How transactional auth email actually ships in `api.auth`: the durable outbox-worker delivery pipeline, the provider abstraction, template versioning/rendering, idempotency, rate limiting, and the no-real-send safety guard. This describes internals; for endpoint shapes see [reference.md](reference.md), and for ops/deploy specifics see the [Email Activation Runbook](../../RUNBOOKS/email-activation.md).

---

## Delivery pipeline (outbox worker)

The API never sends mail inline. Request handlers enqueue a durable row in the MySQL **email outbox**; a separate worker process (`src/workers/email_worker.py`, run as `python -m src.workers.email_worker`) drains it.

```text
enqueue (MySQL outbox row, encrypted render payload)
        │
        ▼
EmailWorker.drain_once()
   ├─ claim_email_messages(worker_id, limit, lease_seconds)   # leased batch, FOR UPDATE SKIP LOCKED
   ├─ for each claimed message:  process_message()
   │     ├─ skip if delivery disabled            → status "disabled"
   │     ├─ suppression check (row flag or is_recipient_suppressed)
   │     │      → record sanitized attempt + finalize "suppressed"
   │     ├─ decrypt transient render payload IN MEMORY (EMAIL_PAYLOAD_KEY / Fernet)
   │     ├─ render_email_template(template_code, variables)   # active DB version → in-code fallback
   │     ├─ provider.send(EmailSendRequest)
   │     ├─ on success → record attempt "sent" + finalize "sent" (+ provider_message_id)
   │     ├─ on EmailTemplateError (render) → permanent failure → finalize "dead"
   │     └─ on EmailProviderError / other → retryable failure
   │            → compute_next_retry (full jitter) → finalize "retry"
   │            → or "dead" once attempts ≥ max_attempts (or non-retryable)
   └─ record worker heartbeat (SystemMetrics)
```

Key properties:

- **Durable first.** The outbox row is the canonical ledger; Redis is only support infrastructure (rate limits, dedupe, wake/heartbeat). A row stays durable even when delivery is disabled.
- **Leased claims.** `claim_email_messages` takes a worker lease (`EMAIL_WORKER_LEASE_SECONDS`, default 300s) using `FOR UPDATE SKIP LOCKED`, so multiple workers can run concurrently without double-sending.
- **Transient render payload.** Variable values (which may include links/PII) are stored encrypted (`render_payload_ciphertext`, Fernet via `EMAIL_PAYLOAD_KEY`) and decrypted only in worker memory at send time. They are never logged.
- **Suppression skip.** A suppressed recipient (row flag or hashed-ledger lookup) is finalized `suppressed` and never sent.
- **Sanitized attempts.** Every attempt is recorded via `record_email_delivery_attempt` with PII-stripped metadata only — hashed recipient, status, provider message id, sanitized error. Raw recipient/links/provider bodies never reach the attempt log.

### Retry and dead-letter

On a retryable failure the worker computes a **full-jitter** delay: it picks the cap from `EMAIL_WORKER_BACKOFF_SECONDS` (`10,30,120,600,1800,3600,7200,14400` by default) indexed by attempt count, then randomizes uniformly in `[0, cap]` to avoid retry stampedes. Once the attempt count reaches `EMAIL_WORKER_MAX_ATTEMPTS` (default 8) — or the failure is non-retryable, or rendering fails permanently — the message is dead-lettered (`finalize` status `dead`).

### Run modes and retention purge

- `run_forever()` (default) loops: drain → maybe-purge → sleep `EMAIL_WORKER_POLL_SECONDS`. It installs SIGTERM/SIGINT handlers for graceful stop.
- `--once` processes a single batch and exits (used in tests / one-shot redrive). In `--once` mode the retention purge does **not** run.
- In long-running mode the worker periodically calls `sp_email_retention_purge` on the `EMAIL_RETENTION_PURGE_INTERVAL_SECONDS` cadence (default hourly; `0` disables). The purge is idempotent and concurrency-safe; it redacts transient render payloads and plaintext recipients, deletes expired link tokens, strips old attempt metadata, and retires expired idempotency keys.

### Running in a container

The worker is a **separate process** from the API (`src/main.py` has no lifespan hook and the worker loop blocks). On the systemd host that is the `api-auth-email-worker` --user service via `scripts/run_email_worker.sh`. Under Docker the production image runs **both** processes in one container via `scripts/docker-entrypoint.sh` (the `Dockerfile` `CMD`): it launches `python -m src.workers.email_worker` and `uvicorn src.main:app` as siblings, forwards SIGTERM/SIGINT to both, and exits if either dies so the orchestrator restarts the container.

> `scripts/run_email_worker.sh` is **not** for containers — it sources a `.env` file (excluded by `.dockerignore`) and uses `.venv/bin/python`. The container entrypoint reads config from the process environment instead.

If the worker process is missing, `GET /system/health` reports `email_worker: unknown` (no Redis heartbeat) and, when delivery is enabled but provider config is absent, `email_provider: not_ready`. For both to go green the container must receive, via `--env-file`/compose `environment:` (never baked into the image): DB/Redis vars (`DB_HOST`, `DB_USER`, `DB_MYSQL_PASSWORD`, `DB_NAME`, `REDIS_HOST`, … — read at **import time**), `EMAIL_DELIVERY_ENABLED=true`, `EMAIL_PROVIDER=resend`, `EMAIL_FROM_ADDRESS`, `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, `EMAIL_SENDER_DOMAIN_VERIFIED=true` (prod), plus the operational peppers/keys (`EMAIL_TOKEN_PEPPER`, `EMAIL_HASH_PEPPER`, `EMAIL_IDEMPOTENCY_PEPPER`, `EMAIL_PAYLOAD_KEY`). Each container replica runs its own worker with a distinct `--worker-id` (derived from `HOSTNAME`); leased claims keep concurrent workers safe.

---

## Provider abstraction

`EmailProvider` is a `Protocol` (`src/Util/email/provider.py`) with three methods:

| Method | Purpose |
|--------|---------|
| `send(EmailSendRequest) -> EmailSendResult` | Deliver one rendered message |
| `verify_webhook(raw_body, headers) -> list[dict]` | Verify and parse a provider webhook |
| `health_check() -> dict` | Report provider readiness |

The concrete provider is selected by `EMAIL_PROVIDER`:

| Value | Class | Use |
|-------|-------|-----|
| `resend` | `ResendProvider` | Real send via Resend; webhook verified with Svix |
| `mailpit` | `MailpitProvider` | Local dev SMTP capture |
| `fake` (default) | `FakeEmailProvider` | Tests / no-op default |

Both the worker (`_provider_from_config`) and the admin `send-test` handler (`_provider_from_config`) resolve the provider the same way. `EmailProviderError` carries a `retryable` flag and sanitized metadata only.

---

## Template resolution, versioning, and rendering

Templates have two provenances:

- **`code`** — the in-code defaults in `src/Util/email/templates.py` (`TEMPLATES`), always available as a resilient fallback.
- **`db`** — a customized active version stored in the `email_templates` table via `db_email_templates`.

`resolve_template(code)` returns the active DB version when present and **falls back to the in-code default on an empty result OR any DB error**, so a missing/unavailable table never breaks delivery.

Admin edits go through `db_email_templates`:

- `save_and_activate_template(...)` writes a **new active version** (PUT). Each save bumps the version; prior versions remain.
- `list_template_versions(code)` / `get_template_version(code, version)` back the GET history and rollback lookup.
- `rollback_template(code, version)` re-activates a stored prior version.

`required_variables` are intrinsic to the workflow and are always taken from the in-code default, never from the editable DB row.

### The single render funnel

`render_template_parts` is the **one** place subject/html/text become a delivered message. The worker (`render_email_template` → `render_transactional_template`), admin **preview**, and admin **send-test** all funnel through it, so preview/test output is byte-identical to a real send. It:

1. validates every placeholder against the per-code allowlist (`validate_template_identifiers`);
2. fills base-variable defaults and enforces `required_variables`;
3. HTML-escapes values, then substitutes with `string.Template` (`$name`) — **not** `str.format`, eliminating attribute/expression injection on admin-editable text;
4. sets transactional headers (`X-Transactional-Scope`, `X-Template-Code`, optional `X-Template-Version`/`X-Entity-Ref-ID`) and **omits** `List-Unsubscribe*` (this is auth email, not marketing).

The admin save path additionally runs `validate_template_draft` (placeholder allowlist + required-var presence + HTML safety + render smoke test) before persisting.

---

## Idempotency

Two independent dedupe layers:

- **Outbound send.** Each `EmailSendRequest` carries an `idempotency_key` = the message's `provider_idempotency_key` (falling back to the message id), so a provider retry of the same message does not duplicate mail.
- **Inbound webhook events.** `_mark_event_seen` records each provider event id in Redis (`email_webhook_event_key`, 24h TTL, `SET NX`) as a fast route-level guard. The **DB stored procedure is the durable authority** and also dedupes by provider event id; the Redis layer is best-effort and falls through to DB dedupe on a Redis error. Peppers/TTLs are driven by `EMAIL_IDEMPOTENCY_PEPPER` / `EMAIL_IDEMPOTENCY_TTL_SECONDS`.

---

## Rate limiting

`EmailRateLimiter` (`src/Util/email/rate_limit.py`) uses fixed-window Redis buckets keyed by **non-PII hashed material only** (raw addresses, tokens, links never appear in keys). The admin `send-test` endpoint reuses the send buckets under `purpose="email_template_test"`:

| Bucket | Default |
|--------|---------|
| recipient / hour | 3 |
| recipient / day | 10 |
| user / hour | 5 |
| IP / hour | 20 |
| resend cooldown | 60s |

The limiter **fails closed** on a Redis error (`fail_closed_on_redis_error=True`) — when Redis is unavailable it raises `RateLimitExceeded` rather than allowing an unmetered send.

---

## Safety guards

### No-real-send guard

`load_email_config(validate_real_send_guard=True)` calls `_enforce_no_real_send_guard`: in an explicit **test runtime** (`APP_ENV` in `test`/`testing`/`pytest`, or under pytest) with `EMAIL_PROVIDER=resend` and real credentials present, a real send is **blocked** unless `EMAIL_ALLOW_REAL_SEND_IN_TESTS=true`. `SAFE_TEST_PROVIDERS = {fake, mailpit}` are always safe. This prevents accidental real mail during automated tests.

> A development box that *should* send real mail must run as `APP_ENV=development` (a non-test runtime) — see the runbook's "dev-box-that-sends" note.

### Readiness states

`validate_email_readiness(config)` returns one of `disabled` / `not_ready` / `ready` without contacting the provider:

- `disabled` — `EMAIL_DELIVERY_ENABLED=false`.
- `not_ready` — missing required config (the `missing[]` list names the keys): `EMAIL_FROM_ADDRESS`; for `resend` also `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET`, and `EMAIL_SENDER_DOMAIN_VERIFIED` in prod; for `mailpit` host/port.
- `ready` — everything required is present.

`send-test` refuses to send unless readiness is `ready`.

---

## Where things live

| Concern | Module |
|---------|--------|
| Admin template API | `src/routes/email_templates.py` |
| Inbound webhook | `src/routes/email_webhooks.py` |
| Worker | `src/workers/email_worker.py` |
| Provider protocol + DTOs | `src/Util/email/provider.py` |
| Config + guards + readiness | `src/Util/email/config.py` |
| Templates + render funnel | `src/Util/email/templates.py` |
| Draft validation | `src/Util/email/template_validation.py` |
| Rate limiter | `src/Util/email/rate_limit.py` |
| DB template versioning | `src/Util/db/db_email_templates.py` |
| Delivery/suppression DB | `src/Util/db/db_email.py` |

---

**Last Updated**: June 2026
**Document Version**: 1.0
