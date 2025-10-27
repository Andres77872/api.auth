# API Audit Log - Quick Start Guide

**Simple, Automatic HTTP Request/Response Auditing**

---

## Overview

✅ **The audit system is already installed and active!** All API requests and responses are automatically logged via middleware. No manual logging needed in routes.

### Key Concept

```
HTTP Request → Auth Context → API Audit → Route Handler → Background Logging → Response
```

Everything is automatic. The middleware is already configured in `src/main.py`.

---

## Current Setup

### ✅ Middleware Already Installed

The middleware is already active in `src/main.py`:

```python
# File: src/main.py
from src.middleware import (
    AuthContextMiddleware,
    APIAuditMiddleware,
    RequestValidationMiddleware
)

app = FastAPI()

# Middleware stack (already configured)
app.add_middleware(RequestValidationMiddleware)
app.add_middleware(APIAuditMiddleware)  # ← Logs all requests
app.add_middleware(AuthContextMiddleware)
```

**Files:**
- `src/middleware/api_audit.py` - Main audit logging middleware
- `src/middleware/auth_context.py` - Extracts user context
- `src/Util/api_audit_logger.py` - Logging utility functions

### ✅ Database Already Configured

The `api_audit_log` table and stored procedures already exist:

```bash
# Verify setup
mysql -u user -p magic_auth -e "
SELECT COUNT(*) FROM information_schema.tables 
WHERE table_schema = 'magic_auth' AND table_name = 'api_audit_log';
"
# Should return: 1

# Check stored procedures
mysql -u user -p magic_auth -e "
SELECT routine_name FROM information_schema.routines 
WHERE routine_schema = 'magic_auth' AND routine_name LIKE '%audit%';
"
# Should return: 8 procedures
```

---

## Testing

### Verify Logging is Working

```bash
# Make a test request
curl -X GET http://localhost:8000/api/v1/users

# Check if logged
mysql -u user -p magic_auth -e "
SELECT * FROM api_audit_log 
WHERE endpoint_path = '/api/v1/users' 
ORDER BY request_timestamp DESC 
LIMIT 1;
"
```

### Check Recent Logs

```bash
mysql -u user -p magic_auth -e "
SELECT 
    request_timestamp,
    http_method,
    endpoint_path,
    user_id,
    response_status,
    duration_ms
FROM api_audit_log
ORDER BY request_timestamp DESC
LIMIT 20;
"
```

---

## Querying Audit Logs

### Example 1: Get Recent Logs

```python
from src.Util.db_config import get_connection

def get_recent_audit_logs(limit=50, days=7):
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_get_audit_logs', (
            limit,      # limit
            0,          # offset
            None,       # user_id
            None,       # project_id
            None,       # endpoint_path
            None,       # http_method
            None,       # status_code
            None,       # is_success
            None,       # security_event
            days        # days
        ))
        
        for result in cursor.stored_results():
            return list(result.fetchall())
```

### Example 2: Get Failed Requests

```python
def get_failed_requests(limit=50, days=7):
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_get_failed_requests', (limit, 0, days))
        
        for result in cursor.stored_results():
            return list(result.fetchall())
```

### Example 3: Get User Activity

```python
def get_user_activity(user_id: str, days=30):
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_get_user_activity_summary', (user_id, days))
        
        results = []
        for result in cursor.stored_results():
            results.append(list(result.fetchall()))
        return results
```

### Example 4: Get Security Events

```python
def get_security_events(limit=100, days=30):
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_get_security_events', (limit, 0, days))
        
        for result in cursor.stored_results():
            return list(result.fetchall())
```

---

## Configuration

### Exclude Endpoints

Edit `src/Util/api_audit_logger.py` to exclude endpoints:

```python
EXCLUDED_PATHS = [
    '/ping',
    '/health',
    '/metrics',
    '/docs',
    '/redoc',
    '/openapi.json',
    '/',
    # Add more here
]
```

### Customize Security Events

Edit `src/Util/api_audit_logger.py`, method `is_security_event()` to customize:

```python
@staticmethod
def is_security_event(path: str, method: str, status_code: int, user_type: Optional[str]) -> bool:
    # Your custom logic here
    if '/critical-endpoint' in path:
        return True
    # ...existing rules...
```

---

## Querying (Optional)

If you need to query logs programmatically, use stored procedures:

```python
from fastapi import APIRouter, Depends, HTTPException
from src.Util.Seccurity import get_current_admin
from src.Util.db_config import get_connection

router = APIRouter(prefix="/api/v1/admin/audit", tags=["Audit Logs"])

@router.get("/logs")
async def get_audit_logs(
    limit: int = 50,
    offset: int = 0,
    user_id: str = None,
    endpoint: str = None,
    method: str = None,
    status: int = None,
    days: int = 7,
    current_admin = Depends(get_current_admin)
):
    """Get audit logs with filtering"""
    
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_get_audit_logs', (
            limit, offset, user_id, None, endpoint, method,
            status, None, None, days
        ))
        
        for result in cursor.stored_results():
            logs = list(result.fetchall())
            return {"logs": logs, "count": len(logs)}

@router.get("/statistics")
async def get_audit_statistics(
    days: int = 7,
    current_admin = Depends(get_current_admin)
):
    """Get audit statistics"""
    
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_get_audit_statistics', (days,))
        
        stats = {}
        result_sets = []
        for result in cursor.stored_results():
            result_sets.append(list(result.fetchall()))
        
        if len(result_sets) >= 4:
            stats['summary'] = result_sets[0][0] if result_sets[0] else {}
            stats['by_method'] = result_sets[1]
            stats['top_endpoints'] = result_sets[2]
            stats['status_codes'] = result_sets[3]
        
        return stats

@router.get("/security-events")
async def get_security_events(
    limit: int = 100,
    offset: int = 0,
    days: int = 30,
    current_admin = Depends(get_current_admin)
):
    """Get flagged security events"""
    
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_get_security_events', (limit, offset, days))
        
        for result in cursor.stored_results():
            events = list(result.fetchall())
            return {"events": events, "count": len(events)}

@router.get("/failed-requests")
async def get_failed_requests(
    limit: int = 50,
    offset: int = 0,
    days: int = 7,
    current_admin = Depends(get_current_admin)
):
    """Get failed API requests"""
    
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_get_failed_requests', (limit, offset, days))
        
        for result in cursor.stored_results():
            requests = list(result.fetchall())
            return {"failed_requests": requests, "count": len(requests)}

@router.get("/user/{user_hash}")
async def get_user_audit_activity(
    user_hash: str,
    days: int = 30,
    current_admin = Depends(get_current_admin)
):
    """Get audit activity for specific user"""
    
    # Get user ID from hash
    from src.Util.db import get_user_by_hash
    user = get_user_by_hash(user_hash)
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    
    with get_connection() as conn:
        cursor = conn.cursor(dictionary=True)
        cursor.callproc('sp_get_user_activity_summary', (user.id, days))
        
        summary = None
        recent_activity = []
        
        result_sets = []
        for result in cursor.stored_results():
            result_sets.append(list(result.fetchall()))
        
        if len(result_sets) >= 2:
            summary = result_sets[0][0] if result_sets[0] else {}
            recent_activity = result_sets[1]
        
        return {
            "user_hash": user_hash,
            "summary": summary,
            "recent_activity": recent_activity
        }
```

---

## Usage Examples

### Monitor Failed Logins

```sql
SELECT 
    request_timestamp,
    client_ip,
    user_agent,
    JSON_EXTRACT(request_body, '$.username') as attempted_username
FROM api_audit_log
WHERE endpoint_path = '/api/v1/auth/login'
  AND is_success = FALSE
  AND request_timestamp >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY request_timestamp DESC;
```

### Track Admin Actions

```sql
SELECT 
    request_timestamp,
    user_id,
    http_method,
    endpoint_path,
    response_status,
    duration_ms
FROM api_audit_log
WHERE user_type IN ('root', 'admin')
  AND http_method IN ('POST', 'PUT', 'DELETE', 'PATCH')
  AND request_timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)
ORDER BY request_timestamp DESC;
```

### Find Slow Endpoints

```sql
SELECT 
    endpoint_path,
    http_method,
    COUNT(*) as request_count,
    AVG(duration_ms) as avg_duration,
    MAX(duration_ms) as max_duration
FROM api_audit_log
WHERE request_timestamp >= DATE_SUB(NOW(), INTERVAL 7 DAY)
  AND duration_ms IS NOT NULL
GROUP BY endpoint_path, http_method
HAVING avg_duration > 500
ORDER BY avg_duration DESC
LIMIT 20;
```

---

## Configuration

### Exclude Endpoints from Logging

Modify middleware to skip certain endpoints:

```python
class APIAuditMiddleware(BaseHTTPMiddleware):
    EXCLUDED_PATHS = [
        '/health',
        '/metrics',
        '/favicon.ico',
        '/docs',
        '/redoc',
        '/openapi.json'
    ]
    
    async def dispatch(self, request: Request, call_next):
        # Skip excluded paths
        if any(request.url.path.startswith(path) for path in self.EXCLUDED_PATHS):
            return await call_next(request)
        
        # ... rest of logging logic
```

### Sample Rate (Log Only X% of Requests)

```python
import random

class APIAuditMiddleware(BaseHTTPMiddleware):
    SAMPLE_RATE = 0.1  # Log 10% of GET requests
    
    async def dispatch(self, request: Request, call_next):
        # Always log non-GET requests
        should_log = request.method != 'GET' or random.random() < self.SAMPLE_RATE
        
        if not should_log:
            return await call_next(request)
        
        # ... rest of logging logic
```

---

## Summary

✅ **Already configured and active** - No setup needed  
✅ **Logs all API requests automatically** - Via middleware  
✅ **Background execution** - Non-blocking  
✅ **Sensitive data filtered** - Passwords, tokens protected  
✅ **Security events flagged** - Admin actions, failures, deletes  
✅ **Easy to query** - 8 stored procedures + direct SQL

**Files:**
- `src/middleware/api_audit.py` - Audit middleware
- `src/middleware/auth_context.py` - User context extraction
- `src/Util/api_audit_logger.py` - Logging utilities

**Documentation:**
- See [IMPLEMENTATION.md](./IMPLEMENTATION.md) for details
- See [USAGE.md](./USAGE.md) for querying examples
- See `src/middleware/README.md` for middleware docs

---

**Documentation Version:** 2.0 (Middleware-Based)  
**Last Updated:** October 26, 2025  
**System:** Magic Auth Multi-Project Authentication  
**Status:** ✅ Active and Running
