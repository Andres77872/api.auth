# Error Handler Implementation Guide

**Quick reference for using the standardized error handling system**

---

## 🚀 Quick Start

### 1. Import What You Need

```python
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.error_handler import (
    ValidationError, NotFoundError, ConflictError, 
    AuthenticationError, AuthorizationError, DatabaseError,
    ErrorCode, mask_uuid
)
```

### 2. Wrap Database Operations

```python
def get_user_by_id(user_id: str) -> Optional[User]:
    """
    Get user by ID.
    
    Args:
        user_id: User ID to retrieve
        
    Returns:
        User object if found, None if not found
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.execute("SELECT * FROM users WHERE id = %s", [user_id])
            result = cur.fetchone()
            if result:
                return User(...)
            return None
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_by_id(user_id={user_id})"
    )
```

### 3. Raise Exceptions in Route Handlers

```python
@router.get("/users/{user_hash}")
async def get_user(user_hash: str):
    user = get_user_by_hash(user_hash)
    
    if not user:
        raise NotFoundError(
            message=f"User not found",
            error_code=ErrorCode.USER_NOT_FOUND
        )
    
    return {"user": user}
```

---

## 📋 Available Exceptions

### 1. ValidationError
**Use for:** Invalid input, missing required fields, malformed data

```python
raise ValidationError(
    message="Username cannot be empty",
    error_code=ErrorCode.MISSING_REQUIRED_FIELD,
    details={"field": "username"}
)
```

**HTTP Status:** 400 Bad Request

---

### 2. NotFoundError
**Use for:** Resource not found

```python
raise NotFoundError(
    message=f"Project not found: {project_id}",
    error_code=ErrorCode.PROJECT_NOT_FOUND
)
```

**HTTP Status:** 404 Not Found

---

### 3. ConflictError
**Use for:** Duplicate entries, constraint violations

```python
raise ConflictError(
    message="Username already exists",
    error_code=ErrorCode.USERNAME_EXISTS
)
```

**HTTP Status:** 409 Conflict

---

### 4. AuthenticationError
**Use for:** Invalid credentials, expired sessions

```python
raise AuthenticationError(
    message="Invalid or expired session",
    error_code=ErrorCode.SESSION_INVALID
)
```

**HTTP Status:** 401 Unauthorized

---

### 5. AuthorizationError
**Use for:** Insufficient permissions

```python
raise AuthorizationError(
    message="Insufficient permissions to delete project",
    error_code=ErrorCode.INSUFFICIENT_PERMISSIONS
)
```

**HTTP Status:** 403 Forbidden

---

### 6. DatabaseError
**Use for:** Database connection issues, query errors

```python
raise DatabaseError(
    message="Failed to connect to database",
    error_code=ErrorCode.DB_CONNECTION_ERROR
)
```

**HTTP Status:** 500 Internal Server Error

---

## 🔐 UUID Masking

**Always mask sensitive UUIDs/hashes in error contexts:**

```python
from src.Util.error_handler import mask_uuid

# Good
error_context=f"get_user(user_hash={mask_uuid(user_hash)})"

# Bad - exposes full UUID
error_context=f"get_user(user_hash={user_hash})"
```

**Output:** `user_hash=abc12...xyz89` (first 5 + last 5 chars)

---

## 🎯 Common Patterns

### Pattern 1: Update Function

```python
def update_user(user_id: str, username: str = None, email: str = None):
    # Validate input
    if not username and not email:
        raise ValidationError(
            message="At least one field required",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD
        )
    
    def _update():
        with get_connection() as con:
            cur = con.cursor()
            # ... update logic ...
            
            if cur.rowcount == 0:
                raise NotFoundError(
                    message=f"User not found: {user_id}",
                    error_code=ErrorCode.USER_NOT_FOUND
                )
            
            con.commit()
            return get_user_by_id(user_id)
    
    return handle_db_operation(_update, error_context=f"update_user({user_id})")
```

### Pattern 2: Create Function with Conflict Handling

```python
def create_project(project_name: str):
    def _create():
        with get_connection() as con:
            cur = con.cursor()
            # handle_db_operation automatically catches IntegrityError
            # and converts to ConflictError
            cur.execute(
                "INSERT INTO projects (name) VALUES (%s)",
                [project_name]
            )
            con.commit()
            return Project(...)
    
    return handle_db_operation(
        _create,
        error_context=f"create_project('{project_name}')"
    )
```

### Pattern 3: Auto-Reactivation

```python
def assign_user_to_group(user_id: str, group_id: str):
    def _assign():
        with get_connection() as con:
            cur = con.cursor()
            try:
                cur.execute("INSERT INTO memberships ...")
                con.commit()
                return membership
            except pymysql.IntegrityError:
                # Already exists - reactivate
                cur.execute("UPDATE memberships SET is_active = 1 ...")
                con.commit()
                return get_membership(user_id, group_id)
    
    return handle_db_operation(_assign, error_context=f"assign({user_id}, {group_id})")
```

---

## 🏗️ Route Handler Best Practices

### ✅ DO: Let Middleware Handle Exceptions

```python
@router.get("/users/{user_hash}")
async def get_user(user_hash: str):
    user = get_user_by_hash(user_hash)
    
    if not user:
        raise NotFoundError(...)  # Middleware converts to JSON
    
    return {"user": user}
```

### ❌ DON'T: Manually Create HTTPException

```python
# Bad - don't do this
@router.get("/users/{user_hash}")
async def get_user(user_hash: str):
    try:
        user = get_user_by_hash(user_hash)
        if not user:
            raise HTTPException(status_code=404, detail="Not found")
        return {"user": user}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
```

---

## 📊 Error Response Format

All errors are automatically formatted by middleware:

```json
{
  "success": false,
  "error": {
    "message": "User not found",
    "error_code": "USER_NOT_FOUND",
    "category": "NOT_FOUND",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "user_hash": "abc12...xyz89"
    }
  }
}
```

**In DEBUG_MODE, additional fields are included:**
- `stack_trace`: Full Python traceback
- `context`: Error context string
- `original_error`: Original exception details

---

## 🔧 Error Codes Reference

| Code | Category | HTTP | Description |
|------|----------|------|-------------|
| AUTH_1001 | AUTHENTICATION | 401 | Invalid credentials |
| AUTH_1002 | AUTHENTICATION | 401 | Session expired |
| AUTH_1003 | AUTHENTICATION | 401 | Session invalid |
| AUTHZ_2001 | AUTHORIZATION | 403 | Insufficient permissions |
| VAL_3001 | VALIDATION | 400 | Missing required field |
| VAL_3002 | VALIDATION | 400 | Invalid format |
| NF_4001 | NOT_FOUND | 404 | User not found |
| NF_4002 | NOT_FOUND | 404 | Project not found |
| CONF_5001 | CONFLICT | 409 | Username exists |
| CONF_5002 | CONFLICT | 409 | Email exists |
| DB_6001 | DATABASE | 500 | Connection error |
| DB_6002 | DATABASE | 500 | Query error |
| INT_9999 | INTERNAL | 500 | Internal error |

**See:** `src/Util/error_handler.py` for complete list

---

## 🧪 Testing Error Scenarios

```python
def test_user_not_found():
    with pytest.raises(NotFoundError) as exc_info:
        get_user_by_id("nonexistent_id")
    
    assert exc_info.value.error_code == ErrorCode.USER_NOT_FOUND
    assert "not found" in str(exc_info.value).lower()

def test_duplicate_username():
    create_user("testuser", "pass123")
    
    with pytest.raises(ConflictError) as exc_info:
        create_user("testuser", "different_pass")
    
    assert exc_info.value.error_code == ErrorCode.USERNAME_EXISTS
```

---

## 📚 Examples from Refactored Code

### Example 1: db_projects.py - update_project

```python
def update_project(project_id: str, project_name: str = None, 
                  project_description: str = None) -> Optional[Project]:
    """Update project with validation."""
    if not project_name and project_description is None:
        raise ValidationError(
            message="At least one field must be provided",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD
        )
    
    def _update():
        with get_connection() as con:
            cur = con.cursor()
            # ... update logic ...
            if cur.rowcount == 0:
                raise NotFoundError(
                    message=f"Project not found",
                    error_code=ErrorCode.PROJECT_NOT_FOUND
                )
            return get_project_by_id(project_id)
    
    return handle_db_operation(_update, error_context=f"update_project({project_id})")
```

### Example 2: db_user_groups.py - grant_group_project_access

```python
def grant_group_project_access(group_id: str, project_id: str) -> UserGroupProject:
    """Grant with auto-reactivation."""
    def _grant():
        with get_connection() as con:
            cur = con.cursor()
            try:
                cur.execute("INSERT INTO user_group_projects ...")
                con.commit()
                return UserGroupProject(...)
            except pymysql.IntegrityError:
                # Reactivate if exists
                cur.execute("UPDATE user_group_projects SET is_active = 1 ...")
                con.commit()
                return get_group_project_access(group_id, project_id)
    
    return handle_db_operation(_grant, error_context=f"grant_access({group_id}, {project_id})")
```

### Example 3: routes/global_roles.py - create_role

```python
@router.post("/", response_model=CreateRoleResponse)
async def create_role_endpoint(
    role_name: str = Form(...),
    role_description: str = Form(None),
    session_data=Depends(require_admin)
):
    # No try-except needed - middleware handles everything
    role = global_roles.create_role(role_name, role_description)
    
    return CreateRoleResponse(
        success=True,
        message="Role created successfully",
        role=RoleInfo(...)
    )
```

---

## 🎓 Migration Checklist

When refactoring a function:

- [ ] Add `handle_db_operation` wrapper
- [ ] Add comprehensive docstring (Args, Returns, Raises)
- [ ] Replace `return None` with appropriate exceptions
- [ ] Replace `try-except` with proper exception raising
- [ ] Add UUID masking to error context
- [ ] Add validation for required fields
- [ ] Test error scenarios

---

**For current status, see:** `STATUS.md`  
**For overview, see:** `README.md`

