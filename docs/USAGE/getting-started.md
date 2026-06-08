# Getting Started

Practical onboarding guide for new users, integrators, and platform administrators. Covers everything from first-time setup to your first authenticated API call.

---

## Table of Contents

- [Who This Guide Is For](#who-this-guide-is-for)
- [Prerequisites](#prerequisites)
- [Environment & Configuration](#environment--configuration)
- [First-Root Bootstrap (Manual DB Step)](#first-root-bootstrap-manual-db-step)
- [First Admin, User Group & Project Setup](#first-admin-user-group--project-setup)
- [Registration & Login Quickstart](#registration--login-quickstart)
- [Authentication Modes](#authentication-modes)
- [Common Gotchas](#common-gotchas)
- [What to Read Next](#what-to-read-next)

---

## Who This Guide Is For

| Role | What you'll get from this guide |
|------|--------------------------------|
| **Platform administrator** | How to bootstrap the system, create the first root, set up projects and user groups |
| **Integrator / developer** | How to authenticate, which content types to use, what headers are required |
| **End user** | How registration works, what you need from your admin to get started |

---

## Prerequisites

- A running **MySQL** instance with the API schema applied (stored procedures, tables, views)
- A running **Redis** instance (sessions are stored here)
- Python 3.10+ with the project dependencies installed (`pip install -r requirements.txt`)
- `curl` or any HTTP client for testing

---

## Environment & Configuration

The API reads configuration from environment variables. See [.env.example](../../.env.example) for the full documented template, including test-only and deprecated variables. These are the core runtime variables you **must** or **should** set:

| Variable | Required | Default | Notes |
|----------|----------|---------|-------|
| `DB_HOST` | Yes | -- | MySQL host |
| `DB_PORT` | No | `3306` | MySQL port |
| `DB_USER` | Yes | -- | MySQL user |
| `DB_MYSQL_PASSWORD` | Yes | -- | MySQL password |
| `DB_NAME` | Yes | -- | Database name |
| `REDIS_HOST` | Yes | -- | Redis host |
| `REDIS_PORT` | No | `6379` | Redis port |
| `REDIS_DB` | No | `0` | Redis DB number |
| `DB_REDIS_PASSWORD` | No | -- | Redis password |
| `JWT_SECRET_KEY` | **Yes outside explicit tests** | None — startup fails | See critical note below |
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | No | `15` | Access-token TTL in minutes; refresh family remains 72h sliding |
| `API_KEY_PEPPER` | Yes | -- | HMAC pepper for API key hashing; required before API key utilities import |
| `ALLOWED_ORIGINS` | No | `http://localhost:3000,http://localhost:5173,http://localhost:4173,https://auth-ui.arz.ai,http://localhost:5177` | Explicit CORS origins (comma-separated) |
| `DEBUG_MODE` | No | `false` | Enables tracebacks in error responses |

### Critical: `JWT_SECRET_KEY`

If `JWT_SECRET_KEY` is **not** set, startup fails outside explicit test runtimes. Silent random JWT secrets are not allowed anymore.

- **Production/staging/dev services must set a fixed, secure value**
- **Only explicit test runtimes use the deterministic test secret**
- **Configuration failures surface as `JWT_CONFIGURATION_FAILURE` (`AUTH_1021`)**

See [Error Reference → JWT Configuration Failure](errors.md#jwt-configuration-failure) for the error envelope and operator guidance.

### Starting the Server

```bash
uvicorn src.main:app --host 0.0.0.0 --port 8000
```

The API has **no configurable base URL prefix**. All routes are mounted at `/`. Health check: `GET /ping` returns `204 No Content`.

---

## First-Root Bootstrap (Manual DB Step)

**There is no API-based bootstrap flow for the very first root user.**

The endpoint `POST /user-types/root` requires an existing root token to authenticate (`Depends(require_root_user)`). There is no CLI script, seed migration, or environment-variable-based bootstrap.

### What you must do

Create the first root user **directly in the database** by calling the stored procedure:

```sql
CALL sp_create_root_user('your_root_username', 'your_root_password', 'root@example.com', NULL);
```

The `NULL` for `created_by` is acceptable for the very first user since there is no existing creator. After this, you can log in and use `POST /user-types/root` to create additional root users via the API.

> **This is a known operational gap.** If you are deploying this platform, plan for this manual step.

Once the root user exists, log in:

```bash
curl -X POST "{BASE_URL}/auth/login" \
  -H "User-Agent: my-client/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=your_root_username&password=your_root_password"
```

Save the `session_token` from the response. You will use it as `$ROOT_TOKEN` for all subsequent admin operations.

---

## First Admin, User Group & Project Setup

After bootstrapping the root user, the typical setup path is:

### 1. Create an Admin User (root only)

```bash
curl -X POST "{BASE_URL}/user-types/admin" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "User-Agent: my-client/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=project_admin&password=AdminPass123!&email=admin@example.com&assigned_project_id=1"
```

### 2. Create a Project (admin)

```bash
curl -X POST "{BASE_URL}/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "name=My+Project&description=First+project"
```

### 3. Create a User Group (admin)

```bash
curl -X POST "{BASE_URL}/admin/user-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "name=developers&description=Development+team"
```

The response includes a `group_hash` (e.g., `grp-abc123...`). **This is the value end users need for registration.**

### 4. Link the User Group to a Project Group

User groups gain project access through **project groups**. Create a project group, assign the project to it, then grant the user group access:

```bash
# Create project group
curl -X POST "{BASE_URL}/admin/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "name=my-project-group&description=Group+for+my+project"

# Assign project to project group (use the project_group_hash from the response above)
curl -X POST "{BASE_URL}/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$PROJECT_HASH"

# Grant user group access to the project group
curl -X POST "{BASE_URL}/admin/user-groups/$GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "User-Agent: my-client/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$PROJECT_GROUP_HASH"
```

Now any user who registers with `$GROUP_HASH` will have access to the project.

---

## Registration & Login Quickstart

### Registration (End User)

Registration requires a valid, active `user_group_hash` provided by an admin. Self-registration is **not** open.

```bash
curl -X POST "{BASE_URL}/auth/register" \
  -H "User-Agent: my-client/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_user&password=MySecurePass123!&email=user@example.com&user_group_hash=$GROUP_HASH"
```

**Password note:** The API has **no server-side password complexity enforcement**. A utility function exists (`validate_password_strength`) but it is only used in unit tests. Clients **must** implement their own password validation before sending credentials.

### Login

```bash
curl -X POST "{BASE_URL}/auth/login" \
  -H "User-Agent: my-client/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_user&password=MySecurePass123!&project_hash=$PROJECT_HASH"
```

> **Note**: `project_hash` is REQUIRED for all users. Root users bypass group-based access validation and may access any project by role.

---

## Authentication Modes

Protected endpoints currently accept access JWTs in **two ways**. Both are equivalent for protected-route authorization:

### Mode 1: Bearer Header (API clients, scripts, server-to-server)

```bash
curl -X GET "{BASE_URL}/users/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "User-Agent: my-client/1.0"
```

### Mode 2: Cookie (Browsers, SPAs)

On login, the API sets an HTTP-only cookie named `session_token`:

| Property | Value |
|----------|-------|
| Access cookie | `session_token` (deprecated alias for `access_token`) |
| Refresh cookie | `refresh_token` |
| Access Max-Age | Short-lived access-token TTL |
| Refresh Max-Age | 259200 seconds (72 hours), sliding on successful refresh |
| HttpOnly | true |
| Secure | true |
| SameSite | strict |

Browsers automatically send these cookies on subsequent requests. No `Authorization` header is needed for browser flows when cookies are used.

### Not a Protected-Route Mode: API Keys

API keys can be created, listed, updated, and revoked through the API-key lifecycle endpoints, but they are **not currently accepted as protected-route authentication**.

- `X-API-Key` alone on protected endpoints currently returns `401`.
- API-key middleware can populate request/audit context, but route authorization still requires Bearer access JWT or the `session_token` cookie.
- Future behavior should allow a valid API token generated for a user/project to authenticate protected routes as that user, but that unified auth dependency and route migration are not wired yet.

### Which to use?

| Scenario | Recommended mode |
|----------|-----------------|
| Browser-based SPA / frontend | Cookie (automatic) |
| curl / scripts / server-to-server | Bearer header |
| Mobile apps | Bearer header (store token securely) |

### Session Lifecycle

Three different TTLs operate independently — don't confuse them:

| TTL | Value | What it controls |
|-----|-------|-----------------|
| **Access JWT/cookie TTL** | Short-lived | How long the access token itself is valid for protected requests. |
| **Refresh JWT/family TTL** | 72 hours (259200s), sliding | How long refresh continuity lives. Renewed on successful `POST /auth/refresh`. |
| **Redis access session TTL** | Access-token TTL | How long `session:{access_jti}` lives in Redis. |
| **Cache layer TTL** | 1 hour (session) / 30 min (permission checks) | How long cached permission/access-check results live in Redis. **Separate from auth sessions.** A user's session can be valid while their cached permissions are stale. |

- **Refresh**: `POST /auth/refresh` requires a valid `refresh_token` cookie/body value, issues a new access+refresh pair, marks the old refresh token used, and deletes the old access session. Access/session tokens are rejected as refresh credentials.
- After admin permission changes, the user may need to wait for cache expiry (30 min) or manually invalidate their cache (`POST /system/cache/invalidate/user/{hash}`) to see updated permissions.

---

## Common Gotchas

### 1. `User-Agent` header is mandatory

**Every** request must include a `User-Agent` header. Missing it returns `422`.

```bash
-H "User-Agent: my-client/1.0"
```

### 2. Most write endpoints use `multipart/form-data`, NOT JSON

Virtually **all** POST/PUT/PATCH endpoints use `Form(...)` parameters. Sending `application/json` will fail with `422`.

**Exceptions** (these DO use JSON):
- `POST /admin/user-groups/{hash}/members/bulk` — `application/json` with `List[str]` body
- `POST /admin/audit/export` — `application/json`

### 3. POST body limit is 8MB

Requests exceeding 8MB return `413 Payload Too Large`.

### 4. Two endpoints return 501 (Not Implemented)

- `PATCH /projects/{hash}/owner` — reserved for future use
- `PATCH /projects/{hash}/archive` — reserved for future use

### 5. No rate limiting

There is **no rate limiting** on any endpoint, including login. Plan for brute-force protection at the infrastructure level (reverse proxy, WAF, etc.).

### 6. Legacy auth headers still work (deprecated)

The API still accepts `X-token-user` and `X-token-collection` headers as a fallback. These are **deprecated** and should not be used in new integrations.

### 7. CORS defaults to an explicit allow-list

`ALLOWED_ORIGINS` defaults to `http://localhost:3000,http://localhost:5173,http://localhost:4173,https://auth-ui.arz.ai,http://localhost:5177`. In production, you **must** set `ALLOWED_ORIGINS` to the exact browser clients that should call this API directly.

### 8. Password complexity is NOT enforced

The API accepts any password, including empty strings. Client-side validation is the only line of defense.

### 9. UUIDs are masked in error responses

Error messages mask UUIDs (e.g., `usr-[550e]...[0000]`). Clients cannot parse full IDs from error messages.

### 10. DEBUG_MODE changes error shape

- `DEBUG_MODE=false` (default): `{"status":"error","error":{"code":"...","category":"...","message":"..."}}`
- `DEBUG_MODE=true`: Adds `details` and `trace` fields to the error object. **Never enable in production.**

---

## What to Read Next

| Topic | Document |
|-------|----------|
| Full authentication flows | [Authentication Usage Cases](authentication-usage-cases.md) |
| Client integration (JS, Python, React) | [Client Authentication Guide](client-authentication-guide.md) |
| Error codes and troubleshooting | [Error Reference](errors.md) |
| How permissions actually work | [Permission Resolution](permissions/resolution.md) |
| User management | [Users Documentation Suite](users/README.md) |
| Groups architecture | [Groups Documentation Suite](groups/README.md) |
| Projects | [Projects Documentation Suite](projects/README.md) |

---

**Last Updated**: June 2026
**API Version**: 2.2.0
