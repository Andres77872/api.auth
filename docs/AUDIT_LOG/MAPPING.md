# Audit Log Activity Mapping

**Magic Auth System - Complete Action-to-Audit Mapping**

---

## Overview

This document provides a complete mapping of system actions to audit log activities. Use this as a quick reference to determine which activity type to log for specific operations.

---

## User Management Actions

### User CRUD Operations

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Create user account | `user_registration` | root, admin | info | YES |
| Update user profile (by admin) | `user_update` | root, admin | info | YES |
| Update own profile | `user_update` | consumer (optional) | info | OPTIONAL |
| Delete user account | `user_deleted` | root, admin | critical | YES |

**Code Example:**
```python
# Create user
ActivityLogger.log_activity(
    user_id=admin.id,
    activity_type=ActivityType.USER_REGISTRATION.value,
    details={"username": new_user.username, "user_type": "consumer"},
    target_user_id=new_user.id
)

# Update user (by admin)
ActivityLogger.log_user_update(
    user_id=admin.id,
    target_user_id=target_user.id,
    changes={"email": "new@example.com"}
)

# Delete user
ActivityLogger.log_activity(
    user_id=admin.id,
    activity_type=ActivityType.USER_DELETED.value,
    details={"deleted_username": user.username},
    target_user_id=user.id
)
```

### User Status & Type Management

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Activate user | `user_status_change` | root, admin | warning | YES |
| Deactivate user | `user_status_change` | root, admin | warning | YES |
| Change user type (admin→root) | `user_type_changed` | root | critical | YES |
| Change user type (consumer→admin) | `user_type_changed` | root | critical | YES |

**Code Example:**
```python
# Change status
ActivityLogger.log_user_status_change(
    user_id=admin.id,
    target_user_id=user.id,
    new_status="inactive"
)

# Change type
ActivityLogger.log_user_type_changed(
    user_id=root.id,
    target_user_id=user.id,
    old_type="consumer",
    new_type="admin"
)
```

### Password Management

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Admin resets user password | `user_password_reset` | root, admin | warning | YES |
| User changes own password | `user_password_reset` | consumer (optional) | info | OPTIONAL |

**Code Example:**
```python
ActivityLogger.log_user_password_reset(
    user_id=admin.id,
    target_user_id=user.id
)
```

---

## Authentication Actions

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Successful login | `user_login` | root, admin, consumer | info | YES |
| Failed login attempt | `user_login_failed` | ALL (any attempt) | warning | YES |
| User logout | `user_logout` | root, admin | info | YES |
| User logout | `user_logout` | consumer | info | OPTIONAL |
| Session expired | `session_expired` | system | info | NO |

**Code Example:**
```python
# Successful login
ActivityLogger.log_user_login(
    user_id=user.id,
    project_id=project.id
)

# Failed login
ActivityLogger.log_activity(
    user_id=None,
    activity_type=ActivityType.USER_LOGIN_FAILED.value,
    details={"attempted_username": "john.doe", "reason": "invalid_password"}
)

# Logout
ActivityLogger.log_user_logout(
    user_id=user.id
)
```

---

## Project Management Actions

### Project CRUD Operations

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Create project | `project_creation` | root, admin | info | YES |
| Update project details | `project_update` | root, admin | info | YES |
| Delete project | `project_delete` | root | critical | YES |
| Archive project | `project_archived` | root, admin | warning | YES |
| Unarchive project | `project_unarchived` | root, admin | info | YES |

**Code Example:**
```python
# Create project
ActivityLogger.log_project_creation(
    user_id=admin.id,
    project_id=project.id,
    project_name="New Application"
)

# Update project
ActivityLogger.log_project_update(
    user_id=admin.id,
    project_id=project.id,
    changes={"project_name": "Updated Name"}
)

# Delete project
ActivityLogger.log_project_delete(
    user_id=root.id,
    project_id=project.id,
    project_name="Deleted Project"
)

# Archive project
ActivityLogger.log_project_archived(
    user_id=admin.id,
    project_id=project.id
)
```

### Project Ownership

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Transfer ownership | `project_ownership_transferred` | root, admin | critical | YES |

**Code Example:**
```python
ActivityLogger.log_project_ownership_transferred(
    user_id=admin.id,
    project_id=project.id,
    target_user_id=new_owner.id
)
```

### Project Members

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Add user to project | `project_member_add` | root, admin | info | YES |
| Remove user from project | `project_member_remove` | root, admin | warning | YES |

**Code Example:**
```python
# Add member
ActivityLogger.log_project_member_add(
    user_id=admin.id,
    project_id=project.id,
    target_user_id=new_member.id
)

# Remove member
ActivityLogger.log_project_member_remove(
    user_id=admin.id,
    project_id=project.id,
    target_user_id=removed_member.id
)
```

---

## Group Management Actions

### Group CRUD Operations

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Create user group | `group_creation` | root, admin | info | YES |
| Update group details | `group_update` | root, admin | info | YES |
| Delete user group | `group_delete` | root, admin | critical | YES |

**Code Example:**
```python
# Create group
ActivityLogger.log_group_creation(
    user_id=admin.id,
    user_group_id=group.id,
    group_name="Engineering Team"
)

# Update group
ActivityLogger.log_group_update(
    user_id=admin.id,
    user_group_id=group.id,
    changes={"group_name": "Updated Name"}
)

# Delete group
ActivityLogger.log_group_delete(
    user_id=admin.id,
    user_group_id=group.id,
    group_name="Deleted Group"
)
```

### Group Membership

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Assign user to group | `user_group_assign` | root, admin | info | YES |
| Remove user from group | `user_group_remove` | root, admin | warning | YES |
| Grant group access to project | `project_member_add` | root, admin | info | YES |
| Revoke group access from project | `project_member_remove` | root, admin | warning | YES |

**Code Example:**
```python
# Assign user to group
ActivityLogger.log_user_group_assign(
    user_id=admin.id,
    target_user_id=user.id,
    user_group_id=group.id
)

# Remove user from group
ActivityLogger.log_user_group_remove(
    user_id=admin.id,
    target_user_id=user.id,
    user_group_id=group.id
)
```

---

## Permission Management Actions

### Permission Operations

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Grant permission to user | `permission_grant` | root, admin | warning | YES |
| Revoke permission from user | `permission_revoke` | root, admin | warning | YES |
| Grant permission to group | `permission_grant` | root, admin | warning | YES |
| Revoke permission from group | `permission_revoke` | root, admin | warning | YES |

**Code Example:**
```python
# Grant permission
ActivityLogger.log_permission_grant(
    user_id=admin.id,
    target_user_id=user.id,
    permission="project.delete",
    project_id=project.id
)

# Revoke permission
ActivityLogger.log_permission_revoke(
    user_id=admin.id,
    target_user_id=user.id,
    permission="project.delete",
    project_id=project.id
)
```

### Role Operations

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Assign role to user | `role_assigned` | root, admin | info | YES |
| Remove role from user | `role_removed` | root, admin | warning | YES |
| Assign permission group to role | `permission_grant` | root, admin | warning | YES |

**Code Example:**
```python
# Assign role
ActivityLogger.log_activity(
    user_id=admin.id,
    activity_type=ActivityType.ROLE_ASSIGNED.value,
    details={"role_name": "Project Manager"},
    target_user_id=user.id
)

# Remove role
ActivityLogger.log_role_removed(
    user_id=admin.id,
    target_user_id=user.id,
    role="Project Manager"
)
```

---

## Bulk Operations

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Bulk assign roles | `bulk_role_assignment` | root, admin | warning | YES |
| Bulk assign groups | `bulk_group_assignment` | root, admin | warning | YES |
| Bulk update users | `bulk_user_update` | root, admin | warning | YES |
| Bulk delete users | `bulk_user_delete` | root | critical | YES |

**Code Example:**
```python
# Bulk role assignment
ActivityLogger.log_bulk_role_assignment(
    user_id=admin.id,
    count=25,
    metadata={"role_name": "Viewer", "target_users": user_ids}
)

# Bulk user update
ActivityLogger.log_bulk_user_update(
    user_id=admin.id,
    count=50,
    metadata={"updated_fields": ["status", "email_domain"]}
)

# Bulk delete
ActivityLogger.log_bulk_user_delete(
    user_id=root.id,
    count=15,
    metadata={"deletion_criteria": "inactive > 365 days"}
)
```

---

## System & Administrative Actions

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| System configuration change | `system_config_change` | root | critical | YES |
| Database backup | `system_event` | system | info | YES |
| General admin action | `admin_action` | root, admin | warning | YES |

**Code Example:**
```python
# System config change
ActivityLogger.log_activity(
    user_id=root.id,
    activity_type=ActivityType.SYSTEM_CONFIG_CHANGE.value,
    details={"config_key": "session_timeout", "old_value": "60", "new_value": "30"}
)

# System event
ActivityLogger.log_system_event(
    event="database_backup_completed",
    details={"backup_size_gb": 1.2, "duration_seconds": 45}
)

# Admin action
ActivityLogger.log_admin_action(
    user_id=admin.id,
    action="manual_intervention",
    details={"description": "Fixed data inconsistency"}
)
```

---

## Security Events

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| Brute force detected | `security_alert` | system | critical | YES |
| Suspicious activity | `suspicious_activity` | system | critical | YES |
| Multiple failed logins | `user_login_failed` | system | warning | YES |

**Code Example:**
```python
# Brute force alert
ActivityLogger.log_activity(
    user_id=None,
    activity_type=ActivityType.SECURITY_ALERT.value,
    details={
        "alert_type": "brute_force_detected",
        "target_username": "admin",
        "attempt_count": 10
    },
    ip_address=attacker_ip
)

# Suspicious activity
ActivityLogger.log_activity(
    user_id=None,
    activity_type=ActivityType.SUSPICIOUS_ACTIVITY.value,
    details={
        "activity_type": "unusual_access_pattern",
        "user_id": user.id,
        "anomaly_score": 0.85
    }
)
```

---

## API & Integration (Optional Logging)

| Action | Activity Code | Logged For | Severity | Required |
|--------|---------------|------------|----------|----------|
| API endpoint access | `api_access` | external systems | info | NO |
| API error | `api_error` | system | warning | YES |
| Integration sync | `integration_sync` | system | info | NO |

**Code Example:**
```python
# API error (if significant)
ActivityLogger.log_activity(
    user_id=None,
    activity_type=ActivityType.API_ERROR.value,
    details={
        "endpoint": "/api/v1/users",
        "error_code": "VALIDATION_ERROR",
        "error_message": "Invalid format"
    }
)
```

---

## Actions That Should NOT Be Logged

### High-Frequency Operations (NEVER LOG)

| Action | Reason | Alternative |
|--------|--------|-------------|
| Session validation | Called every request | Monitor session count |
| Permission check | Multiple per request | Log permission grants/revokes only |
| Token verification | Every authenticated request | Log authentication events |
| Health check | Automated frequent checks | Use monitoring tools |
| Cache operations | Very high frequency | Monitor cache hit rate |
| Metrics collection | Continuous operation | Use metrics system |

### Read-Only Operations (DON'T LOG)

| Action | Reason | Alternative |
|--------|--------|-------------|
| View profile (GET) | Read operation | Log updates only |
| List users | Read operation | Log when user is created |
| List projects | Read operation | Log project creation |
| Search operations | Read operation | Monitor search patterns separately |
| View permissions | Read operation | Log permission changes |
| Analytics views | Read operation | Use analytics system |

### Consumer Routine Actions (OPTIONAL - Generally Don't Log)

| Action | Reason | Alternative |
|--------|--------|-------------|
| Update own profile | Low security impact | Optional configuration |
| View own projects | Routine operation | Not needed |
| Change own password | Optional to log | Log if security policy requires |
| Navigation actions | UI operations | Not needed |

---

## Quick Decision Matrix

Use this matrix to quickly decide if an action should be logged:

| Criteria | Log? |
|----------|------|
| **User Type** | |
| Root user action | ✅ YES |
| Admin user action | ✅ YES |
| Consumer security action | ✅ YES |
| Consumer routine action | ❌ NO (optional) |
| **Operation Type** | |
| CREATE operation | ✅ YES |
| UPDATE operation | ✅ YES |
| DELETE operation | ✅ YES |
| READ operation (GET) | ❌ NO |
| **Frequency** | |
| Once per session | ✅ YES |
| Multiple per request | ❌ NO |
| Every request | ❌ NO |
| **Impact** | |
| State changing | ✅ YES |
| Read-only | ❌ NO |
| Security-critical | ✅ YES |
| Administrative | ✅ YES |

---

## Route-to-Activity Mapping

### User Routes (`/api/v1/users/*`)

| Endpoint | Method | Activity Code | Log? |
|----------|--------|---------------|------|
| `/users/profile` | GET | - | ❌ NO |
| `/admin/users` | POST | `user_registration` | ✅ YES |
| `/admin/users/{hash}` | PUT | `user_update` | ✅ YES |
| `/admin/users/{hash}` | DELETE | `user_deleted` | ✅ YES |
| `/admin/users/{hash}/status` | PUT | `user_status_change` | ✅ YES |
| `/admin/users/{hash}/type` | PUT | `user_type_changed` | ✅ YES |

### Project Routes (`/api/v1/projects/*`)

| Endpoint | Method | Activity Code | Log? |
|----------|--------|---------------|------|
| `/projects` | GET | - | ❌ NO |
| `/projects` | POST | `project_creation` | ✅ YES |
| `/projects/{hash}` | GET | - | ❌ NO |
| `/projects/{hash}` | PUT | `project_update` | ✅ YES |
| `/projects/{hash}` | DELETE | `project_delete` | ✅ YES |
| `/projects/{hash}/archive` | POST | `project_archived` | ✅ YES |
| `/projects/{hash}/members` | POST | `project_member_add` | ✅ YES |
| `/projects/{hash}/members/{user}` | DELETE | `project_member_remove` | ✅ YES |

### Group Routes (`/api/v1/groups/*`)

| Endpoint | Method | Activity Code | Log? |
|----------|--------|---------------|------|
| `/groups` | GET | - | ❌ NO |
| `/groups` | POST | `group_creation` | ✅ YES |
| `/groups/{hash}` | PUT | `group_update` | ✅ YES |
| `/groups/{hash}` | DELETE | `group_delete` | ✅ YES |
| `/groups/{hash}/members` | POST | `user_group_assign` | ✅ YES |
| `/groups/{hash}/members/{user}` | DELETE | `user_group_remove` | ✅ YES |

### Authentication Routes (`/api/v1/auth/*`)

| Endpoint | Method | Activity Code | Log? |
|----------|--------|---------------|------|
| `/auth/login` | POST | `user_login` / `user_login_failed` | ✅ YES |
| `/auth/logout` | POST | `user_logout` | ✅ YES (admin/root) |
| `/auth/validate-session` | GET | - | ❌ NO |
| `/auth/refresh` | POST | - | ❌ NO |

### Permission Routes (`/api/v1/permissions/*`)

| Endpoint | Method | Activity Code | Log? |
|----------|--------|---------------|------|
| `/permissions` | GET | - | ❌ NO |
| `/permissions/grant` | POST | `permission_grant` | ✅ YES |
| `/permissions/revoke` | POST | `permission_revoke` | ✅ YES |
| `/permissions/check` | GET | - | ❌ NO |

---

## Summary Statistics

### Activities by Category

| Category | Total | Always Log | Optional | Never Log |
|----------|-------|------------|----------|-----------|
| User Management | 5 | 4 | 1 | 0 |
| Authentication | 4 | 3 | 1 | 0 |
| Project Management | 6 | 6 | 0 | 0 |
| Group Management | 5 | 5 | 0 | 0 |
| Permissions | 4 | 4 | 0 | 0 |
| Bulk Operations | 4 | 4 | 0 | 0 |
| Security | 3 | 3 | 0 | 0 |
| System/Admin | 3 | 3 | 0 | 0 |
| API/Integration | 3 | 1 | 0 | 2 |

### Logging by User Type

| User Type | Always Log | Sometimes Log | Never Log |
|-----------|------------|---------------|-----------|
| **Root** | All actions | - | High-frequency reads |
| **Admin** | All actions | - | High-frequency reads |
| **Consumer** | Security events | Profile updates (optional) | Routine operations |

---

**Last Updated:** October 26, 2025  
**Version:** 1.0  
**System:** Magic Auth Multi-Project Authentication
