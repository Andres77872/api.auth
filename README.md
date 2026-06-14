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
- 72-hour sliding refresh-token families by default, or 30-day absolute refresh families when `remember_me=true`
- HttpOnly Secure cookies for both `session_token` (access alias) and `refresh_token`
- Multi-project login and project switching
- Consumer-only Google OAuth/OIDC login through opaque provider-init tokens; see [Google OAuth docs](docs/USAGE/google-oauth/README.md)
- Platform-scoped login for root/admin users
- Session validation, strict refresh rotation, logout, and deactivation revocation
- Username/email availability checking
- Self-service password recovery (`/auth/password/forgot`, `/auth/password/reset`, `/auth/password/change`)
- Email verification/activation (`/auth/email/verify`) and per-user multi-email management
- API-key validation endpoint (`POST /auth/validate-api-key`, `X-API-Key` header)

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
- User-scoped API keys for programmatic access (`/users/api-keys`)
- Admin-scoped key management (create, revoke, inspect) (`/api-keys`)
- Per-project and per-user key listing
- One-time secret reveal (`sk_{public_id}.{secret}`), HMAC-SHA-256 verification, step-up re-auth on mutations
- API-key validation via `POST /auth/validate-api-key` (`X-API-Key` header)

### 📧 Email & Notifications
- Per-user multi-email management with primary-email selection (`/users/me/emails/*`)
- Email verification/activation and password-recovery delivery
- ROOT-only transactional email templates with preview, send-test, and rollback (`/admin/email-templates`)
- Outbox-worker delivery model and inbound provider webhook (`/webhooks/email/resend`)
- Email delivery logs in the audit surface (`/admin/email/logs`)

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

The API exposes **167 endpoints across 17 route modules** (API version `2.2.0`).

### Authentication (`/auth`) — 13 endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/login` | POST | User login (requires `project_hash`; optional `remember_me`) |
| `/auth/platform/login` | POST | Platform-scoped login for root/admin (no project required) |
| `/auth/register` | POST | New user registration |
| `/auth/validate` | GET | Validate an access token only |
| `/auth/validate-api-key` | POST | Validate an API key via the `X-API-Key` header |
| `/auth/logout` | POST | End session and revoke refresh continuity |
| `/auth/refresh` | POST | Rotate with a refresh token only |
| `/auth/switch-project` | POST | Switch project context and rotate access+refresh tokens |
| `/auth/check-availability` | POST | Check username/email availability |
| `/auth/email/verify` | POST | Verify/activate an email address from a token |
| `/auth/password/forgot` | POST | Request a password-reset link (generic 202) |
| `/auth/password/reset` | POST | Reset password from a recovery token |
| `/auth/password/change` | POST | Change the authenticated user's password |

### Google OAuth (`/auth/google`) — 6 endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/google/start` | POST | Consumer Google OAuth start via opaque `provider_init_token` |
| `/auth/google/callback` | GET | Google OAuth callback; reuses local `LoginResponse` on success |
| `/auth/google/link/start` | POST | Start Google link flow for an authenticated consumer |
| `/auth/google/link/finish` | POST | Finish Google external-account linking |
| `/auth/google/reauth/start` | POST | Start Google recent-reauth/step-up flow |
| `/auth/google/unlink` | DELETE | Soft-unlink Google when fallback auth exists |

### Users (`/users`) — 18 endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/users/profile` | GET | Get current user profile |
| `/users/profile` | PUT | Update current user profile |
| `/users/access-summary` | GET | Get hierarchical access summary |
| `/users/list` | GET | List users with filters (admin) |
| `/users/me/emails` | GET | List own emails |
| `/users/me/emails` | POST | Add an email to own account (generic 202) |
| `/users/me/emails/{email_id}/resend` | POST | Resend activation for own email (cooldown) |
| `/users/me/emails/{email_id}` | DELETE | Remove own email (revokes sessions) |
| `/users/me/emails/{email_id}/primary` | POST | Set own primary email |
| `/users/{user_hash}/emails` | GET | List a user's emails (admin, masked) |
| `/users/{user_hash}/emails/{email_id}/resend` | POST | Resend a user's email activation (admin) |
| `/users/{user_hash}` | GET | Get user details |
| `/users/{user_hash}` | PUT | Update user details (admin/root) |
| `/users/{user_hash}/status` | PUT | Update user status |
| `/users/{user_hash}/type` | PATCH | Change user type (root only) |
| `/users/{user_hash}/reset-password` | POST | Queue a hash-only admin password-reset link (no temp password/token/URL) |
| `/users/{user_hash}` | DELETE | Delete user (admin) |
| `/users/search/query` | GET | Search users (admin) |

### User API Keys (`/users/api-keys`) — 5 endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/users/api-keys` | POST | Create own API key (one-time secret reveal) |
| `/users/api-keys` | GET | List own API keys |
| `/users/api-keys/{key_id}` | GET | Get own key details |
| `/users/api-keys/{key_id}` | PUT | Update own key |
| `/users/api-keys/{key_id}` | DELETE | Revoke own key |

### Projects (`/projects`) — 11 endpoints
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

### User Groups (`/admin/user-groups`) — 13 endpoints
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

### Project Groups (`/admin/project-groups`) — 7 endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/project-groups` | POST | Create project group |
| `/admin/project-groups` | GET | List project groups |
| `/admin/project-groups/{hash}` | GET | Get group details (includes `assigned_projects`) |
| `/admin/project-groups/{hash}` | PUT | Update group |
| `/admin/project-groups/{hash}` | DELETE | Delete group |
| `/admin/project-groups/{hash}/projects` | POST | Add project |
| `/admin/project-groups/{hash}/projects/{proj}` | DELETE | Remove project |

### Roles (`/roles`) — 28 endpoints total (roles + permission-groups + permissions, below)
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

### Permission Groups (`/roles/permission-groups`) — part of the 28 `/roles` endpoints
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

### Permission Definitions (`/roles/permissions`) — part of the 28 `/roles` endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/roles/permissions` | POST | Create permission |
| `/roles/permissions` | GET | List all permissions |
| `/roles/permissions/{hash}` | GET | Get permission details |
| `/roles/permissions/{hash}` | PUT | Update permission |
| `/roles/permissions/{hash}` | DELETE | Delete permission |

### Permission Assignments (`/permissions`) — 17 endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/permissions/admin/user-groups/{hash}/permission-groups` | POST | Assign permission group to user group |
| `/permissions/admin/user-groups/{hash}/permission-groups` | GET | Get group's permission groups |
| `/permissions/admin/user-groups/{hash}/permission-groups/{pg}` | DELETE | Remove permission group from user group |
| `/permissions/admin/user-groups/{hash}/permission-groups/bulk` | POST | Bulk assign permission groups (JSON body) |
| `/permissions/users/{user}/permission-groups` | POST | Assign permission group to user |
| `/permissions/users/{user}/permission-groups` | GET | Get user's direct permission groups |
| `/permissions/users/{user}/permission-groups/{pg}` | DELETE | Remove permission group from user |
| `/permissions/users/me/permissions` | GET | Get my permissions |
| `/permissions/users/me/permissions/check/{permission_name}` | GET | Check a specific permission |
| `/permissions/users/me/permission-groups` | GET | Get my direct permission groups |
| `/permissions/users/me/permission-sources` | GET | Get permission source breakdown |
| `/permissions/projects/{hash}/permission-group-catalog/{pg}` | POST | Add permission group to project catalog |
| `/permissions/projects/{hash}/permission-group-catalog/{pg}` | DELETE | Remove from project catalog |
| `/permissions/projects/{hash}/permission-group-catalog` | GET | List project permission-group catalog |
| `/permissions/permissions/groups/{pg}/project-catalog` | GET | Projects catalog-listing a permission group |
| `/permissions/permissions/groups/{pg}/user-groups` | GET | User groups assigned a permission group |
| `/permissions/permissions/groups/{pg}/users` | GET | Users assigned a permission group |

### User Type Management (`/user-types`) — 10 endpoints
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

### API Keys Admin (`/api-keys`) — 7 endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api-keys` | POST | Create API key (admin) |
| `/api-keys` | GET | List keys (admin scope) |
| `/api-keys/{key_id}` | GET | Get key details |
| `/api-keys/{key_id}` | PUT | Update key |
| `/api-keys/{key_id}` | DELETE | Revoke key |
| `/api-keys/users/{user_hash}` | GET | List user's keys |
| `/api-keys/projects/{project_hash}` | GET | List project's keys |

### Email Templates (`/admin/email-templates`) — 6 endpoints (ROOT-only, JSON bodies)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/email-templates` | GET | List transactional templates |
| `/admin/email-templates/{template_code}` | GET | Get a template |
| `/admin/email-templates/{template_code}` | PUT | Update a template (versioned) |
| `/admin/email-templates/{template_code}/preview` | POST | Render a preview |
| `/admin/email-templates/{template_code}/send-test` | POST | Send a test to the caller's own activated email |
| `/admin/email-templates/{template_code}/rollback` | POST | Roll a template back to a prior version |

### Email Webhooks (`/webhooks/email`) — 1 endpoint
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/webhooks/email/resend` | POST | Inbound provider webhook (Svix-signed raw body, no app auth, always 204) |

### System (`/system`) — 7 endpoints
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/system/info` | GET | No | System information |
| `/system/health` | GET | No | Health check |
| `/system/ping` | GET | No | Simple ping |
| `/system/cache/stats` | GET | Yes | Cache statistics |
| `/system/cache/clear` | POST | Admin | Clear all cache |
| `/system/cache/invalidate/user/{hash}` | POST | Admin | Invalidate user cache |
| `/system/cache/invalidate/project/{id}` | POST | Admin | Invalidate project cache |

### Admin Dashboard (`/admin`) — 8 endpoints
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

### Audit Logs (`/admin/audit/*` and `/admin/email/logs`) — 6 endpoints
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/audit/logs` | GET | Paginated audit logs |
| `/admin/audit/security-events` | GET | Security events |
| `/admin/audit/statistics` | GET | Audit statistics |
| `/admin/audit/export` | POST | Export logs (CSV/JSON; JSON body) |
| `/admin/email/logs` | GET | Email delivery logs (redacted) |
| `/admin/users/{user_id}/activity` | GET | User activity timeline |

### Bulk Operations (`/admin`) — 4 endpoints
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
- `refresh_token`: 72-hour sliding JWT by default, or a 30-day absolute JWT when `remember_me=true`; it is used **only** for `/auth/refresh` and returned in the JSON body and as an HttpOnly Secure `refresh_token` cookie.
- `session_token`: deprecated compatibility alias for `access_token` in response bodies and the access cookie.

`POST /auth/refresh` rejects legacy access/session tokens immediately. Do not send `Authorization: Bearer <access_token>` to refresh; send the refresh token through the `refresh_token` cookie or explicit `refresh_token` form/body field.

Access JWT signature, `exp`, `type`, `jti`, `session_id`, `family_id`, and server-side Redis session/family state are all enforced before a request is trusted.

### Authentication
```bash
# Login (requires a project_hash context; optional remember_me)
curl -X POST "http://localhost:8000/auth/login" \
  -H "User-Agent: my-client/1.0" \
  -F "username=john_doe" -F "password=SecurePass123!" -F "project_hash=proj-xxxx"

# Platform login for root/admin (no project required)
curl -X POST "http://localhost:8000/auth/platform/login" \
  -H "User-Agent: my-client/1.0" \
  -F "username=admin_user" -F "password=SecurePass123!"

# Use the access_token/session_token alias for authenticated requests
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "User-Agent: my-client/1.0"

# Refresh with the refresh token only; Authorization Bearer is not refresh transport
curl -X POST "http://localhost:8000/auth/refresh" \
  -H "User-Agent: my-client/1.0" \
  -F "refresh_token=YOUR_REFRESH_TOKEN"

# Validate an API key (X-API-Key header; do not also send Authorization)
curl -X POST "http://localhost:8000/auth/validate-api-key" \
  -H "User-Agent: my-client/1.0" \
  -H "X-API-Key: sk_PUBLIC.SECRET"
```

### Request Format
- Almost all `POST`/`PUT`/`PATCH` endpoints take **multipart form data** (`multipart/form-data`, FastAPI `Form(...)` fields).
- A few endpoints take a **JSON** body (`application/json`): `POST /admin/user-groups/{hash}/members/bulk`, `POST /permissions/admin/user-groups/{hash}/permission-groups/bulk`, `POST /admin/audit/export`, the Google OAuth `POST /auth/google/start` and `POST /auth/google/link/finish`, and all `/admin/email-templates` mutations (`PUT`, `/preview`, `/send-test`, `/rollback`).
- `POST /webhooks/email/resend` consumes a raw, Svix-signed request body (no app Content-Type contract).
- A **`User-Agent` header is required on every request** (a missing `User-Agent` returns `422`).
- Responses are JSON with Pydantic validation.

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
| [Google OAuth/OIDC](docs/USAGE/google-oauth/README.md) | Provider-init, scope, request flow, scenarios, troubleshooting, reference |
| [Users](docs/USAGE/users/README.md) | Profile, admin operations, bulk ops, [multi-email management](docs/USAGE/users/email-management.md) |
| [Groups](docs/USAGE/groups/README.md) | User groups, project groups, flows, troubleshooting |
| [Projects](docs/USAGE/projects/README.md) | Project management suite |
| [Roles](docs/USAGE/roles/README.md) | Role definitions, assignment flows |
| [Permissions](docs/USAGE/permissions/README.md) | Permission groups, RBAC resolution |
| [API Keys](docs/USAGE/api-keys/README.md) | Self-service and admin API-key management |
| [Email](docs/USAGE/email/README.md) | Templates, delivery/outbox, provider webhook |
| [Audit Logs](docs/USAGE/audit_logs/README.md) | Audit trail, security events, email logs, export |
| [Admin](docs/USAGE/admin-usage-cases.md) | Dashboard, bulk ops, cache |
| [Error Reference](docs/USAGE/errors.md) | Error codes and troubleshooting |

### Schema
- [Database Schema](schemas/docs/README.md)
- [External Accounts Schema](schemas/docs/external-accounts.md)

### Runbooks
- [Google OAuth Runbook](docs/RUNBOOKS/google-oauth.md)
- [Email Activation Runbook](docs/RUNBOOKS/email-activation.md)

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

See [.env.example](.env.example) for the full documented environment template,
including test-only, Docker-only, and deprecated variables.

```bash
# Database (MySQL)
DB_HOST=192.168.1.90
DB_PORT=3306                    # optional, default: 3306
DB_USER=your_mysql_user         # required
DB_MYSQL_PASSWORD=your_password # required
DB_NAME=magic-auth              # required

# JWT
JWT_SECRET_KEY=your_secure_jwt_secret_key   # required outside explicit tests; missing value fails startup/auth initialization
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15          # access token TTL; refresh family remains 72h sliding

# Redis
REDIS_HOST=192.168.1.90
REDIS_PORT=6379                 # optional, default: 6379
REDIS_DB=0                      # optional, default: 0
DB_REDIS_PASSWORD=your_password # optional

# API Keys
API_KEY_PEPPER=your_pepper_secret  # required for /api-keys and /users/api-keys

# CORS
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173,http://localhost:4173  # optional, comma-separated; add deployment origins outside docs
```

Google OAuth configuration is documented in [docs/USAGE/google-oauth/reference.md](docs/USAGE/google-oauth/reference.md) and rollout/rollback is in [docs/RUNBOOKS/google-oauth.md](docs/RUNBOOKS/google-oauth.md). Do not place real Google secrets, provider-init bearer credentials, production origins, or raw strict hashes in README examples.

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
