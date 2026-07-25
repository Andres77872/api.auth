# Email Subsystem — Troubleshooting

Failure modes for the ROOT-only template API, the inbound Resend webhook, and the outbox worker. For deployment-side issues (queue growth, DLQ redrive, secret rotation, DNS/SPF/DKIM), see the [Email Activation Runbook](../../RUNBOOKS/email-activation.md).

---

## Template editing (`/admin/email-templates`)

| Symptom | Cause | Fix |
|---------|-------|-----|
| `403 ACCESS_DENIED` on any template endpoint | Caller is not ROOT | These are ROOT-only (`is_root_user`); a project-scoped admin cannot use them. Authenticate as a root user. |
| `404 RESOURCE_NOT_FOUND` on GET/PUT/preview/send-test | `template_code` is neither a built-in code nor a created dynamic code | Use one of the built-in codes (`email_activation`, `password_reset`, `admin_password_reset`, `security_notification`, `delivery_operation`, `patreon_link_proof`, `email_credit_grant_notification`) or create a dynamic internal code first. |
| Worker finalizes messages as `cancelled` with `EMAIL_TEMPLATE_DISABLED` | The template code was disabled through the admin API | Re-enable by saving a valid new version with PUT or by rolling back to a valid version. Do not redrive while disabled. |
| Worker retries with `EMAIL_TEMPLATE_LOOKUP_FAILED` | Template catalog/active-version state could not be read | Restore DB/stored-procedure availability. The worker intentionally does not fall back on lookup failure. |
| `404 RESOURCE_NOT_FOUND` on rollback | The requested `version` does not exist for that code | Call `GET /admin/email-templates/{code}` and pick a `version` from `versions[]`. |
| `400 INVALID_INPUT` "template uses variables outside the allowlist: ..." | The draft uses a `$placeholder` not in the per-code allowlist | Use only the `allowed_variables` for that code (see the GET response). |
| `400 INVALID_INPUT` "missing required template variables: ..." | The draft omits a required variable (e.g. `activation_link`, `reset_link`, `message`, `status_summary`) | Include every required placeholder for the code. |
| `400 INVALID_INPUT` "template contains an invalid $ placeholder" | A stray/malformed `$` in subject/html/text | Use `$name` / `${name}`; escape a literal dollar sign as `$$`. |
| `400 INVALID_INPUT` (HTML safety / render smoke test) | Draft fails `validate_template_draft` HTML safety or the render smoke test | Remove unsafe HTML/script; ensure the body renders against sample variables. The failing version is **not** saved. |
| Preview/test rendered with values you did not send | By design | Variable *values* are always the server-side `sample_variables`; admins inject template text, never values. |
| 422 on a request | Missing `User-Agent` header | Send a `User-Agent` header on every request. |

> `string.Template` (`$name`), not `str.format`, is used deliberately — `format` would expose attribute/expression injection on admin-editable text. A disallowed identifier is always rejected.

---

## Send-test (`POST /{code}/send-test`)

| Symptom | Cause | Fix |
|---------|-------|-----|
| `400` "You have no verified email address on file ..." | The ROOT caller has no `activated` email | Add and activate an email on the caller's account first (users suite); the recipient is **locked** to the caller's own activated address. |
| `400` "Email delivery is not ready (status: disabled ...)" | `EMAIL_DELIVERY_ENABLED=false` | Enable delivery (and ensure provider config) before testing. |
| `400` "Email delivery is not ready (status: not_ready ...)" | Missing provider config — e.g. `EMAIL_FROM_ADDRESS`, or for `resend` `RESEND_API_KEY`/`RESEND_WEBHOOK_SECRET`, or `EMAIL_SENDER_DOMAIN_VERIFIED` in prod | Fill the keys named in the readiness `missing[]` list. |
| "Too many test emails; please wait ..." (`RATE_LIMIT_EXCEEDED`) | The `email_template_test` buckets are exhausted (recipient 3/hr & 10/day, user 5/hr, IP 20/hr) or Redis is down (fail-closed) | Wait for the window to reset; if Redis is unavailable the limiter fails closed — restore Redis. |
| `400` "Test email could not be sent by the provider" | `provider.send` raised `EmailProviderError` | Check provider credentials/connectivity; inspect sanitized logs. |
| Expected the recipient address in the response | By design | Only `recipient_masked` is returned; the audit entry redacts the recipient entirely. There is no recipient body field. |

---

## Inbound webhook (`POST /webhooks/email/resend`)

| Symptom | Cause | Fix |
|---------|-------|-----|
| `400 "Invalid webhook signature"` | Missing one of `svix-id` / `svix-timestamp` / `svix-signature` | Ensure Resend/Svix sends all three headers; do not strip them at a proxy. |
| `400 "Invalid webhook signature"` (headers present) | Wrong `RESEND_WEBHOOK_SECRET`, or the body was re-serialized before verification | Deploy the correct Svix secret. Verification runs over the **raw bytes** — never JSON-parse-and-reserialize ahead of the endpoint. |
| `400` after timestamp skew | Event timestamp outside `RESEND_WEBHOOK_TOLERANCE_SECONDS` (default 300) | Fix clock skew or widen the tolerance. |
| Event accepted (`204`) but nothing changed | Unsupported event `type`, or the provider event id was already seen (Redis 24h dedupe / DB authority) | Expected — only `delivered`/`sent`/`bounced`/`complained` variants act; duplicates are idempotently ignored. |
| Expected a `200`/JSON result | The endpoint always returns `204 No Content` | There is no 2xx-with-body path. Only signature/header failures return `400`. |
| A bounce/complaint did not suppress | The event id was deduped, or the recipient could not be resolved to a local message | Confirm the event is first-seen and carries a resolvable recipient/message id; suppression is applied by `apply_email_provider_event`. |

---

## Outbox worker not delivering

| Symptom | Cause | Fix |
|---------|-------|-----|
| Rows queue up, nothing sends | `EMAIL_DELIVERY_ENABLED=false` | The worker logs "Email delivery disabled; worker drain skipped" and leaves rows durable. Enable delivery. |
| Worker process not running | `python -m src.workers.email_worker` not deployed/crashed | Start/restart the worker; it is deployed independently from the API. |
| Claims fail | MySQL < 8.0 (no `FOR UPDATE SKIP LOCKED`) or DB unreachable | Use MySQL 8.0+ and verify connectivity. |
| Real mail sent during tests unexpectedly, or blocked when you wanted it | No-real-send guard | In a test runtime, real `resend` sends are blocked unless `EMAIL_ALLOW_REAL_SEND_IN_TESTS=true`; for a dev box that should send, run `APP_ENV=development` (non-test runtime). |
| Messages dead-letter repeatedly | Render/template failure (permanent) or exhausted retries (`EMAIL_WORKER_MAX_ATTEMPTS`, default 8) | Render errors dead-letter immediately — fix the template first, then redrive. For provider/config causes, fix readiness first. See the runbook DLQ section. |
| Render payloads / recipient PII never purged | Running `--once` only (no auto-purge), or `EMAIL_RETENTION_PURGE_INTERVAL_SECONDS=0` | In `--once` batch mode schedule `sp_email_retention_purge` externally; otherwise the long-running worker purges on cadence. |

---

## Cross-references

- Deployment, rotation, DLQ redrive, retention, rollback → [Email Activation Runbook](../../RUNBOOKS/email-activation.md).
- Reading sanitized delivery logs (`GET /admin/email/logs`) → [Audit Logs Usage Cases](../audit-log-usage-cases.md).
- Per-user email add/activate/resend/remove → [Users Documentation](../users/README.md).
- Error envelope and codes → [Errors Reference](../errors.md).

---

**Document Version**: 1.0
