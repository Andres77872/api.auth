# Users request flow

What happens to a `/users`, `/user-types` or bulk user request between the client and the database.
Components and invariants are described in [architecture.md](architecture.md).

## Common path

```text
client
  -> platform middleware (CORS, request validation, API audit, auth context)
  -> route authentication (access token -> session -> active user)
  -> handler checks (caller type, scope, target, fields)
  -> DB helpers in src/Util/db -> MySQL stored procedures
  -> Redis: session/refresh revocation, cache invalidation, email rate limits
  -> JSON response, or an error envelope from the exception handlers
```

Platform-wide request rules (User-Agent, body size, error envelope) are in
[Platform-wide contracts](../README.md#platform-wide-contracts).

### Authentication per route family

| Family | How the token is checked | Caller-type check |
| --- | --- | --- |
| `/users` | The `log_and_handle_errors` decorator validates the token and builds a log context (`user_id`, `user_hash`, `project_hash`) | In the handler (`is_root_user`, `get_user_type`, or `resolve_admin_scope`) |
| `/user-types` | The `require_root_user` or `require_root_or_admin_user` dependency | In the dependency (`403`, `AUTHZ_2002`) |
| `/admin/users/bulk-*` | The handler calls `validate_session` | Session permissions must include `admin` or `manage_users`, and `resolve_admin_scope` must find a root or admin user |

`validate_session` verifies the access JWT, loads the Redis session and refresh family, reloads the
user (an inactive or missing user fails and has its auth state revoked), and rebuilds the project
context: root may use any active project, an admin must still be assigned to the session project,
and a consumer must still reach it through a user group. A failure returns `401`.

## Reads

### List users

`GET /users/list`

1. Load the caller. Root skips scoping; an admin loads their reachable projects; anyone else gets
   `403`.
2. `sp_list_users_with_access` returns one page with `groups_json` and `projects_json` aggregated
   per user, filtered by `search`, type, group, project and `include_inactive`.
3. `sp_count_users` computes `pagination.total` from type and `include_inactive` only.
4. For an admin, root rows and rows whose projects do not overlap the admin's are dropped (the
   admin's own row is kept).
5. Each remaining row gets `user_type_info` and, per project, effective permissions.

### Read or change one user (overlap routes)

`GET`/`PUT /users/{user_hash}`, `PUT /users/{user_hash}/status`, `DELETE /users/{user_hash}`

1. Load the caller and the target with `sp_get_user_by_hash` (active users only, else `404`).
2. Root passes. Otherwise the caller must be an admin (`403`), the target must not be a root user
   (`403`), and the admin's reachable projects must overlap the target's (`403`, "User not in your
   projects"). Reading your own record skips these checks.
3. Route-specific guards run: no self-deactivation or self-delete (`400`), `user_type` only from
   root (`403`).

### Assigned-scope routes

Search, reset-password, the admin email routes, and `/user-types/{user_hash}/info` and
`/user-types/users/{user_type}` use `resolve_admin_scope`:

1. Read the caller's type live (`sp_get_user_type`). Not root or admin: `403`.
2. For an admin, read assigned project IDs with `sp_get_admin_assigned_projects` (membership of
   each project's `admin_<project_id>` group).
3. `user_in_scope` allows root, the admin themselves, and non-root targets whose reachable projects
   include an assigned one. Search and list-by-type apply this after fetching rows.

## Lifecycle writes

### Deactivate

`PUT /users/{user_hash}/status?is_active=false`

1. Overlap and guard checks as above.
2. `set_user_active_status` calls `sp_set_user_status`, which sets `users.is_active`; group
   memberships are left as they are. No updated row returns `500`.
3. When deactivating, `revoke_user_auth_state` deletes every `session:{access_jti}` listed in
   `user_sessions:{user_id}` and revokes every refresh family in `user_refresh_families:{user_id}`.
4. `invalidate_user_sessions` and `cache_manager.invalidate_user_cache` clear remaining sessions
   and cached user data.

`is_active=true` runs the same path but only reaches active users (inactive ones are `404`), so it
changes nothing.

### Soft delete

`DELETE /users/{user_hash}`

1. Overlap and guard checks as above.
2. `sp_delete_user` sets `users.is_active = 0` and deactivates active `user_group_members` rows. It
   reports whether the `users` row changed, so a user without memberships is deleted normally.
3. On success, `revoke_user_auth_state` removes the user's sessions and refresh families, and
   `invalidate_user_sessions` and `cache_manager.invalidate_user_cache` clear cached state.

### Hard delete

`DELETE /users/{user_hash}/hard`

1. `is_root_user` on the caller (`403` otherwise).
2. Load the target including inactive users (`sp_get_user_by_hash` with `include_inactive`); refuse
   the caller's own account (`400`).
3. Count the target's non-removed email rows for the response and audit record.
4. `sp_hard_delete_user` deletes the `users` row. Foreign keys cascade to owned data and set audit and
   ownership references to `NULL`.
5. Revoke auth state and clear caches, then write the audit record with the pre-deletion snapshot.

### Admin password-reset link

`POST /users/{user_hash}/reset-password`

1. `resolve_admin_scope` on the caller; load the target; refuse root targets (`400`); require the
   target in scope (`403`).
2. Consume the `admin_password_reset` send buckets (target, caller, IP); a full bucket returns `429`.
3. Mint a link token; only its hash is stored.
4. `sp_admin_password_reset_link_enqueue` picks the primary activated address (else the
   earliest-activated), inserts the hash-only token into `user_email_link_tokens` and the message
   into the `email_messages` outbox. With no activated address it inserts nothing.
5. Write an `admin_password_reset_requested` activity record and return `has_delivery_target`.
   The outbox worker delivers the email later.

## Email lifecycle

### Add an address

`POST /users/me/emails`

1. Read `email` from the form or JSON body, check its shape (`400`), trim and lower-case it, and hash
   it with the email pepper.
2. Consume the `email_activation` send buckets (`429` when full).
3. Replay a stored `202` if the `Idempotency-Key` matches a completed request.
4. Mint an activation token and encrypt the render payload.
5. `sp_user_email_add_and_enqueue` finds or creates the `pending` row, enforces the 5-address limit,
   revokes older activation tokens, and inserts the new token and outbox message. Refusals and
   errors are logged, not returned.
6. Record the idempotency result and return the generic `202`.

The resend routes follow the same steps with the resend cooldown after step 2 and
`sp_user_email_resend_and_enqueue`, which only sends for a `pending` row outside the cooldown.

### Activate an address

`POST /auth/email/verify` calls `sp_consume_email_activation_token`. When the token is valid and no
other account holds the address, the row becomes `activated` (and primary if the user had none,
updating the `v_users.email` read projection), then `revoke_user_auth_state` signs the user out everywhere.

### Remove an address or change the primary

`DELETE /users/me/emails/{email_id}` calls `sp_user_email_remove`; `POST .../primary` calls
`sp_user_email_set_primary`. A refusal from the procedure becomes `404` or `409`. On success,
`revoke_user_auth_state_except_current` revokes every session and refresh family except the ones in
the caller's access token.

## Type changes and admin assignment

### Change a type

- `PUT /user-types/{user_hash}/type`: validate `user_type`; for `admin`, require existing
  `assigned_project_ids` and look up every admin group with `sp_find_admin_group_for_project` before
  changing anything (`404`, `NF_4003`, when missing). `update_user_type` then runs
  `sp_update_user_type` and adds the user to each requested project's admin group in the same transaction; the user cache is
  invalidated and `user_type_info` is rebuilt.
- `PATCH /users/{user_hash}/type` and `PUT /users/{user_hash}` with `user_type`: set the type only
  (`sp_update_user_type` or `sp_update_user`) and invalidate the user cache.

When the type actually changes, `revoke_user_auth_state` revokes every access session and refresh
family of the user, because sessions carry the type (and, for root and admin, the permission set)
and refresh would carry it forward. A `username` update only invalidates the cache;
sessions stay valid.

### Assign or remove an admin project

- Add: `sp_find_admin_group_for_project` finds the project's `admin_<project_id>` group (`404`,
  `NF_4003`, when missing), `sp_check_user_in_group` skips existing members, and the user is added
  to the group.
- Remove: `sp_find_admin_groups_for_user_in_project` lists the admin groups the user belongs to for
  that project, and the user is removed from each; none returns `404` (`NF_4003`).
- Replace: validates every project ID, removes projects missing from the new set, adds new ones, and
  collects per-project failures into `success: false`.

## Bulk writes

`POST /admin/users/bulk-update` and `POST /admin/users/bulk-delete`

1. `validate_session`, the session permission check, and `resolve_admin_scope` (root or admin
   user, else `403`).
2. Field validation (list size, `user_type`, `confirm_deletion`, unsupported fields).
3. For each hash: load the active user, refuse the caller's own account for deactivation or delete,
   and, for an admin, root users and users outside the assigned scope. Apply the change
   (`update_user` and a direct `is_active` update, or `delete_user`), record a per-user result, and
   continue on failure.
4. Update revokes auth state for each deactivated user. Delete refuses root users and revokes auth
   state for each deleted user; a failed revocation becomes a `warnings[]` entry.
5. Write the bulk activity record and return the summary. See
   [Bulk user operations](bulk-operations.md).
