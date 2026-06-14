# Audit Logs Troubleshooting, Caveats, and Best Practices

Things that commonly confuse operators working with the audit and activity logging systems in `api.auth`.

---

## Troubleshooting

### Consumer User Gets 403 on Audit Endpoints

All audit endpoints (`/admin/email/logs`, `/admin/audit/*`, `/admin/activity*`, `/admin/users/{id}/activity`) require **root or admin** user type. Consumer users are always denied.

**Error:** 403 `ACCESS_DENIED` — "Admin access required"

**Fix:** use a root or admin token. There is no permission-based bypass for audit access.

---

### Empty Results from Audit Logs

**Issue:** `GET /admin/audit/logs` returns an empty `logs` array.

**Possible causes:**

1. **Time range too narrow** — the `days` parameter defaults to 30. If no requests were logged in that window, results are empty. Try increasing `days`.

2. **Filters too restrictive** — combining multiple filters (user_id + endpoint_path + status_code) may match zero records. Remove filters one at a time to isolate the issue.

3. **Endpoint is excluded from logging** — `/ping`, `/health`, `/metrics`, `/docs`, `/redoc`, `/openapi.json`, `/auth/validate`, and `OPTIONS` requests are never logged.

4. **Middleware not registered** — if `APIAuditMiddleware` is not added to the FastAPI app in `main.py`, no requests are captured. Check application startup logs.

**Diagnostic:**

```bash
# Broad query — no filters
curl -X GET "http://localhost:8000/admin/audit/logs?days=365&limit=10" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# If still empty, check middleware registration in main.py
```

---

### Empty Results from Activity Feed

**Issue:** `GET /admin/activity` returns an empty `activities` array.

**Possible causes:**

1. **No semantic events logged** — the `@log_and_handle_errors` decorator only logs when `activity_type` is set. Read-only endpoints typically skip activity logging.

2. **Time range too narrow** — same as audit logs.

3. **Stored procedures missing** — the activity feed relies on `sp_get_activity_logs`. Verify: `SHOW PROCEDURE STATUS LIKE 'sp_%activity%'`.

**Diagnostic:**

```bash
# Broad query
curl -X GET "http://localhost:8000/admin/activity?days=365&limit=10" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Check available activity types
curl -X GET "http://localhost:8000/admin/activity/types" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### Export Fails with 400 INVALID_RANGE

**Issue:** `POST /admin/audit/export` returns:

```json
{
  "error": {
    "code": "INVALID_RANGE",
    "message": "Export would return 15000 records, exceeding the hard limit of 10000"
  }
}
```

**Cause:** The pre-export count check found more matching records than the 10,000 hard limit.

**Fix:** Narrow your filters:

```bash
# Instead of 30 days, try 7 days
{
  "source": "api_audit",
  "format": "csv",
  "limit": 10000,
  "filters": { "days": 7 }
}

# Or add more specific filters
{
  "source": "api_audit",
  "format": "csv",
  "limit": 10000,
  "filters": { "days": 30, "project_id": "specific-project" }
}
```

**Workaround:** export in chunks (week by week, project by project) and merge locally.

---

### Export Returns Empty CSV with Just an Empty Row

**Issue:** CSV export returns a single empty row instead of proper headers.

**Cause:** When no data matches the export filters, the CSV generator yields `writer.writerow([])` — a single empty row, not a header row.

**Fix:** narrow or broaden your filters to ensure matching data. Check with the corresponding list endpoint first:

```bash
# Verify data exists before exporting
curl -X GET "http://localhost:8000/admin/audit/logs?days=30&limit=1" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### Security Events Endpoint Returns Fewer Results Than Expected

**Issue:** Requesting 500 security events returns only 200.

**Cause:** The limit applies to the **merged** result from both sources, not per-source. If `api_audit` contributes 300 events and `activity_log` contributes 200, the merged list is 500, then truncated to the limit.

Additionally, severity filtering (`severity=critical`) is applied **per-source** before merging, which can further reduce results.

**Fix:** use the `source` filter to query each source independently:

```bash
curl -X GET "http://localhost:8000/admin/audit/security-events?source=api_audit&limit=500&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X GET "http://localhost:8000/admin/audit/security-events?source=activity_log&limit=500&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### User Activity Timeline Seems Incomplete

**Issue:** `GET /admin/users/{user_id}/activity` returns fewer timeline entries than expected.

**Cause:** The timeline is a **fixed-size merge** — up to 50 entries from `activity_logs` and up to 50 from `api_audit_log`, sorted together. If a user has 200 activity log entries, only the 50 most recent are included.

**Fix:** use the list endpoints directly for complete data:

```bash
# Full activity log for user
curl -X GET "http://localhost:8000/admin/activity?user_id={user_id}&days=30&limit=500" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Full API audit log for user
curl -X GET "http://localhost:8000/admin/audit/logs?user_id={user_id}&days=30&limit=1000" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### Empty or Confusing Results from `GET /admin/email/logs`

**Issue:** The email delivery log returns no rows, or `has_more` behaves unexpectedly.

**Possible causes and fixes:**

1. **Filter value typo** — `status` and `purpose` are matched exactly. Valid `status` values: `pending`, `processing`, `sent`, `delivered`, `bounced`, `complained`, `suppressed`, `retry`, `dead`, `cancelled`. Valid `purpose` values: `email_activation`, `password_reset`, `admin_password_reset`, `security_notification`, `delivery_operation`. An unknown value is accepted but matches nothing (returns an empty `logs` array, not an error).

2. **`provider` mismatch** — `provider` is exact-match free text (default `resend`). Querying `?provider=Resend` (wrong case) or a provider you don't use returns nothing.

3. **No email subsystem activity** — if the email outbox worker has not run (or no transactional emails were sent), `email_messages` is empty. Confirm with a broad query: `GET /admin/email/logs?limit=10` (no filters).

4. **`has_more` page-fill heuristic** — this endpoint does **not** run a count query. `has_more` is `true` whenever `returned == limit`. On an exactly-full final page, `has_more` reports `true` even though the next page (`offset += limit`) is empty. Page until a request returns fewer than `limit` rows; do not rely on `has_more` as an authoritative "more data exists" signal.

**Diagnostic:**

```bash
# Broad query, no filters
curl -X GET "http://localhost:8000/admin/email/logs?limit=10" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

---

### Cannot See Audit Logs for a Specific Project

**Issue:** An admin assigned to only one project expects to see only that project's logs.

**Cause:** Audit access is **GLOBAL**. Any admin can see ALL audit logs across ALL projects. There is no project-scoping for audit endpoints. If you see logs from other projects, this is by design.

**This is a data isolation gap.** If your compliance requirements demand project-scoped audit access, this needs an architectural change.

---

### Export Uses JSON Body While Rest of API Uses Form Data

**Issue:** Sending `multipart/form-data` to `POST /admin/audit/export` fails.

**Cause:** The export endpoint accepts an `application/json` body, which is unusual — most POST/PUT/PATCH endpoints in the API use `multipart/form-data`. Other JSON-body endpoints include `POST /admin/user-groups/{hash}/members/bulk` and the Google sign-in endpoints in `auth_google.py` (e.g. `POST /auth/google/start`, `/link/finish`, `/reauth/start`).

**Fix:** always use `Content-Type: application/json` for export requests:

```bash
curl -X POST "http://localhost:8000/admin/audit/export" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"source": "api_audit", "format": "csv"}'
```

---

### `audit` and `api_audit` Are the Same Source in Export

**Issue:** Confusion about whether `audit` and `api_audit` export different data.

**Cause:** Both source names query the same `api_audit_log` table. `audit` is kept for backward compatibility; `api_audit` is the canonical name.

**Best practice:** always use `api_audit` for clarity.

---

## Current Caveats

### Admin Access Is Global

Any admin can view audit logs for ALL projects. There is no project-level access check. This is by design but may conflict with compliance requirements that demand data isolation.

### No Data Retention Policy

Logs accumulate indefinitely. The `days` parameter limits queries but does not delete old data. The `api_audit_log` and `activity_logs` tables grow unbounded.

**Mitigation:** implement your own archival process (e.g., periodic exports + manual cleanup).

### Security Events Have No Pagination

The security events endpoint returns a flat list. For large datasets, use the `source` filter to split queries.

### User Activity Timeline Has No Pagination

Fixed-size merge (50 per source). Use the individual list endpoints for complete data.

### Sensitive Data Is Always Filtered

Passwords, tokens, and API keys appear as `***FILTERED***` in audit logs. This cannot be disabled. If you need raw request bodies for debugging, check application logs, not audit logs.

### Empty CSV Export Returns Empty Row

When no data matches export filters, CSV returns a single empty row, not a proper header row. This is a known limitation.

---

## Best Practices

### 1. Always filter by date

Use the `days` parameter to limit queries. Without it, you scan the entire table.

```bash
# Good
curl -X GET "http://localhost:8000/admin/audit/logs?days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Bad — scans everything
curl -X GET "http://localhost:8000/admin/audit/logs" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### 2. Use the right endpoint for the right question

| Question | Use |
|----------|-----|
| "What happened?" (business events) | `/admin/activity` |
| "What HTTP requests were made?" | `/admin/audit/logs` |
| "What security-relevant events occurred?" | `/admin/audit/security-events` |
| "What's the overall API health?" | `/admin/audit/statistics` |
| "What did this user do?" | `/admin/users/{id}/activity` |
| "Did this email get delivered?" | `/admin/email/logs` |
| "I need a compliance report" | `POST /admin/audit/export` |

### 3. Export in chunks for large datasets

If your filters match more than 10,000 records, export week by week or project by project:

```bash
# Week 1
curl -X POST "http://localhost:8000/admin/audit/export" \
  -H "Content-Type: application/json" \
  -d '{"source": "api_audit", "format": "csv", "filters": {"days": 7}}' \
  --output week1.csv

# Week 2
curl -X POST "http://localhost:8000/admin/audit/export" \
  -H "Content-Type: application/json" \
  -d '{"source": "api_audit", "format": "csv", "filters": {"days": 7}}' \
  --output week2.csv
```

### 4. Use `api_audit` not `audit` in export

Both work, but `api_audit` is the canonical name. `audit` is backward-compatibility only.

### 5. Cross-reference both sources for investigations

Security events merge both sources, but for deep investigations, query each source independently:

```bash
# Check API audit for the user
curl -X GET "http://localhost:8000/admin/audit/logs?user_id=X&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Check activity log for the user
curl -X GET "http://localhost:8000/admin/activity?user_id=X&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

### 6. Monitor export limits proactively

Before running a large export, check the count:

```bash
# Get total count first
curl -X GET "http://localhost:8000/admin/audit/logs?days=30&limit=1&offset=0" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# Check pagination.total — if > 10000, narrow your filters before exporting
```

---

## Related Documentation

- **[Audit Logs Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Error Reference](../errors.md)** — All error codes and response shapes

---

**Last Updated**: June 2026
**Document Version**: 1.1
