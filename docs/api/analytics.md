# Analytics API

Complete analytics and reporting documentation for monitoring system usage, user activity, project metrics, and performance insights.

## 🔐 Authentication Required

All analytics endpoints require admin authentication:

```
Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN
```

---

## 📊 Dashboard Analytics

### GET `/analytics/dashboard/stats`

Get comprehensive analytics dashboard statistics with key metrics.

**Authentication:** Required (admin permission)

**Query Parameters:**
- `period_days` (optional, default: 30, max: 365): Analysis period in days

**Example Request:**
```bash
curl -X GET "http://localhost:8000/analytics/dashboard/stats?period_days=30" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Success Response (200):**
```json
{
  "success": true,
  "analytics": {
    "period": {
      "days": 30,
      "start_date": "2023-12-16T10:30:00Z",
      "end_date": "2024-01-15T10:30:00Z"
    },
    "user_metrics": {
      "total_users": 150,
      "new_users": 12,
      "growth_rate": 8.7,
      "user_types": {
        "root": 2,
        "admin": 8,
        "consumer": 140
      }
    },
    "project_metrics": {
      "total_projects": 25,
      "new_projects": 3,
      "growth_rate": 13.6
    },
    "activity_metrics": {
      "total_activities": 1524,
      "activities_per_day": 50.8,
      "activity_breakdown": {
        "user_login": 523,
        "user_logout": 498,
        "user_created": 12,
        "project_created": 3
      }
    },
    "session_metrics": {
      "active_sessions": 42,
      "session_stats": {
        "total_logins": 523,
        "unique_users": 128,
        "avg_session_duration_minutes": 45.2
      }
    },
    "login_metrics": {
      "total_logins": 523,
      "unique_users": 128,
      "avg_logins_per_user": 4.1
    }
  },
  "summary": {
    "total_entities": 175,
    "activity_score": 85,
    "growth_trend": "moderate_growth",
    "health_status": "healthy"
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

## 👥 User Analytics

### GET `/analytics/users`

Get detailed user analytics with growth trends and activity patterns.

**Authentication:** Required (admin permission)

**Query Parameters:**
- `period_days` (optional, default: 30, max: 365): Analysis period
- `user_type` (optional): Filter by user type (`root`, `admin`, `consumer`)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/analytics/users?period_days=30&user_type=consumer" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Success Response (200):**
```json
{
  "period": {
    "days": 30,
    "start_date": "2023-12-16T10:30:00Z",
    "end_date": "2024-01-15T10:30:00Z"
  },
  "user_totals": {
    "total_users": 140,
    "new_users_period": 12,
    "daily_avg_registrations": 0.4
  },
  "user_type_breakdown": {
    "consumer": 140
  },
  "activity_patterns": {
    "login_statistics": {
      "total_logins": 523,
      "unique_users": 128,
      "avg_logins_per_user": 4.1
    },
    "avg_logins_per_day": 17.43
  },
  "trends": {
    "registration_trend": "stable",
    "activity_trend": "active"
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

## 📁 Project Analytics

### GET `/analytics/projects`

Get detailed project analytics including usage and member activity.

**Authentication:** Required (admin permission)

**Query Parameters:**
- `period_days` (optional, default: 30, max: 365): Analysis period

**Example Request:**
```bash
curl -X GET "http://localhost:8000/analytics/projects?period_days=30" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Success Response (200):**
```json
{
  "period": {
    "days": 30,
    "start_date": "2023-12-16T10:30:00Z",
    "end_date": "2024-01-15T10:30:00Z"
  },
  "project_totals": {
    "total_projects": 25,
    "new_projects_period": 3,
    "daily_avg_creation": 0.1
  },
  "activity_metrics": {
    "total_project_activities": 1524,
    "avg_activities_per_project": 60.96,
    "activities_per_day": 50.8
  },
  "trends": {
    "creation_trend": "stable",
    "activity_trend": "high"
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

## 🎯 Activity Analytics

### GET `/analytics/activity`

Get detailed activity analytics with action breakdowns.

**Authentication:** Required (admin permission)

**Query Parameters:**
- `period_days` (optional, default: 30, max: 365): Analysis period
- `activity_type` (optional): Filter by activity type

**Example Request:**
```bash
curl -X GET "http://localhost:8000/analytics/activity?period_days=7&activity_type=user_login" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Success Response (200):**
```json
{
  "period": {
    "days": 7,
    "start_date": "2024-01-08T10:30:00Z",
    "end_date": "2024-01-15T10:30:00Z"
  },
  "activity_totals": {
    "total_activities": 365,
    "daily_avg_activities": 52.14,
    "filtered_by_type": "user_login"
  },
  "activity_breakdown": {
    "user_login": 125,
    "user_logout": 118,
    "user_created": 3,
    "project_created": 1
  },
  "engagement_metrics": {
    "unique_active_users": 45,
    "unique_active_projects": 8,
    "activities_per_user": 8.11
  },
  "trends": {
    "volume_trend": "high",
    "engagement_trend": "active"
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

## 📈 Analytics Summary

### GET `/analytics/summary`

Get a comprehensive analytics summary with all key metrics.

**Authentication:** Required (admin permission)

**Example Request:**
```bash
curl -X GET "http://localhost:8000/analytics/summary" \
  -H "Authorization: Bearer YOUR_ADMIN_SESSION_TOKEN"
```

**Success Response (200):**
```json
{
  "current_totals": {
    "users": 150,
    "projects": 25,
    "active_sessions": 42
  },
  "recent_activity": {
    "last_7_days": {
      "users": 5,
      "projects": 1,
      "activities": 365
    },
    "last_30_days": {
      "users": 12,
      "projects": 3,
      "activities": 1524
    }
  },
  "login_metrics": {
    "total_logins": 125,
    "unique_users": 45,
    "avg_logins_per_user": 2.78
  },
  "growth_indicators": {
    "weekly_user_growth": 5,
    "weekly_project_growth": 1,
    "weekly_activity_volume": 365
  },
  "generated_at": "2024-01-15T10:30:00Z"
}
```

---

## 🧪 Testing Analytics

### Analytics Test Script

```bash
#!/bin/bash

# Get admin token
ADMIN_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=PROJECT_HASH" | \
  jq -r '.session_token')

echo "1. Getting dashboard analytics..."
curl -X GET "http://localhost:8000/analytics/dashboard/stats?period_days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n2. Getting user analytics..."
curl -X GET "http://localhost:8000/analytics/users?period_days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n3. Getting project analytics..."
curl -X GET "http://localhost:8000/analytics/projects?period_days=30" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n4. Getting activity analytics..."
curl -X GET "http://localhost:8000/analytics/activity?period_days=7" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

echo -e "\n5. Getting analytics summary..."
curl -X GET "http://localhost:8000/analytics/summary" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

## 🛡️ Best Practices

### Data Collection
- **Regular Monitoring**: Check analytics daily for anomalies
- **Trend Analysis**: Review weekly and monthly trends
- **Alert Configuration**: Set up alerts for critical metrics

### Performance
- **Cache Results**: Cache analytics responses for faster dashboards
- **Limit Period**: Use shorter periods for real-time monitoring
- **Batch Requests**: Use summary endpoint for overview data

### Privacy & Security
- **Access Control**: Restrict analytics to admin users only
- **Data Anonymization**: Consider anonymizing sensitive data
- **Audit Trail**: Log all analytics access

---

**Next:** Explore [Bulk Operations](bulk-operations.md) for batch management or [Admin API](admin.md) for system administration.
