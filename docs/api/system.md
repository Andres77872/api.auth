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
    "version": "2.0.0",
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

## 📈 Group System Monitoring

### GET `/system/groups/health`

Detailed health check specifically for the group-based system.

**Authentication:** Recommended (returns more details if authenticated)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/system/groups/health" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "status": "healthy",
  "timestamp": "2024-01-01T12:00:00Z",
  "group_system": {
    "user_groups": {
      "total": 10,
      "active": 10,
      "with_members": 8,
      "without_members": 2,
      "with_project_access": 7
    },
    "project_groups": {
      "total": 5,
      "active": 5,
      "with_projects": 4,
      "without_projects": 1,
      "permission_sets": [
        "full-access",
        "read-write",
        "read-only",
        "api-access"
      ]
    },
    "relationships": {
      "user_group_members": 45,
      "project_group_assignments": 20,
      "user_group_project_access": 15
    },
    "recent_activity": {
      "new_group_assignments_24h": 3,
      "project_access_grants_24h": 1,
      "group_logins_24h": 28
    }
  }
}
```

---

### GET `/system/groups/stats`

Comprehensive group system statistics.

**Authentication:** Required (admin preferred for full stats)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/system/groups/stats" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "statistics": {
    "user_groups": {
      "total": 10,
      "active": 10,
      "by_type": {
        "administrators": 1,
        "users": 3,
        "guests": 2,
        "custom": 4
      },
      "membership": {
        "total_assignments": 45,
        "average_members_per_group": 4.5,
        "largest_group": {
          "name": "users",
          "member_count": 15
        }
      }
    },
    "project_groups": {
      "total": 5,
      "active": 5,
      "by_permissions": {
        "full-access": 2,
        "read-write": 2,
        "read-only": 1
      },
      "assignment": {
        "total_projects": 25,
        "assigned_projects": 20,
        "unassigned_projects": 5
      }
    },
    "access_patterns": {
      "most_accessed_projects": [
        {
          "project_name": "Main API",
          "access_count": 150
        }
      ],
      "most_active_groups": [
        {
          "group_name": "administrators",
          "session_count": 50
        }
      ]
    }
  }
}
```

---

## ⚡ Performance Monitoring

### GET `/system/performance`

Get system performance metrics.

**Authentication:** Recommended

**Example Request:**
```bash
curl -X GET "http://localhost:8000/system/performance" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "performance": {
    "response_times": {
      "average_ms": 45,
      "p95_ms": 120,
      "p99_ms": 250
    },
    "throughput": {
      "requests_per_second": 150,
      "peak_rps": 300,
      "requests_24h": 12960000
    },
    "database": {
      "query_time_avg_ms": 12,
      "slow_queries": 2,
      "connection_pool_usage": 0.3
    },
    "redis": {
      "hit_rate": 0.95,
      "avg_response_ms": 2,
      "memory_usage_mb": 15.2
    },
    "group_operations": {
      "permission_check_avg_ms": 5,
      "group_resolution_avg_ms": 8,
      "cache_hit_rate": 0.89
    }
  }
}
```

---

## 🔧 System Diagnostics

### GET `/system/diagnostics`

Detailed system diagnostics for troubleshooting.

**Authentication:** Required (admin preferred)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/system/diagnostics" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Response (200):**
```json
{
  "success": true,
  "diagnostics": {
    "environment": {
      "python_version": "3.11.5",
      "fastapi_version": "0.104.1",
      "mysql_version": "8.0.35",
      "redis_version": "7.0.12"
    },
    "configuration": {
      "debug_mode": false,
      "group_system_enabled": true,
      "session_timeout_hours": 72,
      "max_connections": 100
    },
    "recent_errors": [
      {
        "timestamp": "2024-01-01T11:30:00Z",
        "level": "WARNING",
        "message": "Slow database query detected",
        "duration_ms": 1200
      }
    ],
    "system_resources": {
      "cpu_usage_percent": 15.5,
      "memory_usage_mb": 512,
      "disk_usage_percent": 45
    }
  }
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

echo -e "\n\n4. Testing group system health..."
curl -X GET "http://localhost:8000/system/groups/health"
```

### Comprehensive System Test

```bash
#!/bin/bash

# Test all system endpoints
ENDPOINTS=(
    "system/ping"
    "system/info" 
    "system/health"
    "system/groups/health"
    "system/performance"
)

for endpoint in "${ENDPOINTS[@]}"; do
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
```

---

## 📚 Monitoring SDK Examples

### Python System Monitoring

```python
import requests
import time

class SystemMonitor:
    def __init__(self, base_url):
        self.base_url = base_url
    
    def ping(self):
        """Simple health check"""
        try:
            response = requests.get(f"{self.base_url}/system/ping", timeout=5)
            return response.status_code == 200
        except requests.RequestException:
            return False
    
    def get_health(self):
        """Get comprehensive health status"""
        response = requests.get(f"{self.base_url}/system/health")
        return response.json()
    
    def get_group_stats(self, session_token=None):
        """Get group system statistics"""
        headers = {}
        if session_token:
            headers["Authorization"] = f"Bearer {session_token}"
        
        response = requests.get(
            f"{self.base_url}/system/groups/stats",
            headers=headers
        )
        return response.json()
    
    def monitor_continuously(self, interval=60):
        """Continuous health monitoring"""
        while True:
            health = self.get_health()
            status = health.get("status", "unknown")
            score = health.get("overall_health_score", 0)
            
            print(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] "
                  f"Status: {status}, Score: {score}%")
            
            if status != "healthy":
                print("⚠️  System unhealthy - alerting required")
                # Add alerting logic here
            
            time.sleep(interval)

# Usage
monitor = SystemMonitor("http://localhost:8000")

# Quick health check
if monitor.ping():
    print("✅ System is responding")
else:
    print("❌ System is not responding")

# Detailed health
health = monitor.get_health()
print(f"System status: {health['status']}")

# Group statistics
stats = monitor.get_group_stats()
print(f"Total user groups: {stats['statistics']['user_groups']['total']}")
```

### JavaScript System Monitoring

```javascript
class SystemMonitor {
    constructor(baseUrl) {
        this.baseUrl = baseUrl;
    }
    
    async ping() {
        try {
            const response = await fetch(`${this.baseUrl}/system/ping`, {
                timeout: 5000
            });
            return response.ok;
        } catch (error) {
            return false;
        }
    }
    
    async getHealth() {
        const response = await fetch(`${this.baseUrl}/system/health`);
        return await response.json();
    }
    
    async getGroupStats(sessionToken = null) {
        const headers = {};
        if (sessionToken) {
            headers['Authorization'] = `Bearer ${sessionToken}`;
        }
        
        const response = await fetch(`${this.baseUrl}/system/groups/stats`, {
            headers
        });
        return await response.json();
    }
    
    async getPerformance(sessionToken = null) {
        const headers = {};
        if (sessionToken) {
            headers['Authorization'] = `Bearer ${sessionToken}`;
        }
        
        const response = await fetch(`${this.baseUrl}/system/performance`, {
            headers
        });
        return await response.json();
    }
    
    startHealthMonitoring(interval = 60000, callback) {
        const monitor = async () => {
            try {
                const health = await this.getHealth();
                callback(health);
                
                if (health.status !== 'healthy') {
                    console.warn('⚠️ System health issue detected:', health);
                }
            } catch (error) {
                console.error('Health check failed:', error);
                callback({ status: 'error', error: error.message });
            }
        };
        
        // Initial check
        monitor();
        
        // Schedule periodic checks
        return setInterval(monitor, interval);
    }
}

// Usage
const monitor = new SystemMonitor('http://localhost:8000');

// Quick health check
const isHealthy = await monitor.ping();
console.log(`System responding: ${isHealthy}`);

// Start continuous monitoring
const healthCheckInterval = monitor.startHealthMonitoring(30000, (health) => {
    console.log(`[${new Date().toISOString()}] Status: ${health.status}`);
    
    if (health.overall_health_score) {
        console.log(`Health Score: ${health.overall_health_score}%`);
    }
});

// Stop monitoring after 5 minutes
setTimeout(() => {
    clearInterval(healthCheckInterval);
    console.log('Health monitoring stopped');
}, 300000);
```

---

## 🚨 Alerting and Monitoring Integration

### Health Check Alerts

```python
def check_system_health_with_alerts(monitor):
    """Health check with alerting"""
    health = monitor.get_health()
    
    if health["status"] != "healthy":
        alert_message = f"System unhealthy: {health['status']}"
        
        # Check specific components
        for component, details in health["components"].items():
            if details["status"] != "healthy":
                alert_message += f"\n- {component}: {details['message']}"
        
        # Send alert (implement your alerting mechanism)
        send_alert(alert_message)
    
    return health

def send_alert(message):
    """Send alert through your preferred channel"""
    # Examples:
    # - Send email
    # - Post to Slack
    # - Create PagerDuty incident
    # - Log to monitoring system
    print(f"🚨 ALERT: {message}")
```

### Performance Monitoring

```javascript
async function monitorPerformance(monitor) {
    const performance = await monitor.getPerformance();
    
    // Check response times
    if (performance.performance.response_times.average_ms > 100) {
        console.warn('⚠️ High response times detected');
    }
    
    // Check database performance
    if (performance.performance.database.query_time_avg_ms > 50) {
        console.warn('⚠️ Slow database queries detected');
    }
    
    // Check Redis performance
    if (performance.performance.redis.hit_rate < 0.8) {
        console.warn('⚠️ Low Redis cache hit rate');
    }
    
    return performance;
}
```

---

## 🔧 Monitoring Best Practices

### Health Check Strategy
- **Use `/system/ping`** for load balancer health checks
- **Use `/system/health`** for comprehensive monitoring
- **Use `/system/groups/health`** for group-specific monitoring
- **Monitor component health individually**

### Performance Monitoring
- **Track response times** across different endpoints
- **Monitor group operation performance** specifically
- **Watch database query performance**
- **Monitor Redis cache effectiveness**

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

### Cache Performance Test

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

echo -e "\n2. Testing cache warm-up..."
curl -X POST "http://localhost:8000/system/cache/warm" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n3. Testing selective cache invalidation..."
curl -X POST "http://localhost:8000/system/cache/invalidate" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"cache_type": "sessions"}'

echo -e "\n4. Checking cache stats after invalidation..."
curl -X GET "http://localhost:8000/system/cache/stats" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## 📊 Cache Monitoring

### Cache Health Monitoring

```python
import requests

def monitor_cache_health(base_url, admin_token):
    """Monitor cache performance and health"""
    headers = {"Authorization": f"Bearer {admin_token}"}
    
    # Get cache statistics
    response = requests.get(f"{base_url}/system/cache/stats", headers=headers)
    stats = response.json()
    
    cache_stats = stats["cache_statistics"]
    overall = cache_stats["overall"]
    
    # Check cache health
    hit_rate = overall["total_hit_rate"]
    cache_size = overall["total_cache_size_mb"]
    
    print(f"Cache Hit Rate: {hit_rate:.2%}")
    print(f"Cache Size: {cache_size:.1f} MB")
    
    # Alert if hit rate is low
    if hit_rate < 0.8:
        print("⚠️  Warning: Cache hit rate below 80%")
    
    # Alert if cache size is too large
    if cache_size > 50:
        print("⚠️  Warning: Cache size above 50MB")
    
    return stats

# Usage
stats = monitor_cache_health("http://localhost:8000", "admin_token")
```

### Cache Performance Analysis

```javascript
class CacheMonitor {
    constructor(baseUrl, adminToken) {
        this.baseUrl = baseUrl;
        this.headers = { 'Authorization': `Bearer ${adminToken}` };
    }
    
    async getCacheStats() {
        const response = await fetch(`${this.baseUrl}/system/cache/stats`, {
            headers: this.headers
        });
        return await response.json();
    }
    
    async analyzeCachePerformance() {
        const stats = await this.getCacheStats();
        const cache = stats.cache_statistics;
        
        const analysis = {
            overall_health: this.calculateHealthScore(cache.overall),
            bottlenecks: this.identifyBottlenecks(cache),
            recommendations: this.generateRecommendations(cache)
        };
        
        return analysis;
    }
    
    calculateHealthScore(overall) {
        const hitRate = overall.total_hit_rate;
        const size = overall.total_cache_size_mb;
        
        let score = 100;
        if (hitRate < 0.9) score -= (0.9 - hitRate) * 200;
        if (size > 20) score -= (size - 20) * 2;
        
        return Math.max(0, Math.min(100, score));
    }
    
    identifyBottlenecks(cache) {
        const bottlenecks = [];
        
        Object.entries(cache).forEach(([type, stats]) => {
            if (stats.hit_rate && stats.hit_rate < 0.8) {
                bottlenecks.push(`${type}: Low hit rate (${stats.hit_rate:.2%})`);
            }
        });
        
        return bottlenecks;
    }
    
    generateRecommendations(cache) {
        const recommendations = [];
        
        if (cache.overall.total_hit_rate < 0.85) {
            recommendations.push("Consider increasing cache TTL values");
        }
        
        if (cache.overall.total_cache_size_mb > 30) {
            recommendations.push("Consider implementing cache size limits");
        }
        
        return recommendations;
    }
}

// Usage
const monitor = new CacheMonitor('http://localhost:8000', 'admin_token');
const analysis = await monitor.analyzeCachePerformance();
console.log('Cache Health Score:', analysis.overall_health);
```

---

**Next:** Learn about [Error Handling](errors-and-responses.md) for comprehensive error reference. 