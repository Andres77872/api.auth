# Middleware Package

**Location:** `src/middleware/`  
**Purpose:** Contains all middleware components for request/response processing

---

## Overview

This directory contains all middleware components used in the Magic Auth API. Middleware functions intercept HTTP requests and responses to provide cross-cutting concerns like authentication, logging, validation, and error handling.

---

## Middleware Stack (Execution Order)

The order in which middleware is added to the application matters. Here's the current stack in `main.py`:

```
1. CORS Middleware (FastAPI built-in)
   ↓ Allow cross-origin requests
   
2. Auth Context Middleware
   ↓ Extract user context from Bearer token
   
3. API Audit Middleware
   ↓ Log all API requests/responses
   
4. Request Validation Middleware
   ↓ Validate requests, track time, log activity
   
5. Your route handlers
```

**Note:** Middleware is executed in **reverse order** of how it's added. The last middleware added runs first.

---

## Middleware Components

### 1. activity_logging.py
**Class:** `ActivityLoggingMiddleware`

**Purpose:** Automatically captures request context (IP address, user agent) for activity logging.

**Features:**
- Extracts client IP (supports X-Forwarded-For, X-Real-IP)
- Extracts user agent from headers
- Sets context in thread-local storage for activity logger
- Cleans up context after request

**Usage:**
```python
from src.middleware import ActivityLoggingMiddleware
app.add_middleware(ActivityLoggingMiddleware)
```

**When to Use:** If you need IP and user agent context in activity logs.

**Status:** ⚠️ **Superseded by auth_context.py** - Consider deprecating

---

### 2. api_audit.py
**Class:** `APIAuditMiddleware`

**Purpose:** Automatically logs ALL API requests and responses to `api_audit_log` table.

**Features:**
- Captures complete request/response details
- Filters sensitive data (passwords, tokens)
- Runs as background tasks (non-blocking)
- Auto-flags security events
- Generates searchable tags
- Extracts resource type/ID from URLs

**Database:** Uses `api_audit_log` table and stored procedures

**Usage:**
```python
from src.middleware import APIAuditMiddleware
app.add_middleware(APIAuditMiddleware)
```

**Configuration:**
Edit excluded endpoints in `src/Util/api_audit_logger.py`:
```python
EXCLUDED_PATHS = ['/ping', '/health', '/metrics']
```

**Performance:** ~2-5ms overhead per request (background execution)

**Status:** ✅ **Active** - Primary audit logging system

---

### 3. auth_context.py
**Class:** `AuthContextMiddleware`

**Purpose:** Extracts authentication context and sets it on `request.state` for downstream middleware.

**Features:**
- Extracts Bearer token from Authorization header
- Validates session via database
- Populates `request.state.user` with user info
- Sets `request.state.session_id` and `request.state.project_id`
- Does NOT enforce authentication (non-blocking)

**Sets on request.state:**
```python
request.state.user = UserContext(
    id=user_id,
    user_hash=user_hash,
    user_type=user_type,
    username=username,
    permissions=permissions,
    groups=groups
)
request.state.session_id = session_token
request.state.project_id = project_id
request.state.project_hash = project_hash
```

**Usage:**
```python
from src.middleware import AuthContextMiddleware
app.add_middleware(AuthContextMiddleware)
```

**When to Use:** Required for `api_audit.py` to capture user context

**Status:** ✅ **Active** - Required by API audit middleware

---

### 4. authentication.py
**Functions:** Authentication dependencies (not a middleware class)

**Purpose:** Provides dependency injection functions for route authentication and authorization.

**Functions:**
- `verify_session()` - Verify valid session, return user data
- `verify_admin_access()` - Require admin/root access
- `verify_root_access()` - Require root access only
- `verify_project_access(project_id)` - Verify project access
- `require_permission(permission)` - Require specific permission
- `optional_auth()` - Optional authentication

**Usage in Routes:**
```python
from src.middleware import verify_session, verify_admin_access

@router.get("/users")
async def get_users(current_user = Depends(verify_session)):
    # current_user contains validated session data
    pass

@router.delete("/users/{user_hash}")
async def delete_user(user_hash: str, current_admin = Depends(verify_admin_access)):
    # Only accessible by admin/root users
    pass
```

**Status:** ✅ **Active** - Core authentication system

---

### 5. error_handler.py
**Function:** `register_exception_handlers(app)`

**Purpose:** Registers global exception handlers for the FastAPI application.

**Features:**
- Handles HTTP exceptions
- Handles validation errors (422)
- Handles database errors
- Handles authentication errors (401/403)
- Returns consistent error response format
- Logs errors with proper context

**Error Response Format:**
```json
{
    "error": {
        "code": "ERROR_CODE",
        "message": "Error message",
        "details": {...},
        "timestamp": "2025-10-26T17:30:00Z"
    }
}
```

**Usage:**
```python
from src.middleware import register_exception_handlers

app = FastAPI()
register_exception_handlers(app)
```

**Status:** ✅ **Active** - Global error handling

---

### 6. request_validation.py
**Class:** `RequestValidationMiddleware`

**Purpose:** Validates requests, tracks processing time, and logs activity via `logger_ws`.

**Features:**
- Validates user-agent header presence (returns 422 if missing)
- Checks POST request size limit (8MB max, returns 413 if exceeded)
- Tracks request processing time
- Adds `X-Process-Time` header to response
- Sets activity logging context (IP, user agent)
- Logs requests to file via `logger_ws`

**Configuration:**
```python
# Maximum POST size (default: 8MB)
MAX_CONTENT_LENGTH = 8388608
```

**Usage:**
```python
from src.middleware import RequestValidationMiddleware
app.add_middleware(RequestValidationMiddleware)
```

**Response Headers:**
```
X-Process-Time: 0.0234  # seconds
```

**Status:** ✅ **Active** - Request validation and logging

---

## Adding New Middleware

### Option 1: Class-Based Middleware (Recommended)

```python
from starlette.middleware.base import BaseHTTPMiddleware
from fastapi import Request
from starlette.responses import Response

class MyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # Before request processing
        print(f"Request: {request.method} {request.url.path}")
        
        # Call next middleware/route
        response = await call_next(request)
        
        # After request processing
        print(f"Response: {response.status_code}")
        
        return response
```

**Register in main.py:**
```python
from src.middleware.my_middleware import MyMiddleware
app.add_middleware(MyMiddleware)
```

### Option 2: Function-Based Middleware

```python
from fastapi import Request

@app.middleware("http")
async def my_middleware(request: Request, call_next):
    # Before request
    response = await call_next(request)
    # After request
    return response
```

**Note:** Function-based middleware should generally be converted to class-based for consistency.

---

## Middleware Best Practices

### 1. Order Matters
- Add authentication before authorization
- Add context extraction before audit logging
- Add validation before processing

### 2. Error Handling
Always wrap `call_next()` in try/except:
```python
try:
    response = await call_next(request)
except Exception as e:
    # Handle error
    return error_response
```

### 3. Background Tasks
Use FastAPI's `BackgroundTasks` for non-blocking operations:
```python
from fastapi import BackgroundTasks

background = BackgroundTasks()
background.add_task(log_to_database, data)
response.background = background
```

### 4. Request State
Use `request.state` to pass data between middleware:
```python
# In middleware A
request.state.user_id = "usr-123"

# In middleware B
if hasattr(request.state, 'user_id'):
    user_id = request.state.user_id
```

### 5. Performance
- Keep middleware lightweight
- Use background tasks for heavy operations
- Avoid blocking I/O in middleware
- Profile middleware overhead

---

## Testing Middleware

### Unit Test Example
```python
from fastapi.testclient import TestClient
from src.main import app

client = TestClient(app)

def test_api_audit_middleware():
    response = client.get("/api/v1/users")
    assert response.status_code == 200
    
    # Check audit log was created
    # ... query database ...
```

### Integration Test Example
```python
def test_authentication_flow():
    # Login
    login_response = client.post("/api/v1/auth/login", json={
        "username": "admin",
        "password": "password"
    })
    token = login_response.json()["token"]
    
    # Make authenticated request
    response = client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {token}"}
    )
    
    assert response.status_code == 200
```

---

## Troubleshooting

### Middleware Not Running
**Check:**
1. Middleware is registered in `main.py`
2. Middleware is registered in correct order
3. No exceptions in middleware code

### Request.state Not Set
**Check:**
1. Middleware setting state runs before middleware reading state
2. Attribute name is correct (case-sensitive)
3. hasattr() check before accessing

### Background Tasks Not Executing
**Check:**
1. Background task is added to response
2. No exceptions in background task function
3. Application doesn't exit before tasks complete

### High Latency
**Check:**
1. Middleware using background tasks for heavy operations
2. No blocking I/O in middleware
3. Database connection pooling configured
4. Profile middleware with timing logs

---

## Migration Guide

### Moving from Inline to Class-Based

**Before (in main.py):**
```python
@app.middleware("http")
async def my_middleware(request: Request, call_next):
    # middleware code
    response = await call_next(request)
    return response
```

**After:**

1. Create `src/middleware/my_middleware.py`:
```python
from starlette.middleware.base import BaseHTTPMiddleware

class MyMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        # middleware code
        response = await call_next(request)
        return response
```

2. Update `src/middleware/__init__.py`:
```python
from src.middleware.my_middleware import MyMiddleware
__all__ = [..., 'MyMiddleware']
```

3. Update `main.py`:
```python
from src.middleware import MyMiddleware
app.add_middleware(MyMiddleware)
```

---

## Current Middleware Summary

| Middleware | Type | Purpose | Status |
|------------|------|---------|--------|
| activity_logging.py | Class | IP/UA context for activity logs | ⚠️ Consider deprecating |
| api_audit.py | Class | API request/response audit logging | ✅ Active |
| auth_context.py | Class | Extract user context from auth | ✅ Active |
| authentication.py | Dependencies | Route authentication/authorization | ✅ Active |
| error_handler.py | Registration | Global exception handling | ✅ Active |
| request_validation.py | Class | Request validation and logging | ✅ Active |

---

## References

- [FastAPI Middleware Documentation](https://fastapi.tiangolo.com/tutorial/middleware/)
- [Starlette Middleware](https://www.starlette.io/middleware/)
- API Audit Logging: `API_AUDIT_MIDDLEWARE_IMPLEMENTATION.md`
- Error Handling: `docs/ERROR_HANDLER/`

---

**Last Updated:** October 26, 2025  
**Maintained By:** Development Team  
**Questions:** Refer to main documentation or team leads
