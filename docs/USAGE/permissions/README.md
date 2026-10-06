# Permissions

The permissions suite covers the `/permissions` API (`src/routes/permission_assignments.py`, 17
routes): giving permission groups to user groups and directly to users, letting any caller inspect
where their own permissions come from, and cataloging permission groups against projects. It also
holds [Permission resolution](resolution.md), the authoritative account of how effective permissions
are computed. Operators use the admin routes; any signed-in client can use the `/me` inspection
routes. Defining roles, permission groups, and permissions, and assigning a user's global role, is
the [roles suite](../roles/README.md).

## Key concepts

- **Three assignment paths.** A permission group reaches a user through their global role, through a
  user group they are a direct member of, or through a direct assignment. This suite writes the last
  two; the role path is written through `/roles`.
- **Only the role counts at auth time.** Route guards use the role-derived set for consumers and a
  fixed list for `root`/`admin`. User-group and direct assignments show up in the inspection
  endpoints and satisfy one guard only: the `manage_roles` fallback of this suite's own admin routes.
  Details: [Permission resolution](resolution.md).
- **Catalogs are metadata.** A permission-group project catalog entry is a UI suggestion. It grants,
  restricts, and scopes nothing.

## Route families

| Family | Paths | Guard |
| --- | --- | --- |
| User-group assignments | `/permissions/admin/user-groups/{group_hash}/permission-groups[...]` (4 routes) | Admin |
| Direct user assignments | `/permissions/users/{user_hash}/permission-groups[...]` (3 routes) | Admin |
| Self-inspection | `/permissions/users/me/...` (4 routes) | Any access token |
| Project catalog | `/permissions/projects/{project_hash}/permission-group-catalog[...]` (3 routes), `/permissions/permissions/groups/{pg_hash}/project-catalog` | Admin to write, any access token to read |
| Usage queries | `/permissions/permissions/groups/{pg_hash}/user-groups`, `.../users` | Admin |

"Admin" means: user type `root` or `admin`, or a consumer holding `manage_roles` from any of the three
sources. The full endpoint list is in [Permissions reference](reference.md).

## Rules and caveats

- **Access tokens only.** Send `Authorization: Bearer <access JWT>` or the `access_token` cookie.
  API keys are not accepted.
- **Form fields.** Writes take `application/x-www-form-urlencoded` or `multipart/form-data`. A JSON
  body is not read, so a required field is reported missing (`400` `VAL_3001`).
- **Doubled prefix.** The `/permissions/permissions/groups/...` paths are real: the router prefix
  `/permissions` is joined to route paths that also start with `/permissions`.
- **Envelope.** Responses from this router carry no `success` field (unlike `/roles`).
- **Not scoped.** An `admin` user can assign to any user group or user, not only those in their
  projects.
- **Reserved names are root-only.** As on `/roles`, only root may assign or remove a permission group
  that contains a [reserved name](../roles/reference.md#reserved-permission-names) such as
  `manage_roles`; other callers, `admin` users included, get `403` `AUTHZ_2002`.
- **Idempotent writes.** Assigning twice re-activates the same row; removing something that is not
  assigned still returns `200`.

## In this suite

| Document | Purpose |
| --- | --- |
| [README.md](README.md) | Overview, route families, rules |
| [resolution.md](resolution.md) | How effective permissions resolve at auth time and at inspection time (authoritative) |
| [usage.md](usage.md) | One task per section: assign, inspect, audit, catalog |
| [scenarios.md](scenarios.md) | End-to-end workflows: delegation, audits, clean removal, 403 diagnosis |
| [reference.md](reference.md) | Endpoints, fields, response shapes, error codes |
| [request-flow.md](request-flow.md) | What happens to a request, from token to stored procedure |
| [architecture.md](architecture.md) | Tables, procedures, invariants, and design decisions |
| [troubleshooting.md](troubleshooting.md) | Symptom, cause, fix |

## Related

- [Roles](../roles/README.md) — roles, permission groups, permissions, user role assignment, role catalog
- [Groups](../groups/README.md) — user groups and memberships, which this suite assigns to
- [Platform-wide contracts](../README.md#platform-wide-contracts) and [error reference](../errors.md)
