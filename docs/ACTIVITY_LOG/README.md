# Activity Logging System Documentation

## Overview

The Activity Logging System is a comprehensive audit trail mechanism that automatically tracks **user actions** (CRUD operations) across the authentication system. This is distinct from API audit logs, which track HTTP requests/responses.

### Key Differences

| Feature | Activity Logs | API Audit Logs |
|---------|--------------|----------------|
| **Purpose** | Track user business actions | Track API requests/responses |
| **Scope** | CRUD operations on entities | HTTP endpoint calls |
| **Trigger** | Database triggers | Middleware |
| **Storage** | `activity_logs` table | `api_audit_log` table |
| **Focus** | User behavior & data changes | System performance & API usage |

## System Architecture

### Components

1. **Activity Catalog** (`activity_catalog` table)
   - Centralized registry of all trackable activity types
   - Defines activity metadata (name, description, category, severity)
   - Enables/disables specific activity tracking

2. **Activity Logs** (`activity_logs` table)
   - Stores actual activity log entries
   - Links to activity catalog for enriched data
   - Captures context: user, project, target entity, metadata

3. **Permission Audit Log** (`permission_audit_log` table)
   - Specialized audit trail for permission changes
   - Tracks old/new values for permission modifications
   - Higher detail level for compliance requirements

4. **Database Triggers** (Automatic logging)
   - Triggers on all major tables for INSERT, UPDATE, DELETE
   - Automatically log activities without application code
   - Capture data changes in real-time

5. **Stored Procedures** (Query & Analysis)
   - `sp_log_activity`: Manual activity logging
   - `sp_get_activity_logs`: Query with filters and pagination
   - `sp_get_activity_stats`: Analytics and reporting
   - `sp_get_user_activity_summary`: Per-user activity summary

## Implementation

### Automatic Logging via Triggers

The system uses MySQL triggers to automatically log activities when data changes occur:

#### Core Entity Triggers (File: `01_activity_logging_triggers.sql`)
- **Users**: creation, updates (type/status/password changes), deletion
- **Projects**: creation, updates (archive/ownership changes), deletion
- **User Groups**: creation, updates, deletion
- **User Group Members**: assignments, removals
- **User Group Projects**: access grants, revocations

#### Permission Entity Triggers (File: `02_permission_activity_triggers.sql`)
- **Roles**: creation, updates, deletion
- **Permission Groups**: creation, updates, deletion
- **Permissions**: creation, updates, deletion
- **Role-Permission Links**: assignments, revocations
- **User-Permission Links**: direct assignments, revocations
- **Sessions**: creation, logout tracking

### Manual Logging

Use the stored procedure for custom activities:

```sql
CALL sp_log_activity(
    p_activity_log_id VARCHAR(64),      -- Unique log ID
    p_user_id VARCHAR(64),               -- User performing action
    p_activity_code VARCHAR(50),         -- Activity code from catalog
    p_details TEXT,                      -- Human-readable description
    p_project_id VARCHAR(64),            -- Related project (optional)
    p_user_group_id VARCHAR(64),         -- Related group (optional)
    p_target_user_id VARCHAR(64),        -- Target user (optional)
    p_ip_address VARCHAR(45),            -- Client IP (optional)
    p_user_agent TEXT,                   -- User agent (optional)
    p_metadata JSON                      -- Additional context (optional)
);
```

## Activity Categories

The system organizes activities into categories:

| Category | Description | Example Activities |
|----------|-------------|-------------------|
| **authentication** | Login/logout events | user_login, user_logout, session_created |
| **user_management** | User CRUD operations | user_registration, user_update, user_deleted |
| **project_management** | Project CRUD operations | project_creation, project_archived, project_delete |
| **project_members** | Project membership changes | project_member_add, project_member_remove |
| **group_management** | User group operations | group_creation, group_update, user_group_assign |
| **permission_management** | Permission/role changes | permission_grant, role_assigned, permission_revoke |
| **bulk_operations** | Batch operations | bulk_role_assignment, bulk_user_delete |
| **admin** | Administrative actions | admin_action |
| **system** | System-level events | system_event |
| **security** | Security-related events | security_alert, user_login_failed |

## Severity Levels

Each activity has a severity level:

- **info**: Normal operations (e.g., user login, profile update)
- **warning**: Operations requiring attention (e.g., permission changes, user deactivation)
- **critical**: High-impact operations (e.g., user deletion, role changes, bulk operations)

## Querying Activity Logs

### Get Recent Activities

```sql
CALL sp_get_activity_logs(
    p_limit INT,              -- Max results (e.g., 50)
    p_offset INT,             -- Pagination offset
    p_user_id VARCHAR(64),    -- Filter by user (NULL for all)
    p_project_id VARCHAR(64), -- Filter by project (NULL for all)
    p_activity_code VARCHAR(50), -- Filter by activity type (NULL for all)
    p_days INT                -- Look back N days
);
```

### Get Activity Statistics

```sql
CALL sp_get_activity_stats(
    p_project_id VARCHAR(64), -- Project filter (NULL for all)
    p_days INT                -- Time window in days
);
```

### Get User Activity Summary

```sql
CALL sp_get_user_activity_summary(
    p_user_id VARCHAR(64),    -- Target user ID
    p_days INT                -- Look back N days
);
```

### Get Security Events

```sql
CALL sp_get_recent_security_events(
    p_hours INT,              -- Look back N hours
    p_limit INT               -- Max results
);
```

## Data Retention

### Cleanup Policy

Use the cleanup procedure to maintain log size:

```sql
CALL sp_cleanup_old_activity_logs(
    p_retention_days INT,     -- Delete logs older than N days
    p_dry_run BOOLEAN         -- TRUE to preview, FALSE to execute
);
```

**Default Retention Policy:**
- **Info logs**: 90 days
- **Warning logs**: 180 days (6 months)
- **Critical logs**: 365 days (1 year) or permanent

## Integration with Application

### Python/FastAPI Example

```python
from src.Util.activity_logger import ActivityLogger

# Log a custom activity
await ActivityLogger.log_activity(
    user_id="user-123",
    activity_code="project_member_add",
    details=f"User {target_user.username} added to project {project.name}",
    project_id=project.id,
    target_user_id=target_user.id,
    metadata={
        "role": "developer",
        "permissions": ["read", "write"]
    }
)
```

### Trigger Context Variables

Triggers automatically capture:
- User performing action (`created_by`, `assigned_by`, etc.)
- Target entities (user, project, group)
- Old and new values (for updates)
- Timestamps

## Use Cases

### Compliance & Auditing
- Track who modified user permissions
- Audit trail for regulatory compliance (SOC 2, GDPR, etc.)
- Generate compliance reports

### Security Monitoring
- Detect unusual user behavior patterns
- Monitor privilege escalations
- Track failed login attempts

### Operations & Support
- Debug user-reported issues
- Track project lifecycle
- Analyze user engagement

### Analytics
- User activity heatmaps
- Most common operations
- Peak activity times

## Security Considerations

1. **Sensitive Data**: Triggers filter sensitive fields (passwords, tokens) from metadata
2. **Immutable Logs**: Activity logs should never be modified, only inserted
3. **Access Control**: Restrict access to activity logs to admin users only
4. **Retention**: Implement automatic cleanup for old info-level logs

## Troubleshooting

### Triggers Not Firing

Check if triggers are enabled:
```sql
SHOW TRIGGERS FROM magic_auth LIKE 'trg_after_%';
```

### Missing Activity Catalog Entries

Verify activity codes exist:
```sql
SELECT * FROM activity_catalog WHERE activity_code = 'your_code';
```

### Performance Issues

Add indexes if querying is slow:
```sql
-- Already created, but verify:
SHOW INDEX FROM activity_logs;
```

## Future Enhancements

- [ ] Real-time activity streaming via WebSockets
- [ ] Activity log search with full-text search
- [ ] Automated anomaly detection
- [ ] Activity log export to external systems (SIEM, Splunk)
- [ ] Activity rollback/undo functionality
- [ ] User activity dashboards in UI

## Related Documentation

- [Activity Events Catalog](./ACTIVITY_EVENTS_CATALOG.md) - Complete list of activity events
- [Implementation Guide](./IMPLEMENTATION_GUIDE.md) - Step-by-step setup
- [API Audit Logs](../AUDIT_LOG/README.md) - HTTP request/response logging
- [Database Schema](../../schemas/tables/08_activity_logging_tables.sql) - Table definitions
- [Stored Procedures](../../schemas/stored_procedures/11_activity_logging.sql) - SP documentation
