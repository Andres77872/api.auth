# Email troubleshooting

Symptom, cause and fix. Error codes and messages are in [reference.md](reference.md#error-codes);
recovery procedures such as dead-letter redrive and secret rotation are in the
[email activation runbook](../../RUNBOOKS/email-activation.md).

## Template admin

| Symptom | Cause | Fix |
| --- | --- | --- |
| `403` "ROOT access required to manage email templates" | The caller is not a root user | Use a root account; admin users cannot edit templates |
| `404` on GET, PUT, DELETE, preview or send-test | The code is neither built-in nor an existing dynamic code | List codes with `GET /admin/email-templates`, or create the dynamic code first |
| `404` on rollback | The `version` does not exist for that code | Pick a `version` from `versions[]` in the GET response |
| `409` on create | The code already exists | Choose another code, or edit the existing one with PUT |
| `400` "template uses variables outside the allowlist: ..." | A placeholder is not in `allowed_variables` | Use only the listed variables |
| `400` "template must reference the required variable(s): ..." | A required placeholder such as `$activation_link` is missing | Put every required variable back |
| `400` "template contains an invalid $ placeholder" | A stray or malformed `$` | Use `$name` or `${name}`; write `$$` for a literal dollar sign |
| `400` "disallowed HTML tag ..." or "unrecognized HTML tag ..." | The HTML uses a tag outside the email allowlist | Stick to the tags listed in [draft validation](reference.md#draft-validation) |
| `400` "disallowed URL scheme ..." | A link uses something other than `http`, `https` or `mailto` | Fix the link, or use a placeholder |
| `400` "Email template state is unavailable" | The catalog could not be read | Restore database access; the API does not fall back to defaults |
| Save or validate answers `400` "... exceeds 65535 bytes (UTF-8)" | The HTML or plain-text body is larger than the 65,535-byte `TEXT` column; accented and non-Latin characters take 2 to 4 bytes each | Shrink the body below 64 KB |
| Preview shows values you did not send | Preview and send-test always use server sample values | Expected; only template text is editable |
| Activation or reset emails stopped for everyone | The built-in code was disabled | Roll back or save a version to re-enable it |

## Send-test

| Symptom | Cause | Fix |
| --- | --- | --- |
| `400` "You have no verified email address on file ..." | Your root account has no activated email | Add and activate an address on your account first |
| `400` "Email template is disabled" | Send-test refuses disabled codes | Re-enable with PUT or rollback, or use preview |
| `400` "Email delivery is not ready (status: disabled)" | `EMAIL_DELIVERY_ENABLED=false` | Enable delivery |
| `400` "Email delivery is not ready (status: not_ready)" | A required setting is missing or invalid | Fix the keys listed as `missing[]` in the `email_provider` health component |
| `400` `INT_7005` "Too many test emails ..." | The `email_template_test` buckets are full, or Redis is down (the limiter fails closed) | Wait for the window, or restore Redis |
| `400` "Test email could not be sent by the provider" | The provider rejected the send | Check provider credentials and connectivity in the application log |

## Internal send

| Symptom | Cause | Fix |
| --- | --- | --- |
| `403` "Root user access required" | The calling service's token is not a root user's | Use a root access token held server-side |
| `422` `template_code is not allowed for internal template delivery` | The template's purpose is activation, reset or Patreon | Use a `delivery_operation` or `security_notification` template |
| `422` `template variables are invalid` | A required variable is missing or empty, or a placeholder has no value | Send every variable the template uses; check `allowed_variables` |
| `422` `valid action_url is required` | `action_url` is not an absolute `http(s)` URL with a real host | Send a full URL |
| A variable you sent is ignored | Keys outside the template's allowlist are dropped | Add the variable to the template (dynamic codes) or use an allowed name |
| `409` | `provider_idempotency_key` was already used | Treat it as already queued, or send a new key |
| `503` `Transactional email is not configured.` | Email config failed to load (missing peppers or bad `EMAIL_PAYLOAD_KEY`) | Fix the secrets; see [configuration](reference.md#secrets) |
| `202` but the message stays `pending` | The worker is not running, or delivery is disabled | Start the worker and set `EMAIL_DELIVERY_ENABLED=true` |

## Webhook

| Symptom | Cause | Fix |
| --- | --- | --- |
| `400` "Invalid webhook signature" | A Svix header is missing, the secret is wrong or unset, the body was re-serialized, or the timestamp is more than 5 minutes off | Forward headers and raw body unchanged, set `RESEND_WEBHOOK_SECRET`, sync the server clock. `RESEND_WEBHOOK_TOLERANCE_SECONDS` has no effect. |
| `204` but nothing changed | Unsupported event type, a duplicate event ID, or no local message matched the event | Expected for the first two. For the third, the provider message ID must match a message this service sent. |
| A message never reaches `delivered` | Webhooks are not configured, or the provider does not send delivery events | Subscribe the endpoint to delivered, bounced and complained events |
| `500` to webhook deliveries | The delivery-state update failed (database trouble) | Fix the database; the dedupe marker is released on failure, so the provider's next retry is applied |
| A bounced address still receives mail | The bounce event did not match a message, so no suppression was written | Check that the event carries the provider message ID of a sent message |
| A user can no longer sign in with their email address | A bounce or complaint marked their account email `suppressed` | They can sign in with their username and add a working address |

## Worker

| Symptom | Cause | Fix |
| --- | --- | --- |
| Rows stay `pending`; log says "Email delivery disabled; worker drain skipped" | `EMAIL_DELIVERY_ENABLED=false` | Enable delivery |
| The worker exits at start with "Email delivery is not ready" | Delivery is enabled but readiness is `not_ready` | Fill the missing settings |
| The worker exits at start with "real email sends are blocked in test runtime" | Test runtime with `resend` and an API key | Use `fake` or `mailpit`, set `APP_ENV=development` on a machine that should send, or set `EMAIL_ALLOW_REAL_SEND_IN_TESTS=true` for a smoke test |
| `email_worker` health is `unknown` | No heartbeat in the last 120 seconds: the process is not running or is stuck | Start or restart the worker process |
| Claims fail | MySQL older than 8.0 (no `SKIP LOCKED`) or the database is unreachable | Use MySQL 8.0 or later; check connectivity |
| Messages end `dead` with `EMAIL_RENDER_FAILED` | The active template no longer renders with the stored variables | Fix or roll back the template, then redrive |
| Messages cycle through `retry` with `EMAIL_PROVIDER_FAILED` | Provider outage or bad credentials | Fix the provider; retries continue until `max_attempts` (8) |
| Messages end `cancelled` with `EMAIL_TEMPLATE_DISABLED` | The code was disabled | Re-enable the template, then redrive if the mail is still needed |
| Messages end `suppressed` | The recipient is on the suppression list after a bounce or complaint | Expected; the address must be fixed by the user |
| Render payloads and addresses are never purged | The worker runs only with `--once`, or `EMAIL_RETENTION_PURGE_INTERVAL_SECONDS=0` | Run the long-lived worker, or schedule `CALL sp_email_retention_purge()` |
| Changing `EMAIL_TERMINAL_RETENTION_DAYS` or `EMAIL_DELIVERY_ATTEMPT_RETENTION_DAYS` has no effect | The purge uses fixed 30- and 365-day windows | Expected; the first setting only affects `send-template` payloads |
