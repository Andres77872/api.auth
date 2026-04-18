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
- [What `/users/*` Does Not Manage](#what-users-does-not-manage)

---

## Route Ownership and Authentication

The users surface is split across three route families:

| Concern | Route Family | Notes |
|--------|--------------|-------|
| Self-service profile and access summary | `/users/profile`, `/users/access-summary` | Any authenticated user |
| Admin/root user operations | `/users/list`, `/users/{hash}`, `/users/{hash}/status`, `/users/{hash}/reset-password`, `/users/{hash}` | Root is global; admin visibility is mostly project-scoped |
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

You may also send `password=...`.

Operational notes:

- at least one of `username`, `email`, or `password` must be present
- the route updates the current user only; it does not let users self-change `user_type`
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

### Reset a user's password

```bash
curl -X POST "http://localhost:8000/users/$USER_HASH/reset-password" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

What the code actually does:

- admin/root only
- refuses to reset `root` user passwords
- generates a temporary password internally with `create_password_reset_data()`
- updates the password hash immediately
- returns expiry metadata and instructions
- **does not return the temporary password in the API response**; the response explicitly says it was delivered out-of-band

So yeah, if your old doc or client expectation looked for `temporary_password` in the JSON body, that is stale.

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
- **[User Types](user-types.md)**
- **[Bulk Operations](bulk-operations.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
