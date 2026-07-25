# Audit Log Management (Legacy)

> **This document is deprecated.** The authoritative documentation is now the **[Audit Logs Documentation Suite](audit_logs/README.md)**.

## What moved where

| Former Content | New Location |
|----------------|-------------|
| Activity feed (`/admin/activity`) | [audit_logs/usage.md](audit_logs/usage.md#activity-feed-dashboard) |
| Activity types (`/admin/activity/types`) | [audit_logs/usage.md](audit_logs/usage.md#activity-feed-dashboard) |
| Activity detail (`/admin/activity/{id}`) | [audit_logs/reference.md](audit_logs/reference.md#dashboard-activity-endpoints) |
| API audit logs (`/admin/audit/*`) | [audit_logs/usage.md](audit_logs/usage.md#api-audit-logs) |
| Security events | [audit_logs/usage.md](audit_logs/usage.md#security-events) |
| Export functionality | [audit_logs/usage.md](audit_logs/usage.md#export) |
| Audit statistics | [audit_logs/usage.md](audit_logs/usage.md#audit-statistics) |
| User activity timeline | [audit_logs/usage.md](audit_logs/usage.md#user-activity) |
| Email delivery logs (`GET /admin/email/logs`) | [audit_logs/usage.md](audit_logs/usage.md#email-delivery-logs) · [audit_logs/reference.md](audit_logs/reference.md#adminemaillogs-filters) |
| SQL stored procedures | [audit_logs/stored-procedures.md](audit_logs/stored-procedures.md) |
| Architecture & data sources | [audit_logs/architecture.md](audit_logs/architecture.md) |
| Scenarios & workflows | [audit_logs/scenarios.md](audit_logs/scenarios.md) |
| Troubleshooting | [audit_logs/troubleshooting.md](audit_logs/troubleshooting.md) |

## Start here

- **[Audit Logs Documentation Suite](audit_logs/README.md)** — Complete guide to activity feed, API audit logs, security events, export, and compliance workflows

## Email Activation / Delivery Audit Quick Reference

The email activation subsystem adds activity catalog entries `act-cat-046` through `act-cat-062`:

| Catalog ID | Activity |
|------------|----------|
| `act-cat-046` | `user_email_added` |
| `act-cat-047` | `user_email_activation_requested` |
| `act-cat-048` | `user_email_activation_resent` |
| `act-cat-049` | `user_email_activated` |
| `act-cat-050` | `user_email_removed` |
| `act-cat-051` | `user_email_primary_changed` |
| `act-cat-052` | `auth_email_login` |
| `act-cat-053` | `password_reset_requested` |
| `act-cat-054` | `password_reset_consumed` |
| `act-cat-055` | `admin_password_reset_requested` |
| `act-cat-056` | `email_message_enqueued` |
| `act-cat-057` | `email_message_sent` |
| `act-cat-058` | `email_message_delivered` |
| `act-cat-059` | `email_message_bounced` |
| `act-cat-060` | `email_message_complained` |
| `act-cat-061` | `email_message_dead_lettered` |
| `act-cat-062` | `email_suppression_updated` |
| `act-cat-063` | `password_changed` |

`password_changed` is the successful self-service `POST /auth/password/change` activity. It is distinct from `password_reset_requested`, `password_reset_consumed`, and `admin_password_reset_requested`: change-password is authenticated and current-password re-authenticated; public reset consume is link-based and creates no session; admin reset only requests link delivery.

Admin/root operators can inspect delivery state through:

```bash
curl -X GET "http://localhost:8000/admin/email/logs?limit=50" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

Redaction guarantees:

- Email audit and delivery log responses expose recipient hash plus masked email only.
- Audit and delivery records must not expose tokens, token secrets, full activation/reset links, plaintext full emails, subject/body, template variables, raw `Idempotency-Key`, provider credentials, or full provider payloads.
- Password-change audit/activity records must not expose `current_password`, `new_password`, password hashes, token secrets, full links, or provider payloads. Non-secret revocation counts are acceptable.
- Provider webhook-originated events use webhook auth-method taxonomy and must not record raw webhook bodies.
- Public email-link token consumes may use email-link auth-method taxonomy, but still preserve generic public `202` behavior.

---

**Document Version**: 2.0 (Legacy)
