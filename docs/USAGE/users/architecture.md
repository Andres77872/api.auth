# Users Architecture

Technical architecture of the users system as it actually exists in `api.auth`.

---

## Core Runtime Model

The user model is not just "users with roles". The repo combines a 3-tier type system with group-based project reach:

```text
ROOT      → global access
ADMIN     → USER → admin USER_GROUP → PROJECT_GROUP → PROJECT
CONSUMER  → USER → USER_GROUP       → PROJECT_GROUP → PROJECT
                          ↘
                            ROLE / PERMISSION_GROUP data affects capabilities
```

Two separate concerns exist at the same time:

- **Reach**: which projects the user can access
- **Capability**: what the user can do once there

`/users/*` primarily documents the user entity and reach inspection. Roles and permission groups are separate systems.

---

## Real Tables Behind the Model

| Table | Purpose |
|------|---------|
| `users` | Core user record, `user_type`, `role_id`, activation state |
| `user_emails` | Activated-email authority for email login and recovery eligibility |
| `user_email_link_tokens` | Hash-only purpose-scoped link-token store for activation and password recovery |
| `email_outbox` | Durable transactional auth-email delivery queue |
| `user_group_members` | Membership bridge from user to user group |
| `user_group_project_groups` | Bridge from user groups to project groups |
| `project_group_members` | Bridge from project groups to projects |
| `bulk_operations_log` | Audit-style tracking for bulk user operations |

The crucial architectural point is still:

```text
USER → USER_GROUP → PROJECT_GROUP → PROJECT
```

There is no active direct user-to-project table in the intended model.

---

## Email Identity Lifecycle

Email is a **separate identity from the user record**. `user_emails` is the
authoritative store; `users.email` is a deprecated compatibility shadow that the
lifecycle stored procedures keep loosely in sync (primary email only) and that
**never grants login by itself**. Email is optional for registration and account
use.

Each `user_emails` row carries a `status`:

| Status | Meaning | Login / reset eligible? |
|--------|---------|--------------------------|
| `pending` | Added but not yet activated via a link token | No |
| `activated` | Activated through a hash-only token; usable identity | Yes |
| `removed` | Soft-removed by the owner; `removed_at` set | No |
| `suppressed` | Hard-bounced/complained per provider webhook | No |

Key invariants and flows:

- **Uniqueness** is DB-enforced via two **VIRTUAL** generated columns —
  `active_activated_email` (at most one activated, non-removed row per normalized
  address, globally) and `primary_user_id` (at most one active primary per user).
  They must stay `VIRTUAL` because `user_id` carries an `ON DELETE CASCADE` FK and
  MySQL forbids cascade actions on the base column of a `STORED` generated column.
- **Login** (`sp_user_login`) resolves username first, then an `activated`,
  non-removed `user_emails` row by normalized address — so an email-shaped
  username cannot be shadowed and the deprecated `users.email` cannot grant login.
- **Activation** (`sp_consume_email_activation_token`) flips `pending → activated`,
  auto-selects the first activated email as primary, and rejects a global
  conflict (another account already activated the address) without activating.
- **Password recovery** (`sp_password_reset_link_enqueue`) is activated-email-only;
  `pending`/`removed`/`suppressed`/unknown identifiers keep the generic `202`
  posture and enqueue nothing.
- **Suppression**: a provider hard-bounce/complaint webhook flips the matching
  `activated` row to `suppressed` (and clears `is_primary`), removing it from
  login and recovery while username login still works.

### HTTP surface for the email lifecycle

The `user_emails` lifecycle is operated at the HTTP layer by six endpoints in
`src/routes/users.py`:

| Lifecycle action | Endpoint | Caller |
|------------------|----------|--------|
| List own emails | `GET /users/me/emails` | Any authenticated user (owner view) |
| Add + enqueue activation | `POST /users/me/emails` | Any authenticated user |
| Resend activation | `POST /users/me/emails/{email_id}/resend` | Any authenticated user |
| Soft-remove | `DELETE /users/me/emails/{email_id}` | Any authenticated user |
| Select primary | `POST /users/me/emails/{email_id}/primary` | Any authenticated user |
| Inspect a target user's emails | `GET /users/{user_hash}/emails` | Root or admin (masked/hash view) |
| Re-trigger a target user's activation | `POST /users/{user_hash}/emails/{email_id}/resend` | Root or admin |

The send-side routes use the generic `202` / `429 + Retry-After` posture, a
resend cooldown (`EMAIL_RESEND_COOLDOWN_SECONDS`, default 60s), and optional
`Idempotency-Key` replay. Removing or re-pointing the primary email revokes the
caller's other sessions while keeping the current one. Full request/response
detail is in [email-management.md](email-management.md).

Tokens, the durable outbox, the worker, webhooks, suppression, retention, and
rollback are documented in `docs/RUNBOOKS/email-activation.md`.

---

## Route and Layer Split

### User entity routes

- Route file: `src/routes/users.py` (18 endpoints)
- Covers profile, access summary, list/search, details, update, status, password reset, delete, one type-change route, and the per-user email-management group (`/users/me/emails*` and the root/admin `/users/{user_hash}/emails*` routes — see [email-management.md](email-management.md))

### User type routes

- Route file: `src/routes/user_types_auth.py`
- Covers root/admin creation, type info, stricter type updates, listing by type, stats, and admin-project assignment

### Bulk user routes

- Route file: `src/routes/bulk_operations.py`
- Covers `bulk-update` and `bulk-delete`

### DB layer

- Main DB module: `src/Util/db/db_users.py`
- Access bridge helpers: `src/Util/db/db_user_groups.py`
- User-type helpers: `src/Util/db/__init__.py`

---

## How Users Relate to Groups, Project Groups, and Projects

### Consumer users

- join one or more user groups through `user_group_members`
- inherit accessible projects through the user-group ↔ project-group bridge
- get effective permissions from the broader authorization system

### Admin users

- are still plain `users` rows with `user_type='admin'`
- gain project reach by being inserted into project-specific admin groups
- `create_admin_user()` and admin-project assignment helpers use `sp_find_admin_group_for_project` and group membership to wire that access

### Root users

- are created as `users.user_type='root'`
- do not need group membership to log in globally
- still may have accessible projects returned for UI convenience, but root auth is not bounded by those project links

---

## Session Embedding Model

### Auth route payload

`src/routes/auth.py:_create_session()` stores this data in Redis:

- `session_id`
- `user_id`
- `user_hash`
- `user_type`
- `project_id`
- `project_hash`
- `project_name`
- `user_group_ids`
- `user_group_names`

This is why `/auth/validate` can return group names directly from session payload.

### Middleware validation path

`src/middleware/authentication.py` uses `validate_session()` from `db_users.py`, which:

- loads the cached session payload
- re-resolves the project by `project_hash`
- reconstructs groups/permissions according to `user_type`

Important consequence:

- some views are driven by cached login/session context
- some permission/group checks are rebuilt during validation
- operators should expect **stale-session edge cases** after access-model changes until re-login, refresh, or project switching happens

---

## Cache and Invalidation Behavior

`src/Util/cache_manager.py` manages:

- session cache (`SESSION_TTL = 3600`)
- access-check cache (`1800`)
- permission-check cache (`1800`)
- user-type/user-info cache (`3600`)

User-focused invalidation triggers documented in code:

- `update_user()` → `invalidate_user_cache(user_id)`
- `update_user_type()` → `invalidate_user_cache(user_id)`
- `delete_user()` → `invalidate_user_cache(user_id)`
- `PUT /users/{hash}/status?is_active=false` → `invalidate_user_sessions(user_id)` and `invalidate_user_cache(user_id)`
- `DELETE /users/{hash}` → same session/cache invalidation cascade after soft delete

Operational implication:

- **status changes and deletes** aggressively revoke access
- **group/role/permission changes** may still require re-login or project switching for clients to observe the new state consistently

---

## Lifecycle Architecture

### Self-registration

- entry point: `POST /auth/register`
- requires a valid `user_group_hash`
- registration is blocked if that user group is not linked to at least one project

### Root/admin creation

- entry point: `POST /user-types/root` and `POST /user-types/admin`
- admin creation validates projects first, then wires admin-group membership

### Status change and deletion

- status changes are handled in `src/routes/users.py` and explicitly clear sessions/cache on deactivation
- deletion uses `sp_delete_user`, which also deactivates active user-group memberships

### Password change and recovery

- self-service password rotation is owned by `POST /auth/password/change`, not profile update
- `PUT /users/profile` rejects password-equivalent fields before the DB update helper runs
- password recovery is link-only and uses activated `user_emails` plus hash-only `user_email_link_tokens`
- reset-link consumption creates no session; authenticated change preserves the current session and revokes other sessions/families

### Type changes

- `PATCH /users/{hash}/type` = enum-focused legacy path
- `PUT /user-types/{hash}/type` = stricter path with admin project assignment requirement

---

## What Is Intentionally Outside the Users Routes

The users suite should not be confused with the whole auth model.

Outside this route family:

- group membership CRUD lives under `/admin/user-groups`
- project reach wiring lives under user-group ↔ project-group routes
- global role assignment lives under `/roles/users/{hash}/role`
- permission-group assignment lives under `/permissions/...`

If you try to use `/users/*` to model all access, you will create a quilombo because the repo intentionally separates the user entity from the access topology.

---

## Related Documentation

- **[Users Overview](README.md)**
- **[Usage](usage.md)**
- **[Email Management](email-management.md)**
- **[User Types](user-types.md)**
- **[Bulk Operations](bulk-operations.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: June 2026
**Document Version**: 1.1
