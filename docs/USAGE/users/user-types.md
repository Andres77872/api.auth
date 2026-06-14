# Users User Types and Admin Assignment

Practical guide for the 3-tier user-type model and the `/user-types/*` lifecycle endpoints.

---

## 3-Tier Model

The repo implements three user types at the `users.user_type` level:

| Type | Operational meaning | Practical scope |
|------|---------------------|-----------------|
| `root` | Global system operator | Can create root/admin users and bypass normal project scoping |
| `admin` | Project-scoped operator | Reach comes from assignment to admin groups for one or more projects |
| `consumer` | Regular end user | Reach comes from normal user-group membership |

Capabilities returned by `get_user_type_info()` reflect this split:

- root: `unrestricted_access`, `global_admin`, `create_root_users`, `manage_all_projects`, `manage_all_users`
- admin: `project_admin`, `manage_project_users`, `manage_project_groups`, `manage_project_permissions`
- consumer: `global_role_permissions`, `group_based_access`, `project_access_via_groups`

---

## Create a Root User

`POST /user-types/root` is root-only.

```bash
curl -X POST "http://localhost:8000/user-types/root" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_root&password=SecurePassword123!&email=root@example.com"
```

What this does in the repo:

- calls `create_root_user()`
- inserts a `users` row with `user_type='root'`
- does **not** require project assignment

---

## Create an Admin User

`POST /user-types/admin` is also root-only, but unlike root creation it requires project assignment.

```bash
curl -X POST "http://localhost:8000/user-types/admin" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_admin&password=SecurePassword123!&email=admin@example.com&assigned_project_ids=1&assigned_project_ids=2"
```

Operational behavior:

- you must provide either `assigned_project_id` or repeated `assigned_project_ids`
- the route validates that every referenced project exists
- the DB layer creates the user first and then adds the user to the admin group for each assigned project
- the first project is returned as `primary_project_id` for legacy compatibility

This is the safest creation path because it guarantees the admin starts with real project reach.

---

## Get User Type Information

```bash
curl -X GET "http://localhost:8000/user-types/$USER_HASH/info" \
  -H "Authorization: Bearer $TOKEN"
```

Behavior notes:

- root may inspect any user
- admin access here is **not fully aligned** with the multi-project model; the route still uses legacy `get_admin_assigned_project()` checks in part of its authorization logic
- for admin users, the response includes `assigned_projects` and `total_assigned_projects`

Operational recommendation:

- use this endpoint for user-type capabilities and admin project assignment metadata
- use `GET /users/{hash}` when you need the richer membership/project breakdown

---

## Change User Type With Assignment Rules

### Preferred path: `PUT /user-types/{hash}/type`

```bash
curl -X PUT "http://localhost:8000/user-types/$USER_HASH/type" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_type=admin&assigned_project_id=1"
```

This route is stricter than `/users/{hash}/type`:

- root only
- validates `user_type`
- when promoting to `admin`, it **requires** `assigned_project_id`
- validates that the assigned project exists
- calls `update_user_type(..., project_id=assigned_project_id)` so the initial admin-project link is created

### Overlapping path: `PATCH /users/{hash}/type`

This older route also changes `user_type`, but it only sends the new enum value:

```bash
curl -X PATCH "http://localhost:8000/users/$USER_HASH/type" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_type=admin"
```

Important caveat:

- this route does **not** require `assigned_project_id`
- promoting a user to `admin` here can leave them with the admin type but without any assigned admin project until you add one later

Operationally, use `/user-types/{hash}/type` for admin promotions. Keep `/users/{hash}/type` for the simpler enum-only path when you explicitly want that behavior.

---

## List Users by Type

```bash
curl -X GET "http://localhost:8000/user-types/users/admin?limit=50&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

Behavior from the route code:

- root can list any type globally
- admin cannot list `root` users
- admin listing for `admin` and `consumer` uses `get_admin_assigned_project()` (single-project legacy helper), not the full multi-project assignment set
- returned admin records expose one `assigned_project` field, also reflecting legacy-first-project behavior

So if an admin is assigned to multiple projects, this endpoint is useful but not a perfect expression of the multi-project model.

---

## User Type Statistics

```bash
curl -X GET "http://localhost:8000/user-types/stats" \
  -H "Authorization: Bearer $TOKEN"
```

What it returns:

- total counts for root/admin/consumer
- percentages
- system metadata (`3-tier`, `hierarchical`, feature flags)
- a `scope` block

Caveat:

- the route text says admins see project-scoped stats, but the counts themselves are derived from global `count_users()` calls; only the `scope` object is adjusted for admin callers

---

## Admin Project Assignment Lifecycle

These routes are root-only and should be treated as the authoritative admin assignment workflow.

### Inspect assigned projects

```bash
curl -X GET "http://localhost:8000/user-types/admin/$ADMIN_HASH/projects" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

### Replace all assignments

```bash
curl -X PUT "http://localhost:8000/user-types/admin/$ADMIN_HASH/projects" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "assigned_project_ids=1&assigned_project_ids=3&assigned_project_ids=5"
```

What the code does:

- verifies target user is an admin
- validates each incoming project exists
- removes assignments not in the new list
- adds assignments that are missing
- ignores individual add/remove failures internally and continues

### Add one project

```bash
curl -X POST "http://localhost:8000/user-types/admin/$ADMIN_HASH/projects/add" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_id=4"
```

This route looks up the admin group for the project and adds the admin user to that group.

### Remove one project

```bash
curl -X DELETE "http://localhost:8000/user-types/admin/$ADMIN_HASH/projects/4" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

This removes the admin user from the matching admin group membership for that project.

---

## Related Documentation

- **[Users Overview](README.md)**
- **[Usage](usage.md)**
- **[Email Management](email-management.md)**
- **[Bulk Operations](bulk-operations.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: June 2026  
**Document Version**: 1.0
