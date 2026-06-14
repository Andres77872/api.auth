# Projects Troubleshooting, Caveats, and Best Practices

Things that commonly confuse operators working with projects in `api.auth`.

---

## Troubleshooting

### User cannot access a project

Check the full chain.

1. Is the user in the expected user group?
   ```bash
   curl -X GET "http://localhost:8000/admin/user-groups/users/$USER_HASH/groups" \
     -H "Authorization: Bearer $TOKEN"
   ```
2. Does that user group have the right project-group link?
   ```bash
   curl -X GET "http://localhost:8000/admin/user-groups/$GROUP_HASH/project-groups" \
     -H "Authorization: Bearer $TOKEN"
   ```
3. Does the project group actually contain the project?
   ```bash
   curl -X GET "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH" \
     -H "Authorization: Bearer $TOKEN"
   ```
4. Can the user see the project through login or access summary?

If any link in `user -> user_group -> project_group -> project` is missing, access fails.

---

### Too many users have access to a project

Audit from the project side first.

```bash
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH/members?limit=100" \
  -H "Authorization: Bearer $TOKEN"

curl -X GET "http://localhost:8000/projects/$PROJECT_HASH/groups" \
  -H "Authorization: Bearer $TOKEN"
```

Typical fix order:

1. identify the user group creating the blast radius
2. revoke its project-group link if the whole team should lose access
3. otherwise remove only the wrong members from that user group

---

### Group changes are not reflecting immediately

Common causes:

- the user's session still carries old project context
- login selected an older project snapshot
- the user needs to re-login or use `/auth/switch-project`

Practical fix order:

1. verify the access links through admin endpoints
2. have the user switch project or log in again
3. if the project was deleted, remember its active sessions were invalidated

---

### Project does not appear after creation

Check two things:

1. the project record exists
2. the expected user or team is linked into the generated default or broader project groups

New projects only auto-create the default scaffolding. They do **not** automatically add your existing team members into `admin_{project_id}` or `user_{project_id}`.

That misunderstanding burns people constantly.

---

### Project switch fails even though the user “should” have access

Verify access through `get_user_accessible_projects()`-equivalent behavior, not through vibes.

If the user can’t see the project in their accessible list at login time, `/auth/switch-project` will reject it with `PROJECT_ACCESS_DENIED`.

---

## Current Caveats

### Ownership transfer and archive routes are not implemented

Both public endpoints exist, validate some state, then return `501`:

- `PATCH /projects/{hash}/owner` (form field `new_owner_hash`)
- `PATCH /projects/{hash}/archive` (form field `archived`)

Do not confuse the archive **endpoint** with archive **enforcement**. The `PATCH /archive` route is a `501` stub and there is no live API route that sets the `archived` flag. However, if a project's `archived` flag is already set in the database, that project is excluded from authorization workflows (logins, project tokens, API-key validation, session validation) as of commit `4e6e5de`. So you may see a project denied at auth time "for no reason" — check whether it is archived in the database, because no endpoint will surface or toggle that state for you.

### `access_level` labels reflect access path, not granular permissions

`GET /projects`, `GET /projects/{hash}`, and `GET /projects/{hash}/members` now report honest access labels:

- `"admin_access"` — user has global admin permission
- `"group_access"` — user reaches the project through the groups-of-groups chain
- `"root_access"` — root user (only in member lists)

The old behavior derived `access_level` from `get_user_project_permissions()`, which returned **global** permissions and ignored `project_id`. That meant a consumer with global `read` appeared as "read-only" on every project, and an admin appeared as "admin" everywhere — neither reflecting actual project-scoped reality.

The function `get_user_project_permissions()` still exists in the DB layer as a backward-compat shim, but project routes no longer use it for access-level computation.

### Non-admin project listing still slices in Python

`GET /projects` for non-admin users fetches all accessible projects first, then slices in Python.

The `pagination.total` field now correctly reports the full accessible count (not the page size), and `has_more` uses proper offset arithmetic. But the fetch-all-then-slice pattern remains — a memory concern at large scale.

### Root access excludes archived projects in the access view

`v_user_project_access` only includes active, non-archived projects for the root-access branch.

---

## Best Practices

### 1. Reuse project groups for shared reach

If multiple teams or multiple projects repeat the same pattern, use project groups intentionally instead of treating them like a random middle table.

### 2. Check generated defaults before creating custom groups

Every project already gets a starter kit from `create_default_groups()`.

### 3. Separate project reach from capability

- project groups decide where a user can go
- permission groups and roles decide what a user can do there

### 4. Use project-side verification after access changes

After changing access, verify with:

- `GET /projects/{hash}/members`
- `GET /projects/{hash}/groups`
- user re-login or `/auth/switch-project`

### 5. Treat deletes as operationally destructive

Soft delete is still destructive enough to remove active visibility and invalidate project sessions.

---

## Related Documentation

- **[Projects Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**

---

**Last Updated**: June 2026  
**Document Version**: 1.1
