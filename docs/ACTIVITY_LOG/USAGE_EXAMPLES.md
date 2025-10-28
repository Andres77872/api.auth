# Activity Logging Usage Examples

Practical examples of using the activity logging system in various scenarios.

## Table of Contents

1. [Authentication Logging](#authentication-logging)
2. [User Management](#user-management)
3. [Project Operations](#project-operations)
4. [Permission Management](#permission-management)
5. [Bulk Operations](#bulk-operations)
6. [Querying & Analytics](#querying--analytics)
7. [Security Monitoring](#security-monitoring)
8. [Compliance Reporting](#compliance-reporting)

---

## Authentication Logging

### Example 1: Login Success

```python
from fastapi import APIRouter, HTTPException, Request, Depends
from src.Util.activity_logger import ActivityLogger

@router.post("/v1/auth/login")
async def login(request: Request, credentials: LoginRequest):
    """Handle user login with activity logging"""
    
    # Authenticate user
    user = await authenticate_user(credentials.username, credentials.password)
    
    if not user:
        # Log failed login attempt
        await ActivityLogger.log_failed_login(
            username=credentials.username,
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent"),
            reason="Invalid credentials"
        )
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # Check if user is active
    if not user.is_active:
        await ActivityLogger.log_failed_login(
            username=credentials.username,
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent"),
            reason="Account deactivated"
        )
        raise HTTPException(status_code=403, detail="Account deactivated")
    
    # Create session
    session = await create_user_session(
        user_id=user.id,
        project_id=credentials.project_id
    )
    
    # Log successful login
    await ActivityLogger.log_login(
        user_id=user.id,
        username=user.username,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent"),
        project_id=credentials.project_id,
        login_method="password"
    )
    
    return {
        "token": session.session_token,
        "user": user.to_dict(),
        "expires_at": session.expires_at
    }
```

### Example 2: Logout

```python
@router.post("/v1/auth/logout")
async def logout(
    request: Request,
    current_user: User = Depends(get_current_user),
    session_id: str = Depends(get_session_id)
):
    """Handle user logout"""
    
    # Deactivate session (triggers automatic logging)
    await deactivate_session(session_id)
    
    # Optionally add more context
    await ActivityLogger.log_activity(
        user_id=current_user.id,
        activity_code="user_logout",
        details=f"User {current_user.username} logged out",
        metadata={
            "logout_type": "manual",
            "session_duration_minutes": calculate_session_duration(session_id)
        }
    )
    
    return {"status": "logged out"}
```

### Example 3: Failed Login Rate Limiting

```python
from collections import defaultdict
from datetime import datetime, timedelta

# In-memory store for failed attempts (use Redis in production)
failed_attempts = defaultdict(list)

@router.post("/v1/auth/login")
async def login_with_rate_limit(request: Request, credentials: LoginRequest):
    """Login with rate limiting on failed attempts"""
    
    client_ip = request.client.host
    
    # Check recent failed attempts
    cutoff_time = datetime.now() - timedelta(minutes=15)
    recent_fails = [t for t in failed_attempts[client_ip] if t > cutoff_time]
    
    if len(recent_fails) >= 5:
        # Log security alert
        await ActivityLogger.log_activity(
            user_id=None,
            activity_code="security_alert",
            details=f"Rate limit exceeded for IP: {client_ip}",
            ip_address=client_ip,
            metadata={
                "failed_attempts": len(recent_fails),
                "time_window_minutes": 15,
                "attempted_username": credentials.username
            }
        )
        raise HTTPException(status_code=429, detail="Too many failed attempts")
    
    # Proceed with authentication...
    user = await authenticate_user(credentials.username, credentials.password)
    
    if not user:
        failed_attempts[client_ip].append(datetime.now())
        await ActivityLogger.log_failed_login(...)
        raise HTTPException(status_code=401)
    
    # Clear failed attempts on success
    failed_attempts[client_ip] = []
    
    await ActivityLogger.log_login(...)
    return {...}
```

---

## User Management

### Example 4: User Registration (Automatic)

```python
@router.post("/v1/users")
async def create_user(
    user_data: CreateUserRequest,
    current_admin: User = Depends(get_admin_user)
):
    """Create new user - automatic activity logging via trigger"""
    
    # Generate user hash
    user_hash = generate_user_hash()
    
    # Create user record
    new_user = User(
        id=generate_id(),
        user_hash=user_hash,
        username=user_data.username,
        email=user_data.email,
        password_hash=hash_password(user_data.password),
        user_type=user_data.user_type,
        created_by=current_admin.id
    )
    
    db.add(new_user)
    db.commit()
    
    # ✅ Activity log automatically created by trigger!
    # No manual logging needed for basic user creation
    
    return {"user": new_user.to_dict()}
```

### Example 5: User Type Change (Automatic with Context)

```python
@router.patch("/v1/users/{user_hash}/type")
async def change_user_type(
    user_hash: str,
    type_change: UserTypeChangeRequest,
    current_admin: User = Depends(get_root_user)
):
    """Change user type with context logging"""
    
    target_user = await get_user_by_hash(user_hash)
    old_type = target_user.user_type
    
    # Update user type
    target_user.user_type = type_change.new_type
    db.commit()
    
    # ✅ Trigger logs user_type_changed automatically
    
    # ➕ Add business context
    await ActivityLogger.log_activity(
        user_id=current_admin.id,
        activity_code="user_type_changed",
        details=f"User type changed from {old_type} to {type_change.new_type} for {target_user.username}. Reason: {type_change.reason}",
        target_user_id=target_user.id,
        metadata={
            "old_type": old_type,
            "new_type": type_change.new_type,
            "reason": type_change.reason,
            "approved_by": type_change.approved_by
        }
    )
    
    return {"status": "updated", "user": target_user.to_dict()}
```

---

## Project Operations

### Example 6: Project Creation (Automatic)

```python
@router.post("/v1/projects")
async def create_project(
    project_data: CreateProjectRequest,
    current_user: User = Depends(get_current_user)
):
    """Create project - automatic logging"""
    
    project = Project(
        id=generate_id(),
        project_hash=generate_project_hash(),
        project_name=project_data.name,
        project_description=project_data.description,
        owner_id=current_user.id,
        created_by=current_user.id
    )
    
    db.add(project)
    db.commit()
    
    # ✅ Activity log created by trigger
    
    return {"project": project.to_dict()}
```

### Example 7: Project Archive with Notification

```python
@router.post("/v1/projects/{project_hash}/archive")
async def archive_project(
    project_hash: str,
    archive_request: ArchiveProjectRequest,
    current_user: User = Depends(get_admin_user)
):
    """Archive project with notifications"""
    
    project = await get_project_by_hash(project_hash)
    
    # Get all project members for notification
    members = await get_project_members(project.id)
    
    # Archive project
    project.archived = True
    project.archived_by = current_user.id
    project.archived_at = datetime.now()
    db.commit()
    
    # ✅ Trigger logs project_archived
    
    # Send notifications
    for member in members:
        await send_notification(
            user_id=member.id,
            message=f"Project {project.project_name} has been archived"
        )
    
    # ➕ Log with notification context
    await ActivityLogger.log_activity(
        user_id=current_user.id,
        activity_code="project_archived",
        details=f"Project archived and {len(members)} members notified",
        project_id=project.id,
        metadata={
            "reason": archive_request.reason,
            "members_notified": len(members),
            "can_restore": True
        }
    )
    
    return {"status": "archived", "members_notified": len(members)}
```

---

## Permission Management

### Example 8: Role Assignment (Automatic)

```python
@router.post("/v1/users/{user_hash}/role")
async def assign_role(
    user_hash: str,
    role_assignment: RoleAssignmentRequest,
    current_admin: User = Depends(get_admin_user)
):
    """Assign role to user"""
    
    target_user = await get_user_by_hash(user_hash)
    role = await get_role_by_hash(role_assignment.role_hash)
    
    # Assign role
    target_user.role_id = role.id
    db.commit()
    
    # ✅ Trigger logs automatically (users table UPDATE)
    # But we should also log to permission_audit_log
    
    await log_permission_change(
        action_type="role_assignment",
        target_user_id=target_user.id,
        performed_by=current_admin.id,
        old_values={"role_id": target_user.role_id},
        new_values={"role_id": role.id},
        table_name="users",
        record_id=target_user.id
    )
    
    return {"status": "role assigned"}
```

### Example 9: Permission Group Assignment to User Group

```python
@router.post("/v1/groups/{group_hash}/permissions")
async def assign_permissions_to_group(
    group_hash: str,
    assignment: PermissionGroupAssignmentRequest,
    current_admin: User = Depends(get_admin_user)
):
    """Assign permission group to user group"""
    
    user_group = await get_user_group_by_hash(group_hash)
    perm_group = await get_permission_group_by_hash(assignment.permission_group_hash)
    
    # Create assignment
    assignment_record = UserGroupPermissionGroup(
        id=generate_id(),
        user_group_id=user_group.id,
        permission_group_id=perm_group.id,
        assigned_by=current_admin.id
    )
    
    db.add(assignment_record)
    db.commit()
    
    # ✅ Trigger logs permission_group_assigned
    
    # Get affected users count
    affected_users = await count_group_members(user_group.id)
    
    # ➕ Add impact context
    await ActivityLogger.log_activity(
        user_id=current_admin.id,
        activity_code="permission_group_assigned",
        details=f"Permission group '{perm_group.group_name}' assigned to group '{user_group.group_name}' affecting {affected_users} users",
        user_group_id=user_group.id,
        metadata={
            "permission_group_name": perm_group.group_name,
            "user_group_name": user_group.group_name,
            "affected_users_count": affected_users
        }
    )
    
    return {"status": "assigned", "affected_users": affected_users}
```

---

## Bulk Operations

### Example 10: Bulk User Update

```python
@router.post("/v1/admin/users/bulk-update")
async def bulk_update_users(
    bulk_request: BulkUserUpdateRequest,
    current_admin: User = Depends(get_admin_user)
):
    """Update multiple users at once"""
    
    results = {
        "success": 0,
        "failed": 0,
        "errors": []
    }
    
    for user_hash in bulk_request.user_hashes:
        try:
            user = await get_user_by_hash(user_hash)
            
            # Apply updates
            if bulk_request.updates.get("is_active") is not None:
                user.is_active = bulk_request.updates["is_active"]
            if bulk_request.updates.get("user_type"):
                user.user_type = bulk_request.updates["user_type"]
            
            db.commit()
            results["success"] += 1
            
            # ✅ Each update triggers automatic logging
            
        except Exception as e:
            results["failed"] += 1
            results["errors"].append({"user_hash": user_hash, "error": str(e)})
    
    # ➕ Log bulk operation summary
    await ActivityLogger.log_bulk_operation(
        user_id=current_admin.id,
        operation_type="bulk_user_update",
        target_count=len(bulk_request.user_hashes),
        success_count=results["success"],
        details=f"Bulk updated {results['success']} of {len(bulk_request.user_hashes)} users",
        metadata={
            "updates_applied": bulk_request.updates,
            "failed_count": results["failed"],
            "error_sample": results["errors"][:5]  # First 5 errors
        }
    )
    
    return results
```

### Example 11: Bulk Role Assignment

```python
@router.post("/v1/admin/roles/bulk-assign")
async def bulk_assign_roles(
    bulk_request: BulkRoleAssignmentRequest,
    current_admin: User = Depends(get_root_user)
):
    """Assign role to multiple users"""
    
    role = await get_role_by_hash(bulk_request.role_hash)
    
    success_count = 0
    failed_users = []
    
    for user_hash in bulk_request.user_hashes:
        try:
            user = await get_user_by_hash(user_hash)
            user.role_id = role.id
            db.commit()
            success_count += 1
        except Exception as e:
            failed_users.append(user_hash)
    
    # Log bulk operation
    await ActivityLogger.log_bulk_operation(
        user_id=current_admin.id,
        operation_type="bulk_role_assignment",
        target_count=len(bulk_request.user_hashes),
        success_count=success_count,
        details=f"Assigned role '{role.role_name}' to {success_count} users",
        metadata={
            "role_name": role.role_name,
            "role_hash": role.role_hash,
            "failed_users": failed_users
        }
    )
    
    return {
        "success": success_count,
        "failed": len(failed_users),
        "failed_users": failed_users
    }
```

---

## Querying & Analytics

### Example 12: User Activity Dashboard

```python
@router.get("/v1/users/{user_hash}/activity")
async def get_user_activity(
    user_hash: str,
    days: int = 30,
    current_user: User = Depends(get_current_user)
):
    """Get user activity summary for dashboard"""
    
    user = await get_user_by_hash(user_hash)
    
    # Get activity summary
    db = DatabaseConfig.get_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.callproc('sp_get_user_activity_summary', [user.id, days])
    
    activities = []
    for result in cursor.stored_results():
        activities = result.fetchall()
    
    # Get recent logs
    cursor.callproc('sp_get_activity_logs', [50, 0, user.id, None, None, days])
    
    recent_logs = []
    for result in cursor.stored_results():
        recent_logs = result.fetchall()
    
    cursor.close()
    db.close()
    
    return {
        "user": user.to_dict(),
        "period_days": days,
        "summary": activities,
        "recent_activities": recent_logs,
        "total_activities": sum(a['activity_count'] for a in activities)
    }
```

### Example 13: Project Activity Report

```python
@router.get("/v1/projects/{project_hash}/activity-report")
async def get_project_activity_report(
    project_hash: str,
    days: int = 30,
    current_admin: User = Depends(get_admin_user)
):
    """Generate project activity report"""
    
    project = await get_project_by_hash(project_hash)
    
    db = DatabaseConfig.get_connection()
    cursor = db.cursor(dictionary=True)
    
    # Get statistics
    cursor.callproc('sp_get_activity_stats', [project.id, days])
    stats = []
    for result in cursor.stored_results():
        stats = result.fetchall()
    
    # Get all activities for this project
    cursor.callproc('sp_get_activity_logs', [1000, 0, None, project.id, None, days])
    all_activities = []
    for result in cursor.stored_results():
        all_activities = result.fetchall()
    
    # Analyze by user
    user_activity = {}
    for activity in all_activities:
        user_id = activity.get('user_id')
        if user_id:
            user_activity[user_id] = user_activity.get(user_id, 0) + 1
    
    # Get top contributors
    top_contributors = sorted(
        user_activity.items(),
        key=lambda x: x[1],
        reverse=True
    )[:10]
    
    cursor.close()
    db.close()
    
    return {
        "project": project.to_dict(),
        "period_days": days,
        "statistics": stats,
        "total_activities": len(all_activities),
        "top_contributors": [
            {"user_id": uid, "activity_count": count}
            for uid, count in top_contributors
        ],
        "activities_by_severity": {
            "info": len([a for a in all_activities if a['severity_level'] == 'info']),
            "warning": len([a for a in all_activities if a['severity_level'] == 'warning']),
            "critical": len([a for a in all_activities if a['severity_level'] == 'critical'])
        }
    }
```

---

## Security Monitoring

### Example 14: Security Events Monitor

```python
@router.get("/v1/admin/security/events")
async def get_security_events(
    hours: int = 24,
    limit: int = 100,
    current_admin: User = Depends(get_root_user)
):
    """Get recent security events for monitoring"""
    
    db = DatabaseConfig.get_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.callproc('sp_get_recent_security_events', [hours, limit])
    
    security_events = []
    for result in cursor.stored_results():
        security_events = result.fetchall()
    
    cursor.close()
    db.close()
    
    # Group by event type
    events_by_type = {}
    for event in security_events:
        event_type = event['activity_type']
        if event_type not in events_by_type:
            events_by_type[event_type] = []
        events_by_type[event_type].append(event)
    
    # Identify anomalies
    anomalies = []
    
    # Check for multiple failed logins from same IP
    failed_logins = events_by_type.get('user_login_failed', [])
    ip_failures = {}
    for event in failed_logins:
        ip = event.get('ip_address')
        if ip:
            ip_failures[ip] = ip_failures.get(ip, 0) + 1
    
    for ip, count in ip_failures.items():
        if count >= 5:
            anomalies.append({
                "type": "multiple_failed_logins",
                "ip_address": ip,
                "count": count,
                "severity": "high"
            })
    
    return {
        "period_hours": hours,
        "total_events": len(security_events),
        "events_by_type": {k: len(v) for k, v in events_by_type.items()},
        "anomalies": anomalies,
        "recent_events": security_events[:20]  # Most recent 20
    }
```

---

## Compliance Reporting

### Example 15: Generate Compliance Report

```python
@router.get("/v1/admin/compliance/report")
async def generate_compliance_report(
    start_date: str,
    end_date: str,
    current_admin: User = Depends(get_root_user)
):
    """Generate compliance audit report"""
    
    db = DatabaseConfig.get_connection()
    cursor = db.cursor(dictionary=True)
    
    # Query all critical activities
    query = """
        SELECT 
            al.*,
            u.username as performed_by_username,
            tu.username as target_username,
            p.project_name,
            ac.activity_name,
            ac.activity_category
        FROM activity_logs al
        LEFT JOIN users u ON al.user_id = u.id
        LEFT JOIN users tu ON al.target_user_id = tu.id
        LEFT JOIN projects p ON al.project_id = p.id
        LEFT JOIN activity_catalog ac ON al.activity_catalog_id = ac.id
        WHERE al.created_at BETWEEN %s AND %s
          AND al.severity_level IN ('warning', 'critical')
        ORDER BY al.created_at DESC
    """
    
    cursor.execute(query, [start_date, end_date])
    critical_activities = cursor.fetchall()
    
    # Group by category
    by_category = {}
    for activity in critical_activities:
        category = activity['activity_category'] or 'unknown'
        if category not in by_category:
            by_category[category] = []
        by_category[category].append(activity)
    
    cursor.close()
    db.close()
    
    return {
        "report_period": {
            "start": start_date,
            "end": end_date
        },
        "total_activities": len(critical_activities),
        "by_category": {k: len(v) for k, v in by_category.items()},
        "activities": critical_activities,
        "summary": {
            "user_deletions": len([a for a in critical_activities if a['activity_type'] == 'user_deleted']),
            "type_changes": len([a for a in critical_activities if a['activity_type'] == 'user_type_changed']),
            "permission_changes": len([a for a in critical_activities if 'permission' in a['activity_type']]),
            "project_deletions": len([a for a in critical_activities if a['activity_type'] == 'project_delete'])
        }
    }
```

---

## Best Practices from Examples

1. **Let Triggers Do The Work** - Don't manually log what triggers already cover
2. **Add Context** - Enhance automatic logs with business context when needed
3. **Log Failures** - Always log authentication failures and security events
4. **Bulk Operations** - Always summarize bulk operations in a single log entry
5. **Include Metadata** - Add relevant metadata for debugging and analysis
6. **Monitor Security** - Regular ly check security events and anomalies
7. **Generate Reports** - Use stored procedures for efficient reporting
8. **Handle Errors Gracefully** - Don't fail requests if logging fails

---

## Testing Your Implementation

```python
import pytest

@pytest.mark.asyncio
async def test_login_logging():
    """Test that login creates activity log"""
    response = await client.post("/v1/auth/login", json={
        "username": "testuser",
        "password": "testpass"
    })
    
    assert response.status_code == 200
    
    # Check activity log created
    logs = await get_recent_activities(activity_code="user_login", days=1)
    assert len(logs) > 0
    assert logs[0]['details'].contains("testuser")

@pytest.mark.asyncio
async def test_failed_login_logging():
    """Test that failed login logs correctly"""
    response = await client.post("/v1/auth/login", json={
        "username": "testuser",
        "password": "wrongpass"
    })
    
    assert response.status_code == 401
    
    # Check failed login logged
    logs = await get_recent_activities(activity_code="user_login_failed", days=1)
    assert len(logs) > 0
```

---

For more details, see the [Implementation Guide](./IMPLEMENTATION_GUIDE.md).
