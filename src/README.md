# `api.auth` API Description

FastAPI authentication and authorization service for multi-project products.

The canonical project overview, setup instructions, test workflows, and
configuration notes live in the repository [README](../README.md). The rendered
operator and integration guides are served at `/documentation` and maintained
under [`docs/USAGE`](../docs/USAGE/README.md).

## Access Model

```text
USER -> USER_GROUP -> PROJECT_GROUP -> PROJECTS
                 \-> PERMISSION_GROUP -> PERMISSIONS
```

- `root` users have global administrative scope.
- `admin` users operate within their assigned project scope.
- `consumer` users receive project reach through user-group to project-group
  links.
- Global roles, permission groups, and direct permission-group assignments are
  separate from project reach.

## Authentication Contract

- Project login: `POST /auth/login`
- Root/admin platform login: `POST /auth/platform/login`
- Session validation: `GET /auth/validate`
- Refresh-token rotation: `POST /auth/refresh`
- API-key validation: `POST /auth/validate-api-key`
- Google OAuth/OIDC: `/auth/google/*`
- Patreon account linking: `/auth/patreon/*` (entitlement link only; never a
  login provider)

Protected requests use a short-lived access JWT. Refresh continuity uses a
strictly rotated refresh-token family: 72-hour sliding by default, or a 30-day
absolute window with `remember_me=true`. `session_token` remains a deprecated
response/cookie alias for the access token.

Project-scoped login, validation, and API-key validation responses may include a
provider-neutral subscription `plan` projection. It is resolved from the
session project's billing group and is never stored in JWT claims, cookies, or
Redis session payloads. Platform sessions without a project omit it.

## Current Route Modules

API version `2.2.0` registers 217 method/path operations across 25 modules in
`src/routes`:

| Module | Operations | Surface |
| --- | ---: | --- |
| `auth.py` | 13 | Local login, registration, refresh, validation, password/email flows |
| `auth_google.py` | 6 | Google OAuth/OIDC |
| `auth_patreon.py` | 4 | Patreon link proof/status/unlink |
| `users.py` | 19 | Profile, lifecycle, email management, scoped administration |
| `user_api_keys.py` | 5 | Self-service API keys |
| `api_keys.py` | 7 | Admin API keys |
| `user_types_auth.py` | 10 | Root/admin user-type workflows |
| `projects.py` | 11 | Project CRUD and operational views |
| `admin_user_groups.py` | 13 | User groups and access links |
| `admin_project_groups.py` | 7 | Project groups and project links |
| `global_roles.py` | 28 | Roles, permission groups, permissions, catalogs |
| `permission_assignments.py` | 17 | Direct/group assignments and lookups |
| `admin_billing.py` | 22 | Billing groups, credentials, catalog, metrics |
| `internal_billing.py` | 6 | Billing S2S facts, catalog, Checkout, Portal, resync |
| `stripe_webhooks.py` | 2 | Global fallback and per-billing-group Stripe webhooks |
| `admin_patreon.py` | 7 | Root-only Patreon operations |
| `internal_patreon.py` | 2 | Patreon entitlement S2S read/resync |
| `patreon_webhooks.py` | 1 | Patreon webhook |
| `internal_email.py` | 3 | Root-gated internal email operations |
| `email_templates.py` | 8 | Root-only template lifecycle |
| `email_webhooks.py` | 1 | Resend/Svix webhook |
| `audit_logs.py` | 6 | Audit, security events, export, email logs |
| `admin_dashboard.py` | 8 | Dashboard, health, activity, statistics |
| `bulk_operations.py` | 4 | Bulk user/group/role operations |
| `system.py` | 7 | Authenticated details, public ping, cache operations |

The count excludes FastAPI's built-in documentation/OpenAPI routes and the five
top-level routes implemented directly in `src/main.py`.

## Request-Wide Constraints

- Every request must carry a `User-Agent` header.
- POST bodies are limited to 8 MiB by request middleware.
- Most older mutation endpoints use form fields; newer provider, internal,
  template, audit-export, and selected bulk endpoints use JSON or signed raw
  request bodies.
- `GET /system/info` and `GET /system/health` require a valid access session.
  `/ping` and `/system/ping` are public liveness endpoints.
- Billing and Patreon internal routes use dedicated S2S bearer credentials, not
  browser cookies, user access JWTs, or regular API keys.

## Documentation

- [Usage documentation](../docs/USAGE/README.md)
- [Operational runbooks](../docs/RUNBOOKS)
- [Database schema documentation](../schemas/docs/README.md)
- Swagger UI: `/docs`
- ReDoc: `/redoc`
- Rendered Markdown: `/documentation`
- Raw Markdown: append `?format=raw` to a `/documentation` URL
