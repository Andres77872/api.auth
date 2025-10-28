# Activity Logging - 100% Trigger-Based Refactoring Guide

## 🎯 Objective

Refactor the activity logging system to make **ALL** activity logging 100% trigger-based, with user context tracking through session variables.

## 🔑 Key Innovation: Session Variable Context

### Problem
Database triggers don't have direct access to application context (which user is logged in).

### Solution
Use MySQL session variables to pass user context from application to triggers:
- `@activity_user_id` - User performing the action
- `@activity_ip_address` - Client IP address
- `@activity_user_agent` - User agent string

## 📦 New Components Created

### 1. Context Management (`schemas/stored_procedures/12_activity_context.sql`)

```sql
-- Set context before any operation
CALL sp_set_activity_context('user-123', '192.168.1.1', 'Mozilla/5.0');

-- Clear context after operation (optional)
CALL sp_clear_activity_context();

-- Helper function for triggers
fn_get_context_user_id(created_by, updated_by, assigned_by)
```

## 🔄 How It Works

### Application Flow

```python
# Before any database operation
await db.execute("CALL sp_set_activity_context(%s, %s, %s)", 
                 [user.id, request.client.host, request.headers.get("user-agent")])

# Perform operation - trigger reads context and logs automatically
user.user_type = 'admin'
db.commit()

# Activity log created automatically by trigger with user context!
```

### Trigger Flow

```sql
CREATE TRIGGER trg_after_user_update AFTER UPDATE ON users
BEGIN
    DECLARE v_user_id VARCHAR(64);
    
    -- Get user from context (priority order):
    -- 1. @activity_user_id (from sp_set_activity_context)
    -- 2. created_by/updated_by/assigned_by from record
    -- 3. NULL (system action)
    SET v_user_id = fn_get_context_user_id(NULL, NEW.id, NULL);
    
    INSERT INTO activity_logs (
        id, user_id, activity_type, details,
        ip_address, user_agent,  -- ← From session variables!
        ...
    ) VALUES (...);
END;
```

## 📋 Refactoring Checklist

### ✅ Step 1: Install Context Management

```bash
mysql -u root -p < schemas/stored_procedures/12_activity_context.sql
```

### ✅ Step 2: Update All Triggers

Each trigger needs to be updated to:
1. Use `fn_get_context_user_id()` to get the performing user
2. Include `@activity_ip_address` and `@activity_user_agent`
3. Remove hardcoded user_id logic

**Files to update:**
- `schemas/triggers/01_activity_logging_triggers.sql`
- `schemas/triggers/02_permission_activity_triggers.sql`

### ✅ Step 3: Application Integration

#### Create Database Wrapper

```python
# src/Util/db_context.py

class DatabaseContext:
    """Context manager to set activity context for triggers"""
    
    def __init__(self, user_id: str, ip_address: str, user_agent: str, db):
        self.user_id = user_id
        self.ip_address = ip_address
        self.user_agent = user_agent
        self.db = db
    
    def __enter__(self):
        cursor = self.db.cursor()
        cursor.callproc('sp_set_activity_context', [
            self.user_id,
            self.ip_address,
            self.user_agent
        ])
        cursor.close()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        # Optional: clear context
        cursor = self.db.cursor()
        cursor.callproc('sp_clear_activity_context')
        cursor.close()
```

#### Use in Endpoints

```python
from src.Util.db_context import DatabaseContext

@router.patch("/users/{user_hash}")
async def update_user(
    user_hash: str,
    updates: UserUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_user),
    db = Depends(get_db)
):
    user = await get_user_by_hash(user_hash)
    
    # Set context - trigger will read this!
    with DatabaseContext(
        user_id=current_user.id,
        ip_address=request.client.host,
        user_agent=request.headers.get("user-agent"),
        db=db
    ):
        # Make changes - triggers log automatically with context
        if updates.user_type:
            user.user_type = updates.user_type  # ← Trigger logs this!
        
        db.commit()
        # ✅ Activity log created with correct user_id, IP, and user agent!
    
    return {"status": "updated", "user": user.to_dict()}
```

### ✅ Step 4: Middleware Integration (Recommended)

Create middleware to automatically set context for all requests:

```python
# src/middleware/activity_context_middleware.py

from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from src.Config.database_config import DatabaseConfig

class ActivityContextMiddleware(BaseHTTPMiddleware):
    """Automatically set activity context for all requests"""
    
    async def dispatch(self, request: Request, call_next):
        # Get user from request state (set by auth middleware)
        user_id = None
        if hasattr(request.state, 'user'):
            user_id = request.state.user.id
        
        # Set context if we have a user
        if user_id:
            try:
                db = DatabaseConfig.get_connection()
                cursor = db.cursor()
                cursor.callproc('sp_set_activity_context', [
                    user_id,
                    request.client.host,
                    request.headers.get("user-agent")
                ])
                cursor.close()
                db.close()
            except Exception as e:
                # Log error but don't fail request
                print(f"Failed to set activity context: {e}")
        
        # Process request
        response = await call_next(request)
        
        return response

# In main.py
app.add_middleware(ActivityContextMiddleware)
```

## 🎯 Benefits of This Approach

### 1. **Zero Manual Logging**
```python
# Before (manual logging required)
user.user_type = 'admin'
db.commit()
await ActivityLogger.log_activity(...)  # ← Manual!

# After (fully automatic)
with DatabaseContext(user_id, ip, ua, db):
    user.user_type = 'admin'
    db.commit()
    # ✅ Automatic logging with user context!
```

### 2. **Complete User Context**
- Who performed the action (user_id)
- From where (ip_address)
- Using what (user_agent)
- When (timestamp)

### 3. **Consistent Logging**
- No missed logs (developers can't forget to log)
- Always same format
- Always same data captured

### 4. **Flexible Fallback**
```sql
fn_get_context_user_id(created_by, updated_by, assigned_by)
-- Priority:
-- 1. @activity_user_id (from context)
-- 2. created_by/updated_by/assigned_by (from record)
-- 3. NULL (system action)
```

## 📊 Coverage After Refactoring

| Event Type | Before | After |
|------------|--------|-------|
| User CRUD | 🤖 Auto (no user) | 🤖 Auto (with user) |
| Project CRUD | 🤖 Auto (no user) | 🤖 Auto (with user) |
| Group CRUD | 🤖 Auto (no user) | 🤖 Auto (with user) |
| Permission CRUD | 🤖 Auto (no user) | 🤖 Auto (with user) |
| Role CRUD | 🤖 Auto (no user) | 🤖 Auto (with user) |
| Session Create | 🤖 Auto (no IP) | 🤖 Auto (with IP) |
| Login/Logout | 👋 Manual | 🤖 Auto (with trigger) |
| Bulk Operations | 👋 Manual | 🤖 Auto (context aware) |

**Result: 100% automatic, 0% manual!**

## 🔧 Implementation Examples

### Example 1: User Type Change

```python
# Application code
@router.patch("/users/{user_hash}/type")
async def change_user_type(
    user_hash: str,
    new_type: str,
    request: Request,
    current_admin: User = Depends(get_admin_user),
    db = Depends(get_db)
):
    user = await get_user_by_hash(user_hash)
    
    # Set context once
    with DatabaseContext(current_admin.id, request.client.host, request.headers.get("user-agent"), db):
        user.user_type = new_type  # ← Trigger logs automatically!
        db.commit()
    
    # Activity log shows:
    # - user_id: current_admin.id  ✅
    # - activity_type: user_type_changed  ✅
    # - target_user_id: user.id  ✅
    # - ip_address: request.client.host  ✅
    # - old_values and new_values  ✅
    
    return {"status": "updated"}
```

### Example 2: Role Assignment

```python
@router.post("/users/{user_hash}/role")
async def assign_role(
    user_hash: str,
    role_hash: str,
    request: Request,
    current_admin: User = Depends(get_admin_user),
    db = Depends(get_db)
):
    user = await get_user_by_hash(user_hash)
    role = await get_role_by_hash(role_hash)
    
    # Set context
    with DatabaseContext(current_admin.id, request.client.host, request.headers.get("user-agent"), db):
        user.role_id = role.id  # ← UPDATE trigger logs automatically!
        db.commit()
    
    # No manual logging needed!
    return {"status": "role assigned"}
```

### Example 3: Bulk Operations

```python
@router.post("/admin/users/bulk-update")
async def bulk_update_users(
    user_hashes: List[str],
    updates: dict,
    request: Request,
    current_admin: User = Depends(get_admin_user),
    db = Depends(get_db)
):
    # Set context once for all operations
    with DatabaseContext(current_admin.id, request.client.host, request.headers.get("user-agent"), db):
        for user_hash in user_hashes:
            user = await get_user_by_hash(user_hash)
            
            if 'is_active' in updates:
                user.is_active = updates['is_active']  # ← Each triggers separately!
            
            db.commit()
        
        # Each update creates its own activity log entry
        # All with correct user_id, IP, and user_agent
    
    return {"updated": len(user_hashes)}
```

## 🚀 Migration Path

### Phase 1: Install Context System (Day 1)
1. Install `12_activity_context.sql`
2. Test context setting/getting
3. Verify session variables work

### Phase 2: Update Triggers (Day 2-3)
1. Update all triggers to use `fn_get_context_user_id()`
2. Add IP and user agent to all INSERT statements
3. Test each trigger individually

### Phase 3: Application Integration (Day 4-5)
1. Create `DatabaseContext` utility
2. Create `ActivityContextMiddleware`
3. Update critical endpoints first
4. Roll out to all endpoints

### Phase 4: Remove Manual Logging (Day 6-7)
1. Remove `ActivityLogger` calls from code
2. Remove `sp_log_activity` manual calls
3. Clean up unused code
4. Update documentation

### Phase 5: Testing & Validation (Day 8-10)
1. Test all CRUD operations
2. Verify user context captured correctly
3. Test bulk operations
4. Load testing
5. Security testing

## 📝 Testing

### Test Context Setting

```sql
-- Test context management
CALL sp_set_activity_context('test-user-123', '192.168.1.1', 'TestAgent/1.0');
CALL sp_get_activity_context();  -- Should show values

-- Test function
SELECT fn_get_context_user_id('user-1', 'user-2', 'user-3');  -- Should return test-user-123

CALL sp_clear_activity_context();
CALL sp_get_activity_context();  -- Should show NULL
```

### Test Trigger with Context

```sql
-- Set context
CALL sp_set_activity_context('admin-123', '192.168.1.100', 'Chrome/90.0');

-- Make change (trigger should capture context)
UPDATE users SET user_type = 'admin' WHERE id = 'user-456';

-- Check activity log
SELECT user_id, activity_type, target_user_id, ip_address, user_agent
FROM activity_logs
WHERE target_user_id = 'user-456'
ORDER BY created_at DESC
LIMIT 1;

-- Should show:
-- user_id: admin-123  ✅
-- ip_address: 192.168.1.100  ✅
-- user_agent: Chrome/90.0  ✅
```

## 🎉 Final Result

### Before Refactoring
- 27 events automatic (without user context)
- 13 events manual (with user context)
- Inconsistent logging
- Easy to forget to log

### After Refactoring
- **40 events automatic** (with full user context)
- **0 events manual**
- Consistent logging
- Impossible to forget to log

## 📚 Updated Documentation Needed

1. ✅ This guide (TRIGGER_BASED_REFACTOR.md)
2. ⚠️ Update IMPLEMENTATION_GUIDE.md
3. ⚠️ Update USAGE_EXAMPLES.md
4. ⚠️ Update QUICK_REFERENCE.md
5. ⚠️ Update README.md

## 🔗 Related Files

- `schemas/stored_procedures/12_activity_context.sql` ✅ Created
- `schemas/triggers/01_activity_logging_triggers.sql` ⚠️ Needs update
- `schemas/triggers/02_permission_activity_triggers.sql` ⚠️ Needs update
- `src/Util/db_context.py` ⚠️ Needs creation
- `src/middleware/activity_context_middleware.py` ⚠️ Needs creation

---

**Status**: Context management created. Triggers and application integration pending.  
**Next Steps**: Update trigger files to use new context mechanism.
