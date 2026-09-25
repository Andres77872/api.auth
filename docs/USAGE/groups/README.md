# Groups

Groups decide which projects a user can reach. A **user group** collects users, a **project group**
collects projects, and a grant between the two gives every member of the user group access to every
active, non-archived project in the project group. Root users, admin users and consumers whose
global role carries the right permission manage groups through `/admin/user-groups` and
`/admin/project-groups`.

## Key concepts

```text
USER -> USER_GROUP -> PROJECT_GROUP -> PROJECT
          |
          +-> PERMISSION_GROUP -> PERMISSIONS   (separate; see the permissions suite)
```

- **User group** (`user_groups`): a global set of users, not tied to one project. Membership rows
  live in `user_group_members`.
- **Project group** (`project_groups`): a container of projects. Assignment rows live in
  `project_group_members`. Project groups carry no permissions.
- **Grant** (`user_group_project_groups`): the only link that gives a user group project access.
  There is no direct user-to-project or user-group-to-project assignment.
- **Effective access**: a consumer reaches a project when every link of the chain is active and the
  project is active and not archived. Root users reach every active, non-archived project without
  groups. Admin users administer a project when they belong to its `admin_<project_id>` user group
  and that group is granted a project group containing the project.
- **Default groups**: `POST /projects` creates a project group `default_<project_id>` containing the
  new project and three user groups (`admin_<project_id>`, `user_<project_id>`,
  `readonly_<project_id>`) granted to it. See [Projects](../projects/README.md#key-concepts).
- **Permission groups** attached to a user group through `/permissions/admin/user-groups/...`
  are a separate mechanism: they do not grant project reach and are not part of the auth-time
  permission set. See [Permission resolution](../permissions/resolution.md).

## Route families

| Concern | Prefix | Session must carry | Body |
| --- | --- | --- | --- |
| User groups, membership, grants | `/admin/user-groups` | `admin` or `manage_users` | Form fields; bulk member add takes JSON |
| Project groups and their projects | `/admin/project-groups` | `admin` or `manage_roles` | Form fields |
| Permission groups on a user group | `/permissions/admin/user-groups/{group_hash}/permission-groups` | See [permissions reference](../permissions/reference.md) | Form fields |

Endpoint tables, fields and response shapes are in [reference.md](reference.md).

## Rules and caveats

Platform-wide rules (User-Agent, body size, error envelope) are in
[Platform-wide contracts](../README.md#platform-wide-contracts).

- **The two prefixes use different permissions.** `manage_users` opens user-group routes,
  `manage_roles` opens project-group routes, and `admin` opens both. Root and admin sessions carry
  `admin`; consumers get these names only from a global role.
- **Group routes are not scoped to the caller's projects.** Any caller that passes the permission
  check can manage every user group and project group, with one exception below.
- **Only root may change a user group whose name starts with `admin_`** (compared the way MySQL's
  `utf8mb4_unicode_ci` collation does, so case and accents are ignored). This covers create,
  rename, delete, members and grants. Membership of `admin_<project_id>` is what makes an admin
  user a project administrator.
- **Deletes are soft.** Rows get `is_active = 0`. Deleted group names stay reserved, and names are
  unique regardless of case.
- **Removing access revokes live sessions.** Deleting a user group or project group, revoking a
  grant, or removing a project from a project group revokes the affected users' project sessions
  and refresh-token families at once. Removing a single member does not; that user's token fails
  on its next request instead. See [architecture.md](architecture.md#session-revocation).
- **A user-group hash works as a registration invitation.** `POST /auth/register` is public and
  places the new consumer in whichever user group hash it receives. Share hashes of the groups
  meant for self-registration only.
- **Group hierarchy is not used for access.** `parent_group_id` exists in both group tables but no
  route sets it and the access chain never follows it.

## In this suite

| Document | Purpose |
| --- | --- |
| [usage.md](usage.md) | Task-by-task requests: create groups, manage members, grant and revoke access, delete |
| [scenarios.md](scenarios.md) | End-to-end workflows: onboard a team, contractor access, multi-domain teams, deprovisioning |
| [reference.md](reference.md) | Endpoints, fields, query parameters, response shapes, error codes |
| [request-flow.md](request-flow.md) | What happens to a group request, and how access is re-checked on every authenticated request |
| [architecture.md](architecture.md) | Tables, stored procedures, access resolution, session revocation, caching, known defects |
| [troubleshooting.md](troubleshooting.md) | Symptom, cause and fix for common group problems |

## Related

- [Projects](../projects/README.md): project CRUD, default groups, archive state
- [Users](../users/README.md): user lifecycle and admin project assignment
- [Permissions](../permissions/README.md): permission groups and resolution
- [Authentication usage cases](../authentication-usage-cases.md): login, refresh and
  project switching
