# Audit Log System - Usage Guide

**Magic Auth System - Practical Implementation Guide**

---

## Quick Start

### Basic Setup

#### 1. Install Middleware (Required)
```python
# In src/main.py
from fastapi import FastAPI
from src.middleware.activity_logging import ActivityLoggingMiddleware

app = FastAPI()

# Add middleware to capture IP and user agent
app.add_middleware(ActivityLoggingMiddleware)
```

#### 2. Import ActivityLogger
```python
from src.Util.activity_logger import ActivityLogger, ActivityType
```

#### 3. Log Activities
```python
# In your route handler
ActivityLogger.log_user_update(
    user_id=current_user.id,
    target_user_id=target_user_hash,
    changes={"email": "new@example.com"}
)
```

---

## Logging Patterns

### Pattern 1: Automatic Context (Recommended)

With middleware installed, IP and user agent are automatically captured:

```python
from src.Util.activity_logger import ActivityLogger

@router.post("/projects")
async def create_project(
    project_name: str,
    credentials: HTTPAuthorizationCredentials = Depends(security)
):
    # Your business logic
    project = create_new_project(project_name)
    
    # Log activity - IP and user agent automatically included
    ActivityLogger.log_project_creation(
        user_id=credentials.user_id,
        project_id=project.id,
        project_name=project_name
    )
    
    return {"status": "success"}
```

### Pattern 2: Manual Context

If not using middleware or need to override:

```python
ActivityLogger.log_activity(
    user_id="usr-123",
    activity_type=ActivityType.PROJECT_UPDATE.value,
    details={"changes": {"name": "New Name"}},
    project_id="prj-456",
    ip_address="192.168.1.100",        # Manual IP
    user_agent="Mozilla/5.0 ..."       # Manual user agent
)
```

### Pattern 3: Context Manager (For Complex Operations)

```python
from src.Util.activity_logger import LogActivity, ActivityType

async def update_user_and_permissions(user_id: str, data: dict):
    with LogActivity(
        user_id=current_user.id,
        activity_type=ActivityType.USER_UPDATE,
        target_user_id=user_id,
        auto_log=True
    ) as log:
        # Perform updates
        updated_user = update_user(user_id, data)
        updated_perms = update_permissions(user_id, data.permissions)
        
        # Add details to log
        log.add_details({
            "updated_fields": list(data.keys()),
            "permission_changes": updated_perms
        })
        
        # Log automatically created on success
        return updated_user
```

### Pattern 4: Decorator-Based (Endpoint-Wide)

```python
from src.Util.activity_logger import log_endpoint_activity, ActivityType

@router.put("/users/{user_hash}")
@log_endpoint_activity(
    activity_type=ActivityType.USER_UPDATE,
    extract_details=lambda *args, **kwargs: {
        "user_hash": kwargs.get("user_hash")
    }
)
async def update_user_endpoint(
    user_hash: str,
    data: UpdateUserRequest,
    current_user = Depends(get_current_user)
):
    # Your logic here
    # Activity automatically logged on success
    return updated_user
```

---

## When to Log: Decision Tree

### ✅ ALWAYS LOG (Required)

#### Root & Admin Actions
```python
# User management
if action in ["create_user", "delete_user", "change_user_type", "change_user_status"]:
    ActivityLogger.log_* (...)  # REQUIRED

# Project management  
if action in ["create_project", "delete_project", "transfer_ownership"]:
    ActivityLogger.log_* (...)  # REQUIRED

# Group management
if action in ["create_group", "delete_group", "assign_user_to_group"]:
    ActivityLogger.log_* (...)  # REQUIRED

# Permission management
if action in ["grant_permission", "revoke_permission", "assign_role"]:
    ActivityLogger.log_* (...)  # REQUIRED

# Bulk operations
if action.startswith("bulk_"):
    ActivityLogger.log_* (...)  # REQUIRED
```

#### Security-Critical Actions
```python
# Authentication
if action in ["login", "logout", "login_failed", "password_reset"]:
    ActivityLogger.log_* (...)  # REQUIRED

# Security alerts
if suspicious_activity_detected or security_alert:
    ActivityLogger.log_* (...)  # REQUIRED
```

### ❌ NEVER LOG (Excluded)

#### High-Frequency Read Operations
```python
# DON'T LOG THESE
if action in [
    "validate_session",           # Called every request
    "check_permission",           # Called multiple times per request
    "verify_token",               # Called every request
    "get_user_profile",           # Read operation
    "list_projects",              # Read operation
    "search_users",               # Read operation
    "view_permissions"            # Read operation
]:
    # NO LOGGING - too frequent and not state-changing
    pass
```

#### Background System Operations
```python
# DON'T LOG THESE
if action in [
    "health_check",
    "session_cleanup",            # Automatic maintenance
    "cache_refresh",              # Internal operation
    "metrics_collection",         # System monitoring
    "heartbeat"
]:
    # NO LOGGING - system maintenance
    pass
```

### 🤔 OPTIONAL LOG (Use Judgment)

#### Consumer Self-Service Actions
```python
# Optional - configure based on requirements
if action in [
    "update_own_profile",         # Consumer updates their info
    "change_own_password",        # Consumer password change
    "view_own_projects"           # Consumer viewing their access
]:
    # OPTIONAL LOGGING - low security impact
    if AUDIT_CONSUMER_ACTIONS:  # Configuration flag
        ActivityLogger.log_* (...)
```

---

## Common Use Cases

### Use Case 1: Creating a User (Admin)

```python
@router.post("/admin/users")
@require_role("admin")
async def create_user(
    data: CreateUserRequest,
    current_user = Depends(get_current_admin)
):
    # Create user in database
    new_user = db_create_user(
        username=data.username,
        email=data.email,
        user_type=data.user_type,
        created_by=current_user.id
    )
    
    # ✅ LOG THIS - Admin creating user
    ActivityLogger.log_activity(
        user_id=current_user.id,
        activity_type=ActivityType.USER_REGISTRATION.value,
        details={
            "username": data.username,
            "user_type": data.user_type,
            "email": data.email,
            "created_by_type": current_user.user_type
        },
        target_user_id=new_user.id
    )
    
    return {"user": new_user, "status": "created"}
```

### Use Case 2: Changing User Status

```python
@router.put("/admin/users/{user_hash}/status")
@require_role("admin")
async def change_user_status(
    user_hash: str,
    new_status: bool,
    current_user = Depends(get_current_admin)
):
    # Get user
    user = get_user_by_hash(user_hash)
    old_status = user.is_active
    
    # Update status
    update_user_status(user.id, new_status)
    
    # ✅ LOG THIS - Security-critical status change
    ActivityLogger.log_user_status_change(
        user_id=current_user.id,
        target_user_id=user.id,
        new_status="active" if new_status else "inactive",
        metadata={
            "old_status": "active" if old_status else "inactive",
            "reason": "admin_action"
        }
    )
    
    return {"status": "updated"}
```

### Use Case 3: Deleting a Project (Root Only)

```python
@router.delete("/admin/projects/{project_hash}")
@require_role("root")  # Only root can delete
async def delete_project(
    project_hash: str,
    current_user = Depends(get_current_root)
):
    # Get project details before deletion
    project = get_project_by_hash(project_hash)
    member_count = count_project_members(project.id)
    
    # Delete project
    db_delete_project(project.id)
    
    # ✅ LOG THIS - Critical destructive action
    ActivityLogger.log_project_delete(
        user_id=current_user.id,
        project_id=project.id,
        project_name=project.project_name,
        metadata={
            "member_count": member_count,
            "deletion_reason": "admin_request",
            "deleted_by_username": current_user.username
        }
    )
    
    return {"status": "deleted"}
```

### Use Case 4: Bulk Role Assignment

```python
@router.post("/admin/bulk/assign-roles")
@require_role("admin")
async def bulk_assign_roles(
    data: BulkRoleAssignmentRequest,
    current_user = Depends(get_current_admin)
):
    successful = 0
    failed = 0
    
    for user_id in data.user_ids:
        try:
            assign_role_to_user(user_id, data.role_id)
            successful += 1
        except Exception as e:
            failed += 1
    
    # ✅ LOG THIS - Bulk operation with high impact
    ActivityLogger.log_bulk_role_assignment(
        user_id=current_user.id,
        count=successful,
        metadata={
            "role_id": data.role_id,
            "target_count": len(data.user_ids),
            "successful": successful,
            "failed": failed
        }
    )
    
    return {"successful": successful, "failed": failed}
```

### Use Case 5: Permission Grant

```python
@router.post("/admin/permissions/grant")
@require_role("admin")
async def grant_permission(
    data: GrantPermissionRequest,
    current_user = Depends(get_current_admin)
):
    # Grant permission
    grant_permission_to_user(
        user_id=data.user_id,
        permission_id=data.permission_id,
        project_id=data.project_id
    )
    
    # ✅ LOG THIS - Security-critical permission change
    ActivityLogger.log_permission_grant(
        user_id=current_user.id,
        target_user_id=data.user_id,
        permission=data.permission_name,
        project_id=data.project_id,
        metadata={
            "permission_id": data.permission_id,
            "grant_reason": data.reason
        }
    )
    
    return {"status": "granted"}
```

### Use Case 6: Failed Login (Auto-Detected)

```python
@router.post("/auth/login")
async def login(data: LoginRequest, request: Request):
    user = authenticate_user(data.username, data.password)
    
    if not user:
        # ✅ LOG THIS - Security monitoring
        ActivityLogger.log_activity(
            user_id=None,  # No user yet
            activity_type=ActivityType.USER_LOGIN_FAILED.value,
            details={
                "attempted_username": data.username,
                "reason": "invalid_credentials",
                "timestamp": datetime.utcnow().isoformat()
            },
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent")
        )
        
        raise HTTPException(status_code=401, detail="Invalid credentials")
    
    # ✅ LOG THIS - Successful login
    ActivityLogger.log_user_login(
        user_id=user.id,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent")
    )
    
    return {"token": create_token(user)}
```

### Use Case 7: Session Validation (DON'T LOG)

```python
@router.get("/validate-session")
async def validate_session(token: str):
    # ❌ DON'T LOG THIS - Called every request
    session = validate_session_token(token)
    
    if not session:
        raise HTTPException(status_code=401)
    
    # NO LOGGING - too frequent
    return {"valid": True, "user": session.user}
```

### Use Case 8: Permission Check (DON'T LOG)

```python
def check_user_has_permission(user_id: str, permission: str, project_id: str) -> bool:
    # ❌ DON'T LOG THIS - Called multiple times per request
    has_perm = db_check_permission(user_id, permission, project_id)
    
    # NO LOGGING - high frequency operation
    return has_perm
```

### Use Case 9: System Event (Automated)

```python
def perform_database_backup():
    start_time = datetime.utcnow()
    
    # Perform backup
    backup_result = backup_database()
    
    duration = (datetime.utcnow() - start_time).total_seconds()
    
    # ✅ LOG THIS - Important system event
    ActivityLogger.log_system_event(
        event="database_backup_completed",
        details={
            "backup_size_gb": backup_result.size_gb,
            "duration_seconds": duration,
            "backup_location": backup_result.path,
            "success": backup_result.success
        }
    )
```

### Use Case 10: Security Alert (Automated)

```python
def detect_brute_force(username: str, ip_address: str) -> None:
    # Check for multiple failed attempts
    failed_attempts = count_failed_logins(username, minutes=15)
    
    if failed_attempts >= 5:
        # ✅ LOG THIS - Critical security alert
        ActivityLogger.log_activity(
            user_id=None,  # System-generated
            activity_type=ActivityType.SECURITY_ALERT.value,
            details={
                "alert_type": "brute_force_detected",
                "target_username": username,
                "attempt_count": failed_attempts,
                "time_window_minutes": 15
            },
            ip_address=ip_address,
            metadata={
                "severity": "critical",
                "requires_investigation": True
            }
        )
        
        # Take action (block IP, lock account, etc.)
        block_ip_address(ip_address)
```

---

## Filtering Examples

### Example 1: Route-Level Filtering

```python
# Define routes that should NOT be logged
NO_LOG_ROUTES = [
    "/validate-session",
    "/check-permission",
    "/health",
    "/metrics",
    "/api/v1/users/profile"  # GET only
]

@app.middleware("http")
async def audit_filter_middleware(request: Request, call_next):
    # Skip logging for excluded routes
    if request.url.path in NO_LOG_ROUTES:
        request.state.skip_audit = True
    
    response = await call_next(request)
    return response

# In route handler
if not getattr(request.state, 'skip_audit', False):
    ActivityLogger.log_* (...)
```

### Example 2: User Type Filtering

```python
def should_log_action(user_type: str, action: str) -> bool:
    """Determine if action should be logged based on user type"""
    
    # Always log root and admin actions
    if user_type in ["root", "admin"]:
        return True
    
    # Log consumer actions only if security-critical
    if user_type == "consumer":
        security_actions = [
            "user_login",
            "user_logout",
            "user_login_failed",
            "user_password_reset"
        ]
        return action in security_actions
    
    return False

# Usage
if should_log_action(current_user.user_type, "user_update"):
    ActivityLogger.log_user_update(...)
```

### Example 3: Operation Type Filtering

```python
def is_state_changing_operation(method: str, endpoint: str) -> bool:
    """Determine if operation changes state"""
    
    # Read operations (GET) - don't log
    if method == "GET":
        return False
    
    # Write operations (POST, PUT, DELETE, PATCH) - log
    if method in ["POST", "PUT", "DELETE", "PATCH"]:
        return True
    
    return False

# Usage
if is_state_changing_operation(request.method, request.url.path):
    ActivityLogger.log_* (...)
```

---

## Querying Audit Logs

### Example 1: Get Recent Activity

```python
from src.Util.activity_logger import ActivityLogger

# Get last 50 activities
recent_logs = ActivityLogger.get_recent_activity(
    limit=50,
    offset=0,
    days=7
)

for log in recent_logs:
    print(f"{log['username']} performed {log['activity_name']} at {log['created_at']}")
```

### Example 2: Filter by User

```python
# Get all activities by specific user
user_activities = ActivityLogger.get_recent_activity(
    limit=100,
    user_id="usr-123",
    days=30
)
```

### Example 3: Filter by Project

```python
# Get all activities for specific project
project_activities = ActivityLogger.get_recent_activity(
    limit=100,
    project_id="prj-456",
    days=30
)
```

### Example 4: Filter by Activity Type

```python
# Get all failed login attempts
failed_logins = ActivityLogger.get_recent_activity(
    limit=100,
    activity_type="user_login_failed",
    days=7
)

# Security monitoring
if len(failed_logins) > 50:
    alert_security_team("High number of failed login attempts")
```

### Example 5: Count Activities

```python
# Count total activities
total = ActivityLogger.count_activity_logs(days=30)

# Count by user
user_activity_count = ActivityLogger.count_activity_logs(
    user_id="usr-123",
    days=30
)

# Count by type
failed_login_count = ActivityLogger.count_activity_logs(
    activity_type="user_login_failed",
    days=1
)
```

### Example 6: Get Activity Catalog

```python
# Get all activity types
all_activities = ActivityLogger.get_activity_catalog()

# Get by category
auth_activities = ActivityLogger.get_activity_catalog(category="authentication")

for activity in auth_activities:
    print(f"{activity['activity_code']}: {activity['activity_name']}")
```

---

## Best Practices

### 1. Log at the Right Granularity

✅ **Good:**
```python
# Log meaningful state changes
ActivityLogger.log_user_update(
    user_id=admin.id,
    target_user_id=user.id,
    changes={
        "email": {"old": "old@example.com", "new": "new@example.com"},
        "username": {"old": "oldname", "new": "newname"}
    }
)
```

❌ **Bad:**
```python
# Too granular - logging every field access
ActivityLogger.log_activity(..., details="Accessed email field")
ActivityLogger.log_activity(..., details="Accessed username field")
```

### 2. Include Relevant Context

✅ **Good:**
```python
ActivityLogger.log_project_delete(
    user_id=admin.id,
    project_id=project.id,
    project_name=project.project_name,
    metadata={
        "member_count": 45,
        "deletion_reason": "project_ended",
        "archived_first": True
    }
)
```

❌ **Bad:**
```python
ActivityLogger.log_project_delete(
    user_id=admin.id,
    project_id=project.id,
    project_name=project.project_name
)
# Missing important context
```

### 3. Never Log Sensitive Data

✅ **Good:**
```python
ActivityLogger.log_user_password_reset(
    user_id=admin.id,
    target_user_id=user.id,
    metadata={"reset_type": "admin_initiated"}
)
```

❌ **Bad:**
```python
ActivityLogger.log_activity(
    ...,
    details={
        "new_password": "plaintext_password",  # NEVER DO THIS!
        "old_password_hash": "hash_value"      # Don't log this either
    }
)
```

### 4. Use Specific Methods Over Generic

✅ **Good:**
```python
ActivityLogger.log_project_creation(
    user_id=user.id,
    project_id=project.id,
    project_name=project.project_name
)
```

❌ **Less Good:**
```python
ActivityLogger.log_activity(
    user_id=user.id,
    activity_type="project_creation",
    details={"project_name": project.project_name},
    project_id=project.id
)
```

### 5. Handle Logging Failures Gracefully

✅ **Good:**
```python
try:
    # Business logic
    project = create_project(data)
    
    # Try to log, but don't fail operation if logging fails
    try:
        ActivityLogger.log_project_creation(...)
    except Exception as e:
        logger.error(f"Failed to log activity: {e}")
        # Operation still succeeds
    
    return {"project": project}
    
except Exception as e:
    # Business logic failure
    raise HTTPException(status_code=500, detail=str(e))
```

❌ **Bad:**
```python
# Business logic
project = create_project(data)

# If this fails, entire operation fails
ActivityLogger.log_project_creation(...)

return {"project": project}
```

### 6. Log After Success, Not Before

✅ **Good:**
```python
# Perform operation
result = update_user(user_id, data)

# Log only if successful
if result:
    ActivityLogger.log_user_update(...)

return result
```

❌ **Bad:**
```python
# Log before operation
ActivityLogger.log_user_update(...)

# Operation might fail
result = update_user(user_id, data)
return result
```

### 7. Use Structured Details

✅ **Good:**
```python
ActivityLogger.log_activity(
    ...,
    details={
        "action": "bulk_update",
        "updated_fields": ["status", "role"],
        "target_count": 50,
        "success_count": 48,
        "failure_count": 2
    }
)
```

❌ **Bad:**
```python
ActivityLogger.log_activity(
    ...,
    details="Updated 50 users, 48 succeeded, 2 failed"  # Unstructured string
)
```

---

## Configuration

### Environment Variables

```bash
# Enable/disable consumer action logging
AUDIT_CONSUMER_ACTIONS=false

# Enable/disable read operation logging
AUDIT_READ_OPERATIONS=false

# Enable/disable high-frequency logging
AUDIT_HIGH_FREQUENCY=false

# Log retention period (days)
AUDIT_LOG_RETENTION_DAYS=365

# Enable async logging
AUDIT_ASYNC_LOGGING=false
```

### Application Configuration

```python
# In config.py
class AuditConfig:
    # Log consumer actions
    LOG_CONSUMER_ACTIONS: bool = False
    
    # Log read operations
    LOG_READ_OPERATIONS: bool = False
    
    # Log API access
    LOG_API_ACCESS: bool = False
    
    # Minimum severity to log
    MIN_SEVERITY: str = "info"  # info, warning, critical
    
    # User types to log
    LOG_USER_TYPES: List[str] = ["root", "admin"]
```

---

## Troubleshooting

### Issue: Logs Not Appearing

**Check:**
1. Middleware installed? `app.add_middleware(ActivityLoggingMiddleware)`
2. Activity in catalog? `SELECT * FROM activity_catalog WHERE activity_code = '...'`
3. Activity is_active? Check `is_active = TRUE` in catalog
4. Database connection working? Check error logs

**Solution:**
```python
# Test logging directly
result = ActivityLogger.log_activity(
    user_id="test-user",
    activity_type="user_login",
    details="Test log"
)
print(f"Log successful: {result}")
```

### Issue: Missing IP Address/User Agent

**Check:**
1. Middleware order (should be early)
2. Behind proxy? Check X-Forwarded-For headers
3. Manual logging? Provide IP/user agent explicitly

**Solution:**
```python
# Verify middleware is capturing context
from src.Util.activity_logger import _request_context
print(f"Current context: {_request_context.get()}")
```

### Issue: Performance Impact

**Check:**
1. Logging high-frequency operations? Filter them out
2. Logging read operations? Disable them
3. Database indexes? Ensure proper indexing

**Solution:**
```python
# Add route-level filtering
if request.method != "GET" and not is_excluded_route(request.url.path):
    ActivityLogger.log_* (...)
```

---

**Last Updated:** October 26, 2025  
**Version:** 1.0  
**System:** Magic Auth Multi-Project Authentication
