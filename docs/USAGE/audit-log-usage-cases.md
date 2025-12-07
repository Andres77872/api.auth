# Audit Log Management Usage Guide

Complete practical guide for viewing, filtering, and managing audit logs and event logs in the authentication system.

---

## 📖 Table of Contents

- [Audit Log Overview](#audit-log-overview)
- [Activity Logs](#activity-logs)
- [API Audit Logs](#api-audit-logs)
- [Security Events](#security-events)
- [User Activity Tracking](#user-activity-tracking)
- [Filtering and Search](#filtering-and-search)
- [Common Scenarios](#common-scenarios)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Audit Log Overview

The authentication system maintains comprehensive audit trails through two logging systems:

### Logging Systems

| System | Table | Purpose | Auto-Logged |
|--------|-------|---------|-------------|
| **Activity Logs** | `activity_logs` | User actions, admin operations, system events | Via decorators |
| **API Audit Logs** | `api_audit_log` | All HTTP requests/responses | Via middleware |

### Activity Types

The system tracks these activity categories:

| Category | Activities | Severity |
|----------|------------|----------|
| **Authentication** | user_login, user_logout, user_registration | info |
| **User Management** | user_update, user_status_change, user_password_reset, user_type_changed | info/warning |
| **Project Management** | project_creation, project_update, project_delete, project_archived | info |
| **Group Management** | group_creation, group_update, group_delete, user_group_assign, user_group_remove | info |
| **Permission Management** | permission_grant, permission_revoke, role_removed | warning |
| **Bulk Operations** | bulk_role_assignment, bulk_group_assignment, bulk_user_update, bulk_user_delete | warning |
| **System Events** | admin_action, system_event | info/critical |

---

## Activity Logs

### Get Activity Feed

**Scenario**: View recent system activities with pagination and filtering.

```bash
# Basic activity feed
curl -X GET "http://localhost:8000/admin/activity" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# With pagination
curl -X GET "http://localhost:8000/admin/activity?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Filter by activity type
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=user_login" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Filter by user
curl -X GET "http://localhost:8000/admin/activity?user_id=123" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Filter by project
curl -X GET "http://localhost:8000/admin/activity?project_id=456" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Custom time range (days)
curl -X GET "http://localhost:8000/admin/activity?days=7" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Combined filters
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=user_login&days=7&limit=100" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "activities": [
    {
      "id": "act-12345...",
      "activity_type": "user_login",
      "details": {"action": "login", "timestamp": "2024-03-25T10:25:00Z"},
      "created_at": "2024-03-25T10:25:00Z",
      "user": {
        "id": "123",
        "username": "john_doe",
        "user_hash": "usr-abc123..."
      },
      "project": {
        "id": "456",
        "name": "API v2",
        "hash": "proj-xyz789..."
      },
      "target_user": null,
      "ip_address": "192.168.1.100"
    }
  ],
  "pagination": {
    "total": 1580,
    "limit": 50,
    "offset": 0,
    "has_more": true,
    "next_offset": 50
  },
  "filters": {
    "activity_type": null,
    "user_id": null,
    "project_id": null,
    "days": 30
  },
  "generated_at": "2024-03-25T10:30:00Z"
}
```

### Get Activity Types

**Scenario**: Get list of all available activity types for filtering.

```bash
curl -X GET "http://localhost:8000/admin/activity/types" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

**Response:**
```json
{
  "activity_types": [
    "user_login",
    "user_logout",
    "user_registration",
    "user_update",
    "user_status_change",
    "user_password_reset",
    "user_type_changed",
    "project_creation",
    "project_update",
    "project_delete",
    "project_member_add",
    "project_member_remove",
    "project_ownership_transferred",
    "project_archived",
    "project_unarchived",
    "group_creation",
    "group_update",
    "group_delete",
    "user_group_assign",
    "user_group_remove",
    "permission_grant",
    "permission_revoke",
    "role_removed",
    "bulk_role_assignment",
    "bulk_group_assignment",
    "bulk_user_update",
    "bulk_user_delete",
    "admin_action",
    "system_event"
  ],
  "generated_at": "2024-03-25T10:30:00Z"
}
```

---

## API Audit Logs

API audit logs automatically capture all HTTP requests and responses. These logs are recorded by the middleware and can be queried directly from the database.

### Log Structure

Each API audit log entry contains:

| Field | Description |
|-------|-------------|
| `id` | Unique audit log ID |
| `request_id` | Request correlation ID |
| `http_method` | GET, POST, PUT, DELETE, PATCH |
| `endpoint_path` | Full request path |
| `user_id` | Authenticated user (if any) |
| `user_type` | root, admin, consumer |
| `response_status` | HTTP status code |
| `duration_ms` | Request processing time |
| `client_ip` | Client IP address |
| `user_agent` | Browser/client user agent |
| `request_timestamp` | When request was received |
| `response_timestamp` | When response was sent |
| `is_success` | True if 2xx status |
| `error_code` | Error code (if failed) |
| `error_message` | Error details (if failed) |
| `security_event` | True if security-relevant |
| `tags` | Searchable tags array |

### Query API Audit Logs (Database)

**Note**: API audit logs are queried via stored procedures. Use these SQL queries:

```sql
-- Get recent audit logs (last 7 days)
CALL sp_get_audit_logs(50, 0, NULL, NULL, NULL, NULL, NULL, NULL, NULL, 7);

-- Filter by user
CALL sp_get_audit_logs(50, 0, 'user-id-123', NULL, NULL, NULL, NULL, NULL, NULL, 7);

-- Filter by endpoint
CALL sp_get_audit_logs(50, 0, NULL, NULL, '/auth/login', NULL, NULL, NULL, NULL, 7);

-- Filter by HTTP method
CALL sp_get_audit_logs(50, 0, NULL, NULL, NULL, 'POST', NULL, NULL, NULL, 7);

-- Filter by status code
CALL sp_get_audit_logs(50, 0, NULL, NULL, NULL, NULL, 401, NULL, NULL, 7);

-- Filter failed requests only
CALL sp_get_audit_logs(50, 0, NULL, NULL, NULL, NULL, NULL, FALSE, NULL, 7);

-- Filter security events only
CALL sp_get_audit_logs(50, 0, NULL, NULL, NULL, NULL, NULL, NULL, TRUE, 7);

-- Count audit logs
CALL sp_count_audit_logs(NULL, NULL, NULL, NULL, NULL, NULL, NULL, 7);
```

### Get Audit Statistics

```sql
-- Get comprehensive audit statistics
CALL sp_get_audit_statistics(7);
```

**Returns multiple result sets:**
1. **Overall Statistics**: Total requests, success/failure counts, average duration
2. **Requests by Method**: Breakdown by GET, POST, PUT, DELETE
3. **Top Endpoints**: Most accessed endpoints with success/failure rates
4. **Status Code Distribution**: Count of each HTTP status code

---

## Security Events

Security events are automatically flagged for requests that involve:
- Failed authentication (401 on `/auth/` endpoints)
- Unauthorized access attempts (403)
- Admin actions
- DELETE operations
- User type/permission changes
- Password resets

### Get Security Events

```sql
-- Get recent security events
CALL sp_get_security_events(50, 0, 7);
```

**Response fields:**
```json
{
  "id": "audit-abc123...",
  "request_id": "req-xyz789...",
  "http_method": "POST",
  "endpoint_path": "/auth/login",
  "user_id": "123",
  "user_type": "consumer",
  "client_ip": "192.168.1.50",
  "response_status": 401,
  "error_code": "AUTH_INVALID_CREDENTIALS",
  "error_message": "Invalid username or password",
  "request_timestamp": "2024-03-25T10:30:00Z",
  "duration_ms": 45,
  "tags": ["post", "client_error", "authentication"],
  "username": "john_doe"
}
```

### Get Failed Requests

```sql
-- Get recent failed requests (for monitoring)
CALL sp_get_failed_requests(50, 0, 7);
```

---

## User Activity Tracking

### Get User Activity Summary

Track a specific user's API usage patterns:

```sql
-- Get user activity summary
CALL sp_get_user_activity_summary('user-id-123', 30);
```

**Returns:**
1. **Summary**: Total requests, success/failure counts, unique endpoints, first/last request
2. **Recent Activity**: Top endpoints accessed by user with timestamps

### Track User Actions via Activity Logs

```bash
# Get all activities for a specific user
curl -X GET "http://localhost:8000/admin/activity?user_id=123&days=30" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Get user login history
curl -X GET "http://localhost:8000/admin/activity?user_id=123&activity_type_filter=user_login&days=90" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

## Filtering and Search

### Activity Log Filters

| Parameter | Type | Description |
|-----------|------|-------------|
| `limit` | int | Max results (1-100, default 50) |
| `offset` | int | Skip results for pagination |
| `activity_type_filter` | string | Filter by activity type |
| `user_id` | string | Filter by user ID |
| `project_id` | string | Filter by project ID |
| `days` | int | Days to look back (1-365, default 30) |

### API Audit Log Filters (Database)

| Parameter | Type | Description |
|-----------|------|-------------|
| `p_limit` | int | Max results |
| `p_offset` | int | Skip results |
| `p_user_id` | string | Filter by user ID |
| `p_project_id` | string | Filter by project ID |
| `p_endpoint_path` | string | Filter by endpoint (partial match) |
| `p_http_method` | string | GET, POST, PUT, DELETE |
| `p_status_code` | int | Exact status code match |
| `p_is_success` | boolean | Success (2xx) or failure |
| `p_security_event` | boolean | Security events only |
| `p_days` | int | Days to look back |

### Filter Examples

```bash
# Authentication events only
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=user_login&days=7" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Permission changes only
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=permission_grant&days=30" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Admin actions in a specific project
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=admin_action&project_id=456&days=7" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"

# Bulk operations
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=bulk_user_update&days=30" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

---

## Common Scenarios

### Scenario 1: Daily Security Review

**Goal**: Review security-relevant events from the past 24 hours.

```bash
# Step 1: Check for failed login attempts
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=user_login&days=1" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: Check for permission changes
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=permission_grant&days=1" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 3: Check for admin actions
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=admin_action&days=1" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

```sql
-- Step 4: Check API security events (database)
CALL sp_get_security_events(100, 0, 1);

-- Step 5: Check failed API requests
CALL sp_get_failed_requests(50, 0, 1);
```

### Scenario 2: Investigate Suspicious User Activity

**Goal**: Audit all actions by a specific user.

```bash
# Step 1: Get user's activity history
curl -X GET "http://localhost:8000/admin/activity?user_id=123&days=30&limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: Check login patterns
curl -X GET "http://localhost:8000/admin/activity?user_id=123&activity_type_filter=user_login&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

```sql
-- Step 3: Get user's API activity summary
CALL sp_get_user_activity_summary('123', 30);

-- Step 4: Get user's API audit logs
CALL sp_get_audit_logs(100, 0, '123', NULL, NULL, NULL, NULL, NULL, NULL, 30);
```

### Scenario 3: Monthly Compliance Report

**Goal**: Generate audit report for compliance purposes.

```bash
# Step 1: Get all admin actions
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=admin_action&days=30&limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 2: Get all permission changes
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=permission_grant&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=permission_revoke&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 3: Get all user status changes
curl -X GET "http://localhost:8000/admin/activity?activity_type_filter=user_status_change&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

```sql
-- Step 4: Get audit statistics
CALL sp_get_audit_statistics(30);

-- Step 5: Count security events
CALL sp_count_audit_logs(NULL, NULL, NULL, NULL, NULL, NULL, TRUE, 30);
```

### Scenario 4: Troubleshoot API Errors

**Goal**: Investigate API failures and errors.

```sql
-- Step 1: Get recent failed requests
CALL sp_get_failed_requests(100, 0, 7);

-- Step 2: Filter by specific endpoint
CALL sp_get_audit_logs(50, 0, NULL, NULL, '/auth/login', NULL, NULL, FALSE, NULL, 7);

-- Step 3: Get 500 errors
CALL sp_get_audit_logs(50, 0, NULL, NULL, NULL, NULL, 500, NULL, NULL, 7);

-- Step 4: Get audit statistics for error patterns
CALL sp_get_audit_statistics(7);
```

### Scenario 5: Track Project Changes

**Goal**: Monitor all changes to a specific project.

```bash
# Get all activity for a project
curl -X GET "http://localhost:8000/admin/activity?project_id=456&days=30&limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Filter to project updates only
curl -X GET "http://localhost:8000/admin/activity?project_id=456&activity_type_filter=project_update&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Check membership changes
curl -X GET "http://localhost:8000/admin/activity?project_id=456&activity_type_filter=project_member_add&days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## Best Practices

### Log Review

1. **Daily reviews** - Check security events and failed logins daily
2. **Weekly summary** - Review admin actions and permission changes weekly
3. **Monthly audit** - Generate compliance reports monthly
4. **Retain logs** - Keep audit logs per your compliance requirements

### Monitoring

1. **Set up alerts** - Monitor for unusual activity patterns
2. **Track failed logins** - Multiple failures may indicate attacks
3. **Watch admin actions** - All admin operations should be expected
4. **Monitor bulk operations** - Verify bulk changes are authorized

### Security

1. **Protect audit logs** - Audit logs should be read-only for most users
2. **Archive regularly** - Archive old logs to maintain performance
3. **Encrypt backups** - Audit log backups should be encrypted
4. **Limit access** - Only authorized admins should view audit logs

### Performance

1. **Use pagination** - Always paginate large result sets
2. **Filter by date** - Use the `days` parameter to limit queries
3. **Index usage** - Queries use indexed columns for performance
4. **Archive old data** - Archive logs older than retention period

---

## Troubleshooting

### No Activity Logs Showing

**Issue**: Activity feed returns empty results

**Solutions**:
1. Verify you have admin/root access
2. Check the time range (days parameter)
3. Verify activities are being logged (check database directly)
4. Ensure stored procedures exist: `SHOW PROCEDURE STATUS LIKE 'sp_%activity%'`

### Missing API Audit Logs

**Issue**: API requests not appearing in audit log

**Solutions**:
1. Check middleware is registered in `main.py`
2. Verify endpoint is not in exclusion list (`APIAuditLogger.EXCLUDED_PATHS`)
3. Check database connection in middleware
4. Review application logs for errors

### Slow Audit Log Queries

**Issue**: Queries taking too long

**Solutions**:
1. Reduce the `days` parameter
2. Add more specific filters (user_id, project_id)
3. Check table indexes: `SHOW INDEX FROM activity_logs`
4. Consider archiving old logs

### Incomplete Log Data

**Issue**: Some fields are null in audit logs

**Solutions**:
1. **user_id null**: Request was unauthenticated
2. **project_id null**: No project context for the request
3. **target_user_id null**: Action didn't affect another user
4. **error_message null**: Request succeeded without errors

---

## Quick Reference

### Activity Log Endpoints

| Operation | Endpoint | Method | Permission |
|-----------|----------|--------|------------|
| Get activity feed | `/admin/activity` | GET | Admin/Root |
| Get activity types | `/admin/activity/types` | GET | Admin/Root |

### Activity Feed Query Parameters

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `limit` | int | 50 | Results per page (1-100) |
| `offset` | int | 0 | Skip for pagination |
| `activity_type_filter` | string | null | Filter by type |
| `user_id` | string | null | Filter by user |
| `project_id` | string | null | Filter by project |
| `days` | int | 30 | Look back period (1-365) |

### API Audit Log Stored Procedures

| Procedure | Parameters | Description |
|-----------|------------|-------------|
| `sp_get_audit_logs` | limit, offset, filters... | Query audit logs |
| `sp_count_audit_logs` | filters... | Count matching logs |
| `sp_get_audit_statistics` | days | Get statistics |
| `sp_get_security_events` | limit, offset, days | Security events |
| `sp_get_failed_requests` | limit, offset, days | Failed requests |
| `sp_get_user_activity_summary` | user_id, days | User activity |

### Activity Types by Category

**Authentication:**
- `user_login` - User logged in
- `user_logout` - User logged out
- `user_registration` - New user registered

**User Management:**
- `user_update` - User profile updated
- `user_status_change` - User activated/deactivated
- `user_password_reset` - Password was reset
- `user_type_changed` - User type modified

**Project Management:**
- `project_creation` - Project created
- `project_update` - Project modified
- `project_delete` - Project deleted
- `project_member_add` - Member added
- `project_member_remove` - Member removed
- `project_ownership_transferred` - Ownership changed
- `project_archived` / `project_unarchived` - Archive status

**Group Management:**
- `group_creation` - Group created
- `group_update` - Group modified
- `group_delete` - Group deleted
- `user_group_assign` - User added to group
- `user_group_remove` - User removed from group

**Permission Management:**
- `permission_grant` - Permission granted
- `permission_revoke` - Permission revoked
- `role_removed` - Role removed from user

**Bulk Operations:**
- `bulk_role_assignment` - Multiple role assignments
- `bulk_group_assignment` - Multiple group assignments
- `bulk_user_update` - Multiple users updated
- `bulk_user_delete` - Multiple users deleted

**System:**
- `admin_action` - Administrative action
- `system_event` - System-level event

---

## Related Documentation

- **[Admin Usage Cases](admin-usage-cases.md)** - Dashboard, system monitoring
- **[Users Usage Cases](users-usage-cases.md)** - User management
- **[Permissions Usage Cases](permissions-usage-cases.md)** - Permission management
- **[Authentication Usage Cases](authentication-usage-cases.md)** - Login, sessions

---

**Last Updated**: December 2024
**Document Version**: 1.0
