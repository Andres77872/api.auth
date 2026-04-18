# Users Request and Data Flow

How user-management requests move through routes, DB helpers, stored procedures, sessions, and cache invalidation.

---

## 1. Self-Registration Flow

Flow for `POST /auth/register`:

1. Validate required form fields: `username`, `password`, `user_group_hash`
2. Check username/email availability globally
3. Resolve the target user group by hash
4. Verify that user group is linked to at least one project
5. Call `enhanced_register(...)`
6. Set the session cookie and return the created user and selected project context

Critical operational point:

- self-registration is not open-ended; it depends on an already-wired user group with project access

---

## 2. Login, Session Creation, and Session Validation

Flow for `POST /auth/login`:

1. Verify credentials with `sp_user_login`
2. ALL users MUST provide `project_hash`; root bypasses group-based access validation
3. For root, lookup the requested project directly (no group validation)
4. For non-root, resolve accessible projects through `get_user_accessible_projects()`
5. Choose the requested project (mandatory for all users)
6. `_create_session()` stores `user_group_ids`, `user_group_names`, and project context in Redis
7. Return token, chosen project, accessible projects, and user groups

Related flows:

- `GET /auth/validate` reads raw session payload from Redis and returns cached group names
- `POST /auth/refresh` creates a new session with the same project context
- `POST /auth/switch-project` validates reach to the requested project and emits a new session bound to that project

---

## 3. Profile and Access Summary Flow

### `GET /users/profile`

1. Resolve current user by `user_hash`
2. Load `get_user_type_info(user.id)`
3. Load user groups and membership metadata
4. Load accessible projects
5. Add effective permissions per project
6. Return assembled user profile snapshot

### `GET /users/access-summary`

Same general input data, but organized for access inspection:

- group list with `projects_count`
- accessible projects with access groups and effective permissions
- current session summary

---

## 4. Admin-Scoped Listing and Detail Flow

### `GET /users/list`

1. Resolve current user
2. Root bypasses scoping
3. Admin callers load their accessible projects
4. `list_users_with_access()` fetches the raw candidate set from `sp_list_users_with_access`
5. For each candidate user, the route checks project overlap against the admin's accessible project IDs
6. Non-overlapping users are skipped from the final result

Caveat:

- `pagination.total` is based on `count_users()` and does not include the later overlap filtering or group/project filters

### `GET /users/{hash}`

1. Resolve current user and target user
2. Allow self-access immediately
3. Root bypasses scoping
4. Admin callers compare their accessible project hashes to the target user's accessible project hashes
5. If overlap exists, build the full detail response; otherwise return access denied

### `GET /users/search/query`

This flow is simpler:

1. Validate admin/root caller
2. Validate `limit` and optional `user_type_filter`
3. Call `sp_search_users`
4. Return search results directly

Important caveat:

- unlike list/details, there is no explicit project-overlap filter in this route

---

## 5. Status Change Cascade

Flow for `PUT /users/{hash}/status?is_active=false`:

1. Resolve acting user and target user
2. Enforce root/admin rules and project-overlap checks for admin callers
3. Block self-deactivation
4. Block non-root deactivation of root users
5. Update the user record
6. If deactivating, run:
   - `invalidate_user_sessions(target_user.id)`
   - `cache_manager.invalidate_user_cache(target_user.id)`
7. Return confirmation

This is the main hard-stop path for compromised or departing accounts.

---

## 6. Password Reset Flow

Flow for `POST /users/{hash}/reset-password`:

1. Resolve acting user and ensure admin/root privileges
2. Resolve target user
3. Reject resets for `root` targets
4. Generate reset metadata with `create_password_reset_data()`
5. Update the target's password hash with the generated temporary password
6. Return expiry metadata and out-of-band delivery instructions

Operational caveat:

- the temporary password exists internally, but the route intentionally does not include it in the public response body

---

## 7. Delete Flow

Flow for `DELETE /users/{hash}`:

1. Resolve acting user and target user
2. Block self-delete
3. Block non-root delete of root users
4. For admin callers, require project overlap with the target user
5. Run `sp_delete_user`
6. Deactivate the target's sessions and user cache
7. Return a soft-delete confirmation

Stored-procedure side effect:

- active `user_group_members` rows for the user are also deactivated

---

## 8. Type-Management Flow

### `PATCH /users/{hash}/type`

1. Root-only authorization
2. Validate new enum value
3. Call `update_user_type(user_id, new_user_type, updated_by=...)`
4. Return previous/new type

This path changes the type but does not force an initial admin-project assignment.

### `PUT /user-types/{hash}/type`

1. Root-only authorization
2. Validate new enum value
3. If `admin`, require `assigned_project_id`
4. Validate the project exists
5. Call `update_user_type(..., project_id=assigned_project_id)`
6. Return enriched `user_type_info`

Use this path when promoting users to admin in a production workflow.

---

## 9. Admin Project Assignment Lifecycle

The admin assignment routes all work through group membership, not a direct column on `users`:

- `GET /user-types/admin/{hash}/projects`
- `PUT /user-types/admin/{hash}/projects`
- `POST /user-types/admin/{hash}/projects/add`
- `DELETE /user-types/admin/{hash}/projects/{project_id}`

The underlying helpers:

- look up the admin group for a project
- add/remove the admin user from that group
- invalidate user cache after assignment changes in the DB layer

That means the admin-project lifecycle is really a controlled admin-group membership lifecycle.

---

## Related Documentation

- **[Users Overview](README.md)**
- **[Usage](usage.md)**
- **[User Types](user-types.md)**
- **[Bulk Operations](bulk-operations.md)**
- **[Architecture](architecture.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
