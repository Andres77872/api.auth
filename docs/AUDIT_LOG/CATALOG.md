# Activity Catalog - Complete Reference

**Magic Auth System - Audit Log Activity Types**

---

## Overview

This document provides a complete catalog of all auditable activities in the Magic Auth system. Each activity type is defined with its code, category, severity level, and audit requirements.

### Catalog Legend

- **Activity Code** - Unique identifier used in logging calls
- **Category** - Functional grouping
- **Severity** - info | warning | critical
- **Audit Required** - Must be logged (TRUE) or optional (FALSE)
- **Logged For** - User types whose actions are logged

---

## Authentication Activities

### user_login
- **Code:** `user_login`
- **Category:** authentication
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** root, admin, consumer
- **Description:** User successfully logged into the system
- **Details Format:**
  ```json
  {
    "action": "login",
    "timestamp": "2025-10-26T14:30:00Z",
    "login_method": "username_password"
  }
  ```
- **When to Log:** Every successful authentication
- **Exclude:** Session validation checks (already authenticated)

### user_logout
- **Code:** `user_logout`
- **Category:** authentication
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** root, admin (optional for consumer)
- **Description:** User logged out of the system
- **Details Format:**
  ```json
  {
    "action": "logout",
    "timestamp": "2025-10-26T14:30:00Z",
    "session_duration_minutes": 45
  }
  ```
- **When to Log:** Explicit logout actions
- **Exclude:** Automatic session expiry (system maintenance)

### user_login_failed
- **Code:** `user_login_failed`
- **Category:** authentication
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** ALL (any failed attempt)
- **Description:** Failed login attempt
- **Details Format:**
  ```json
  {
    "reason": "invalid_password",
    "attempted_username": "john.doe",
    "timestamp": "2025-10-26T14:30:00Z",
    "failure_count": 3
  }
  ```
- **When to Log:** Every failed authentication attempt
- **Security:** Monitor for brute force attacks

### user_password_reset
- **Code:** `user_password_reset`
- **Category:** authentication
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin (initiator or target)
- **Description:** User password was reset
- **Details Format:**
  ```json
  {
    "reset_type": "admin_initiated",
    "temporary_password": false,
    "forced_change": true
  }
  ```
- **When to Log:** Password reset initiated or completed
- **Security:** Never log actual password values

---

## User Management Activities

### user_registration
- **Code:** `user_registration`
- **Category:** user_management
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** root, admin (creator)
- **Description:** New user account created
- **Details Format:**
  ```json
  {
    "action": "registration",
    "username": "new.user",
    "user_type": "consumer",
    "email": "user@example.com",
    "created_by_type": "admin"
  }
  ```
- **When to Log:** User account creation by root/admin
- **Exclude:** Self-registration (if enabled)

### user_update
- **Code:** `user_update`
- **Category:** user_management
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** root, admin (modifier)
- **Description:** User account information updated
- **Details Format:**
  ```json
  {
    "changes": {
      "email": {"old": "old@example.com", "new": "new@example.com"},
      "username": {"old": "oldname", "new": "newname"}
    },
    "updated_fields": ["email", "username"]
  }
  ```
- **When to Log:** Profile updates by admin/root (not user's own profile updates)
- **Exclude:** Consumer updating their own profile (optional)

### user_status_change
- **Code:** `user_status_change`
- **Category:** user_management
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin (modifier)
- **Description:** User account status changed (activated/deactivated)
- **Details Format:**
  ```json
  {
    "old_status": "active",
    "new_status": "inactive",
    "reason": "policy_violation"
  }
  ```
- **When to Log:** Always when status changes
- **Security:** Critical for access control auditing

### user_type_changed
- **Code:** `user_type_changed`
- **Category:** user_management
- **Severity:** CRITICAL
- **Audit Required:** YES
- **Logged For:** root (only root can change types)
- **Description:** User type modified (root/admin/consumer)
- **Details Format:**
  ```json
  {
    "old_type": "admin",
    "new_type": "root",
    "reason": "promotion"
  }
  ```
- **When to Log:** ALWAYS - highest security impact
- **Security:** Monitor for unauthorized privilege escalation

### user_deleted
- **Code:** `user_deleted`
- **Category:** user_management
- **Severity:** CRITICAL
- **Audit Required:** YES
- **Logged For:** root, admin (deleter)
- **Description:** User account deleted
- **Details Format:**
  ```json
  {
    "deleted_username": "removed.user",
    "deleted_user_type": "consumer",
    "reason": "account_closure",
    "soft_delete": false
  }
  ```
- **When to Log:** ALWAYS - irreversible action
- **Security:** Requires strong audit trail

---

## Project Management Activities

### project_creation
- **Code:** `project_creation`
- **Category:** project_management
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** root, admin (creator)
- **Description:** New project created
- **Details Format:**
  ```json
  {
    "project_name": "New Application",
    "project_description": "Customer portal",
    "owner_id": "usr-123",
    "initial_status": "active"
  }
  ```
- **When to Log:** Every project creation
- **Exclude:** N/A (always log)

### project_update
- **Code:** `project_update`
- **Category:** project_management
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** root, admin (modifier)
- **Description:** Project information updated
- **Details Format:**
  ```json
  {
    "changes": {
      "project_name": {"old": "Old Name", "new": "New Name"},
      "project_description": {"old": "...", "new": "..."}
    },
    "updated_fields": ["project_name", "project_description"]
  }
  ```
- **When to Log:** Significant project attribute changes
- **Exclude:** Minor metadata updates (optional)

### project_delete
- **Code:** `project_delete`
- **Category:** project_management
- **Severity:** CRITICAL
- **Audit Required:** YES
- **Logged For:** root only
- **Description:** Project deleted
- **Details Format:**
  ```json
  {
    "project_name": "Deleted Project",
    "deletion_reason": "project_end",
    "member_count": 45,
    "data_archived": true
  }
  ```
- **When to Log:** ALWAYS - destructive action
- **Security:** Requires root approval

### project_archived
- **Code:** `project_archived`
- **Category:** project_management
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin
- **Description:** Project archived
- **Details Format:**
  ```json
  {
    "project_name": "Old Project",
    "archive_reason": "inactive",
    "archive_date": "2025-10-26"
  }
  ```
- **When to Log:** Project archival
- **Exclude:** N/A

### project_unarchived
- **Code:** `project_unarchived`
- **Category:** project_management
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** root, admin
- **Description:** Project unarchived (restored)
- **Details Format:**
  ```json
  {
    "project_name": "Restored Project",
    "restore_reason": "reactivation"
  }
  ```
- **When to Log:** Project restoration
- **Exclude:** N/A

### project_ownership_transferred
- **Code:** `project_ownership_transferred`
- **Category:** project_management
- **Severity:** CRITICAL
- **Audit Required:** YES
- **Logged For:** root, admin
- **Description:** Project ownership transferred to another user
- **Details Format:**
  ```json
  {
    "project_name": "Transferred Project",
    "old_owner_id": "usr-123",
    "new_owner_id": "usr-456",
    "transfer_reason": "role_change"
  }
  ```
- **When to Log:** ALWAYS - significant control change
- **Security:** Monitor for unauthorized transfers

---

## Project Member Activities

### project_member_add
- **Code:** `project_member_add`
- **Category:** project_members
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** root, admin (assigner)
- **Description:** User added to project
- **Details Format:**
  ```json
  {
    "added_user_id": "usr-789",
    "added_user_type": "consumer",
    "access_granted_via": "user_group_assignment"
  }
  ```
- **When to Log:** User granted project access
- **Exclude:** Automatic group-based access (log group assignment instead)

### project_member_remove
- **Code:** `project_member_remove`
- **Category:** project_members
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin (remover)
- **Description:** User removed from project
- **Details Format:**
  ```json
  {
    "removed_user_id": "usr-789",
    "removal_reason": "role_ended",
    "removed_via": "group_removal"
  }
  ```
- **When to Log:** User access revoked
- **Exclude:** N/A

### project_member_removed
- **Code:** `project_member_removed`
- **Category:** project_members
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin (remover)
- **Description:** Alternative code for member removal
- **Details Format:** Same as `project_member_remove`
- **When to Log:** User access revoked (passive voice)
- **Note:** Duplicate of project_member_remove (consider deprecating)

---

## Group Management Activities

### group_creation
- **Code:** `group_creation`
- **Category:** group_management
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** root, admin (creator)
- **Description:** New user group created
- **Details Format:**
  ```json
  {
    "group_name": "Engineering Team",
    "group_description": "Software engineers",
    "parent_group_id": null,
    "group_level": 0
  }
  ```
- **When to Log:** Every group creation
- **Exclude:** N/A

### group_update
- **Code:** `group_update`
- **Category:** group_management
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** root, admin (modifier)
- **Description:** User group information updated
- **Details Format:**
  ```json
  {
    "changes": {
      "group_name": {"old": "Old Name", "new": "New Name"},
      "group_description": {"old": "...", "new": "..."}
    },
    "updated_fields": ["group_name"]
  }
  ```
- **When to Log:** Group attribute changes
- **Exclude:** N/A

### group_delete
- **Code:** `group_delete`
- **Category:** group_management
- **Severity:** CRITICAL
- **Audit Required:** YES
- **Logged For:** root, admin (deleter)
- **Description:** User group deleted
- **Details Format:**
  ```json
  {
    "group_name": "Deleted Group",
    "member_count": 12,
    "project_access_count": 3,
    "deletion_reason": "restructuring"
  }
  ```
- **When to Log:** ALWAYS - affects multiple users
- **Security:** Monitor impact on access control

### user_group_assign
- **Code:** `user_group_assign`
- **Category:** group_management
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** root, admin (assigner)
- **Description:** User assigned to a group
- **Details Format:**
  ```json
  {
    "assigned_user_id": "usr-123",
    "group_id": "grp-456",
    "group_name": "Engineering Team",
    "assignment_reason": "role_change"
  }
  ```
- **When to Log:** User added to group
- **Exclude:** N/A

### user_group_remove
- **Code:** `user_group_remove`
- **Category:** group_management
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin (remover)
- **Description:** User removed from a group
- **Details Format:**
  ```json
  {
    "removed_user_id": "usr-123",
    "group_id": "grp-456",
    "group_name": "Engineering Team",
    "removal_reason": "role_ended"
  }
  ```
- **When to Log:** User removed from group
- **Exclude:** N/A

---

## Permission Management Activities

### permission_grant
- **Code:** `permission_grant`
- **Category:** permission_management
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin (granter)
- **Description:** Permission granted to user or group
- **Details Format:**
  ```json
  {
    "permission": "project.delete",
    "granted_to_type": "user",
    "granted_to_id": "usr-123",
    "scope": "project",
    "scope_id": "prj-456"
  }
  ```
- **When to Log:** ALWAYS - security critical
- **Security:** Monitor for privilege escalation

### permission_revoke
- **Code:** `permission_revoke`
- **Category:** permission_management
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin (revoker)
- **Description:** Permission revoked from user or group
- **Details Format:**
  ```json
  {
    "permission": "project.delete",
    "revoked_from_type": "user",
    "revoked_from_id": "usr-123",
    "revocation_reason": "role_change"
  }
  ```
- **When to Log:** ALWAYS - security critical
- **Security:** Part of access control audit trail

### role_assigned
- **Code:** `role_assigned`
- **Category:** permission_management
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** root, admin (assigner)
- **Description:** Role assigned to user or group
- **Details Format:**
  ```json
  {
    "role_name": "Project Manager",
    "role_id": "rol-789",
    "assigned_to_type": "user",
    "assigned_to_id": "usr-123"
  }
  ```
- **When to Log:** Role assignments
- **Exclude:** Default role assignments on user creation (optional)

### role_removed
- **Code:** `role_removed`
- **Category:** permission_management
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin (remover)
- **Description:** Role removed from user or group
- **Details Format:**
  ```json
  {
    "role_name": "Project Manager",
    "role_id": "rol-789",
    "removed_from_type": "user",
    "removed_from_id": "usr-123",
    "removal_reason": "role_ended"
  }
  ```
- **When to Log:** Role removals
- **Exclude:** N/A

---

## Bulk Operations

### bulk_role_assignment
- **Code:** `bulk_role_assignment`
- **Category:** bulk_operations
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin (operator)
- **Description:** Roles assigned to multiple users
- **Details Format:**
  ```json
  {
    "count": 25,
    "role_name": "Viewer",
    "target_users": ["usr-1", "usr-2", "..."],
    "operation_duration_seconds": 5.3
  }
  ```
- **When to Log:** ALWAYS - mass changes
- **Security:** High-impact operation

### bulk_group_assignment
- **Code:** `bulk_group_assignment`
- **Category:** bulk_operations
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin (operator)
- **Description:** Groups assigned to multiple users
- **Details Format:**
  ```json
  {
    "count": 30,
    "group_name": "Engineering",
    "target_users": ["usr-1", "usr-2", "..."]
  }
  ```
- **When to Log:** ALWAYS - mass changes
- **Security:** High-impact operation

### bulk_user_update
- **Code:** `bulk_user_update`
- **Category:** bulk_operations
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin (operator)
- **Description:** Multiple users updated
- **Details Format:**
  ```json
  {
    "count": 50,
    "updated_fields": ["status", "email_domain"],
    "update_criteria": "department = 'Sales'"
  }
  ```
- **When to Log:** ALWAYS - mass changes
- **Security:** Monitor for unintended changes

### bulk_user_delete
- **Code:** `bulk_user_delete`
- **Category:** bulk_operations
- **Severity:** CRITICAL
- **Audit Required:** YES
- **Logged For:** root only
- **Description:** Multiple users deleted
- **Details Format:**
  ```json
  {
    "count": 15,
    "deletion_criteria": "inactive > 365 days",
    "soft_delete": true
  }
  ```
- **When to Log:** ALWAYS - destructive operation
- **Security:** Requires strong approval

---

## Administrative Actions

### admin_action
- **Code:** `admin_action`
- **Category:** admin
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** root, admin (actor)
- **Description:** General administrative action performed
- **Details Format:**
  ```json
  {
    "action": "system_configuration_change",
    "details": "Updated session timeout to 60 minutes",
    "affected_components": ["authentication"]
  }
  ```
- **When to Log:** Admin actions not covered by specific codes
- **Use:** Catch-all for administrative operations

---

## System Events

### system_event
- **Code:** `system_event`
- **Category:** system
- **Severity:** info
- **Audit Required:** YES
- **Logged For:** system (no user)
- **Description:** System-level event occurred
- **Details Format:**
  ```json
  {
    "event": "database_backup_completed",
    "details": "Backup size: 1.2GB",
    "duration_seconds": 45
  }
  ```
- **When to Log:** Significant system events
- **Exclude:** Routine health checks

### system_config_change
- **Code:** `system_config_change`
- **Category:** system
- **Severity:** CRITICAL
- **Audit Required:** YES
- **Logged For:** root only
- **Description:** System configuration modified
- **Details Format:**
  ```json
  {
    "config_key": "max_login_attempts",
    "old_value": "5",
    "new_value": "3",
    "config_scope": "global"
  }
  ```
- **When to Log:** ALWAYS - affects entire system
- **Security:** Monitor for unauthorized changes

---

## API & Integration Activities

### api_access
- **Code:** `api_access`
- **Category:** api
- **Severity:** info
- **Audit Required:** NO
- **Logged For:** external systems
- **Description:** API endpoint accessed
- **Details Format:**
  ```json
  {
    "endpoint": "/api/v1/users",
    "method": "GET",
    "response_status": 200,
    "response_time_ms": 45
  }
  ```
- **When to Log:** Optional - only for API analytics
- **Exclude:** HIGH-FREQUENCY - not for audit

### api_error
- **Code:** `api_error`
- **Category:** api
- **Severity:** warning
- **Audit Required:** YES
- **Logged For:** system
- **Description:** API error occurred
- **Details Format:**
  ```json
  {
    "endpoint": "/api/v1/users",
    "error_code": "VALIDATION_ERROR",
    "error_message": "Invalid user hash format",
    "request_id": "req-123"
  }
  ```
- **When to Log:** API errors requiring investigation
- **Exclude:** Expected errors (404s, validation failures)

### integration_sync
- **Code:** `integration_sync`
- **Category:** integration
- **Severity:** info
- **Audit Required:** NO
- **Logged For:** system
- **Description:** External integration synchronized
- **Details Format:**
  ```json
  {
    "integration": "ldap_sync",
    "records_synced": 150,
    "duration_seconds": 30
  }
  ```
- **When to Log:** Optional - integration monitoring
- **Exclude:** HIGH-FREQUENCY - not for audit

---

## Security Activities

### security_alert
- **Code:** `security_alert`
- **Category:** security
- **Severity:** CRITICAL
- **Audit Required:** YES
- **Logged For:** system
- **Description:** Security-related alert triggered
- **Details Format:**
  ```json
  {
    "alert_type": "brute_force_detected",
    "target_user": "admin.user",
    "source_ip": "192.168.1.100",
    "attempt_count": 10,
    "time_window_minutes": 5
  }
  ```
- **When to Log:** ALWAYS - security incident
- **Security:** Immediate investigation required

### suspicious_activity
- **Code:** `suspicious_activity`
- **Category:** security
- **Severity:** CRITICAL
- **Audit Required:** YES
- **Logged For:** system (auto-detected)
- **Description:** Suspicious activity detected
- **Details Format:**
  ```json
  {
    "activity_type": "unusual_access_pattern",
    "user_id": "usr-123",
    "anomaly_score": 0.85,
    "details": "Access from new location + unusual time"
  }
  ```
- **When to Log:** ALWAYS - potential security breach
- **Security:** Investigation required

### session_expired
- **Code:** `session_expired`
- **Category:** security
- **Severity:** info
- **Audit Required:** NO
- **Logged For:** system
- **Description:** User session expired
- **Details Format:**
  ```json
  {
    "user_id": "usr-123",
    "session_duration_minutes": 120,
    "expiry_reason": "timeout"
  }
  ```
- **When to Log:** Optional - session management analytics
- **Exclude:** HIGH-FREQUENCY - routine operation

---

## Activity Summary Table

| Category | Activities Count | Critical | Warning | Info | Audit Required |
|----------|------------------|----------|---------|------|----------------|
| authentication | 4 | 0 | 2 | 2 | 4 |
| user_management | 5 | 2 | 1 | 2 | 5 |
| project_management | 6 | 2 | 1 | 3 | 6 |
| project_members | 3 | 0 | 2 | 1 | 3 |
| group_management | 5 | 1 | 1 | 3 | 5 |
| permission_management | 4 | 0 | 3 | 1 | 4 |
| bulk_operations | 4 | 1 | 3 | 0 | 4 |
| admin | 1 | 0 | 1 | 0 | 1 |
| system | 2 | 1 | 0 | 1 | 2 |
| api | 2 | 0 | 1 | 1 | 1 |
| integration | 1 | 0 | 0 | 1 | 0 |
| security | 3 | 2 | 0 | 1 | 2 |
| **TOTAL** | **40** | **9** | **15** | **16** | **37** |

---

## Usage in Code

### Example: Log Project Creation
```python
from src.Util.activity_logger import ActivityLogger

ActivityLogger.log_project_creation(
    user_id="usr-123",
    project_id="prj-456",
    project_name="New Application"
)
# IP and user agent automatically included from middleware
```

### Example: Log User Type Change
```python
ActivityLogger.log_user_type_changed(
    user_id="usr-root",              # Who made the change
    target_user_id="usr-789",         # Who was changed
    old_type="admin",
    new_type="root"
)
```

### Example: Generic Activity Log
```python
ActivityLogger.log_activity(
    user_id="usr-123",
    activity_type="custom_action",   # Must be in catalog
    details={"key": "value"},
    project_id="prj-456",
    metadata={"additional": "info"}
)
```

---

## Adding Custom Activities

### Step 1: Add to Database Catalog
```sql
INSERT INTO activity_catalog (
    id, activity_code, activity_name, activity_description,
    activity_category, severity_level, requires_audit, is_active
) VALUES (
    'act-cat-041',
    'custom_operation',
    'Custom Operation',
    'Description of your custom activity',
    'custom_category',
    'warning',
    TRUE,
    TRUE
);
```

### Step 2: Add to ActivityType Enum (Optional)
```python
# In src/Util/activity_logger.py
class ActivityType(Enum):
    # ... existing types ...
    CUSTOM_OPERATION = "custom_operation"
```

### Step 3: Create Convenience Method (Optional)
```python
# In ActivityLogger class
@staticmethod
def log_custom_operation(user_id: str, details: Dict, **kwargs) -> bool:
    return ActivityLogger.log_activity(
        user_id=user_id,
        activity_type=ActivityType.CUSTOM_OPERATION.value,
        details=details,
        **ActivityLogger._get_request_context(),
        **kwargs
    )
```

---

**Last Updated:** October 26, 2025  
**Version:** 1.0  
**Total Activities:** 40  
**System:** Magic Auth Multi-Project Authentication
