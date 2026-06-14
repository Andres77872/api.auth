# Projects Request and Data Flow

How project-related requests move through the API, DB layer, stored procedures, and session lifecycle.

---

## 1. List Accessible Projects

Flow for `GET /projects`:

1. `src/routes/projects.py:list_projects()` validates the session
2. session permissions are checked for `admin`
3. admins use `list_all_projects()` or `search_projects()`
4. non-admins call `get_user_accessible_projects(user_id)`
5. non-admin results are sliced in Python with `offset:offset+limit`
6. each returned project is decorated with an `access_level`

Important runtime detail:

- non-admin listing is not DB-paginated
- `access_level` labels reflect the access path (which route family resolved the project), not granular per-project permissions; the route layer no longer calls `get_user_project_permissions()` for this

---

## 2. Create a Project

Flow for `POST /projects`:

1. the route validates the session
2. `admin` permission is required
3. the acting user is resolved for audit context
4. `db_projects.py:create_project()` runs
5. `sp_create_project` inserts into `projects`
6. `create_default_groups(project_id)` auto-builds the initial access scaffolding
7. the API returns `CreateProjectResponse`

Result: the project exists **and** already belongs to a default project group with three default user groups wired to it.

---

## 3. Get Project Details

Flow for `GET /projects/{project_hash}`:

1. validate session
2. resolve project by hash
3. resolve current user
4. allow session-level `admin`, otherwise verify the user reaches the project through `get_user_accessible_projects()`
5. load project statistics
6. load user groups for the current user
7. load project group information for the project
8. return detailed project response

This is the main “do I have access and what does this project look like?” flow.

---

## 4. List Project Members

Flow for `GET /projects/{project_hash}/members`:

1. validate session
2. require `admin` or `manage_users`
3. resolve project
4. call `get_project_members_page(project_id, limit, offset, user_type)`
5. the DB layer uses project-access resolution data to build the member page
6. each member is enriched with permissions, groups, and access level

Operational detail:

- the endpoint is paginated
- statistics in the response are computed from the current page payload plus total count

---

## 5. Delete a Project

Flow for `DELETE /projects/{project_hash}`:

1. validate session
2. require `admin`
3. resolve project
4. resolve acting user
5. `delete_project(project.id, deleted_by=user_id)` runs
6. `sp_delete_project` soft-deactivates the project, linked project-group memberships, and active sessions
7. API returns success with a warning

So deletion is not a cosmetic hide. It actively tears down project visibility and live sessions.

---

## 6. Resolve Access Internally

The core runtime access path is:

```text
user_group_members
  → user_groups
  → user_group_project_groups
  → project_groups
  → project_group_members
  → projects
```

This is used by:

- project listing for non-admin users
- login project selection
- switch-project validation
- member views through `v_user_project_access`

Without every link in that chain, the user does not reach the project. Simple as that.

---

## 7. Login with Project Context

Flow for `POST /auth/login`:

1. credentials are verified
2. ALL users MUST provide `project_hash`; root bypasses group validation and may access any project
3. root users lookup the requested project directly
4. non-root users call `get_user_accessible_projects(user_id)`
5. `project_hash` is validated against the accessible list (non-root) or directly (root)
6. `_create_session()` issues a project-bound session
7. cookie is set and accessible projects are returned to the client

This is where project context becomes part of the session contract.

---

## 8. Switch Project Context

Flow for `POST /auth/switch-project`:

1. current session is loaded from the token
2. user is resolved from the session payload
3. target project is resolved by hash
4. `get_user_accessible_projects(user_id)` verifies access
5. `_create_session(user, new_project)` issues a new project-bound session
6. old session is deleted
7. new cookie and project info are returned

The response also includes `user_groups` that intersect the user and the new project.

---

## 9. Archive and Ownership Transfer Stubs

Both of these flows stop at the route layer today:

- `PATCH /projects/{hash}/owner` — required form field `new_owner_hash`
- `PATCH /projects/{hash}/archive` — required form field `archived` (bool)

Flow for `PATCH /projects/{hash}/owner`:

1. validate session
2. require `admin`
3. resolve project by hash
4. resolve `new_owner_hash` (raises `USER_NOT_FOUND` if it does not exist)
5. raise `FeatureNotImplementedError` (`501`)

Flow for `PATCH /projects/{hash}/archive`:

1. validate session
2. require `admin`
3. resolve project by hash
4. raise `FeatureNotImplementedError` (`501`)

So if you were expecting a deeper runtime flow here, ni en pedo — it doesn't exist yet.

Note the distinction: even though the `PATCH /archive` **route** is a stub, archive **enforcement** is live elsewhere. Commit `4e6e5de` made the login, project-token, API-key, and session-validation flows exclude archived projects, so a project whose `archived` flag is already set in the database is denied at auth time. There is simply no API route that flips that flag yet.

---

## Related Documentation

- **[Projects Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: June 2026  
**Document Version**: 1.1
