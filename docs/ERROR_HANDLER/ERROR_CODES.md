# Error Codes Reference

**Complete catalog of all error codes used in the system**

**Source:** `src/Util/error_handler.py`

---

## Error Code Format

```
CATEGORY_NNNN

Examples:
- AUTH_1001  = Authentication errors (1xxx)
- AUTHZ_2001 = Authorization errors (2xxx)
- VAL_3001   = Validation errors (3xxx)
- NF_4001    = Not Found errors (4xxx)
- CONF_5001  = Conflict errors (5xxx)
- DB_6001    = Database errors (6xxx)
- INT_7001   = Internal errors (7xxx)
- EXT_8001   = External service errors (8xxx)
```

---

## 🔐 Authentication Errors (AUTH_1xxx) → HTTP 401

| Code | Name | Description | HTTP Status |
|------|------|-------------|-------------|
| AUTH_1001 | INVALID_CREDENTIALS | Invalid username or password | 401 |
| AUTH_1002 | SESSION_EXPIRED | User session has expired | 401 |
| AUTH_1003 | SESSION_INVALID | Session token is invalid | 401 |
| AUTH_1004 | TOKEN_INVALID | JWT token is invalid or malformed | 401 |
| AUTH_1005 | ACCOUNT_INACTIVE | User account is inactive | 401 |
| AUTH_1006 | ACCOUNT_LOCKED | User account is locked | 401 |
| AUTH_1007 | PASSWORD_RESET_REQUIRED | Password reset is required | 401 |
| AUTH_1008 | MFA_REQUIRED | Multi-factor authentication required | 401 |
| AUTH_1009 | MFA_INVALID | MFA code is invalid | 401 |

### Usage Example:
```python
raise AuthenticationError(
    message="Invalid or expired session",
    error_code=ErrorCode.SESSION_INVALID
)
```

---

## 🚫 Authorization Errors (AUTHZ_2xxx) → HTTP 403

| Code | Name | Description | HTTP Status |
|------|------|-------------|-------------|
| AUTHZ_2001 | ACCESS_DENIED | Access denied to resource | 403 |
| AUTHZ_2002 | INSUFFICIENT_PERMISSIONS | User lacks required permissions | 403 |
| AUTHZ_2003 | PROJECT_ACCESS_DENIED | No access to project | 403 |
| AUTHZ_2004 | GROUP_ACCESS_DENIED | No access to group | 403 |
| AUTHZ_2005 | RESOURCE_ACCESS_DENIED | No access to specific resource | 403 |
| AUTHZ_2006 | ROLE_ASSIGNMENT_DENIED | Cannot assign this role | 403 |
| AUTHZ_2007 | PERMISSION_DENIED | Specific permission denied | 403 |

### Usage Example:
```python
raise AuthorizationError(
    message="Insufficient permissions to delete project",
    error_code=ErrorCode.INSUFFICIENT_PERMISSIONS
)
```

---

## ⚠️ Validation Errors (VAL_3xxx) → HTTP 400

| Code | Name | Description | HTTP Status |
|------|------|-------------|-------------|
| VAL_3001 | INVALID_INPUT | General invalid input | 400 |
| VAL_3002 | MISSING_REQUIRED_FIELD | Required field is missing | 400 |
| VAL_3003 | INVALID_FORMAT | Invalid format | 400 |
| VAL_3004 | INVALID_UUID | UUID format is invalid | 400 |
| VAL_3005 | INVALID_EMAIL | Email format is invalid | 400 |
| VAL_3006 | INVALID_USERNAME | Username format is invalid | 400 |
| VAL_3007 | WEAK_PASSWORD | Password doesn't meet requirements | 400 |
| VAL_3008 | INVALID_DATE | Date format is invalid | 400 |
| VAL_3009 | INVALID_RANGE | Value out of range | 400 |
| VAL_3010 | INVALID_LENGTH | String length invalid | 400 |
| VAL_3011 | INVALID_TYPE | Data type is invalid | 400 |
| VAL_3012 | INVALID_ENUM_VALUE | Enum value not recognized | 400 |

### Usage Example:
```python
raise ValidationError(
    message="Username cannot be empty",
    error_code=ErrorCode.MISSING_REQUIRED_FIELD,
    details={"field": "username"}
)
```

---

## 🔍 Not Found Errors (NF_4xxx) → HTTP 404

| Code | Name | Description | HTTP Status |
|------|------|-------------|-------------|
| NF_4001 | USER_NOT_FOUND | User does not exist | 404 |
| NF_4002 | PROJECT_NOT_FOUND | Project does not exist | 404 |
| NF_4003 | GROUP_NOT_FOUND | Group does not exist | 404 |
| NF_4004 | RESOURCE_NOT_FOUND | Generic resource not found | 404 |
| NF_4005 | PERMISSION_NOT_FOUND | Permission does not exist | 404 |
| NF_4006 | SESSION_NOT_FOUND | Session does not exist | 404 |
| NF_4007 | ROLE_NOT_FOUND | Role does not exist | 404 |
| NF_4008 | ENDPOINT_NOT_FOUND | API endpoint not found | 404 |
| NF_4009 | USER_TYPE_NOT_FOUND | User type not recognized | 404 |

### Usage Example:
```python
raise NotFoundError(
    message=f"User not found",
    error_code=ErrorCode.USER_NOT_FOUND
)
```

---

## ⚔️ Conflict Errors (CONF_5xxx) → HTTP 409

| Code | Name | Description | HTTP Status |
|------|------|-------------|-------------|
| CONF_5001 | USERNAME_EXISTS | Username already exists | 409 |
| CONF_5002 | EMAIL_EXISTS | Email already exists | 409 |
| CONF_5003 | RESOURCE_EXISTS | Resource already exists | 409 |
| CONF_5004 | DUPLICATE_ENTRY | Duplicate database entry | 409 |
| CONF_5005 | CONSTRAINT_VIOLATION | Database constraint violated | 409 |
| CONF_5006 | ROLE_ALREADY_ASSIGNED | Role already assigned to user | 409 |
| CONF_5007 | PERMISSION_ALREADY_GRANTED | Permission already granted | 409 |
| CONF_5008 | STATE_CONFLICT | Resource in conflicting state | 409 |

### Usage Example:
```python
raise ConflictError(
    message="Username already exists",
    error_code=ErrorCode.USERNAME_EXISTS
)
```

---

## 💾 Database Errors (DB_6xxx) → HTTP 500

| Code | Name | Description | HTTP Status |
|------|------|-------------|-------------|
| DB_6001 | DB_CONNECTION_ERROR | Cannot connect to database | 500 |
| DB_6002 | DB_QUERY_ERROR | Database query failed | 500 |
| DB_6003 | DB_TRANSACTION_ERROR | Transaction failed | 500 |
| DB_6004 | DB_TIMEOUT | Database operation timeout | 500 |
| DB_6005 | DB_INTEGRITY_ERROR | Database integrity constraint | 500 |
| DB_6006 | DB_DEADLOCK | Database deadlock detected | 500 |
| DB_6007 | REDIS_CONNECTION_ERROR | Cannot connect to Redis | 500 |
| DB_6008 | REDIS_OPERATION_ERROR | Redis operation failed | 500 |

### Usage Example:
```python
raise DatabaseError(
    message="Failed to connect to database",
    error_code=ErrorCode.DB_CONNECTION_ERROR
)
```

---

## 🔥 Internal Errors (INT_7xxx) → HTTP 500

| Code | Name | Description | HTTP Status |
|------|------|-------------|-------------|
| INT_7001 | INTERNAL_ERROR | Generic internal error | 500 |
| INT_7002 | CONFIGURATION_ERROR | Invalid configuration | 500 |
| INT_7003 | INITIALIZATION_ERROR | Service failed to initialize | 500 |
| INT_7004 | PROCESSING_ERROR | Data processing failed | 500 |
| INT_7005 | ENCRYPTION_ERROR | Encryption operation failed | 500 |
| INT_7006 | DECRYPTION_ERROR | Decryption operation failed | 500 |
| INT_7007 | SERIALIZATION_ERROR | Cannot serialize data | 500 |
| INT_7008 | DESERIALIZATION_ERROR | Cannot deserialize data | 500 |

### Usage Example:
```python
raise InternalError(
    message="Failed to process request",
    error_code=ErrorCode.INTERNAL_ERROR
)
```

---

## 🌐 External Service Errors (EXT_8xxx) → HTTP 502/503

| Code | Name | Description | HTTP Status |
|------|------|-------------|-------------|
| EXT_8001 | EXTERNAL_SERVICE_ERROR | External service unavailable | 502 |
| EXT_8002 | API_REQUEST_FAILED | External API request failed | 502 |
| EXT_8003 | NETWORK_ERROR | Network communication error | 503 |
| EXT_8004 | TIMEOUT_ERROR | External service timeout | 504 |
| EXT_8005 | RATE_LIMIT_EXCEEDED | Rate limit exceeded | 429 |

### Usage Example:
```python
raise ExternalError(
    message="External API unavailable",
    error_code=ErrorCode.EXTERNAL_SERVICE_ERROR
)
```

---

## 🎯 Special Error Code

| Code | Name | Description | HTTP Status |
|------|------|-------------|-------------|
| INT_9999 | INTERNAL_ERROR | Catch-all for unexpected errors | 500 |

---

## 📊 Error Response Format

### Production Mode
```json
{
  "success": false,
  "error": {
    "message": "User not found",
    "error_code": "NF_4001",
    "category": "NOT_FOUND",
    "timestamp": "2025-10-26T10:30:00.123456Z"
  }
}
```

### Debug Mode (Additional Fields)
```json
{
  "success": false,
  "error": {
    "message": "User not found",
    "error_code": "NF_4001",
    "category": "NOT_FOUND",
    "timestamp": "2025-10-26T10:30:00.123456Z",
    "stack_trace": "Traceback (most recent call last):\n  File...",
    "context": "get_user_by_id(user_id=abc12...xyz89)",
    "details": {
      "user_hash": "abc12...xyz89",
      "operation": "user_lookup"
    },
    "original_error": "pymysql.err.OperationalError: (2003, ...)"
  }
}
```

---

## 🔧 HTTP Status Code Mapping

| Error Category | HTTP Status | Description |
|----------------|-------------|-------------|
| AUTHENTICATION | 401 | Unauthorized - Invalid/missing credentials |
| AUTHORIZATION | 403 | Forbidden - Insufficient permissions |
| VALIDATION | 400 | Bad Request - Invalid input |
| NOT_FOUND | 404 | Not Found - Resource doesn't exist |
| CONFLICT | 409 | Conflict - Duplicate/constraint violation |
| DATABASE | 500 | Internal Server Error - DB issues |
| INTERNAL | 500 | Internal Server Error - Application issues |
| EXTERNAL | 502/503 | Bad Gateway/Service Unavailable |

---

## 🎓 Quick Reference by Use Case

### User Management
- Creating user → `CONF_5001` (username exists), `CONF_5002` (email exists)
- Updating user → `NF_4001` (not found), `VAL_3002` (missing fields)
- Deleting user → `NF_4001` (not found), `AUTHZ_2002` (no permission)
- Getting user → `NF_4001` (not found)

### Authentication
- Login → `AUTH_1001` (invalid credentials), `AUTH_1005` (inactive account)
- Session validation → `AUTH_1002` (expired), `AUTH_1003` (invalid)
- Logout → `NF_4006` (session not found)

### Authorization
- Permission check → `AUTHZ_2002` (insufficient permissions)
- Project access → `AUTHZ_2003` (project access denied)
- Role assignment → `AUTHZ_2006` (cannot assign role)

### Database Operations
- Connection → `DB_6001` (connection error)
- Query → `DB_6002` (query error)
- Transaction → `DB_6003` (transaction failed)
- Duplicate → `CONF_5004` (duplicate entry)

---

## 📝 Adding New Error Codes

If you need to add a new error code:

1. **Add to** `src/Util/error_handler.py`:
```python
class ErrorCode(str, Enum):
    # Your new code
    NEW_ERROR_CODE = "CATEGORY_NNNN"
```

2. **Update this document** with the new code

3. **Use appropriate HTTP status** based on category

4. **Follow naming convention:**
   - CATEGORY_NNNN format
   - Clear, descriptive name
   - Matches error type

---

## 🔗 Related Documentation

- **IMPLEMENTATION_GUIDE.md** - How to use error codes
- **README.md** - System overview
- **STATUS.md** - Refactoring progress

---

**Source Code:** `src/Util/error_handler.py` (lines 37-130)  
**Last Updated:** 2025-10-26  
**Total Error Codes:** 60+

