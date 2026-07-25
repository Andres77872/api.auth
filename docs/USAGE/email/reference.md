# Email Endpoint and Configuration Reference

Reference for the email subsystem API surface in `api.auth`: the ROOT-only admin template API, the inbound provider webhook, and the email configuration/env surface.

> **API Version**: 2.2.0 · Every request must send a `User-Agent` header (missing ⇒ `422`).

---

## `/admin/email-templates` Endpoints (ROOT only)

All endpoints require ROOT. Auth is `HTTPBearerOrCookie` (session bearer/cookie) + `is_root_user` (`_require_root`). A non-root caller receives `403 ACCESS_DENIED`. Bodies, where present, are **JSON** (Pydantic models), not form data.

| Endpoint | Method | Auth | Body | Purpose |
|----------|--------|------|------|---------|
| `/admin/email-templates` | GET | ROOT | – | List every cataloged template code with active `source`/`version`, `purpose`, enabled/dynamic state, `revision`, variables |
| `/admin/email-templates` | POST | ROOT | JSON `TemplateCreateRequest` | Create a dynamic internal template code and activate version 1 |
| `/admin/email-templates/{template_code}` | GET | ROOT | – | Active subject/html/text body + catalog metadata + built-in `default` body when applicable + full `versions[]` history |
| `/admin/email-templates/{template_code}` | PUT | ROOT | JSON `TemplateDraft` | Validate the draft, then save and activate it as a new version; disabled templates are re-enabled on success |
| `/admin/email-templates/{template_code}` | DELETE | ROOT | – | Disable the template without deleting catalog or version history |
| `/admin/email-templates/{template_code}/preview` | POST | ROOT | JSON `TemplatePreviewRequest` (optional) | Render a draft (or the active version) with server-side sample data |
| `/admin/email-templates/{template_code}/send-test` | POST | ROOT | JSON `TemplatePreviewRequest` (optional) | Send a rendered `[TEST]` email to the **caller's own** verified address |
| `/admin/email-templates/{template_code}/rollback` | POST | ROOT | JSON `TemplateRollbackRequest` | Validate and re-activate a prior version; disabled templates are re-enabled on success |

Built-in `{template_code}` values include `email_activation`, `password_reset`, `admin_password_reset`, `security_notification`, `delivery_operation`, `patreon_link_proof`, and `email_credit_grant_notification`. Dynamic codes must be created first with `POST /admin/email-templates`.

## `/internal/email` Endpoints (ROOT session required)

These JSON routes are companion-service primitives, but their current authority
is a normal ROOT access session via `require_root_user`. They do not accept the
billing or Patreon S2S bearer tokens. Never forward the root credential to a
browser.

| Endpoint | Method | Body | Success | Purpose |
| --- | --- | --- | --- | --- |
| `/internal/email/resolve-identity` | POST | `{ "email": "..." }` | `200` | Resolve an activated linked email to a safe local identity projection; unmatched email returns `matched=false` |
| `/internal/email/send-template` | POST | `recipient_email`, `template_code`, `variables`, optional provider idempotency key/priority | `202` | Enqueue an enabled `delivery_operation` or `security_notification` template |
| `/internal/email/message-status` | POST | `{ "email_message_id": "..." }` | `200` | Return redacted delivery state; unknown IDs return `404` |

`send-template` filters variables through the selected template's allow-list,
adds server-owned `app_name`/masked-recipient values, validates any
`action_url`, encrypts the transient render payload, and returns only the local
message id/lifecycle status/template code. It rejects auth/reset/Patreon
purposes on this generic internal route.

### Request bodies

```jsonc
// TemplateDraft  (PUT /{template_code})  — all three required
{
  "subject_template": "Activate your $app_name email",
  "html_template": "<!DOCTYPE html>...$activation_link...",
  "text_template": "Activate ...\n$activation_link\n..."
}

// TemplateCreateRequest  (POST /admin/email-templates)
{
  "template_code": "ops_incident_notice",
  "purpose": "delivery_operation",
  "allowed_variables": ["notice", "ticket_id"],
  "required_variables": ["notice"],
  "subject_template": "Notice $ticket_id",
  "html_template": "<p>$notice</p>",
  "text_template": "$notice"
}

// TemplatePreviewRequest  (preview, send-test) — all optional; omit body to use the active version
{
  "subject_template": "...",   // optional
  "html_template": "...",      // optional
  "text_template": "..."       // optional
}

// TemplateRollbackRequest  (rollback)
{ "version": 3 }
```

For `preview`/`send-test`: if **any** of the three fields is present, that draft is validated and rendered; if the body is omitted/empty, the **active** version is rendered. Variable *values* are always the server-side `sample_variables(code)` — an admin cannot inject variable values.

Dynamic template creation is limited to internal purposes: `delivery_operation` and `security_notification`. `template_code` must be lowercase snake_case and cannot collide with a built-in code. `required_variables` must be a subset of `allowed_variables`, and every required variable must appear in the template body.

### Success responses

**`GET /admin/email-templates`**

```json
{
  "templates": [
    {
      "template_code": "email_activation",
      "purpose": "email_activation",
      "subject_template": "Activate your $app_name email",
      "source": "code",
      "version": null,
      "is_customized": false,
      "is_enabled": true,
      "is_dynamic": false,
      "revision": 1,
      "disabled_at": null,
      "disabled_by": null,
      "required_variables": ["activation_link"],
      "allowed_variables": ["activation_link", "app_name", "expires_in", "recipient_masked", "support_email"]
    }
  ],
  "generated_at": "2026-06-14T12:00:00Z"
}
```

**`GET /admin/email-templates/{template_code}`** adds `html_template`, `text_template`, a `default` object (built-in subject/html/text), and `versions[]`:

```json
{
  "template_code": "email_activation",
  "purpose": "email_activation",
  "source": "db",
  "version": 4,
  "is_customized": true,
  "is_enabled": true,
  "is_dynamic": false,
  "revision": 7,
  "disabled_at": null,
  "disabled_by": null,
  "subject_template": "...",
  "html_template": "...",
  "text_template": "...",
  "required_variables": ["activation_link"],
  "allowed_variables": ["activation_link", "app_name", "expires_in", "recipient_masked", "support_email"],
  "default": { "subject_template": "...", "html_template": "...", "text_template": "..." },
  "versions": [
    { "version": 4, "subject_template": "...", "is_active": true,  "created_at": "2026-06-13T09:00:00Z" },
    { "version": 3, "subject_template": "...", "is_active": false, "created_at": "2026-06-01T09:00:00Z" }
  ],
  "generated_at": "2026-06-14T12:00:00Z"
}
```

**`PUT /admin/email-templates/{template_code}`**

```json
{ "success": true, "template_code": "email_activation", "version": 5, "revision": 8, "is_enabled": true, "used_variables": ["app_name", "recipient_masked", "activation_link", "expires_in"], "updated_at": "2026-06-14T12:00:00Z" }
```

**`POST /admin/email-templates`**

```json
{ "success": true, "template_code": "ops_incident_notice", "purpose": "delivery_operation", "version": 1, "revision": 1, "is_dynamic": true, "is_enabled": true, "used_variables": ["notice", "ticket_id"], "created_at": "2026-06-14T12:00:00Z" }
```

**`DELETE /admin/email-templates/{template_code}`**

```json
{ "success": true, "template_code": "ops_incident_notice", "is_enabled": false, "revision": 2, "disabled_at": "2026-06-14T12:00:00Z" }
```

Delete means disable. The catalog row and all `email_templates` versions remain for audit/rollback. Pending or retrying worker messages for that code are finalized `cancelled` with `EMAIL_TEMPLATE_DISABLED` when claimed.

**`POST /admin/email-templates/{template_code}/preview`**

```json
{ "template_code": "email_activation", "subject": "Activate your Magic Auth email", "html": "<!DOCTYPE html>...", "text": "Activate ...", "sample_variables": { "app_name": "Magic Auth", "recipient_masked": "j***@example.com", "expires_in": "24 hours", "support_email": "support@example.com", "activation_link": "https://example.com/auth/email/verify?token=sample..." }, "generated_at": "2026-06-14T12:00:00Z" }
```

The returned `html` is byte-identical to what the worker would send; the dashboard renders it inside a **script-less sandboxed iframe**.

**`POST /admin/email-templates/{template_code}/send-test`**

```json
{ "success": true, "template_code": "email_activation", "recipient_masked": "j***@example.com", "provider": "resend", "sent_at": "2026-06-14T12:00:00Z" }
```

The recipient is **never** in the body and never returned in clear — it is locked to the caller's own activated address; the audit entry redacts it.

**`POST /admin/email-templates/{template_code}/rollback`**

```json
{ "success": true, "template_code": "email_activation", "version": 3, "revision": 9, "is_enabled": true, "rolled_back_at": "2026-06-14T12:00:00Z" }
```

### Error codes

| Code | HTTP | When |
|------|------|------|
| `ACCESS_DENIED` | 403 | Caller is not ROOT |
| `RESOURCE_NOT_FOUND` | 404 | Unknown `template_code`; or rollback to a `version` that does not exist for the code |
| `INVALID_INPUT` | 400 | Dynamic create uses a forbidden purpose/colliding code; PUT/preview/send-test/rollback draft fails `validate_template_draft` (disallowed placeholder, missing required var, unsafe HTML, render failure); template is disabled for send-test; caller has no activated email; delivery not ready; provider send failed |
| `RATE_LIMIT_EXCEEDED` | 400/429 | send-test exceeds the `email_template_test` rate-limit buckets |

> See [errors.md](../errors.md) for the full error envelope. Validation failures surface the underlying `TemplateValidationError` message.

---

## `POST /webhooks/email/resend` (Resend / Svix inbound webhook)

| Property | Value |
|----------|-------|
| Method / Path | `POST /webhooks/email/resend` |
| App auth | **None** — authenticated by Svix signature over the **raw** request body (`verify_resend_webhook`) |
| Required headers | `svix-id`, `svix-timestamp`, `svix-signature` (all three; missing ⇒ `400 "Invalid webhook signature"`) |
| Success status | **`204 No Content`** — always, including ignored/unsupported events |
| Failure status | `400 "Invalid webhook signature"` (missing headers or signature verification failure) |

There is **no 2xx-with-body** path: successful processing, dedupe hits, and unsupported event types all return `204`. Only signature/header failures return `400`.

### Supported event types

| Effect | Recognized `type` values |
|--------|--------------------------|
| Delivered | `delivered`, `email.delivered`, `delivery.delivered` |
| Sent | `sent`, `email.sent` |
| Bounced (updates suppression) | `bounced`, `bounce`, `hard_bounce`, `email.bounced` |
| Complained (updates suppression) | `complained`, `complaint`, `email.complained` |

Processing per event: verify signature → skip if `type` unsupported → dedupe by provider event ID (Redis 24h TTL fast-path + DB stored-proc authority) → `apply_email_provider_event` (records a delivery attempt; bounce/complaint flips suppression) → sanitized activity log. Recipients are hashed (never logged in clear); raw payloads/links are never logged.

---

## Email Configuration / Environment Reference

Parsed by `load_email_config` (`src/Util/email/config.py`); defaults from `auth_constants.py`. The four peppers/keys (`EMAIL_TOKEN_PEPPER`, `EMAIL_HASH_PEPPER`, `EMAIL_IDEMPOTENCY_PEPPER`, `EMAIL_PAYLOAD_KEY`) are **always required** — `load_email_config` raises if any is missing, and `EMAIL_PAYLOAD_KEY` must be a Fernet URL-safe base64 32-byte key.

### Delivery & provider

| Env var | Default | Meaning |
|---------|---------|---------|
| `EMAIL_DELIVERY_ENABLED` | `false` | Master switch; when false the worker leaves rows durable but unsent |
| `EMAIL_PROVIDER` | `fake` | `resend` (real send), `mailpit` (dev SMTP), or `fake` (tests/default) |
| `EMAIL_ALLOW_REAL_SEND_IN_TESTS` | `false` | Opt-in to allow a real `resend` send under a test runtime (smoke tests only) |
| `EMAIL_FROM_ADDRESS` | – | Sender address; required for readiness |
| `EMAIL_REPLY_TO_ADDRESS` | – | Optional reply-to |
| `EMAIL_SENDER_DOMAIN_VERIFIED` | `false` | Must be `true` in prod with `resend` for readiness |
| `APP_ENV` | – | Runtime name; `test`/`testing`/`pytest` ⇒ test runtime (no-real-send guard active) |

### Resend / Mailpit

| Env var | Default | Meaning |
|---------|---------|---------|
| `RESEND_API_KEY` | – | Resend send key; required for `resend` readiness |
| `RESEND_WEBHOOK_SECRET` | – | Svix signing secret; required for `resend` readiness and webhook verification |
| `RESEND_WEBHOOK_TOLERANCE_SECONDS` | `300` | Allowed Svix timestamp skew |
| `MAILPIT_SMTP_HOST` | – | Required for `mailpit` readiness |
| `MAILPIT_SMTP_PORT` | – | Required for `mailpit` readiness |
| `MAILPIT_API_BASE_URL` | – | Optional Mailpit API base |

### Secrets / crypto (required)

| Env var | Meaning |
|---------|---------|
| `EMAIL_TOKEN_PEPPER` | Link-token hashing pepper |
| `EMAIL_HASH_PEPPER` | Recipient-hashing pepper (used for suppression/rate keys) |
| `EMAIL_IDEMPOTENCY_PEPPER` | Idempotency-key pepper |
| `EMAIL_PAYLOAD_KEY` | Fernet key encrypting the transient render payload at rest |

### TTLs & retention

| Env var | Default | Meaning |
|---------|---------|---------|
| `EMAIL_ACTIVATION_TOKEN_TTL_SECONDS` | `86400` | Activation link lifetime |
| `EMAIL_PASSWORD_RESET_TOKEN_TTL_SECONDS` | `3600` | Reset link lifetime; not a token value |
| `EMAIL_IDEMPOTENCY_TTL_SECONDS` | `86400` | Idempotency cache TTL |
| `EMAIL_TERMINAL_RETENTION_DAYS` | `30` | Terminal message retention |
| `EMAIL_DELIVERY_ATTEMPT_RETENTION_DAYS` | `365` | Delivery-attempt metadata retention |
| `EMAIL_RETENTION_PURGE_INTERVAL_SECONDS` | `3600` | In-worker `sp_email_retention_purge` cadence (`0` disables) |

### Worker tuning

| Env var | Default | Meaning |
|---------|---------|---------|
| `EMAIL_WORKER_POLL_SECONDS` | `5` | Idle poll interval in `run_forever` |
| `EMAIL_WORKER_BATCH_SIZE` | `25` | Rows claimed per drain |
| `EMAIL_WORKER_LEASE_SECONDS` | `300` | Claim lease duration |
| `EMAIL_WORKER_MAX_ATTEMPTS` | `8` | Attempts before dead-letter |
| `EMAIL_WORKER_BACKOFF_SECONDS` | `10,30,120,600,1800,3600,7200,14400` | Full-jitter retry cap schedule |

### Rate-limit defaults (send buckets, also reused by send-test)

| Env var | Default | Bucket |
|---------|---------|--------|
| `EMAIL_SEND_RECIPIENT_HOURLY_LIMIT` | `3` | recipient/hour |
| `EMAIL_SEND_RECIPIENT_DAILY_LIMIT` | `10` | recipient/day |
| `EMAIL_SEND_USER_HOURLY_LIMIT` | `5` | user/hour |
| `EMAIL_SEND_IP_HOURLY_LIMIT` | `20` | IP/hour |
| `EMAIL_RESEND_COOLDOWN_SECONDS` | `60` | resend cooldown |

`send-test` consumes the send buckets under `purpose="email_template_test"` with non-PII (hashed) key material; the limiter **fails closed** on a Redis error.

---

## Email Readiness States (`validate_email_readiness`)

| Status | `ready` | When |
|--------|---------|------|
| `disabled` | false | `EMAIL_DELIVERY_ENABLED=false` |
| `not_ready` | false | Missing required config (e.g. `EMAIL_FROM_ADDRESS`; for `resend`: `RESEND_API_KEY`/`RESEND_WEBHOOK_SECRET`, and `EMAIL_SENDER_DOMAIN_VERIFIED` in prod; for `mailpit`: host/port) — `missing[]` lists the keys |
| `ready` | true | All required config present |

`send-test` requires `ready=true`; otherwise it returns `400 INVALID_INPUT` with `Email delivery is not ready (status: ...)`.

---

**Document Version**: 1.0
