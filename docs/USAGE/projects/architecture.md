# Projects Architecture

Technical architecture of the projects system as it actually exists in `api.auth`.

---

## Core Access Model

Projects are resolved through the active runtime chain:

```
USER → USER_GROUP → PROJECT_GROUP → PROJECT
```

That means:

- projects are not directly assigned to users
- user groups do not directly point to projects in the active model
- project groups are the reusable access containers in the middle

---

## Real Tables Behind the Model

| Table | Purpose |
|------|---------|
| `projects` | Core project records, owner, archived state, soft-delete state |
| `project_groups` | Reusable project containers |
| `project_group_members` | Project-to-project-group membership |
| `user_group_project_groups` | User-group-to-project-group access bridge |
| `user_sessions` | Active session records tied to current project context |
| `api_audit_log` | Project-visible operational activity source |

Access resolution also depends on the view `v_user_project_access`.

---

## Route and Layer Split

### Project operations
- Route file: `src/routes/projects.py`
- DB layer: `src/Util/db/db_projects.py`
- Stored procedures: `schemas/stored_procedures/03_projects.sql`

### Project-group operations
- Route file: `src/routes/admin_project_groups.py`
- DB layer: `src/Util/db/db_project_groups.py`
- Stored procedures: `schemas/stored_procedures/04_project_groups.sql`

### Access resolution and session context
- Route file: `src/routes/auth.py`
- DB layer: `src/Util/db/db_user_groups.py`
- View: `schemas/tables/06_create_views.sql`

---

## Access Resolution Backbone

Two repo artifacts matter most:

### `sp_get_user_accessible_projects`

- root users get all active projects through a special branch
- non-root users are resolved through the join chain:

```text
user_group_members
  → user_groups
  → user_group_project_groups
  → project_groups
  → project_group_members
  → projects
```

### `v_user_project_access`

This view exposes the effective user-to-project access map and is used by member/statistical flows.

It includes:

- `group_access` rows for normal users
- `root_access` rows for root users across active, non-archived projects

---

## Project Creation Bootstrap

`src/Util/db/db_projects.py:create_project()` inserts the project and immediately calls `create_default_groups(project_id)`.

That bootstrap function:

1. creates a default project group
2. links the new project to that project group
3. creates three default user groups: `admin_{project_id}`, `user_{project_id}`, `readonly_{project_id}`
4. links all three user groups to the default project group

Important detail: this logic is implemented with raw SQL inserts in Python, not through dedicated stored procedures.

---

## Authorization Split

The project surface is not guarded uniformly.

| Area | Permission Gate |
|------|-----------------|
| `POST /projects`, `PUT /projects/{hash}`, `DELETE /projects/{hash}` | `admin` |
| `GET /projects/{hash}/members` | `admin` or `manage_users` |
| `/admin/project-groups/*` | `admin` or `manage_roles` |
| `/admin/user-groups/{hash}/project-groups/*` | `admin` or `manage_users` |

So project access administration is split across at least two admin capabilities.

---

## Login and Session Architecture

Project context is embedded during login and project switching.

### Login

`src/routes/auth.py:login()`:

- resolves accessible projects
- binds non-root users to a requested or default project
- issues a session containing project context
- also exposes `accessible_projects` to the client

### Switch project

`src/routes/auth.py:switch_project()`:

- validates the current session
- verifies the requested project is in `get_user_accessible_projects()`
- creates a new session bound to the new project
- deletes the old session

So when access changes, session refresh or re-login may be required before the client sees the new reality.

---

## Soft Deletes and Archive State

Project deletion is implemented as soft delete:

- `projects.is_active = 0`
- linked `project_group_members` rows are deactivated
- active `user_sessions` for that project are invalidated

Archive is a separate concept in the schema (`archived`, `archived_at`, `archived_by`), but the public archive endpoint is still a stub.

---

## Important Current Caveats

### Two public project endpoints are stubs

- `PATCH /projects/{hash}/owner` → 501
- `PATCH /projects/{hash}/archive` → 501

### `access_level` uses honest path-based labels (fixed)

Project routes no longer derive `access_level` from `get_user_project_permissions()` (which returns global permissions). Instead:

- Admin users → `"admin_access"`
- Non-admin users with group-based access → `"group_access"`
- Member lists use user type → `"root_access"`, `"admin_access"`, or `"group_access"`

The `get_user_project_permissions()` function still exists in the DB layer but is no longer called by project routes.

### Access checks use the groups-of-groups chain (fixed)

`GET /projects/{hash}`, `GET /projects/{hash}/activity`, and `GET /projects/{hash}/stats` now verify non-admin access by checking `get_user_accessible_projects()` instead of relying on global permissions. This means consumers with valid group-based access are no longer incorrectly denied.

### Non-admin project listing still slices in Python

`GET /projects` for non-admin users fetches all accessible projects first, then slices in Python.

Pagination metadata (`total`, `has_more`) is now correct, but the fetch-all-then-slice pattern remains a memory concern at large scale.

### The `Project` model lags the table shape

The SQL layer returns fields like `owner_id` and `archived`, but the Python `Project` model used in several places does not expose all of them cleanly.

---

## Related Documentation

- **[Projects Overview](README.md)**
- **[Usage](usage.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
