# Email Documentation

Repo-specific documentation for the **transactional auth email** subsystem in `api.auth`: the ROOT-only admin API for DB-managed email templates, the inbound Resend/Svix delivery webhook, and the durable MySQL outbox worker that actually sends mail.

---

## 📖 Overview

This subsystem is **transactional auth email only** — activation links, password-reset links, admin-triggered reset links, security notifications, and delivery-status notices. It is **not** marketing, newsletters, broadcast notifications, or a preference center.

Three operator-facing surfaces live here:

- **Admin email templates** (`/admin/email-templates`, **ROOT only**) — list, inspect, edit (PUT creates a new active version), preview, send a locked self-test, and roll back DB-managed transactional templates. Six endpoints.
- **Inbound provider webhook** (`POST /webhooks/email/resend`) — Svix-signature-verified Resend delivery/bounce/complaint callbacks. No application auth; always returns `204`.
- **Outbox delivery model** (`src/workers/email_worker.py`) — a separate worker process claims durable MySQL outbox rows and sends them through the configured provider. Documented at a high level in [architecture.md](architecture.md).

The five transactional template codes are:

| Code | Purpose | Required variable |
|------|---------|-------------------|
| `email_activation` | Email-address activation link | `activation_link` |
| `password_reset` | Self-service password-reset link | `reset_link` |
| `admin_password_reset` | Admin-triggered reset link | `reset_link` |
| `security_notification` | Account security event notice | `message` |
| `delivery_operation` | Transactional delivery-status notice | `status_summary` |

---

## 🗂️ Documents in This Suite

| Document | Focus |
|----------|-------|
| [usage.md](usage.md) | Day-to-day template flows: inspect, edit, preview, self-test, rollback, and webhook setup |
| [reference.md](reference.md) | Endpoint table for the 6 `/admin/email-templates` routes + the webhook, plus the email config/env reference |
| [architecture.md](architecture.md) | Outbox-worker delivery pipeline, provider abstraction, template versioning, idempotency, rate limiting, and safety guards |
| [troubleshooting.md](troubleshooting.md) | Failure modes for template edits, self-tests, webhooks, and the worker |

---

## 🔐 Auth at a Glance

The six `/admin/email-templates` endpoints are **ROOT only**. Auth is two-layered:

1. `HTTPBearerOrCookie` resolves the session (bearer token or session cookie).
2. `_require_root` → `is_root_user(user_id)` gates **every** handler. A non-root caller gets an `AuthorizationError` with error code `ACCESS_DENIED`.

These are **not** generic admin endpoints — editing security-email content is high-impact, so a project-scoped admin cannot use them.

`POST /webhooks/email/resend` has **no application auth**. It is authenticated by the Svix signature over the raw request body; missing `svix-*` headers or a bad signature return `400`.

> Every request must include a `User-Agent` header (missing ⇒ `422`).

---

## 🚦 Recommended Reading Order

1. Start with [usage.md](usage.md) to edit/preview/roll back a template.
2. Read [reference.md](reference.md) for exact request/response shapes and config keys.
3. Read [architecture.md](architecture.md) to understand how a queued message actually ships.
4. Keep [troubleshooting.md](troubleshooting.md) open when a self-test or webhook fails.

---

## ⚠️ Scope and Out-of-Scope Cross-Links

This suite documents `src/routes/email_templates.py` and `src/routes/email_webhooks.py`, plus the delivery internals in `src/Util/email/*` and `src/workers/email_worker.py`. The following email-related surfaces live **elsewhere** and are not redefined here:

- **`GET /admin/email/logs`** — sanitized email activity/delivery logs live in the **audit suite** (`src/routes/audit_logs.py`). See [Audit Logs Usage Cases](../audit-log-usage-cases.md).
- **Per-user email management** — adding, listing, activating, resending, and removing a user's email addresses (`/users/me/emails*`, `/users/{user_hash}/emails*`) lives in the **users suite**. See [Users Documentation](../users/README.md).
- **Public verify / forgot / reset flows** — `/auth/...` endpoints are documented in the authentication material. See [Authentication Usage Cases](../authentication-usage-cases.md).
- **Deployment, rollout, rotation, DLQ redrive, retention, and rollback** — operational procedures live in the runbook. See [Email Activation & Transactional Auth Email Runbook](../../RUNBOOKS/email-activation.md) (reference only; this suite does not duplicate it).

---

## 🔗 Related Documentation

- **[Usage Documentation Home](../README.md)** — complete usage index
- **[Audit Logs Usage Cases](../audit-log-usage-cases.md)** — where `GET /admin/email/logs` is documented
- **[Users Documentation Suite](../users/README.md)** — per-user email management endpoints
- **[Authentication Usage Cases](../authentication-usage-cases.md)** — public verify/forgot/reset flows
- **[Email Activation Runbook](../../RUNBOOKS/email-activation.md)** — deployment/operations
- **[Errors Reference](../errors.md)** — error envelope and codes

---

**Last Updated**: June 2026
**Document Version**: 1.0
**API Version**: 2.2.0
