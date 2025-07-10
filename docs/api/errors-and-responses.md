# Error Handling & Response Formats

Complete reference for error codes, response formats, and troubleshooting in the Group-Based Multi-Project Authentication API.

## 📋 Overview

The API uses standard HTTP status codes and consistent JSON response formats for both success and error responses.

---

## 🎯 Standard Response Format

### Success Response Structure

All successful API responses follow this format:

```json
{
  "success": true,
  "message": "Optional success message",
  "data": {
    "...": "Endpoint-specific data"
  },
  "timestamp": "2024-01-01T12:00:00Z"
}
```

### Error Response Structure

All error responses follow this format:

```json
{
  "success": false,
  "detail": "Error description",
  "error_code": "SPECIFIC_ERROR_CODE",
  "timestamp": "2024-01-01T12:00:00Z",
  "path": "/api/endpoint",
  "request_id": "req_123456789"
}
```

---

## 🚨 HTTP Status Codes

### 2xx Success Codes

| Code | Meaning | Usage |
|------|---------|-------|
| **200** | OK | Successful GET, PUT, POST operations |
| **201** | Created | Successful resource creation |
| **204** | No Content | Successful DELETE or HEAD operations |

### 4xx Client Error Codes

| Code | Meaning | Common Causes |
|------|---------|---------------|
| **400** | Bad Request | Invalid request parameters, malformed JSON |
| **401** | Unauthorized | Missing or invalid session token |
| **403** | Forbidden | Valid token but insufficient permissions |
| **404** | Not Found | Resource not found or user has no access |
| **409** | Conflict | Resource already exists, constraint violation |
| **422** | Unprocessable Entity | Valid format but invalid data |
| **429** | Too Many Requests | Rate limiting triggered |

### 5xx Server Error Codes

| Code | Meaning | Common Causes |
|------|---------|---------------|
| **500** | Internal Server Error | Unexpected server error |
| **502** | Bad Gateway | Upstream service error |
| **503** | Service Unavailable | System maintenance or overload |
| **504** | Gateway Timeout | Request timeout |

---

## 🔍 Authentication Errors

### 401 Unauthorized

**Cause:** Missing or invalid session token

```json
{
  "success": false,
  "detail": "Authentication required",
  "error_code": "AUTH_REQUIRED",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Include `Authorization: Bearer YOUR_TOKEN` header
- Verify token is not expired
- Check token format is correct

---

### 401 Invalid Token

**Cause:** Session token is malformed or expired

```json
{
  "success": false,
  "detail": "Invalid or expired session token",
  "error_code": "INVALID_TOKEN",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Login again to get new token
- Check system clock synchronization
- Verify token hasn't been manually modified

---

### 403 Insufficient Permissions

**Cause:** Valid token but user lacks required permissions

```json
{
  "success": false,
  "detail": "Insufficient permissions for this operation",
  "error_code": "INSUFFICIENT_PERMISSIONS",
  "required_permission": "admin",
  "user_permissions": ["read", "write"],
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Contact admin to grant required permissions
- Check if user is in correct group
- Verify project access through user groups

---

## 👥 Group-Related Errors

### Group Not Found

```json
{
  "success": false,
  "detail": "User group not found",
  "error_code": "GROUP_NOT_FOUND",
  "group_identifier": "group_hash_123",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Verify group hash/name is correct
- Check if group was deleted
- Ensure proper permissions to access group

---

### User Not In Group

```json
{
  "success": false,
  "detail": "User is not a member of required group",
  "error_code": "USER_NOT_IN_GROUP",
  "required_groups": ["administrators"],
  "user_groups": ["users"],
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Admin adds user to required group
- Use different user with correct group membership
- Verify group-based project access

---

### Group Access Denied

```json
{
  "success": false,
  "detail": "User group does not have access to this project",
  "error_code": "GROUP_ACCESS_DENIED",
  "project_hash": "proj_123",
  "user_groups": ["guests"],
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Admin grants group access to project
- User joins group with project access
- Check project group permissions

---

## 📁 Project-Related Errors

### Project Not Found

```json
{
  "success": false,
  "detail": "Project not found or access denied",
  "error_code": "PROJECT_NOT_FOUND",
  "project_hash": "proj_123",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Verify project hash is correct
- Check if user's group has project access
- Confirm project exists and is active

---

### Project Access Denied

```json
{
  "success": false,
  "detail": "No access to project through user groups",
  "error_code": "PROJECT_ACCESS_DENIED",
  "project_hash": "proj_123",
  "accessible_projects": ["proj_456", "proj_789"],
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Admin grants user group access to project
- Switch to accessible project
- Join group with required project access

---

## 🔄 Validation Errors

### Invalid Request Data

```json
{
  "success": false,
  "detail": "Validation failed",
  "error_code": "VALIDATION_ERROR",
  "validation_errors": [
    {
      "field": "username",
      "message": "Username must be at least 3 characters"
    },
    {
      "field": "email",
      "message": "Invalid email format"
    }
  ],
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Fix validation errors listed in response
- Check API documentation for field requirements
- Ensure all required fields are provided

---

### Duplicate Resource

```json
{
  "success": false,
  "detail": "Resource already exists",
  "error_code": "DUPLICATE_RESOURCE",
  "resource_type": "user_group",
  "conflicting_field": "group_name",
  "conflicting_value": "developers",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Use different name/identifier
- Update existing resource instead
- Check if resource was already created

---

## 🗄️ Database & System Errors

### Database Connection Error

```json
{
  "success": false,
  "detail": "Database connection failed",
  "error_code": "DATABASE_ERROR",
  "retry_after": 5,
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Retry request after suggested delay
- Check system health endpoint
- Contact system administrator

---

### Redis Connection Error

```json
{
  "success": false,
  "detail": "Session store unavailable",
  "error_code": "REDIS_ERROR",
  "impact": "Session operations may be slow",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Request may still succeed but slower
- Check system health
- Try again in a few moments

---

## 🚫 Rate Limiting

### Rate Limit Exceeded

```json
{
  "success": false,
  "detail": "Rate limit exceeded",
  "error_code": "RATE_LIMIT_EXCEEDED",
  "limit": 100,
  "window": "1 hour",
  "retry_after": 3600,
  "timestamp": "2024-01-01T12:00:00Z"
}
```

**Solutions:**
- Wait for retry_after seconds
- Reduce request frequency
- Contact admin for rate limit increase

---

## 🔧 Troubleshooting Guide

### Error Response Analysis

```python
def analyze_error_response(response):
    """Analyze API error response and provide guidance"""
    if response.status_code == 401:
        if "INVALID_TOKEN" in response.json().get("error_code", ""):
            return "Token expired or invalid - please login again"
        else:
            return "Authentication required - please provide session token"
    
    elif response.status_code == 403:
        error_data = response.json()
        required = error_data.get("required_permission")
        user_perms = error_data.get("user_permissions", [])
        return f"Need '{required}' permission, you have: {user_perms}"
    
    elif response.status_code == 404:
        return "Resource not found or no access - check permissions"
    
    elif response.status_code >= 500:
        return "Server error - check system health or retry later"
    
    return f"Error {response.status_code}: {response.json().get('detail')}"
```

### Common Error Patterns

```javascript
class APIErrorHandler {
    static handle(error, response) {
        const errorData = response?.data || {};
        
        switch (response?.status) {
            case 401:
                if (errorData.error_code === 'INVALID_TOKEN') {
                    // Clear stored token and redirect to login
                    localStorage.removeItem('session_token');
                    window.location.href = '/login';
                } else {
                    console.error('Authentication required');
                }
                break;
                
            case 403:
                const required = errorData.required_permission;
                const userPerms = errorData.user_permissions || [];
                console.error(`Missing permission: ${required}, have: ${userPerms.join(', ')}`);
                break;
                
            case 404:
                if (errorData.error_code === 'PROJECT_NOT_FOUND') {
                    console.error('Project not accessible or does not exist');
                } else {
                    console.error('Resource not found');
                }
                break;
                
            case 409:
                console.error(`Conflict: ${errorData.detail}`);
                break;
                
            default:
                console.error(`API Error: ${errorData.detail || 'Unknown error'}`);
        }
        
        return errorData;
    }
}
```

---

## 📊 Error Monitoring & Logging

### Error Tracking

```python
import logging
from datetime import datetime

def log_api_error(response, endpoint, user_id=None):
    """Log API errors for monitoring"""
    error_data = response.json() if response.content else {}
    
    log_entry = {
        'timestamp': datetime.utcnow().isoformat(),
        'status_code': response.status_code,
        'endpoint': endpoint,
        'error_code': error_data.get('error_code'),
        'error_detail': error_data.get('detail'),
        'user_id': user_id,
        'request_id': error_data.get('request_id')
    }
    
    if response.status_code >= 500:
        logging.error(f"Server error: {log_entry}")
    elif response.status_code >= 400:
        logging.warning(f"Client error: {log_entry}")
    
    return log_entry
```

### Error Metrics

```javascript
class ErrorMetrics {
    constructor() {
        this.errorCounts = new Map();
        this.errorsByEndpoint = new Map();
    }
    
    recordError(error, endpoint) {
        // Count by error code
        const errorCode = error.error_code || 'UNKNOWN';
        this.errorCounts.set(errorCode, (this.errorCounts.get(errorCode) || 0) + 1);
        
        // Count by endpoint
        if (!this.errorsByEndpoint.has(endpoint)) {
            this.errorsByEndpoint.set(endpoint, new Map());
        }
        const endpointErrors = this.errorsByEndpoint.get(endpoint);
        endpointErrors.set(errorCode, (endpointErrors.get(errorCode) || 0) + 1);
    }
    
    getTopErrors(limit = 10) {
        return Array.from(this.errorCounts.entries())
            .sort((a, b) => b[1] - a[1])
            .slice(0, limit);
    }
    
    getEndpointErrors(endpoint) {
        return this.errorsByEndpoint.get(endpoint) || new Map();
    }
}
```

---

## 🧪 Error Response Testing

### Test Error Scenarios

```bash
#!/bin/bash

# Test authentication errors
echo "Testing authentication errors..."

echo "1. No token:"
curl -X GET "http://localhost:8000/users/profile"

echo -e "\n2. Invalid token:"
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer invalid_token"

echo -e "\n3. Expired token:"
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer expired_token_here"

# Test permission errors
echo -e "\n\nTesting permission errors..."
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer USER_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"group_name": "test", "description": "test"}'

# Test validation errors
echo -e "\n\nTesting validation errors..."
curl -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=ab&email=invalid&password=weak"
```

### Error Response Validation

```python
def test_error_response_format(response):
    """Validate error response follows standard format"""
    assert response.status_code >= 400
    
    data = response.json()
    
    # Check required fields
    assert 'success' in data
    assert data['success'] is False
    assert 'detail' in data
    assert 'timestamp' in data
    
    # Check optional fields
    if 'error_code' in data:
        assert isinstance(data['error_code'], str)
        assert data['error_code'].isupper()
    
    if 'validation_errors' in data:
        assert isinstance(data['validation_errors'], list)
        for error in data['validation_errors']:
            assert 'field' in error
            assert 'message' in error
    
    print("✅ Error response format is valid")
```

---

## 🎯 Best Practices

### Error Handling in Client Code

1. **Always check status codes** before processing response
2. **Handle authentication errors** by redirecting to login
3. **Show user-friendly messages** instead of raw error details
4. **Implement retry logic** for 5xx errors with exponential backoff
5. **Log errors** for debugging and monitoring

### Error Response Design

1. **Consistent format** across all endpoints
2. **Meaningful error codes** for programmatic handling
3. **Helpful error messages** for developers
4. **Security considerations** - don't expose sensitive information
5. **Include context** like required permissions or valid values

### Group-Specific Error Handling

1. **Check group membership** before attempting restricted operations
2. **Handle project access** gracefully with alternative suggestions
3. **Provide clear guidance** on how to gain required access
4. **Cache group information** to reduce repeated permission errors

---

**This completes the API documentation. For implementation guides and system architecture, see the other documentation sections.** 