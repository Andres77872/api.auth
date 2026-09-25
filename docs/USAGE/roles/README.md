# Roles

The roles suite covers the `/roles` API (`src/routes/global_roles.py`, 28 routes): defining global
permissions, bundling them into permission groups, linking groups to roles, giving each user one
global role, and keeping per-project role catalogs. Operators and delegated role managers use the
write routes; any signed-in client can read the catalog of roles, groups, and permissions. Assigning
permission groups to user groups or directly to users, and self-inspection of effective permissions,
belong to the [permissions suite](../permissions/README.md).

## Key concepts

```text
users.role_id ─► role ─► permission groups ─► permissions      (global, no project dimension)
project ─► role catalog                                          (metadata only)
```

- **Permission.** A name that guards match on, such as `manage_users`.
- **Permission group.** A named bundle of permissions, reusable by roles, user groups, and users.
- **Role.** A named bundle of permission groups. Each user holds at most one (`users.role_id`).
- **Role and consumers.** For a consumer, the role is the only source of the permissions route guards
  see. `root` and `admin` sessions carry fixed built-in lists, so a role changes nothing for them.
  Details: [Permission resolution](../permissions/resolution.md).
- **Project role catalog.** Suggests roles for a project. It restricts nothing.

## Route families

| Family | Paths | Routes |
| --- | --- | --- |
| Roles | `/roles/roles`, `/roles/roles/{role_hash}` | 5 |
| Role to permission-group links | `/roles/roles/{role_hash}/permission-groups[/{group_hash}]` | 3 |
| Permission groups | `/roles/permission-groups`, `/roles/permission-groups/{group_hash}` | 5 |
| Group to permission links | `/roles/permission-groups/{group_hash}/permissions[/{permission_hash}]` | 3 |
| Permissions | `/roles/permissions`, `/roles/permissions/{permission_hash}` | 5 |
| User role | `/roles/users/me/role`, `/roles/users/{user_hash}/role` | 4 |
| Project role catalog | `/roles/projects/{project_hash}/catalog/roles[/{role_hash}]` | 3 |

`POST /admin/projects/{project_hash}/bulk-assign-roles` (bulk operations router) assigns one role to
many users and is documented here too. Full contract: [Roles reference](reference.md).

## Rules and caveats

- **Who can write.** `root` and `admin` users, or a consumer whose **role** grants `manage_roles`
  (user-group and direct grants do not count here). Reads need any access token; API keys are not
  accepted.
- **Reserved names are root-only.** Non-root callers cannot create, edit, move, or hand out
  `admin`, `manage_users`, `manage_roles`, and the other
  [reserved permission names](reference.md#reserved-permission-names), and cannot change their own role.
  The same holds for bulk role assignment and for the `/permissions` assignment routes.
- **Doubled path.** Role CRUD lives at `/roles/roles/...`: the router prefix `/roles` plus route paths
  that also start with `/roles`.
- **Form fields.** Writes take form-encoded or multipart bodies. A JSON body is not read (`400`
  `VAL_3001` for required fields; optional-only `PUT`s silently change nothing).
- **Soft deletes.** Deleting a role, group, or permission marks it inactive and keeps its name taken.
  It stops granting at once, through every source; links to it are kept as history.
- **Pagination.** `pagination.total` is the size of the returned page, not the overall count.
- **Timing.** Changes reach consumers' existing tokens within about 30 seconds (`VALIDATE_CACHE_TTL`)
  without a new login.

## In this suite

| Document | Purpose |
| --- | --- |
| [README.md](README.md) | Overview, route families, rules |
| [usage.md](usage.md) | One task per section: permissions, groups, roles, assignment, catalog |
| [scenarios.md](scenarios.md) | End-to-end workflows: build a role, delegate role management, change and retire roles |
| [reference.md](reference.md) | Endpoints, fields, reserved names, response objects, error codes |
| [request-flow.md](request-flow.md) | What happens to a request, guard by guard |
| [architecture.md](architecture.md) | Tables, procedures, invariants, and design decisions |
| [troubleshooting.md](troubleshooting.md) | Symptom, cause, fix |

## Related

- [Permission resolution](../permissions/resolution.md) — how roles and assignments become effective permissions
- [Permissions](../permissions/README.md) — user-group and direct assignments, self-inspection
- [Groups](../groups/README.md) — user groups and project access (which projects a user can enter)
- [Users](../users/README.md) — user types (`root`, `admin`, `consumer`)
- [Platform-wide contracts](../README.md#platform-wide-contracts) and [error reference](../errors.md)
