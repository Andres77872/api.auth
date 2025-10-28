# CRUD Operations to Activity Events Mapping

This document maps all database CRUD operations to their corresponding activity log events. It serves as a reference for understanding what gets logged automatically (via triggers) and what requires manual logging.

## Legend

- 🤖 **Automatic** - Logged via database trigger
- 👋 **Manual** - Requires explicit logging in application code
- ⚠️ **Hybrid** - Trigger logs basic info, but additional context should be added manually

---

## Users Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** user | `user_registration` | 🤖 Automatic | `trg_after_user_insert` | Captures user_hash, username, user_type |
| **UPDATE** user (type changed) | `user_type_changed` | 🤖 Automatic | `trg_after_user_update` | Critical severity, captures old/new type |
| **UPDATE** user (status changed) | `user_status_change` | 🤖 Automatic | `trg_after_user_update` | Captures active/inactive change |
| **UPDATE** user (password changed) | `user_password_reset` | 🤖 Automatic | `trg_after_user_update` | Warning severity |
| **UPDATE** user (general) | `user_update` | 🤖 Automatic | `trg_after_user_update` | For profile updates |
| **DELETE** user | `user_deleted` | 🤖 Automatic | `trg_after_user_delete` | Critical severity, captures snapshot |

---

## Projects Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** project | `project_creation` | 🤖 Automatic | `trg_after_project_insert` | Captures project_hash, name, owner |
| **UPDATE** project (archived) | `project_archived` | 🤖 Automatic | `trg_after_project_update` | Warning severity |
| **UPDATE** project (unarchived) | `project_unarchived` | 🤖 Automatic | `trg_after_project_update` | Info severity |
| **UPDATE** project (owner changed) | `project_ownership_transferred` | 🤖 Automatic | `trg_after_project_update` | Critical severity |
| **UPDATE** project (general) | `project_update` | 🤖 Automatic | `trg_after_project_update` | For name/description updates |
| **DELETE** project | `project_delete` | 🤖 Automatic | `trg_after_project_delete` | Critical severity |

---

## User Groups Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** user_group | `group_creation` | 🤖 Automatic | `trg_after_user_group_insert` | Captures group_hash, name, level |
| **UPDATE** user_group | `group_update` | 🤖 Automatic | `trg_after_user_group_update` | Captures old/new values |
| **DELETE** user_group | `group_delete` | 🤖 Automatic | `trg_after_user_group_delete` | Critical severity |

---

## User Group Members Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** member assignment | `user_group_assign` | 🤖 Automatic | `trg_after_ugm_insert` | Links user to group |
| **DELETE** member assignment | `user_group_remove` | 🤖 Automatic | `trg_after_ugm_delete` | Warning severity |

---

## User Group Projects Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** group-project link | `group_project_access_granted` | 🤖 Automatic | `trg_after_ugp_insert` | Warning severity |
| **DELETE** group-project link | `group_project_access_revoked` | 🤖 Automatic | `trg_after_ugp_delete` | Warning severity |

---

## Roles Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** role | `role_assigned` | 🤖 Automatic | `trg_after_role_insert` | Captures role_hash, priority |
| **UPDATE** role | `role_assigned` | 🤖 Automatic | `trg_after_role_update` | Updates to role details |
| **DELETE** role | `role_removed` | 🤖 Automatic | `trg_after_role_delete` | Warning severity |

---

## Global Permission Groups Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** permission_group | `permission_group_assigned` | 🤖 Automatic | `trg_after_perm_group_insert` | Captures group_hash, category |
| **UPDATE** permission_group | `permission_group_assigned` | 🤖 Automatic | `trg_after_perm_group_update` | Updates to group details |
| **DELETE** permission_group | `permission_group_revoked` | 🤖 Automatic | `trg_after_perm_group_delete` | Warning severity |

---

## Global Permissions Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** permission | `permission_grant` | 🤖 Automatic | `trg_after_permission_insert` | Captures permission_hash, category |
| **UPDATE** permission | `permission_grant` | 🤖 Automatic | `trg_after_permission_update` | Updates to permission details |
| **DELETE** permission | `permission_revoke` | 🤖 Automatic | `trg_after_permission_delete` | Warning severity |

---

## Role Permission Groups Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** role-permgroup link | `permission_group_assigned` | 🤖 Automatic | `trg_after_rpg_insert` | Links perm group to role |
| **DELETE** role-permgroup link | `permission_group_revoked` | 🤖 Automatic | `trg_after_rpg_delete` | Warning severity |

---

## User Group Permission Groups Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** usergroup-permgroup link | `permission_group_assigned` | 🤖 Automatic | `trg_after_ugpg_insert` | Assigns perm group to user group |
| **DELETE** usergroup-permgroup link | `permission_group_revoked` | 🤖 Automatic | `trg_after_ugpg_delete` | Warning severity |

---

## User Permission Groups Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** user-permgroup link | `permission_group_assigned` | 🤖 Automatic | `trg_after_upg_insert` | Direct user permission assignment |
| **DELETE** user-permgroup link | `permission_group_revoked` | 🤖 Automatic | `trg_after_upg_delete` | Warning severity |

---

## Global Permission Group Permissions Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** permission in group | `permission_grant` | 🤖 Automatic | `trg_after_gpgp_insert` | Adds permission to group |
| **DELETE** permission from group | `permission_revoke` | 🤖 Automatic | `trg_after_gpgp_delete` | Removes permission from group |

---

## User Sessions Table

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** session | `session_created` | 🤖 Automatic | `trg_after_session_insert` | Info severity |
| **UPDATE** session (deactivated) | `user_logout` | 🤖 Automatic | `trg_after_session_update` | Only when is_active → FALSE |

---

## Project Groups Table (No automatic triggers)

| Operation | Activity Code | Type | Trigger | Notes |
|-----------|--------------|------|---------|-------|
| **CREATE** project_group | `admin_action` | 👋 Manual | - | Use manual logging |
| **UPDATE** project_group | `admin_action` | 👋 Manual | - | Use manual logging |
| **DELETE** project_group | `admin_action` | 👋 Manual | - | Use manual logging |

**Recommendation:** Add triggers for project_groups if needed.

---

## Manual Logging Required

### Authentication Events

| Event | Activity Code | When to Log |
|-------|--------------|-------------|
| User login | `user_login` | On successful authentication |
| Failed login | `user_login_failed` | On authentication failure |
| Session expired | `session_expired` | When cleanup job runs |

### Project Membership (No direct table)

| Event | Activity Code | When to Log |
|-------|--------------|-------------|
| Member added to project | `project_member_add` | Via application logic |
| Member removed from project | `project_member_remove` | Via application logic |

### Bulk Operations

| Event | Activity Code | When to Log |
|-------|--------------|-------------|
| Bulk role assignment | `bulk_role_assignment` | After bulk operation completes |
| Bulk group assignment | `bulk_group_assignment` | After bulk operation completes |
| Bulk user update | `bulk_user_update` | After bulk operation completes |
| Bulk user delete | `bulk_user_delete` | After bulk operation completes |

### Administrative Actions

| Event | Activity Code | When to Log |
|-------|--------------|-------------|
| Custom admin action | `admin_action` | For operations not covered by triggers |
| System event | `system_event` | For maintenance, migrations, etc. |
| Security alert | `security_alert` | For suspicious activities |

---

## Usage Patterns

### Pattern 1: Fully Automatic (Triggers Handle Everything)

**Example: User Creation**

```python
# Application code - just create the user
user = User(
    id=generate_id(),
    username="johndoe",
    email="john@example.com",
    ...
)
db.add(user)
db.commit()

# ✅ Activity log automatically created by trg_after_user_insert
# No manual logging needed!
```

### Pattern 2: Manual Logging Required

**Example: User Login**

```python
# Application code
user = authenticate(username, password)

if user:
    # Manual logging required
    await ActivityLogger.log_login(
        user_id=user.id,
        username=user.username,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
else:
    # Log failed attempt
    await ActivityLogger.log_failed_login(
        username=username,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
```

### Pattern 3: Hybrid (Trigger + Manual Enhancement)

**Example: Project Archived with Context**

```python
# Application code
project.archived = True
project.archived_by = current_user.id
project.archived_at = datetime.now()
db.commit()

# ✅ Trigger logs basic archive event

# ➕ Optionally add more context
await ActivityLogger.log_activity(
    user_id=current_user.id,
    activity_code="project_archived",
    details=f"Project archived. Reason: {reason}",
    project_id=project.id,
    metadata={
        "reason": reason,
        "will_restore": False,
        "notification_sent": True
    }
)
```

---

## Coverage Summary

### ✅ Fully Covered (Automatic via Triggers)

- Users (all CRUD operations)
- Projects (all CRUD operations)
- User Groups (all CRUD operations)
- User Group Members (assignments/removals)
- User Group Projects (access grants/revocations)
- Roles (all CRUD operations)
- Permission Groups (all CRUD operations)
- Permissions (all CRUD operations)
- All permission assignment tables
- Sessions (creation, logout)

### ⚠️ Partially Covered (Requires Manual Logging)

- Authentication events (login, logout, failed attempts)
- Project membership (no direct table mapping)
- Bulk operations
- Custom admin actions

### ❌ Not Covered (Add Triggers if Needed)

- Project Groups
- Project Group Members
- Role Project Catalog (metadata only)
- Permission Project Catalog (metadata only)
- Password Resets (user_password_resets table)

---

## Recommended Trigger Additions

If you need more comprehensive coverage, consider adding triggers for:

### Password Resets Table

```sql
-- Track password reset token generation
CREATE TRIGGER trg_after_password_reset_insert
AFTER INSERT ON user_password_resets
FOR EACH ROW
BEGIN
    INSERT INTO activity_logs (...)
    SELECT ... WHERE ac.activity_code = 'user_password_reset' ...;
END;
```

### Bulk Operations Log Table

```sql
-- Track bulk operation execution
CREATE TRIGGER trg_after_bulk_op_insert
AFTER INSERT ON bulk_operations_log
FOR EACH ROW
BEGIN
    -- Determine activity code based on operation_type
    -- Log to activity_logs
END;
```

---

## Testing CRUD Mapping

### Test Script

```sql
-- Test user creation
INSERT INTO users (...) VALUES (...);
SELECT * FROM activity_logs WHERE activity_type = 'user_registration' ORDER BY created_at DESC LIMIT 1;

-- Test user update
UPDATE users SET user_type = 'admin' WHERE id = 'user-123';
SELECT * FROM activity_logs WHERE activity_type = 'user_type_changed' ORDER BY created_at DESC LIMIT 1;

-- Test user deletion
DELETE FROM users WHERE id = 'user-123';
SELECT * FROM activity_logs WHERE activity_type = 'user_deleted' ORDER BY created_at DESC LIMIT 1;

-- Repeat for other entities...
```

---

## Maintenance

### Regular Checks

1. **Verify trigger coverage** - Run quarterly:
```sql
SELECT TABLE_NAME, TRIGGER_NAME, EVENT_MANIPULATION
FROM information_schema.TRIGGERS
WHERE TRIGGER_SCHEMA = 'magic_auth'
ORDER BY TABLE_NAME, EVENT_MANIPULATION;
```

2. **Check activity catalog completeness**:
```sql
SELECT activity_category, COUNT(*) as event_count
FROM activity_catalog
WHERE is_active = TRUE
GROUP BY activity_category;
```

3. **Audit log volume**:
```sql
SELECT 
    DATE(created_at) as log_date,
    COUNT(*) as log_count,
    severity_level
FROM activity_logs
WHERE created_at >= DATE_SUB(NOW(), INTERVAL 7 DAY)
GROUP BY DATE(created_at), severity_level
ORDER BY log_date DESC, severity_level;
```

---

## Summary

- **40 activity event types** defined in catalog
- **28 automatic triggers** covering core CRUD operations
- **12 manual logging points** for business logic events
- **100% coverage** on primary entities (users, projects, groups, permissions)
- **Extensible** - easy to add new triggers and events as needed
