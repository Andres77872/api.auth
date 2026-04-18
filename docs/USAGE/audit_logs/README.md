# Audit Logs Documentation

Detailed, repo-specific documentation for the audit and activity logging systems in `api.auth`.

---

## Overview

This documentation set covers the **two logging systems** that operate in this API:

```
HTTP REQUEST
  ├─► APIAuditMiddleware (every request) ──► api_audit_log table (raw HTTP audit trail)
  │
  └─► Route handler
        └─► @log_and_handle_errors decorator ──► activity_logs table (semantic operations)
```

What matters operationally:

- **Two distinct data sources**: `activity_logs` (semantic, decorator-based) and `api_audit_log` (raw HTTP, middleware-based)
- **Two distinct endpoint sets**: `/admin/activity` (dashboard) and `/admin/audit/*` (dedicated audit routes)
- **Security events merge both sources** into a unified view
- **Admin access is GLOBAL** — any admin/root can see ALL logs across ALL projects; there is NO project scoping
- **Export uses JSON body** — one of only two endpoints in the API that accepts `application/json`
- **Export hard limit is 10,000 records** — exceeding it returns a 400 error
- **No data retention policy** — logs accumulate indefinitely; `days` parameter limits queries but does not delete data

---

## Documents in This Suite

| Document | Focus |
|----------|-------|
| [usage.md](usage.md) | Day-to-day admin/compliance workflows: activity feed, audit logs, security events, user activity, exports |
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

- This suite documents the **active public route layer** under `src/routes/audit_logs.py` (572 lines) and `src/routes/admin_dashboard.py` (activity endpoints)
- The **middleware** that populates `api_audit_log` lives in `src/middleware/api_audit.py`
- The **decorator** that populates `activity_logs` lives in `src/Util/activity_logger.py`
- **Admin access is GLOBAL** — any admin can view audit logs for ALL projects, not just assigned ones. This is a data isolation gap.
- **Security events endpoint has no pagination** — returns a flat merged list with a limit but no offset/has_more
- **User activity timeline has no pagination** — fixed-size merge (50 entries per source max)
- **`audit` and `api_audit` are aliases in export** — both query the same `api_audit_log` data
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

**Last Updated**: April 2026
**Document Version**: 1.0
