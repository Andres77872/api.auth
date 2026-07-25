# Getting Started

Practical onboarding guide for new users, integrators, and platform administrators. Covers everything from first-time setup to your first authenticated API call.

---

## Table of Contents

- [Who This Guide Is For](#who-this-guide-is-for)
- [Prerequisites](#prerequisites)
- [Environment & Configuration](#environment--configuration)
- [First-Root Bootstrap and Current Seed Caveat](#first-root-bootstrap-and-current-seed-caveat)
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
- Python 3.12 (the version used by the project Docker images) with dependencies installed (`pip install -r requirements.txt`)
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
| `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` | No | `15` | Access-token TTL in minutes. Refresh continuity is 72h sliding (`remember_me=false`) or a 30-day absolute, non-sliding window (`remember_me=true`). |
| `API_KEY_PEPPER` | Yes | -- | HMAC pepper for API key hashing; required before API key utilities import |
| `ALLOWED_ORIGINS` | No | source fallback | Explicit CORS allow-list (comma-separated). **Set it in every deployment.** Use [.env.example](../../.env.example) as the maintained template rather than relying on source fallbacks. |
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

## First-Root Bootstrap and Current Seed Caveat

**There is no API-based bootstrap flow for the very first root user.**

The endpoint `POST /user-types/root` requires an existing root token to
authenticate (`Depends(require_root_user)`). The repository does contain a SQL
seed, but its current credential path is not compatible with current login:

- `scripts/create_database.py` and `scripts/recreate_database.py` execute
  `schemas/tables/05_initialize_data.sql`;
- that SQL inserts `root` with a legacy SHA-256 hash for plaintext
  `1248163264`;
- the active password verifier accepts Argon2id hashes only, so that seeded
  credential cannot log in;
- both Python scripts print `admin123`, which does not match the SQL seed and
  also cannot log in.

Treat both exposed defaults as invalid development artifacts, not deployment
credentials.

### After the canonical database script

Rotate the seeded row to a policy-compliant Argon2id password before first
login:

```bash
.venv/bin/python - <<'PY'
from getpass import getpass
from src.Util.db.db_config import get_connection
from src.Util.password_security import assert_password_policy, hash_password

password = getpass("Root password: ")
assert_password_policy(password, username="root", email="root@system.local")

with get_connection() as connection:
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT id FROM users "
            "WHERE username = %s AND user_type = 'root' AND is_active = TRUE "
            "LIMIT 1",
            ("root",),
        )
        row = cursor.fetchone()
        if not row:
            raise SystemExit("Seeded root row was not found")
        cursor.callproc("sp_update_password_hash", [row["id"], hash_password(password)])
    connection.commit()

print("Seeded root password rotated to Argon2id")
PY
```

### If the SQL seed is deliberately omitted

Create the first root through the application's DB helper. It generates IDs,
hashes the password with Argon2id, and calls the six-argument stored procedure:

```bash
.venv/bin/python - <<'PY'
from getpass import getpass
from src.Util.db.db_users import create_root_user
from src.Util.password_security import assert_password_policy

username = input("Root username: ").strip()
email = input("Root email (optional): ").strip() or None
password = getpass("Root password: ")
assert_password_policy(password, username=username, email=email)
user = create_root_user(
    username=username,
    password=password,
    email=email,
    created_by=None,
)
print(f"Created {user.user_hash}")
PY
```

Do not pass plaintext directly to `sp_create_root_user`; its database contract
expects generated IDs and a password hash. `created_by=None` is acceptable only
for this first user. After bootstrap, use `POST /user-types/root` to create
additional root users through the API.

> **Current operational gap:** the SQL seed, active verifier, and bootstrap
> completion messages disagree. The documented rotation is required until the
> source bootstrap is corrected.

Once the root user exists, log in:

```bash
curl -X POST "{BASE_URL}/auth/platform/login" \
  -H "User-Agent: my-client/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=your_root_username&password=your_root_password"
```

Save the `access_token` (the deprecated `session_token` alias has the same value)
from the response. Use it as `$ROOT_TOKEN` for subsequent admin operations.

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

**Password note:** Password-setting routes enforce the shared server-side policy:
minimum length (default 8), common-password denial, username/email derivation
checks, and repeated/sequential-value rejection. The policy intentionally does
not require arbitrary character classes. A rejection uses `VAL_3007` with safe
reason codes; clients should mirror the guidance, but the server remains
authoritative.

### Login

```bash
curl -X POST "{BASE_URL}/auth/login" \
  -H "User-Agent: my-client/1.0" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_user&password=MySecurePass123!&project_hash=$PROJECT_HASH"
```

> **Note**: `project_hash` is REQUIRED for all users. Root users bypass group-based access validation and may access any project by role.

### Other Available Auth Flows

Beyond username/password login, the `/auth` suite exposes several additional flows. These are documented in full elsewhere — see the linked suites rather than duplicating them here:

| Flow | Entry endpoint(s) | Where to read |
|------|-------------------|---------------|
| **Email verification** (activation) | `POST /auth/email/verify` (+ per-user `/users/*/emails*` management) | [Authentication Usage Cases](authentication-usage-cases.md), [Email Suite](email/README.md), [Users → Email Management](users/email-management.md) |
| **Password recovery** | `POST /auth/password/forgot`, `POST /auth/password/reset` | [Authentication Usage Cases](authentication-usage-cases.md), [Email Activation Runbook](../RUNBOOKS/email-activation.md) |
| **Authenticated password change** | `POST /auth/password/change` | [Authentication Usage Cases](authentication-usage-cases.md) |
| **Google sign-in (OAuth)** | `POST /auth/google/start`, `GET /auth/google/callback`, link/unlink/reauth | [Google OAuth Suite](google-oauth/README.md) |
| **Platform login** (project-agnostic) | `POST /auth/platform/login` | [Authentication Usage Cases](authentication-usage-cases.md) |
| **API-key validation** | `POST /auth/validate-api-key` | [API Keys Suite](api-keys/README.md) |

Public email flows (`verify`/`forgot`/`reset` and the authenticated add/resend routes) return a generic `202 Accepted` regardless of account state to prevent enumeration; honor `429 Retry-After` if rate-limited.

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
| Refresh Max-Age | 259200s (72h), sliding on refresh — or 2592000s (30d) absolute when `remember_me=true` |
| HttpOnly | true |
| Secure | true |
| SameSite | strict |

Browsers automatically send these cookies on subsequent requests. No `Authorization` header is needed for browser flows when cookies are used.

### API Keys: lifecycle + dedicated validation, not general route auth

API keys can be created, listed, updated, and revoked through the API-key lifecycle endpoints (self-service `/users/api-keys`, admin `/api-keys`), and a dedicated endpoint validates them:

- **`POST /auth/validate-api-key`** authenticates a user-created API key supplied in the **`X-API-Key`** header and returns the resolved user/project/groups/permissions context. Sending **both** `Authorization` and `X-API-Key` is rejected with `400 ambiguous_credentials`. The raw key/secret is never echoed back. This is the supported way to verify a key.
- API keys are **still not a general protected-route auth mode**: the other protected endpoints (e.g. `/users/profile`) require a Bearer access JWT or the `session_token` cookie. `X-API-Key` populates request/audit context but does not by itself authorize arbitrary protected routes.

See the [API Keys Documentation Suite](api-keys/README.md) for the full lifecycle, key format, scope model, and validation contract.

### Which to use?

| Scenario | Recommended mode |
|----------|-----------------|
| Browser-based SPA / frontend | Cookie (automatic) |
| curl / scripts / server-to-server | Bearer header |
| Mobile apps | Bearer header (store token securely) |

### Session Lifecycle

Four different TTLs operate independently — don't confuse them:

| TTL | Value | What it controls |
|-----|-------|-----------------|
| **Access JWT/cookie TTL** | Short-lived | How long the access token itself is valid for protected requests. |
| **Refresh JWT/family TTL** | 72h (259200s) sliding, or 30 days absolute with `remember_me=true` | How long refresh continuity lives. With `remember_me=false` the 72h window slides on each successful `POST /auth/refresh`; with `remember_me=true` it is a fixed 30-day (2592000s) non-sliding window. |
| **Refresh anchor TTL** | Matches the refresh family window | How long `refresh_anchor:{family_id}` keeps non-secret refresh continuity context. This outlives `session:{access_jti}` but never stores raw tokens or permissions. |
| **Redis access session TTL** | Access-token TTL | How long `session:{access_jti}` lives in Redis. |
| **Cache layer TTL** | 1 hour (session) / 30 min (permission checks) | How long cached permission/access-check results live in Redis. **Separate from auth sessions.** A user's session can be valid while their cached permissions are stale. |

- **Refresh**: `POST /auth/refresh` requires a valid `refresh_token` cookie/body value, issues a new access+refresh pair, marks the old refresh token used, and deletes the old access session. Access/session tokens are rejected as refresh credentials.
- **Access expiry is recoverable**: an expired access JWT or evicted `session:{access_jti}` is expected after the short access TTL. Refresh still succeeds while the refresh token, refresh family, and `refresh_anchor:{family_id}` or safe legacy fallback remain valid/current.
- **Logout/revocation is different from access expiry**: deleting only `session:{access_jti}` invalidates that access token, but it is not a full logout contract. Logout, reuse detection, deactivation, and admin revocation revoke/tombstone the refresh family and delete the refresh anchor.
- After admin permission changes, the user may need to wait for cache expiry (30 min) or manually invalidate their cache (`POST /system/cache/invalidate/user/{hash}`) to see updated permissions.

---

## Common Gotchas

### 1. `User-Agent` header is mandatory

**Every** request must include a `User-Agent` header. Missing it returns `422`.

```bash
-H "User-Agent: my-client/1.0"
```

### 2. Write endpoints use more than one content type

Login, registration, refresh, switching, and many older CRUD/admin mutations are
form-encoded. Email-template, provider, internal S2S, audit-export, and selected
bulk routes use JSON. Webhooks require their provider's signed raw body. Follow
the request-body schema in OpenAPI or the relevant domain reference; do not
assume one content type for every write.

### 3. POST body limit is 8MB

Requests exceeding 8MB return `413 Payload Too Large`.

### 4. Two endpoints return 501 (Not Implemented)

- `PATCH /projects/{hash}/owner` — reserved for future use
- `PATCH /projects/{hash}/archive` — reserved for future use

### 5. Rate limiting is route-specific

Login-identifier, password/email, Google OAuth, Patreon, and billing flows have
dedicated limits and may return `429` with `Retry-After`. The service does not
provide one universal limit for every route, so keep infrastructure-level
protection as an additional control.

### 6. Use only the documented auth transports

Protected routes use `Authorization: Bearer <access_token>` or the
`session_token` cookie. Legacy `X-token-user` / `X-token-collection` constants
remain in compatibility code but are not wired into the active protected-route
dependency.

### 7. CORS uses an explicit allow-list

Set `ALLOWED_ORIGINS` to the exact browser clients that should call the API.
[`.env.example`](../../.env.example) is the maintained deployment template; do
not depend on fallback lists embedded in source.

### 8. Password policy is server-enforced

Password-setting flows enforce the shared policy described in the registration
section. Treat `VAL_3007` reason codes as the public contract and never log or
echo the submitted password.

### 9. UUIDs are masked in error responses

Error messages mask UUIDs (e.g., `usr-[550e]...[0000]`). Clients cannot parse full IDs from error messages.

### 10. DEBUG_MODE changes error shape

- `DEBUG_MODE=false` (default): `{"status":"error","error":{"code":"...","category":"...","message":"..."}}`
- `DEBUG_MODE=true`: Adds `details` and `trace` fields to the error object. **Never enable in production.**

---

## What to Read Next

| Topic | Document |
|-------|----------|
| Full authentication flows (login, refresh, password, email verify) | [Authentication Usage Cases](authentication-usage-cases.md) |
| Client integration (JS, Python, React) | [Client Authentication Guide](client-authentication-guide.md) |
| Google sign-in (OAuth) | [Google OAuth Documentation Suite](google-oauth/README.md) |
| API keys (lifecycle + validation) | [API Keys Documentation Suite](api-keys/README.md) |
| Transactional email (templates, webhooks, delivery) | [Email Documentation Suite](email/README.md) |
| Error codes and troubleshooting | [Error Reference](errors.md) |
| How permissions actually work | [Permission Resolution](permissions/resolution.md) |
| User management (incl. per-user email management) | [Users Documentation Suite](users/README.md) |
| Groups architecture | [Groups Documentation Suite](groups/README.md) |
| Projects | [Projects Documentation Suite](projects/README.md) |

---

**API Version**: 2.2.0
