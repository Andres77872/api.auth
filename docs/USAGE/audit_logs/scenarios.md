# Audit Logs Scenarios

Concrete admin and compliance workflows for the audit and activity logging systems in `api.auth`.

---

## Table of Contents

- [Security Scenarios](#security-scenarios)
- [Investigation Scenarios](#investigation-scenarios)
- [Compliance Scenarios](#compliance-scenarios)
- [Performance Scenarios](#performance-scenarios)

---

## Security Scenarios

### Scenario 1: Daily Security Review

**Goal:** Review security-relevant events from the past 24 hours.

```bash
# Step 1: Check critical security events from both sources
curl -X GET "http://localhost:8000/admin/audit/security-events?severity=critical&days=1" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: Check warning-level events
curl -X GET "http://localhost:8000/admin/audit/security-events?severity=warning&days=1" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 3: Split by source for detailed analysis
curl -X GET "http://localhost:8000/admin/audit/security-events?source=api_audit&severity=critical&days=1" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X GET "http://localhost:8000/admin/audit/security-events?source=activity_log&severity=critical&days=1" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**What to look for:**
- Multiple 403 responses from the same IP (potential brute force)
- 401 responses on `/auth/login` from unfamiliar IPs
- DELETE requests to unexpected endpoints
- Activity log entries for `permission_grant` or `user_type_changed`

---

### Scenario 2: Investigate Failed Login Attempts

**Goal:** Find all failed login attempts in the past week.

```bash
# Step 1: Find failed requests to the login endpoint
curl -X GET "http://localhost:8000/admin/audit/logs?endpoint_path=/auth/login&is_success=false&days=7&limit=200" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: Cross-reference with activity log for login failures
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=user_login&days=7&limit=200" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 3: Get security events for this pattern
curl -X GET "http://localhost:8000/admin/audit/security-events?source=api_audit&days=7&limit=500" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**What to look for:**
- Same `client_ip` with multiple 401 responses
- Same `user_id` with repeated failures from different IPs
- Pattern of failures followed by a success (potential compromised account)

---

### Scenario 3: Track Permission Changes

**Goal:** Audit all permission grants and revocations in the past month.

```bash
# Step 1: Activity log for permission grants
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=permission_grant&days=30&limit=200" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: Activity log for permission revocations
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=permission_revoke&days=30&limit=200" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 3: API audit for requests to permission endpoints
curl -X GET "http://localhost:8000/admin/audit/logs?endpoint_path=/permissions&days=30&limit=200" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## Investigation Scenarios

### Scenario 4: Investigate a Specific User

**Goal:** Audit all actions by a specific user over the past 30 days.

```bash
# Step 1: Get combined user activity (both sources)
curl -X GET "http://localhost:8000/admin/users/{user_id}/activity?days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: Get their API audit logs
curl -X GET "http://localhost:8000/admin/audit/logs?user_id={user_id}&days=30&limit=500" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 3: Get their activity log entries
curl -X GET "http://localhost:8000/admin/activity?user_id={user_id}&days=30&limit=500" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**What to look for:**
- Unusual endpoint access patterns
- Requests outside normal working hours
- Access to projects the user shouldn't have
- Failed requests followed by successful ones (potential exploitation)

---

### Scenario 5: Investigate a Specific Project

**Goal:** Monitor all changes to a specific project.

```bash
# Step 1: Activity log for the project
curl -X GET "http://localhost:8000/admin/activity?project_id={project_id}&days=30&limit=200" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: API audit logs for the project
curl -X GET "http://localhost:8000/admin/audit/logs?project_id={project_id}&days=30&limit=500" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 3: Filter to project update events only
curl -X GET "http://localhost:8000/admin/activity?project_id={project_id}&activity_type_filter=project_update&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 4: Filter to membership changes
curl -X GET "http://localhost:8000/admin/activity?project_id={project_id}&activity_type_filter=project_member_add&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### Scenario 6: Track Who Changed User Types

**Goal:** Find all user type changes in the past week.

```bash
# Step 1: Activity log for user type changes
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=user_type_changed&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: API audit for requests to user-type endpoints
curl -X GET "http://localhost:8000/admin/audit/logs?endpoint_path=/user-types&days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## Compliance Scenarios

### Scenario 7: Monthly Compliance Export

**Goal:** Generate a full audit export for compliance purposes.

```bash
# Step 1: Export API audit logs for the past 30 days (CSV)
curl -X POST "http://localhost:8000/admin/audit/export" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "api_audit",
    "format": "csv",
    "limit": 10000,
    "filters": { "days": 30 }
  }' \
  --output audit_export_api_30d.csv

# Step 2: Export activity logs for the past 30 days (CSV)
curl -X POST "http://localhost:8000/admin/audit/export" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "activity",
    "format": "csv",
    "limit": 10000,
    "filters": { "days": 30 }
  }' \
  --output audit_export_activity_30d.csv
```

**If the export fails with 400 INVALID_RANGE**, your filters match more than 10,000 records. Narrow the filters:

```bash
# Export week by week instead
curl -X POST "http://localhost:8000/admin/audit/export" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "api_audit",
    "format": "csv",
    "limit": 10000,
    "filters": { "days": 7 }
  }' \
  --output audit_export_week1.csv
```

---

### Scenario 8: Export Security Events Only

**Goal:** Export only security-flagged audit log entries.

```bash
curl -X POST "http://localhost:8000/admin/audit/export" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "source": "api_audit",
    "format": "json",
    "limit": 5000,
    "filters": {
      "security_event": true,
      "days": 90
    }
  }' \
  --output security_events_90d.json
```

---

## Performance Scenarios

### Scenario 9: API Performance Analysis

**Goal:** Identify slow or problematic endpoints.

```bash
# Step 1: Get audit statistics
curl -X GET "http://localhost:8000/admin/audit/statistics?days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: Find all 500 errors
curl -X GET "http://localhost:8000/admin/audit/logs?status_code=500&days=30&limit=200" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 3: Find slow endpoints (filter by specific endpoint, check duration_ms in response)
curl -X GET "http://localhost:8000/admin/audit/logs?endpoint_path=/admin/dashboard&days=7&limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Use the `top_endpoints` section from statistics** to identify which endpoints have the highest failure rates or longest average durations.

---

### Scenario 10: Identify High-Volume Users

**Goal:** Find users generating the most API traffic.

```bash
# Step 1: Get audit statistics for method breakdown
curl -X GET "http://localhost:8000/admin/audit/statistics?days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: Check specific user activity
curl -X GET "http://localhost:8000/admin/users/{user_id}/activity?days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

The `api_audit_summary` in the user activity response includes `total_requests` and `unique_endpoints` for volume analysis.

---

## Related Documentation

- **[Audit Logs Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**
- **[Admin Usage Cases](../admin-usage-cases.md)** — Dashboard, activity feed quick reference

---

**Last Updated**: April 2026
**Document Version**: 1.0
