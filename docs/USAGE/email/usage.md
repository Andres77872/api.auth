# Email usage

One task per section. Bodies, limits and error codes are in [reference.md](reference.md). The
examples use a root user's access token in `$ROOT_TOKEN`; all bodies are JSON.

## Manage templates

### List templates

`GET /admin/email-templates`

```bash
curl "http://localhost:8000/admin/email-templates" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

Each entry shows `source` (`db` for a stored version, `code` for the built-in default),
`version`, `revision`, `is_enabled`, `is_dynamic` and the allowed and required variables.

### Inspect one template

`GET /admin/email-templates/{template_code}`

```bash
curl "http://localhost:8000/admin/email-templates/email_activation" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

Returns the active subject, HTML and text, the built-in `default` bodies and `versions[]`. Use a
`version` from that list for a rollback.

### Edit a template

`PUT /admin/email-templates/{template_code}` — all three parts are required. The draft is
validated before anything is saved; a failure returns `400` and saves nothing.

```bash
curl -X PUT "http://localhost:8000/admin/email-templates/email_activation" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "subject_template": "Activate your $app_name email",
    "html_template": "<!DOCTYPE html><html><body><p>Confirm $recipient_masked.</p><p><a href=\"$activation_link\">Activate</a></p><p>The link expires in $expires_in.</p></body></html>",
    "text_template": "Confirm $recipient_masked for $app_name:\n$activation_link\nThe link expires in $expires_in."
  }'
```

Returns the new `version`, `revision` and `used_variables`. The new version is active at once,
including for queued messages the worker has not rendered yet. Saving re-enables a disabled
template.

Use only the placeholders in `allowed_variables`, keep every required one (here
`$activation_link`), and write `$$` for a literal dollar sign.

### Preview a template

`POST /admin/email-templates/{template_code}/preview` — send a draft, or no body to render the
active version.

```bash
curl -X POST "http://localhost:8000/admin/email-templates/email_activation/preview" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

Returns `subject`, `html`, `text` and the `sample_variables` used. Values always come from the
server's sample set. Show the HTML in a sandboxed iframe without scripts. Disabled templates can
be previewed.

### Send a test email to yourself

`POST /admin/email-templates/{template_code}/send-test` — same optional draft body as preview.

```bash
curl -X POST "http://localhost:8000/admin/email-templates/email_activation/send-test" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

```json
{
  "success": true,
  "template_code": "email_activation",
  "recipient_masked": "a***e@example.com",
  "provider": "resend",
  "sent_at": "2026-09-24T12:00:00Z"
}
```

The message goes straight to the provider, not through the outbox, with the subject prefix
`[TEST] `. Requirements:

- your account has an activated email address (the first one is used; you cannot choose another);
- the template is enabled;
- email readiness is `ready`;
- the `email_template_test` rate limits are not exhausted (by default 3 per recipient per hour,
  10 per day, 5 per user per hour).

### Create a dynamic template

`POST /admin/email-templates` — for internal notices only (`delivery_operation` or
`security_notification`).

```bash
curl -X POST "http://localhost:8000/admin/email-templates" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "template_code": "ops_incident_notice",
    "purpose": "security_notification",
    "allowed_variables": ["app_name", "notice", "ticket_id"],
    "required_variables": ["notice"],
    "subject_template": "$app_name notice $ticket_id",
    "html_template": "<p>$notice</p>",
    "text_template": "$notice"
  }'
```

Returns `version: 1` and `is_dynamic: true`. An existing code returns `409`. The code can then be
sent with [`send-template`](#queue-an-internal-email).

### Disable a template

`DELETE /admin/email-templates/{template_code}`

```bash
curl -X DELETE "http://localhost:8000/admin/email-templates/ops_incident_notice" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

Returns `is_enabled: false`. Nothing is deleted. Queued messages for the code are cancelled with
`EMAIL_TEMPLATE_DISABLED` when claimed, and `send-template` and send-test reject it.

> [!CAUTION]
> Built-in codes can be disabled too. Disabling `email_activation` or `password_reset` stops those
> emails for every user until you save a version or roll back.

### Roll back to an earlier version

`POST /admin/email-templates/{template_code}/rollback`

```bash
curl -X POST "http://localhost:8000/admin/email-templates/email_activation/rollback" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"version": 3}'
```

The stored version is validated against the current rules, becomes the only active version, and
the template is re-enabled. An unknown version returns `404`.

## Send internal email

These routes serve trusted companion services. They need a root access token, so call them only
from a server.

### Queue an internal email

`POST /internal/email/send-template`

```bash
curl -X POST "http://localhost:8000/internal/email/send-template" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "recipient_email": "player@example.com",
    "template_code": "email_credit_grant_notification",
    "variables": {"credits": "25", "action_url": "https://app.example.com/credits", "expires_at": "No expiration"},
    "provider_idempotency_key": "credit-grant-8841"
  }'
```

Returns `202` with `email_message_id` (`em-...`) and `lifecycle_status: template_email_enqueued`.
Only templates with purpose `delivery_operation` or `security_notification` are accepted.
Variables outside the template's allowlist are dropped, and the message is test-rendered before it
is queued. Reusing a `provider_idempotency_key` returns `409`.

### Check a message's delivery state

`POST /internal/email/message-status`

```bash
curl -X POST "http://localhost:8000/internal/email/message-status" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email_message_id": "em-5b0c3f5e-1f0a-4c1e-9d0b-2a6f1d2e3c4b"}'
```

Returns `status` (`pending`, `processing`, `retry`, `sent`, `delivered`, `bounced`,
`complained`, `suppressed`, `dead` or `cancelled`), attempt counts, timestamps and
`last_error_code`. `delivered`, `bounced` and `complained` appear only when the provider webhook is
configured.

### Find the user behind an address

`POST /internal/email/resolve-identity`

```bash
curl -X POST "http://localhost:8000/internal/email/resolve-identity" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"email": "player@example.com"}'
```

Returns `matched: true` with `user_hash`, `username` and `user_type` when an active user has the
address as an activated email; otherwise `matched: false`.

## Connect the provider webhook

1. In Resend, add a webhook to `https://<your-host>/webhooks/email/resend` for the sent,
   delivered, bounced and complained events.
2. Put its signing secret in `RESEND_WEBHOOK_SECRET` and restart the API.
3. Make sure proxies forward the body unchanged; the signature covers the raw bytes.

A valid event returns `204`. A missing Svix header or a bad signature returns
`400 Invalid webhook signature` and changes nothing. Unsupported event types are acknowledged with
`204` and ignored.

## Run the worker

The API only queues messages. Start the worker as its own process:

```bash
python -m src.workers.email_worker                      # poll forever
python -m src.workers.email_worker --once               # one batch, then exit
python -m src.workers.email_worker --worker-id mail-1   # stable ID for heartbeats
```

`scripts/run_email_worker.sh` loads `.env` and runs it on a host. The container entrypoint
(`scripts/docker-entrypoint.sh`) starts it next to the API. With `EMAIL_DELIVERY_ENABLED=true` and
incomplete provider configuration the worker exits at start; check `GET /system/health`, whose
`email_worker` component reports `healthy`, `disabled`, `not_ready` or `unknown`.
