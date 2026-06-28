# 🔐 Group-Based Multi-Project Authentication API

`api.auth` is a FastAPI authentication and authorization service for multi-project products. It combines local username/password auth, Google OAuth/OIDC, hierarchical group access, global roles, permission groups, API keys, transactional email, Patreon entitlement linking, and provider-agnostic Stripe billing facts.

## 🏗️ Access Model

```text
USER -> USER_GROUP -> PROJECT_GROUP -> PROJECTS
                 \-> PERMISSION_GROUP -> PERMISSIONS
```

**Key concepts:**
- **Users** belong to **User Groups**.
- **User Groups** receive access to **Project Groups**.
- **Project Groups** contain related **Projects**.
- **User Groups** and individual users can receive **Permission Groups**.
- **Permission Groups** contain granular **Permissions**.

## 🌟 User Types

| Type | Description | Access Level |
|------|-------------|--------------|
| 🔴 `root` | System administrators | Full global access and sensitive admin surfaces |
| 🟡 `admin` | Project/platform administrators | Project, group, role, audit, and delegated admin workflows |
| 🟢 `consumer` | Regular users | Self-service profile/auth and project access through groups |

## ✨ Features

### 🔐 Authentication & Sessions
- True access/refresh JWT model with Redis-backed revocation authority.
- Short-lived access tokens for protected requests and `/auth/validate`.
- 72-hour sliding refresh-token families by default, or 30-day absolute refresh families when `remember_me=true`.
- HttpOnly Secure cookies for both `session_token` (access alias) and `refresh_token`.
- Multi-project login, project switching, root/admin platform login, strict refresh rotation, logout, and deactivation revocation.
- Consumer Google OAuth/OIDC through opaque provider-init tokens; see [Google OAuth docs](docs/USAGE/google-oauth/README.md).
- Self-service password recovery, email verification/activation, multi-email management, and username/email availability checks.
- API-key validation through `POST /auth/validate-api-key` with the `X-API-Key` header.

### 👥 Groups, Roles, Permissions, and Projects
- User groups, project groups, and groups-of-groups access control.
- Global role definitions, role assignment, permission-group catalogs, and direct permission-group assignment.
- Project CRUD, member/group/activity/statistics reads, and project archive enforcement in downstream auth checks.
- Project owner/archive API toggle routes exist but currently return 501.

### 🔑 API Keys
- Self-service API keys under `/users/api-keys`.
- Admin API-key management under `/api-keys`.
- Split-token format (`sk_{public_id}.{secret}`), one-time secret reveal, HMAC-SHA-256 verification, and step-up re-auth on key mutations.

### 📧 Email & Notifications
- Per-user multi-email management and primary-email selection.
- ROOT-only transactional email templates with create/update/disable/preview/send-test/rollback.
- Durable outbox-worker delivery model, Resend webhook ingestion, Mailpit/local capture support, and email delivery audit logs.
- Internal email endpoints for trusted template delivery and delivery-status lookup.

### 💳 Stripe Billing Facts
- Provider-agnostic billing facts with Stripe as the provider adapter.
- Billing groups own per-group encrypted Stripe credentials, per-group project membership, and catalog items.
- Admin billing dashboard API for groups, credentials, capabilities, catalog reconciliation/import/sync, and metrics.
- S2S billing API for status, public catalog, hosted Checkout, Customer Portal, purchase status, and resync requests.
- Stripe webhook routes for global migration fallback and per-billing-group webhook secrets.

### 🟠 Patreon Entitlements
- Patreon is entitlement/link proof only; it does not issue local sessions, JWTs, refresh tokens, cookies, or API keys.
- Authenticated link lifecycle: request proof, confirm proof, read status, and unlink.
- ROOT-only Patreon admin status, entitlement, tier-map, sync-job, webhook, and resync APIs.
- S2S entitlement read/resync routes for trusted consumers.

### 🛡️ Security and Operations
- UUID-style public identifiers such as `usr-{UUID4}` and `proj-{UUID4}`.
- Audit trail, security-event views, CSV/JSON export, activity feed, and API audit middleware.
- Redis-backed session, refresh-family, validation-cache, rate-limit, and worker-heartbeat state.
- Dedicated S2S bearer boundaries for internal billing and Patreon APIs.

## 🚀 Quick Start

```bash
# 1. Install dependencies
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

# 2. Configure local environment
cp .env.example .env
# Edit .env: DB_*, REDIS_*, JWT_SECRET_KEY, API_KEY_PEPPER, and feature flags.

# 3. Create the database schema
python scripts/create_database.py

# 4. Start the API
python -m uvicorn src.main:app --reload

# 5. Smoke test
curl -H "User-Agent: local-smoke/1.0" http://localhost:8000/system/ping
```

`src/__init__.py` loads the project `.env` before runtime imports. Use `scripts/recreate_database.py` only when you intentionally want to drop and rebuild `magic_auth`; it is destructive and asks for confirmation.

## 📡 API Surface

The app currently registers **217 route-module endpoint methods across 25 `src/routes/*.py` modules** for API version `2.2.0`. This count treats each method/path pair as one endpoint and excludes FastAPI's built-in `/docs`, `/redoc`, `/openapi.json`, root route, top-level `/ping`, and the two rendered documentation routes in `src/main.py`.

| Surface | Prefix | Module | Count | Contract |
|---------|--------|--------|-------|----------|
| Authentication | `/auth` | `auth.py` | 13 | Session, refresh token, API-key validation |
| Google OAuth | `/auth/google` | `auth_google.py` | 6 | Provider-init mediated OAuth/OIDC |
| Patreon Link | `/auth/patreon` | `auth_patreon.py` | 4 | Existing local session + recent reauth |
| Users | `/users` | `users.py` | 19 | Profile, admin user management, email management |
| User API Keys | `/users/api-keys` | `user_api_keys.py` | 5 | Self-service API-key lifecycle |
| Admin API Keys | `/api-keys` | `api_keys.py` | 7 | Admin API-key lifecycle |
| User Types | `/user-types` | `user_types_auth.py` | 10 | Root/admin user-type workflows |
| Projects | `/projects` | `projects.py` | 11 | Project CRUD and project reads |
| User Groups | `/admin/user-groups` | `admin_user_groups.py` | 13 | User-group CRUD, membership, project-group access |
| Project Groups | `/admin/project-groups` | `admin_project_groups.py` | 7 | Project-group CRUD and project membership |
| Roles | `/roles` | `global_roles.py` | 28 | Roles, permission groups, permissions, role catalogs |
| Permission Assignments | `/permissions` | `permission_assignments.py` | 17 | Permission-group assignment and lookup |
| Admin Billing | `/admin/billing` | `admin_billing.py` | 22 | Billing groups, credentials, capabilities, catalog, metrics |
| Billing Internal | `/internal/.../billing` | `internal_billing.py` | 6 | S2S billing facts, catalog, Checkout, Portal, resync |
| Stripe Webhooks | `/webhooks/stripe` | `stripe_webhooks.py` | 2 | Raw Stripe webhook intake |
| Admin Patreon | `/admin/patreon` | `admin_patreon.py` | 7 | ROOT-only Patreon status and operations |
| Patreon Internal | `/internal/users/{user_hash}/entitlements` | `internal_patreon.py` | 2 | S2S entitlement read and resync |
| Patreon Webhooks | `/webhooks/patreon` | `patreon_webhooks.py` | 1 | Raw Patreon webhook intake |
| Internal Email | `/internal/email` | `internal_email.py` | 3 | Root-gated identity, template send, message status |
| Email Templates | `/admin/email-templates` | `email_templates.py` | 8 | ROOT-only template lifecycle |
| Email Webhooks | `/webhooks/email` | `email_webhooks.py` | 1 | Raw Resend/Svix webhook intake |
| Audit Logs | `/admin/audit`, `/admin/email/logs` | `audit_logs.py` | 6 | Audit, security events, export, user activity |
| Admin Dashboard | `/admin` | `admin_dashboard.py` | 8 | Dashboard, health, activity, statistics |
| Bulk Operations | `/admin` | `bulk_operations.py` | 4 | Bulk user, group, and role assignment operations |
| System | `/system` | `system.py` | 7 | Info, health, ping, cache management |

Detailed request/response examples live in the domain docs under [docs/USAGE](docs/USAGE/README.md). The running API also serves:
- Swagger UI: `/docs`
- ReDoc: `/redoc`
- Rendered markdown documentation: `/documentation`
- Raw markdown documentation: add `?format=raw` to `/documentation/...`

## 💡 API Usage

### Auth Token Contract

This release uses a **two-token model**:

- `access_token`: short-lived JWT used for protected API requests, `/auth/validate`, `/auth/logout`, and `/auth/switch-project`.
- `refresh_token`: 72-hour sliding JWT by default, or a 30-day absolute JWT when `remember_me=true`; it is used only for `/auth/refresh` and returned in the JSON body and as an HttpOnly Secure `refresh_token` cookie.
- `session_token`: deprecated compatibility alias for `access_token` in response bodies and the access cookie.

`POST /auth/refresh` rejects legacy access/session tokens. Do not send `Authorization: Bearer <access_token>` to refresh; send the refresh token through the `refresh_token` cookie or explicit `refresh_token` form/body field.

Access JWT signature, `exp`, `type`, `jti`, `session_id`, `family_id`, and server-side Redis session/family state are enforced before a request is trusted.

### Authentication

```bash
# Login with a project context
curl -X POST "http://localhost:8000/auth/login" \
  -H "User-Agent: my-client/1.0" \
  -F "username=john_doe" \
  -F "password=SecurePass123!" \
  -F "project_hash=proj-xxxx"

# Platform login for root/admin users
curl -X POST "http://localhost:8000/auth/platform/login" \
  -H "User-Agent: my-client/1.0" \
  -F "username=admin_user" \
  -F "password=SecurePass123!"

# Authenticated request with the access token
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "User-Agent: my-client/1.0"

# Refresh with the refresh token only
curl -X POST "http://localhost:8000/auth/refresh" \
  -H "User-Agent: my-client/1.0" \
  -F "refresh_token=YOUR_REFRESH_TOKEN"

# Validate an API key
curl -X POST "http://localhost:8000/auth/validate-api-key" \
  -H "User-Agent: my-client/1.0" \
  -H "X-API-Key: sk_PUBLIC.SECRET"
```

### Request Format

- A **`User-Agent` header is required on every request**. Missing it returns `422`.
- Most legacy/admin mutating endpoints use `multipart/form-data` FastAPI `Form(...)` fields.
- Major JSON-body surfaces include Google OAuth POST routes, Patreon link request/confirm, admin billing capabilities/catalog import, admin Patreon resync, internal billing, internal Patreon resync, internal email, email-template mutations, audit export, and bulk permission/user membership operations.
- Webhook endpoints consume raw provider-signed request bodies.
- Responses are JSON and use Pydantic response validation or explicit safe DTO serialization.

### Response Shape

Most first-party responses follow this shape:

```json
{
  "success": true,
  "message": "Operation completed successfully",
  "data": {}
}
```

Some webhook and internal routes intentionally return narrower provider-safe DTOs or empty success responses.

## 📚 Documentation

### Usage Guides

| Document | Description |
|----------|-------------|
| [Getting Started](docs/USAGE/getting-started.md) | Installation, env vars, first run |
| [Authentication](docs/USAGE/authentication-usage-cases.md) | Login, sessions, project switching |
| [Google OAuth/OIDC](docs/USAGE/google-oauth/README.md) | Provider-init, scope, request flow, scenarios, troubleshooting, reference |
| [Patreon Link](docs/USAGE/patreon-link/README.md) | Entitlement-only Patreon link/proof, S2S read, webhooks, sync |
| [Stripe Billing](docs/USAGE/stripe-billing/README.md) | Billing groups, catalog, credentials, S2S checkout/portal/status, webhooks |
| [Users](docs/USAGE/users/README.md) | Profile, admin operations, bulk ops, multi-email management |
| [Groups](docs/USAGE/groups/README.md) | User groups, project groups, flows, troubleshooting |
| [Projects](docs/USAGE/projects/README.md) | Project management suite |
| [Roles](docs/USAGE/roles/README.md) | Role definitions, assignment flows |
| [Permissions](docs/USAGE/permissions/README.md) | Permission groups, RBAC resolution |
| [API Keys](docs/USAGE/api-keys/README.md) | Self-service and admin API-key management |
| [Email](docs/USAGE/email/README.md) | Templates, delivery/outbox, provider webhook |
| [Audit Logs](docs/USAGE/audit_logs/README.md) | Audit trail, security events, email logs, export |
| [Admin](docs/USAGE/admin-usage-cases.md) | Dashboard, bulk ops, cache |
| [Error Reference](docs/USAGE/errors.md) | Error codes and troubleshooting |

### Schema and Runbooks

- [Database Schema](schemas/docs/README.md)
- [External Accounts Schema](schemas/docs/external-accounts.md)
- [Google OAuth Runbook](docs/RUNBOOKS/google-oauth.md)
- [Email Activation Runbook](docs/RUNBOOKS/email-activation.md)
- [Patreon Link Runbook](docs/RUNBOOKS/patreon-link.md)
- [Stripe Billing Runbook](docs/RUNBOOKS/stripe-billing.md)

## 🐳 Docker and Tests

There is no production `docker-compose.yml` in this repository. Use the Dockerfile directly or provide your own compose/orchestrator configuration:

```bash
docker build -t api-auth .
docker run --env-file .env -p 8000:8000 api-auth
```

The container entrypoint starts the API server, the email outbox worker, and the Patreon sync worker. Set `PATREON_SYNC_WORKER_ENABLED=0` if the Patreon worker should not start in that container.

For isolated e2e tests with MySQL, Redis, and Mailpit:

```bash
pip install -r requirements-test.txt
bash scripts/run-e2e.sh
```

`scripts/run-e2e.sh` requires `.env.test` and Docker access. It uses [docker-compose.test.yml](docker-compose.test.yml), not a production compose file.

## 🔧 Configuration

See [.env.example](.env.example) for the full documented environment template, including disabled-by-default provider flags, test-only settings, Docker-only settings, and deprecated variables.

Minimum local runtime values:

```bash
# Database
DB_HOST=127.0.0.1
DB_PORT=3306
DB_USER=auth_app
DB_MYSQL_PASSWORD=change-me
DB_NAME=magic_auth

# Redis
REDIS_HOST=127.0.0.1
REDIS_PORT=6379
REDIS_DB=0
DB_REDIS_PASSWORD=

# Auth and API keys
JWT_SECRET_KEY=change-me-generate-with-openssl-rand-hex-32
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=15
API_KEY_PEPPER=change-me-generate-with-openssl-rand-hex-32

# Browser origins
ALLOWED_ORIGINS=http://localhost:3000,http://localhost:5173,http://localhost:4173
```

Provider-specific setup is intentionally documented outside this top-level README:
- Google OAuth: [docs/USAGE/google-oauth/reference.md](docs/USAGE/google-oauth/reference.md) and [docs/RUNBOOKS/google-oauth.md](docs/RUNBOOKS/google-oauth.md)
- Patreon: [docs/USAGE/patreon-link/reference.md](docs/USAGE/patreon-link/reference.md) and [docs/RUNBOOKS/patreon-link.md](docs/RUNBOOKS/patreon-link.md)
- Stripe billing: [docs/USAGE/stripe-billing/reference.md](docs/USAGE/stripe-billing/reference.md) and [docs/RUNBOOKS/stripe-billing.md](docs/RUNBOOKS/stripe-billing.md)
- Email: [docs/USAGE/email/README.md](docs/USAGE/email/README.md) and [docs/RUNBOOKS/email-activation.md](docs/RUNBOOKS/email-activation.md)

Do not place real Google, Patreon, Stripe, Resend, provider-init, S2S bearer, encryption, HMAC, JWT, or API-key secrets in README examples.

## 🆘 Troubleshooting

| Problem | Solution |
|---------|----------|
| Access token expired | Call `/auth/refresh` with the refresh token; if refresh fails, re-authenticate via `/auth/login` |
| Legacy client cannot refresh | Update the client to store/use `refresh_token`; old access/session tokens are not refresh credentials |
| Missing JWT secret | Set `JWT_SECRET_KEY`; non-test runtime fails fast without it |
| API key import/startup error | Set `API_KEY_PEPPER` before importing API-key routes |
| Access denied | Check user group membership, project group access, and project archive state |
| Permission denied | Verify role, permission-group, and direct permission assignments |
| Database errors | Verify MySQL connection, schema, stored procedures, and triggers |
| Cache/session issues | Check Redis connectivity and use `/system/cache/clear` when appropriate |
| Provider feature returns neutral/disabled response | Confirm the feature flag, provider credentials, S2S bearer, encryption/HMAC secrets, and per-group readiness |

### Quick Diagnostics

```bash
curl -H "User-Agent: local-smoke/1.0" http://localhost:8000/system/health
python -c "from src.Util.db import get_connection; print('DB connected')"
python -c "from src.Util.db_config import redis_client; redis_client.ping(); print('Redis OK')"
```

## 🚚 Migration and Rollback Notes

This is a breaking auth-contract deployment:

- Old access/session tokens cannot be used on `/auth/refresh` and may require users to log in again.
- Deployments must set `JWT_SECRET_KEY`; there is no non-test random fallback.
- Refresh/session Redis namespaces include `session:{access_jti}`, `session_full:{access_jti}`, `refresh_family:{family_id}`, `refresh_token:{refresh_jti}`, `refresh_used:{family_id}`, `revoked_family:{family_id}`, `user_sessions:{user_id}`, and `user_refresh_families:{user_id}`.
- Rollback means redeploying the previous release. If needed, clear or let expire the refresh-family Redis namespaces; tokens issued by this true-refresh release are not compatible with the older session-rotation contract.
- Do not re-enable legacy access-token refresh silently unless a separate approved spec changes the auth contract.

## 👨‍💻 Author

**Andrés**
- Website: https://arizmendi.io
- Email: andres@arz.ai

---

**Ready to start?** Check the [Usage Documentation](docs/USAGE/README.md) for complete guides and examples.
