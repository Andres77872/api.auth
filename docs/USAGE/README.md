# Documentation overview

Integration, administration and operations guides for `api.auth` API version `2.2.0`: the
authentication and authorization service behind Magic Auth. It signs users in (password or
OAuth), issues access and refresh sessions, decides which projects and actions a user may reach,
and manages API keys, transactional email, Patreon entitlement links and Stripe billing facts.

Every page is checked against the code. When a page and the running API disagree, the code wins;
fix the page in the same change.

> [!TIP]
> In the documentation wiki (`/documentation`), press `Ctrl K` (`⌘K` on macOS) or `/` to search
> every page, endpoint, field and error code. Add `?format=raw` to any page URL for its Markdown
> source, or open `/documentation?format=raw` for a Markdown index of every page.

## Start here

| Step | Guide | What you get |
| --- | --- | --- |
| 1 | [Getting started](getting-started.md) | Configuration, schema, first-root bootstrap, first project and first login |
| 2 | [Authentication](authentication-usage-cases.md) | The `/auth` contract: login, registration, refresh rotation, validation, logout, project switching, email and password flows, API-key validation |
| 3 | [Client integration guide](client-authentication-guide.md) | Browser, mobile and server clients: cookies or bearer tokens, refresh, CORS, working code |
| 4 | [Error reference](errors.md) | Response envelopes, status codes, the error-code catalog and fixes by symptom |
| 5 | [Administration and operations](admin-usage-cases.md) | Dashboard statistics, activity feed, system health, cache and bulk operations |

## How access works

```text
USER -> USER_GROUP -> PROJECT_GROUP -> PROJECTS
                 \-> PERMISSION_GROUP -> PERMISSIONS
```

Project reach and action permission are separate:

- A consumer reaches a project only through an active chain: user group → grant → project group →
  active, non-archived project. See [Groups](groups/README.md).
- Root users reach every active project. Admin users administer the projects whose
  `admin_<project_id>` user group they belong to.
- What a session may do is its permission set: a fixed list for root and admin sessions, and the
  permission groups of the global role for consumers.
- Permission groups assigned directly to users or user groups appear in the inspection endpoints,
  but only one guard honours them. [Permission resolution](permissions/resolution.md) is the single
  explanation of both sets.

## Documentation map

Each topic folder has the same pages, so you always know where to look:

| Page | Job |
| --- | --- |
| Overview (`README.md`) | What the domain is, key concepts, route families, rules and caveats |
| Usage | One task per section, with the request and what comes back |
| Scenarios | End-to-end workflows that chain several calls |
| Architecture | Components, tables and stored procedures, caching, invariants, known gaps |
| Request flow | What happens to a request, step by step |
| Reference | The contract: endpoints, fields, responses, error codes, settings |
| Troubleshooting | Symptom → cause → fix |

### Identity and access

| Topic | Covers |
| --- | --- |
| [Users](users/README.md) | Profiles, lifecycle, user types, scoped administration, hard-delete guardrails, multi-email management, bulk operations |
| [Groups](groups/README.md) | User groups, project groups, membership, the grants that give project access, revocation |
| [Projects](projects/README.md) | Project lifecycle, default groups, members, activity, statistics, archive enforcement |
| [Roles](roles/README.md) | Global roles, permission groups, the permission catalog, project role catalogs |
| [Permissions](permissions/README.md) | Assigning permission groups, self-inspection, and how permissions resolve |
| [API keys](api-keys/README.md) | Split-token keys: self-service and admin lifecycle, validation, rotation |

### Sign-in and billing

| Topic | Covers |
| --- | --- |
| [OAuth](oauth/README.md) | Provider-agnostic sign-in: connections, project bindings, readiness, linking, the admin API |
| [Google OAuth](google-oauth/README.md) | Deprecated `/auth/google/*` aliases onto the OAuth pipeline and `GOOGLE_OAUTH_*` configuration |
| [Patreon link](patreon-link/README.md) | Entitlement-only account linking: proof, admin, S2S reads, webhooks, sync |
| [Stripe billing](stripe-billing/README.md) | Billing groups, catalog, per-account credentials, S2S checkout and portal, webhooks |

### Operations

| Topic | Covers |
| --- | --- |
| [Email](email/README.md) | Templates, internal delivery, the outbox worker, the provider webhook |
| [Audit logs](audit_logs/README.md) | API audit trail, activity, security events, email logs, export |

Rollout, kill-switch, secret-rotation and incident procedures for the external integrations are
operations material. They live in the runbooks under `docs/RUNBOOKS/`, listed in the wiki under
Operations → Runbooks.

## Common tasks

| Task | Guide |
| --- | --- |
| Bootstrap the first root user | [Getting started](getting-started.md#first-root-bootstrap-and-current-seed-caveat) |
| Create a project and let users register into it | [Getting started](getting-started.md#set-up-the-first-project-and-groups) |
| Sign in, refresh or sign out | [Authentication](authentication-usage-cases.md) |
| Build a browser or mobile client | [Client integration guide](client-authentication-guide.md) |
| Grant a team access to projects | [Groups usage](groups/usage.md) |
| Manage a user's lifecycle | [Users usage](users/usage.md) |
| Manage a user's email addresses | [User email management](users/email-management.md) |
| Issue, rotate or revoke an API key | [API keys usage](api-keys/usage.md) |
| Find out why a user has or lacks a permission | [Permission resolution](permissions/resolution.md) |
| Enable a sign-in provider for a project | [OAuth usage](oauth/usage.md) |
| Set up billing for a project | [Stripe billing usage](stripe-billing/usage.md) |
| Link a Patreon account | [Patreon link scenarios](patreon-link/scenarios.md) |
| Send transactional email | [Email usage](email/usage.md) |
| Inspect or export audit events | [Audit logs usage](audit_logs/usage.md) |
| Check system health | [Administration and operations](admin-usage-cases.md#system-health--metrics) |
| Decode an error response | [Error reference](errors.md) |

## API surface

API version `2.2.0` registers **246 HTTP method/path operations across 28 `src/routes/*.py`
modules** (`assistant.py` adds one WebSocket endpoint and no HTTP operations). The count excludes
FastAPI's built-in `/docs`, `/redoc` and `/openapi.json` routes and the routes declared directly in
`src/main.py` (`/ping`, the `/documentation` wiki, the legacy `/docs/USAGE/*` redirect and the `/`
redirect). Endpoint-level contracts live in each topic's reference page and in the running OpenAPI
document.

| Surface | Prefix | Module | Operations | Authority |
| --- | --- | --- | ---: | --- |
| Authentication | `/auth` | `auth.py` | 13 | Mixed public/session |
| OAuth | `/auth/oauth` | `auth_oauth.py` | 9 | Project API key (init, providers), public (start, callback), session (link, reauth, unlink) |
| Google OAuth (deprecated) | `/auth/google` | `auth_google.py` | 5 | Public OAuth + session |
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
| Admin OAuth | `/admin/oauth` | `admin_oauth.py` | 20 | Admin; connections, credentials and catalog root-only |
| Root assistant | `/admin/assistant/ws` | `assistant.py` | 0 | One root-only WebSocket endpoint; excluded from HTTP operation counts |
| Billing internal | `/internal/.../billing` | `internal_billing.py` | 6 | Dedicated billing S2S bearer |
| Stripe webhooks | `/webhooks/stripe` | `stripe_webhooks.py` | 2 | Stripe signature |
| Admin Patreon | `/admin/patreon` | `admin_patreon.py` | 8 | Root |
| Patreon internal | `/internal/users/{user_hash}/entitlements` | `internal_patreon.py` | 2 | Dedicated Patreon S2S bearer |
| Patreon webhook | `/webhooks/patreon` | `patreon_webhooks.py` | 1 | Patreon signature |
| Internal email | `/internal/email` | `internal_email.py` | 3 | Root access session |
| Email templates | `/admin/email-templates` | `email_templates.py` | 8 | Root |
| Email webhook | `/webhooks/email` | `email_webhooks.py` | 1 | Svix signature |
| Audit logs | `/admin/audit`, `/admin/email/logs` | `audit_logs.py` | 6 | Admin/root |
| Admin dashboard | `/admin` | `admin_dashboard.py` | 8 | Admin/root |
| Bulk operations | `/admin` | `bulk_operations.py` | 4 | Admin/permission |
| System | `/system` | `system.py` | 7 | Mixed session/admin/public ping |

## Platform-wide contracts

Rules that hold for every route. Topic pages only repeat a rule when a route family differs from it.

| Contract | Current behavior |
| --- | --- |
| User agent | Every request needs a `User-Agent` header. Without one, the request middleware answers `422` with `{"status": "Error", "action": "User-Agent header not found"}` before any route runs. Browsers and `curl` send one. |
| POST size | POST requests whose `Content-Length` exceeds 8 MiB are rejected with `413`. |
| Content types | Older CRUD and admin mutations take form fields (`application/x-www-form-urlencoded` or multipart; list fields repeat). OAuth init/start and administration, email templates, internal email and billing, audit export and the user-group bulk add take JSON. Webhooks take the provider's signed raw body. Each reference page states the format per route. |
| Validation errors | Request-validation failures return `400` `VAL_3001` with `error.details.validation_errors`; FastAPI's default `422` body is never produced. Outside `DEBUG_MODE`, `error.details` is returned only for validation failures and rate limits. See the [error reference](errors.md). |
| Session tokens | Access and refresh tokens are distinct JWTs. `session_token` is a deprecated alias of `access_token` in response bodies and the name of the access-token cookie; it is never a refresh credential. The refresh token travels in the `refresh_token` cookie (path `/auth`) or form field. |
| Permission freshness | Auth-time permissions are re-read on every token check and cached per token for up to 30 seconds (API-key validation results: 60 seconds). Role and permission changes need no new login. |
| Billing plan projection | Project-scoped consumer login, `POST /auth/refresh`, `GET /auth/validate` and consumer `POST /auth/validate-api-key` may include a provider-neutral subscription `plan`, resolved at response time from the project's billing group. It is never stored in JWT claims, cookies or Redis session state. Platform sessions and switch-project responses omit it. |
| System details | `/system/info` and `/system/health` require a valid access session. `/ping` and `/system/ping` are public. |
| Project stubs | `PATCH /projects/{project_hash}/owner` and `/archive` currently return `501`; archive enforcement elsewhere is active. |
| CORS | Set `ALLOWED_ORIGINS` explicitly. `.env.example` is the maintained deployment template. When unset, CORS, early-reject responses and email-link origin checks share one built-in list (`DEFAULT_ALLOWED_ORIGINS` in `src/Util/auth_constants.py`) of localhost/LAN development origins plus the hosted auth UI origin `https://auth-ui.arz.ai`; never rely on it in a deployment. |
| First root | There is no unauthenticated API bootstrap. The canonical SQL seeds a legacy SHA-256 root credential that the Argon2id-only verifier rejects, while the Python bootstrap scripts print a different password. Rotate that row to Argon2id before first login, or omit the seed and create the root through the application helper; see [Getting started](getting-started.md#first-root-bootstrap-and-current-seed-caveat). |

## Writing and maintaining these docs

Code and runtime configuration are authoritative:

- route registration: `src/main.py` and the decorators in `src/routes/*.py`;
- request and response models: `src/Util/Models.py`;
- error codes: `src/Util/error_handler.py`;
- environment template: `.env.example`;
- schema and stored procedures: `schemas/`;
- operational commands: `scripts/`, the Dockerfiles and the test configuration.

When a route, model, feature flag or workflow changes, update the topic's pages and the route
inventory above in the same change.

### Conventions

- One `# H1` per page (the page title), sentence-case headings, no skipped levels.
- Put paths, fields, codes and environment variables in backticks, for example
  `POST /auth/login`, `project_hash`, `AUTH_1001`.
- Fence code with a language: `bash`, `json`, `jsonc`, `http`, `python`, `typescript`, `sql`,
  `text`. A `json` fence must be strictly valid JSON; use `jsonc` for comments or elisions.
- Mark real caveats with GitHub alerts (`> [!NOTE]`, `> [!TIP]`, `> [!IMPORTANT]`,
  `> [!WARNING]`, `> [!CAUTION]`), sparingly.
- In reference route tables, the path cell comes first and the method cell right after it.
- No manual tables of contents (the wiki builds an "On this page" outline), no "last updated"
  stamps, no source line numbers and no commit hashes: they drift silently.
- Cross-references stay inside `docs/USAGE/`, so a topic reads end to end without depending on
  documents maintained elsewhere.

### The documentation wiki

`/documentation` renders `docs/` with navigation, search, a per-page outline, previous/next links
and light and dark themes that match the admin console. The renderer lives in
`src/Util/docs_site/`: a dependency-free Markdown renderer that always escapes raw HTML. Topic
titles, icons and navigation order are set in `src/Util/docs_site/site.py`; a new folder under
`docs/USAGE/` still appears automatically under "More" until it is added there. The "Common tasks"
table above also feeds the wiki's home page.

### Checks

```bash
.venv/bin/python -m pytest tests/static tests/unit/test_documentation_renderer.py -q
```

`tests/static/test_documentation_consistency.py` verifies the route inventory, that reference route
tables list only registered operations, that local links and anchors resolve, that every `json`
fence parses and that referenced repository files exist. The other `tests/static/*_docs_static.py`
files guard topic-specific contracts, and `tests/unit/test_documentation_renderer.py` covers the
wiki renderer.
