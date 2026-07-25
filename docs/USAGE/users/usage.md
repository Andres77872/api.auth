# Users Usage

Practical usage guide for operating user-management endpoints in `api.auth`.

---

## 📖 Table of Contents

- [Route Ownership and Authentication](#route-ownership-and-authentication)
- [Profile Operations](#profile-operations)
- [Access Summary](#access-summary)
- [List and Search Users](#list-and-search-users)
- [Inspect and Update a Specific User](#inspect-and-update-a-specific-user)
- [Status, Password Reset, and Deletion](#status-password-reset-and-deletion)
- [Email Management](#email-management)
- [What `/users/*` Does Not Manage](#what-users-does-not-manage)

---

## Route Ownership and Authentication

The users surface is split across three route families:

| Concern | Route Family | Notes |
|--------|--------------|-------|
| Self-service profile and access summary | `/users/profile`, `/users/access-summary` | Any authenticated user |
| Self-service email management | `/users/me/emails`, `/users/me/emails/{id}/resend`, `/users/me/emails/{id}`, `/users/me/emails/{id}/primary` | Any authenticated user; full lifecycle in [email-management.md](email-management.md) |
| Admin/root user operations | `/users/list`, `/users/{hash}`, `/users/{hash}/status`, `/users/{hash}/reset-password`, `/users/{hash}`, `/users/{hash}/emails`, `/users/{hash}/emails/{id}/resend` | Root is global; admin visibility is mostly project-scoped |
| Type lifecycle and root-only creation | `/user-types/*` | Covered in [user-types.md](user-types.md) |

Request-shape reality:

- `PUT /users/profile` and `PUT /users/{hash}` use form fields
- `PUT /users/{hash}/status` uses query parameter `is_active`
- `GET` endpoints use query parameters

---

## Profile Operations

### Get current profile

```bash
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $TOKEN"
```

What this does in the repo:

- loads the current `users` row by `user_hash`
- loads `get_user_type_info(user.id)` for capability metadata
- loads current user groups through `get_user_groups_for_user()`
- loads accessible projects through `get_user_accessible_projects()`
- adds per-project effective permissions with `get_user_effective_permissions()`

The response is intentionally richer than a plain account record. It is an operational snapshot of the user, their memberships, and their reachable projects.

### Update current profile

```bash
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_username&email=new@example.com"
```

Operational notes:

- at least one of `username` or `email` must be present
- the route updates the current user only; it does not let users self-change `user_type`
- password-equivalent fields are rejected; use `POST /auth/password/change` for authenticated password rotation
- successful updates invalidate user cache through the DB layer

---

## Access Summary

`GET /users/access-summary` is the best operator-facing endpoint when you need the full "why can this user reach these projects?" view.

```bash
curl -X GET "http://localhost:8000/users/access-summary" \
  -H "Authorization: Bearer $TOKEN"
```

What it assembles:

- current user identity and `user_type`
- user-group memberships and assignment metadata
- accessible projects resolved through the groups-of-groups chain
- effective permissions per project
- current session project context summary

Use this when a user says "I can log in but I don't know what I actually have access to".

---

## List and Search Users

### List users with filters

```bash
curl -X GET "http://localhost:8000/users/list?limit=25&offset=0&sort_by=username&sort_order=asc&user_type_filter=consumer&include_inactive=false" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Useful filters:

- `search`
- `user_type_filter`
- `group_filter`
- `project_filter`
- `include_inactive`
- `include_group_info`
- `include_project_access`

Operational behavior from the route code:

- **root** sees the full result set
- **admin** can only keep users who share at least one accessible project with the admin, except the admin can always see themselves
- user groups and projects are hydrated from aggregated JSON returned by `sp_list_users_with_access`
- `pagination.total` comes from `count_users()` and **does not include group/project filters**, so it can overstate the effective admin-visible result set

### Quick search

```bash
curl -X GET "http://localhost:8000/users/search/query?q=john&user_type_filter=consumer&limit=50" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Important caveat:

- this endpoint checks that the caller is admin/root, but unlike `GET /users/list` it does **not** apply the same explicit project-overlap filter in route code
- treat it as a faster lookup endpoint, not a perfect mirror of list scoping

---

## Inspect and Update a Specific User

### Get user details

```bash
curl -X GET "http://localhost:8000/users/$USER_HASH?include_group_hierarchy=true&include_permission_details=true" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Behavior:

- users may inspect their own record
- root may inspect any user
- admin may inspect users only when there is project overlap between the admin's accessible projects and the target user's accessible projects

The detail response is built from:

- base user record
- `get_user_type_info()`
- user-group memberships
- accessible projects
- optional per-project effective permissions and access-group breakdown

### Update user details

```bash
curl -X PUT "http://localhost:8000/users/$USER_HASH" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=updated_user&email=updated@example.com"
```

Operational rules:

- root or admin may update username/email
- admin must still satisfy project-overlap checks
- only **root** may send `user_type`
- if no fields are provided, the route rejects the request

If you need a type change that also enforces admin-project assignment rules, use the stricter `/user-types/{hash}/type` route documented in [user-types.md](user-types.md).

---

## Status, Password Reset, and Deletion

### Activate or deactivate a user

```bash
curl -X PUT "http://localhost:8000/users/$USER_HASH/status?is_active=false" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Important behavior:

- root can change any user's status
- admin can change status only for users in overlapping accessible projects
- non-root users cannot deactivate root users
- users cannot deactivate themselves
- **deactivation** triggers both `invalidate_user_sessions()` and `cache_manager.invalidate_user_cache()`

That means this is the main emergency lockout path.

### Queue an admin password-reset link

```bash
curl -X POST "http://localhost:8000/users/$USER_HASH/reset-password" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

This is a body-less POST (no form/JSON fields are read).

What the code actually does:

- admin/root only
- refuses to reset `root` user passwords
- creates hash-only `admin_password_reset` link-token metadata
- enqueues a reset-link email through the durable outbox when the target has a primary activated email
- returns accepted metadata and safe instructions
- **does not return or generate a visible temporary password**; no reset token, reset URL, full email, subject/body, or provider payload is exposed

Do not expect a temporary password in the JSON body. Clients that still depend on that legacy behavior must migrate to the reset-link flow.

### Soft-delete a user

```bash
curl -X DELETE "http://localhost:8000/users/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Delete behavior in the repo:

- this is a soft delete (`users.is_active = 0`)
- `sp_delete_user` also deactivates active `user_group_members` rows for that user
- the route invalidates Redis sessions and user cache after deletion
- users cannot delete themselves
- non-root users cannot delete root users

### Permanently delete a user (ROOT only)

```bash
curl -X DELETE "http://localhost:8000/users/$USER_HASH/hard" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

This is a destructive deep-clean operation, not the normal offboarding path:

- only a root may call it, and a root cannot delete their own account;
- inactive/soft-deleted users may still be targeted;
- the user row and owned identity content are permanently removed through
  foreign-key cascade;
- the user's email rows are released for future registration;
- shared projects and user groups are preserved with ownership cleared;
- lingering sessions and cache state are revoked after the database deletion.

Use status deactivation or soft delete for recoverable operational lockout.
Reserve hard delete for an explicit permanent-removal requirement.

---

## Email Management

A user can hold multiple emails. The `/users/me/emails*` group is self-service
(any authenticated user, acting on their own `user_id`); the
`/users/{user_hash}/emails*` group is root/admin only. Email is optional — these
routes only matter when a user wants email login or recovery. Full lifecycle
detail (status model, owner vs admin field views, response examples) lives in
[email-management.md](email-management.md).

### List your emails

```bash
curl -X GET "http://localhost:8000/users/me/emails" \
  -H "Authorization: Bearer $TOKEN"
```

Returns the caller's `user_emails` rows in the owner view (includes the
normalized `email`, `email_masked`, `status`, `is_primary`, and lifecycle
timestamps).

### Add an email (enqueue activation)

```bash
curl -X POST "http://localhost:8000/users/me/emails" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Idempotency-Key: $(uuidgen)" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=new@example.com"
```

The `email` field may be form or JSON. The route adds/reuses a `pending` row,
enqueues a hash-only activation link, and returns a generic `202`.

### Resend activation

```bash
curl -X POST "http://localhost:8000/users/me/emails/$EMAIL_ID/resend" \
  -H "Authorization: Bearer $TOKEN"
```

### Remove an email / change the primary email

```bash
curl -X DELETE "http://localhost:8000/users/me/emails/$EMAIL_ID" \
  -H "Authorization: Bearer $TOKEN"

curl -X POST "http://localhost:8000/users/me/emails/$EMAIL_ID/primary" \
  -H "Authorization: Bearer $TOKEN"
```

Key operational behavior from the route code:

- **Generic `202`** is returned by add/resend regardless of whether a row
  actually changed; enqueue failures are swallowed and still return `202`. You
  cannot infer existence or delivery from the body.
- **`429 + Retry-After`** is the only detailed public response (rate limiter and
  resend cooldown). The resend cooldown is `EMAIL_RESEND_COOLDOWN_SECONDS`
  (default **60s**).
- **`Idempotency-Key`** (optional) is honored on `POST /users/me/emails` and the
  owner resend; the admin resend does not read it.
- **Session revocation**: removing an email (reason `email_removed`) or setting a
  new primary (reason `email_primary_changed`) revokes the user's *other*
  sessions while preserving the current one when possible. Other devices must
  re-authenticate.

### Admin/root email endpoints

```bash
# List a target user's emails (masked/hash-only view)
curl -X GET "http://localhost:8000/users/$USER_HASH/emails" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Re-trigger activation for a target user's email
curl -X POST "http://localhost:8000/users/$USER_HASH/emails/$EMAIL_ID/resend" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

The admin list view never returns the plaintext address (only `email_masked` and
`email_hash`). The admin resend returns a generic `202` and is subject to the
same rate limit and cooldown.

---

## What `/users/*` Does Not Manage

Do **not** use the `/users/*` routes for these tasks:

- **add/remove user from user groups** → use `/admin/user-groups/.../members`
- **grant/revoke project reach** → use user-group ↔ project-group wiring in the groups suite
- **assign/remove global role** → use `/roles/users/{user_hash}/role`
- **assign/remove permission groups** → use `/permissions/...`

In other words: `/users/*` manages the user entity and its immediate lifecycle. Access topology lives elsewhere.

---

## Related Documentation

- **[Users Overview](README.md)**
- **[Email Management](email-management.md)**
- **[User Types](user-types.md)**
- **[Bulk Operations](bulk-operations.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Document Version**: 1.1
