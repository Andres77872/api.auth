# Projects

A project is the tenant every session is scoped to: users log in to one project at a time with its
`project_hash`, and API keys belong to one project. Root users create projects; root and the admin
users assigned to a project administer it; consumers read the projects they reach through their
groups. Project routes live under `/projects` in `src/routes/projects.py`.

## Key concepts

- **Project hash**: `project_hash`, 64 upper-case hex characters, identifies a project in every
  API call. The internal ID (`proj-<uuid>`) is not returned by project routes, but it appears in the
  names of the default groups.
- **Default groups**: `POST /projects` also creates a project group `default_<project_id>`
  containing the project and three user groups granted to it: `admin_<project_id>`,
  `user_<project_id>` and `readonly_<project_id>`. All three start empty. They are ordinary groups
  managed through the [groups suite](../groups/README.md).
- **Reach**: users reach a project only through user group, project group and grant
  (`USER -> USER_GROUP -> PROJECT_GROUP -> PROJECT`). There is no direct user-to-project
  assignment. Root reaches every active, non-archived project.
- **Admin scope**: root administers every project. An admin user administers the projects whose
  `admin_<project_id>` group they belong to. Nobody else has admin scope, whatever permission
  names their session carries.
- **Deleted vs archived**: `DELETE /projects/{project_hash}` sets `is_active = 0`; the project then
  returns `404` everywhere. `archived` is a separate flag that no API route can change, but that
  every auth path enforces.

## Route families

| Concern | Prefix | Who |
| --- | --- | --- |
| Create a project | `POST /projects` | Root only |
| List projects | `GET /projects` | Any authenticated user; results depend on user type |
| Read one project: details, activity, statistics | `/projects/{project_hash}`, `/activity`, `/stats` | Root, an admin of the project, or a user who reaches it through groups |
| Administer one project: update, delete, members, groups, owner, archive | `/projects/{project_hash}` and sub-routes | Root or an admin of the project |
| Give users access to a project | `/admin/project-groups`, `/admin/user-groups` | See the [groups suite](../groups/README.md) |

Endpoint tables, fields and response shapes are in [reference.md](reference.md).

## Rules and caveats

Platform-wide rules (User-Agent, body size, error envelope) are in
[Platform-wide contracts](../README.md#platform-wide-contracts).

- **Session permission names do not grant project administration.** Project routes read the
  caller's user type and admin assignments live from the database. A consumer whose global role
  carries `admin` or `manage_users` is still a consumer here and gets `403` on admin routes.
- **Writes take form fields** (`application/x-www-form-urlencoded` or `multipart/form-data`).
- **Two routes are stubs.** `PATCH /projects/{project_hash}/owner` and
  `PATCH /projects/{project_hash}/archive` validate the request, then always return `501`
  `INT_7006`. Ownership and the archive flag never change through the API.
- **Archive enforcement is live.** A project with `archived` set in the database is left out of
  listings and group reach, and login, project switching, token validation and API-key validation
  refuse it. Root can still read and update it by hash.
- **Statistics count group access, not sessions.** `statistics` in `GET /projects/{project_hash}`
  and `GET /projects/{project_hash}/stats` counts users and groups reached through the group chain;
  root users are not counted and `active_sessions` is always `null`
  ([fields](reference.md#project-statistics)).
- **Deleting a project keeps its default groups.** The project leaves every project group and its
  sessions stop validating, but `default_<project_id>` and the three user groups remain.

## In this suite

| Document | Purpose |
| --- | --- |
| [usage.md](usage.md) | Task-by-task requests: create, list, inspect, update, delete, audit access |
| [scenarios.md](scenarios.md) | End-to-end workflows: new project with its first admin, onboarding users, audits, retirement |
| [reference.md](reference.md) | Endpoints, authorization matrix, fields, query parameters, response shapes, error codes |
| [request-flow.md](request-flow.md) | What happens to each project request, and how project state affects sessions |
| [architecture.md](architecture.md) | Table, stored procedures, default-group bootstrap, admin scope, archive enforcement, known defects |
| [troubleshooting.md](troubleshooting.md) | Symptom, cause and fix for common project problems |

## Related

- [Groups](../groups/README.md): the access chain and how to grant or revoke reach
- [Users](../users/README.md) and [user types](../users/user-types.md): admin project assignment
- [Authentication usage cases](../authentication-usage-cases.md): project-scoped login and
  switch-project
- [API keys](../api-keys/README.md): project-scoped keys
