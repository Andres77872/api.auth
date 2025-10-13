# Complete API Endpoints Reference

## Overview

The API provides **95+ REST endpoints** organized into **11 functional modules**. This document catalogs all endpoints with their HTTP methods, authentication requirements, and primary purposes.

---

## Module 1: Authentication (8 endpoints)

**Base Path:** `/auth`

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|
| POST | `/auth/login` | No | Authenticate user and get session token |
| POST | `/auth/register` | No | Register new consumer user |
| POST | `/auth/logout` | Yes | Invalidate session and logout |
| GET | `/auth/validate` | Yes | Validate session token |
| POST | `/auth/switch-project` | Yes | Switch to different accessible project |
| POST | `/auth/check-availability` | No | Check username/email availability |
| POST | `/auth/refresh` | Yes | Refresh session token |
| HEAD | `/access` | Yes | Legacy token validation (middleware) |

**Key Features:**
- 3-tier user type aware authentication
- Multi-project session management
- Auto-project selection for users
- Group context in sessions

---

## Module 2: User Management (7 endpoints)

**Base Path:** `/users`

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|
| GET | `/users/profile` | Yes | Get current user profile |
| PUT | `/users/profile` | Yes | Update current user profile |
| GET | `/users/access-summary` | Yes | Get user's access and group summary |
| GET | `/users/list` | Admin | List all users with filtering |
| GET | `/users/{user_hash}` | Yes* | Get specific user details |
| PUT | `/users/{user_hash}/status` | Admin | Activate/deactivate user |
| POST | `/users/{user_hash}/reset-password` | Admin | Reset user password |

*Users can view themselves, admins can view any

---

## Module 3: User Type Management (10 endpoints)

**Base Path:** `/user-types`

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|
| POST | `/user-types/root` | Root Only | Create new root user |
| POST | `/user-types/admin` | Root Only | Create new admin user |
| GET | `/user-types/{user_hash}/info` | Yes* | Get user type information |
| PUT | `/user-types/{user_hash}/type` | Root Only | Change user type |
| GET | `/user-types/admin/{user_hash}/projects` | Admin* | Get admin's project assignments |
| PUT | `/user-types/admin/{user_hash}/projects` | Root Only | Replace admin's projects |
| POST | `/user-types/admin/{user_hash}/projects/add` | Root Only | Add admin to project |
| DELETE | `/user-types/admin/{user_hash}/projects/{project_id}` | Root Only | Remove admin from project |
| GET | `/user-types/stats` | Admin | Get user type statistics |
| GET | `/user-types/users/{user_type}` | Yes* | List users by type |

*Access controls vary by user type

---

## Module 4: Project Management (14 endpoints)

**Base Path:** `/projects`

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|
| GET | `/projects` | Yes | List accessible projects |
| POST | `/projects` | Admin | Create new project |
| GET | `/projects/{project_hash}` | Yes | Get project details |
| PUT | `/projects/{project_hash}` | Admin | Update project |
| DELETE | `/projects/{project_hash}` | Admin | Delete project |
| PATCH | `/projects/{project_hash}/owner` | Admin | Transfer project ownership |
| PATCH | `/projects/{project_hash}/archive` | Admin | Archive/unarchive project |
| GET | `/projects/{project_hash}/activity` | Yes | Get project activity log |
| GET | `/projects/{project_hash}/stats` | Yes | Get project statistics |
| GET | `/projects/{project_hash}/members` | Admin | List project members |
| POST | `/projects/{project_hash}/members` | Admin | Add member to project |
| DELETE | `/projects/{project_hash}/members/{user_hash}` | Admin | Remove member from project |
| GET | `/projects/{project_hash}/groups` | Yes | List user groups with project access |
| POST | `/projects/{project_hash}/groups` | Admin | Grant group access to project |

---

## Module 5: Admin - User Groups (12 endpoints)

**Base Path:** `/admin/user-groups`

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|
| GET | `/admin/user-groups` | Admin | List all user groups |
| POST | `/admin/user-groups` | Admin | Create user group |
| GET | `/admin/user-groups/{group_hash}` | Admin | Get user group details |
| PUT | `/admin/user-groups/{group_hash}` | Admin | Update user group |
| DELETE | `/admin/user-groups/{group_hash}` | Admin | Delete user group |
| POST | `/admin/user-groups/{group_hash}/members` | Admin | Add user to group |
| DELETE | `/admin/user-groups/{group_hash}/members/{user_hash}` | Admin | Remove user from group |
| GET | `/admin/user-groups/{group_hash}/members` | Admin | List group members |
| POST | `/admin/user-groups/{group_hash}/members/bulk` | Admin | Bulk add users to group |
| GET | `/admin/user-groups/users/{user_hash}/groups` | Admin | Get user's groups |
| POST | `/admin/user-groups/{group_hash}/projects` | Admin | Grant group project access |
| DELETE | `/admin/user-groups/{group_hash}/projects/{project_hash}` | Admin | Revoke group project access |

---

## Module 6: Admin - Project Groups (8 endpoints)

**Base Path:** `/admin/project-groups`

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|
| GET | `/admin/project-groups` | Admin | List all project groups |
| POST | `/admin/project-groups` | Admin | Create project group |
| GET | `/admin/project-groups/{group_hash}` | Admin | Get project group details |
| PUT | `/admin/project-groups/{group_hash}` | Admin | Update project group |
| DELETE | `/admin/project-groups/{group_hash}` | Admin | Delete project group |
| POST | `/admin/project-groups/{group_hash}/projects` | Admin | Assign project to group |
| DELETE | `/admin/project-groups/{group_hash}/projects/{project_hash}` | Admin | Remove project from group |
| GET | `/admin/project-groups/{group_hash}/projects` | Admin | List group's projects |

---

## Module 7: Admin Dashboard (6 endpoints)

**Base Path:** `/admin`

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|
| GET | `/admin/dashboard/stats` | Admin | Get dashboard statistics |
| GET | `/admin/activity` | Admin | Get activity feed |
| GET | `/admin/health` | Admin | Get system health |
| GET | `/admin/activity/types` | Admin | List activity types |
| GET | `/admin/users/statistics` | Admin | Get user statistics |
| GET | `/admin/projects/statistics` | Admin | Get project statistics |

---

## Module 8: Analytics (5 endpoints)

**Base Path:** `/analytics`

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|
| GET | `/analytics/dashboard/stats` | Admin | Dashboard analytics |
| GET | `/analytics/users` | Admin | User analytics |
| GET | `/analytics/projects` | Admin | Project analytics |
| GET | `/analytics/activity` | Admin | Activity analytics |
| GET | `/analytics/summary` | Admin | Analytics summary |

---

## Module 9: Global Roles System (22 endpoints)

**Base Path:** `/roles`

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|  
| POST | `/roles/roles` | Admin | Create global role |
| GET | `/roles/roles` | Yes | List all global roles |
| GET | `/roles/roles/{role_hash}` | Yes | Get role details |
| PUT | `/roles/roles/{role_hash}` | Admin | Update role |
| DELETE | `/roles/roles/{role_hash}` | Admin | Delete role |
| POST | `/roles/permission-groups` | Admin | Create permission group |
| GET | `/roles/permission-groups` | Yes | List permission groups |
| GET | `/roles/permission-groups/{group_hash}` | Yes | Get permission group details |
| POST | `/roles/permissions` | Admin | Create global permission |
| GET | `/roles/permissions` | Yes | List all permissions |
| GET | `/roles/permissions/{permission_hash}` | Yes | Get permission details |
| POST | `/roles/roles/{role_hash}/permission-groups/{group_hash}` | Admin | Assign permission group to role |
| GET | `/roles/roles/{role_hash}/permission-groups` | Yes | Get role's permission groups |
| POST | `/roles/permission-groups/{group_hash}/permissions/{permission_hash}` | Admin | Assign permission to group |
| GET | `/roles/permission-groups/{group_hash}/permissions` | Yes | Get group's permissions |
| PUT | `/roles/users/{user_hash}/role` | Admin | Assign role to user |
| GET | `/roles/users/{user_hash}/role` | Yes | Get user's role |
| GET | `/roles/users/me/role` | Yes | Get current user's role |
| GET | `/roles/users/me/permissions` | Yes | Get current user's permissions |
| GET | `/roles/users/me/permissions/check/{permission_name}` | Yes | Check specific permission |
| POST | `/roles/projects/{project_hash}/catalog/roles/{role_hash}` | Admin | Add role to project catalog (metadata) |
| GET | `/roles/projects/{project_hash}/catalog/roles` | Yes | Get project cataloged roles |

---

## Module 10: System Information (6 endpoints)

**Base Path:** `/system`

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|
| GET | `/system/info` | No | Get system information |
| GET | `/system/health` | No | System health check |
| GET | `/system/ping` | No | Simple ping endpoint |
| GET | `/system/cache/stats` | Yes | Get cache statistics |
| POST | `/system/cache/clear` | Admin | Clear entire cache |
| POST | `/system/cache/invalidate/user/{user_hash}` | Admin | Invalidate user cache |

---

## Module 11: Bulk Operations (4 endpoints)

**Base Path:** `/admin`

| Method | Endpoint | Auth Required | Purpose |
|--------|----------|---------------|---------|
| POST | `/admin/users/bulk-update` | Admin | Bulk update users |
| POST | `/admin/users/bulk-delete` | Admin | Bulk delete users |
| POST | `/admin/projects/{project_hash}/bulk-assign-roles` | Admin | Bulk assign roles |
| POST | `/admin/user-groups/bulk-assign` | Admin | Bulk assign users to groups |

---

## Authentication Types

### No Authentication Required (Public)
- `/auth/login`
- `/auth/register`
- `/auth/check-availability`
- `/system/info`
- `/system/health`
- `/system/ping`

### User Authentication Required
Most endpoints require a valid session token in the Authorization header:
```
Authorization: Bearer YOUR_SESSION_TOKEN
```

### Admin Authentication Required
Admin-only endpoints require admin or root user type:
- All `/admin/*` endpoints
- Project creation and management
- User management operations
- Group management operations

### Root-Only Authentication Required
Root-only endpoints require root user type:
- `/user-types/root` (create root user)
- `/user-types/admin` (create admin user)
- `/user-types/{user_hash}/type` (change user type)
- Admin project assignment management

---

## Common Query Parameters

### Pagination
```
?limit=50&offset=0
```
- Used across list endpoints
- Default limit varies by endpoint (10-50)
- Maximum limit usually 100-500

### Filtering
```
?search=query&user_type_filter=admin&group_filter=developers
```
- Search by text fields
- Filter by specific attributes
- Multiple filters can be combined

### Sorting
```
?sort_by=created_at&sort_order=desc
```
- Available on list endpoints
- Common sort fields: `created_at`, `updated_at`, `name`, `priority`
- Order: `asc` or `desc`

### Date Ranges
```
?days=30&start_date=2024-01-01&end_date=2024-01-31
```
- Used in analytics and activity endpoints
- Limit historical data retrieval

---

## Response Formats

### Success Response
```json
{
    "success": true,
    "message": "Operation successful",
    "data": { /* endpoint-specific data */ },
    "timestamp": "2024-01-15T10:30:00Z"
}
```

### Error Response
```json
{
    "success": false,
    "detail": "Error description",
    "error_code": "SPECIFIC_ERROR_CODE",
    "timestamp": "2024-01-15T10:30:00Z"
}
```

### Pagination Response
```json
{
    "success": true,
    "items": [ /* array of items */ ],
    "pagination": {
        "total": 150,
        "limit": 50,
        "offset": 0,
        "has_more": true,
        "next_offset": 50
    }
}
```

---

## Rate Limiting

### Default Limits
- **Public endpoints**: 100 requests/hour per IP
- **Authenticated endpoints**: 1000 requests/hour per user
- **Admin endpoints**: 2000 requests/hour per admin
- **Bulk operations**: 100 requests/hour per admin

### Rate Limit Headers
```
X-RateLimit-Limit: 1000
X-RateLimit-Remaining: 987
X-RateLimit-Reset: 1704636000
```

---

## Versioning

### Current Version
- **API Version**: 2.2.0
- **Base URL**: `http://localhost:8000` (development)

### Version Header
```
X-API-Version: 2.2.0
```

### Backward Compatibility
- Legacy `/access` endpoint maintained for compatibility
- New features added without breaking existing endpoints
- Deprecation notices provided 6 months before removal

---

## WebSocket Endpoints (Future)

*Not yet implemented - planned for v3.0*

```
/ws/activities - Real-time activity stream
/ws/notifications - User notifications
/ws/system-events - System event stream
```

---

## Endpoint Statistics

### By HTTP Method
- **GET**: 48 endpoints (51%)
- **POST**: 30 endpoints (32%)
- **PUT**: 5 endpoints (5%)
- **PATCH**: 2 endpoints (2%)
- **DELETE**: 9 endpoints (9%)
- **HEAD**: 1 endpoint (1%)

### By Authentication Level
- **Public**: 6 endpoints (6%)
- **User**: 35 endpoints (37%)
- **Admin**: 51 endpoints (54%)
- **Root Only**: 4 endpoints (4%)

### By Module Size
1. Global Roles System: 22 endpoints
2. Project Management: 14 endpoints
3. Admin User Groups: 12 endpoints
4. User Type Management: 10 endpoints
5. Authentication: 8 endpoints

---

## Testing Endpoints

### Health Check Sequence
```bash
# 1. System ping
curl http://localhost:8000/system/ping

# 2. System info
curl http://localhost:8000/system/info

# 3. Health check
curl http://localhost:8000/system/health
```

### Authentication Flow
```bash
# 1. Check availability
curl -X POST http://localhost:8000/auth/check-availability \
  -d "username=testuser"

# 2. Register
curl -X POST http://localhost:8000/auth/register \
  -d "username=testuser&password=pass123&email=test@example.com&user_group_hash=grp123"

# 3. Login
curl -X POST http://localhost:8000/auth/login \
  -d "username=testuser&password=pass123"

# 4. Validate token
TOKEN="your_token_here"
curl -H "Authorization: Bearer $TOKEN" \
  http://localhost:8000/auth/validate
```

---

## Deprecated Endpoints

### Planned for Removal (v3.0)
- `HEAD /access` - Use `/auth/validate` instead

### Migration Paths
All deprecated endpoints will have direct replacements with migration guides provided.

---

**Related Documentation:**
- [Authentication API](../api/authentication.md)
- [User Management API](../api/user-management.md)
- [Global Roles System API](../api/global_roles.md)
- [Error Responses](../api/errors-and-responses.md)
