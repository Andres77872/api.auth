# Authentication Usage Guide

Complete practical guide for authentication, session management, and user registration in the authentication system.

> **New here?** Start with [Getting Started](getting-started.md) for platform setup and first-time onboarding.
> For client integration (JS, Python, React), see [Client Authentication Guide](client-authentication-guide.md).
> For error codes and troubleshooting, see [Error Reference](errors.md).

> **Important**: Every request MUST include a `User-Agent` header. Missing it returns `422`. All curl examples below include it.

---

## 📖 Table of Contents

- [Authentication Overview](#authentication-overview)
- [Login](#login)
- [Registration](#registration)
- [Session Management](#session-management)
- [Project Switching](#project-switching)
- [Common Scenarios](#common-scenarios)
- [Best Practices](#best-practices)
- [Troubleshooting](#troubleshooting)

---

## Authentication Overview

The authentication system uses **JWT tokens** with **HTTP-only cookies** for secure session management.

### Key Concepts

- **Session Token**: JWT token returned on login, stored in HTTP-only cookie
- **Project Context**: All users (including root) operate within a project context on `/auth/login`
- **Root Users**: Have global access (bypass group-membership validation) but still require `project_hash` on `/auth/login`. Use `/auth/platform/login` for login without project binding.
- **User Groups**: Determine which projects a user can access (root bypasses this validation)

### Authentication Flow

```
1. User submits credentials (username/password)
2. System validates credentials
3. System checks project access (via user groups)
4. JWT token is generated and stored in Redis
5. HTTP-only cookie is set with the token
6. User can now access authorized endpoints
```

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
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
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
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
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

> **Alternative endpoint**: Root and admin users can use `/auth/platform/login` which does **NOT** require `project_hash`. This endpoint is restricted to root/admin; consumer users are rejected (403).

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

### Validate Session

**Scenario**: Check if current session is valid.

```bash
curl -X GET "http://localhost:8000/auth/validate" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
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
    "is_global_session": false
  },
  "user_groups": ["developers", "qa_team"]
}
```

### Refresh Token

**Scenario**: Refresh session token before it expires.

```bash
curl -X POST "http://localhost:8000/auth/refresh" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "User-Agent: my-client/1.0"
```

**Response:**
```json
{
  "success": true,
  "message": "Token refreshed successfully",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
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

**Scenario**: End current session.

```bash
curl -X POST "http://localhost:8000/auth/logout" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
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

**Scenario**: Change project context without re-logging in.

```bash
curl -X POST "http://localhost:8000/auth/switch-project" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "project_hash=proj-newproject456..."
```

**Response:**
```json
{
  "success": true,
  "message": "Successfully switched to project: New Project",
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
TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=john_doe&password=SecurePass123!" | jq -r '.session_token')

# Step 2: Use the token for authenticated requests
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: my-client/1.0"

# Step 3: Refresh token before expiry (optional)
NEW_TOKEN=$(curl -s -X POST "http://localhost:8000/auth/refresh" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: my-client/1.0" | jq -r '.session_token')

# Step 4: Logout
curl -X POST "http://localhost:8000/auth/logout" \
  -H "Authorization: Bearer $NEW_TOKEN" \
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
TOKEN=$(curl -s -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=newdev&password=SecurePass123!&email=newdev@company.com&user_group_hash=grp-public123..." | jq -r '.session_token')

# Step 3: Start working
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: my-client/1.0"
```

### Scenario 3: Multi-Project User Workflow

**Goal**: User works across multiple projects in a single session.

```bash
# Step 1: Login (must specify project_hash for all users)
TOKEN=$(curl -s -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=john_doe&password=SecurePass123!&project_hash=proj-a123..." | jq -r '.session_token')
```

---

## Best Practices

### Security

1. **Use HTTPS** - Always use HTTPS in production
2. **Store tokens securely** - Never store tokens in localStorage
3. **Refresh before expiry** - Refresh tokens proactively
4. **Logout on inactivity** - Implement automatic logout

### Token Management

1. **Check expiry** - Monitor token expiration
2. **Handle refresh failures** - Re-authenticate if refresh fails
3. **Clear on logout** - Ensure tokens are cleared on logout

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
1. Re-authenticate with login
2. Implement automatic token refresh
3. Check Redis connection (sessions stored in Redis)

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
| Validate session | `/auth/validate` | GET | Yes |
| Logout | `/auth/logout` | POST | Yes |
| Refresh token | `/auth/refresh` | POST | Yes |
| Switch project | `/auth/switch-project` | POST | Yes |
| Check availability | `/auth/check-availability` | POST | No |

### Form Fields

| Endpoint | Required Fields | Optional Fields |
|----------|-----------------|-----------------|
| `/auth/login` | username, password, **project_hash** (required for ALL user types: root, admin, consumer) | - |
| `/auth/platform/login` | username, password | - (only root/admin; consumer rejected) |
| `/auth/register` | username, password, user_group_hash | email |
| `/auth/switch-project` | project_hash | - |
| `/auth/check-availability` | (at least one) | username, email |

---

## Related Documentation

- **[Getting Started](getting-started.md)** — Platform setup, bootstrap, and first steps
- **[Client Authentication Guide](client-authentication-guide.md)** — JS, Python, and React integration examples
- **[Error Reference](errors.md)** — Error codes, response shapes, and troubleshooting
- **[Users Documentation Suite](users/README.md)** - User profile, access summary, and lifecycle management
- **[Groups Documentation Suite](groups/README.md)** - Understanding user groups and project access flow
- **[Projects Documentation Suite](projects/README.md)** - Project access control and project switching context

---

**Last Updated**: April 2026
**API Version**: 2.2.0
