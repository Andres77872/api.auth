# System API

System monitoring, health checks, and information endpoints for the **3-Tier User Type Multi-Project Authentication** system.

## 🔍 Overview

System endpoints provide health monitoring, system information, and status checks. Most endpoints are public, but some require authentication.

---

## 📊 System Information

### GET `/system/info`

Get comprehensive system information and statistics.

**Authentication:** None required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/system/info"
```

**Response (200):**
```json
{
  "success": true,
  "system": {
    "name": "Group-Based Multi-Project Authentication API",
    "version": "1.0.0",
    "architecture": "hierarchical-group-based",
    "status": "operational"
  },
  "statistics": {
    "total_users": 150,
    "total_projects": 25,
    "total_user_groups": 10,
    "total_project_groups": 5,
    "authentication_type": "group-based-jwt"
  },
  "features": [
    "hierarchical-group-access-control",
    "global-user-groups",
    "project-permission-groups",
    "multi-project-support",
    "session-management-with-group-context",
    "comprehensive-audit-trail",
    "restful-admin-api"
  ]
}
```

---

## 🏥 Health Monitoring

### GET `/system/health`

Comprehensive system health check including all components.

**Authentication:** None required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/system/health"
```

**Response (200):**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00Z",
  "components": {
    "database": {
      "status": "healthy",
      "message": "Database accessible"
    },
    "redis": {
      "status": "healthy",
      "message": "Redis accessible"
    },
    "group_system": {
      "status": "healthy",
      "message": "Group system operational: 10 user groups, 5 project groups"
    }
  }
}
```

**Response (503) - Unhealthy:**
```json
{
  "status": "unhealthy",
  "timestamp": "2024-01-01T12:00:00Z",
  "components": {
    "database": {
      "status": "unhealthy",
      "message": "Database error: Connection timeout"
    },
    "redis": {
      "status": "healthy",
      "message": "Redis accessible"
    },
    "group_system": {
        "status": "healthy",
        "message": "Group system operational: 10 user groups, 5 project groups"
    }
  }
}
```

---

### GET `/system/ping`

Simple health check endpoint for load balancers and monitoring.

**Authentication:** None required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/system/ping"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Group-based authentication API is running",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

---

## 🧪 Testing System Endpoints

### Basic Health Check Test

```bash
#!/bin/bash

echo "1. Testing basic ping..."
curl -X GET "http://localhost:8000/system/ping"

echo -e "\n\n2. Testing system info..."
curl -X GET "http://localhost:8000/system/info"

echo -e "\n\n3. Testing health check..."
curl -X GET "http://localhost:8000/system/health"

echo -e "\n\n4. Testing cache stats (requires auth)..."
curl -X GET "http://localhost:8000/system/cache/stats" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

### Comprehensive System Test

```bash
#!/bin/bash

# Get session token
SESSION_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=PROJECT_HASH" | \
  jq -r '.session_token')

# Test public endpoints
PUBLIC_ENDPOINTS=(
    "system/ping"
    "system/info" 
    "system/health"
)

# Test authenticated endpoints
AUTH_ENDPOINTS=(
    "system/cache/stats"
)

echo "Testing public endpoints..."
for endpoint in "${PUBLIC_ENDPOINTS[@]}"; do
    echo "Testing $endpoint..."
    response=$(curl -s -w "\n%{http_code}" "http://localhost:8000/$endpoint")
    status_code=$(echo "$response" | tail -n 1)
    
    if [ "$status_code" -eq 200 ]; then
        echo "✅ $endpoint - OK"
    else
        echo "❌ $endpoint - Failed ($status_code)"
    fi
    echo "---"
done

echo -e "\nTesting authenticated endpoints..."
for endpoint in "${AUTH_ENDPOINTS[@]}"; do
    echo "Testing $endpoint..."
    response=$(curl -s -w "\n%{http_code}" "http://localhost:8000/$endpoint" \
        -H "Authorization: Bearer $SESSION_TOKEN")
    status_code=$(echo "$response" | tail -n 1)
    
    if [ "$status_code" -eq 200 ]; then
        echo "✅ $endpoint - OK"
    else
        echo "❌ $endpoint - Failed ($status_code)"
    fi
    echo "---"
done
```

---

## 🔧 Monitoring Best Practices

### Health Check Strategy
- **Use `/system/ping`** for load balancer health checks
- **Use `/system/health`** for comprehensive monitoring including database, Redis, and group system
- **Use `/system/cache/stats`** for cache performance monitoring
- **Monitor component health individually**

### Performance Monitoring
- **Track response times** across different endpoints
- **Monitor cache hit rates** using `/system/cache/stats`
- **Watch database and Redis connectivity** via `/system/health`
- **Clear cache selectively** when needed using invalidation endpoints

### Alerting Guidelines
- **Critical**: System completely down
- **Warning**: Individual components unhealthy
- **Info**: Performance degradation
- **Success**: System recovery

---

## 💾 Cache Management

The system includes comprehensive cache management for performance optimization with automatic invalidation.

### GET `/system/cache/stats`

Get detailed cache statistics and performance metrics.

**Authentication:** Required

**Example Request:**
```bash
curl -X GET "http://localhost:8000/system/cache/stats" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "cache_statistics": {
    "sessions": 145,
    "access_checks": 892,
    "permission_checks": 567,
    "user_types": 234,
    "rbac_checks": 123,
    "total_keys": 1961
  },
  "cache_configuration": {
    "session_ttl": "3600 seconds (1 hour)",
    "access_check_ttl": "1800 seconds (30 minutes)",
    "rbac_check_ttl": "1800 seconds (30 minutes)",
    "user_info_ttl": "3600 seconds (1 hour)"
  },
  "timestamp": "2024-01-01T12:00:00Z"
}
```

---

### POST `/system/cache/clear`

Clear the entire authentication cache.

**Authentication:** Required (admin only)

**Example Request:**
```bash
curl -X POST "http://localhost:8000/system/cache/clear" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Entire authentication cache has been cleared",
  "cleared_by": "USER_HASH...",
  "timestamp": "2024-01-01T12:00:00Z",
  "warning": "All users will need to re-authenticate or may experience slower response times"
}
```

---

### POST `/system/cache/invalidate/user/{user_hash}`

Invalidate the cache for a specific user.

**Authentication:** Required (admin only)

**Path Parameters:**
- `user_hash`: The hash of the user to invalidate from the cache.

**Example Request:**
```bash
curl -X POST "http://localhost:8000/system/cache/invalidate/user/usr-1234..." \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Cache invalidated for user: usr-1234...",
  "invalidated_by": "ADMIN_USER_HASH...",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

---

### POST `/system/cache/invalidate/project/{project_id}`

Invalidate the cache for a specific project.

**Authentication:** Required (admin only)

**Path Parameters:**
- `project_id`: The ID of the project to invalidate from the cache.

**Example Request:**
```bash
curl -X POST "http://localhost:8000/system/cache/invalidate/project/5" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "message": "Cache invalidated for project: 5",
  "invalidated_by": "ADMIN_USER_HASH...",
  "timestamp": "2024-01-01T12:00:00Z"
}
```

---

## 🧪 Testing Cache Operations

### Cache Management Test

```bash
#!/bin/bash

# Get admin token
ADMIN_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=PROJECT_HASH" | \
  jq -r '.session_token')

echo "1. Getting cache statistics..."
curl -X GET "http://localhost:8000/system/cache/stats" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n2. Testing user-specific cache invalidation..."
USER_HASH="usr-example-hash-12345"
curl -X POST "http://localhost:8000/system/cache/invalidate/user/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n3. Testing project-specific cache invalidation..."
PROJECT_ID="5"
curl -X POST "http://localhost:8000/system/cache/invalidate/project/$PROJECT_ID" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n4. Clearing entire cache (use with caution)..."
curl -X POST "http://localhost:8000/system/cache/clear" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n5. Checking cache stats after operations..."
curl -X GET "http://localhost:8000/system/cache/stats" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

---

**Next:** Learn about [Error Handling](errors-and-responses.md) for comprehensive error reference. 