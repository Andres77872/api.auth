# Audit & Logging System

Complete documentation for audit logging, activity tracking, and error logging in the Magic Auth system.

---

## Table of Contents

1. [Overview](#overview)
2. [Activity Logging](#activity-logging)
3. [API Audit Log](#api-audit-log)
4. [Permission Audit Log](#permission-audit-log)
5. [Error Logging](#error-logging)
6. [Activity Catalog](#activity-catalog)
7. [Triggers](#triggers)
8. [Stored Procedures](#stored-procedures)
9. [Views](#views)
10. [Maintenance](#maintenance)

---

## Overview

The Magic Auth system implements comprehensive auditing at multiple levels:

| System | Purpose | Storage |
|--------|---------|---------|
| **Activity Logging** | Track user and system activities | `activity_logs` |
| **API Audit Log** | Complete API request/response logging | `api_audit_log` |
| **Permission Audit Log** | Permission change audit trail | `permission_audit_log` |
| **Error Logging** | Error tracking with statistics and alerts | `error_logs` |

### Key Features

- **Automatic Trigger-Based Logging**: 104 triggers are defined across the canonical trigger files; this guide details the 46 core/permission triggers below
- **90 Seeded Activity Types**: The canonical seed extends the original core catalog with email, Google OAuth, and Patreon activities
- **Error Tracking**: Always logs regardless of DEBUG_MODE
- **Alert System**: Automatic alerting for error patterns
- **Retention Management**: Cleanup procedures for old logs

---

## Activity Logging

### Table: `activity_logs`

```sql
CREATE TABLE activity_logs (
    id VARCHAR(64) NOT NULL,
    user_id VARCHAR(64),                        -- Who performed the action
    activity_type VARCHAR(50) NOT NULL,         -- Activity code
    activity_catalog_id VARCHAR(64),            -- Link to catalog
    details TEXT,                               -- Human-readable details
    project_id VARCHAR(64),                     -- Project context
    user_group_id VARCHAR(64),                  -- Group context
    target_user_id VARCHAR(64),                 -- Target of action
    ip_address VARCHAR(45),                     -- Client IP
    user_agent TEXT,                            -- Browser/client info
    metadata JSON,                              -- Additional structured data
    severity_level ENUM('info', 'warning', 'critical') NOT NULL DEFAULT 'info',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (id)
);
```

### Activity Logging Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_log_activity` | Log a new activity |
| `sp_get_activity_logs` | Query activities with filters |
| `sp_count_activity_logs` | Count matching activities |
| `sp_get_activity_stats` | Get activity statistics |
| `sp_get_user_activity_summary` | Get user's activity summary |
| `sp_get_recent_security_events` | Get recent security events |
| `sp_cleanup_old_activity_logs` | Clean old activity logs |

**Log Activity Example:**
```sql
CALL sp_log_activity(
    'act-uuid',                         -- id
    'user-id',                          -- user_id
    'user_login',                       -- activity_code
    'User logged in successfully',      -- details
    'project-id',                       -- project_id
    NULL,                               -- user_group_id
    NULL,                               -- target_user_id
    '192.168.1.100',                   -- ip_address
    'Mozilla/5.0...',                  -- user_agent
    '{"method": "password"}'           -- metadata (JSON)
);
```

**Query Activities Example:**
```sql
-- Get last 100 activities for user in last 7 days
CALL sp_get_activity_logs(
    100,            -- limit
    0,              -- offset
    'user-id',      -- user_id filter (NULL = all)
    NULL,           -- project_id filter
    NULL,           -- activity_code filter
    7               -- days back
);

-- Get login failures in last 24 hours
CALL sp_get_activity_logs(100, 0, NULL, NULL, 'user_login_failed', 1);

-- Count activities
CALL sp_count_activity_logs('user-id', NULL, NULL, 30);

-- Get activity statistics for project
CALL sp_get_activity_stats('project-id', 7);
-- Returns: activity_category, severity_level, activity_count, unique_users
```

**Security Events Example:**
```sql
-- Get recent warning/critical events
CALL sp_get_recent_security_events(
    24,             -- hours back
    100             -- limit
);
-- Returns: activities with severity_level IN ('warning', 'critical')
```

---

## API Audit Log

### Table: `api_audit_log`

```sql
CREATE TABLE api_audit_log (
    id VARCHAR(64) NOT NULL,
    request_id VARCHAR(64),                     -- Unique request identifier
    http_method VARCHAR(10) NOT NULL,           -- GET, POST, PUT, DELETE, etc.
    endpoint_path VARCHAR(512) NOT NULL,        -- API path
    route_pattern VARCHAR(512),                 -- Route pattern (e.g., /users/{id})
    user_id VARCHAR(64),                        -- Authenticated user
    user_type ENUM('root', 'admin', 'consumer'),
    session_id VARCHAR(256),                    -- Session identifier
    request_headers JSON,                       -- Request headers
    request_body JSON,                          -- Request body
    request_query JSON,                         -- Query parameters
    request_size_bytes INT,                     -- Request size
    response_status INT NOT NULL,               -- HTTP status code
    response_body JSON,                         -- Response body
    response_headers JSON,                      -- Response headers
    response_size_bytes INT,                    -- Response size
    request_timestamp DATETIME NOT NULL,        -- Request start time
    response_timestamp DATETIME,                -- Response end time
    duration_ms INT,                            -- Request duration
    client_ip VARCHAR(45),                      -- Client IP
    user_agent TEXT,                            -- User agent
    referer VARCHAR(512),                       -- Referer header
    is_success BOOLEAN,                         -- 2xx = success
    error_code VARCHAR(50),                     -- Error code if failed
    error_message TEXT,                         -- Error message if failed
    project_id VARCHAR(64),                     -- Project context
    target_resource_type VARCHAR(50),           -- Resource type affected
    target_resource_id VARCHAR(64),             -- Resource ID affected
    metadata JSON,                              -- Additional data
    tags JSON,                                  -- Tags for filtering
    requires_audit BOOLEAN DEFAULT TRUE,        -- Should be audited
    security_event BOOLEAN DEFAULT FALSE,       -- Is security event
    PRIMARY KEY (id)
);
```

### API Audit Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_log_api_request` | Log request start |
| `sp_update_api_response` | Log response completion |
| `sp_get_audit_logs` | Query audit logs |
| `sp_count_audit_logs` | Count audit logs |
| `sp_get_audit_statistics` | Get statistics |
| `sp_get_security_events` | Get security events |
| `sp_get_failed_requests` | Get failed requests |
| `sp_get_user_activity_summary` | Get user's API activity |

**Log Request/Response Example:**
```sql
-- Log request start (called by middleware at request start)
CALL sp_log_api_request(
    'audit-uuid',                       -- id
    'req-uuid',                         -- request_id
    'POST',                             -- http_method
    '/api/v1/users',                    -- endpoint_path
    '/api/v1/users',                    -- route_pattern
    'user-id',                          -- user_id
    'admin',                            -- user_type
    'session-id',                       -- session_id
    '{"Authorization": "..."}',         -- request_headers (JSON)
    '{"username": "new"}',              -- request_body (JSON)
    '{}',                               -- request_query (JSON)
    256,                                -- request_size_bytes
    '192.168.1.100',                   -- client_ip
    'Mozilla/5.0...',                  -- user_agent
    NULL,                               -- referer
    'project-id',                       -- project_id
    '{}'                                -- metadata (JSON)
);

-- Log response (called by middleware at response end)
CALL sp_update_api_response(
    'audit-uuid',                       -- id
    201,                                -- response_status
    '{"id": "new-user-id"}',           -- response_body (JSON)
    '{"Content-Type": "..."}',         -- response_headers (JSON)
    128,                                -- response_size_bytes
    NULL,                               -- error_code
    NULL,                               -- error_message
    'user',                             -- target_resource_type
    'new-user-id',                      -- target_resource_id
    '["user-creation"]',               -- tags (JSON)
    FALSE                               -- security_event
);
```

**Query Audit Logs Example:**
```sql
-- Get audit logs with filters
CALL sp_get_audit_logs(
    100,            -- limit
    0,              -- offset
    'user-id',      -- user_id (NULL = all)
    'project-id',   -- project_id (NULL = all)
    '/api/v1/users',-- endpoint_path (partial match)
    'POST',         -- http_method (NULL = all)
    NULL,           -- status_code (NULL = all)
    FALSE,          -- is_success (NULL = all)
    FALSE,          -- security_event (NULL = all)
    30              -- days back
);

-- Get failed requests
CALL sp_get_failed_requests(100, 0, 7);

-- Get security events
CALL sp_get_security_events(100, 0, 30);

-- Get statistics
CALL sp_get_audit_statistics(7);
-- Returns 4 result sets:
--   1. Overall stats (total, success, failed, avg_duration, etc.)
--   2. Requests by method
--   3. Top endpoints
--   4. Status code distribution
```

---

## Permission Audit Log

### Table: `permission_audit_log`

```sql
CREATE TABLE permission_audit_log (
    id VARCHAR(64) NOT NULL,
    action_type VARCHAR(50) NOT NULL,           -- Action performed
    project_id VARCHAR(64),                     -- Project context
    target_user_id VARCHAR(64),                 -- User affected
    user_group_id VARCHAR(64),                  -- Group affected
    permission_id VARCHAR(64),                  -- Permission affected
    permission_group_id VARCHAR(64),            -- Permission group affected
    performed_by VARCHAR(64),                   -- Who performed action
    old_values JSON,                            -- Previous state
    new_values JSON,                            -- New state
    action_timestamp DATETIME NOT NULL,
    performed_at DATETIME NOT NULL,
    ip_address VARCHAR(45),
    user_agent TEXT,
    table_name VARCHAR(100),                    -- Source table
    record_id VARCHAR(64),                      -- Source record ID
    PRIMARY KEY (id)
);
```

### Permission Audit Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_log_permission_change` | Log permission change |
| `sp_rbac_get_project_audit_log` | Get project's permission audit |

**Log Permission Change Example:**
```sql
CALL sp_log_permission_change(
    'audit-uuid',                       -- id
    'permission_granted',               -- action_type
    'project-id',                       -- project_id
    'target-user-id',                   -- target_user_id
    'user-group-id',                    -- user_group_id
    'permission-id',                    -- permission_id
    'perm-group-id',                    -- permission_group_id
    'admin-user-id',                    -- performed_by
    '{}',                               -- old_values (JSON)
    '{"permission": "users.create"}',   -- new_values (JSON)
    '192.168.1.100',                   -- ip_address
    'Mozilla/5.0...',                  -- user_agent
    'user_group_permission_groups',     -- table_name
    'record-id'                         -- record_id
);
```

**Query Permission Audit Example:**
```sql
-- Get project's permission audit log
CALL sp_rbac_get_project_audit_log(
    'project-id',
    NULL,           -- action_type filter (NULL = all)
    100,            -- limit
    0               -- offset
);
-- Returns: id, action_type, table_name, record_id, old_values, new_values, performed_by, performed_at, ip_address, user_agent, project_id
```

---

## Error Logging

### Table: `error_logs`

```sql
CREATE TABLE error_logs (
    id VARCHAR(64) NOT NULL,
    error_hash VARCHAR(255) NOT NULL,           -- Unique error identifier
    error_code VARCHAR(20) NOT NULL,            -- e.g., AUTH_1001, VAL_3001
    error_category VARCHAR(50) NOT NULL,        -- authentication, validation, etc.
    error_message TEXT NOT NULL,                -- User-friendly message
    status_code INT NOT NULL,                   -- HTTP status code
    severity_level ENUM('info', 'warning', 'error', 'critical') NOT NULL DEFAULT 'error',
    user_id VARCHAR(64) NULL,                   -- User who encountered error
    project_id VARCHAR(64) NULL,                -- Project context
    session_id VARCHAR(256) NULL,               -- Session ID
    request_path VARCHAR(500) NULL,             -- API endpoint
    request_method VARCHAR(10) NULL,            -- HTTP method
    request_query_params JSON NULL,             -- Query parameters
    client_ip VARCHAR(45) NULL,                 -- Client IP
    user_agent TEXT NULL,                       -- User agent
    function_name VARCHAR(255) NULL,            -- Function where error occurred
    function_params JSON NULL,                  -- Function parameters (sanitized)
    error_context TEXT NULL,                    -- Full context string
    error_details JSON NULL,                    -- Additional details
    database_error JSON NULL,                   -- DB-specific error info
    original_error_type VARCHAR(255) NULL,      -- Original exception type
    original_error_message TEXT NULL,           -- Original error message
    stack_trace LONGTEXT NULL,                  -- Full stack trace
    created_at DATETIME NOT NULL,
    environment VARCHAR(20) NULL,               -- development, staging, production
    debug_mode BOOLEAN NOT NULL DEFAULT FALSE,  -- Was DEBUG_MODE enabled
    PRIMARY KEY (id),
    UNIQUE KEY uk_error_hash (error_hash)
);
```

**Important**: Error logging ALWAYS occurs regardless of DEBUG_MODE. DEBUG_MODE only controls what's returned in API responses.

### Error Statistics Table: `error_log_statistics`

```sql
CREATE TABLE error_log_statistics (
    id VARCHAR(64) NOT NULL,
    error_code VARCHAR(20) NOT NULL,
    error_category VARCHAR(50) NOT NULL,
    occurrence_count INT NOT NULL DEFAULT 1,
    first_occurrence DATETIME NOT NULL,
    last_occurrence DATETIME NOT NULL,
    affected_users_count INT NOT NULL DEFAULT 0,
    affected_projects_count INT NOT NULL DEFAULT 0,
    date_bucket DATE NOT NULL,                  -- Daily aggregation
    hour_bucket INT NOT NULL,                   -- Hourly aggregation (0-23)
    PRIMARY KEY (id),
    UNIQUE KEY uk_error_stats (error_code, date_bucket, hour_bucket)
);
```

### Error Alerts Table: `error_log_alerts`

```sql
CREATE TABLE error_log_alerts (
    id VARCHAR(64) NOT NULL,
    alert_type ENUM('spike', 'critical_error', 'repeated_error', 'new_error') NOT NULL,
    error_code VARCHAR(20) NOT NULL,
    error_category VARCHAR(50) NOT NULL,
    alert_message TEXT NOT NULL,
    occurrence_count INT NOT NULL,
    time_window_minutes INT NOT NULL,
    threshold_exceeded BOOLEAN NOT NULL DEFAULT TRUE,
    first_detected DATETIME NOT NULL,
    last_updated DATETIME NOT NULL,
    acknowledged BOOLEAN NOT NULL DEFAULT FALSE,
    acknowledged_by VARCHAR(64) NULL,
    acknowledged_at DATETIME NULL,
    resolved BOOLEAN NOT NULL DEFAULT FALSE,
    resolved_by VARCHAR(64) NULL,
    resolved_at DATETIME NULL,
    resolution_notes TEXT NULL,
    PRIMARY KEY (id)
);
```

### Error Logging Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_log_error` | Log error (always logs) |
| `sp_get_error_logs` | Query error logs |
| `sp_get_error_by_id` | Get error with full stack trace |
| `sp_get_error_statistics` | Get aggregated statistics |
| `sp_get_critical_errors` | Get critical/500 errors |
| `sp_get_error_trends` | Get error trends over time |
| `sp_get_error_log_summary` | Get dashboard summary |

### Error Alert Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_create_error_alert` | Create alert |
| `sp_get_active_alerts` | Get unresolved alerts |
| `sp_acknowledge_alert` | Mark alert acknowledged |
| `sp_resolve_alert` | Mark alert resolved |

### Error Cleanup

| Procedure | Description |
|-----------|-------------|
| `sp_cleanup_old_error_logs` | Clean old logs |

**Log Error Example:**
```sql
CALL sp_log_error(
    'err-hash-unique',                  -- error_hash
    'AUTH_1001',                        -- error_code
    'authentication',                   -- error_category
    'Invalid credentials',              -- error_message
    401,                                -- status_code
    'warning',                          -- severity_level
    'user-id',                          -- user_id
    'project-id',                       -- project_id
    'session-id',                       -- session_id
    '/api/v1/auth/login',              -- request_path
    'POST',                             -- request_method
    '{}',                               -- request_query_params (JSON)
    '192.168.1.100',                   -- client_ip
    'Mozilla/5.0...',                  -- user_agent
    'authenticate_user',                -- function_name
    '{"username": "john"}',            -- function_params (JSON, sanitized)
    'authenticate_user(john)',          -- error_context
    '{}',                               -- error_details (JSON)
    '{}',                               -- database_error (JSON)
    'InvalidCredentialsError',          -- original_error_type
    'Password mismatch',                -- original_error_message
    'Traceback...',                     -- stack_trace
    'production',                       -- environment
    FALSE                               -- debug_mode
);
```

**Query Errors Example:**
```sql
-- Get error logs with filters
CALL sp_get_error_logs(
    100,                    -- limit
    0,                      -- offset
    'AUTH_1001',           -- error_code (NULL = all)
    'authentication',       -- error_category (NULL = all)
    NULL,                   -- severity_level (NULL = all)
    NULL,                   -- user_id (NULL = all)
    NULL,                   -- project_id (NULL = all)
    NULL,                   -- start_date (NULL = no min)
    NULL                    -- end_date (NULL = no max)
);

-- Get error with full stack trace
CALL sp_get_error_by_id('err-uuid');

-- Get critical errors (last 24 hours)
CALL sp_get_critical_errors(100, 24);

-- Get error statistics
CALL sp_get_error_statistics(
    '2024-01-01',          -- start_date (NULL = no min)
    '2024-12-31',          -- end_date (NULL = no max)
    'authentication'        -- error_category (NULL = all)
);

-- Get error trends
CALL sp_get_error_trends(
    7,                      -- days_back
    NULL                    -- error_category (NULL = all)
);

-- Get dashboard summary
CALL sp_get_error_log_summary(24);
-- Returns 3 result sets:
--   1. Overall summary (total, unique codes, affected users, severity breakdown)
--   2. Top error codes
--   3. Errors by category
```

**Alert Management Example:**
```sql
-- Create alert for error spike
CALL sp_create_error_alert(
    'spike',                            -- alert_type
    'AUTH_1001',                        -- error_code
    'authentication',                   -- error_category
    'Login failures spiked: 50 in 5 minutes',  -- alert_message
    50,                                 -- occurrence_count
    5                                   -- time_window_minutes
);

-- Get active (unresolved) alerts
CALL sp_get_active_alerts();
-- Returns: alerts sorted by priority (critical > spike > repeated > other)

-- Acknowledge alert
CALL sp_acknowledge_alert('alert-id', 'admin-user-id');

-- Resolve alert
CALL sp_resolve_alert('alert-id', 'admin-user-id', 'Fixed by rate limiting login attempts');
```

---

## Activity Catalog

### Table: `activity_catalog`

Defines all possible activity types:

```sql
CREATE TABLE activity_catalog (
    id VARCHAR(64) NOT NULL,
    activity_code VARCHAR(50) NOT NULL,         -- Unique code
    activity_name VARCHAR(100) NOT NULL,        -- Display name
    activity_description TEXT,
    activity_category VARCHAR(50) NOT NULL DEFAULT 'general',
    severity_level ENUM('info', 'warning', 'critical') NOT NULL DEFAULT 'info',
    requires_audit BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL,
    updated_at DATETIME,
    PRIMARY KEY (id),
    UNIQUE KEY uk_activity_code (activity_code)
);
```

### Original Core Activity Types (First 40)

The tables below document the original `act-cat-001` through `act-cat-040`
catalog. The authoritative seed now continues through `act-cat-090`; inspect
`schemas/tables/08_activity_logging_tables.sql` for the email, Google OAuth, and
Patreon additions. Billing IDs `act-cat-091` through `act-cat-106` exist in
runtime constants but are not currently present in the SQL seed.

#### Authentication (5 types)

| Code | Name | Severity |
|------|------|----------|
| `user_login` | User Login | info |
| `user_logout` | User Logout | info |
| `user_login_failed` | Login Failed | warning |
| `session_created` | Session Created | info |
| `session_expired` | Session Expired | info |

#### User Management (6 types)

| Code | Name | Severity |
|------|------|----------|
| `user_registration` | User Registration | info |
| `user_update` | User Updated | info |
| `user_status_change` | User Status Changed | warning |
| `user_password_reset` | Password Reset | warning |
| `user_type_changed` | User Type Changed | critical |
| `user_deleted` | User Deleted | critical |

#### Project Management (6 types)

| Code | Name | Severity |
|------|------|----------|
| `project_creation` | Project Created | info |
| `project_update` | Project Updated | info |
| `project_delete` | Project Deleted | critical |
| `project_archived` | Project Archived | warning |
| `project_unarchived` | Project Unarchived | info |
| `project_ownership_transferred` | Ownership Transferred | critical |

#### Project Members (3 types)

| Code | Name | Severity |
|------|------|----------|
| `project_member_add` | Member Added | info |
| `project_member_remove` | Member Removed | warning |
| `project_member_removed` | Member Left | info |

#### Group Management (7 types)

| Code | Name | Severity |
|------|------|----------|
| `group_creation` | Group Created | info |
| `group_update` | Group Updated | info |
| `group_delete` | Group Deleted | critical |
| `user_group_assign` | User Assigned to Group | info |
| `user_group_remove` | User Removed from Group | warning |
| `group_project_access_granted` | Group Project Access | warning |
| `group_project_access_revoked` | Group Access Revoked | warning |

#### Permission Management (6 types)

| Code | Name | Severity |
|------|------|----------|
| `permission_grant` | Permission Granted | warning |
| `permission_revoke` | Permission Revoked | warning |
| `role_removed` | Role Removed | warning |
| `role_assigned` | Role Assigned | warning |
| `permission_group_assigned` | Permission Group Assigned | warning |
| `permission_group_revoked` | Permission Group Revoked | warning |

#### Bulk Operations (4 types)

| Code | Name | Severity |
|------|------|----------|
| `bulk_role_assignment` | Bulk Role Assignment | critical |
| `bulk_group_assignment` | Bulk Group Assignment | warning |
| `bulk_user_update` | Bulk User Update | warning |
| `bulk_user_delete` | Bulk User Delete | critical |

#### Admin/System/Security (3 types)

| Code | Name | Severity |
|------|------|----------|
| `admin_action` | Admin Action | warning |
| `system_event` | System Event | info |
| `security_alert` | Security Alert | critical |

### Activity Catalog Procedures

| Procedure | Description |
|-----------|-------------|
| `sp_get_activity_catalog` | Get activity types by category |
| `sp_get_activity_by_code` | Get activity type by code |

**Example:**
```sql
-- Get all authentication activity types
CALL sp_get_activity_catalog('authentication');

-- Get specific activity type
CALL sp_get_activity_by_code('user_login');
```

---

## Triggers

### Activity Logging Triggers - Core Entities

**File**: `triggers/01_activity_logging_triggers.sql` (21 triggers)

| Table | Triggers | Activity Types |
|-------|----------|----------------|
| `users` | INSERT, UPDATE, DELETE | registration, update, type_changed, status_change, password_reset, deleted |
| `projects` | INSERT, UPDATE, DELETE | creation, update, archived, unarchived, ownership_transferred, delete |
| `user_groups` | INSERT, UPDATE, DELETE | group_creation, group_update, group_delete |
| `project_groups` | INSERT, UPDATE, DELETE | project_group_creation, project_group_update, project_group_delete |
| `user_group_members` | INSERT, UPDATE, DELETE | user_group_assign, user_group_remove |
| `project_group_members` | INSERT, UPDATE, DELETE | project_group_assign, project_group_remove |
| `user_group_project_groups` | INSERT, UPDATE, DELETE | access_granted, access_revoked |

### Activity Logging Triggers - Permissions

**File**: `triggers/02_permission_activity_triggers.sql` (25 triggers)

| Table | Triggers | Activity Types |
|-------|----------|----------------|
| `roles` | INSERT, UPDATE, DELETE | role_assigned, role_removed |
| `global_permission_groups` | INSERT, UPDATE, DELETE | permission_group_assigned, permission_group_revoked |
| `global_permissions` | INSERT, UPDATE, DELETE | permission_grant, permission_revoke |
| `role_permission_groups` | INSERT, DELETE | permission_group_assigned, permission_group_revoked |
| `user_group_permission_groups` | INSERT, DELETE | permission_group_assigned, permission_group_revoked |
| `user_permission_groups` | INSERT, DELETE | permission_group_assigned, permission_group_revoked |
| `global_permission_group_permissions` | INSERT, DELETE | permission_grant, permission_revoke |
| `user_sessions` | INSERT, UPDATE | session_created, user_logout |
| `user_group_project_group_permissions` | INSERT, UPDATE, DELETE | permission_group_assigned, permission_group_revoked |
| `user_group_project_group_roles` | INSERT, UPDATE, DELETE | role_assigned, role_removed |

---

## Stored Procedures

### Activity Context Management

**File**: `stored_procedures/12_activity_context.sql`

| Procedure/Function | Description |
|--------------------|-------------|
| `sp_set_activity_context` | Set session context for triggers |
| `sp_clear_activity_context` | Clear session context |
| `sp_get_activity_context` | Get current context (debug) |
| `fn_get_context_user_id` | Helper function for context resolution |

**Set Context Example:**
```sql
-- Before operations, set the context
CALL sp_set_activity_context(
    'user-id',                  -- user_id
    '192.168.1.100',           -- ip_address
    'Mozilla/5.0...'           -- user_agent
);

-- Triggers will use this context

-- After operations, clear context (optional)
CALL sp_clear_activity_context();
```

---

## Views

### Error Monitoring Views

| View | Description |
|------|-------------|
| `v_recent_error_logs` | Last 24 hours errors |
| `v_error_summary_by_code` | Error aggregation by code |
| `v_critical_errors` | Critical/500 errors |
| `v_error_frequency_hourly` | Error frequency over time (7 days) |

**View Examples:**
```sql
-- Recent errors
SELECT * FROM v_recent_error_logs ORDER BY created_at DESC LIMIT 100;

-- Error summary
SELECT * FROM v_error_summary_by_code ORDER BY total_occurrences DESC;

-- Critical errors
SELECT * FROM v_critical_errors ORDER BY created_at DESC;

-- Hourly frequency
SELECT * FROM v_error_frequency_hourly 
WHERE error_date = CURDATE() 
ORDER BY error_hour DESC;
```

---

## Maintenance

### Cleanup Procedures

| Procedure | Parameters | Description |
|-----------|------------|-------------|
| `sp_cleanup_old_activity_logs` | `retention_days, dry_run` | Clean old activity logs |
| `sp_cleanup_old_error_logs` | `days_to_keep` | Clean old error logs |

**Activity Log Cleanup:**
```sql
-- Dry run (see what would be deleted)
CALL sp_cleanup_old_activity_logs(90, TRUE);
-- Returns: logs_to_delete, cutoff_date, status

-- Actual cleanup (deletes info-level logs only, keeps warning/critical)
CALL sp_cleanup_old_activity_logs(90, FALSE);
-- Returns: logs_deleted, cutoff_date, status
```

**Error Log Cleanup:**
```sql
-- Clean error logs older than 90 days
CALL sp_cleanup_old_error_logs(90);
-- Returns: deleted_error_logs, deleted_statistics, message
```

### Recommended Schedule

| Frequency | Task | Command |
|-----------|------|---------|
| Daily | Check critical errors | `CALL sp_get_critical_errors(100, 24);` |
| Daily | Check active alerts | `CALL sp_get_active_alerts();` |
| Weekly | Error summary review | `CALL sp_get_error_log_summary(168);` |
| Monthly | Clean activity logs | `CALL sp_cleanup_old_activity_logs(90, FALSE);` |
| Monthly | Clean error logs | `CALL sp_cleanup_old_error_logs(90);` |

### Monitoring Queries

```sql
-- Total activity logs
SELECT COUNT(*) FROM activity_logs;

-- Activity by severity (last 7 days)
SELECT severity_level, COUNT(*) as count
FROM activity_logs
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY severity_level;

-- Top error codes (last 24 hours)
SELECT error_code, COUNT(*) as count
FROM error_logs
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
GROUP BY error_code
ORDER BY count DESC
LIMIT 10;

-- Active alerts count
SELECT alert_type, COUNT(*) as count
FROM error_log_alerts
WHERE resolved = FALSE
GROUP BY alert_type;
```

---

## Indexes

### Activity Logs Indexes

| Index | Purpose |
|-------|---------|
| `idx_user_activity` | User + date queries |
| `idx_project_activity` | Project + date queries |
| `idx_activity_type` | Activity type + date queries |
| `idx_severity` | Severity + date queries |
| `idx_target_user` | Target user queries |
| `idx_created_at` | Date range queries |

### API Audit Log Indexes

| Index | Purpose |
|-------|---------|
| `idx_timestamp` | Date queries |
| `idx_user_time` | User + date queries |
| `idx_endpoint` | Endpoint queries |
| `idx_status` | Status code queries |
| `idx_success` | Success/failure queries |
| `idx_security` | Security event queries |

### Error Log Indexes

| Index | Purpose |
|-------|---------|
| `idx_error_code` | Error code queries |
| `idx_error_category` | Category queries |
| `idx_severity` | Severity queries |
| `idx_user_id` | User queries |
| `idx_created_at` | Date queries |
| `idx_composite_search` | Category + severity + date |
