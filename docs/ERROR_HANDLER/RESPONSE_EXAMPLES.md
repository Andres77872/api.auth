# Error Response Examples

**Real-world examples of error responses for every scenario**

---

## 📋 Standard Response Structure

### Success Response
```json
{
  "success": true,
  "message": "Operation completed successfully",
  "data": {
    // Your response data
  }
}
```

### Error Response (Production)
```json
{
  "success": false,
  "error": {
    "message": "User-friendly error message",
    "error_code": "CATEGORY_NNNN",
    "category": "ERROR_CATEGORY",
    "timestamp": "2025-10-26T10:30:00.123456Z"
  }
}
```

### Error Response (Debug Mode)
```json
{
  "success": false,
  "error": {
    "message": "User-friendly error message",
    "error_code": "CATEGORY_NNNN",
    "category": "ERROR_CATEGORY",
    "timestamp": "2025-10-26T10:30:00.123456Z",
    "details": {
      "context": {
        "field": "value",
        "masked_uuid": "abc12...xyz89"
      },
      "function": {
        "name": "function_name",
        "params": {
          "param1": "value1",
          "param2": "***"
        }
      },
      "error_metadata": {
        "error_class": "NotFoundError",
        "error_code": "NF_4001",
        "category": "not_found",
        "status_code": 404
      }
    },
    "trace": "Full Python traceback..."
  }
}
```

**Note:** For database errors, `database_error` replaces `original_error` to avoid redundancy.

### Database Error Example (Debug Mode)
```json
{
  "status": "error",
  "error": {
    "code": "DB_6005",
    "category": "database",
    "message": "A roles with role_name 'admin' already exists",
    "details": {
      "context": {
        "constraint_type": "duplicate",
        "field": "role_name",
        "value": "admin",
        "table": "roles",
        "mysql_error_code": 1062
      },
      "function": {
        "name": "create_role",
        "params": {
          "role_name": "admin"
        }
      },
      "database_error": {
        "error_type": "IntegrityError",
        "mysql_error_code": 1062,
        "mysql_error_message": "Duplicate entry 'admin' for key 'roles.uk_role_name'",
        "constraint_type": "duplicate_key"
      },
      "error_metadata": {
        "error_class": "ConflictError",
        "error_code": "CONF_5004",
        "category": "conflict",
        "status_code": 409
      }
    },
    "trace": "Traceback (most recent call last):\n  ..."
  }
}
```

**Key improvements:**
- ✅ `database_error` contains all MySQL-specific details
- ✅ `original_error` is omitted (redundant with database_error)
- ✅ `function` captures the function name and parameters automatically
- ✅ `context` contains user-provided details

---

## 🔐 Authentication Errors (401)

### Invalid Credentials
```json
{
  "success": false,
  "error": {
    "message": "Invalid username or password",
    "error_code": "AUTH_1001",
    "category": "AUTHENTICATION",
    "timestamp": "2025-10-26T10:30:00Z"
  }
}
```

### Session Expired
```json
{
  "success": false,
  "error": {
    "message": "Your session has expired. Please log in again",
    "error_code": "AUTH_1002",
    "category": "AUTHENTICATION",
    "timestamp": "2025-10-26T10:30:00Z"
  }
}
```

### Invalid Session Token
```json
{
  "success": false,
  "error": {
    "message": "Invalid or expired session token",
    "error_code": "AUTH_1003",
    "category": "AUTHENTICATION",
    "timestamp": "2025-10-26T10:30:00Z"
  }
}
```

---

## 🚫 Authorization Errors (403)

### Insufficient Permissions
```json
{
  "success": false,
  "error": {
    "message": "You do not have permission to perform this action",
    "error_code": "AUTHZ_2002",
    "category": "AUTHORIZATION",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "required_permission": "project:delete",
      "user_permissions": ["project:read", "project:update"]
    }
  }
}
```

### Project Access Denied
```json
{
  "success": false,
  "error": {
    "message": "You do not have access to this project",
    "error_code": "AUTHZ_2003",
    "category": "AUTHORIZATION",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "project_hash": "abc12...xyz89"
    }
  }
}
```

---

## ⚠️ Validation Errors (400)

### Missing Required Field
```json
{
  "success": false,
  "error": {
    "message": "Username is required",
    "error_code": "VAL_3002",
    "category": "VALIDATION",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "field": "username",
      "required": true
    }
  }
}
```

### Invalid Email Format
```json
{
  "success": false,
  "error": {
    "message": "Invalid email format",
    "error_code": "VAL_3005",
    "category": "VALIDATION",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "field": "email",
      "provided": "invalid-email",
      "expected_format": "user@example.com"
    }
  }
}
```

### Invalid UUID
```json
{
  "success": false,
  "error": {
    "message": "Invalid UUID format",
    "error_code": "VAL_3004",
    "category": "VALIDATION",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "field": "user_hash",
      "provided": "not-a-uuid"
    }
  }
}
```

### Multiple Validation Errors
```json
{
  "success": false,
  "error": {
    "message": "Validation failed for multiple fields",
    "error_code": "VAL_3001",
    "category": "VALIDATION",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "errors": [
        {"field": "username", "message": "Username is required"},
        {"field": "email", "message": "Invalid email format"},
        {"field": "password", "message": "Password too weak"}
      ]
    }
  }
}
```

---

## 🔍 Not Found Errors (404)

### User Not Found
```json
{
  "success": false,
  "error": {
    "message": "User not found",
    "error_code": "NF_4001",
    "category": "NOT_FOUND",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "user_hash": "abc12...xyz89"
    }
  }
}
```

### Project Not Found
```json
{
  "success": false,
  "error": {
    "message": "Project not found",
    "error_code": "NF_4002",
    "category": "NOT_FOUND",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "project_hash": "def34...uvw56"
    }
  }
}
```

### Resource Not Found (Generic)
```json
{
  "success": false,
  "error": {
    "message": "The requested resource could not be found",
    "error_code": "NF_4004",
    "category": "NOT_FOUND",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "resource_type": "permission_group",
      "resource_id": "123"
    }
  }
}
```

---

## ⚔️ Conflict Errors (409)

### Username Already Exists
```json
{
  "success": false,
  "error": {
    "message": "Username already exists",
    "error_code": "CONF_5001",
    "category": "CONFLICT",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "field": "username",
      "value": "existing_user"
    }
  }
}
```

### Email Already Exists
```json
{
  "success": false,
  "error": {
    "message": "Email address already registered",
    "error_code": "CONF_5002",
    "category": "CONFLICT",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "field": "email",
      "value": "user@example.com"
    }
  }
}
```

### Duplicate Entry
```json
{
  "success": false,
  "error": {
    "message": "This entry already exists",
    "error_code": "CONF_5004",
    "category": "CONFLICT",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "table": "user_group_members",
      "constraint": "unique_user_group",
      "conflicting_values": {
        "user_id": "123",
        "group_id": "456"
      }
    }
  }
}
```

---

## 💾 Database Errors (500)

### Connection Error
```json
{
  "success": false,
  "error": {
    "message": "Unable to connect to database",
    "error_code": "DB_6001",
    "category": "DATABASE",
    "timestamp": "2025-10-26T10:30:00Z"
  }
}
```

**Debug Mode:**
```json
{
  "success": false,
  "error": {
    "message": "Unable to connect to database",
    "error_code": "DB_6001",
    "category": "DATABASE",
    "timestamp": "2025-10-26T10:30:00Z",
    "stack_trace": "Traceback...",
    "context": "get_connection()",
    "original_error": "pymysql.err.OperationalError: (2003, \"Can't connect to MySQL server...\")"
  }
}
```

### Query Error
```json
{
  "success": false,
  "error": {
    "message": "Database query failed",
    "error_code": "DB_6002",
    "category": "DATABASE",
    "timestamp": "2025-10-26T10:30:00Z"
  }
}
```

**Debug Mode:**
```json
{
  "success": false,
  "error": {
    "message": "Database query failed",
    "error_code": "DB_6002",
    "category": "DATABASE",
    "timestamp": "2025-10-26T10:30:00Z",
    "stack_trace": "Traceback...",
    "context": "update_user(user_id=123)",
    "original_error": "pymysql.err.ProgrammingError: (1146, \"Table 'users' doesn't exist\")"
  }
}
```

### Redis Connection Error
```json
{
  "success": false,
  "error": {
    "message": "Unable to connect to cache server",
    "error_code": "DB_6007",
    "category": "DATABASE",
    "timestamp": "2025-10-26T10:30:00Z"
  }
}
```

---

## 🔥 Internal Errors (500)

### Generic Internal Error
```json
{
  "success": false,
  "error": {
    "message": "An internal error occurred. Please try again later",
    "error_code": "INT_9999",
    "category": "INTERNAL",
    "timestamp": "2025-10-26T10:30:00Z"
  }
}
```

**Debug Mode:**
```json
{
  "success": false,
  "error": {
    "message": "An internal error occurred",
    "error_code": "INT_9999",
    "category": "INTERNAL",
    "timestamp": "2025-10-26T10:30:00Z",
    "stack_trace": "Traceback (most recent call last):\n  File \"/app/src/routes/users.py\", line 42...",
    "context": "create_user(username='testuser', email='test@example.com')",
    "details": {
      "request_id": "req_abc123",
      "endpoint": "/api/users",
      "method": "POST"
    },
    "original_error": "KeyError: 'missing_key'"
  }
}
```

---

## 🎯 Real-World Scenarios

### Scenario 1: User Registration with Existing Email
**Request:**
```http
POST /api/auth/register
Content-Type: application/json

{
  "username": "newuser",
  "email": "existing@example.com",
  "password": "securepass123"
}
```

**Response:**
```json
{
  "success": false,
  "error": {
    "message": "Email address already registered",
    "error_code": "CONF_5002",
    "category": "CONFLICT",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "field": "email"
    }
  }
}
```

---

### Scenario 2: Updating User Without Authentication
**Request:**
```http
PUT /api/users/usr-abc123
Content-Type: application/json

{
  "username": "updated_name"
}
```

**Response:**
```json
{
  "success": false,
  "error": {
    "message": "Authentication required",
    "error_code": "AUTH_1003",
    "category": "AUTHENTICATION",
    "timestamp": "2025-10-26T10:30:00Z"
  }
}
```

---

### Scenario 3: Deleting Project Without Permission
**Request:**
```http
DELETE /api/projects/prj-xyz789
Authorization: Bearer <valid_token>
```

**Response:**
```json
{
  "success": false,
  "error": {
    "message": "You do not have permission to delete this project",
    "error_code": "AUTHZ_2002",
    "category": "AUTHORIZATION",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "required_permission": "project:delete",
      "user_role": "viewer",
      "project_hash": "prj-x...9"
    }
  }
}
```

---

### Scenario 4: Invalid Search Query
**Request:**
```http
GET /api/projects/search?q=
```

**Response:**
```json
{
  "success": false,
  "error": {
    "message": "Search term cannot be empty",
    "error_code": "VAL_3002",
    "category": "VALIDATION",
    "timestamp": "2025-10-26T10:30:00Z",
    "details": {
      "field": "search_term",
      "min_length": 1
    }
  }
}
```

---

## 🔧 Testing Error Responses

### Using cURL
```bash
# Test authentication error
curl -X GET http://localhost:8000/api/users/me \
  -H "Authorization: Bearer invalid_token"

# Test validation error
curl -X POST http://localhost:8000/api/users \
  -H "Content-Type: application/json" \
  -d '{"email": "invalid-email"}'

# Test not found error
curl -X GET http://localhost:8000/api/users/nonexistent-id
```

### Using Python requests
```python
import requests

# Test conflict error
response = requests.post(
    "http://localhost:8000/api/auth/register",
    json={
        "username": "existing_user",
        "email": "new@example.com",
        "password": "pass123"
    }
)

if not response.json()["success"]:
    error = response.json()["error"]
    print(f"Error {error['error_code']}: {error['message']}")
```

---

## 📊 Error Response Statistics

**Common HTTP Status Codes:**
- 400 Bad Request: 35% (Validation errors)
- 401 Unauthorized: 25% (Authentication)
- 403 Forbidden: 15% (Authorization)
- 404 Not Found: 15% (Resource not found)
- 409 Conflict: 5% (Duplicates)
- 500 Internal Server Error: 5% (Database/internal)

---

## 🔗 Related Documentation

- **ERROR_CODES.md** - Complete error code reference
- **IMPLEMENTATION_GUIDE.md** - How to raise errors
- **README.md** - System overview

---

**Last Updated:** 2025-10-26  
**Middleware:** `src/middleware/error_handler.py`  
**Error Handler:** `src/Util/error_handler.py`

