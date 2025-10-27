# Audit Log System Architecture

**Magic Auth System - Comprehensive Activity Auditing**

---

## Overview

The Audit Log system provides comprehensive tracking and auditing of all significant user actions within the Magic Auth system. It is designed to capture administrative actions, security-critical operations, and system changes while intelligently filtering out routine operations like session validation and permission verification.

### Key Principles

1. **Selective Logging** - Only log meaningful actions that represent state changes or administrative decisions
2. **Hierarchical Filtering** - Focus on root and admin actions; minimal logging for consumer routine operations
3. **Performance Conscious** - Avoid logging high-frequency operations (session checks, permission lookups)
4. **Audit Compliance** - Provide complete audit trail for security-sensitive operations
5. **Contextual Information** - Capture IP address, user agent, and request metadata automatically

---

## System Components

### 1. Database Layer

#### Tables

##### **activity_catalog**
Defines all possible activity types in the system.

```sql
CREATE TABLE activity_catalog (
    id VARCHAR(64) PRIMARY KEY,
    activity_code VARCHAR(50) UNIQUE NOT NULL,
    activity_name VARCHAR(100) NOT NULL,
    activity_description TEXT,
    activity_category VARCHAR(50) NOT NULL DEFAULT 'general',
    severity_level ENUM('info', 'warning', 'critical') NOT NULL DEFAULT 'info',
    requires_audit BOOLEAN NOT NULL DEFAULT FALSE,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    updated_at DATETIME
);
```

**Key Fields:**
- `activity_code` - Unique identifier for activity type (e.g., 'user_creation', 'group_delete')
- `activity_category` - Groups activities by domain (authentication, user_management, etc.)
- `severity_level` - Indicates importance: info, warning, critical
- `requires_audit` - Flag indicating if this activity MUST be logged for compliance

##### **activity_logs**
Stores actual audit log entries.

```sql
CREATE TABLE activity_logs (
    id VARCHAR(64) PRIMARY KEY,
    user_id VARCHAR(64),                    -- Who performed the action
    activity_type VARCHAR(50) NOT NULL,     -- Activity code from catalog
    activity_catalog_id VARCHAR(64),        -- Link to catalog
    details TEXT,                           -- JSON or text details
    project_id VARCHAR(64),                 -- Project context
    user_group_id VARCHAR(64),              -- Group context
    target_user_id VARCHAR(64),             -- Target of action (if applicable)
    ip_address VARCHAR(45),                 -- Client IP
    user_agent TEXT,                        -- Browser/client info
    metadata JSON NULL,                     -- Additional structured data
    severity_level ENUM('info', 'warning', 'critical') NOT NULL DEFAULT 'info',
    created_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    INDEX idx_activity_catalog (activity_catalog_id),
    FOREIGN KEY (activity_catalog_id) REFERENCES activity_catalog(id)
);
```

##### **permission_audit_log**
Specialized audit trail for permission-related changes.

```sql
CREATE TABLE permission_audit_log (
    id VARCHAR(64) PRIMARY KEY,
    action_type VARCHAR(50) NOT NULL,
    project_id VARCHAR(64),
    target_user_id VARCHAR(64),
    user_group_id VARCHAR(64),
    permission_id VARCHAR(64),
    permission_group_id VARCHAR(64),
    performed_by VARCHAR(64),
    old_values JSON,                        -- State before change
    new_values JSON,                        -- State after change
    action_timestamp DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    performed_at DATETIME NOT NULL DEFAULT CURRENT_TIMESTAMP,
    ip_address VARCHAR(45),
    user_agent TEXT,
    table_name VARCHAR(100),
    record_id VARCHAR(64)
);
```

#### Stored Procedures

##### **sp_log_activity**
Primary procedure for logging activities.

```sql
CALL sp_log_activity(
    p_activity_log_id,      -- Generated UUID
    p_user_id,              -- User performing action
    p_activity_code,        -- Activity type
    p_details,              -- JSON or text details
    p_project_id,           -- Optional project context
    p_user_group_id,        -- Optional group context
    p_target_user_id,       -- Optional target user
    p_ip_address,           -- Client IP
    p_user_agent,           -- Browser info
    p_metadata              -- Additional JSON metadata
);
```

##### **sp_get_activity_logs**
Retrieve audit logs with filtering and pagination.

```sql
CALL sp_get_activity_logs(
    p_limit,                -- Max results
    p_offset,               -- Skip results
    p_user_id,              -- Filter by user
    p_project_id,           -- Filter by project
    p_activity_code,        -- Filter by activity type
    p_days                  -- Look back period
);
```

##### **sp_count_activity_logs**
Count matching audit logs.

##### **sp_get_activity_catalog**
Retrieve activity catalog entries by category.

### 2. Application Layer

#### ActivityLogger Class
Primary interface for audit logging (`src/Util/activity_logger.py`).

**Core Methods:**

```python
# Generic logging
ActivityLogger.log_activity(
    user_id: str,
    activity_type: str,
    details: Dict[str, Any] | str,
    project_id: Optional[str] = None,
    user_group_id: Optional[str] = None,
    target_user_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None
) -> bool

# Retrieval
ActivityLogger.get_recent_activity(
    limit: int = 50,
    offset: int = 0,
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    activity_type: Optional[str] = None,
    days: int = 30
) -> List[Dict[str, Any]]

ActivityLogger.count_activity_logs(...) -> int
ActivityLogger.get_activity_catalog(category: Optional[str] = None) -> List[Dict]
```

**Specialized Logging Methods:**

```python
# User Management
ActivityLogger.log_user_update(user_id, target_user_id, changes, **kwargs)
ActivityLogger.log_user_status_change(user_id, target_user_id, new_status, **kwargs)
ActivityLogger.log_user_type_changed(user_id, target_user_id, old_type, new_type, **kwargs)
ActivityLogger.log_user_password_reset(user_id, target_user_id, **kwargs)

# Project Management
ActivityLogger.log_project_creation(user_id, project_id, project_name, **kwargs)
ActivityLogger.log_project_update(user_id, project_id, changes, **kwargs)
ActivityLogger.log_project_delete(user_id, project_id, project_name, **kwargs)
ActivityLogger.log_project_archived(user_id, project_id, **kwargs)

# Group Management
ActivityLogger.log_group_creation(user_id, user_group_id, group_name, **kwargs)
ActivityLogger.log_group_update(user_id, user_group_id, changes, **kwargs)
ActivityLogger.log_group_delete(user_id, user_group_id, group_name, **kwargs)
ActivityLogger.log_user_group_assign(user_id, target_user_id, user_group_id, **kwargs)
ActivityLogger.log_user_group_remove(user_id, target_user_id, user_group_id, **kwargs)

# Permission Management
ActivityLogger.log_permission_grant(user_id, target_user_id, permission, project_id, **kwargs)
ActivityLogger.log_permission_revoke(user_id, target_user_id, permission, project_id, **kwargs)
ActivityLogger.log_role_removed(user_id, target_user_id, role, project_id, **kwargs)

# Bulk Operations
ActivityLogger.log_bulk_role_assignment(user_id, count, project_id, **kwargs)
ActivityLogger.log_bulk_group_assignment(user_id, count, user_group_id, **kwargs)
ActivityLogger.log_bulk_user_update(user_id, count, **kwargs)
ActivityLogger.log_bulk_user_delete(user_id, count, **kwargs)

# System & Admin
ActivityLogger.log_admin_action(user_id, action, details, project_id, target_user_id)
ActivityLogger.log_system_event(event, details, **kwargs)
```

#### ActivityLoggingMiddleware
Automatic capture of request context (`src/middleware/activity_logging.py`).

**Features:**
- Extracts IP address from request (supports X-Forwarded-For, X-Real-IP headers)
- Captures user agent string
- Sets context variables for use by all activity logging calls in the request
- Automatically cleans up context after request completion

**Usage:**
```python
from src.middleware.activity_logging import ActivityLoggingMiddleware

app = FastAPI()
app.add_middleware(ActivityLoggingMiddleware)
```

---

## Activity Categorization

### Categories and Severity Levels

| Category | Purpose | Default Severity | Audit Required |
|----------|---------|------------------|----------------|
| **authentication** | Login/logout/auth failures | info/warning | YES |
| **user_management** | User CRUD, status, type changes | info/critical | YES |
| **project_management** | Project CRUD, archiving, ownership | info/critical | YES |
| **project_members** | Adding/removing project members | info/warning | YES |
| **group_management** | Group CRUD, membership changes | info/critical | YES |
| **permission_management** | Permission/role grants and revocations | warning/critical | YES |
| **bulk_operations** | Bulk updates/deletions | warning/critical | YES |
| **admin** | General administrative actions | warning | YES |
| **system** | System events, config changes | info/critical | YES |
| **security** | Security alerts, suspicious activity | critical | YES |
| **api** | API access, integration events | info | NO |
| **integration** | External system syncs | info | NO |

---

## Audit Filtering Strategy

### What TO LOG (Required)

#### Root & Admin Actions (ALWAYS LOG)
- User creation, modification, deletion
- User type changes (promoting to admin/root)
- User status changes (activate/deactivate)
- Password resets initiated by admins
- Project creation, updates, deletion, archiving
- Project ownership transfers
- Group creation, updates, deletion
- User group assignments/removals
- Group project access grants/revocations
- Permission grants and revocations
- Role assignments and removals
- Permission group assignments
- Bulk operations (any mass changes)
- System configuration changes
- Administrative override actions

#### Security-Critical Actions (ALWAYS LOG)
- Login attempts (success and failure)
- Suspicious activity detection
- Security alerts
- Multiple failed login attempts
- Password reset requests
- Session creation/destruction (for root/admin only)

### What NOT TO LOG (Filtered Out)

#### Routine Consumer Operations
- Session validation checks (`/validate-session`)
- Permission verification lookups (`/check-permission`)
- Profile viewing (GET endpoints without modifications)
- Listing operations (browsing data)
- Search queries
- Analytics dashboard views
- Read-only API calls

#### High-Frequency Background Operations
- Automated health checks
- Internal system heartbeats
- Cache updates
- Session expiry cleanups
- Background maintenance tasks
- Performance monitoring queries

#### Non-Administrative Consumer Actions
- Viewing own profile
- Listing own projects
- Reading documentation
- Viewing permitted resources
- Basic navigation
- UI interactions without state changes

---

## Data Flow

### Logging Flow

```
┌─────────────────┐
│  HTTP Request   │
│  (User Action)  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│ ActivityLogging         │
│ Middleware              │
│ - Capture IP            │
│ - Capture User Agent    │
│ - Set Context Variables │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  Route Handler          │
│  (Business Logic)       │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  State Change Detected  │
│  (Create/Update/Delete) │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  ActivityLogger.log_*   │
│  - Merge context        │
│  - Validate activity    │
│  - Format details       │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  sp_log_activity()      │
│  - Lookup catalog       │
│  - Insert log entry     │
│  - Commit transaction   │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  activity_logs table    │
│  (Persistent Storage)   │
└─────────────────────────┘
```

### Retrieval Flow

```
┌─────────────────┐
│  Request Logs   │
│  (Admin Panel)  │
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│  ActivityLogger.get_*   │
│  - Apply filters        │
│  - Set pagination       │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  sp_get_activity_logs() │
│  - Query with JOINs     │
│  - Enrich with context  │
│  - Return results       │
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  Format Response        │
│  - User names           │
│  - Project names        │
│  - Group names          │
│  - Activity descriptions│
└────────┬────────────────┘
         │
         ▼
┌─────────────────────────┐
│  Return JSON Response   │
└─────────────────────────┘
```

---

## Context Management

### Request Context Variables

The system uses Python `contextvars` to automatically propagate request context:

```python
# Set by middleware
_request_context: ContextVar[Dict[str, Any]] = ContextVar('request_context', default={})

# Structure:
{
    "ip_address": "192.168.1.100",
    "user_agent": "Mozilla/5.0 ..."
}
```

### Automatic Context Injection

All `ActivityLogger.log_*` methods automatically merge request context:

```python
ActivityLogger.log_project_creation(
    user_id="usr-123",
    project_id="prj-456",
    project_name="New Project"
)
# Automatically includes ip_address and user_agent from request context
```

---

## Performance Considerations

### Async Logging
- Logs written synchronously within transaction
- Consider async queue for very high-volume systems
- Current implementation: direct database writes (acceptable for moderate load)

### Indexing Strategy
```sql
-- Indexes on activity_logs
INDEX idx_activity_catalog (activity_catalog_id)
INDEX idx_user_activity (user_id, created_at)
INDEX idx_project_activity (project_id, created_at)
INDEX idx_activity_type (activity_type, created_at)
INDEX idx_severity (severity_level, created_at)
INDEX idx_target_user (target_user_id, created_at)
```

### Query Optimization
- Use stored procedures for efficient queries
- Limit date ranges for large log tables
- Implement log rotation/archival for long-term storage
- Consider partitioning by date for very large datasets

### Filtering at Source
- Don't log high-frequency operations
- Filter before database write (not after)
- Use `requires_audit` flag in catalog to enable/disable activities

---

## Security & Compliance

### Data Retention
- Keep audit logs for compliance period (typically 1-7 years)
- Implement automated archival to cold storage
- Never delete security-critical logs (login attempts, access changes)

### Data Protection
- Audit logs contain PII (IP addresses, user IDs)
- Apply appropriate access controls
- Mask sensitive data in details field when necessary
- Comply with GDPR/CCPA retention policies

### Integrity
- Logs are append-only (no updates/deletes)
- Consider cryptographic signing for tamper-evidence
- Regular backups of audit log tables
- Monitor for gaps in log sequence

### Access Control
- Only root and designated admin users can view full audit logs
- Implement role-based access to log viewing
- Log all access to audit logs themselves (meta-logging)

---

## Monitoring & Alerting

### Critical Events to Monitor
- Multiple failed login attempts (brute force detection)
- Unusual bulk operations
- Permission escalations
- Root/admin user creation
- System configuration changes
- Suspicious activity patterns

### Alert Thresholds
```sql
-- Example: Failed login threshold
SELECT COUNT(*) as failed_attempts
FROM activity_logs
WHERE activity_type = 'user_login_failed'
  AND user_id = ?
  AND created_at > DATE_SUB(NOW(), INTERVAL 15 MINUTE);
-- Alert if > 5 attempts
```

### Log Analysis
- Regular reviews of critical severity logs
- Anomaly detection (unusual activity patterns)
- User behavior analytics
- Compliance reporting

---

## Extension Points

### Custom Activity Types
Add new activities to catalog:

```sql
INSERT INTO activity_catalog (
    id, activity_code, activity_name, activity_description,
    activity_category, severity_level, requires_audit, is_active
) VALUES (
    'act-cat-041', 'custom_action', 'Custom Action',
    'Description of custom action', 'custom_category',
    'warning', TRUE, TRUE
);
```

### Custom Log Handlers
Implement additional log destinations:

```python
class ExternalAuditLogger:
    def log(self, activity_log: Dict[str, Any]):
        # Send to SIEM, CloudWatch, Splunk, etc.
        pass
```

### Webhooks & Notifications
Trigger external actions on specific activities:

```python
@ActivityLogger.on_activity('user_type_changed')
def notify_security_team(log_entry):
    send_email_alert(log_entry)
```

---

## Best Practices

1. **Always log state changes** - Any CREATE, UPDATE, DELETE operation
2. **Never log password values** - Only log "password changed" event
3. **Include context** - Who, what, when, where, why
4. **Use structured details** - JSON format for complex data
5. **Set appropriate severity** - Critical for security, warning for admin, info for routine
6. **Filter aggressively** - Don't log read operations or validations
7. **Monitor log volume** - Alert on unusual spikes
8. **Test logging** - Verify logs are written correctly
9. **Document custom activities** - Keep catalog up to date
10. **Review regularly** - Periodic audit of audit logs

---

## Troubleshooting

### Logs Not Appearing
1. Check activity is in catalog and is_active = TRUE
2. Verify stored procedure `sp_log_activity` exists
3. Check database connection and permissions
4. Review application logs for exceptions
5. Verify middleware is installed

### Missing Context (IP/User Agent)
1. Confirm `ActivityLoggingMiddleware` is installed
2. Check middleware order (should be early in chain)
3. Verify proxy headers if behind load balancer

### Performance Issues
1. Check index usage with EXPLAIN
2. Implement date-based partitioning
3. Archive old logs to separate table
4. Consider async logging queue
5. Reduce log retention period

---

**Last Updated:** October 26, 2025  
**Version:** 1.0  
**System:** Magic Auth Multi-Project Authentication
