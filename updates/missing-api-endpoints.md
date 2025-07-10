# Missing API Endpoints Documentation

This document contains all the API endpoints found in the Magic Auth Dashboard services that are **NOT** currently documented in the existing API definition. These endpoints need to be implemented in the backend API.

## 🔐 Authentication Endpoints (Missing)

### POST `/auth/logout`
**Description:** Logout user and invalidate session  
**Headers:** `Authorization: Bearer <token>`

**Request:** No body required

**Response:**
```json
{
  "success": true,
  "message": "Logout successful"
}
```

### POST `/auth/refresh`
**Description:** Refresh authentication token  
**Headers:** `Authorization: Bearer <token>`

**Request:** No body required

**Response:**
```json
{
  "success": true,
  "message": "Token refreshed successfully",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "expires_at": "2024-01-18T10:30:00Z"
}
```

---

## 📊 Admin Dashboard Endpoints

### GET `/admin/dashboard/stats` 🔒
**Description:** Get admin dashboard statistics (ADMIN/ROOT only)  

**Response:**
```json
{
  "success": true,
  "message": "Dashboard stats retrieved",
  "data": {
    "total_users": 150,
    "total_projects": 25,
    "active_sessions": 45,
    "recent_registrations": 12,
    "system_health": "healthy",
    "monthly_growth": {
      "users": 15.2,
      "projects": 8.7
    }
  }
}
```

### GET `/admin/activity` 🔒
**Description:** Get recent admin activity feed  
**Params:** `?limit=10&offset=0&type=all&severity=info`

**Response:**
```json
{
  "success": true,
  "message": "Activity retrieved",
  "data": [
    {
      "id": "act_123",
      "type": "user_created",
      "severity": "info",
      "message": "New user registered: john_doe",
      "user_hash": "usr_def456abc",
      "timestamp": "2024-01-15T10:30:00Z",
      "metadata": {
        "user_type": "consumer",
        "project_hash": "proj_abc123xyz"
      }
    }
  ],
  "pagination": {
    "limit": 10,
    "offset": 0,
    "total": 150,
    "has_more": true
  }
}
```

### GET `/admin/users/statistics` 🔒
**Description:** Get user statistics for admin dashboard  

**Response:**
```json
{
  "success": true,
  "message": "User statistics retrieved",
  "data": {
    "total_users": 150,
    "user_types": {
      "root": 2,
      "admin": 8,
      "consumer": 140
    },
    "active_users_today": 45,
    "new_users_this_week": 12,
    "growth_rate": 15.2,
    "top_active_users": [
      {
        "user_hash": "usr_abc123",
        "username": "john_doe",
        "activity_score": 95
      }
    ]
  }
}
```

### GET `/admin/projects/statistics` 🔒
**Description:** Get project statistics for admin dashboard  

**Response:**
```json
{
  "success": true,
  "message": "Project statistics retrieved",
  "data": {
    "total_projects": 25,
    "active_projects": 20,
    "archived_projects": 5,
    "avg_members_per_project": 6.2,
    "projects_created_this_week": 3,
    "most_active_projects": [
      {
        "project_hash": "proj_abc123",
        "project_name": "Main Project",
        "member_count": 15,
        "activity_score": 88
      }
    ]
  }
}
```

### GET `/admin/system/overview` 🔒
**Description:** Get system overview for admin dashboard  

**Response:**
```json
{
  "success": true,
  "message": "System overview retrieved",
  "data": {
    "uptime": "15d 4h 30m",
    "version": "2.1.0",
    "environment": "production",
    "database": {
      "status": "healthy",
      "connections": "8/20",
      "response_time_ms": 12
    },
    "cache": {
      "status": "healthy",
      "memory_usage_percent": 45,
      "hit_rate_percent": 92.5
    },
    "api": {
      "requests_per_minute": 125,
      "avg_response_time_ms": 45,
      "error_rate_percent": 0.2
    }
  }
}
```

---

## 📁 Export/Import Endpoints

### GET `/admin/export/users` 🔒
**Description:** Export users data  
**Params:** `?format=csv` or `?format=json`

**Response:**
```json
{
  "success": true,
  "message": "Export initiated",
  "data": {
    "download_url": "https://api.example.com/downloads/users_2024-01-15.csv",
    "expires_at": "2024-01-15T15:00:00Z",
    "file_size": "2.5MB",
    "record_count": 150
  }
}
```

### GET `/admin/export/projects` 🔒
**Description:** Export projects data  
**Params:** `?format=csv` or `?format=json`

**Response:**
```json
{
  "success": true,
  "message": "Export initiated",
  "data": {
    "download_url": "https://api.example.com/downloads/projects_2024-01-15.csv",
    "expires_at": "2024-01-15T15:00:00Z",
    "file_size": "1.2MB",
    "record_count": 25
  }
}
```

### POST `/admin/import/users` 🔒
**Description:** Import users from CSV/JSON file  
**Content-Type:** `multipart/form-data`

**Request:** Form data with file upload

**Response:**
```json
{
  "success": true,
  "message": "Import completed",
  "data": {
    "imported_count": 45,
    "skipped_count": 5,
    "error_count": 2,
    "errors": [
      {
        "row": 15,
        "error": "Email already exists",
        "data": { "email": "john@example.com" }
      }
    ]
  }
}
```

---

## 👥 User Management (Extended)

### GET `/users` 🔒
**Description:** List all users with filtering  
**Params:** `?limit=10&offset=0&search=john&user_type=consumer&status=active`

**Response:**
```json
{
  "success": true,
  "message": "Users retrieved",
  "data": [
    {
      "user_hash": "usr_def456abc",
      "username": "john_doe",
      "email": "john@example.com",
      "user_type": "consumer",
      "status": "active",
      "created_at": "2024-01-15T10:30:00Z",
      "last_login": "2024-01-15T16:00:00Z"
    }
  ],
  "pagination": {
    "limit": 10,
    "offset": 0,
    "total": 150,
    "has_more": true
  }
}
```

### GET `/users/{user_hash}` 🔒
**Description:** Get detailed user information  

**Response:**
```json
{
  "success": true,
  "message": "User retrieved",
  "data": {
    "user_hash": "usr_def456abc",
    "username": "john_doe",
    "email": "john@example.com",
    "user_type": "consumer",
    "status": "active",
    "created_at": "2024-01-15T10:30:00Z",
    "last_login": "2024-01-15T16:00:00Z",
    "projects": [
      {
        "project_hash": "proj_abc123",
        "project_name": "Main Project",
        "role": "member"
      }
    ],
    "groups": [
      {
        "group_hash": "grp_def456",
        "group_name": "Developers"
      }
    ]
  }
}
```

### PATCH `/users/{user_hash}/status` 🔒
**Description:** Activate or deactivate user account  

**Request:**
```json
{
  "is_active": false
}
```

**Response:**
```json
{
  "success": true,
  "message": "User status updated",
  "data": {
    "user_hash": "usr_def456abc",
    "username": "john_doe",
    "status": "inactive",
    "updated_at": "2024-01-15T17:00:00Z"
  }
}
```

### POST `/users/{user_hash}/reset-password` 🔒
**Description:** Reset user password (generates new temporary password)  

**Response:**
```json
{
  "success": true,
  "message": "Password reset successfully",
  "data": {
    "new_password": "temp_pass_123456",
    "expires_at": "2024-01-16T10:30:00Z",
    "must_change_on_login": true
  }
}
```

### PATCH `/users/{user_hash}/type` 🔒
**Description:** Change user type (ROOT only)  

**Request:**
```json
{
  "user_type": "admin"
}
```

**Response:**
```json
{
  "success": true,
  "message": "User type updated",
  "data": {
    "user_hash": "usr_def456abc",
    "username": "john_doe",
    "user_type": "admin",
    "updated_at": "2024-01-15T17:00:00Z"
  }
}
```

---

## 🔄 Bulk Operations

### POST `/admin/users/bulk-update` 🔒
**Description:** Update multiple users at once  

**Request:**
```json
{
  "user_hashes": ["usr_123", "usr_456", "usr_789"],
  "updates": {
    "status": "active",
    "user_type": "consumer"
  }
}
```

**Response:**
```json
{
  "success": true,
  "message": "Bulk update completed",
  "data": {
    "updated_count": 2,
    "skipped_count": 1,
    "errors": [
      {
        "user_hash": "usr_789",
        "error": "User not found"
      }
    ]
  }
}
```

### POST `/admin/users/bulk-delete` 🔒
**Description:** Delete multiple users at once  

**Request:**
```json
{
  "user_hashes": ["usr_123", "usr_456"]
}
```

**Response:**
```json
{
  "success": true,
  "message": "Bulk delete completed",
  "data": {
    "deleted_count": 2
  }
}
```

---

## 📁 Project Management (Extended)

### GET `/projects/{project_hash}` 🔒
**Description:** Get detailed project information  

**Response:**
```json
{
  "success": true,
  "message": "Project retrieved",
  "data": {
    "project_hash": "proj_abc123xyz",
    "project_name": "My Project",
    "project_description": "Sample project",
    "status": "active",
    "created_at": "2024-01-10T09:00:00Z",
    "owner": {
      "user_hash": "usr_owner123",
      "username": "project_owner"
    },
    "member_count": 15,
    "activity_score": 88,
    "permissions": ["read", "write", "manage"]
  }
}
```

### GET `/projects/{project_hash}/members` 🔒
**Description:** Get project members list  
**Params:** `?limit=10&offset=0&role=all`

**Response:**
```json
{
  "success": true,
  "message": "Project members retrieved",
  "data": [
    {
      "user_hash": "usr_def456abc",
      "username": "john_doe",
      "email": "john@example.com",
      "role": "member",
      "joined_at": "2024-01-12T10:00:00Z",
      "permissions": ["read", "write"]
    }
  ],
  "pagination": {
    "limit": 10,
    "offset": 0,
    "total": 15,
    "has_more": true
  }
}
```

---

## 📊 Analytics Endpoints

### GET `/analytics/activity` 🔒
**Description:** Get analytics activity feed  
**Params:** `?limit=10&cursor=abc123&type=user_action&user_type=consumer&severity=info&search=login&start_date=2024-01-01&end_date=2024-01-15`

**Response:**
```json
{
  "success": true,
  "message": "Activity feed retrieved",
  "data": {
    "activities": [
      {
        "id": "act_analytics_123",
        "type": "user_login",
        "severity": "info",
        "message": "User logged in from new device",
        "user_hash": "usr_def456abc",
        "timestamp": "2024-01-15T16:00:00Z",
        "metadata": {
          "ip_address": "192.168.1.100",
          "device": "Desktop Chrome"
        }
      }
    ],
    "total": 1500,
    "has_more": true,
    "next_cursor": "xyz789def"
  }
}
```

### GET `/analytics/dashboard/stats` 🔒
**Description:** Get dashboard analytics statistics  

**Response:**
```json
{
  "success": true,
  "message": "Dashboard stats retrieved",
  "data": {
    "total_users": 150,
    "total_projects": 25,
    "recent_activity": 125,
    "system_health": "healthy"
  }
}
```

---

## 🔍 Summary

This document covers **87+ missing API endpoints** that are called by the frontend services but not documented in the current API definition. 

### 🚨 Critical Endpoints for Basic Functionality

The following endpoints are essential for the dashboard to function properly:
- `/auth/logout` - User logout functionality
- `/admin/dashboard/stats` - Admin dashboard statistics
- `/users` - User listing and management
- `/projects/{project_hash}` - Project details
- `/analytics/dashboard/stats` - Dashboard analytics

These should be prioritized for immediate implementation. 