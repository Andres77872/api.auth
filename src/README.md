# 🔐 Group-Based Multi-Project Authentication API

A comprehensive authentication system with **hierarchical group-based access control** and **complete RBAC** capabilities for enterprise-grade access control.

## 🏗️ Groups-of-Groups Architecture

```
USER → USER_GROUP → PROJECT_GROUP → PROJECTS
                 ↘
                   PERMISSION_GROUP → PERMISSIONS
```

**Key Concepts:**
- **Users** belong to **User Groups** (organizational teams)
- **User Groups** have access to **Project Groups** (project containers)
- **Project Groups** contain related **Projects**
- **User Groups** also have **Permission Groups** assigned
- **Permission Groups** contain individual **Permissions**

## 🌟 User Types

| Type | Description | Access Level |
|------|-------------|--------------|
| 🔴 `root` | System administrators | Full global access |
| 🟡 `admin` | Project administrators | Manage users in their projects |
| 🟢 `consumer` | Regular users | Self-service + project access via groups |

## ✨ Features

### 🔐 Authentication & Sessions
- Two-token JWT model with short-lived access tokens and 72-hour sliding refresh families
- Dual access-token authentication (Bearer access token + secure `session_token` access cookie)
- Refresh-token transport through HttpOnly Secure `refresh_token` cookie or explicit `refresh_token` body/form field
- Multi-project login and project switching
- Platform login for root/admin users and platform refresh through `/auth/refresh`
- Session validation, strict single-use refresh rotation, logout, switch-project, and deactivation revocation

### 👥 Hierarchical Group Management
- **User Groups**: Organize users globally, control project access
- **Project Groups**: Container for related projects
- **Permission Groups**: Reusable permission templates

### 🎭 Global Role & Permission System
- **Global Roles**: One role per user with permission groups
- **Permission Groups**: Reusable bundles assignable to users/groups
- **Permissions**: Granular individual permissions
- Real-time permission validation with caching

### 🛡️ Enterprise Security
- Multi-layer security (transport, auth, authorization, data isolation)
- UUID-based identification (`usr-{UUID4}`, `proj-{UUID4}`)
- Comprehensive audit trails
- Redis-based session and permission caching

## 📚 Documentation

### 📖 Usage Guides

| Guide | Description |
|-------|-------------|
| [📚 Documentation Home](/documentation) | Main documentation index |
| [🔐 Authentication](/documentation/USAGE/authentication-usage-cases.md) | Login, sessions, tokens, project switching |
| [👤 Users](/documentation/USAGE/users/README.md) | Profile management, admin operations |
| [👥 Groups](/documentation/USAGE/groups/README.md) | User groups, project groups, flows, troubleshooting |
| [📁 Projects](/documentation/USAGE/projects/README.md) | Project management suite, access control |
| [🔑 Permissions](/documentation/USAGE/permissions-usage-cases.md) | Roles, permission groups, assignments |
| [⚙️ Admin](/documentation/USAGE/admin-usage-cases.md) | Dashboard, bulk operations, cache management |

**For LLM/API consumption**: Add `?format=raw` to any URL to get plain markdown.

## 📡 API Endpoints Overview

### Authentication (`/auth`) - 8 endpoints
- `POST /auth/login` - User login
- `POST /auth/platform/login` - Root/admin platform login without project binding; refreshable through `/auth/refresh`
- `POST /auth/register` - New user registration
- `GET /auth/validate` - Validate access token only
- `POST /auth/logout` - End session and revoke refresh continuity
- `POST /auth/refresh` - Rotate using refresh token only; access/session tokens are rejected
- `POST /auth/switch-project` - Switch project context and rotate access+refresh credentials
- `POST /auth/check-availability` - Check username/email

### Users (`/users`) - 9 endpoints
- `GET /users/profile` - Get current user profile
- `PUT /users/profile` - Update profile
- `GET /users/access-summary` - Hierarchical access summary
- `GET /users/list` - List users (admin)
- `GET /users/search/query` - Search users (admin)
- `GET /users/{user_hash}` - Get user details
- `PUT /users/{user_hash}/status` - Update status
- `POST /users/{user_hash}/reset-password` - Reset password
- `DELETE /users/{user_hash}` - Delete user

### Projects (`/projects`) - 11 endpoints
- `POST /projects` - Create project
- `GET /projects` - List projects
- `GET /projects/{hash}` - Get details
- `PUT /projects/{hash}` - Update project
- `DELETE /projects/{hash}` - Delete project
- `GET /projects/{hash}/members` - Get members
- `GET /projects/{hash}/groups` - Get groups
- `GET /projects/{hash}/activity` - Get activity
- `GET /projects/{hash}/stats` - Get statistics
- `PATCH /projects/{hash}/owner` - Change owner (currently 501)
- `PATCH /projects/{hash}/archive` - Archive/unarchive project (currently 501)

### User Groups (`/admin/user-groups`) - 12 endpoints
- `POST /admin/user-groups` - Create group
- `GET /admin/user-groups` - List groups
- `GET /admin/user-groups/{hash}` - Get details
- `PUT /admin/user-groups/{hash}` - Update group
- `DELETE /admin/user-groups/{hash}` - Delete group
- `GET /admin/user-groups/{hash}/members` - Get members
- `POST /admin/user-groups/{hash}/members` - Add member
- `POST /admin/user-groups/{hash}/members/bulk` - Bulk add
- `DELETE /admin/user-groups/{hash}/members/{user}` - Remove member
- `GET /admin/user-groups/{hash}/project-groups` - Get project access
- `POST /admin/user-groups/{hash}/project-groups` - Grant access
- `DELETE /admin/user-groups/{hash}/project-groups/{pg}` - Revoke access

### Project Groups (`/admin/project-groups`) - 8 endpoints
- `POST /admin/project-groups` - Create group
- `GET /admin/project-groups` - List groups
- `GET /admin/project-groups/{hash}` - Get details
- `PUT /admin/project-groups/{hash}` - Update group
- `DELETE /admin/project-groups/{hash}` - Delete group
- `GET /admin/project-groups/{hash}/projects` - Get projects
- `POST /admin/project-groups/{hash}/projects` - Add project
- `DELETE /admin/project-groups/{hash}/projects/{proj}` - Remove project

### Roles (`/roles`) - 10 endpoints
- `POST /roles/roles` - Create role
- `GET /roles/roles` - List roles
- `GET /roles/roles/{hash}` - Get details
- `PUT /roles/roles/{hash}` - Update role
- `DELETE /roles/roles/{hash}` - Delete role
- `POST /roles/roles/{hash}/permission-groups/{pg}` - Add permission group
- `DELETE /roles/roles/{hash}/permission-groups/{pg}` - Remove permission group
- `GET /roles/users/{user_hash}/role` - Get user's role
- `POST /roles/users/{user_hash}/role` - Assign role
- `GET /roles/users/me/role` - Get my role

### Permission Groups (`/roles/permission-groups`) - 8 endpoints
- `POST /roles/permission-groups` - Create group
- `GET /roles/permission-groups` - List groups
- `GET /roles/permission-groups/{hash}` - Get details
- `PUT /roles/permission-groups/{hash}` - Update group
- `DELETE /roles/permission-groups/{hash}` - Delete group
- `GET /roles/permission-groups/{hash}/permissions` - Get permissions
- `POST /roles/permission-groups/{hash}/permissions` - Add permission
- `DELETE /roles/permission-groups/{hash}/permissions/{p}` - Remove permission

### Permissions (`/permissions`) - 7 endpoints
- `GET /roles/permissions` - List all permissions
- `GET /permissions/users/me/permissions` - Get my permissions
- `POST /permissions/users/me/permissions/check` - Check permission
- `GET /permissions/users/me/permission-groups` - My permission groups
- `GET /permissions/users/me/sources` - Permission sources
- `POST /permissions/admin/user-groups/{hash}/permission-groups` - Assign to group
- `POST /permissions/users/{user}/permission-groups` - Assign to user

### System (`/system`) - 7 endpoints
- `GET /system/info` - System info (public)
- `GET /system/health` - Health check (public)
- `GET /system/ping` - Simple ping (public)
- `GET /system/cache/stats` - Cache stats
- `POST /system/cache/clear` - Clear cache (admin)
- `POST /system/cache/invalidate/user/{hash}` - Invalidate user
- `POST /system/cache/invalidate/project/{id}` - Invalidate project

### Admin Dashboard (`/admin`) - 7 endpoints
- `GET /admin/dashboard/stats` - Dashboard statistics
- `GET /admin/activity` - Activity feed
- `GET /admin/activity/types` - Activity types
- `GET /admin/health` - Detailed health
- `GET /admin/users/statistics` - User statistics
- `GET /admin/projects/statistics` - Project statistics
- `GET /admin/system/overview` - System overview

### Bulk Operations (`/admin`) - 4 endpoints
- `POST /admin/users/bulk-update` - Bulk update users
- `POST /admin/users/bulk-delete` - Bulk delete users
- `POST /admin/projects/{hash}/bulk-assign-roles` - Bulk assign roles
- `POST /admin/user-groups/bulk-assign` - Bulk assign groups

## 🔑 Key Features

### Form Data API
All API endpoints use **Form Data** (`application/x-www-form-urlencoded`):
- Consistent across all endpoints
- Bulk operations use JSON for arrays
- Responses are JSON with Pydantic validation

### Auth Token Contract
- **Access token**: short-lived JWT used for protected routes, `/auth/validate`, `/auth/logout`, and `/auth/switch-project`.
- **Refresh token**: 72-hour sliding JWT used only for `/auth/refresh`; returned in the JSON body and as HttpOnly Secure `refresh_token` cookie.
- **`session_token`**: deprecated alias for the access token in response bodies and access cookie.
- **Refresh transport**: `refresh_token` cookie or explicit `refresh_token` body/form field. `Authorization: Bearer <access_token>` is not accepted by `/auth/refresh`.
- **JWT authority**: request paths enforce signature, `exp`, `type`, `jti`, `session_id`, `family_id`, and Redis session/family state.

### Access Authentication
- **Bearer Access Token**: `Authorization: Bearer <access_token>`
- **HTTP-Only Access Cookie**: Secure `session_token` cookie
- Automatic fallback between access-token methods

### Caching Strategy
- **Access Session Cache**: short-lived, keyed by access-token `jti`
- **Refresh Family Cache**: 72-hour sliding TTL, keyed by `family_id`/refresh `jti`
- **Permission Cache**: 30 minutes TTL
- **Access Cache**: 30 minutes TTL
- **Automatic Invalidation**: On user/role changes

## 🚚 Deployment, Migration, and Rollback

- `JWT_SECRET_KEY` is mandatory outside explicit tests. Missing it is a startup/auth configuration failure, not a recoverable credential error.
- This auth contract is intentionally breaking: legacy access/session tokens cannot refresh and may require users to log in again.
- Clients must store/use `refresh_token`, serialize refresh calls, retry the original request once after successful refresh, and stop retrying if refresh fails due to invalid/reused/revoked/expired refresh token.
- New Redis namespaces (`refresh_family:*`, `refresh_token:*`, `refresh_used:*`, `revoked_family:*`, `user_sessions:*`, `user_refresh_families:*`) can expire naturally. Rollback means redeploying the previous release and clearing/expiring those namespaces if needed.
- Do not silently re-enable legacy access-token refresh unless a new spec explicitly supersedes this contract.

## 🆘 Quick Troubleshooting

| Problem | Solution |
|---------|----------|
| Authentication failing | Check `JWT_SECRET_KEY`; it is required outside tests |
| Permission errors | Verify role and permission group assignments |
| Access token expired | Use `/auth/refresh` with the refresh token; re-authenticate if refresh fails |
| Refresh rejected | Send a valid `refresh_token`; `/auth/refresh` rejects access/session tokens and `Authorization: Bearer` refresh transport |
| Database errors | Verify MySQL connection and schema |
| Cache issues | Use `/system/cache/clear` endpoint |

## 💝 Support

**Version**: 2.2.0 | **Total Endpoints**: 90+

This authentication system is free and open for everyone!

**[Support on Patreon](https://patreon.com/findit_moe)** 🙏
