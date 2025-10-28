# Activity Logging Implementation Guide

This guide walks you through implementing and using the activity logging system in your authentication API.

## Table of Contents

1. [Database Setup](#database-setup)
2. [Trigger Installation](#trigger-installation)
3. [Python Integration](#python-integration)
4. [Querying Activity Logs](#querying-activity-logs)
5. [Best Practices](#best-practices)
6. [Troubleshooting](#troubleshooting)

---

## Database Setup

### Step 1: Install Activity Logging Tables

Run the table creation script to set up the activity logging infrastructure:

```bash
mysql -u your_user -p magic_auth < schemas/tables/08_activity_logging_tables.sql
```

This creates:
- `activity_catalog` - Registry of all activity types
- `activity_logs` - Actual activity log entries
- `permission_audit_log` - Specialized permission change audit

### Step 2: Install Stored Procedures

```bash
mysql -u your_user -p magic_auth < schemas/stored_procedures/11_activity_logging.sql
```

This creates procedures for:
- Logging activities
- Querying logs with filters
- Analytics and reporting
- Cleanup operations

### Step 3: Install Triggers

Install both trigger files to enable automatic logging:

```bash
# Core entity triggers (users, projects, groups)
mysql -u your_user -p magic_auth < schemas/triggers/01_activity_logging_triggers.sql

# Permission/role triggers
mysql -u your_user -p magic_auth < schemas/triggers/02_permission_activity_triggers.sql
```

### Step 4: Verify Installation

```sql
-- Check tables exist
SHOW TABLES LIKE 'activity%';

-- Check activity catalog populated
SELECT COUNT(*) FROM activity_catalog;  -- Should return 40+

-- Check triggers installed
SHOW TRIGGERS FROM magic_auth LIKE 'trg_after_%';  -- Should show multiple triggers

-- Check stored procedures
SHOW PROCEDURE STATUS WHERE Db = 'magic_auth' AND Name LIKE 'sp_%activity%';
```

---

## Trigger Installation

### Understanding Trigger Coverage

The system includes triggers for:

**Core Entities (File: 01_activity_logging_triggers.sql)**
- Users: INSERT, UPDATE, DELETE
- Projects: INSERT, UPDATE, DELETE
- User Groups: INSERT, UPDATE, DELETE
- User Group Members: INSERT, DELETE
- User Group Projects: INSERT, DELETE

**Permission Entities (File: 02_permission_activity_triggers.sql)**
- Roles: INSERT, UPDATE, DELETE
- Permission Groups: INSERT, UPDATE, DELETE
- Permissions: INSERT, UPDATE, DELETE
- Role-Permission Links: INSERT, DELETE
- User-Permission Links: INSERT, DELETE
- Group-Permission Links: INSERT, DELETE
- Sessions: INSERT, UPDATE

### Trigger Behavior

Triggers automatically:
1. Generate unique activity log IDs
2. Look up activity catalog entries
3. Capture old/new values for updates
4. Insert activity logs with metadata
5. Handle NULL values gracefully

### Disabling Triggers (if needed)

```sql
-- Disable specific trigger
DROP TRIGGER IF EXISTS trg_after_user_insert;

-- Re-enable by running trigger file again
SOURCE schemas/triggers/01_activity_logging_triggers.sql;
```

---

## Python Integration

### Create Activity Logger Utility

Create `src/Util/activity_logger.py`:

```python
"""
Activity Logger Utility
Logs user actions to activity_logs table
"""

import uuid
import json
from typing import Optional, Dict, Any
from datetime import datetime

from src.Config.database_config import DatabaseConfig


class ActivityLogger:
    """Utility for logging user activities"""
    
    @staticmethod
    async def log_activity(
        user_id: Optional[str],
        activity_code: str,
        details: str,
        project_id: Optional[str] = None,
        user_group_id: Optional[str] = None,
        target_user_id: Optional[str] = None,
        ip_address: Optional[str] = None,
        user_agent: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Log an activity to the database.
        
        Args:
            user_id: User performing the action
            activity_code: Activity code from catalog
            details: Human-readable description
            project_id: Related project (optional)
            user_group_id: Related user group (optional)
            target_user_id: Target user (optional)
            ip_address: Client IP (optional)
            user_agent: User agent string (optional)
            metadata: Additional context (optional)
            
        Returns:
            True if logged successfully
        """
        try:
            db = DatabaseConfig.get_connection()
            cursor = db.cursor()
            
            activity_log_id = f"act-log-{uuid.uuid4().hex[:16]}"
            metadata_json = json.dumps(metadata) if metadata else None
            
            cursor.callproc('sp_log_activity', [
                activity_log_id,
                user_id,
                activity_code,
                details,
                project_id,
                user_group_id,
                target_user_id,
                ip_address,
                user_agent,
                metadata_json
            ])
            
            db.commit()
            cursor.close()
            db.close()
            
            return True
            
        except Exception as e:
            print(f"Error logging activity: {e}")
            return False
    
    @staticmethod
    async def log_login(
        user_id: str,
        username: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
        project_id: Optional[str] = None,
        login_method: str = "password"
    ):
        """Log successful user login"""
        await ActivityLogger.log_activity(
            user_id=user_id,
            activity_code="user_login",
            details=f"User {username} logged in",
            project_id=project_id,
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={
                "username": username,
                "login_method": login_method
            }
        )
    
    @staticmethod
    async def log_failed_login(
        username: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
        reason: str = "Invalid credentials"
    ):
        """Log failed login attempt"""
        await ActivityLogger.log_activity(
            user_id=None,  # No user ID for failed attempts
            activity_code="user_login_failed",
            details=f"Failed login attempt for: {username}",
            ip_address=ip_address,
            user_agent=user_agent,
            metadata={
                "username": username,
                "reason": reason
            }
        )
    
    @staticmethod
    async def log_bulk_operation(
        user_id: str,
        operation_type: str,
        target_count: int,
        success_count: int,
        details: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """Log bulk operation"""
        activity_code_map = {
            "bulk_role_assignment": "bulk_role_assignment",
            "bulk_group_assignment": "bulk_group_assignment",
            "bulk_user_update": "bulk_user_update",
            "bulk_user_delete": "bulk_user_delete"
        }
        
        activity_code = activity_code_map.get(operation_type, "admin_action")
        
        merged_metadata = metadata or {}
        merged_metadata.update({
            "target_count": target_count,
            "success_count": success_count,
            "error_count": target_count - success_count
        })
        
        await ActivityLogger.log_activity(
            user_id=user_id,
            activity_code=activity_code,
            details=details,
            metadata=merged_metadata
        )
```

### Using in FastAPI Endpoints

#### Example 1: Login Endpoint

```python
from fastapi import APIRouter, HTTPException, Request
from src.Util.activity_logger import ActivityLogger

router = APIRouter()

@router.post("/auth/login")
async def login(request: Request, credentials: LoginRequest):
    try:
        # Authenticate user
        user = await authenticate_user(credentials.username, credentials.password)
        
        if not user:
            # Log failed attempt
            await ActivityLogger.log_failed_login(
                username=credentials.username,
                ip_address=request.client.host,
                user_agent=request.headers.get("user-agent"),
                reason="Invalid credentials"
            )
            raise HTTPException(status_code=401, detail="Invalid credentials")
        
        # Create session
        session = await create_session(user.id, credentials.project_id)
        
        # Log successful login
        await ActivityLogger.log_login(
            user_id=user.id,
            username=user.username,
            ip_address=request.client.host,
            user_agent=request.headers.get("user-agent"),
            project_id=credentials.project_id
        )
        
        return {"token": session.token, "user": user}
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

#### Example 2: Bulk User Update

```python
@router.post("/admin/users/bulk-update")
async def bulk_update_users(
    request: Request,
    updates: BulkUserUpdateRequest,
    current_user: User = Depends(get_current_admin_user)
):
    try:
        results = await perform_bulk_user_update(updates.user_ids, updates.changes)
        
        # Log bulk operation
        await ActivityLogger.log_bulk_operation(
            user_id=current_user.id,
            operation_type="bulk_user_update",
            target_count=len(updates.user_ids),
            success_count=results["success"],
            details=f"Bulk updated {results['success']} users",
            metadata={
                "changes": updates.changes,
                "user_ids": updates.user_ids[:10]  # First 10 for reference
            }
        )
        
        return results
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

#### Example 3: Project Member Addition

```python
@router.post("/projects/{project_hash}/members")
async def add_project_member(
    request: Request,
    project_hash: str,
    member_data: AddMemberRequest,
    current_user: User = Depends(get_current_user)
):
    # Add member logic
    project = await get_project_by_hash(project_hash)
    target_user = await get_user_by_hash(member_data.user_hash)
    
    # Database operation (triggers won't capture project_member_add)
    # So we log manually
    await ActivityLogger.log_activity(
        user_id=current_user.id,
        activity_code="project_member_add",
        details=f"User {target_user.username} added to project {project.project_name}",
        project_id=project.id,
        target_user_id=target_user.id,
        metadata={
            "role": member_data.role,
            "permissions": member_data.permissions
        }
    )
    
    return {"status": "success"}
```

---

## Querying Activity Logs

### Using Stored Procedures

#### Get Recent Activities

```python
async def get_recent_activities(
    user_id: Optional[str] = None,
    project_id: Optional[str] = None,
    activity_code: Optional[str] = None,
    days: int = 7,
    limit: int = 50,
    offset: int = 0
):
    """Query recent activity logs"""
    db = DatabaseConfig.get_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.callproc('sp_get_activity_logs', [
        limit,
        offset,
        user_id,
        project_id,
        activity_code,
        days
    ])
    
    results = []
    for result in cursor.stored_results():
        results = result.fetchall()
    
    cursor.close()
    db.close()
    
    return results
```

#### Get Activity Statistics

```python
async def get_activity_stats(project_id: Optional[str] = None, days: int = 30):
    """Get activity statistics"""
    db = DatabaseConfig.get_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.callproc('sp_get_activity_stats', [project_id, days])
    
    results = []
    for result in cursor.stored_results():
        results = result.fetchall()
    
    cursor.close()
    db.close()
    
    return results
```

#### Get User Activity Summary

```python
async def get_user_activity_summary(user_id: str, days: int = 30):
    """Get summary of user activities"""
    db = DatabaseConfig.get_connection()
    cursor = db.cursor(dictionary=True)
    
    cursor.callproc('sp_get_user_activity_summary', [user_id, days])
    
    results = []
    for result in cursor.stored_results():
        results = result.fetchall()
    
    cursor.close()
    db.close()
    
    return results
```

### Direct SQL Queries

```python
# Get all critical activities in last 24 hours
async def get_critical_activities():
    query = """
        SELECT al.*, u.username, ac.activity_name
        FROM activity_logs al
        LEFT JOIN users u ON al.user_id = u.id
        LEFT JOIN activity_catalog ac ON al.activity_catalog_id = ac.id
        WHERE al.severity_level = 'critical'
          AND al.created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
        ORDER BY al.created_at DESC
    """
    
    db = DatabaseConfig.get_connection()
    cursor = db.cursor(dictionary=True)
    cursor.execute(query)
    results = cursor.fetchall()
    cursor.close()
    db.close()
    
    return results
```

---

## Best Practices

### 1. Use Triggers for CRUD Operations

Let database triggers handle automatic logging for entity changes:
- Users, projects, groups, roles, permissions
- No need to manually log these in application code

### 2. Manually Log Business Actions

Use manual logging for:
- Login/logout events
- Bulk operations
- Custom admin actions
- Security alerts

### 3. Include Contextual Metadata

Always include relevant metadata:
```python
metadata = {
    "reason": "User request",
    "previous_value": old_value,
    "new_value": new_value,
    "additional_context": "..."
}
```

### 4. Capture IP Address and User Agent

For security and debugging:
```python
ip_address = request.client.host
user_agent = request.headers.get("user-agent")
```

### 5. Use Appropriate Activity Codes

Reference the [Activity Events Catalog](./ACTIVITY_EVENTS_CATALOG.md) for correct codes.

### 6. Handle Logging Failures Gracefully

```python
try:
    await ActivityLogger.log_activity(...)
except Exception as e:
    # Log error but don't fail the request
    logger.error(f"Failed to log activity: {e}")
```

### 7. Regular Cleanup

Schedule cleanup of old info-level logs:
```sql
-- Run monthly
CALL sp_cleanup_old_activity_logs(90, FALSE);
```

### 8. Monitor Security Events

Query critical/warning activities regularly:
```python
# Schedule daily job
security_events = await get_recent_activities(
    activity_code=None,
    days=1
)

# Filter for security concerns
critical_events = [e for e in security_events if e['severity_level'] in ['warning', 'critical']]
```

---

## Troubleshooting

### Triggers Not Logging

**Problem:** CRUD operations not creating activity logs

**Solutions:**
```sql
-- 1. Check if triggers exist
SHOW TRIGGERS FROM magic_auth LIKE 'trg_after_%';

-- 2. Check if activity catalog has entries
SELECT * FROM activity_catalog WHERE is_active = TRUE;

-- 3. Test trigger manually
INSERT INTO users (...) VALUES (...);
SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT 1;

-- 4. Check MySQL error log
SHOW VARIABLES LIKE 'log_error';
```

### Missing Activity Catalog Entries

**Problem:** Triggers can't find activity codes

**Solution:**
```sql
-- Verify catalog entry exists
SELECT * FROM activity_catalog WHERE activity_code = 'your_code';

-- Re-run catalog population
SOURCE schemas/tables/08_activity_logging_tables.sql;
```

### Performance Issues

**Problem:** Activity logging slowing down operations

**Solutions:**
1. Verify indexes exist:
```sql
SHOW INDEX FROM activity_logs;
```

2. Archive old logs:
```sql
CALL sp_cleanup_old_activity_logs(90, FALSE);
```

3. Consider async logging (application-level)

### Metadata Too Large

**Problem:** JSON metadata exceeds TEXT limit

**Solution:**
```python
# Limit metadata size
def safe_metadata(data: dict) -> dict:
    import json
    serialized = json.dumps(data)
    if len(serialized) > 60000:  # Leave buffer under 65535
        # Truncate or summarize
        return {"_truncated": True, "summary": "..."}
    return data
```

---

## Testing

### Unit Tests

```python
import pytest
from src.Util.activity_logger import ActivityLogger

@pytest.mark.asyncio
async def test_log_activity():
    result = await ActivityLogger.log_activity(
        user_id="test-user-123",
        activity_code="user_login",
        details="Test login",
        metadata={"test": True}
    )
    assert result == True

@pytest.mark.asyncio
async def test_log_failed_login():
    await ActivityLogger.log_failed_login(
        username="testuser",
        ip_address="127.0.0.1",
        user_agent="TestAgent/1.0"
    )
    # Query and verify log was created
```

### Integration Tests

```python
async def test_trigger_on_user_creation():
    # Create user
    user = await create_user(username="testuser", ...)
    
    # Check activity log created
    logs = await get_recent_activities(
        activity_code="user_registration",
        days=1
    )
    
    assert any(log['target_user_id'] == user.id for log in logs)
```

---

## Next Steps

1. Review [Activity Events Catalog](./ACTIVITY_EVENTS_CATALOG.md) for all event types
2. Set up monitoring dashboard for critical events
3. Configure log retention policies
4. Implement alerting for security events
5. Create compliance reports using activity data
