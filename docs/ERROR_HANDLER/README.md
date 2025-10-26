# Error Handler System Documentation

## Overview

Centralized, production-ready error handling system with automatic function context extraction, UUID masking, and comprehensive debugging information.

---

## 📚 Documentation Files

### **Start Here**
**[COMPLETE_IMPLEMENTATION.md](./COMPLETE_IMPLEMENTATION.md)** - **READ THIS FIRST**
- Complete implementation guide
- How everything works
- Fixes applied
- Testing checklist
- **Single source of truth**

### Reference Guides
- **[ERROR_CODES.md](./ERROR_CODES.md)** - Complete error code catalog
- **[IMPLEMENTATION_GUIDE.md](./IMPLEMENTATION_GUIDE.md)** - How to use the error handler
- **[RESPONSE_EXAMPLES.md](./RESPONSE_EXAMPLES.md)** - Example error responses

### Status & History
- **[REFACTORING_STATUS.md](./REFACTORING_STATUS.md)** - Current implementation status
- **[IMPLEMENTATION_REVIEW.md](./IMPLEMENTATION_REVIEW.md)** - Detailed review
- **[REFACTORING_SUMMARY.md](./REFACTORING_SUMMARY.md)** - Changes summary

---

## Quick Start

### Raise an Exception (Route Handler)
```python
@router.get("/users/{user_id}")
async def get_user(user_id: str):
    user = get_user_by_id(user_id)
    if not user:
        raise NotFoundError(
            message="User not found",
            error_code=ErrorCode.USER_NOT_FOUND,
            details={"user_id": user_id}
        )
    return user
```

**That's it!** The middleware automatically:
- Extracts function name: `"get_user"`
- Extracts parameters: `{"user_id": "..."}`
- Masks UUIDs
- Adds API context (endpoint, method, etc.)
- Builds complete error response

### Database Operation with Error Handling
```python
# Raises exception on error
user = handle_db_operation(
    lambda: get_user_by_id(user_id),
    error_context="fetch user",
    not_found_message=f"User not found: {user_id}"
)
```

### Database Operation with Graceful Fallback
```python
# Returns 0 on error instead of raising
count = handle_db_operation(
    lambda: count_users(),
    error_context="count users",
    default_return=0
)
```

---

## Error Response Structure

```json
{
    "status": "error",
    "error": {
        "code": "NF_4001",
        "category": "not_found",
        "message": "User not found",
        "details": {
            "context": {"user_id": "..."},
            "function": {
                "name": "get_user",
                "params": {"user_id": "usr-[1234]...[5678]"}
            },
            "error_metadata": {...},
            "api_error": {...}
        },
        "trace": "..." (DEBUG_MODE only)
    }
}
```

---

## Exception Classes

| Class | Status Code | Category | Use For |
|-------|------------|----------|---------|
| `AuthenticationError` | 401 | authentication | Invalid credentials, expired sessions |
| `AuthorizationError` | 403 | authorization | Insufficient permissions, access denied |
| `ValidationError` | 400 | validation | Invalid input, malformed data |
| `NotFoundError` | 404 | not_found | Resource doesn't exist |
| `ConflictError` | 409 | conflict | Duplicates, state conflicts |
| `DatabaseError` | 500 | database | Database operation failures |
| `InternalError` | 500 | internal | Unexpected server errors |

---

## Features

### ✅ Automatic Function Context
- Function name extracted from exception traceback
- Parameters extracted from frame locals
- No manual `error_context` needed in routes

### ✅ Database Error Handling
- Detailed MySQL error information
- Constraint violation parsing
- Graceful fallback with `default_return`

### ✅ Security
- UUID masking in all contexts
- Sensitive data sanitization
- DEBUG_MODE for development only

### ✅ Complete Debugging Info
- Function name and parameters
- Endpoint and HTTP method
- Query parameters
- Database error details
- Full traceback (DEBUG_MODE)

---

## Critical Fixes (2025-10-26)

### Fix #1: Function Context Extraction
**Problem:** Used `inspect.stack()` which doesn't capture route handler frames  
**Solution:** Use `sys.exc_info()` to walk exception's traceback  
**File:** `src/middleware/error_handler.py`

### Fix #2: Missing `default_return` Parameter
**Problem:** `handle_db_operation()` called with unknown parameter  
**Solution:** Added `default_return` parameter for graceful degradation  
**File:** `src/Util/db_error_wrapper.py`

### Fix #3: Database Error Context
**Problem:** `error_context` stored in `details` instead of parameter  
**Solution:** Pass as `error_context` parameter to exception constructor  
**File:** `src/Util/db_error_wrapper.py`

---

## Debug Mode

Enable detailed error information:
```bash
export DEBUG_MODE=true
```

**Production:** Only code, category, message  
**Debug:** Includes details, function, traceback, database errors

---

## Files

### Core Implementation
- `src/Util/error_handler.py` - Exception classes and error codes
- `src/Util/db_error_wrapper.py` - Database operation wrapper
- `src/middleware/error_handler.py` - Global exception handlers

### Routes & Database
- `src/routes/*.py` - Route handlers (no special error handling needed)
- `src/Util/db/*.py` - Database access layer (uses `handle_db_operation`)

---

## Testing

```bash
# Test route error with function context
curl http://localhost:8000/roles/users/me/role

# Test database operation with default return
curl http://localhost:8000/users/list?limit=10&offset=0

# Test database error
curl -X POST http://localhost:8000/roles -F "role_name=admin"
```

**Verify:**
1. ✅ `details.function` present in responses
2. ✅ Function name matches route handler
3. ✅ Parameters extracted correctly
4. ✅ UUIDs masked
5. ✅ `default_return` works for analytics

---

## Support

- **Complete Guide:** [COMPLETE_IMPLEMENTATION.md](./COMPLETE_IMPLEMENTATION.md)
- **Error Codes:** [ERROR_CODES.md](./ERROR_CODES.md)
- **Examples:** [RESPONSE_EXAMPLES.md](./RESPONSE_EXAMPLES.md)
- **Status:** [REFACTORING_STATUS.md](./REFACTORING_STATUS.md)

---

**Status:** ✅ 100% Complete - Production Ready  
**Last Updated:** 2025-10-26 (Deep Review + Final Cleanup Completed)  
**Version:** 2.0
