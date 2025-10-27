# Audit Log System - Implementation Guide

**Magic Auth System - Automatic Middleware-Based Auditing**

---

## Quick Implementation Steps

### ✅ Already Implemented!

The API audit logging is **automatically active** via middleware. **No manual logging required!**

```python
# File: src/main.py
from src.middleware import (
    AuthContextMiddleware,
    APIAuditMiddleware,
    RequestValidationMiddleware
)

app = FastAPI()

# Middleware stack (already configured)
app.add_middleware(RequestValidationMiddleware)  # Validates requests
app.add_middleware(APIAuditMiddleware)          # Logs ALL requests automatically
app.add_middleware(AuthContextMiddleware)       # Extracts user context
```

### How It Works

Every HTTP request is **automatically logged** to `api_audit_log` table via middleware:

```
HTTP Request → Auth Context → API Audit → Route Handler → Background Logging → Response
```

**No code changes needed in routes!**

---

## Database Setup

### Verify Tables

```sql
-- Check api_audit_log table exists
SELECT table_name FROM information_schema.tables 
WHERE table_schema = 'magic_auth' 
  AND table_name = 'api_audit_log';

-- Verify table structure
DESCRIBE api_audit_log;

-- Check stored procedures
SELECT routine_name FROM information_schema.routines 
WHERE routine_schema = 'magic_auth' 
  AND routine_name LIKE '%audit%';
-- Should return: sp_log_api_request, sp_update_api_response, sp_get_audit_logs, etc.
```

### Test Logging

```bash
# Make a test request
curl -X GET http://localhost:8000/api/v1/users

# Check if logged
mysql -u user -p magic_auth -e "
SELECT * FROM api_audit_log 
WHERE endpoint_path = '/api/v1/users' 
ORDER BY request_timestamp DESC LIMIT 1;
"
```

---

## What Gets Logged Automatically

### Every Request Captures:

**Request Data:**
- HTTP method (GET, POST, PUT, DELETE)
- Endpoint path and route pattern
- Headers (sensitive data filtered)
- Request body (passwords/tokens filtered)
- Query parameters
- Client IP, user agent, referer

**Response Data:**
- HTTP status code
- Response headers (filtered)
- Duration in milliseconds
- Success/failure flag
- Error details (if any)

**User Context (if authenticated):**
- User ID and user type
- Session ID
- Project ID
- Permissions and groups

**Metadata:**
- Resource type and ID
- Security event flag
- Searchable tags

### Example Route (No Manual Logging Needed!)

```python
# User creation - automatically logged by middleware
@router.post("/admin/users")
async def create_user(data: CreateUserRequest, current_admin = Depends(verify_admin_access)):
    user = db_create_user(data)
    return {"user": user}
    # ✅ Automatically logged to api_audit_log:
    #    - POST /api/v1/admin/users
    #    - user_id: current_admin.id
    #    - user_type: admin
    #    - request_body: {"username": "...", "password": "***FILTERED***"}
    #    - security_event: TRUE (admin action)
    #    - tags: ["post", "create", "admin_action", "user_management"]

# User status update - automatically logged
@router.put("/admin/users/{user_hash}/status")
async def change_status(user_hash: str, new_status: bool, current_admin = Depends(verify_admin_access)):
    user = get_user_by_hash(user_hash)
    update_user_status(user.id, new_status)
    return {"status": "updated"}
    # ✅ Automatically logged with:
    #    - target_resource_type: "user"
    #    - target_resource_id: user_hash
    #    - security_event: TRUE

# Project deletion - automatically logged
@router.delete("/projects/{project_hash}")
async def delete_project(project_hash: str, current_root = Depends(verify_root_access)):
    project = get_project_by_hash(project_hash)
    db_delete_project(project.id)
    return {"status": "deleted"}
    # ✅ Automatically logged with:
    #    - http_method: DELETE
    #    - security_event: TRUE (delete operation)
    #    - tags: ["delete", "admin_action", "project_management"]

# Login - automatically logged (even failures!)
@router.post("/auth/login")
async def login(data: LoginRequest):
    user = authenticate_user(data.username, data.password)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid credentials")
    return {"token": create_token(user)}
    # ✅ Success: Logged with user_id, tags: ["authentication", "post"]
    # ✅ Failure: Logged with status 401, security_event: TRUE
```

---

## Configuration

### Exclude Endpoints from Logging

Edit `src/Util/api_audit_logger.py`:

```python
EXCLUDED_PATHS = [
    '/ping',
    '/health',
    '/metrics',
    '/docs',
    '/redoc',
    '/openapi.json',
    # Add more paths here
]
```

### Customize Security Event Detection

Edit `src/Util/api_audit_logger.py`, method `is_security_event()`:

```python
@staticmethod
def is_security_event(path: str, method: str, status_code: int, user_type: Optional[str]) -> bool:
    # Failed authentication
    if status_code == 401 and '/auth/' in path:
        return True
    
    # Add your custom rules here
    if '/critical-endpoint' in path:
        return True
    
    # ...existing rules...
```

---

## Testing

### Test Middleware is Working

```python
from fastapi.testclient import TestClient
from src.main import app
from src.Util.db_config import get_connection

client = TestClient(app)

def test_audit_middleware_logs_request():
    # Make request
    response = client.get("/api/v1/users")
    
    # Check database for log
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT * FROM api_audit_log 
            WHERE endpoint_path = '/api/v1/users' 
            ORDER BY request_timestamp DESC LIMIT 1
        """)
        log = cursor.fetchone()
    
    assert log is not None
    assert log['http_method'] == 'GET'
    assert log['response_status'] == response.status_code
```

### Test Sensitive Data Filtering

```python
def test_password_filtering():
    # Login with password
    response = client.post("/api/v1/auth/login", json={
        "username": "test",
        "password": "secret123"
    })
    
    # Check password is filtered
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT request_body FROM api_audit_log 
            WHERE endpoint_path LIKE '%/auth/login%' 
            ORDER BY request_timestamp DESC LIMIT 1
        """)
        log = cursor.fetchone()
    
    import json
    body = json.loads(log['request_body'])
    assert body['password'] == '***FILTERED***'
```

### Test User Context Capture

```python
def test_user_context_logged(admin_token):
    response = client.get(
        "/api/v1/users",
        headers={"Authorization": f"Bearer {admin_token}"}
    )
    
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT user_id, user_type FROM api_audit_log 
            WHERE endpoint_path = '/api/v1/users' 
            ORDER BY request_timestamp DESC LIMIT 1
        """)
        log = cursor.fetchone()
    
    assert log['user_id'] is not None
    assert log['user_type'] in ['admin', 'root']
```

---

## Querying Audit Logs

### Using Stored Procedures

```python
from src.Util.db_config import get_connection

# Get recent audit logs
with get_connection() as conn:
    cursor = conn.cursor(dictionary=True)
    cursor.callproc('sp_get_audit_logs', (
        50,          # limit
        0,           # offset
        None,        # user_id
        None,        # project_id
        None,        # endpoint_path
        None,        # http_method
        None,        # status_code
        None,        # is_success
        None,        # security_event
        7            # days
    ))
    for result in cursor.stored_results():
        logs = result.fetchall()
```

### Direct SQL Queries

```sql
-- Recent requests
SELECT 
    request_timestamp,
    http_method,
    endpoint_path,
    user_id,
    response_status,
    duration_ms
FROM api_audit_log
ORDER BY request_timestamp DESC
LIMIT 50;

-- Failed login attempts
SELECT 
    client_ip,
    COUNT(*) as attempts,
    MAX(request_timestamp) as last_attempt
FROM api_audit_log
WHERE endpoint_path LIKE '%/auth/login%'
  AND is_success = FALSE
  AND request_timestamp >= DATE_SUB(NOW(), INTERVAL 15 MINUTE)
GROUP BY client_ip
HAVING attempts >= 5;

-- Admin activity
SELECT 
    u.username,
    COUNT(*) as actions,
    COUNT(CASE WHEN a.security_event THEN 1 END) as security_events
FROM api_audit_log a
JOIN users u ON a.user_id = u.id
WHERE a.user_type IN ('root', 'admin')
  AND a.request_timestamp >= DATE_SUB(NOW(), INTERVAL 30 DAY)
GROUP BY u.username
ORDER BY actions DESC;

-- Slow endpoints
SELECT 
    endpoint_path,
    http_method,
    AVG(duration_ms) as avg_duration,
    MAX(duration_ms) as max_duration,
    COUNT(*) as request_count
FROM api_audit_log
WHERE duration_ms IS NOT NULL
  AND request_timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
GROUP BY endpoint_path, http_method
HAVING avg_duration > 500
ORDER BY avg_duration DESC;
```

---

## Maintenance

### Archive Old Logs

```sql
-- Create archive table if not exists
CREATE TABLE IF NOT EXISTS api_audit_log_archive LIKE api_audit_log;

-- Archive logs older than 1 year
INSERT INTO api_audit_log_archive
SELECT * FROM api_audit_log
WHERE request_timestamp < DATE_SUB(NOW(), INTERVAL 365 DAY);

-- Delete archived logs
DELETE FROM api_audit_log
WHERE request_timestamp < DATE_SUB(NOW(), INTERVAL 365 DAY);

-- Optimize table
OPTIMIZE TABLE api_audit_log;
```

### Monitor Table Size

```sql
SELECT 
    table_rows,
    ROUND(((data_length + index_length) / 1024 / 1024), 2) AS size_mb,
    ROUND((data_length / 1024 / 1024), 2) AS data_mb,
    ROUND((index_length / 1024 / 1024), 2) AS index_mb
FROM information_schema.TABLES
WHERE table_schema = 'magic_auth' AND table_name = 'api_audit_log';
```

---

## Middleware Files

**Location:** `src/middleware/`

1. **api_audit.py** - Main audit logging middleware
2. **auth_context.py** - Extracts user context from Bearer token
3. **request_validation.py** - Validates requests and tracks time

**Utility:** `src/Util/api_audit_logger.py` - Logging functions and filters

**Documentation:** `src/middleware/README.md` - Complete middleware guide

---

**Last Updated:** October 26, 2025  
**Version:** 2.0 (Middleware-Based)  
**System:** Magic Auth Multi-Project Authentication
