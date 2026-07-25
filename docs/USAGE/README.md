# Usage Documentation

Practical integration, administration, and operations documentation for
`api.auth` API version `2.2.0`.

## Start Here

1. [Getting Started](getting-started.md) — local setup, required configuration,
   root bootstrap, and the first authenticated request.
2. [Authentication Usage Cases](authentication-usage-cases.md) — login,
   registration, token rotation, validation, project switching, password/email
   flows, and API-key validation.
3. [Client Authentication Guide](client-authentication-guide.md) — browser,
   mobile, and service integration patterns.
4. [Error Reference](errors.md) — response envelopes, status codes, and
   operator diagnostics.

## Access Model

```text
USER -> USER_GROUP -> PROJECT_GROUP -> PROJECTS
                 \-> PERMISSION_GROUP -> PERMISSIONS
```

Project reach and action permission are related but distinct:

- users reach projects through user-group to project-group links;
- global roles attach permission groups to a user;
- permission groups may also be assigned directly to users or user groups;
- the permissions suite documents the current difference between auth-time and
  inspection-time resolution.

## Domain Suites

| Domain | Entry point | Current scope |
| --- | --- | --- |
| Users | [users/README.md](users/README.md) | Profile, lifecycle, scoped administration, hard-delete guardrails, multi-email management |
| Groups | [groups/README.md](groups/README.md) | User groups, project groups, membership, access links, revocation |
| Projects | [projects/README.md](projects/README.md) | Project CRUD, members, groups, activity, statistics, current 501 stubs |
| Roles | [roles/README.md](roles/README.md) | Global roles, permission groups, permissions, project role catalogs |
| Permissions | [permissions/README.md](permissions/README.md) | Assignment, resolution paths, self-inspection, project catalogs |
| API keys | [api-keys/README.md](api-keys/README.md) | Self-service/admin lifecycle and split-token validation |
| Email | [email/README.md](email/README.md) | Template lifecycle, internal delivery, outbox worker, provider webhook |
| Google OAuth | [google-oauth/README.md](google-oauth/README.md) | Provider-init mediated OAuth/OIDC login/link/reauth |
| Patreon | [patreon-link/README.md](patreon-link/README.md) | Entitlement-only link proof, admin, S2S, webhook, sync |
| Stripe billing | [stripe-billing/README.md](stripe-billing/README.md) | Billing groups, centralized catalog, per-account credentials, S2S, webhooks |
| Audit logs | [audit_logs/README.md](audit_logs/README.md) | API audit, activity, security events, email logs, export |

## Admin and Operations

- [Admin Usage Cases](admin-usage-cases.md) — dashboard, statistics, activity,
  protected system health/info, cache operations, and bulk operations.
- [Google OAuth Runbook](../RUNBOOKS/google-oauth.md)
- [Email Activation Runbook](../RUNBOOKS/email-activation.md)
- [Patreon Link Runbook](../RUNBOOKS/patreon-link.md)
- [Stripe Billing Runbook](../RUNBOOKS/stripe-billing.md)

## API Surface

The application currently registers **217 method/path operations across 25
`src/routes/*.py` modules**. This inventory excludes FastAPI's built-in
`/docs`, `/redoc`, and `/openapi.json` routes plus routes implemented directly
in `src/main.py`.

| Surface | Prefix | Module | Operations | Authority |
| --- | --- | --- | ---: | --- |
| Authentication | `/auth` | `auth.py` | 13 | Mixed public/session |
| Google OAuth | `/auth/google` | `auth_google.py` | 6 | Public OAuth + session |
| Patreon link | `/auth/patreon` | `auth_patreon.py` | 4 | Session + recent reauth |
| Users | `/users` | `users.py` | 19 | Session/scoped admin/root |
| User API keys | `/users/api-keys` | `user_api_keys.py` | 5 | Session + step-up |
| Admin API keys | `/api-keys` | `api_keys.py` | 7 | Admin/root |
| User types | `/user-types` | `user_types_auth.py` | 10 | Admin/root |
| Projects | `/projects` | `projects.py` | 11 | Mixed session/admin |
| User groups | `/admin/user-groups` | `admin_user_groups.py` | 13 | Admin/permission |
| Project groups | `/admin/project-groups` | `admin_project_groups.py` | 7 | Admin/permission |
| Roles | `/roles` | `global_roles.py` | 28 | Mixed session/admin |
| Permission assignments | `/permissions` | `permission_assignments.py` | 17 | Mixed session/admin |
| Admin billing | `/admin/billing` | `admin_billing.py` | 22 | Admin/manage_billing; credentials root-only |
| Billing internal | `/internal/.../billing` | `internal_billing.py` | 6 | Dedicated billing S2S bearer |
| Stripe webhooks | `/webhooks/stripe` | `stripe_webhooks.py` | 2 | Stripe signature |
| Admin Patreon | `/admin/patreon` | `admin_patreon.py` | 7 | Root |
| Patreon internal | `/internal/users/{user_hash}/entitlements` | `internal_patreon.py` | 2 | Dedicated Patreon S2S bearer |
| Patreon webhook | `/webhooks/patreon` | `patreon_webhooks.py` | 1 | Patreon signature |
| Internal email | `/internal/email` | `internal_email.py` | 3 | Root access session |
| Email templates | `/admin/email-templates` | `email_templates.py` | 8 | Root |
| Email webhook | `/webhooks/email` | `email_webhooks.py` | 1 | Svix signature |
| Audit logs | `/admin/audit`, `/admin/email/logs` | `audit_logs.py` | 6 | Admin/root |
| Admin dashboard | `/admin` | `admin_dashboard.py` | 8 | Admin/root |
| Bulk operations | `/admin` | `bulk_operations.py` | 4 | Admin/permission |
| System | `/system` | `system.py` | 7 | Mixed session/admin/public ping |

The root [README](../../README.md) explains the count boundary and test
workflows. Endpoint-level contracts live in each domain suite and in the
running OpenAPI document.

## Platform-Wide Contracts

| Contract | Current behavior |
| --- | --- |
| User agent | Every request requires a `User-Agent`; missing returns `422`. Standard `curl` already sends one. |
| POST size | Request middleware rejects POST bodies over 8 MiB with `413`. |
| Content types | Older/admin mutations are mainly form-encoded. Provider/internal/template/audit-export and selected bulk routes use JSON; webhooks use signed raw bytes. |
| Session tokens | Access and refresh tokens are distinct. `session_token` is a deprecated access-token alias, never a refresh credential. |
| Billing plan projection | Project-scoped consumer login, validation, and consumer API-key validation may expose a provider-neutral subscription `plan`; it is not stored in JWT/cookie/Redis auth state. Current refresh and switch-project response bodies omit it. |
| System details | `/system/info` and `/system/health` require a valid access session. `/ping` and `/system/ping` are public. |
| Project stubs | `PATCH /projects/{project_hash}/owner` and `/archive` currently return `501`; archive enforcement elsewhere is active. |
| CORS | Set `ALLOWED_ORIGINS` explicitly. `.env.example` is the maintained deployment template; do not depend on development fallback origins. |
| First root | There is no unauthenticated API bootstrap. The canonical SQL currently seeds a legacy SHA-256 root credential that the Argon2id-only verifier rejects, while the Python bootstrap scripts print a different password. Rotate that row to Argon2id before first login, or omit the seed and create the root through the application helper. |

## Common Tasks

| Task | Guide |
| --- | --- |
| Log in, refresh, or log out | [Authentication](authentication-usage-cases.md) |
| Integrate a browser/mobile client | [Client guide](client-authentication-guide.md) |
| Manage a user's lifecycle | [Users usage](users/usage.md) |
| Manage email addresses | [User email management](users/email-management.md) |
| Grant a team project access | [Groups usage](groups/usage.md) |
| Check permission resolution | [Permission resolution](permissions/resolution.md) |
| Manage billing groups/catalog | [Stripe billing reference](stripe-billing/reference.md) |
| Link Patreon entitlement | [Patreon scenarios](patreon-link/scenarios.md) |
| Inspect or export audit events | [Audit logs usage](audit_logs/usage.md) |
| Diagnose system health | [Admin usage](admin-usage-cases.md#system-health--metrics) |

## Documentation Maintenance

Treat code and runtime configuration as authoritative:

- route registration: `src/main.py` and decorators in `src/routes/*.py`;
- request/response models: `src/Util/Models.py`;
- environment template: `.env.example`;
- schema: `schemas/`;
- operational commands: `scripts/`, Dockerfiles, and test configuration.

When a route, model, feature flag, or workflow changes, update the relevant
domain suite, the route inventory above, and the root/source READMEs in the same
change. Documentation consistency checks live in
`tests/static/test_documentation_consistency.py`.
