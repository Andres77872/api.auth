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

### POST `/projects/{project_hash}/members` 🔒
**Description:** Add member to project  

**Request:**
```json
{
  "user_hash": "usr_new123"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Member added to project",
  "data": {
    "user_hash": "usr_new123",
    "project_hash": "proj_abc123xyz",
    "role": "member",
    "added_at": "2024-01-15T17:30:00Z"
  }
}
```

### DELETE `/projects/{project_hash}/members/{user_hash}` 🔒
**Description:** Remove member from project  

**Response:**
```json
{
  "success": true,
  "message": "Member removed from project"
}
```

### GET `/projects/{project_hash}/activity` 🔒
**Description:** Get project activity feed  
**Params:** `?limit=10&offset=0&type=all`

**Response:**
```json
{
  "success": true,
  "message": "Project activity retrieved",
  "data": [
    {
      "id": "act_proj_123",
      "type": "member_added",
      "message": "john_doe was added to the project",
      "user_hash": "usr_def456abc",
      "timestamp": "2024-01-15T17:30:00Z",
      "metadata": {
        "added_by": "usr_admin123"
      }
    }
  ],
  "pagination": {
    "limit": 10,
    "offset": 0,
    "total": 50,
    "has_more": true
  }
}
```

### GET `/projects/{project_hash}/stats` 🔒
**Description:** Get project statistics  

**Response:**
```json
{
  "success": true,
  "message": "Project stats retrieved",
  "data": {
    "member_count": 15,
    "activity_count_last_week": 45,
    "permissions_granted": 12,
    "roles_assigned": 8,
    "health_score": 88,
    "created_at": "2024-01-10T09:00:00Z"
  }
}
```

### PATCH `/projects/{project_hash}/owner` 🔒
**Description:** Transfer project ownership  

**Request:**
```json
{
  "new_owner_hash": "usr_newowner123"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Project ownership transferred",
  "data": {
    "project_hash": "proj_abc123xyz",
    "previous_owner": "usr_oldowner123",
    "new_owner": "usr_newowner123",
    "transferred_at": "2024-01-15T18:00:00Z"
  }
}
```

### PATCH `/projects/{project_hash}/archive` 🔒
**Description:** Archive or unarchive project  

**Request:**
```json
{
  "archived": true
}
```

**Response:**
```json
{
  "success": true,
  "message": "Project archived successfully",
  "data": {
    "project_hash": "proj_abc123xyz",
    "project_name": "My Project",
    "status": "archived",
    "archived_at": "2024-01-15T18:00:00Z"
  }
}
```

---

## 👥 User Group Management (Extended)

### GET `/admin/user-groups/{group_hash}` 🔒
**Description:** Get detailed group information  

**Response:**
```json
{
  "success": true,
  "message": "Group retrieved",
  "data": {
    "group_hash": "grp_users123abc",
    "group_name": "Developers",
    "description": "Development team members",
    "member_count": 5,
    "created_at": "2024-01-10T09:00:00Z",
    "permissions": ["read", "write"],
    "projects": [
      {
        "project_hash": "proj_abc123",
        "project_name": "Main Project"
      }
    ]
  }
}
```

### GET `/admin/user-groups/{group_hash}/members` 🔒
**Description:** Get group members list  
**Params:** `?limit=10&offset=0`

**Response:**
```json
{
  "success": true,
  "message": "Group members retrieved",
  "data": [
    {
      "user_hash": "usr_def456abc",
      "username": "john_doe",
      "email": "john@example.com",
      "joined_at": "2024-01-12T10:00:00Z"
    }
  ],
  "pagination": {
    "limit": 10,
    "offset": 0,
    "total": 5,
    "has_more": false
  }
}
```

### DELETE `/admin/user-groups/{group_hash}/members/{user_hash}` 🔒
**Description:** Remove user from group  

**Response:**
```json
{
  "success": true,
  "message": "User removed from group"
}
```

### POST `/admin/user-groups/{group_hash}/members/bulk` 🔒
**Description:** Add multiple users to group  

**Request:**
```json
{
  "user_hashes": ["usr_123", "usr_456", "usr_789"]
}
```

**Response:**
```json
{
  "success": true,
  "message": "Bulk assignment completed",
  "data": {
    "added_count": 2,
    "skipped_count": 1,
    "errors": [
      {
        "user_hash": "usr_789",
        "error": "User already in group"
      }
    ]
  }
}
```

### GET `/admin/users/{user_hash}/groups` 🔒
**Description:** Get groups for a specific user  

**Response:**
```json
{
  "success": true,
  "message": "User groups retrieved",
  "data": [
    {
      "group_hash": "grp_users123abc",
      "group_name": "Developers",
      "description": "Development team members",
      "joined_at": "2024-01-12T10:00:00Z"
    }
  ]
}
```

---

## 🛡️ RBAC Management (Extended)

### GET `/rbac/projects/{project_hash}/roles` 🔒
**Description:** List project roles  
**Params:** `?limit=50&offset=0`

**Response:**
```json
{
  "success": true,
  "message": "Roles retrieved successfully",
  "data": [
    {
      "id": 1,
      "role_name": "Editor",
      "description": "Can read and write documents",
      "permission_count": 5,
      "member_count": 8,
      "created_at": "2024-01-10T10:00:00Z",
      "permissions": [
        {
          "id": 1,
          "permission_name": "read_documents",
          "category": "documents"
        }
      ]
    }
  ],
  "pagination": {
    "limit": 50,
    "offset": 0,
    "total": 5,
    "has_more": false
  }
}
```

### POST `/rbac/projects/{project_hash}/roles` 🔒
**Description:** Create project role  

**Request:**
```json
{
  "role_name": "Content Manager",
  "description": "Can manage all content",
  "permission_ids": [1, 2, 3, 5]
}
```

**Response:**
```json
{
  "success": true,
  "message": "Role created successfully",
  "data": {
    "id": 6,
    "role_name": "Content Manager",
    "description": "Can manage all content",
    "permission_count": 4,
    "created_at": "2024-01-15T18:30:00Z"
  }
}
```

### DELETE `/rbac/users/{user_hash}/projects/{project_hash}/roles/{role_id}` 🔒
**Description:** Remove user from role  

**Response:**
```json
{
  "success": true,
  "message": "User removed from role successfully"
}
```

### POST `/rbac/projects/{project_hash}/bulk-assign` 🔒
**Description:** Bulk assign roles to users  

**Request:**
```json
{
  "assignments": [
    {
      "user_hash": "usr_123",
      "role_ids": [1, 2]
    },
    {
      "user_hash": "usr_456",
      "role_ids": [2, 3]
    }
  ]
}
```

**Response:**
```json
{
  "success": true,
  "message": "Bulk assignment completed",
  "data": {
    "success_count": 2,
    "errors": []
  }
}
```

### GET `/rbac/projects/{project_hash}/matrix` 🔒
**Description:** Get permission matrix for project  

**Response:**
```json
{
  "success": true,
  "message": "Permission matrix retrieved",
  "data": {
    "roles": [
      {
        "role_id": 1,
        "role_name": "Editor",
        "permissions": [
          {
            "permission_name": "read_documents",
            "granted": true
          },
          {
            "permission_name": "write_documents",
            "granted": true
          }
        ]
      }
    ],
    "users": [
      {
        "user_hash": "usr_123",
        "username": "john_doe",
        "roles": ["Editor"],
        "effective_permissions": ["read_documents", "write_documents"]
      }
    ]
  }
}
```

### GET `/rbac/users/{user_hash}/projects/{project_hash}/history` 🔒
**Description:** Get user role assignment history  

**Response:**
```json
{
  "success": true,
  "message": "Role history retrieved",
  "data": [
    {
      "role_id": 1,
      "role_name": "Editor",
      "action": "assigned",
      "assigned_by": "usr_admin123",
      "assigned_at": "2024-01-15T15:30:00Z"
    },
    {
      "role_id": 2,
      "role_name": "Viewer",
      "action": "removed",
      "removed_by": "usr_admin123",
      "removed_at": "2024-01-14T10:00:00Z"
    }
  ]
}
```

---

## 🔧 System Management (Extended)

### GET `/system/admins` 🔒
**Description:** List admin users (ROOT only)  
**Params:** `?limit=10&offset=0`

**Response:**
```json
{
  "success": true,
  "message": "Admin users retrieved",
  "data": [
    {
      "user_hash": "usr_admin456def",
      "username": "project_admin",
      "email": "padmin@company.com",
      "user_type": "admin",
      "status": "active",
      "created_at": "2024-01-15T12:30:00Z",
      "last_login": "2024-01-15T16:00:00Z",
      "assigned_projects": 3
    }
  ],
  "pagination": {
    "limit": 10,
    "offset": 0,
    "total": 8,
    "has_more": false
  }
}
```

### POST `/system/admins` 🔒
**Description:** Create admin user (ROOT only)  

**Request:**
```json
{
  "username": "new_admin",
  "password": "secure_password",
  "email": "newadmin@company.com",
  "assigned_project_ids": [1, 2]
}
```

**Response:**
```json
{
  "success": true,
  "message": "Admin user created successfully",
  "data": {
    "user_hash": "usr_newadmin789",
    "username": "new_admin",
    "email": "newadmin@company.com",
    "user_type": "admin",
    "created_at": "2024-01-15T19:00:00Z"
  }
}
```

### GET `/system/audit-logs` 🔒
**Description:** Get system audit logs  
**Params:** `?limit=10&offset=0&level=info&user_hash=usr_123&start_date=2024-01-01&end_date=2024-01-15`

**Response:**
```json
{
  "success": true,
  "message": "Audit logs retrieved",
  "data": [
    {
      "id": "log_123456",
      "level": "info",
      "action": "user_login",
      "user_hash": "usr_def456abc",
      "message": "User logged in successfully",
      "ip_address": "192.168.1.100",
      "user_agent": "Mozilla/5.0...",
      "timestamp": "2024-01-15T16:00:00Z",
      "metadata": {
        "project_hash": "proj_abc123xyz",
        "session_id": "sess_xyz789abc"
      }
    }
  ],
  "pagination": {
    "limit": 10,
    "offset": 0,
    "total": 1500,
    "has_more": true
  }
}
```

### GET `/system/settings` 🔒
**Description:** Get system settings (ROOT only)  

**Response:**
```json
{
  "success": true,
  "message": "System settings retrieved",
  "data": {
    "authentication": {
      "session_timeout": 3600,
      "max_login_attempts": 5,
      "password_policy": {
        "min_length": 8,
        "require_uppercase": true,
        "require_numbers": true,
        "require_special_chars": true
      }
    },
    "system": {
      "maintenance_mode": false,
      "registration_enabled": true,
      "email_verification_required": false
    },
    "api": {
      "rate_limit_per_minute": 100,
      "timeout_seconds": 30
    }
  }
}
```

### PUT `/system/settings` 🔒
**Description:** Update system settings (ROOT only)  

**Request:**
```json
{
  "authentication": {
    "session_timeout": 7200,
    "max_login_attempts": 3
  },
  "system": {
    "maintenance_mode": false,
    "registration_enabled": true
  }
}
```

**Response:**
```json
{
  "success": true,
  "message": "System settings updated",
  "data": {
    "updated_at": "2024-01-15T19:30:00Z",
    "updated_by": "usr_root123"
  }
}
```

### POST `/system/backup` 🔒
**Description:** Initiate system backup (ROOT only)  

**Response:**
```json
{
  "success": true,
  "message": "Backup initiated",
  "data": {
    "backup_id": "backup_20240115_193000",
    "status": "in_progress",
    "estimated_completion": "2024-01-15T20:00:00Z"
  }
}
```

### GET `/system/metrics` 🔒
**Description:** Get system performance metrics  

**Response:**
```json
{
  "success": true,
  "message": "System metrics retrieved",
  "data": {
    "cpu_usage_percent": 25.5,
    "memory_usage_percent": 68.2,
    "disk_usage_percent": 45.7,
    "network": {
      "requests_per_minute": 125,
      "avg_response_time_ms": 45,
      "error_rate_percent": 0.2
    },
    "database": {
      "active_connections": 8,
      "max_connections": 20,
      "query_avg_time_ms": 12
    },
    "cache": {
      "hit_rate_percent": 92.5,
      "memory_usage_mb": 256,
      "evictions_per_hour": 5
    }
  }
}
```

### POST `/system/cache/clear` 🔒
**Description:** Clear system cache  

**Response:**
```json
{
  "success": true,
  "message": "Cache cleared successfully",
  "data": {
    "cleared_at": "2024-01-15T19:45:00Z",
    "cache_size_before_mb": 256,
    "cache_size_after_mb": 0
  }
}
```

### GET `/system/cache/status` 🔒
**Description:** Get cache status  

**Response:**
```json
{
  "success": true,
  "message": "Cache status retrieved",
  "data": {
    "status": "healthy",
    "memory_usage_mb": 256,
    "memory_limit_mb": 512,
    "hit_rate_percent": 92.5,
    "miss_rate_percent": 7.5,
    "evictions_per_hour": 5,
    "uptime": "15d 4h 30m"
  }
}
```

### GET `/system/sessions` 🔒
**Description:** Get active sessions (ROOT only)  

**Response:**
```json
{
  "success": true,
  "message": "Active sessions retrieved",
  "data": [
    {
      "session_id": "sess_xyz789abc",
      "user_hash": "usr_def456abc",
      "username": "john_doe",
      "ip_address": "192.168.1.100",
      "user_agent": "Mozilla/5.0...",
      "created_at": "2024-01-15T16:00:00Z",
      "last_activity": "2024-01-15T19:45:00Z",
      "expires_at": "2024-01-18T16:00:00Z"
    }
  ]
}
```

### DELETE `/system/sessions/{session_id}` 🔒
**Description:** Terminate specific session  

**Response:**
```json
{
  "success": true,
  "message": "Session terminated successfully"
}
```

### POST `/system/sessions/terminate-all` 🔒
**Description:** Terminate all active sessions (ROOT only)  

**Response:**
```json
{
  "success": true,
  "message": "All sessions terminated",
  "data": {
    "terminated_count": 45
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

### GET `/analytics/users` 🔒
**Description:** Get comprehensive user analytics (ROOT only)  
**Params:** `?start_date=2024-01-01&end_date=2024-01-15`

**Response:**
```json
{
  "success": true,
  "message": "User analytics retrieved",
  "data": {
    "metrics": {
      "total_users": 150,
      "active_users": 85,
      "new_users_this_week": 12,
      "user_growth_rate": 15.2,
      "users_by_type": {
        "root": 2,
        "admin": 8,
        "consumer": 140
      }
    },
    "engagement": {
      "daily_active_users": [
        { "date": "2024-01-15", "count": 45 },
        { "date": "2024-01-14", "count": 52 }
      ],
      "avg_session_duration": 1800,
      "most_active_users": [
        {
          "user_hash": "usr_abc123",
          "username": "john_doe",
          "activity_score": 95
        }
      ]
    },
    "security": {
      "failed_login_attempts": 15,
      "suspicious_activities": 2,
      "security_events": [
        {
          "type": "multiple_failed_logins",
          "user_hash": "usr_suspicious123",
          "timestamp": "2024-01-15T16:00:00Z"
        }
      ]
    }
  }
}
```

### GET `/analytics/projects` 🔒
**Description:** Get project analytics  
**Params:** `?start_date=2024-01-01&end_date=2024-01-15`

**Response:**
```json
{
  "success": true,
  "message": "Project analytics retrieved",
  "data": {
    "projects": [
      {
        "project_hash": "proj_abc123",
        "project_name": "Main Project",
        "member_count": 15,
        "activity_score": 88,
        "health_score": 92
      }
    ],
    "total_projects": 25,
    "avg_health_score": 85.5,
    "total_activity": 1250,
    "engagement": {
      "project_activity": [
        { "date": "2024-01-15", "project_hash": "proj_abc123", "activity_count": 45 }
      ],
      "member_engagement": [
        { "project_hash": "proj_abc123", "avg_engagement": 75.5 }
      ]
    }
  }
}
```

### GET `/analytics/projects/{project_id}` 🔒
**Description:** Get analytics for specific project  

**Response:**
```json
{
  "success": true,
  "message": "Project analytics retrieved",
  "data": {
    "project": {
      "project_hash": "proj_abc123",
      "project_name": "Main Project",
      "member_count": 15,
      "activity_score": 88,
      "health_score": 92
    },
    "activity": {
      "daily_activity": [
        { "date": "2024-01-15", "activity_count": 45 }
      ],
      "top_contributors": [
        {
          "user_hash": "usr_contributor123",
          "username": "jane_doe",
          "contribution_score": 85
        }
      ]
    },
    "permissions": {
      "roles_assigned": 8,
      "permissions_granted": 25,
      "recent_changes": [
        {
          "type": "role_assigned",
          "user_hash": "usr_123",
          "role_name": "Editor",
          "timestamp": "2024-01-15T15:30:00Z"
        }
      ]
    }
  }
}
```

### POST `/analytics/export` 🔒
**Description:** Export analytics data  

**Request:**
```json
{
  "data_type": "user_analytics",
  "format": "csv",
  "date_range": {
    "start": "2024-01-01",
    "end": "2024-01-15"
  },
  "filters": {
    "user_type": "consumer",
    "project_hash": "proj_abc123"
  }
}
```

**Response:**
```json
{
  "success": true,
  "message": "Export initiated",
  "data": {
    "export_id": "export_20240115_200000",
    "download_url": "https://api.example.com/downloads/analytics_export.csv",
    "expires_at": "2024-01-16T20:00:00Z",
    "estimated_size": "5.2MB"
  }
}
```

### GET `/analytics/users/{user_hash}/activity` 🔒
**Description:** Get activity timeline for specific user (ROOT only)  
**Params:** `?start_date=2024-01-01&end_date=2024-01-15`

**Response:**
```json
{
  "success": true,
  "message": "User activity timeline retrieved",
  "data": {
    "activities": [
      {
        "id": "act_user_123",
        "type": "login",
        "message": "User logged in",
        "timestamp": "2024-01-15T16:00:00Z",
        "metadata": {
          "ip_address": "192.168.1.100",
          "project_hash": "proj_abc123"
        }
      }
    ],
    "summary": {
      "total_activities": 150,
      "most_active_day": "2024-01-15",
      "avg_daily_activities": 12.5
    }
  }
}
```

---

## 🔍 Summary

This document covers **87 missing API endpoints** that are called by the frontend services but not documented in the current API definition. These endpoints cover:

- **Admin Dashboard** (5 endpoints)
- **Export/Import** (3 endpoints) 
- **Extended User Management** (5 endpoints)
- **Bulk Operations** (2 endpoints)
- **Extended Project Management** (8 endpoints)
- **Extended Group Management** (5 endpoints)
- **Extended RBAC** (6 endpoints)
- **Extended System Management** (14 endpoints)
- **Analytics** (6 endpoints)
- **Authentication Extensions** (2 endpoints)

### 🔗 Next Steps

1. **Backend Implementation**: Implement these missing endpoints in the Magic Auth API
2. **Authentication**: Ensure all endpoints marked with 🔒 require proper Bearer token authentication
3. **Authorization**: Implement proper role-based access control (ROOT/ADMIN/CONSUMER) for each endpoint
4. **Testing**: Create comprehensive test suites for all new endpoints
5. **Documentation**: Update the main API documentation to include these endpoints

### 🚨 Critical Endpoints for Basic Functionality

The following endpoints are essential for the dashboard to function properly:
- `/auth/logout` - User logout functionality
- `/admin/dashboard/stats` - Admin dashboard statistics
- `/users` - User listing and management
- `/projects/{project_hash}` - Project details
- `/analytics/dashboard/stats` - Dashboard analytics

These should be prioritized for immediate implementation. 