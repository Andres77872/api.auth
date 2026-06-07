# Authentication Usage Guide

Complete practical guide for authentication, session management, and user registration in the authentication system.

> **New here?** Start with [Getting Started](getting-started.md) for platform setup and first-time onboarding.
> For client integration (JS, Python, React), see [Client Authentication Guide](client-authentication-guide.md).
> For error codes and troubleshooting, see [Error Reference](errors.md).

> **Important**: Every request MUST include a `User-Agent` header. Missing it returns `422`. All curl examples below include it.

---

## 📖 Table of Contents

- [Authentication Overview](#authentication-overview)
- [Supported Protected-Route Authentication](#supported-protected-route-authentication)
- [API Key Lifecycle Status](#api-key-lifecycle-status)
- [Login](#login)
- [Registration](#registration)
- [Session Management](#session-management)
- [Project Switching](#project-switching)
- [Common Scenarios](#common-scenarios)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Authentication Overview

The authentication system uses **short-lived access JWTs** plus **72-hour sliding refresh JWT families** with Redis-backed revocation.

### Key Concepts

- **Access Token**: short-lived JWT used for protected requests, `/auth/validate`, `/auth/logout`, and `/auth/switch-project`
- **Refresh Token**: 72-hour sliding JWT used only by `/auth/refresh`; returned in JSON and as HttpOnly Secure `refresh_token` cookie
- **Session Token**: deprecated response/cookie alias for the access token
- **Project Context**: All users (including root) operate within a project context on `/auth/login`
- **Root Users**: Have global access (bypass group-membership validation) but still require `project_hash` on `/auth/login`. Use `/auth/platform/login` for login without project binding.
- **User Groups**: Determine which projects a user can access (root bypasses this validation)

### Authentication Flow

```
1. User submits credentials (username/password)
2. System validates credentials
3. System checks project access (via user groups)
4. Access + refresh JWT pair is generated and server-side Redis state is written by token `jti`/`family_id`
5. HTTP-only cookies are set: `session_token` for access, `refresh_token` for refresh
6. User can access authorized endpoints with the access token and renew through `/auth/refresh` with the refresh token
```

### Supported Protected-Route Authentication

Protected endpoints currently authorize requests through the session auth dependency. The supported protected-route credentials are:

| Mechanism | Transport | Protected-route status | Notes |
|-----------|-----------|------------------------|-------|
| Access JWT | `Authorization: Bearer <access_token>` | Supported | Primary mode for API clients, scripts, mobile apps, and server-to-server callers |
| Access JWT cookie | `session_token=<access_token>` | Supported | Browser/SPA mode; `session_token` is a deprecated name but still carries the access JWT |
| Refresh JWT | `refresh_token` cookie or `refresh_token` body/form field | Not accepted on protected routes | Only `/auth/refresh` accepts refresh tokens |
| API key | `X-API-Key: sk_<public_id>.<secret>` | Not supported yet | Lifecycle and audit context exist, but route authorization still requires an access JWT or `session_token` cookie |

### API Key Lifecycle Status

API keys are lifecycle-supported but are **not currently a replacement for access/session JWTs** on protected routes.

What works today:

- Users can create, list, view, update, and revoke their own keys through `/users/api-keys` endpoints.
- Admin/root users can create, list, view, update, and revoke scoped keys through `/api-keys` endpoints.
- Generated keys use split-token format, server-side hashing, storage, cache validation, expiration, and revocation support.
- Middleware can read `X-API-Key` and populate request/audit context such as `auth_method = "api_key"`.

What does **not** work today:

- Sending only `X-API-Key` to protected endpoints such as `/users/profile` currently returns `401`.
- API-key request/audit context does not satisfy the route-level authorization dependency.
- API-key management endpoints themselves still require Bearer/session JWT authentication.

Known limitation / implementation gap:

The intended future behavior is that an API token generated for a specific user and project can authenticate protected routes as that user. That requires a unified auth dependency and route migration so protected endpoints trust either a valid access/session JWT or a valid API key. Until that is implemented, clients must continue using Bearer access JWTs or the `session_token` cookie for protected-route access.

---

## Login

### Consumer Login (requires project_hash)

**Scenario**: Non-root user logs in with username, password, and project context.

```bash
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=john_doe&password=SecurePass123!&project_hash=proj-xyz789..."
```

**Response:**
```json
{
  "success": true,
  "message": "Login successful",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_expires_in": 259200,
  "user": {
    "user_hash": "usr-abc123...",
    "username": "john_doe",
    "email": "john@example.com",
    "user_type": "consumer"
  },
  "project": {
    "project_hash": "proj-xyz789...",
    "project_name": "Default Project",
    "project_description": "User's default project"
  },
  "accessible_projects": [
    {
      "project_hash": "proj-xyz789...",
      "project_name": "Default Project"
    },
    {
      "project_hash": "proj-abc456...",
      "project_name": "Secondary Project"
    }
  ],
  "user_groups": [
    {
      "group_hash": "grp-dev123...",
      "group_name": "developers",
      "description": "Development team"
    }
  ]
}
```

### Login with Specific Project

**Scenario**: User logs in directly to a specific project.

```bash
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=john_doe&password=SecurePass123!&project_hash=proj-specific123..."
```

### Login with Email

**Scenario**: User logs in using email instead of username. All users must include `project_hash` on `/auth/login`.

```bash
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=john@example.com&password=SecurePass123!&project_hash=proj-xyz789..."
```

### Root User Login

**Scenario**: Root user logs in to a specific project. **Root must provide `project_hash` on `/auth/login`** — the requirement applies to all user types. Root only bypasses group-membership validation, not the `project_hash` requirement.

```bash
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=root_admin&password=RootPass123!&project_hash=proj-xyz789..."
```

**Response:**
```json
{
  "success": true,
  "message": "Root user login successful",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_expires_in": 259200,
  "user": {
    "user_hash": "usr-root123...",
    "username": "root_admin",
    "email": "root@example.com",
    "user_type": "root"
  },
  "project": {
    "project_hash": "proj-xyz789...",
    "project_name": "Default Project",
    "project_description": "Root's target project"
  },
  "accessible_projects": [...],
  "user_groups": []
}
```

> **Alternative endpoint**: Root and admin users can use `/auth/platform/login` which does **NOT** require `project_hash`. This endpoint is restricted to root/admin; consumer users are rejected (403). Platform login returns the same access+refresh token pair and platform refresh works through `/auth/refresh`.

### Platform Login (root/admin, no project_hash)

```bash
curl -X POST "http://localhost:8000/auth/platform/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=root_admin&password=RootPass123!"
```

**Response highlights:**
```json
{
  "success": true,
  "access_token": "...platform access JWT...",
  "refresh_token": "...platform refresh JWT...",
  "session_token": "...same value as access_token...",
  "project": null,
  "accessible_projects": [],
  "user": { "user_type": "root" }
}
```

---

## Registration

### Register New User

**Scenario**: Register a new user with automatic group assignment.

```bash
curl -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=new_user&password=SecurePass123!&email=newuser@example.com&user_group_hash=grp-default123..."
```

**Response:**
```json
{
  "success": true,
  "message": "User registered successfully",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_expires_in": 259200,
  "user": {
    "user_hash": "usr-new456...",
    "username": "new_user",
    "email": "newuser@example.com",
    "user_type": "consumer"
  },
  "project": {
    "project_hash": "proj-default...",
    "project_name": "Default Project"
  }
}
```

### Check Username/Email Availability

**Scenario**: Check if username or email is available before registration.

```bash
# Check username
curl -X POST "http://localhost:8000/auth/check-availability" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=desired_username"

# Check email
curl -X POST "http://localhost:8000/auth/check-availability" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "email=desired@email.com"

# Check both
curl -X POST "http://localhost:8000/auth/check-availability" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=desired_username&email=desired@email.com"
```

**Response:**
```json
{
  "success": true,
  "username_available": true,
  "email_available": true
}
```

---

## Session Management

### Validate Access Token

**Scenario**: Check if the current access token is valid. Refresh tokens are rejected here.

```bash
curl -X GET "http://localhost:8000/auth/validate" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

**Response:**
```json
{
  "success": true,
  "valid": true,
  "user": {
    "user_hash": "usr-abc123...",
    "username": "john_doe",
    "user_type": "consumer"
  },
  "project": {
    "project_hash": "proj-xyz789...",
    "project_name": "Default Project"
  },
  "session": {
    "created_at": null,
    "scope": "project"
  },
  "user_groups": ["developers", "qa_team"]
}
```

### Refresh Token Rotation

**Scenario**: Use the current refresh token to rotate the token pair. `/auth/refresh` accepts the `refresh_token` cookie and/or explicit `refresh_token` body/form value. It rejects access tokens, legacy session tokens, and `Authorization: Bearer` refresh transport.

```bash
curl -X POST "http://localhost:8000/auth/refresh" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "refresh_token=YOUR_REFRESH_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Token refreshed successfully",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "Bearer",
  "expires_in": 900,
  "refresh_expires_in": 259200,
  "user": {
    "user_hash": "usr-abc123...",
    "username": "john_doe",
    "email": "john@example.com",
    "user_type": "consumer"
  },
  "project": {
    "project_hash": "proj-xyz789...",
    "project_name": "Default Project"
  },
  "accessible_projects": [...],
  "user_groups": [...]
}
```

### Logout

**Scenario**: End current session. Logout validates the access token, revokes the associated refresh family, and clears both `session_token` and `refresh_token` cookies.

```bash
curl -X POST "http://localhost:8000/auth/logout" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

**Response:**
```json
{
  "success": true,
  "message": "Logged out successfully"
}
```

---

## Project Switching

### Switch to Different Project

**Scenario**: Change project context without re-logging in. Switch-project requires a valid access token plus the current refresh token (cookie or explicit `refresh_token` field) and returns a new project-scoped access+refresh pair.

```bash
curl -X POST "http://localhost:8000/auth/switch-project" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "project_hash=proj-newproject456...&refresh_token=YOUR_REFRESH_TOKEN"
```

**Response:**
```json
{
  "success": true,
  "message": "Successfully switched to project: New Project",
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "project": {
    "project_hash": "proj-newproject456...",
    "project_name": "New Project",
    "project_description": "Switched project context"
  },
  "user_groups": ["developers"]
}
```

---

## Common Scenarios

### Scenario 1: Complete Authentication Flow

**Goal**: Full login → work → logout cycle.

```bash
# Step 1: Login
LOGIN_JSON=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=john_doe&password=SecurePass123!&project_hash=proj-a123...")
ACCESS_TOKEN=$(echo "$LOGIN_JSON" | jq -r '.access_token')
REFRESH_TOKEN=$(echo "$LOGIN_JSON" | jq -r '.refresh_token')

# Step 2: Use the access token for authenticated requests
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "User-Agent: my-client/1.0"

# Step 3: Refresh access token with the refresh token only
REFRESH_JSON=$(curl -s -X POST "http://localhost:8000/auth/refresh" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "refresh_token=$REFRESH_TOKEN")
ACCESS_TOKEN=$(echo "$REFRESH_JSON" | jq -r '.access_token')
REFRESH_TOKEN=$(echo "$REFRESH_JSON" | jq -r '.refresh_token')

# Step 4: Logout
curl -X POST "http://localhost:8000/auth/logout" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

### Scenario 2: Self-Service Registration

**Goal**: User registers and immediately starts working.

```bash
# Step 1: Check availability
curl -X POST "http://localhost:8000/auth/check-availability" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=newdev&email=newdev@company.com"

# Step 2: Register (requires knowing a user group hash)
REGISTER_JSON=$(curl -s -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=newdev&password=SecurePass123!&email=newdev@company.com&user_group_hash=grp-public123...")
ACCESS_TOKEN=$(echo "$REGISTER_JSON" | jq -r '.access_token')
REFRESH_TOKEN=$(echo "$REGISTER_JSON" | jq -r '.refresh_token')

# Step 3: Start working
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

### Scenario 3: Multi-Project User Workflow

**Goal**: User works across multiple projects in a single session.

```bash
# Step 1: Login (must specify project_hash for all users)
LOGIN_JSON=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=john_doe&password=SecurePass123!&project_hash=proj-a123...")
ACCESS_TOKEN=$(echo "$LOGIN_JSON" | jq -r '.access_token')
REFRESH_TOKEN=$(echo "$LOGIN_JSON" | jq -r '.refresh_token')

# Step 2: Switch project and rotate both credentials
SWITCH_JSON=$(curl -s -X POST "http://localhost:8000/auth/switch-project" \
  -H "Authorization: Bearer $ACCESS_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "project_hash=proj-b456...&refresh_token=$REFRESH_TOKEN")
ACCESS_TOKEN=$(echo "$SWITCH_JSON" | jq -r '.access_token')
REFRESH_TOKEN=$(echo "$SWITCH_JSON" | jq -r '.refresh_token')
```

### Scenario 4: Platform Login and Refresh

**Goal**: Root/admin logs into platform scope and refreshes without project binding.

```bash
PLATFORM_JSON=$(curl -s -X POST "http://localhost:8000/auth/platform/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=root_admin&password=RootPass123!")
ACCESS_TOKEN=$(echo "$PLATFORM_JSON" | jq -r '.access_token')
REFRESH_TOKEN=$(echo "$PLATFORM_JSON" | jq -r '.refresh_token')

REFRESHED_PLATFORM_JSON=$(curl -s -X POST "http://localhost:8000/auth/refresh" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "refresh_token=$REFRESH_TOKEN")
```

Platform refresh preserves platform scope, permissions, and the absence of project binding.

### Scenario 5: Refresh Reuse Revokes Family

If a refresh token is used successfully and then presented again later, the server treats that as reuse/theft, revokes the family, invalidates active access sessions in that family, and returns HTTP 401 with the canonical `{status, error}` envelope. Clients must serialize refresh calls and clear local credentials after a reuse/family-revoked response.

### Scenario 6: Inactive, Deleted, or Bulk-Deactivated User

When an administrator deactivates, deletes, or bulk-deactivates a user, the API revokes that user's active access sessions and refresh families. Old access tokens fail on `/auth/validate` and protected routes, and old refresh tokens fail on `/auth/refresh` with HTTP 401. Clients should clear credentials and stop refresh retries; only an administrator can reactivate the account.

---

## Best Practices

### Security

1. **Use HTTPS** - Always use HTTPS in production
2. **Store tokens securely** - Never store access or refresh tokens in localStorage
3. **Refresh before access expiry** - Use `refresh_token` cookie/body only; do not send access tokens to `/auth/refresh`
4. **Logout on inactivity** - Implement automatic logout

### Token Management

1. **Check access expiry** - Access tokens are short-lived; refresh families are 72h sliding
2. **Handle refresh failures** - Re-authenticate if refresh fails due to invalid/reused/revoked/expired refresh token
3. **Clear on logout** - Ensure tokens are cleared on logout
4. **Serialize refresh calls** - Concurrent duplicate refresh attempts can revoke the family under strict single-use rotation

### Error Handling

1. **Handle 401** - Redirect to login on authentication errors
2. **Handle 403** - Show access denied message
3. **Retry logic** - Implement retry for network errors

---

## Troubleshooting

### Invalid Credentials

**Error**: "Invalid username or password"

**Solutions**:
1. Check username/email is correct
2. Check password is correct
3. Check if user account is active

### Session Expired

**Error**: "Invalid or expired session"

**Solutions**:
1. If the access token expired, call `/auth/refresh` with the current refresh token
2. If refresh fails, clear tokens and re-authenticate with login
3. Check Redis connection (access sessions and refresh families are stored in Redis)

### Refresh Rejected

**Error**: "A valid refresh token is required", `REFRESH_TOKEN_REUSED`, `REFRESH_FAMILY_REVOKED`, or `TOKEN_TYPE_INVALID`

**Solutions**:
1. Ensure `/auth/refresh` receives `refresh_token` cookie or explicit `refresh_token` field
2. Do not send `Authorization: Bearer <access_token>` to `/auth/refresh`
3. Stop retrying after refresh-token reuse/family-revoked errors and force login
4. Legacy access/session tokens are not upgrade credentials and cannot refresh

### Access Denied to Project

**Error**: "Access denied to project"

**Solutions**:
1. Check user is in a user group with access
2. Verify user group has access to project group
3. Verify project is in the project group

```bash
# Check user's groups
curl -X GET "http://localhost:8000/admin/user-groups/users/$USER_HASH/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"

# Check group's project access
curl -X GET "http://localhost:8000/admin/user-groups/$GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

### Username/Email Already Exists

**Error**: "Username already exists" or "Email already exists"

**Solutions**:
1. Use check-availability endpoint first
2. Choose a different username/email
3. Contact admin if you own the account

---

## Quick Reference

### Authentication Endpoints

| Operation | Endpoint | Method | Auth Required |
|-----------|----------|--------|---------------|
| Login | `/auth/login` | POST | No |
| Register | `/auth/register` | POST | No |
| Validate access token | `/auth/validate` | GET | Access JWT or `session_token` cookie |
| Logout | `/auth/logout` | POST | Access JWT or `session_token` cookie |
| Refresh token | `/auth/refresh` | POST | Refresh token only |
| Switch project | `/auth/switch-project` | POST | Access token + current refresh token |
| Check availability | `/auth/check-availability` | POST | No |

### API Key Lifecycle Endpoints

| Operation | Endpoint | Method | Auth Required |
|-----------|----------|--------|---------------|
| Create own API key | `/users/api-keys` | POST | Access JWT or `session_token` cookie |
| List own API keys | `/users/api-keys` | GET | Access JWT or `session_token` cookie |
| View/update/revoke own API key | `/users/api-keys/{key_id}` | GET/PUT/DELETE | Access JWT or `session_token` cookie |
| Create/list admin-scoped API keys | `/api-keys` | POST/GET | Admin/root access JWT or `session_token` cookie |
| View/update/revoke admin-scoped API key | `/api-keys/{key_id}` | GET/PUT/DELETE | Admin/root access JWT or `session_token` cookie |
| List keys for user/project | `/api-keys/users/{user_hash}`, `/api-keys/projects/{project_hash}` | GET | Admin/root access JWT or `session_token` cookie |

These endpoints manage API-key records. They do not mean `X-API-Key` is accepted as protected-route authentication yet.

### Form Fields

| Endpoint | Required Fields | Optional Fields |
|----------|-----------------|-----------------|
| `/auth/login` | username, password, **project_hash** (required for ALL user types: root, admin, consumer) | - |
| `/auth/platform/login` | username, password | - (only root/admin; consumer rejected) |
| `/auth/register` | username, password, user_group_hash | email |
| `/auth/refresh` | refresh_token (or `refresh_token` cookie) | - |
| `/auth/switch-project` | project_hash, refresh_token (or `refresh_token` cookie) | - |
| `/auth/check-availability` | (at least one) | username, email |

---

## Migration and Rollback Notes

This auth change is intentionally breaking:

- `/auth/refresh` rejects legacy access/session tokens immediately. Clients using the old contract must log in again and store `refresh_token`.
- Deployments must set `JWT_SECRET_KEY`; missing secret fails outside explicit tests.
- New refresh-family Redis namespaces may be cleared on rollback or left to expire naturally: `refresh_family:*`, `refresh_token:*`, `refresh_used:*`, `revoked_family:*`, `user_sessions:*`, and `user_refresh_families:*`.
- Rollback means redeploying the previous release. Tokens issued by this true-refresh release are not compatible with the old session-rotation release, so user re-login may be required.
- Do not silently re-enable access-token refresh without a new approved spec.

---

## Related Documentation

- **[Getting Started](getting-started.md)** — Platform setup, bootstrap, and first steps
- **[Client Authentication Guide](client-authentication-guide.md)** — JS, Python, and React integration examples
- **[Error Reference](errors.md)** — Error codes, response shapes, and troubleshooting
- **[Users Documentation Suite](users/README.md)** - User profile, access summary, and lifecycle management
- **[Groups Documentation Suite](groups/README.md)** - Understanding user groups and project access flow
- **[Projects Documentation Suite](projects/README.md)** - Project access control and project switching context

---

**Last Updated**: June 2026
**API Version**: 2.2.0
