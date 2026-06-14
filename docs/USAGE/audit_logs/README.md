# Audit Logs Documentation

Detailed, repo-specific documentation for the audit and activity logging systems in `api.auth`.

---

## Overview

This documentation set covers the **two logging systems** that operate in this API, plus a redacted **email delivery log** surface:

```
HTTP REQUEST
  ├─► APIAuditMiddleware (every request) ──► api_audit_log table (raw HTTP audit trail)
  │
  └─► Route handler
        └─► @log_and_handle_errors decorator ──► activity_logs table (semantic operations)

EMAIL OUTBOX WORKER ──► email_messages table (delivery ledger; queried read-only by GET /admin/email/logs)
```

What matters operationally:

- **Two primary data sources**: `activity_logs` (semantic, decorator-based) and `api_audit_log` (raw HTTP, middleware-based)
- **A third, read-only source**: `email_messages` (delivery ledger populated by the email outbox worker) is exposed by `GET /admin/email/logs`, returning recipient hash + masked email only (no plaintext recipient/body/template vars)
- **Two distinct endpoint sets**: `/admin/activity` (dashboard) and `/admin/audit/*` (dedicated audit routes), plus `GET /admin/email/logs`
- **Security events merge both audit sources** into a unified view
- **Admin access is GLOBAL** — any admin/root can see ALL logs across ALL projects; there is NO project scoping
- **Export uses a JSON body** — one of the few endpoints in the API that accepts `application/json` (most use `multipart/form-data`)
- **Export hard limit is 10,000 records** — exceeding it returns a 400 error
- **No data retention policy** — logs accumulate indefinitely; `days` parameter limits queries but does not delete data

---

## Documents in This Suite

| Document | Focus |
|----------|-------|
| [usage.md](usage.md) | Day-to-day admin/compliance workflows: activity feed, audit logs, security events, user activity, email delivery logs, exports |
| [architecture.md](architecture.md) | Data sources, route organization, middleware vs decorator logging, table/procedure relationships, auth model |
| [request-flow.md](request-flow.md) | End-to-end flows: request capture, semantic logging, security aggregation, export, user activity merge |
| [scenarios.md](scenarios.md) | Concrete workflows with curl examples: security review, investigation, compliance, performance analysis |
| [reference.md](reference.md) | Endpoint/filter tables, export format/body reference, operational notes |
| [stored-procedures.md](stored-procedures.md) | SQL stored procedures for direct database queries of `api_audit_log` and `activity_logs` |
| [troubleshooting.md](troubleshooting.md) | Common failures: empty data, filter mistakes, export-limit issues, access scope caveats |

---

## Recommended Reading Order

1. Start with [usage.md](usage.md)
2. Then read [architecture.md](architecture.md) for the dual-system distinction
3. Use [request-flow.md](request-flow.md) for runtime behavior
4. Keep [reference.md](reference.md) open while operating the API
5. Use [scenarios.md](scenarios.md) and [troubleshooting.md](troubleshooting.md) when applying it to real workflows

---

## Scope and Caveats

- This suite documents the **active public route layer** under `src/routes/audit_logs.py` (618 lines, 6 endpoints) and `src/routes/admin_dashboard.py` (activity endpoints)
- `src/routes/audit_logs.py` exposes 6 endpoints: `GET /admin/email/logs`, `GET /admin/audit/logs`, `GET /admin/audit/security-events`, `GET /admin/audit/statistics`, `POST /admin/audit/export`, and `GET /admin/users/{user_id}/activity`
- The **middleware** that populates `api_audit_log` lives in `src/middleware/api_audit.py`
- The **decorator** that populates `activity_logs` lives in `src/Util/activity_logger.py`
- **Admin access is GLOBAL** — any admin can view audit logs for ALL projects, not just assigned ones. This is a data isolation gap.
- **Security events endpoint has no pagination** — returns a flat merged list with a limit but no offset/has_more
- **User activity timeline has no pagination** — fixed-size merge (50 entries per source max)
- **`audit` and `api_audit` are aliases in export** — both query the same `api_audit_log` data
- **`GET /admin/email/logs` has its own pagination contract** — `has_more` is a page-fill heuristic (`len(logs) == limit`), not a real total count like `/admin/audit/logs`
- The existing flat file `../audit-log-usage-cases.md` is a **legacy redirect** pointing here. SQL stored procedure documentation lives in [stored-procedures.md](stored-procedures.md).

---

## Related Documentation

- **[Usage Documentation Home](../README.md)** - Complete usage index
- **[Admin Usage Cases](../admin-usage-cases.md)** - Dashboard, system monitoring, activity feed quick reference
- **[Error Reference](../errors.md)** - Error codes, response shapes, and troubleshooting
- **[Authentication Usage Cases](../authentication-usage-cases.md)** - Login, session management, project switching
- **[Projects Documentation Suite](../projects/README.md)** - Project access model
- **[Users Documentation Suite](../users/README.md)** - User profile, access summary, and lifecycle operations
- **[Database Schema](../../../schemas/)** - SQL tables, views, and stored procedures

---

**Last Updated**: June 2026
**Document Version**: 1.1
