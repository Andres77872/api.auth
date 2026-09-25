# Email reference

The contract for the template admin API, the internal email routes, the provider webhook, and the
email configuration. Suite-wide rules are in [README.md](README.md#rules-and-caveats).

## Endpoints

### Template admin

Prefix `/admin/email-templates`. Access token (`Authorization: Bearer` or the `session_token`
cookie) of a root user. `{template_code}` is matched case-insensitively.

| Path | Method | Body | Purpose |
| --- | --- | --- | --- |
| `/admin/email-templates` | GET | — | List every code with its active version and state (no bodies) |
| `/admin/email-templates` | POST | [`TemplateCreateRequest`](#templatecreaterequest) | Create a dynamic code and activate version 1 |
| `/admin/email-templates/{template_code}` | GET | — | Active subject and bodies, variables, in-code default, version history |
| `/admin/email-templates/{template_code}` | PUT | [`TemplateDraft`](#templatedraft) | Validate and save a new active version; re-enables a disabled code |
| `/admin/email-templates/{template_code}` | DELETE | — | Disable the code; history is kept |
| `/admin/email-templates/{template_code}/preview` | POST | Optional [`TemplatePreviewRequest`](#templatepreviewrequest) | Render a draft or the active version with sample values |
| `/admin/email-templates/{template_code}/send-test` | POST | Optional [`TemplatePreviewRequest`](#templatepreviewrequest) | Send a rendered test to the caller's own activated address |
| `/admin/email-templates/{template_code}/rollback` | POST | [`TemplateRollbackRequest`](#templaterollbackrequest) | Re-activate a stored version; re-enables a disabled code |

### Internal email

Prefix `/internal/email`. Access token of a root user (`require_root_user`).

| Path | Method | Body | Success | Purpose |
| --- | --- | --- | --- | --- |
| `/internal/email/resolve-identity` | POST | `{"email": "..."}` | `200` | Find the active user who owns an activated address |
| `/internal/email/send-template` | POST | [Send-template body](#send-template-body) | `202` | Queue an email from a `delivery_operation` or `security_notification` template |
| `/internal/email/message-status` | POST | `{"email_message_id": "em-..."}` | `200` | Read one outbox message's redacted state |

### Provider webhook

| Path | Method | Auth | Success |
| --- | --- | --- | --- |
| `/webhooks/email/resend` | POST | `svix-id`, `svix-timestamp`, `svix-signature` headers, verified over the raw body with `RESEND_WEBHOOK_SECRET` | `204` with no body |

## Request bodies

### TemplateDraft

All three fields are required.

| Field | Rules |
| --- | --- |
| `subject_template` | One line, at most 255 characters |
| `html_template` | At most 65,535 bytes as UTF-8 (the `TEXT` column); see [draft validation](#draft-validation) |
| `text_template` | At most 40,000 characters and 65,535 bytes as UTF-8 |

> [!NOTE]
> Stored bodies are MySQL `TEXT` columns (65,535 bytes). A body that passes validation but is
> larger than that fails when it is saved.

### TemplateCreateRequest

`TemplateDraft` plus:

| Field | Required | Rules |
| --- | --- | --- |
| `template_code` | Yes | Lowercase snake_case, 1–100 characters, not a built-in code |
| `purpose` | Yes | `delivery_operation` or `security_notification` |
| `allowed_variables` | No | Identifier names; duplicates removed |
| `required_variables` | No | Must be a subset of `allowed_variables`; each must appear in the draft |

### TemplatePreviewRequest

Optional `subject_template`, `html_template`, `text_template`. With no body, or with all three
empty, the active version is used. If any field is set, the three are validated as a complete
draft. Variable values always come from the server's sample set; callers cannot supply them.

### TemplateRollbackRequest

| Field | Required | Rules |
| --- | --- | --- |
| `version` | Yes | An existing version number of this code |

### Send-template body

| Field | Required | Default | Rules |
| --- | --- | --- | --- |
| `recipient_email` | Yes | — | 3–320 characters; trimmed and lower-cased. Need not belong to a user. |
| `template_code` | Yes | — | Enabled code whose purpose is `delivery_operation` or `security_notification` |
| `variables` | No | `{}` | Keys outside the template's allowlist are dropped; values become strings. `app_name` (`Magic Worlds`) and `recipient_masked` are pre-filled and replaced only by an allowed key. `action_url`, when present, must be an absolute `http`/`https` URL with a usable host. |
| `provider_idempotency_key` | No | `template-email-{email_message_id}` | At most 128 characters; must be unique per provider |
| `priority` | No | `4` | 0–9; lower values are claimed first |

## Draft validation

`validate_template_draft` runs on create, update, preview and send-test drafts, and on the stored
version before a rollback. It stops at the first violation and returns it as `400` `VAL_3001`.

1. Subject, HTML and text are present and within the length limits; the subject is one line.
2. Every `$name` or `${name}` placeholder is in the code's allowed variables. A stray `$` is an
   error; write `$$` for a literal dollar sign.
3. Every required variable is referenced.
4. HTML safety:
   - allowed tags: `html`, `head`, `body`, `title`, `meta`, `style`, `table`, `thead`, `tbody`,
     `tfoot`, `tr`, `td`, `th`, `div`, `span`, `p`, `br`, `hr`, `a`, `img`, `h1`–`h6`, `strong`,
     `b`, `em`, `i`, `u`, `small`, `blockquote`, `ul`, `ol`, `li`, `center`, `font`;
   - no `on*` attributes, no `srcdoc`, no `<meta http-equiv="refresh">`;
   - URL attributes (`href`, `src`, `background`, `action`) use `http`, `https`, `mailto`, a
     relative path, or start with a `$` placeholder;
   - `style` values contain no `expression(`, `javascript:`, `vbscript:`, `@import`,
     `behavior:` or `-moz-binding`.
5. The draft renders with the code's sample values.

Common messages: `template uses variables outside the allowlist: ...`,
`template must reference the required variable(s): ...`,
`template contains an invalid $ placeholder`, `disallowed HTML tag <script>`,
`unrecognized HTML tag <...> is not permitted in email templates`.

## Template variables

Values are HTML-escaped in the HTML part. When a message does not supply them, `app_name`,
`recipient_masked`, `expires_in`, `support_email`, `event_title`, `message` and `status_summary`
fall back to built-in defaults. Any other placeholder used in the template must be supplied, even
if it is not required, or rendering fails. Required variables must have a non-empty value.

Activation and password-reset emails set `expires_in` from the configured link lifetime (see
[Configuration](#configuration)): whole days from two days up read "2 days", whole hours read
"1 hour" or "24 hours", and anything else reads in whole minutes, rounded down ("90 minutes").

| Code | Allowed variables |
| --- | --- |
| `email_activation` | `app_name`, `recipient_masked`, `expires_in`, `support_email`, `activation_link` |
| `password_reset`, `admin_password_reset` | `app_name`, `recipient_masked`, `expires_in`, `support_email`, `reset_link` |
| `security_notification` | `app_name`, `support_email`, `event_title`, `message` |
| `delivery_operation` | `app_name`, `support_email`, `status_summary` |
| `email_credit_grant_notification` | `app_name`, `recipient_masked`, `credits`, `action_url`, `expires_at`, `support_email`, `expires_in` |
| `patreon_link_proof` | `app_name`, `recipient_masked`, `expires_in`, `expires_at`, `support_email`, `patreon_link_proof_url`, `proof_token`, `lookup_id` |
| Dynamic codes | The `allowed_variables` given at creation |

Rendered messages carry the headers `X-Transactional-Scope: auth_transactional`,
`X-Template-Code`, `X-Template-Version` (stored versions), `X-Template-Revision` and
`X-Entity-Ref-ID` (the message ID). `List-Unsubscribe` is never added.

## Responses

### Template list and detail

`GET /admin/email-templates` returns `templates` (sorted by code) and `generated_at`:

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
  "generated_at": "2026-09-24T12:00:00Z"
}
```

`source` is `db` when a stored version is active and `code` when the in-code default is used;
`is_customized` is `source == "db"`. `GET /admin/email-templates/{template_code}` adds
`html_template`, `text_template`, `default` (the in-code subject and bodies for built-in codes,
`null` for dynamic ones) and `versions[]` (`version`, `subject_template`, `is_active`,
`created_at`).

### Write responses

| Route | Response fields |
| --- | --- |
| `POST /admin/email-templates` | `success`, `template_code`, `purpose`, `version` (`1`), `revision`, `is_dynamic`, `is_enabled`, `used_variables`, `created_at` |
| `PUT /admin/email-templates/{template_code}` | `success`, `template_code`, `version`, `revision`, `is_enabled` (`true`), `used_variables`, `updated_at` |
| `DELETE /admin/email-templates/{template_code}` | `success`, `template_code`, `is_enabled` (`false`), `revision`, `disabled_at` |
| `POST .../rollback` | `success`, `template_code`, `version`, `revision`, `is_enabled` (`true`), `rolled_back_at` |
| `POST .../preview` | `template_code`, `subject`, `html`, `text`, `sample_variables`, `generated_at` |
| `POST .../send-test` | `success`, `template_code`, `recipient_masked`, `provider`, `sent_at` |

`used_variables` is sorted. Update, disable and rollback increment the catalog `revision`; create
starts it at `1`.

```json
{
  "success": true,
  "template_code": "email_activation",
  "version": 5,
  "revision": 8,
  "is_enabled": true,
  "used_variables": ["activation_link", "app_name", "expires_in", "recipient_masked"],
  "updated_at": "2026-09-24T12:00:00Z"
}
```

Preview and send-test use the same render path as the worker, so the HTML matches a real send.
Send-test adds the subject prefix `[TEST] ` and the header `X-Email-Template-Test: true`.

### Internal responses

`POST /internal/email/resolve-identity`:

| Case | Fields |
| --- | --- |
| No active user has the address as an activated, non-removed email | `matched: false`, `email`, `email_masked` |
| Match | `matched: true`, `email`, `email_masked`, `user_hash`, `username`, `user_type`. With several matches, the primary email wins, then the earliest activation. |

`POST /internal/email/send-template` returns `202`:

```json
{
  "accepted": true,
  "email_message_id": "em-5b0c3f5e-1f0a-4c1e-9d0b-2a6f1d2e3c4b",
  "lifecycle_status": "template_email_enqueued",
  "template_code": "delivery_operation"
}
```

`POST /internal/email/message-status` returns `email_message_id`, `purpose`, `template_code`,
`recipient_masked`, `provider`, `provider_message_id`, `status`, `attempt_count`,
`max_attempts`, `sent_at`, `terminal_at`, `last_error_code`, `created_at` and `updated_at`. The
recipient address, body and variables are never returned.

## Error codes

### Template admin errors

| Status | Code | When |
| --- | --- | --- |
| `401` | `AUTH_1003` | Missing, invalid or expired access token |
| `403` | `AUTHZ_2001` | Caller is not a root user ("ROOT access required to manage email templates") |
| `404` | `NF_4004` | Unknown `template_code`, or rollback to a version that does not exist |
| `409` | `CONF_5004` | Create with a `template_code` that already exists |
| `400` | `VAL_3001` | Request body fails schema validation ("Request validation failed") |
| `400` | `VAL_3001` | Create: code not snake_case or collides with a built-in; purpose not allowed; invalid variable names; required not a subset of allowed |
| `400` | `VAL_3001` | Draft fails [validation](#draft-validation), or the stored version fails it on rollback |
| `400` | `VAL_3001` | "Email template state is unavailable" (catalog could not be read) |
| `400` | `VAL_3001` | Send-test: template disabled; no activated email ("You have no verified email address on file ..."); "Email delivery is not ready (status: ...)"; "Test email could not be sent by the provider" |
| `400` | `INT_7005` | Send-test: "Too many test emails; please wait before sending another" |

### Internal email errors

| Status | `error.message` | When |
| --- | --- | --- |
| `401` | — | Missing, invalid or expired access token |
| `403` | "Root user access required" (`AUTHZ_2002`) | Caller is not a root user |
| `400` | "Request validation failed" | Body fails schema validation (lengths, `priority` range) |
| `422` | `valid email is required` | Address has no `@`, contains spaces, or is too long |
| `422` | `template_code is invalid` / `template_code is disabled` | Unknown or disabled code |
| `422` | `template_code is not allowed for internal template delivery` | Purpose is not `delivery_operation` or `security_notification` |
| `422` | `valid action_url is required` / `template variables are invalid` | Bad `action_url`, or a required variable is missing or empty |
| `409` | Duplicate entry (`CONF_5004`) | `provider_idempotency_key` already used for this provider |
| `503` | `Transactional email template state is unavailable.` / `Transactional email is not configured.` | Catalog unreadable, or email config (peppers, payload key) invalid |
| `404` | `email_message_id not found` | Unknown message ID on `message-status` |

`422` responses carry `error.code` `VAL_3001`.

### Webhook errors

| Status | When |
| --- | --- |
| `400` | "Invalid webhook signature": a Svix header is missing, the signature or timestamp fails verification, or `RESEND_WEBHOOK_SECRET` is not set |
| `500` | Applying the event to the database failed |

## Webhook events

The event type is read from `type`, `event` or `event_type`; the event ID from `id`, `event_id`,
`provider_event_id` or the `svix-id` header; the provider message ID from `data.email_id`. The
local message is matched by `data.email_message_id` when present, otherwise by provider message
ID.

| Effect | Accepted `type` values | Message status | Activity written |
| --- | --- | --- | --- |
| Sent | `sent`, `email.sent` | Unchanged; attempt recorded | `email_message_sent` |
| Delivered | `delivered`, `email.delivered`, `delivery.delivered` | `delivered` | `email_message_delivered` |
| Bounced | `bounced`, `bounce`, `hard_bounce`, `email.bounced` | `bounced`; recipient suppressed (`hard_bounce`) | `email_message_bounced`, `email_suppression_updated` |
| Complained | `complained`, `complaint`, `email.complained` | `complained`; recipient suppressed (`complaint`) | `email_message_complained`, `email_suppression_updated` |

Other types are ignored and still answered with `204`. Duplicate event IDs are skipped: first by a
Redis marker kept for 24 hours, then by `sp_apply_email_provider_event`, which checks
`email_delivery_attempts`. The marker is removed again when the database update fails, so the
provider's retry of a `500` is applied. Events whose message cannot be found change nothing. Suppression also
sets a matching `activated` account email to `suppressed` and clears its primary flag.

## Outbox statuses and worker error codes

| Status | Meaning |
| --- | --- |
| `pending` | Queued, not yet claimed |
| `processing` | Claimed by a worker under a lease; reclaimed if the lease expires |
| `retry` | Failed; waiting for `next_attempt_at` |
| `sent` | Accepted by the provider |
| `delivered`, `bounced`, `complained` | Set by webhook events |
| `suppressed` | Not sent: recipient on the suppression list |
| `dead` | Retries exhausted or permanent failure |
| `cancelled` | Template disabled, or user data erased |

| `last_error_code` | Outcome |
| --- | --- |
| `EMAIL_SUPPRESSED` | `suppressed` |
| `EMAIL_TEMPLATE_DISABLED` | `cancelled` |
| `EMAIL_TEMPLATE_LOOKUP_FAILED` | `retry` (template catalog unreadable) |
| `EMAIL_RENDER_FAILED` | `dead` at once (render error or missing recipient) |
| `EMAIL_PROVIDER_FAILED` | `retry`, or `dead` when the provider marks the error non-retryable |
| `EMAIL_WORKER_FAILED` | `retry` (unexpected error) |

## Configuration

`load_email_config` in `src/Util/email/config.py` reads these variables. `.env.example` is the
maintained template.

### Delivery and provider

| Variable | Default | Meaning |
| --- | --- | --- |
| `EMAIL_DELIVERY_ENABLED` | `false` | Master switch. When false, rows stay queued and the worker sends nothing. |
| `EMAIL_PROVIDER` | `fake` | `resend`, `mailpit` or `fake`. `fake` is ready only in a test runtime. |
| `EMAIL_FROM_ADDRESS` | — | Sender; required for readiness |
| `EMAIL_REPLY_TO_ADDRESS` | — | Optional single mailbox, bare or `Name <addr>`. A malformed value makes readiness `not_ready`. |
| `EMAIL_SENDER_DOMAIN_VERIFIED` | `false` | Must be `true` for `resend` when `APP_ENV` is `prod` or `production` |
| `EMAIL_ALLOW_REAL_SEND_IN_TESTS` | `false` | Allows `resend` sends in a test runtime (provider smoke tests only) |
| `APP_ENV` | — | `test`, `testing` or `pytest` marks a test runtime; unset also counts as test under pytest |
| `AUTH_EMAIL_PUBLIC_BASE_URL` | — | Pins the origin of emailed links; see [README.md](README.md#rules-and-caveats) |

### Resend and Mailpit

| Variable | Default | Meaning |
| --- | --- | --- |
| `RESEND_API_KEY` | — | Required for `resend` readiness |
| `RESEND_WEBHOOK_SECRET` | — | Svix signing secret; required for `resend` readiness and for the webhook |
| `RESEND_WEBHOOK_TOLERANCE_SECONDS` | `300` | Parsed but not used; Svix applies its own fixed 5-minute tolerance |
| `MAILPIT_SMTP_HOST`, `MAILPIT_SMTP_PORT` | — | Required for `mailpit` readiness |
| `MAILPIT_API_BASE_URL` | — | Parsed; used only by e2e tests |

### Secrets

All four are required; `load_email_config` fails without them.

| Variable | Meaning |
| --- | --- |
| `EMAIL_TOKEN_PEPPER` | HMAC pepper for link tokens |
| `EMAIL_HASH_PEPPER` | HMAC pepper for recipient hashes (suppression, rate-limit keys, `recipient_hash`) |
| `EMAIL_IDEMPOTENCY_PEPPER` | Pepper for idempotency keys |
| `EMAIL_PAYLOAD_KEY` | Fernet key (URL-safe base64, 32 bytes) that encrypts render payloads |

### Lifetimes and retention

| Variable | Default | Meaning |
| --- | --- | --- |
| `EMAIL_ACTIVATION_TOKEN_TTL_SECONDS` | `86400` | Activation link lifetime; the email's `expires_in` text is derived from it (`86400` reads "24 hours") |
| `EMAIL_PASSWORD_RESET_TOKEN_TTL_SECONDS` | `3600` | Reset link lifetime; the email's `expires_in` text is derived from it, not fixed (`3600` reads "1 hour") |
| `EMAIL_IDEMPOTENCY_TTL_SECONDS` | `86400` | Lifetime of email-route idempotency records |
| `EMAIL_TERMINAL_RETENTION_DAYS` | `30` | Sets `payload_purge_at` for `send-template` messages only; the purge procedure also clears data after a fixed 30 days |
| `EMAIL_DELIVERY_ATTEMPT_RETENTION_DAYS` | `365` | Parsed but not used; the purge procedure uses a fixed 365 days |
| `EMAIL_RETENTION_PURGE_INTERVAL_SECONDS` | `3600` | How often the long-running worker calls `sp_email_retention_purge`; `0` disables |

### Worker

| Variable | Default | Meaning |
| --- | --- | --- |
| `EMAIL_WORKER_POLL_SECONDS` | `5` | Sleep between drains |
| `EMAIL_WORKER_BATCH_SIZE` | `25` | Rows claimed per drain |
| `EMAIL_WORKER_LEASE_SECONDS` | `300` | Claim lease |
| `EMAIL_WORKER_MAX_ATTEMPTS` | `8` | Fallback attempt budget; rows carry their own `max_attempts` (`8` when enqueued) |
| `EMAIL_WORKER_BACKOFF_SECONDS` | `10,30,120,600,1800,3600,7200,14400` | Retry caps; the delay is random between 0 and the cap |

### Rate limits

Read once at import; restart the API after changing them. Keys are hashed; Redis errors fail
closed.

| Variable | Default | Bucket |
| --- | --- | --- |
| `EMAIL_SEND_RECIPIENT_HOURLY_LIMIT` | `3` | Sends per recipient per hour, per purpose |
| `EMAIL_SEND_RECIPIENT_DAILY_LIMIT` | `10` | Sends per recipient per day, per purpose |
| `EMAIL_SEND_USER_HOURLY_LIMIT` | `5` | Sends per user per hour, per purpose |
| `EMAIL_SEND_IP_HOURLY_LIMIT` | `20` | Sends per IP per hour, per purpose |
| `EMAIL_CONSUME_LOOKUP_HOURLY_LIMIT` | `5` | Link consumes per lookup ID per hour |
| `EMAIL_CONSUME_IP_HOURLY_LIMIT` | `30` | Link consumes per IP per hour |
| `EMAIL_RESEND_COOLDOWN_SECONDS` | `60` | Cooldown between resends |
| `EMAIL_LOGIN_IDENTIFIER_FAILURE_LIMIT`, `EMAIL_LOGIN_IDENTIFIER_FAILURE_WINDOW_SECONDS` | `10`, `900` | Failed logins per identifier and IP |
| `EMAIL_LOGIN_ACCOUNT_FAILURE_LIMIT`, `EMAIL_LOGIN_ACCOUNT_FAILURE_WINDOW_SECONDS` | `30`, `900` | Failed logins per identifier across IPs |

Send-test uses the send buckets under the purpose `email_template_test`. The login buckets are
enforced by `POST /auth/login` and answer `429` with `Retry-After`.

### Readiness

`validate_email_readiness` checks configuration without calling the provider:

| Status | When |
| --- | --- |
| `disabled` | `EMAIL_DELIVERY_ENABLED` is false |
| `not_ready` | A key listed in `missing[]` is absent or invalid: `EMAIL_FROM_ADDRESS`, a malformed `EMAIL_REPLY_TO_ADDRESS`; for `resend`, `RESEND_API_KEY`, `RESEND_WEBHOOK_SECRET` and (production) `EMAIL_SENDER_DOMAIN_VERIFIED`; for `mailpit`, host and port; `EMAIL_PROVIDER` when it is unknown, or `fake` outside a test runtime |
| `ready` | Everything required is present |

Send-test and the worker require `ready`; with delivery enabled but not ready, the worker refuses
to start.

## Redis keys

| Key | TTL | Purpose |
| --- | --- | --- |
| `email_rate:{bucket}:{digest}` | Bucket window | Rate-limit counters |
| `email_cooldown:{purpose}:{digest}` | Cooldown | Resend cooldown |
| Webhook event marker (`CacheManager.email_webhook_event_key`) | 24 hours | First-seen check for provider event IDs |
| Worker heartbeat | 120 seconds | Written after each drain; read by `GET /system/health` |
