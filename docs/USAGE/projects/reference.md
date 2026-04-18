# Projects Endpoint and Operational Reference

Reference for the project-related API surface used in this repository.

---

## Projects

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/projects` | POST | `admin` | Form | Create project and trigger default group bootstrap |
| `/projects` | GET | Valid session | Query params | List visible projects |
| `/projects/{hash}` | GET | Project access or `admin` | - | Get project details |
| `/projects/{hash}` | PUT | `admin` | Form | Update project metadata |
| `/projects/{hash}` | DELETE | `admin` | - | Soft-delete project and invalidate project sessions |
| `/projects/{hash}/members` | GET | `admin` or `manage_users` | Query params | List effective project members |
| `/projects/{hash}/groups` | GET | `admin` or `manage_users` | Query params | List user groups with access to the project |
| `/projects/{hash}/activity` | GET | Project access or `admin` | Query params | Get project activity feed |
| `/projects/{hash}/stats` | GET | Project access or `admin` | Query params | Get project statistics |
| `/projects/{hash}/owner` | PATCH | `admin` | Form | Planned ownership transfer endpoint (**currently 501**) |
| `/projects/{hash}/archive` | PATCH | `admin` | Form | Planned archive/unarchive endpoint (**currently 501**) |

---

## Project Groups

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/admin/project-groups` | POST | `admin` or `manage_roles` | Form | Create project group |
| `/admin/project-groups` | GET | `admin` or `manage_roles` | Query params | List project groups |
| `/admin/project-groups/{hash}` | GET | `admin` or `manage_roles` | - | Get project-group details |
| `/admin/project-groups/{hash}` | PUT | `admin` or `manage_roles` | Form | Update project-group metadata |
| `/admin/project-groups/{hash}` | DELETE | `admin` or `manage_roles` | - | Soft-delete project group and active links |
| `/admin/project-groups/{hash}/projects` | GET | `admin` or `manage_roles` | Query params | List projects in the group |
| `/admin/project-groups/{hash}/projects` | POST | `admin` or `manage_roles` | Form | Add project to group |
| `/admin/project-groups/{hash}/projects/{project_hash}` | DELETE | `admin` or `manage_roles` | - | Remove project from group |

---

## Access Bridge Routes That Matter to Projects

| Endpoint | Method | Auth / Permission | Purpose |
|----------|--------|-------------------|---------|
| `/admin/user-groups/{hash}/project-groups` | GET | `admin` or `manage_users` | List which project groups a user group can reach |
| `/admin/user-groups/{hash}/project-groups` | POST | `admin` or `manage_users` | Grant user-group access to a project group |
| `/admin/user-groups/{hash}/project-groups/{pg_hash}` | DELETE | `admin` or `manage_users` | Revoke user-group access to a project group |

---

## Operational Notes

### Request shapes
- create and update project routes use form data
- most list routes use `limit` / `offset`
- `PATCH /projects/{hash}/archive` expects form field `archived`, but still returns 501

### Access semantics
- project reach is resolved through `user_group_project_groups` and `project_group_members`
- root access is modeled separately in `v_user_project_access`
- project access and permissions are not the same concern

### Response semantics
- project member and project list access levels are influenced by global permission lookup
- some older docs or responses may still use legacy naming like `accessible_projects`

---

## Related Documentation

- **[Projects Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
