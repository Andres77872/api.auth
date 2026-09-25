# 🔐 Group-Based Multi-Project Authentication API

`api.auth` is a FastAPI authentication and authorization service for multi-project products. It combines local username/password auth, provider-agnostic OAuth/OIDC sign-in, hierarchical group access, global roles, permission groups, API keys, transactional email, Patreon entitlement linking, and provider-agnostic Stripe billing facts.

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
- HttpOnly, Secure, `SameSite=Strict` cookies for both `session_token` (access alias, path `/`) and `refresh_token` (path `/auth`).
- Multi-project login, project switching, root/admin platform login, strict refresh rotation, logout, and deactivation revocation.
- Self-service password recovery, email verification/activation, multi-email management, and username/email availability checks.
- API-key validation through `POST /auth/validate-api-key` with the `X-API-Key` header.

### 🌐 OAuth Sign-in
- Provider-agnostic OAuth/OIDC sign-in under `/auth/oauth` with built-in adapters for Google, GitHub, Discord, Microsoft, and generic OIDC.
- Provider connections (client id plus encrypted, write-only secret) are managed by root; each project binds a connection and owns its provisioning mode, default user group, and exact-match redirect URI / return-origin allow-lists.
- A project backend lists its enabled providers and mints a single-use init token with its project API key; the project and provisioning group always come from server-side configuration, never from the request.
- Signed-in users can link, re-authenticate with, list, and unlink external identities.
- `GET /admin/oauth/projects/{project_hash}/readiness` explains why a provider is unavailable for a project.
- `/auth/google/*` remains as deprecated aliases onto the same pipeline. See [OAuth docs](docs/USAGE/oauth/README.md) and [Google OAuth docs](docs/USAGE/google-oauth/README.md).

### 👥 Groups, Roles, Permissions, and Projects
- User groups, project groups, and groups-of-groups access control.
- Global role definitions, role assignment, permission-group catalogs, and direct permission-group assignment.
- Project CRUD, member/group/activity/statistics reads, and project archive enforcement in downstream auth checks.
- Project owner/archive API toggle routes exist but currently return 501.

### 🔑 API Keys
- Self-service API keys under `/users/api-keys`.
- Admin API-key management under `/api-keys`.
- Split-token format (`sk_{public_id}.{secret}`), one-time secret reveal, HMAC-SHA-256 verification, and a recent-authentication check on key mutations.
- "Recent authentication" here and on switch-project, OAuth link/unlink, and Patreon link means the session signed in (password, OAuth, or registration) within `OAUTH_RECENT_REAUTH_SECONDS` (300 seconds by default), or completed an OAuth re-authentication (`POST /auth/oauth/{connection}/reauth/start`) within that window. The sign-in time travels in the access token's `auth_time` claim and is kept unchanged by `/auth/refresh` and `/auth/switch-project`, so refreshing never renews it. It is not a password or MFA re-check.

### 📧 Email & Notifications
- Per-user multi-email management and primary-email selection.
- ROOT-only transactional email templates with create/update/disable/preview/send-test/rollback.
- Durable outbox-worker delivery model, Resend webhook ingestion, Mailpit/local capture support, and email delivery audit logs.
- Internal email endpoints for trusted template delivery and delivery-status lookup.

### 💳 Stripe Billing Facts
- Provider-agnostic billing facts with Stripe as the provider adapter.
- Billing groups own per-group encrypted Stripe credentials, per-group project membership, and catalog items.
- Admin billing dashboard API for groups, credentials, capabilities, catalog reconciliation/import/sync, and metrics. It requires the `admin` or `manage_billing` permission; writing credentials also requires a root user.
- S2S billing API for status, public catalog, hosted Checkout (with `Idempotency-Key`), Customer Portal, purchase status, and resync requests, authenticated only by the dedicated `BILLING_S2S_BEARER_TOKEN`. Purchase status is read by `purchase_ref`, scoped to the user and the project the purchase was made in; a purchase appears once its Stripe webhook has been recorded.
- Stripe webhook routes for global migration fallback and per-billing-group webhook secrets, verified with `Stripe-Signature` against the pinned Stripe API version.
- Resync jobs queued by webhooks and the S2S resync route are processed by `src/workers/billing_sync_worker.py`, which the Docker entrypoint starts (see Docker below).

### 🟠 Patreon Entitlements
- Patreon is entitlement/link proof only; it does not issue local sessions, JWTs, refresh tokens, cookies, or API keys.
- Authenticated link lifecycle: request proof, confirm proof, read status, and unlink. Request, confirm, and unlink also require a recent authentication.
- ROOT-only Patreon admin status, entitlement, tier-map, sync-job, webhook, and resync APIs.
- S2S entitlement read/resync routes for trusted consumers, authenticated only by the dedicated `PATREON_S2S_BEARER_TOKEN`.
- Webhook intake at `/webhooks/patreon`, verified with `X-Patreon-Signature` over the raw body.
- The Patreon sync worker drains webhook- and admin-triggered resync jobs; the Docker entrypoint starts it.
- Every Patreon feature flag defaults to off; disabled surfaces answer with neutral or disabled responses.

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

`src/__init__.py` loads the project `.env` before runtime imports; variables already exported in the environment take precedence. Use `scripts/recreate_database.py` only when you intentionally want to drop and rebuild `magic_auth`; it is destructive and asks for confirmation.

To bring an existing database up to the canonical schema without dropping anything, review and then apply the additive catch-up:

```bash
python scripts/schema_sync.py --env-file .env --dry-run
python scripts/schema_sync.py --env-file .env --apply
```

For an isolated development tenant, copy `.env.dev.example` to `.env.dev` and run `python scripts/dev_env_setup.py --env-file .env.dev --dry-run`, then `--apply`. It seeds a local project, its default groups, and a Google OAuth connection and binding, and it refuses to run unless the database host is a loopback address and every configured URL is local.

The canonical database scripts currently seed a legacy root row whose SHA-256
password hash is incompatible with the active Argon2id-only verifier. Their
completion message also prints a different password. Before trying to log in,
follow the
[first-root repair step](docs/USAGE/getting-started.md#first-root-bootstrap-and-current-seed-caveat);
neither printed/seeded default is a valid current login.

## 📡 API Surface

The app currently registers **246 route-module endpoint methods across 28 `src/routes/*.py` modules** for API version `2.2.0`. This count treats each method/path pair as one endpoint and excludes FastAPI's built-in routes plus every route declared directly in `src/main.py`.

| Surface | Prefix | Module | Count | Contract |
|---------|--------|--------|-------|----------|
| Authentication | `/auth` | `auth.py` | 13 | Session, refresh token, API-key validation |
| OAuth | `/auth/oauth` | `auth_oauth.py` | 9 | Provider-agnostic OAuth: init token, start, callback, link, reauth, unlink |
| Google OAuth (deprecated aliases) | `/auth/google` | `auth_google.py` | 5 | Aliases onto the OAuth pipeline with connection `google` |
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
| Admin OAuth | `/admin/oauth` | `admin_oauth.py` | 20 | Provider catalog, connections, write-only credentials, project bindings, URL allow-lists, readiness |
| Root assistant | `/admin/assistant/ws` | `assistant.py` | 0 | One root-only WebSocket endpoint; excluded from HTTP operation counts |
| Billing Internal | `/internal/.../billing` | `internal_billing.py` | 6 | S2S billing facts, catalog, Checkout, Portal, resync |
| Stripe Webhooks | `/webhooks/stripe` | `stripe_webhooks.py` | 2 | Raw Stripe webhook intake |
| Admin Patreon | `/admin/patreon` | `admin_patreon.py` | 8 | ROOT-only Patreon status and operations |
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
- Swagger UI: `/docs` — tags collapsed by default, with a filter box.
- ReDoc: `/redoc` — tags grouped into Sign-in, Users and Access, Billing, Integrations, Email, and Operations.
- OpenAPI document: `/openapi.json`
- Documentation wiki: `/documentation` — the `docs/` tree rendered with navigation, full-text search (`Ctrl K` / `⌘K`), per-page outline, and light/dark themes matching the admin console. Renderer: `src/Util/docs_site/`.
- Raw markdown documentation: add `?format=raw` to any `/documentation/...` page; `/documentation?format=raw` lists every page.

The OpenAPI document is generated from the code. Its description is [src/README.md](src/README.md); tag descriptions, ReDoc tag groups, security schemes, and the shared `ErrorResponse` schema live in [src/Util/openapi_metadata.py](src/Util/openapi_metadata.py); every operation's own description is its route docstring. It declares four security schemes:

| Scheme | Credential | Used by |
|--------|------------|---------|
| `HTTPBearerOrCookie` | Access JWT as `Authorization: Bearer ...` or the `session_token` cookie | Authenticated user and admin routes |
| `ProjectApiKey` | `X-API-Key: sk_{public_id}.{secret}` | `POST /auth/validate-api-key` (OAuth init/providers declare the same header as a parameter) |
| `BillingS2SBearer` | Dedicated `BILLING_S2S_BEARER_TOKEN` | Billing internal routes |
| `PatreonS2SBearer` | Dedicated `PATREON_S2S_BEARER_TOKEN` | Patreon internal routes |

Webhooks are verified by provider signature headers over the raw body and declare no security scheme. [tests/integration/test_openapi_contract.py](tests/integration/test_openapi_contract.py) fails if an operation loses its description or tag, or references an undefined scheme.

## 💡 API Usage

### Auth Token Contract

This release uses a **two-token model**:

- `access_token`: short-lived JWT used for protected API requests, `/auth/validate`, `/auth/logout`, and `/auth/switch-project`.
- `refresh_token`: 72-hour sliding JWT by default, or a 30-day absolute JWT when `remember_me=true`; it is used by `/auth/refresh` (and required alongside the access token by `/auth/switch-project`) and returned in the JSON body and as an HttpOnly Secure `refresh_token` cookie scoped to `/auth`.
- `session_token`: deprecated compatibility alias for `access_token` in response bodies and the access cookie.

`POST /auth/refresh` rejects legacy access/session tokens. Do not send `Authorization: Bearer <access_token>` to refresh; send the refresh token through the `refresh_token` cookie or explicit `refresh_token` form/body field.

Access JWT signature, `exp`, `type`, `jti`, `session_id`, `family_id`, and server-side Redis session/family state are enforced before a request is trusted.

Project-scoped consumer login, `POST /auth/refresh`, `GET /auth/validate`, and
consumer `POST /auth/validate-api-key` may also return a provider-neutral
subscription `plan`. It is resolved at response time from project → billing group
and is not stored in JWT claims, cookies, or Redis auth state. The switch-project
response body does not include it; validate the newly issued access token when the
client needs the plan for the new project.

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
- POST requests whose `Content-Length` exceeds 8 MiB are rejected with `413`.
- Form fields (`application/x-www-form-urlencoded` or `multipart/form-data`): login, platform login, registration, refresh, switch-project, availability checks, the OAuth `form_post` callback, and most older CRUD/admin mutations, including `/admin` bulk operations (list fields are repeated).
- JSON or form: email verification, forgot password, and reset password.
- JSON: OAuth init/start, Patreon link request/confirm, OAuth administration, admin Patreon resync, internal billing, internal Patreon resync, internal email, email templates, audit export, and the user-group bulk assignment. Admin billing mixes JSON and form per route.
- Webhook endpoints consume raw provider-signed request bodies.
- Emailed links point at `<public base>/auth/email/verify?token=...`, `/auth/password/reset?token=...`, and `/auth/patreon/link/confirm?token=...`. The API serves only `POST` on those paths, so the frontend must host the `GET` pages that submit the token.
- Responses are JSON and use Pydantic response validation or explicit safe DTO serialization; the CSV audit export is the exception.

### Response Shape

Many first-party responses, especially older CRUD and auth routes, follow this shape:

```json
{
  "success": true,
  "message": "Operation completed successfully",
  "data": {}
}
```

Admin read views return their own objects (for example `{logs, pagination, filters, generated_at}` from the audit routes), and webhook, internal, and OAuth routes return narrower provider-safe DTOs or empty success responses. Each operation's OpenAPI response schema is authoritative.

Errors use one envelope (the `ErrorResponse` schema in OpenAPI):

```json
{
  "status": "error",
  "error": {
    "code": "AUTH_1001",
    "category": "authentication",
    "message": "Invalid username or password"
  }
}
```

Request-validation failures return `400` with code `VAL_3001` and `error.details.validation_errors`; FastAPI's default `422 {"detail": [...]}` body is never produced. `422` is used only for deliberate route rejections, such as a missing `User-Agent` or semantically invalid internal email and billing requests. See the [Error Reference](docs/USAGE/errors.md) for every code.

## 📚 Documentation

### Usage Guides

| Document | Description |
|----------|-------------|
| [Getting Started](docs/USAGE/getting-started.md) | Installation, env vars, first run |
| [Authentication](docs/USAGE/authentication-usage-cases.md) | Login, sessions, project switching |
| [Client Authentication Guide](docs/USAGE/client-authentication-guide.md) | Browser, mobile, and service integration patterns |
| [OAuth Sign-in](docs/USAGE/oauth/README.md) | Provider-agnostic sign-in: connections, project bindings, readiness, admin API |
| [Google OAuth/OIDC](docs/USAGE/google-oauth/README.md) | Deprecated `/auth/google/*` aliases and the `GOOGLE_OAUTH_*` environment configuration |
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
- [OAuth Runbook](docs/RUNBOOKS/oauth.md)
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

The container entrypoint ([scripts/docker-entrypoint.sh](scripts/docker-entrypoint.sh)) starts the API server, the email outbox worker, the Patreon sync worker, and the billing sync worker. Set `PATREON_SYNC_WORKER_ENABLED=0` or `BILLING_SYNC_WORKER_ENABLED=0` if that worker should not start in the container, for example when it runs as its own deployment.

The billing sync worker processes queued billing resync jobs and runs billing retention purges only while billing sync is enabled (`BILLING_SYNC_ENABLED` or `STRIPE_SYNC_ENABLED`); otherwise it only writes its heartbeat. Its heartbeat id defaults to `container-<HOSTNAME>-billing` (override with `BILLING_WORKER_ID`).

For routine host-side tests, use the serial batch runner:

```bash
bash scripts/run-test-batches.sh
bash scripts/run-test-batches.sh --layer unit
bash scripts/run-test-batches.sh --target tests/integration/test_slice2_auth_login.py
```

It runs each `unit`, `integration`, and `static` file in a separate pytest
process, excluding E2E, `real_db`, and live-provider tests. Defaults enforce a
1,536 MiB address-space cap, a 60-second per-test timeout, and a 180-second
per-file timeout. These limits may be lowered with `PYTEST_MEM_LIMIT_MB`,
`PYTEST_TIMEOUT_SECONDS`, and `TEST_BATCH_TIMEOUT_SECONDS`; certified runs reject
zero, malformed, or larger values. Coverage aggregation has its own 1,536 MiB
and 300-second ceilings, configurable downward with `COVERAGE_MEM_LIMIT_MB` and
`COVERAGE_TIMEOUT_SECONDS`. Coverage shards are unique per file and combined
into reports under `test-results/host/`. Unexpected skips and empty
non-`real_db` files fail closed. A repository-wide workflow lock prevents
overlapping host, Docker, or coverage-merge runs from defeating the memory limit
or replacing one another's artifacts.

For isolated e2e tests with MySQL, Redis, and Mailpit:

```bash
bash scripts/run-e2e.sh
```

`scripts/run-e2e.sh` requires `.env.test` and Docker access. It uses
[docker-compose.test.yml](docker-compose.test.yml), not a production compose
file. Every invocation:

- removes the previous test project and database volume;
- builds the test image before starting services;
- starts resource-limited MySQL, Redis, and Mailpit containers;
- runs each E2E file and each `real_db` integration file serially in one
  disposable runner container;
- writes cumulative branch-coverage reports under `test-results/e2e/`; and
- removes containers, networks, and volumes on both success and failure,
  propagating a teardown failure even when the tests themselves passed.

For a focused workflow check against the same fresh Docker stack:

```bash
bash scripts/run-e2e.sh \
  --target tests/e2e/test_full_chain_lifecycle.py \
  -- -k test_full_register_login_access_chain_live_redis
```

The official Docker run disables all live Patreon and Stripe flags. External
provider smoke tests remain explicit manual opt-ins and are not part of the
routine E2E gate.

A certifiable full host or E2E run accepts no pytest filters from
`PYTEST_ADDOPTS`; focused E2E filters must use the explicit `--target ... --`
form above. Ambient pytest plugin injection and `PYTHONPATH` are disabled, while
the exact pinned coverage, asyncio, and AnyIO plugins are loaded explicitly.
Each workflow records exact batch/JUnit dispositions, enforced resource limits, a
before/after fingerprint of source, tests, schemas, scripts, documentation,
test configuration, and dependency inputs, an independently validated fingerprint
of the installed exact dependency versions, plus the SHA-256 of its raw coverage
database. The Docker result also records the resolved image IDs for the runner,
MySQL, Redis, and Mailpit.

After both complete full runs succeed against the same source state, combine
their branch data without deleting either input:

```bash
bash scripts/combine-test-coverage.sh
```

The combined text, XML, JSON, and HTML reports are written under
`test-results/combined/`. The merge refuses focused or failed workflow
artifacts, duplicate or inconsistent summary fields, coverage hash mismatches,
source changes during either run, stale results from a different current source
state, and merges attempted while another test workflow holds the shared lock.

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

`ALLOWED_ORIGINS` is optional: when unset, CORS, early-reject responses, and
email-link origin validation share the built-in `DEFAULT_ALLOWED_ORIGINS` list in
[src/Util/auth_constants.py](src/Util/auth_constants.py). That list holds
localhost/LAN development origins plus the hosted auth UI origin
`https://auth-ui.arz.ai`, so set the variable explicitly in every deployment.

OAuth configuration has two sources, selected by `OAUTH_CONFIG_SOURCE`:

- `env` (default): the historical single Google connection configured by the `GOOGLE_OAUTH_*` and `PROVIDER_INIT_*` variables.
- `db`: connections, project bindings, and URL allow-lists live in the database and are managed through `/admin/oauth/*`. Connection secrets are encrypted at rest, so `OAUTH_SECRET_ENCRYPTION_KEY`, `OAUTH_SECRET_ENCRYPTION_KEY_ID`, and `OAUTH_SECRET_HMAC_KEY` become required. Move an existing deployment with `scripts/schema_sync.py` and `scripts/migrations/oauth_env_import.py`, as described in the [OAuth runbook](docs/RUNBOOKS/oauth.md).

Never change the OAuth peppers (`OAUTH_*_PEPPER` or their `GOOGLE_OAUTH_*_PEPPER` predecessors) on a live deployment: they key every linked identity.

Provider-specific setup is intentionally documented outside this top-level README:
- OAuth sign-in: [docs/USAGE/oauth/reference.md](docs/USAGE/oauth/reference.md) and [docs/RUNBOOKS/oauth.md](docs/RUNBOOKS/oauth.md)
- Google OAuth (deprecated aliases, `env` source): [docs/USAGE/google-oauth/reference.md](docs/USAGE/google-oauth/reference.md) and [docs/RUNBOOKS/google-oauth.md](docs/RUNBOOKS/google-oauth.md)
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
| Permission denied | Verify the active guard first. Session/route enforcement is role-derived; user-group/direct assignments are visible through inspection APIs but are not part of the auth-time permission set. |
| Database errors | Verify MySQL connection, schema, stored procedures, and triggers |
| Cache/session issues | Check Redis connectivity first. `POST /system/cache/clear` (root/admin) deletes every cached access session, so every user, including the caller, must refresh or sign in again; prefer `/system/cache/invalidate/user/{user_hash}` for one user |
| Provider feature returns neutral/disabled response | Confirm the feature flag, provider credentials, S2S bearer, encryption/HMAC secrets, and per-group readiness |
| OAuth provider button missing or failing | Call `GET /admin/oauth/projects/{project_hash}/readiness`; it names the failing layer (global flag, catalog, connection, credentials, binding, project, allow-lists, default group) |
| `400` with `VAL_3001` | Read `error.details.validation_errors`; the request did not match the operation's documented parameters or body |

### Quick Diagnostics

Detailed system diagnostics require a valid access session; `/ping` and
`/system/ping` remain public and touch no database, Redis, or provider, so use
them for container and load-balancer probes. `GET /system/health` answers `200`
even when a component is degraded: read its `status` field (`healthy` or
`degraded`) and per-component entries such as `email_worker`.

```bash
curl http://localhost:8000/system/health \
  -H "Authorization: Bearer ${ACCESS_TOKEN}" \
  -H "User-Agent: local-smoke/1.0"
python -c "from src.Util.db_config import get_connection; get_connection().cursor().execute('SELECT 1'); print('DB connected')"
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

### Root AI assistant

The dashboard includes a root-only floating Deep Agents assistant with ten domain
skills, specialist subagents, planning, questions and explicit approval for app
changes. Read tools are enabled by default; write tools require a master switch
and individual activation. Ollama, OpenAI-compatible and Anthropic profiles,
conversations, activity and usage are persisted on the backend. WebSocket event
replay restores background generations after browser reconnects.

See [assistant setup and protocol](docs/ASSISTANT.md),
[research](docs/ASSISTANT_RESEARCH.md), and
[project review findings](docs/ASSISTANT_PROJECT_REVIEW.md).
