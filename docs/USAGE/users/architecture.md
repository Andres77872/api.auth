# Users architecture

How the users domain is built: the model, where the data lives, how scoping and revocation work,
and the design choices behind them. The request-by-request view is in
[request-flow.md](request-flow.md).

## Model

```text
root      -> every active project (no group membership needed)
admin     -> USER -> admin_<project_id> USER_GROUP -> PROJECT_GROUP -> PROJECT   (assigned projects)
          -> USER -> other USER_GROUPs            -> PROJECT_GROUP -> PROJECT   (extra reach)
consumer  -> USER -> USER_GROUP                   -> PROJECT_GROUP -> PROJECT
```

- **Reach** (which projects a user can use) always comes from user-group membership, except for
  root, whom `sp_get_user_accessible_projects` gives every active, non-archived project. There is no
  direct user-to-project table.
- **Admin assignment** is membership of a project's `admin_<project_id>` user group. `POST /projects`
  creates that group and grants it the project; the `/user-types/admin/...` routes add and remove
  members. See [User types](user-types.md#how-admin-assignment-works).
- **Capability** (what a user may do inside a project) comes from global roles and permission
  groups, managed by the [roles](../roles/README.md) and [permissions](../permissions/README.md)
  suites. The `capabilities` list in type info is descriptive only.
- **Email identity** is separate from the account: `user_emails` holds any number of addresses with
  their own lifecycle; `users.email` is a legacy shadow of the primary one.

## Where the data lives

| Table | Holds |
| --- | --- |
| `users` | Account: `user_hash`, `username` (unique), legacy `email`, `password_hash`, `user_type`, `role_id`, `is_active` |
| `user_group_members` | User to user group memberships (`is_active`, `assigned_at`, `removed_at`) |
| `user_group_project_groups` | User group to project group grants |
| `project_group_members` | Project group to project links |
| `user_emails` | Email addresses, status, primary flag and timestamps |
| `user_email_link_tokens` | Hashes of activation and password-reset links; the link secrets are never stored |
| `email_messages` | Durable outbox of queued emails, delivered by the email worker |
| `email_idempotency_keys` | Stored `202` replies for `Idempotency-Key` retries |

Stored procedures by operation:

| Operation | Procedures |
| --- | --- |
| Look up, list, count, search | `sp_get_user_by_hash`, `sp_get_user_type`, `sp_list_users_with_access`, `sp_count_users`, `sp_search_users` |
| Create | `sp_create_root_user`, `sp_create_admin_user`, `sp_create_consumer_user` |
| Update | `sp_update_user`, `sp_update_user_type` |
| Delete | `sp_delete_user` (soft), `sp_hard_delete_user` |
| Reach and admin assignment | `sp_get_user_accessible_projects`, `sp_get_admin_assigned_projects`, `sp_get_admin_project_assignments_with_details`, `sp_find_admin_group_for_project`, `sp_find_admin_groups_for_user_in_project` |
| Email lifecycle | `sp_user_email_add_and_enqueue`, `sp_user_email_resend_and_enqueue`, `sp_consume_email_activation_token`, `sp_user_email_remove`, `sp_user_email_set_primary`, `sp_user_email_list_for_user`, `sp_admin_user_email_list`, `sp_admin_password_reset_link_enqueue` |

Code map: routes in `src/routes/users.py`, `src/routes/user_types_auth.py` and
`src/routes/bulk_operations.py`; account helpers in `src/Util/db/db_users.py`; email helpers in
`src/Util/db/db_email.py` and `src/Util/email/`; scope checks in `src/Util/admin_scope.py`; bulk logic
in `src/Util/bulk_operations.py`; session revocation in `src/Util/auth_lifecycle.py`. Tables and
procedures are defined under `schemas/`.

## Scoping

Two scope models coexist:

| Model | Admin's projects | Used by |
| --- | --- | --- |
| Overlap | Every project the admin reaches (`sp_get_user_accessible_projects`) | list, detail, `PUT /users/{user_hash}`, status, soft delete |
| Assigned scope | Only projects whose admin group the admin belongs to (`resolve_admin_scope`) | search, reset-password, admin email routes, type info, list by type |

`src/Util/admin_scope.py` implements the assigned-scope model. Its rules:

- Only `root` and `admin` user types have any scope. Session permissions such as `admin` or
  `manage_users` coming from a consumer's global role grant nothing on these routes.
- The caller's type and assignments are read from the database on each request, not from the
  session, so a demotion or unassignment applies to the next call.
- Admins are always in scope for themselves.

Root reaches every project, so both models exclude root targets explicitly: an admin's overlap and
scope never contain a root user (`_require_target_in_admin_projects` in `src/routes/users.py`,
`user_in_scope` in `src/Util/admin_scope.py`).

The bulk routes require a root or admin caller and apply the assigned-scope model to each target
([Bulk user operations](bulk-operations.md#authorization)).

## Email identity invariants

Rules and statuses are listed in [User email management](email-management.md#address-lifecycle).
The database enforces them:

- Two `VIRTUAL` generated columns with unique indexes: `active_activated_email` (one activated,
  non-removed row per normalized address, across all users) and `primary_user_id` (one activated
  primary per user). They must stay `VIRTUAL`: `user_id` has an `ON DELETE CASCADE` foreign key, and
  MySQL forbids cascading actions on a base column of a `STORED` generated column.
- Triggers on `user_emails` normalize the address, reject primary flags on non-activated or removed
  rows, and cap each user at 5 `pending` + `activated` rows.
- `sp_user_login` resolves a username first, then an activated, non-removed address, so an
  email-shaped username cannot be shadowed and `users.email` never grants login.
- Only hashes of link tokens are stored; tokens, links and message payloads never appear in API
  responses.

## Sessions, revocation and caching

Sign-in stores each access session in Redis as `session:{access_jti}` and indexes it per user in
`user_sessions:{user_id}`; refresh families are indexed in `user_refresh_families:{user_id}`.

Every authenticated request re-validates: the access JWT, the Redis session and family, that the user
still exists and is active (otherwise their auth state is revoked), and that the session's project is
still reachable (for admins: still assigned). So an inactive user's tokens stop working on their next
use even when nothing revoked them.

| Event | Effect on sessions |
| --- | --- |
| Deactivation, soft delete, hard delete, bulk deactivation, bulk delete | `revoke_user_auth_state`: every access session and refresh family of the user |
| Type change (any route) | `revoke_user_auth_state` when the type actually changes |
| Email activation, password reset through a link | `revoke_user_auth_state` |
| Password change, email removal, primary change | `revoke_user_auth_state_except_current`: all but the caller's session and family |
| Username or legacy email update (own profile or by an admin) | None; sessions stay valid |
| Admin project removed | Nothing immediately; a session on that project is revoked on its next use |

`src/Util/cache_manager.py` caches user data (`USER_INFO_TTL`, `3600` seconds) and access and
permission checks (`1800` seconds). The user update, status, type change, password change, soft delete
and hard delete helpers call `invalidate_user_cache`. It drops those entries and the user's derived
`session_full:*` validation cache, but keeps the `session:*` access sessions: those are auth state, not
cache, and are only removed by the revocation calls in the table above.

A type change revokes everything because a session carries the user type and, for root and admin, its
permission set, and refresh rotation carries both forward; only a new sign-in reflects the new type.
The username stored in an existing session is not rewritten, so a renamed user's `/auth/validate`
shows the new name after their next sign-in.

## Account lifecycle

| Path | Creates or changes | Notes |
| --- | --- | --- |
| `POST /auth/register` | `consumer` in a user group | Public; tokens only if the group reaches an active project |
| External sign-in | `consumer` | Created by the OAuth pipeline; see the [OAuth suite](../oauth/README.md) |
| `POST /user-types/root`, `POST /user-types/admin` | `root`, `admin` | Root-only; admin creation adds admin-group memberships |
| Type change routes, bulk update | `user_type` | Only `PUT /user-types/{user_hash}/type` assigns an admin project |
| Soft delete, bulk delete, bulk deactivation | `is_active = 0` | Row, addresses and history are kept; no route reactivates |
| Hard delete | Removes the row | Root-only; foreign keys cascade |

Design choices visible in the code:

- **Soft delete by default.** Offboarding keeps the row so audit history and references stay intact.
  Soft delete also deactivates group memberships; deactivation through bulk update does not.
- **Hard delete is a root-only deep clean.** `sp_hard_delete_user` is a single `DELETE`; foreign keys
  with `ON DELETE CASCADE` remove owned data (sessions, API keys, email rows and tokens, external
  accounts, memberships, direct permission-group grants, billing and Patreon records) and `ON DELETE
  SET NULL` clears audit and ownership references, so shared projects and user groups survive
  without an owner. This is also the only way to free addresses held by a soft-deleted account.
- **Enumeration-safe email sends.** Send routes return one generic `202` so they cannot be used to
  learn which addresses exist; only rate limiting is reported.
- **Password changes live in the auth routes.** `PUT /users/profile` rejects password fields;
  `POST /auth/password/change` verifies the current password and applies the shared policy.
