# 🔐 Group-Based Multi-Project Authentication System

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
- True access/refresh JWT model with Redis-backed revocation authority
- Short-lived access tokens for protected requests and `/auth/validate`
- 72-hour sliding refresh-token families for `/auth/refresh`
- HttpOnly Secure cookies for both `session_token` (access alias) and `refresh_token`
- Multi-project login and project switching
- Platform-scoped login for root/admin users
- Session validation, strict refresh rotation, logout, and deactivation revocation
- Username/email availability checking

### 👥 Hierarchical Group Management
- **User Groups**: Organize users globally
- **Project Groups**: Container for related projects
- **Permission Groups**: Reusable permission templates
- Groups-of-groups architecture for scalable access control

### 🎭 Complete RBAC Management
- **Global Roles**: Job function-based permission assignment
- **Permission Groups**: Create reusable permission templates
- **Permissions**: Granular individual permissions
- Real-time permission validation

### 📁 Project Management
- Project CRUD with group-based access
- Project members and statistics
- Activity tracking and audit logs
- Archive functionality

### 🔑 API Key Management
- User-scoped API keys for programmatic access
- Admin-scoped key management (create, revoke, inspect)
- Per-project and per-user key listing

### 🛡️ Enterprise Security
- Multi-layer security (transport, auth, authorization, data isolation)
- UUID-based identification (`usr-{UUID4}`, `proj-{UUID4}`)
- Comprehensive audit trails with export (CSV/JSON)
- Redis-based session caching

### 🔧 Admin Features
- Dashboard statistics and monitoring
- Activity feed with filtering and detail view
- Audit log browser with security events and statistics
- System health checks
- Cache management
- Bulk operations (update, delete, assign)

## 🚀 Quick Start

```bash
# 1. Clone and install
git clone <repository-url>
cd api.auth
pip install -r requirements.txt

# 2. Set environment variables
export DB_HOST=192.168.1.90
export DB_USER=your_mysql_user
export DB_MYSQL_PASSWORD=your_mysql_password
export DB_NAME=magic-auth
export DB_REDIS_PASSWORD=your_redis_password
export JWT_SECRET_KEY=your_jwt_secret
export API_KEY_PEPPER=your_api_key_pepper_secret

# 3. Initialize database
python scripts/recreate_database.py

# 4. Start the server
python -m uvicorn src.main:app --reload

# 5. Test the system
curl http://localhost:8000/system/ping
```

## 📡 Complete API Reference

### Authentication (`/auth`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/login` | POST | User login (requires `project_hash`) |
| `/auth/platform/login` | POST | Platform-scoped login for root/admin (no project required) |
| `/auth/register` | POST | New user registration |
| `/auth/validate` | GET | Validate an access token only |
| `/auth/logout` | POST | End session and revoke refresh continuity |
| `/auth/refresh` | POST | Rotate with a refresh token only |
| `/auth/switch-project` | POST | Switch project context and rotate access+refresh tokens |
| `/auth/check-availability` | POST | Check username/email availability |

### Users (`/users`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/users/profile` | GET | Get current user profile |
| `/users/profile` | PUT | Update current user profile |
| `/users/access-summary` | GET | Get hierarchical access summary |
| `/users/list` | GET | List users with filters (admin) |
| `/users/search/query` | GET | Search users (admin) |
| `/users/{user_hash}` | GET | Get user details |
| `/users/{user_hash}` | PUT | Update user details (admin/root) |
| `/users/{user_hash}/status` | PUT | Update user status |
| `/users/{user_hash}/type` | PATCH | Change user type (root only) |
| `/users/{user_hash}/reset-password` | POST | Reset password (admin) |
| `/users/{user_hash}` | DELETE | Delete user (admin) |

### User API Keys (`/users/api-keys`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/users/api-keys` | POST | Create own API key |
| `/users/api-keys` | GET | List own API keys |
| `/users/api-keys/{key_id}` | GET | Get own key details |
| `/users/api-keys/{key_id}` | PUT | Update own key |
| `/users/api-keys/{key_id}` | DELETE | Revoke own key |

### Projects (`/projects`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/projects` | POST | Create project |
| `/projects` | GET | List projects |
| `/projects/{hash}` | GET | Get project details |
| `/projects/{hash}` | PUT | Update project |
| `/projects/{hash}` | DELETE | Delete project |
| `/projects/{hash}/members` | GET | Get project members |
| `/projects/{hash}/groups` | GET | Get project groups |
| `/projects/{hash}/activity` | GET | Get project activity |
| `/projects/{hash}/stats` | GET | Get project statistics |
| `/projects/{hash}/owner` | PATCH | Change project owner (**currently 501**) |
| `/projects/{hash}/archive` | PATCH | Archive/unarchive project (**currently 501**) |

### User Groups (`/admin/user-groups`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/user-groups` | POST | Create user group |
| `/admin/user-groups` | GET | List user groups |
| `/admin/user-groups/{hash}` | GET | Get group details |
| `/admin/user-groups/{hash}` | PUT | Update group |
| `/admin/user-groups/{hash}` | DELETE | Delete group |
| `/admin/user-groups/{hash}/members` | GET | Get members |
| `/admin/user-groups/{hash}/members` | POST | Add member |
| `/admin/user-groups/{hash}/members/bulk` | POST | Bulk add members |
| `/admin/user-groups/{hash}/members/{user}` | DELETE | Remove member |
| `/admin/user-groups/{hash}/project-groups` | GET | Get project group access |
| `/admin/user-groups/{hash}/project-groups` | POST | Grant project group access |
| `/admin/user-groups/{hash}/project-groups/{pg}` | DELETE | Revoke access |
| `/admin/user-groups/users/{user_hash}/groups` | GET | Get user's groups |

### Project Groups (`/admin/project-groups`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/project-groups` | POST | Create project group |
| `/admin/project-groups` | GET | List project groups |
| `/admin/project-groups/{hash}` | GET | Get group details |
| `/admin/project-groups/{hash}` | PUT | Update group |
| `/admin/project-groups/{hash}` | DELETE | Delete group |
| `/admin/project-groups/{hash}/projects` | GET | Get projects in group |
| `/admin/project-groups/{hash}/projects` | POST | Add project |
| `/admin/project-groups/{hash}/projects/{proj}` | DELETE | Remove project |

### Roles (`/roles`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/roles/roles` | POST | Create role |
| `/roles/roles` | GET | List roles |
| `/roles/roles/{hash}` | GET | Get role details |
| `/roles/roles/{hash}` | PUT | Update role |
| `/roles/roles/{hash}` | DELETE | Delete role |
| `/roles/roles/{hash}/permission-groups` | GET | Get role's permission groups |
| `/roles/roles/{hash}/permission-groups/{pg}` | POST | Add permission group to role |
| `/roles/roles/{hash}/permission-groups/{pg}` | DELETE | Remove permission group from role |
| `/roles/users/me/role` | GET | Get my role |
| `/roles/users/{user_hash}/role` | GET | Get user's role |
| `/roles/users/{user_hash}/role` | PUT | Assign role to user |
| `/roles/users/{user_hash}/role` | DELETE | Remove role from user |
| `/roles/projects/{hash}/catalog/roles` | GET | Get project role catalog |
| `/roles/projects/{hash}/catalog/roles/{role_hash}` | POST | Add role to project catalog |
| `/roles/projects/{hash}/catalog/roles/{role_hash}` | DELETE | Remove from project catalog |

### Permission Groups (`/roles/permission-groups`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/roles/permission-groups` | POST | Create permission group |
| `/roles/permission-groups` | GET | List permission groups |
| `/roles/permission-groups/{hash}` | GET | Get group details |
| `/roles/permission-groups/{hash}` | PUT | Update group |
| `/roles/permission-groups/{hash}` | DELETE | Delete group |
| `/roles/permission-groups/{hash}/permissions` | GET | Get permissions in group |
| `/roles/permission-groups/{hash}/permissions/{p}` | POST | Add permission to group |
| `/roles/permission-groups/{hash}/permissions/{p}` | DELETE | Remove permission from group |

### Permissions (`/roles/permissions` and `/permissions`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/roles/permissions` | POST | Create permission |
| `/roles/permissions` | GET | List all permissions |
| `/roles/permissions/{hash}` | GET | Get permission details |
| `/roles/permissions/{hash}` | PUT | Update permission |
| `/roles/permissions/{hash}` | DELETE | Delete permission |
| `/permissions/users/me/permissions` | GET | Get my permissions |
| `/permissions/users/me/permissions/check/{permission_name}` | GET | Check specific permission |
| `/permissions/users/me/permission-groups` | GET | Get my direct permission groups |
| `/permissions/users/me/permission-sources` | GET | Get permission source breakdown |
| `/permissions/admin/user-groups/{hash}/permission-groups` | GET | Get group's permission groups |
| `/permissions/admin/user-groups/{hash}/permission-groups` | POST | Assign permission group to user group |
| `/permissions/admin/user-groups/{hash}/permission-groups` | POST | Bulk assign permission groups |
| `/permissions/admin/user-groups/{hash}/permission-groups/{pg}` | DELETE | Remove permission group from user group |
| `/permissions/users/{user}/permission-groups` | GET | Get user's direct permission groups |
| `/permissions/users/{user}/permission-groups` | POST | Assign permission group to user |
| `/permissions/users/{user}/permission-groups/{pg}` | DELETE | Remove permission group from user |

### User Type Management (`/user-types`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/user-types/root` | POST | Create root user |
| `/user-types/admin` | POST | Create admin user |
| `/user-types/{user_hash}/info` | GET | Get user type info |
| `/user-types/{user_hash}/type` | PUT | Update user type |
| `/user-types/users/{user_type}` | GET | List users by type |
| `/user-types/stats` | GET | User type statistics |
| `/user-types/admin/{user_hash}/projects` | GET | Get admin's projects |
| `/user-types/admin/{user_hash}/projects` | PUT | Update admin's projects |
| `/user-types/admin/{user_hash}/projects/add` | POST | Add admin to project |
| `/user-types/admin/{user_hash}/projects/{project_id}` | DELETE | Remove admin from project |

### API Keys Admin (`/api-keys`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api-keys` | POST | Create API key (admin) |
| `/api-keys` | GET | List keys (admin scope) |
| `/api-keys/{key_id}` | GET | Get key details |
| `/api-keys/{key_id}` | PUT | Update key |
| `/api-keys/{key_id}` | DELETE | Revoke key |
| `/api-keys/users/{user_hash}` | GET | List user's keys |
| `/api-keys/projects/{project_hash}` | GET | List project's keys |

### System (`/system`)
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/system/info` | GET | No | System information |
| `/system/health` | GET | No | Health check |
| `/system/ping` | GET | No | Simple ping |
| `/system/cache/stats` | GET | Yes | Cache statistics |
| `/system/cache/clear` | POST | Admin | Clear all cache |
| `/system/cache/invalidate/user/{hash}` | POST | Admin | Invalidate user cache |
| `/system/cache/invalidate/project/{id}` | POST | Admin | Invalidate project cache |

### Admin Dashboard (`/admin`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/dashboard/stats` | GET | Dashboard statistics |
| `/admin/activity` | GET | Activity feed |
| `/admin/activity/types` | GET | Activity type list |
| `/admin/activity/{activity_id}` | GET | Activity detail |
| `/admin/health` | GET | Detailed health check |
| `/admin/users/statistics` | GET | User statistics |
| `/admin/projects/statistics` | GET | Project statistics |
| `/admin/system/overview` | GET | System overview |

### Audit Logs (`/admin/audit`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/audit/logs` | GET | Paginated audit logs |
| `/admin/audit/security-events` | GET | Security events |
| `/admin/audit/statistics` | GET | Audit statistics |
| `/admin/audit/export` | POST | Export logs (CSV/JSON) |
| `/admin/users/{user_id}/activity` | GET | User activity timeline |

### Bulk Operations (`/admin`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/users/bulk-update` | POST | Bulk update users |
| `/admin/users/bulk-delete` | POST | Bulk delete users |
| `/admin/projects/{hash}/bulk-assign-roles` | POST | Bulk assign roles |
| `/admin/user-groups/bulk-assign` | POST | Bulk assign to groups |

## 💡 API Usage

### Auth Token Contract

This release uses a **two-token model**:

- `access_token`: short-lived JWT used for protected API requests, `/auth/validate`, `/auth/logout`, and `/auth/switch-project`.
- `refresh_token`: 72-hour sliding JWT used **only** for `/auth/refresh`; it is returned in the JSON body and as an HttpOnly Secure `refresh_token` cookie.
- `session_token`: deprecated compatibility alias for `access_token` in response bodies and the access cookie.

`POST /auth/refresh` rejects legacy access/session tokens immediately. Do not send `Authorization: Bearer <access_token>` to refresh; send the refresh token through the `refresh_token` cookie or explicit `refresh_token` form/body field.

Access JWT signature, `exp`, `type`, `jti`, `session_id`, `family_id`, and server-side Redis session/family state are all enforced before a request is trusted.

### Authentication
```bash
# Login (requires a project_hash context)
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=john_doe&password=SecurePass123!&project_hash=proj-xxxx"

# Platform login for root/admin (no project required)
curl -X POST "http://localhost:8000/auth/platform/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=admin_user&password=SecurePass123!"

# Use the access_token/session_token alias for authenticated requests
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "User-Agent: my-client/1.0"

# Refresh with the refresh token only; Authorization Bearer is not refresh transport
curl -X POST "http://localhost:8000/auth/refresh" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "refresh_token=YOUR_REFRESH_TOKEN"
```

### Request Format
- Most endpoints use **Form data** (`application/x-www-form-urlencoded`)
- Bulk operations use **JSON** (`application/json`)

### Response Format
```json
{
  "success": true,
  "message": "Operation completed successfully",
  "data": { ... }
}
```

## 📚 Documentation

### Usage Guides
| Document | Description |
|----------|-------------|
| [Getting Started](docs/USAGE/getting-started.md) | Installation, env vars, first run |
| [Authentication](docs/USAGE/authentication-usage-cases.md) | Login, sessions, project switching |
| [Users](docs/USAGE/users/README.md) | Profile, admin operations, bulk ops |
| [Groups](docs/USAGE/groups/README.md) | User groups, project groups, flows, troubleshooting |
| [Projects](docs/USAGE/projects/README.md) | Project management suite |
| [Roles](docs/USAGE/roles/README.md) | Role definitions, assignment flows |
| [Permissions](docs/USAGE/permissions/README.md) | Permission groups, RBAC resolution |
| [Audit Logs](docs/USAGE/audit_logs/README.md) | Audit trail, security events, export |
| [Admin](docs/USAGE/admin-usage-cases.md) | Dashboard, bulk ops, cache |
| [Error Reference](docs/USAGE/errors.md) | Error codes and troubleshooting |

### Schema
- [Database Schema](schemas/README.md)

## 🐳 Docker Deployment

```bash
docker-compose up -d
```

```yaml
services:
  api-auth:
    environment:
      - DB_HOST=192.168.1.90
      - DB_USER=your_mysql_user
      - DB_MYSQL_PASSWORD=secure_password
      - DB_NAME=magic-auth
      - JWT_SECRET_KEY=your_jwt_secret
      - API_KEY_PEPPER=your_api_key_pepper_secret
      - DB_REDIS_PASSWORD=secure_password
```

## 🔧 Configuration

```bash
# Database (MySQL)
DB_HOST=192.168.1.90
DB_PORT=3306                    # optional, default: 3306
DB_USER=your_mysql_user         # required
DB_MYSQL_PASSWORD=your_password # required
DB_NAME=magic-auth              # required

# JWT
JWT_SECRET_KEY=your_secure_jwt_secret_key   # required outside explicit tests; missing value fails startup/auth initialization
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15          # access token TTL; refresh family remains 72h sliding

# Redis
REDIS_HOST=192.168.1.90
REDIS_PORT=6379                 # optional, default: 6379
REDIS_DB=0                      # optional, default: 0
DB_REDIS_PASSWORD=your_password # optional

# API Keys
API_KEY_PEPPER=your_pepper_secret  # required for /api-keys and /users/api-keys

# CORS
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173,http://localhost:4173,https://auth-ui.arz.ai  # optional, comma-separated
```

## 📊 Performance

- **Concurrent Users**: 1000+ simultaneous sessions
- **Response Time**: <50ms for authentication operations
- **Cache Hit Rate**: >95% with Redis optimization
- **Projects**: Unlimited with group-based access

## 🆘 Troubleshooting

| Problem | Solution |
|---------|----------|
| Access token expired | Call `/auth/refresh` with the refresh token; if refresh fails, re-authenticate via `/auth/login` |
| Legacy client cannot refresh | Update client to store/use `refresh_token`; old access/session tokens are not refresh credentials |
| Missing JWT secret | Set `JWT_SECRET_KEY`; non-test runtime fails fast without it |
| Access denied | Check user group membership and project group access |
| Permission denied | Verify permission groups assigned to user/group |
| Database errors | Verify MySQL connection and schema |
| Cache issues | Use `/system/cache/clear` to reset |
| API key errors | Verify `API_KEY_PEPPER` env var is set |

## 🚚 Migration and Rollback Notes

This is a breaking auth-contract deployment:

- Old access/session tokens cannot be used on `/auth/refresh` and may require users to log in again.
- Deployments MUST set `JWT_SECRET_KEY`; there is no non-test random fallback.
- New Redis namespaces include `session:{access_jti}`, `session_full:{access_jti}`, `refresh_family:{family_id}`, `refresh_token:{refresh_jti}`, `refresh_used:{family_id}`, `revoked_family:{family_id}`, `user_sessions:{user_id}`, and `user_refresh_families:{user_id}`.
- Rollback means redeploying the previous release. If needed, clear or let expire the new refresh-family Redis namespaces; tokens issued by this true-refresh release are not compatible with the older session-rotation contract.
- Do not re-enable legacy access-token refresh silently unless a separate approved spec changes the auth contract.

### Quick Diagnostics
```bash
# Test system
curl http://localhost:8000/system/health

# Test database
python -c "from src.Util.db import get_connection; print('✓ DB Connected')"

# Test Redis
python -c "from src.Util.db_config import redis_client; redis_client.ping(); print('✓ Redis OK')"
```

## 👨‍💻 Author

**Andrés**
- Website: https://arizmendi.io
- Email: andres@arz.ai

---

**🚀 Ready to start?** Check the [Usage Documentation](docs/USAGE/README.md) for complete guides and examples.
