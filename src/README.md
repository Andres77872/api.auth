# `api.auth`

FastAPI authentication and authorization service for multi-project products:
local and OAuth sign-in, access/refresh sessions, hierarchical group access,
global roles and permission groups, API keys, transactional email, Patreon
entitlement links, and provider-agnostic billing facts.

This text is the OpenAPI description served at `/docs` (Swagger UI) and
`/redoc`. ReDoc groups the tags into sections; in Swagger UI use the filter box
to find a tag. Integration guides are rendered at
[/documentation](/documentation) — append `?format=raw` to any documentation
URL for plain Markdown.

## Credentials

| Credential | How to send it | Scheme in this document | Accepted by |
| --- | --- | --- | --- |
| Access token (JWT) | `Authorization: Bearer <access_token>`, or the HttpOnly `session_token` cookie | `HTTPBearerOrCookie` | Every route that lists this scheme |
| Refresh token (JWT) | HttpOnly `refresh_token` cookie (path `/auth`) or a `refresh_token` form field; `Authorization` is ignored | none | `POST /auth/refresh`, and `POST /auth/switch-project` alongside the access token |
| API key | `X-API-Key: sk_{public_id}.{secret}` | `ProjectApiKey`, or a declared `X-API-Key` header parameter | `POST /auth/validate-api-key`, `POST /auth/oauth/init`, `GET /auth/oauth/providers` |
| OAuth init token | `init_token` field of the JSON body | none | `POST /auth/oauth/start` |
| Billing S2S bearer | `Authorization: Bearer <token>` | `BillingS2SBearer` | `/internal/users/{user_hash}/billing…`, `/internal/projects/{project_hash}/billing/catalog` |
| Patreon S2S bearer | `Authorization: Bearer <token>` | `PatreonS2SBearer` | `/internal/users/{user_hash}/entitlements…` |
| Webhook signature | `Stripe-Signature`, `X-Patreon-Signature`, or `svix-id` + `svix-timestamp` + `svix-signature`, computed over the raw body | none | `/webhooks/stripe…`, `/webhooks/patreon`, `/webhooks/email/resend` |

An operation without a security scheme is either public (login, registration,
availability checks, password recovery, email activation, OAuth start and
callback, `/ping`, `/system/ping`, documentation) or authenticates with one of
the credentials above that OpenAPI cannot express as a scheme. The S2S bearers
are separate secrets: a user access token or API key is never accepted in their
place.

## Session Contract

- **Access token**: short-lived JWT (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`, default
  15). Signature, expiry, token type, and the server-side Redis session and
  refresh family are all checked before a request is trusted.
- **Refresh token**: a separate JWT that `POST /auth/refresh` rotates strictly,
  returning a new pair; `POST /auth/switch-project` also requires it. Families last 72 hours, sliding,
  by default, or 30 days, absolute, when the login sent `remember_me=true`.
  Re-using a spent refresh token always fails; outside a short grace window it
  also revokes the whole family. An access token is never a refresh credential.
- **`session_token`**: deprecated alias of `access_token` in response bodies and
  the name of the access-token cookie.
- Logout revokes the current session; deactivating a user revokes all of that
  user's sessions and refresh families.
- Project-scoped consumer login, `GET /auth/validate`, and consumer
  `POST /auth/validate-api-key` may include a provider-neutral subscription
  `plan`, resolved at response time from the project's billing group. It is never
  stored in JWT claims, cookies, or Redis session state. Platform sessions
  without a project, refresh, and switch-project responses omit it.

## Access Model

```text
USER -> USER_GROUP -> PROJECT_GROUP -> PROJECTS
                 \-> PERMISSION_GROUP -> PERMISSIONS
```

- `root` users have global administrative scope.
- `admin` users operate within their assigned project scope.
- `consumer` users reach projects through user-group to project-group links.
- Global roles, permission groups, and direct permission-group assignments are
  separate from project reach.

## Request Conventions

- Every request must carry a `User-Agent` header. Without one the API answers
  `422` with a short `{"status": "Error", "action": …}` body before any route
  runs. Browsers and `curl` send one automatically.
- POST requests whose `Content-Length` exceeds 8 MiB are rejected with `413`.
- Form fields (`application/x-www-form-urlencoded` or `multipart/form-data`):
  login, platform login, registration, refresh, switch-project, availability
  checks, the OAuth `form_post` callback, and most older CRUD and admin
  mutations, including `/admin` bulk operations (list fields are repeated).
- JSON or form: email verification, forgot password, and reset password.
- JSON: OAuth init and start, Patreon link request and confirm, OAuth
  administration, email templates, internal email, internal billing, audit
  export, and the user-group bulk assignment. Admin billing mixes JSON and form
  per route.
- Webhooks take the provider's raw signed body.
- Each operation's request body in this document states which applies.
- Browser origins must be listed in `ALLOWED_ORIGINS` for CORS with credentials.

## Responses and Errors

Many older CRUD and auth routes answer with a success envelope:

```json
{"success": true, "message": "Operation completed successfully", "data": {}}
```

Admin read views, webhook, S2S, and OAuth routes return their own typed
objects instead; each operation's response schema is authoritative.

Errors share one envelope, documented as the `ErrorResponse` schema:

```json
{"status": "error", "error": {"code": "AUTH_1001", "category": "authentication", "message": "Invalid username or password"}}
```

- `error.code` is an `ErrorCode` value in `CATEGORY_NNNN` form.
- Request validation failures return `400` with code `VAL_3001` and a
  `details.validation_errors` list. FastAPI's default `422` validation response
  is not used.
- Rate-limited routes return `429`; honour `Retry-After` when present.
- `DEBUG_MODE=true` adds diagnostic `details` and a `trace`; never enable it in
  production.

The [error reference](/documentation/USAGE/errors.md) lists every code.

## Route Modules

API version `2.2.0` registers 245 method/path operations across 27 modules in
`src/routes`, each under one tag:

| Module | Tag | Operations | Surface |
| --- | --- | ---: | --- |
| `auth.py` | Authentication | 13 | Local login, registration, refresh, validation, password and email flows |
| `auth_oauth.py` | OAuth | 9 | Provider-agnostic sign-in: init, providers, start, callback, link, reauth, unlink, links |
| `auth_google.py` | Google OAuth | 5 | Deprecated `/auth/google/*` aliases onto the OAuth pipeline |
| `auth_patreon.py` | Patreon Link | 4 | Patreon link proof, status, and unlink |
| `users.py` | User Management | 19 | Profile, lifecycle, email management, scoped administration |
| `user_api_keys.py` | API Keys - User | 5 | Self-service API keys |
| `api_keys.py` | API Keys - Admin | 7 | Admin API keys |
| `user_types_auth.py` | User Type Management | 10 | Root/admin user-type workflows |
| `projects.py` | Project Management | 11 | Project CRUD and read views |
| `admin_user_groups.py` | Admin - User Groups | 13 | User groups, membership, and project-group access links |
| `admin_project_groups.py` | Admin - Project Groups | 7 | Project groups and project membership |
| `global_roles.py` | Global Role System | 28 | Roles, permission groups, permissions, catalogs |
| `permission_assignments.py` | Permission Assignments | 17 | Direct and user-group assignments and lookups |
| `admin_billing.py` | Admin - Billing | 22 | Billing groups, credentials, catalog, metrics |
| `internal_billing.py` | Billing Internal | 6 | Billing S2S facts, catalog, Checkout, Portal, resync |
| `stripe_webhooks.py` | Stripe Webhooks | 2 | Global fallback and per-billing-group Stripe webhooks |
| `admin_oauth.py` | Admin - OAuth | 20 | Provider catalog, connections, credentials, project bindings, readiness |
| `admin_patreon.py` | Admin - Patreon | 7 | Root-only Patreon operations |
| `internal_patreon.py` | Patreon Internal | 2 | Patreon entitlement S2S read and resync |
| `patreon_webhooks.py` | Patreon Webhooks | 1 | Patreon webhook |
| `email_templates.py` | Admin - Email Templates | 8 | Root-only template lifecycle |
| `internal_email.py` | Internal Email | 3 | Root-gated internal email operations |
| `email_webhooks.py` | Email Webhooks | 1 | Resend/Svix webhook |
| `audit_logs.py` | Audit Logs | 6 | Audit, security events, export, email logs |
| `admin_dashboard.py` | Admin Dashboard | 8 | Dashboard, health, activity, statistics |
| `bulk_operations.py` | Bulk Operations | 4 | Bulk user, group, and role operations |
| `system.py` | System Information | 7 | Authenticated details, public ping, cache operations |

The count excludes FastAPI's built-in documentation routes and the five routes
declared directly in `src/main.py`: `/ping`, the two `/documentation` routes,
the legacy `/docs/USAGE/*` alias, and the `/` redirect to `/docs`.

## Further Reading

- [Usage documentation](/documentation) — domain guides for every surface above
- [Authentication usage cases](/documentation/USAGE/authentication-usage-cases.md)
- [Client authentication guide](/documentation/USAGE/client-authentication-guide.md)
- [OAuth sign-in](/documentation/USAGE/oauth/README.md)
- [Operational runbooks](/documentation/RUNBOOKS)
- Database schema documentation: `schemas/docs/README.md` in the repository
