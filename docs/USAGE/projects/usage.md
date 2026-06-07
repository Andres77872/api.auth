# Projects Usage

Practical usage guide for operating projects in `api.auth`.

---

## 📖 Table of Contents

- [Authentication and Route Ownership](#authentication-and-route-ownership)
- [Creating Projects](#creating-projects)
- [Inspecting Projects](#inspecting-projects)
- [Updating Projects](#updating-projects)
- [Managing Access Through Groups](#managing-access-through-groups)
- [Deleting Projects](#deleting-projects)
- [Known Unimplemented Operations](#known-unimplemented-operations)

---

## Authentication and Route Ownership

Projects are operated across three route families:

| Concern | Route Family | Notes |
|--------|--------------|-------|
| Project CRUD, members, stats, activity | `/projects` | Mostly requires valid session; create/delete require `admin` |
| Project-group CRUD and project assignment | `/admin/project-groups` | Requires `admin` or `manage_roles` |
| User-group to project-group access bridge | `/admin/user-groups/{hash}/project-groups` | Requires `admin` or `manage_users` |

**Important:** current project write endpoints use `application/x-www-form-urlencoded`.

---

## Creating Projects

Create a project with:

```bash
curl -X POST "http://localhost:8000/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_name=Customer API v2&project_description=New customer management API"
```

What the repo actually does:

1. `src/routes/projects.py:create_new_project()` validates the session
2. only users with `admin` in session permissions can proceed
3. `src/Util/db/db_projects.py:create_project()` calls `sp_create_project`
4. `create_default_groups(project_id)` runs immediately after insert

### The critical side effect: `create_default_groups()`

New projects do **not** start empty. The DB layer auto-creates:

- one default project group: `default_{project_id}`
- three default user groups:
  - `admin_{project_id}`
  - `user_{project_id}`
  - `readonly_{project_id}`
- links from each default user group to the default project group

So before you create extra groups manually, dejate de joder and verify whether the generated defaults already solve the use case.

---

## Inspecting Projects

### List projects

```bash
curl -X GET "http://localhost:8000/projects?limit=20&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

- admins see all projects through `list_all_projects()` / `search_projects()`
- non-admin users get projects from `get_user_accessible_projects()`
- the returned `access_level` is path-based (`group_access` for group-derived users, `admin_access` for admin paths), not derived from `get_user_project_permissions()`; see [architecture.md](architecture.md)

### Get project details

```bash
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

The details route checks project access, loads project statistics, and returns the project plus access-context information.

### Get operational views

```bash
# Members with effective access
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH/members?limit=50&offset=0" \
  -H "Authorization: Bearer $TOKEN"

# User groups with access to the project
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH/groups" \
  -H "Authorization: Bearer $TOKEN"

# Activity feed
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH/activity?days=30" \
  -H "Authorization: Bearer $TOKEN"

# Statistics
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH/stats" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Updating Projects

Update metadata with:

```bash
curl -X PUT "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_name=Customer API v2&project_description=Updated description"
```

This updates the `projects` row through `sp_update_project`.

Use updates for naming and descriptive cleanup. Do **not** expect this to change access; access is managed through group links, not project metadata.

---

## Managing Access Through Groups

This repo does **not** support direct user-to-project assignment.

The live architecture is:

```text
user → user_group → project_group → project
```

### Add a project to a project group

```bash
curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$PROJECT_HASH"
```

### Grant a user group access to that project group

```bash
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$PROJECT_GROUP_HASH"
```

### Revoke access

```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/project-groups/$PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Operationally:

- add/remove users from user groups under `/admin/user-groups/.../members`
- add/remove projects from project groups under `/admin/project-groups/.../projects`
- grant/revoke team reach through `/admin/user-groups/.../project-groups`

That separation is not optional. Mixing access and capability concerns is how people create a quilombo.

---

## Deleting Projects

Delete a project with:

```bash
curl -X DELETE "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Current delete behavior is a **soft delete**:

- `projects.is_active = 0`
- matching `project_group_members` rows are deactivated
- active `user_sessions` for that project are invalidated

The API warns that user-group access to the project has been revoked. That's accurate enough operationally, but the important detail is that the actual cascade happens through project membership deactivation, not by deleting user groups.

---

## Known Unimplemented Operations

Two project endpoints exist but currently return `501 Feature Not Implemented`:

- `PATCH /projects/{project_hash}/owner`
- `PATCH /projects/{project_hash}/archive`

Relevant caveat:

- the SQL stored procedures `sp_archive_project` and `sp_unarchive_project` exist
- the Python route implementation still raises `FeatureNotImplementedError`
- ownership transfer does not even have a stored procedure yet

So no, those routes are not production-ready just because they show up in the router.

---

## Related Documentation

- **[Projects Overview](README.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
