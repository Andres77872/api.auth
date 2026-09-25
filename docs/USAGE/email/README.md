# Email

The service sends transactional account email only: activation links, password-reset links,
security notices, delivery notices and a few integration messages. It is not a marketing or
newsletter system. Request handlers never send mail directly; they write a row to a MySQL outbox
that a separate worker delivers. Root users manage the email templates, trusted companion
services queue internal notices, and the provider reports delivery results through a signed
webhook.

## Key concepts

- **Outbox** (`email_messages`): one row per email, with an encrypted render payload, a status
  (`pending`, `processing`, `retry`, `sent`, `delivered`, `bounced`, `complained`, `suppressed`,
  `dead`, `cancelled`) and retry state.
- **Worker** (`src/workers/email_worker.py`): a separate process that claims due rows, renders
  the template, sends through the provider, and retries or dead-letters failures.
- **Provider**: `resend` for real mail, `mailpit` for local SMTP capture, or `fake` in tests,
  chosen by `EMAIL_PROVIDER`. Nothing is sent while `EMAIL_DELIVERY_ENABLED=false` (the default).
- **Templates**: each code has a catalog row (purpose, allowed and required variables, enabled
  flag, revision) and a history of stored versions. Built-in codes fall back to bodies in
  `src/Util/email/templates.py` until a version is saved. Placeholders use `$name`.
- **Suppression**: a bounce or complaint reported by the provider blocks later sends to that
  address and marks a matching account email `suppressed`.
- **Privacy**: recipients are stored as a peppered hash plus a masked form (`a***e@example.com`);
  render variables are encrypted until sent and then cleared.

### Built-in template codes

| Code | Purpose | Required variables | Sent by |
| --- | --- | --- | --- |
| `email_activation` | `email_activation` | `activation_link` | Email add and resend flows (users suite) |
| `password_reset` | `password_reset` | `reset_link` | `POST /auth/password/forgot` |
| `admin_password_reset` | `admin_password_reset` | `reset_link` | Admin-triggered reset (users suite) |
| `security_notification` | `security_notification` | `message` | `POST /internal/email/send-template` |
| `delivery_operation` | `delivery_operation` | `status_summary` | `POST /internal/email/send-template` |
| `email_credit_grant_notification` | `delivery_operation` | `credits`, `action_url`, `expires_at` | `POST /internal/email/send-template` |
| `patreon_link_proof` | `patreon_link_proof` | `patreon_link_proof_url`, `proof_token` | Patreon link flow |

Root users can add dynamic codes, limited to the `delivery_operation` and
`security_notification` purposes.

## Route families

| Family | Routes | Auth | Body |
| --- | --- | --- | --- |
| Template admin | 8 routes under `/admin/email-templates` | Access token of a root user | JSON |
| Internal email | 3 routes under `/internal/email` | Access token of a root user | JSON |
| Provider webhook | `POST /webhooks/email/resend` | Svix signature over the raw body; no access token | Raw provider JSON |

Endpoint tables are in [reference.md](reference.md).

## Rules and caveats

Platform-wide rules are in [Platform-wide contracts](../README.md#platform-wide-contracts). These
apply to this suite:

- **Root only.** Template routes check `is_root_user` (`403` `AUTHZ_2001` otherwise); internal
  routes use `require_root_user` (`403` `AUTHZ_2002`). Admin users and global-role permissions do
  not grant access.
- **Internal routes use a root session, not a service credential.** Despite the prefix, there is
  no dedicated S2S token. A companion service calling them holds a root access token and must keep
  it server-side.
- **JSON bodies.** A body that fails schema validation returns `400` `VAL_3001`
  ("Request validation failed").
- **Only send-test bypasses the outbox.** `POST /admin/email-templates/{template_code}/send-test`
  sends immediately to the caller's own activated address. Everything else is queued.
- **Disabling a built-in template stops that email.** Queued messages for a disabled code are
  cancelled when the worker claims them.
- **Link origins.** Activation and reset links use `AUTH_EMAIL_PUBLIC_BASE_URL` when set,
  otherwise the `X-Public-Base-Url` header if its origin is in `ALLOWED_ORIGINS`, otherwise the
  request's own origin.

## Out of scope here

- Adding, activating, resending and removing a user's addresses: [Users email
  management](../users/email-management.md).
- Public verify, forgot and reset flows under `/auth/...`: [Authentication usage
  cases](../authentication-usage-cases.md).
- Reading the outbox as an admin (`GET /admin/email/logs`) and the email activity catalog:
  [Audit logs usage](../audit_logs/usage.md#email-delivery-logs).
- Rollout, secret rotation, dead-letter redrive and retention operations:
  [Email activation runbook](../../RUNBOOKS/email-activation.md).

## In this suite

| Document | Purpose |
| --- | --- |
| [usage.md](usage.md) | Tasks: manage templates, send internal email, check status, wire the webhook, run the worker |
| [reference.md](reference.md) | Endpoints, bodies, validation rules, responses, error codes, webhook events, configuration |
| [architecture.md](architecture.md) | Outbox and worker pipeline, providers, template resolution, idempotency, rate limits, retention |
| [troubleshooting.md](troubleshooting.md) | Symptom, cause and fix for templates, send-test, internal sends, webhook and worker |

## Related

- [Audit logs](../audit_logs/README.md) — delivery log and email activity entries
- [Users](../users/README.md) — account email addresses
- [System health](../admin-usage-cases.md) — `email_provider` and `email_worker` health components
- [Errors](../errors.md) — error envelope and `EMAIL_9xxx` codes
