# Users Troubleshooting, Caveats, and Best Practices

Things that commonly confuse operators working with the users system in `api.auth`.

---

## Troubleshooting

### Admin can list some users but search seems broader

That is a real route-level caveat.

- `GET /users/list` applies explicit project-overlap filtering for admin callers
- `GET /users/search/query` checks admin/root privilege but does not apply the same overlap filtering in route code

Practical guidance:

1. use `list` for authoritative scoped operations
2. use `search` as a quick locator
3. verify the target again with `GET /users/{hash}` before changing anything

---

### Admin gets “User not in your projects”

That means the target user's accessible project set does not overlap with the admin's accessible project set.

Check:

1. the admin's assigned projects or admin groups
2. the target user's user-group/project reach
3. whether you are using the right admin account for that project area

---

### Type promotion to `admin` succeeded, but the new admin cannot operate anywhere

Most likely cause:

- the type was changed through `PATCH /users/{hash}/type` without assigning an initial project

Fix:

1. inspect current assignment with `GET /user-types/admin/{hash}/projects`
2. add a project with `POST /user-types/admin/{hash}/projects/add`
3. have the user log in again

---

### Password reset did not return the temporary password

This is current documented behavior, not necessarily an outage.

The route:

- generates a temporary password internally
- updates the password hash
- returns only expiry metadata and the instruction that delivery was out-of-band

If your support workflow needs the temporary secret visible in the API response, that is a product/code change request, not an operator mistake.

---

### Access or permission changes are not visible immediately

Common causes:

- current session still reflects earlier login context
- user-group names are cached in the auth session payload
- role/group/permission changes require re-login, refresh, or project switching before every view aligns

Practical fix order:

1. verify the admin change actually succeeded
2. refresh token or switch project if relevant
3. re-login if necessary
4. use targeted cache/session invalidation only when justified

---

### Bulk update behaves unexpectedly

This is a documented implementation risk.

The route contract suggests a field-based bulk update API, but the imported utility signature does not line up cleanly with the route call.

Practical guidance:

- validate `bulk-update` in staging first
- prefer smaller batches
- keep a rollback plan
- use individual update/status routes if the bulk path is uncertain during an incident

---

### Pagination total looks wrong on filtered admin lists

Yep. The route computes `pagination.total` with `count_users()` and does not include every later filter/scoping step.

Treat `total` as approximate when using:

- `group_filter`
- `project_filter`
- admin project-overlap visibility

---

## Current Caveats

### Two type-change endpoints exist

- `/users/{hash}/type` = simpler enum-change path
- `/user-types/{hash}/type` = stricter path with admin assignment validation

Do not treat them as equivalent.

### Some admin user-type endpoints still rely on legacy single-project helpers

`/user-types/{hash}/info` and `/user-types/users/{type}` still expose traces of the old single-project admin assumption even though the repo supports multi-project admin assignment elsewhere.

### `/users/*` is not the whole access-control system

If a user appears wrong here, the cause may actually be in:

- user-group membership
- project-group links
- role assignment
- permission-group assignment

---

## Best Practices

### 1. Prefer deactivation before deletion

Deactivation is the safest immediate lockout because it preserves the account and invalidates sessions/cache.

### 2. Promote to admin through `/user-types/{hash}/type`

That path forces you to think about project assignment up front.

### 3. Use `/users/access-summary` before escalating

It is the fastest high-signal endpoint for understanding a user's current reach.

### 4. Keep role/group management in their own route families

Trying to solve every access issue through `/users/*` is how teams create operational confusion.

### 5. Verify bulk workflows in staging

Especially `bulk-update`. Large user changes deserve proof, not vibes.

---

## Related Documentation

- **[Users Overview](README.md)**
- **[Usage](usage.md)**
- **[User Types](user-types.md)**
- **[Bulk Operations](bulk-operations.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
