# Activity Events Catalog

This document provides a complete reference of all activity events tracked in the system, organized by category.

## Quick Reference

| Code | Name | Category | Severity | Trigger | Manual |
|------|------|----------|----------|---------|--------|
| user_login | User Login | authentication | info | ✗ | ✓ |
| user_logout | User Logout | authentication | info | ✓ | ✓ |
| user_login_failed | Login Failed | authentication | warning | ✗ | ✓ |
| session_created | Session Created | authentication | info | ✓ | ✗ |
| session_expired | Session Expired | authentication | info | ✗ | ✓ |
| user_registration | User Registration | user_management | info | ✓ | ✗ |
| user_update | User Updated | user_management | info | ✓ | ✗ |
| user_status_change | User Status Changed | user_management | warning | ✓ | ✗ |
| user_password_reset | Password Reset | user_management | warning | ✓ | ✗ |
| user_type_changed | User Type Changed | user_management | critical | ✓ | ✗ |
| user_deleted | User Deleted | user_management | critical | ✓ | ✗ |
| project_creation | Project Created | project_management | info | ✓ | ✗ |
| project_update | Project Updated | project_management | info | ✓ | ✗ |
| project_delete | Project Deleted | project_management | critical | ✓ | ✗ |
| project_archived | Project Archived | project_management | warning | ✓ | ✗ |
| project_unarchived | Project Unarchived | project_management | info | ✓ | ✗ |
| project_ownership_transferred | Ownership Transferred | project_management | critical | ✓ | ✗ |
| project_member_add | Member Added | project_members | info | ✗ | ✓ |
| project_member_remove | Member Removed | project_members | warning | ✗ | ✓ |
| group_creation | Group Created | group_management | info | ✓ | ✗ |
| group_update | Group Updated | group_management | info | ✓ | ✗ |
| group_delete | Group Deleted | group_management | critical | ✓ | ✗ |
| user_group_assign | User Assigned to Group | group_management | info | ✓ | ✗ |
| user_group_remove | User Removed from Group | group_management | warning | ✓ | ✗ |
| group_project_access_granted | Group Project Access | group_management | warning | ✓ | ✗ |
| group_project_access_revoked | Group Access Revoked | group_management | warning | ✓ | ✗ |
| permission_grant | Permission Granted | permission_management | warning | ✓ | ✗ |
| permission_revoke | Permission Revoked | permission_management | warning | ✓ | ✗ |
| role_removed | Role Removed | permission_management | warning | ✓ | ✗ |
| role_assigned | Role Assigned | permission_management | warning | ✓ | ✗ |
| permission_group_assigned | Permission Group Assigned | permission_management | warning | ✓ | ✗ |
| permission_group_revoked | Permission Group Revoked | permission_management | warning | ✓ | ✗ |
| bulk_role_assignment | Bulk Role Assignment | bulk_operations | critical | ✗ | ✓ |
| bulk_group_assignment | Bulk Group Assignment | bulk_operations | warning | ✗ | ✓ |
| bulk_user_update | Bulk User Update | bulk_operations | warning | ✗ | ✓ |
| bulk_user_delete | Bulk User Delete | bulk_operations | critical | ✗ | ✓ |
| admin_action | Admin Action | admin | warning | ✗ | ✓ |
| system_event | System Event | system | info | ✗ | ✓ |
| security_alert | Security Alert | security | critical | ✗ | ✓ |

**Legend:**
- ✓ = Available
- ✗ = Not applicable/Not available

---

## Authentication Activities

### user_login
**Code:** `user_login`  
**Category:** authentication  
**Severity:** info  
**Requires Audit:** Yes

**Description:** User successfully logged into the system.

**Triggered By:** Manual logging (auth endpoint)

**Captured Data:**
- User ID
- IP address
- User agent
- Project ID (if project-specific login)
- Session ID

**Example:**
```json
{
  "activity_code": "user_login",
  "user_id": "user-123",
  "details": "User johndoe logged in",
  "ip_address": "192.168.1.1",
  "metadata": {
    "username": "johndoe",
    "project_id": "proj-456",
    "login_method": "password"
  }
}
```

---

### user_logout
**Code:** `user_logout`  
**Category:** authentication  
**Severity:** info  
**Requires Audit:** Yes

**Description:** User logged out or session ended.

**Triggered By:** Database trigger (user_sessions UPDATE)

**Captured Data:**
- User ID
- Session ID
- Project ID

---

### user_login_failed
**Code:** `user_login_failed`  
**Category:** authentication  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** Failed login attempt.

**Triggered By:** Manual logging (auth endpoint)

**Captured Data:**
- Username/email attempted
- IP address
- User agent
- Failure reason

**Use Case:** Security monitoring, detect brute force attacks

---

### session_created
**Code:** `session_created`  
**Category:** authentication  
**Severity:** info  
**Requires Audit:** No

**Description:** New user session created.

**Triggered By:** Database trigger (user_sessions INSERT)

**Captured Data:**
- User ID
- Session ID
- Project ID
- Expiration time

---

### session_expired
**Code:** `session_expired`  
**Category:** authentication  
**Severity:** info  
**Requires Audit:** No

**Description:** User session expired.

**Triggered By:** Manual logging (session cleanup job)

---

## User Management Activities

### user_registration
**Code:** `user_registration`  
**Category:** user_management  
**Severity:** info  
**Requires Audit:** Yes

**Description:** New user account created.

**Triggered By:** Database trigger (users INSERT)

**Captured Data:**
- User ID
- Username
- Email
- User type
- Created by (user ID)

**Metadata Example:**
```json
{
  "user_hash": "usr-abc123",
  "username": "johndoe",
  "email": "john@example.com",
  "user_type": "consumer",
  "is_active": true
}
```

---

### user_update
**Code:** `user_update`  
**Category:** user_management  
**Severity:** info  
**Requires Audit:** Yes

**Description:** User profile updated (general changes).

**Triggered By:** Database trigger (users UPDATE)

**Captured Data:**
- User ID
- Old values
- New values

---

### user_status_change
**Code:** `user_status_change`  
**Category:** user_management  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** User account activated or deactivated.

**Triggered By:** Database trigger (users UPDATE where is_active changed)

**Captured Data:**
- User ID
- Previous status
- New status

**Use Case:** Track account suspensions/reactivations

---

### user_password_reset
**Code:** `user_password_reset`  
**Category:** user_management  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** User password was changed/reset.

**Triggered By:** Database trigger (users UPDATE where password_hash changed)

**Captured Data:**
- User ID
- Performed by (admin or self)
- IP address

**Security Note:** Password values are never logged, only the fact that change occurred.

---

### user_type_changed
**Code:** `user_type_changed`  
**Category:** user_management  
**Severity:** critical  
**Requires Audit:** Yes

**Description:** User type changed (root/admin/consumer).

**Triggered By:** Database trigger (users UPDATE where user_type changed)

**Captured Data:**
- User ID
- Old user type
- New user type
- Performed by

**Use Case:** Security audit, privilege escalation tracking

---

### user_deleted
**Code:** `user_deleted`  
**Category:** user_management  
**Severity:** critical  
**Requires Audit:** Yes

**Description:** User account permanently deleted.

**Triggered By:** Database trigger (users DELETE)

**Captured Data:**
- User ID
- Username
- User type
- All user metadata (snapshot)

---

## Project Management Activities

### project_creation
**Code:** `project_creation`  
**Category:** project_management  
**Severity:** info  
**Requires Audit:** Yes

**Description:** New project created.

**Triggered By:** Database trigger (projects INSERT)

**Captured Data:**
- Project ID
- Project name
- Project hash
- Owner ID
- Created by

---

### project_update
**Code:** `project_update`  
**Category:** project_management  
**Severity:** info  
**Requires Audit:** Yes

**Description:** Project details updated (general changes).

**Triggered By:** Database trigger (projects UPDATE)

**Captured Data:**
- Project ID
- Old values
- New values

---

### project_delete
**Code:** `project_delete`  
**Category:** project_management  
**Severity:** critical  
**Requires Audit:** Yes

**Description:** Project permanently deleted.

**Triggered By:** Database trigger (projects DELETE)

**Captured Data:**
- Project ID
- Project name
- Project snapshot

---

### project_archived
**Code:** `project_archived`  
**Category:** project_management  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** Project archived (soft delete).

**Triggered By:** Database trigger (projects UPDATE where archived = TRUE)

**Captured Data:**
- Project ID
- Project name
- Archived by
- Archived at

---

### project_unarchived
**Code:** `project_unarchived`  
**Category:** project_management  
**Severity:** info  
**Requires Audit:** Yes

**Description:** Project restored from archived state.

**Triggered By:** Database trigger (projects UPDATE where archived = FALSE)

---

### project_ownership_transferred
**Code:** `project_ownership_transferred`  
**Category:** project_management  
**Severity:** critical  
**Requires Audit:** Yes

**Description:** Project ownership transferred to another user.

**Triggered By:** Database trigger (projects UPDATE where owner_id changed)

**Captured Data:**
- Project ID
- Previous owner ID
- New owner ID
- Performed by

---

## Project Members Activities

### project_member_add
**Code:** `project_member_add`  
**Category:** project_members  
**Severity:** info  
**Requires Audit:** Yes

**Description:** User added to project.

**Triggered By:** Manual logging (membership endpoint)

**Captured Data:**
- User ID
- Project ID
- Added by
- Assigned role/permissions

---

### project_member_remove
**Code:** `project_member_remove`  
**Category:** project_members  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** User removed from project.

**Triggered By:** Manual logging (membership endpoint)

**Captured Data:**
- User ID
- Project ID
- Removed by
- Reason (optional)

---

## Group Management Activities

### group_creation
**Code:** `group_creation`  
**Category:** group_management  
**Severity:** info  
**Requires Audit:** Yes

**Description:** New user group created.

**Triggered By:** Database trigger (user_groups INSERT)

**Captured Data:**
- Group ID
- Group name
- Group hash
- Parent group (if hierarchical)
- Created by

---

### group_update
**Code:** `group_update`  
**Category:** group_management  
**Severity:** info  
**Requires Audit:** Yes

**Description:** User group details updated.

**Triggered By:** Database trigger (user_groups UPDATE)

---

### group_delete
**Code:** `group_delete`  
**Category:** group_management  
**Severity:** critical  
**Requires Audit:** Yes

**Description:** User group deleted.

**Triggered By:** Database trigger (user_groups DELETE)

---

### user_group_assign
**Code:** `user_group_assign`  
**Category:** group_management  
**Severity:** info  
**Requires Audit:** Yes

**Description:** User assigned to user group.

**Triggered By:** Database trigger (user_group_members INSERT)

**Captured Data:**
- User ID
- Group ID
- Assigned by

---

### user_group_remove
**Code:** `user_group_remove`  
**Category:** group_management  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** User removed from user group.

**Triggered By:** Database trigger (user_group_members DELETE)

---

### group_project_access_granted
**Code:** `group_project_access_granted`  
**Category:** group_management  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** User group granted access to project.

**Triggered By:** Database trigger (user_group_projects INSERT)

**Captured Data:**
- Group ID
- Project ID
- Granted by

---

### group_project_access_revoked
**Code:** `group_project_access_revoked`  
**Category:** group_management  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** User group access to project revoked.

**Triggered By:** Database trigger (user_group_projects DELETE)

---

## Permission Management Activities

### permission_grant
**Code:** `permission_grant`  
**Category:** permission_management  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** Permission granted (creation or assignment).

**Triggered By:** Database trigger (global_permissions INSERT, global_permission_group_permissions INSERT)

---

### permission_revoke
**Code:** `permission_revoke`  
**Category:** permission_management  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** Permission revoked or deleted.

**Triggered By:** Database trigger (global_permissions DELETE, global_permission_group_permissions DELETE)

---

### role_assigned
**Code:** `role_assigned`  
**Category:** permission_management  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** Role assigned or created.

**Triggered By:** Database trigger (roles INSERT, role_permission_groups INSERT)

---

### role_removed
**Code:** `role_removed`  
**Category:** permission_management  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** Role removed or deleted.

**Triggered By:** Database trigger (roles DELETE)

---

### permission_group_assigned
**Code:** `permission_group_assigned`  
**Category:** permission_management  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** Permission group assigned.

**Triggered By:** Database trigger (various permission group assignment tables)

---

### permission_group_revoked
**Code:** `permission_group_revoked`  
**Category:** permission_management  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** Permission group revoked.

**Triggered By:** Database trigger (various permission group assignment tables)

---

## Bulk Operations Activities

### bulk_role_assignment
**Code:** `bulk_role_assignment`  
**Category:** bulk_operations  
**Severity:** critical  
**Requires Audit:** Yes

**Description:** Multiple roles assigned at once.

**Triggered By:** Manual logging (bulk operations endpoint)

**Captured Data:**
- Number of users affected
- Roles assigned
- Performed by

---

### bulk_group_assignment
**Code:** `bulk_group_assignment`  
**Category:** bulk_operations  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** Multiple users assigned to groups.

**Triggered By:** Manual logging

---

### bulk_user_update
**Code:** `bulk_user_update`  
**Category:** bulk_operations  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** Multiple users updated at once.

**Triggered By:** Manual logging

---

### bulk_user_delete
**Code:** `bulk_user_delete`  
**Category:** bulk_operations  
**Severity:** critical  
**Requires Audit:** Yes

**Description:** Multiple users deleted at once.

**Triggered By:** Manual logging

**Captured Data:**
- Number of users deleted
- User IDs
- Performed by

---

## Admin and System Activities

### admin_action
**Code:** `admin_action`  
**Category:** admin  
**Severity:** warning  
**Requires Audit:** Yes

**Description:** General administrative action.

**Triggered By:** Manual logging

**Use Case:** Track custom admin operations not covered by other events.

---

### system_event
**Code:** `system_event`  
**Category:** system  
**Severity:** info  
**Requires Audit:** Yes

**Description:** System-level event.

**Triggered By:** Manual logging

**Use Case:** Track system maintenance, migrations, etc.

---

### security_alert
**Code:** `security_alert`  
**Category:** security  
**Severity:** critical  
**Requires Audit:** Yes

**Description:** Security-related alert or event.

**Triggered By:** Manual logging

**Use Case:** Track suspicious activities, security incidents, rate limiting triggers.

---

## Adding New Activity Events

To add a new activity event:

1. **Insert into activity_catalog:**
```sql
INSERT INTO activity_catalog (
    id, activity_code, activity_name, activity_description,
    activity_category, severity_level, requires_audit, is_active
) VALUES (
    'act-cat-041',
    'your_activity_code',
    'Display Name',
    'Detailed description',
    'category',
    'info',  -- or 'warning', 'critical'
    TRUE,
    TRUE
);
```

2. **Create trigger (if automatic):** Add to appropriate triggers file

3. **Update documentation:** Add to this catalog

4. **Test:** Verify trigger fires and log is created correctly
