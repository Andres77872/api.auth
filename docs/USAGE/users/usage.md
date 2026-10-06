# Users usage

How to do common user-management tasks. Examples use `http://localhost:8000` and an access token in
`$TOKEN` (any user), `$ADMIN_TOKEN` (root or admin) or `$ROOT_TOKEN` (root). Field, response and
error tables are in the [reference](reference.md); who may act on whom is in
[Caller rules](reference.md#caller-rules).

## Your own account

### Read your profile

```bash
curl "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $TOKEN"
```

Returns your account fields, `user_type_info`, your user groups, and the projects you can reach,
each with your effective `permissions` there. The access summary below also shows which groups grant
each project.

### See what you can reach and why

```bash
curl "http://localhost:8000/users/access-summary" \
  -H "Authorization: Bearer $TOKEN"
```

Returns `access_summary` with each user group (and how many projects it reaches) and each reachable
project with the groups that grant it and your effective permissions there. This is the first call to
make when someone says "I can sign in but cannot see project X". `current_session` only carries the
session's `project_hash`.

### Change your username

```bash
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "username=new_username"
```

Send `username` to edit the profile. Email fields are rejected; add and activate addresses through
[User email management](email-management.md). Password fields are rejected with `400`; change a
password with `POST /auth/password/change` ([Authentication usage](../authentication-usage-cases.md)).

Your sessions stay valid, including the one you used. Sessions keep the username they were issued
with, so `/auth/validate` shows a new username after your next sign-in. The same holds for the target
user when an admin updates their username.

## Find users

### List users

```bash
curl "http://localhost:8000/users/list?limit=25&offset=0&sort_by=created_at&sort_order=desc&user_type_filter=consumer&project_filter=$PROJECT_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Root sees everyone. An admin sees themselves plus non-root users sharing a project with them. Each item has
the user's groups and projects with effective permissions unless you turn those off with
`include_group_info=false` or `include_project_access=false`.

> [!NOTE]
> `pagination.total` ignores `search`, `group_filter`, `project_filter` and admin scoping, and admin
> filtering happens after the page is read, so an admin's page can be short or even empty before the
> end. To read everything, keep increasing `offset` by `limit` until it reaches `pagination.total`.

### Search users

```bash
curl "http://localhost:8000/users/search/query?q=jane&user_type_filter=consumer&limit=20" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Matches active users by username or activated primary email substring. `limit` is capped at `100`. Admins only
get non-root users in their assigned projects (and themselves), and that filter runs after `limit`.

### Inspect a user

```bash
curl "http://localhost:8000/users/$USER_HASH?include_group_hierarchy=true&include_permission_details=true" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Anyone can read their own record. Root can read anyone; an admin can read non-root users who share a
project with them, otherwise `403`. The account is in `user`, with per-project `effective_permissions` and
`access_groups`.

## Change a user

### Update a username

```bash
curl -X PUT "http://localhost:8000/users/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  --data-urlencode "username=jane.doe"
```

Root, or an admin sharing a project with a non-root user. Send at least one of `username`,
`user_type`; only root may send `user_type` (see [User types](user-types.md#change-a-users-type)).
A taken username returns `409` (`CONF_5004`). The user's sessions stay valid unless `user_type`
changes, which signs them out everywhere.

### Deactivate a user

```bash
curl -X PUT "http://localhost:8000/users/$USER_HASH/status?is_active=false" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

- Root, or an admin sharing a project with a non-root user (`403` otherwise). Nobody can deactivate
  themselves (`400`).
- Returns `user_hash` and `is_active: false`. The account is deactivated and its sessions and
  refresh tokens are revoked; group memberships are kept (soft delete also deactivates them).
- No route reactivates an account: an inactive user is not found by the status route (`404`) or by
  bulk update. Plan deactivations accordingly.
- To deactivate many users, use [bulk update](bulk-operations.md).

### Send a password-reset link

```bash
curl -X POST "http://localhost:8000/users/$USER_HASH/reset-password" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

- Root, or an admin for users in their assigned projects (and themselves). Root targets are refused
  with `400`.
- No body. No password is set and none is returned. The link goes to the user's primary activated
  address, else their earliest-activated one. The user finishes with `POST /auth/password/reset`
  and then signs in again.
- The link works once, and not after `EMAIL_PASSWORD_RESET_TOKEN_TTL_SECONDS` (default `3600`).
- `reset_data.has_delivery_target` is `false` when the user has no activated address; nothing is
  sent. The response does not include the token, the link or the address.
- Rate limited per target user, per calling admin and per IP (`429` with `Retry-After`); see
  [Settings](reference.md#settings).

### Soft-delete a user

```bash
curl -X DELETE "http://localhost:8000/users/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

- Root, or an admin sharing a project with a non-root user. Nobody can delete themselves.
- The account and its active group memberships are deactivated; the row, email addresses and history
  stay. Sessions and refresh tokens are revoked.

### Permanently delete a user

```bash
curl -X DELETE "http://localhost:8000/users/$USER_HASH/hard" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

> [!CAUTION]
> Hard delete is irreversible and root-only. Use deactivation or soft delete for offboarding, and
> reserve this for an explicit permanent-removal requirement, such as freeing an address for a new
> account.

- Root only (`403` for anyone else). A root cannot delete their own account (`400`), but any other
  user can be targeted, including other roots and already soft-deleted users.
- The `users` row is deleted. Foreign-key cascades remove what the user owns: sessions, API keys,
  email addresses and link tokens, external sign-in links, group memberships, direct permission-group
  grants and billing or Patreon records. Audit and ownership references are set to `NULL`; projects
  and user groups the user created are kept with no owner.
- The user's addresses become available for another account to activate.
- The response's `removed` block summarizes the deletion (`emails_unlinked` counts the addresses
  that were not already removed).

## Other tasks

| Task | Where |
| --- | --- |
| Add, activate, remove or re-point email addresses | [User email management](email-management.md) |
| Create root or admin users, change types, assign admin projects | [User types](user-types.md) |
| Deactivate or delete many users at once | [Bulk user operations](bulk-operations.md) |
| Add or remove a user from a user group | `/admin/user-groups/{group_hash}/members` in the [groups suite](../groups/README.md) |
| Grant a group access to projects | User group to project group links in the [groups suite](../groups/README.md) |
| Assign a global role | `/roles/users/{user_hash}/role` in the [roles suite](../roles/README.md) |
| Grant permission groups directly | `/permissions/users/{user_hash}/permission-groups` in the [permissions suite](../permissions/README.md) |
| Sign in, refresh, switch project, change a password | [Authentication usage](../authentication-usage-cases.md) |
