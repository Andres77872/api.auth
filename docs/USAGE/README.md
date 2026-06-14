# Usage Documentation

Practical usage guides and real-world scenarios for the `api.auth` authentication and authorization system.

---

## System Architecture

The system uses a **Groups-of-Groups** access model:

```
USER → USER_GROUP → PROJECT_GROUP → PROJECTS
                  ↘
                    PERMISSION_GROUP → PERMISSIONS
```

- **Users** belong to **User Groups** (organizational teams)
- **User Groups** link to **Project Groups** (project containers)
- **Project Groups** contain related **Projects**
- **User Groups** also have **Permission Groups** assigned
- **Permission Groups** contain individual **Permissions**

---

## Documentation Suites

### Getting Started
- **[Getting Started](getting-started.md)** — First-time setup, bootstrap, env config, registration/login, gotchas

### Authentication & Sessions
- **[Authentication Usage Cases](authentication-usage-cases.md)** — Login (including `remember_me` for a 30-day absolute refresh window), registration, session management, project switching, multi-project workflows, and `POST /auth/validate-api-key` (`X-API-Key` validation). Covers the full 13-endpoint `/auth` surface.
- **[Client Authentication Guide](client-authentication-guide.md)** — Frontend/mobile integration with JS, Python, and React examples

### Domain Suites

| Domain | Entry Point | Covers |
|--------|-------------|--------|
| Users | [users/README.md](users/README.md) | Profile, user types, bulk ops, lifecycle, per-user email management ([email-management.md](users/email-management.md)) |
| Groups | [groups/README.md](groups/README.md) | User groups + project groups (20 admin endpoints), CRUD, live project-session revocation on delete/revoke |
| Projects | [projects/README.md](projects/README.md) | Project CRUD (11 endpoints under `/projects`), access control, member management |
| Permissions | [permissions/README.md](permissions/README.md) | Dual-path auth, permission groups, assignments |
| Roles | [roles/README.md](roles/README.md) | Global role CRUD, permission-group linking, user assignment |
| API Keys | [api-keys/README.md](api-keys/README.md) | Self-service & admin API key lifecycle, `sk_` token format, validation cross-link |
| Email | [email/README.md](email/README.md) | ROOT-only `/admin/email-templates` management, `POST /webhooks/email/resend`, outbox-worker delivery model |
| Google OAuth | [google-oauth/README.md](google-oauth/README.md) | `/auth/google` sign-in, account link/unlink, reauth, provider-init opaque-token model |
| Audit Logs | [audit_logs/README.md](audit_logs/README.md) | Activity feed, API audit logs (`/admin/audit/*`), email delivery logs (`GET /admin/email/logs`), security events, export |

### Admin & System
- **[Admin Usage Cases](admin-usage-cases.md)** — Canonical guide for `/admin/*` dashboard/health/statistics and `/system/*` info/health/ping/cache endpoints, plus cross-domain bulk operations. Note: `GET /admin/activity/{activity_id}` validates the id against `^act-[0-9a-fA-F]{32}$`, returning 400 `INVALID_INPUT` on a malformed id or 404 `RESOURCE_NOT_FOUND` when absent — see [activity detail](admin-usage-cases.md#activity-detail).

### Reference
- **[Error Reference](errors.md)** — Error codes, response shapes, status codes, UUID masking, troubleshooting

---

## API Surface Overview

### Route Families

**167 endpoints across 17 route modules** (see `src/routes/*.py`). Counts below are authoritative as of API 2.2.0.

| Prefix | Module | Count | Auth | Key Endpoints |
|--------|--------|-------|------|---------------|
| `/auth` | `auth.py` | 13 | Mixed | login, platform/login, register, validate, validate-api-key, refresh, logout, switch-project, check-availability, email/verify, password/forgot, password/reset, password/change |
| `/auth/google` | `auth_google.py` | 6 | Mixed | start, callback, link/start, link/finish, reauth/start, unlink |
| `/users` | `users.py` | 18 | Yes | profile, access-summary, list, search, detail, update, status, reset-password, delete, type, plus the 6-endpoint email-management group (`me/emails*`, `{hash}/emails*`) |
| `/users/api-keys` | `user_api_keys.py` | 5 | Session | self-service create, list, get, update, revoke |
| `/api-keys` | `api_keys.py` | 7 | Admin | admin create, list, get, update, revoke, by-user, by-project |
| `/user-types` | `user_types_auth.py` | 10 | Root/Admin | create root/admin, type info, type change, list by type, stats, admin project assignment |
| `/projects` | `projects.py` | 11 | Mixed | CRUD, members, groups, activity, stats, owner (501), archive (501) |
| `/admin/user-groups` | `admin_user_groups.py` | 13 | Admin/manage_users | CRUD, members (single/bulk), project-group links, reverse lookup |
| `/admin/project-groups` | `admin_project_groups.py` | 7 | Admin/manage_roles | CRUD, project links |
| `/roles` | `global_roles.py` | 28 | Mixed | Role/permission-group/permission CRUD, user role assignment, project catalog |
| `/permissions` | `permission_assignments.py` | 17 | Mixed | Assign permission groups to user-groups/users, self-service queries, catalogs |
| `/admin/email-templates` | `email_templates.py` | 6 | Root | list, get, update, preview, send-test, rollback |
| `/webhooks/email` | `email_webhooks.py` | 1 | Svix sig | resend delivery-event webhook |
| `/admin` (audit) | `audit_logs.py` | 6 | Admin/Root | audit/logs, audit/security-events, audit/statistics, audit/export, email/logs, users/{id}/activity |
| `/admin` (dashboard) | `admin_dashboard.py` | 8 | Admin/Root | dashboard/stats, activity, activity/{id}, activity/types, health, users/projects statistics, system/overview |
| `/system` | `system.py` | 7 | Mixed | info, health, ping, cache stats/clear/invalidate |
| `/admin` (bulk) | `bulk_operations.py` | 4 | Admin | users/bulk-update, users/bulk-delete, projects/{hash}/bulk-assign-roles, user-groups/bulk-assign |

**API Version**: 2.2.0 (see `src/main.py`)

**Content-Type**: Almost all POST/PUT/PATCH endpoints use `multipart/form-data`. Exceptions that use a JSON body: `POST /admin/user-groups/{hash}/members/bulk`, `POST /admin/audit/export`, and the `/admin/email-templates` mutations (PUT/preview/send-test/rollback). The `/auth/google` POST endpoints (`start`, `link/*`, `reauth/start`) use JSON or opaque-token/session credentials, and `POST /webhooks/email/resend` reads the raw request body for Svix signature verification.

**User-Agent**: Required on every request. Missing it returns 422.

For detailed endpoint tables, see each suite's `reference.md`.

---

## Quick Start

1. **[Getting Started](getting-started.md)** — Deploy, bootstrap root, create first admin/project/group
2. **[Error Reference](errors.md)** — Understand error responses before integrating
3. **[Authentication Usage Cases](authentication-usage-cases.md)** — Login, register, session lifecycle, `validate-api-key`
4. **[Google OAuth Suite](google-oauth/README.md)** — "Continue with Google" sign-in, account link/unlink, reauth
5. **[Users Suite](users/README.md)** — User management, lifecycle, per-user [email management](users/email-management.md)
6. **[Groups Suite](groups/README.md)** — Understand the access bridge
7. **[Projects Suite](projects/README.md)** — Project CRUD and access
8. **[Permissions Suite](permissions/README.md)** — How permissions resolve (critical: read [resolution.md](permissions/resolution.md))
9. **[Roles Suite](roles/README.md)** — Global role management
10. **[Admin Usage Cases](admin-usage-cases.md)** — Dashboard, monitoring, bulk ops
11. **[Audit Logs Suite](audit_logs/README.md)** — Activity feed, API audit logs, email delivery logs, compliance
12. **[API Keys Suite](api-keys/README.md)** — Self-service & admin API key lifecycle, `sk_` token format
13. **[Email Suite](email/README.md)** — Template management, delivery webhook, outbox-worker model

### Common Tasks

| Task | Guide |
|------|-------|
| Login/Logout | [Authentication - Login](authentication-usage-cases.md#login) |
| Register new user | [Authentication - Registration](authentication-usage-cases.md#registration) |
| Update my profile | [Users - Profile](users/usage.md#profile-operations) |
| View my access | [Users - Access Summary](users/usage.md#access-summary) |
| Change user type | [Users - User Types](users/user-types.md#change-user-type-with-assignment-rules) |
| Add user to a project | [Projects - Scenario 1](projects/scenarios.md#scenario-1-setting-up-a-new-project) |
| Create a new team | [Groups - Usage](groups/usage.md#creating-user-groups) |
| Grant team access to projects | [Groups - Architecture](groups/architecture.md#core-access-model) |
| Set up permissions for a team | [Permissions - Usage](permissions/usage.md#user-group-permission-assignments) |
| Create ROOT/ADMIN users | [Users - User Types](users/user-types.md#create-a-root-user) |
| Check my permissions | [Permissions - Usage](permissions/usage.md#current-user-queries) |
| Create a new role | [Roles - Usage](roles/usage.md#creating-roles) |
| View dashboard stats | [Admin - Dashboard](admin-usage-cases.md#admin-dashboard) |
| Bulk update users | [Users - Bulk Operations](users/bulk-operations.md#bulk-update-users) |
| View activity logs | [Audit Logs - Activity Feed](audit_logs/usage.md#activity-feed-dashboard) |
| View API audit logs | [Audit Logs - API Audit Logs](audit_logs/usage.md#api-audit-logs) |
| Export audit data | [Audit Logs - Export](audit_logs/usage.md#export) |
| Did this email get delivered? | [Audit Logs - Email Delivery Logs](audit_logs/usage.md#email-delivery-logs) (`GET /admin/email/logs`) |
| Create an API key | [API Keys - Usage](api-keys/usage.md) |
| Validate an API key | [Authentication - validate-api-key](authentication-usage-cases.md#validate-api-key) (`POST /auth/validate-api-key`) |
| Manage a user's emails | [Users - Email Management](users/email-management.md) |
| Manage email templates | [Email - Usage](email/usage.md) |
| Sign in with Google | [Google OAuth - Usage](google-oauth/README.md) |

---

## Platform Constraints

| Constraint | Detail |
|------------|--------|
| **Content-Type** | Almost all POST/PUT/PATCH use `multipart/form-data`. JSON-body exceptions: `POST /admin/user-groups/{hash}/members/bulk`, `POST /admin/audit/export`, and the `/admin/email-templates` mutations. The `/auth/google` POSTs use JSON/opaque-token credentials; `POST /webhooks/email/resend` reads the raw body for Svix verification. |
| **User-Agent** | Required on **every** request. Missing it returns 422. |
| **POST body limit** | 8MB maximum. Exceeding it returns 413. |
| **501 stubs** | `PATCH /projects/{hash}/owner` and `PATCH /projects/{hash}/archive` still raise `FeatureNotImplementedError` (501) — there is no API route to flip the archive flag. Note: archive *enforcement* is live (archived projects are excluded from logins/api-keys/tokens/session validation per commit `4e6e5de`); only the toggle endpoints remain stubs. |
| **Rate limiting** | Application-level rate limiting applies to the email surface (e.g. `/users/*/emails*` resend and `/admin/email-templates/*/send-test` via `EmailRateLimiter`, returning 429 + `Retry-After`). Other endpoints have none — protect them at the infrastructure level. |
| **JWT_SECRET_KEY** | Required outside explicit test runtimes. If omitted, startup fails; the runtime does not auto-generate a random secret. |
| **CORS** | Defaults to `http://localhost:3000,http://localhost:5173,http://localhost:4173,https://auth-ui.arz.ai,http://localhost:5177,http://localhost:5183,http://192.168.1.13:5173`. Set `ALLOWED_ORIGINS` in production. |
| **Password validation** | No server-side enforcement. Clients must validate. |
| **First root user** | Must be created directly in the database. No API bootstrap exists. |

---

## Related Documentation

- **[Database Schema](../../schemas/)** — Database structure, relationships, and stored procedures
- **[Email Activation Runbook](../RUNBOOKS/email-activation.md)** — Tokens, outbox, delivery worker, and suppression internals shared by the [Users email-management endpoints](users/email-management.md) and the [Email suite](email/README.md)

---

**Last Updated**: June 2026
**API Version**: 2.2.0
