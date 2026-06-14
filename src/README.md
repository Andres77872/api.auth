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
- Two-token JWT model with short-lived access tokens, 72-hour sliding refresh families by default, and 30-day absolute remembered refresh families
- Dual access-token authentication (Bearer access token + secure `session_token` access cookie)
- Refresh-token transport through HttpOnly Secure `refresh_token` cookie or explicit `refresh_token` body/form field
- Multi-project login and project switching
- Consumer-only Google OAuth/OIDC under `/auth/google/*`; provider-init redemption keeps strict project/group bindings server-side and callback success reuses the existing local `LoginResponse`
- Platform login for root/admin users and platform refresh through `/auth/refresh`
- Session validation, strict single-use refresh rotation, logout, switch-project, and deactivation revocation
- Self-service password recovery (`/auth/password/forgot`, `/auth/password/reset`, `/auth/password/change`)
- Email verification/activation (`/auth/email/verify`) and API-key validation (`POST /auth/validate-api-key`, `X-API-Key` header)

### 👥 Hierarchical Group Management
- **User Groups**: Organize users globally, control project access
- **Project Groups**: Container for related projects
- **Permission Groups**: Reusable permission templates

### 🎭 Global Role & Permission System
- **Global Roles**: One role per user with permission groups
- **Permission Groups**: Reusable bundles assignable to users/groups
- **Permissions**: Granular individual permissions
- Real-time permission validation with caching

### 🔑 API Keys
- Self-service API keys (`/users/api-keys`) and admin-scoped key management (`/api-keys`)
- One-time secret reveal (`sk_{public_id}.{secret}`), HMAC-SHA-256 verification, step-up re-auth on mutations
- API-key validation via `POST /auth/validate-api-key` (`X-API-Key` header)

### 📧 Email & Notifications
- Per-user multi-email management with primary-email selection (`/users/me/emails/*`)
- ROOT-only transactional templates with preview, send-test, and rollback (`/admin/email-templates`)
- Outbox-worker delivery, inbound provider webhook (`/webhooks/email/resend`), and delivery logs (`/admin/email/logs`)

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
| [🔵 Google OAuth/OIDC](/documentation/USAGE/google-oauth/README.md) | Provider-init, request flow, rollout, troubleshooting, error/activity/audit contracts |
| [👤 Users](/documentation/USAGE/users/README.md) | Profile management, admin operations, [multi-email management](/documentation/USAGE/users/email-management.md) |
| [👥 Groups](/documentation/USAGE/groups/README.md) | User groups, project groups, flows, troubleshooting |
| [📁 Projects](/documentation/USAGE/projects/README.md) | Project management suite, access control |
| [🔑 Permissions](/documentation/USAGE/permissions/README.md) | Roles, permission groups, assignments |
| [🗝️ API Keys](/documentation/USAGE/api-keys/README.md) | Self-service and admin API-key management |
| [📧 Email](/documentation/USAGE/email/README.md) | Templates, delivery/outbox, provider webhook |
| [📝 Audit Logs](/documentation/USAGE/audit_logs/README.md) | Audit trail, security events, email logs, export |
| [⚙️ Admin](/documentation/USAGE/admin-usage-cases.md) | Dashboard, bulk operations, cache management |

**For LLM/API consumption**: Add `?format=raw` to any URL to get plain markdown.

## 📡 API Endpoints Overview

**167 endpoints across 17 route modules.** A `User-Agent` header is required on every request.

### Authentication (`/auth`) - 13 endpoints
- `POST /auth/login` - User login (requires `project_hash`; optional `remember_me`)
- `POST /auth/platform/login` - Root/admin platform login without project binding; refreshable through `/auth/refresh`
- `POST /auth/register` - New user registration
- `GET /auth/validate` - Validate access token only
- `POST /auth/validate-api-key` - Validate an API key via the `X-API-Key` header
- `POST /auth/logout` - End session and revoke refresh continuity
- `POST /auth/refresh` - Rotate using refresh token only; access/session tokens are rejected
- `POST /auth/switch-project` - Switch project context and rotate access+refresh credentials
- `POST /auth/check-availability` - Check username/email
- `POST /auth/email/verify` - Verify/activate an email address from a token
- `POST /auth/password/forgot` - Request a password-reset link (generic 202)
- `POST /auth/password/reset` - Reset password from a recovery token
- `POST /auth/password/change` - Change the authenticated user's password

### Google OAuth (`/auth/google`) - 6 endpoints
- `POST /auth/google/start` - Google OAuth start using only an opaque `provider_init_token`
- `GET /auth/google/callback` - Google OAuth callback; validates ID token then reuses local session issuance
- `POST /auth/google/link/start` - Start Google external-account linking for an authenticated consumer with recent reauth
- `POST /auth/google/link/finish` - Finish Google external-account linking without returning Google tokens
- `POST /auth/google/reauth/start` - Start Google recent-reauth/step-up flow
- `DELETE /auth/google/unlink` - Soft-unlink Google only when fallback auth exists

### Users (`/users`) - 18 endpoints
- `GET /users/profile` - Get current user profile
- `PUT /users/profile` - Update profile
- `GET /users/access-summary` - Hierarchical access summary
- `GET /users/list` - List users (admin)
- `GET /users/me/emails` - List own emails
- `POST /users/me/emails` - Add an email to own account (generic 202)
- `POST /users/me/emails/{email_id}/resend` - Resend own email activation (cooldown)
- `DELETE /users/me/emails/{email_id}` - Remove own email (revokes sessions)
- `POST /users/me/emails/{email_id}/primary` - Set own primary email
- `GET /users/{user_hash}/emails` - List a user's emails (admin, masked)
- `POST /users/{user_hash}/emails/{email_id}/resend` - Resend a user's email activation (admin)
- `GET /users/{user_hash}` - Get user details
- `PUT /users/{user_hash}` - Update user details (admin/root)
- `PUT /users/{user_hash}/status` - Update status
- `PATCH /users/{user_hash}/type` - Change user type (root only)
- `POST /users/{user_hash}/reset-password` - Queue a hash-only admin password-reset link (no temp password/token/URL)
- `DELETE /users/{user_hash}` - Delete user
- `GET /users/search/query` - Search users (admin)

### User Types (`/user-types`) - 10 endpoints
- `POST /user-types/root` - Create root user
- `POST /user-types/admin` - Create admin user
- `GET /user-types/{user_hash}/info` - Get user type info
- `PUT /user-types/{user_hash}/type` - Update user type
- `GET /user-types/users/{user_type}` - List users by type
- `GET /user-types/stats` - User type statistics
- `GET /user-types/admin/{user_hash}/projects` - Get admin's projects
- `PUT /user-types/admin/{user_hash}/projects` - Update admin's projects
- `POST /user-types/admin/{user_hash}/projects/add` - Add admin to project
- `DELETE /user-types/admin/{user_hash}/projects/{project_id}` - Remove admin from project

### API Keys - 12 endpoints (self-service + admin)
- `POST /users/api-keys` - Create own API key (one-time secret reveal)
- `GET /users/api-keys` - List own API keys
- `GET /users/api-keys/{key_id}` - Get own key details
- `PUT /users/api-keys/{key_id}` - Update own key
- `DELETE /users/api-keys/{key_id}` - Revoke own key
- `POST /api-keys` - Create API key (admin)
- `GET /api-keys` - List keys (admin scope; root must filter)
- `GET /api-keys/{key_id}` - Get key details (admin)
- `PUT /api-keys/{key_id}` - Update key (admin)
- `DELETE /api-keys/{key_id}` - Revoke key (admin)
- `GET /api-keys/users/{user_hash}` - List a user's keys (admin)
- `GET /api-keys/projects/{project_hash}` - List a project's keys (admin)

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

### User Groups (`/admin/user-groups`) - 13 endpoints
- `POST /admin/user-groups` - Create group
- `GET /admin/user-groups` - List groups
- `GET /admin/user-groups/{hash}` - Get details
- `PUT /admin/user-groups/{hash}` - Update group
- `DELETE /admin/user-groups/{hash}` - Delete group
- `GET /admin/user-groups/{hash}/members` - Get members
- `POST /admin/user-groups/{hash}/members` - Add member
- `POST /admin/user-groups/{hash}/members/bulk` - Bulk add (JSON body)
- `DELETE /admin/user-groups/{hash}/members/{user}` - Remove member
- `GET /admin/user-groups/{hash}/project-groups` - Get project access
- `POST /admin/user-groups/{hash}/project-groups` - Grant access
- `DELETE /admin/user-groups/{hash}/project-groups/{project_group_hash}` - Revoke access
- `GET /admin/user-groups/users/{user_hash}/groups` - Reverse lookup: a user's groups

### Project Groups (`/admin/project-groups`) - 7 endpoints
- `POST /admin/project-groups` - Create group
- `GET /admin/project-groups` - List groups
- `GET /admin/project-groups/{hash}` - Get details (includes `assigned_projects`)
- `PUT /admin/project-groups/{hash}` - Update group
- `DELETE /admin/project-groups/{hash}` - Delete group
- `POST /admin/project-groups/{hash}/projects` - Add project
- `DELETE /admin/project-groups/{hash}/projects/{proj}` - Remove project

### Roles (`/roles`) - 28 endpoints (roles, permission-groups, permissions, role assignment, project catalog)
- `POST /roles/roles` - Create role
- `GET /roles/roles` - List roles
- `GET /roles/roles/{hash}` - Get details
- `PUT /roles/roles/{hash}` - Update role
- `DELETE /roles/roles/{hash}` - Delete role
- `POST /roles/roles/{hash}/permission-groups/{pg}` - Add permission group to role
- `GET /roles/roles/{hash}/permission-groups` - List role's permission groups
- `DELETE /roles/roles/{hash}/permission-groups/{pg}` - Remove permission group from role
- `GET /roles/users/me/role` - Get my role
- `GET /roles/users/{user_hash}/role` - Get user's role
- `PUT /roles/users/{user_hash}/role` - Assign role to user
- `DELETE /roles/users/{user_hash}/role` - Remove role from user
- `POST /roles/projects/{hash}/catalog/roles/{role_hash}` - Add role to project catalog
- `GET /roles/projects/{hash}/catalog/roles` - List project role catalog
- `DELETE /roles/projects/{hash}/catalog/roles/{role_hash}` - Remove role from project catalog
- Permission-group CRUD: `POST|GET /roles/permission-groups`, `GET|PUT|DELETE /roles/permission-groups/{hash}`, plus `POST|GET|DELETE /roles/permission-groups/{hash}/permissions[/{p}]`
- Permission CRUD: `POST|GET /roles/permissions`, `GET|PUT|DELETE /roles/permissions/{hash}`

### Permission Assignments (`/permissions`) - 17 endpoints
- `POST /permissions/admin/user-groups/{hash}/permission-groups` - Assign permission group to user group
- `GET /permissions/admin/user-groups/{hash}/permission-groups` - Get group's permission groups
- `DELETE /permissions/admin/user-groups/{hash}/permission-groups/{pg}` - Remove from user group
- `POST /permissions/admin/user-groups/{hash}/permission-groups/bulk` - Bulk assign (JSON body)
- `POST /permissions/users/{user}/permission-groups` - Assign permission group to user
- `GET /permissions/users/{user}/permission-groups` - Get user's direct permission groups
- `DELETE /permissions/users/{user}/permission-groups/{pg}` - Remove from user
- `GET /permissions/users/me/permissions` - Get my permissions
- `GET /permissions/users/me/permissions/check/{permission_name}` - Check a specific permission
- `GET /permissions/users/me/permission-groups` - My direct permission groups
- `GET /permissions/users/me/permission-sources` - Permission source breakdown
- `POST /permissions/projects/{hash}/permission-group-catalog/{pg}` - Add to project catalog
- `DELETE /permissions/projects/{hash}/permission-group-catalog/{pg}` - Remove from project catalog
- `GET /permissions/projects/{hash}/permission-group-catalog` - List project catalog
- `GET /permissions/permissions/groups/{pg}/project-catalog` - Projects catalog-listing a group
- `GET /permissions/permissions/groups/{pg}/user-groups` - User groups assigned a group
- `GET /permissions/permissions/groups/{pg}/users` - Users assigned a group

### System (`/system`) - 7 endpoints
- `GET /system/info` - System info (public)
- `GET /system/health` - Health check (public)
- `GET /system/ping` - Simple ping (public)
- `GET /system/cache/stats` - Cache stats
- `POST /system/cache/clear` - Clear cache (admin)
- `POST /system/cache/invalidate/user/{hash}` - Invalidate user
- `POST /system/cache/invalidate/project/{id}` - Invalidate project

### Admin Dashboard (`/admin`) - 8 endpoints
- `GET /admin/dashboard/stats` - Dashboard statistics
- `GET /admin/activity` - Activity feed
- `GET /admin/activity/types` - Activity types
- `GET /admin/activity/{activity_id}` - Activity detail
- `GET /admin/health` - Detailed health
- `GET /admin/users/statistics` - User statistics
- `GET /admin/projects/statistics` - Project statistics
- `GET /admin/system/overview` - System overview

### Audit Logs (`/admin/audit/*` and `/admin/email/logs`) - 6 endpoints
- `GET /admin/audit/logs` - Paginated audit logs
- `GET /admin/audit/security-events` - Security events
- `GET /admin/audit/statistics` - Audit statistics
- `POST /admin/audit/export` - Export logs CSV/JSON (JSON body)
- `GET /admin/email/logs` - Email delivery logs (redacted)
- `GET /admin/users/{user_id}/activity` - User activity timeline

### Email Templates (`/admin/email-templates`) - 6 endpoints (ROOT-only, JSON bodies)
- `GET /admin/email-templates` - List transactional templates
- `GET /admin/email-templates/{template_code}` - Get a template
- `PUT /admin/email-templates/{template_code}` - Update a template (versioned)
- `POST /admin/email-templates/{template_code}/preview` - Render a preview
- `POST /admin/email-templates/{template_code}/send-test` - Send a test to the caller's own activated email
- `POST /admin/email-templates/{template_code}/rollback` - Roll back to a prior version

### Email Webhooks (`/webhooks/email`) - 1 endpoint
- `POST /webhooks/email/resend` - Inbound provider webhook (Svix-signed raw body, no app auth, always 204)

### Bulk Operations (`/admin`) - 4 endpoints
- `POST /admin/users/bulk-update` - Bulk update users
- `POST /admin/users/bulk-delete` - Bulk delete users
- `POST /admin/projects/{hash}/bulk-assign-roles` - Bulk assign roles
- `POST /admin/user-groups/bulk-assign` - Bulk assign groups

## 🔑 Key Features

### Request Format
- Almost all `POST`/`PUT`/`PATCH` endpoints take **multipart form data** (`multipart/form-data`, FastAPI `Form(...)` fields).
- JSON-body exceptions (`application/json`): `POST /admin/user-groups/{hash}/members/bulk`, `POST /permissions/admin/user-groups/{hash}/permission-groups/bulk`, `POST /admin/audit/export`, Google OAuth `POST /auth/google/start` and `POST /auth/google/link/finish`, and all `/admin/email-templates` mutations (`PUT`, `/preview`, `/send-test`, `/rollback`).
- `POST /webhooks/email/resend` consumes a raw, Svix-signed body (no app Content-Type contract).
- A **`User-Agent` header is required on every request** (a missing `User-Agent` returns `422`).
- Responses are JSON with Pydantic validation.

### Auth Token Contract
- **Access token**: short-lived JWT used for protected routes, `/auth/validate`, `/auth/logout`, and `/auth/switch-project`.
- **Refresh token**: 72-hour sliding JWT by default, or a 30-day absolute JWT when `remember_me=true`; used only for `/auth/refresh` and returned in the JSON body and as HttpOnly Secure `refresh_token` cookie.
- **`session_token`**: deprecated alias for the access token in response bodies and access cookie.
- **Refresh transport**: `refresh_token` cookie or explicit `refresh_token` body/form field. `Authorization: Bearer <access_token>` is not accepted by `/auth/refresh`.
- **JWT authority**: request paths enforce signature, `exp`, `type`, `jti`, `session_id`, `family_id`, and Redis session/family state.

### Google OAuth Implementation Contracts

- Browser start requests send only `provider_init_token`; raw `project_hash` and `user_group_hash` remain server-side between `magic-worlds-api` and `api.auth`.
- Google OAuth requests `scope=openid email` only and must not persist Google access token, refresh token, or id token material.
- `/auth/google/start` and `/auth/google/callback` are unauthenticated public OAuth surfaces for AuthContext extraction, but API audit remains active with `auth_method='oauth'`.
- OAuth activity uses `act-cat-064..074`; OAuth provider/protocol errors use `EXT_8xxx` values.
- See [Google OAuth docs](/documentation/USAGE/google-oauth/README.md), [reference](/documentation/USAGE/google-oauth/reference.md), and [runbook](/documentation/RUNBOOKS/google-oauth.md).

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

**Version**: 2.2.0 | **Total Endpoints**: 167 across 17 route modules | **Last Updated**: June 2026

This authentication system is free and open for everyone!

**[Support on Patreon](https://patreon.com/findit_moe)** 🙏
