# Groups Endpoint and Operational Reference

Reference for the groups-related API surface used in this repository.

---

## User Groups

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/admin/user-groups` | POST | `admin` or `manage_users` | Form | Create user group |
| `/admin/user-groups` | GET | `admin` or `manage_users` | Query params | List user groups |
| `/admin/user-groups/{hash}` | GET | `admin` or `manage_users` | - | Group details, members, linked project groups |
| `/admin/user-groups/{hash}` | PUT | `admin` or `manage_users` | Form | Update group metadata |
| `/admin/user-groups/{hash}` | DELETE | `admin` or `manage_users` | - | Soft-delete group and linked active access |
| `/admin/user-groups/{hash}/members` | GET | `admin` or `manage_users` | Query params | List members |
| `/admin/user-groups/{hash}/members` | POST | `admin` or `manage_users` | Form | Add one member |
| `/admin/user-groups/{hash}/members/bulk` | POST | `admin` or `manage_users` | JSON | Bulk add members |
| `/admin/user-groups/{hash}/members/{user_hash}` | DELETE | `admin` or `manage_users` | - | Remove one member |
| `/admin/user-groups/{hash}/project-groups` | GET | `admin` or `manage_users` | - | List project-group access links |
| `/admin/user-groups/{hash}/project-groups` | POST | `admin` or `manage_users` | Form | Grant project-group access |
| `/admin/user-groups/{hash}/project-groups/{pg_hash}` | DELETE | `admin` or `manage_users` | - | Revoke project-group access |
| `/admin/user-groups/users/{user_hash}/groups` | GET | `admin` or `manage_users` | - | List a user's current user-group memberships |

---

## Project Groups

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/admin/project-groups` | POST | `admin` or `manage_roles` | Form | Create project group |
| `/admin/project-groups` | GET | `admin` or `manage_roles` | Query params | List project groups |
| `/admin/project-groups/{hash}` | GET | `admin` or `manage_roles` | - | Project-group details |
| `/admin/project-groups/{hash}` | PUT | `admin` or `manage_roles` | Form | Update project-group metadata |
| `/admin/project-groups/{hash}` | DELETE | `admin` or `manage_roles` | - | Soft-delete project group |
| `/admin/project-groups/{hash}/projects` | GET | `admin` or `manage_roles` | - | List projects in the group |
| `/admin/project-groups/{hash}/projects` | POST | `admin` or `manage_roles` | Form | Add project to group |
| `/admin/project-groups/{hash}/projects/{project_hash}` | DELETE | `admin` or `manage_roles` | - | Remove project from group |

---

## Permission-Group Operations That Matter to Groups

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/roles/permission-groups` | POST | Create reusable permission-group template |
| `/roles/permission-groups` | GET | List permission groups |
| `/roles/permission-groups/{hash}` | GET | Inspect permission-group details |
| `/roles/permission-groups/{hash}/permissions/{perm_hash}` | POST | Add permission to template |
| `/permissions/admin/user-groups/{hash}/permission-groups` | POST | Attach permission group to a user group |
| `/permissions/admin/user-groups/{hash}/permission-groups/{pg_hash}` | DELETE | Remove permission group from a user group |
| `/permissions/admin/user-groups/{hash}/permission-groups` | GET | List permission groups attached to a user group |

---

## Operational Notes

### Request shapes
- Most group endpoints use form data
- Bulk member assignment uses JSON
- List endpoints use standard `limit` / `offset` query parameters where available

### Access semantics
- User-group membership alone does not grant project access
- Project-group membership alone does not grant user access
- The effective bridge is `user_group_project_groups`
- Permission groups are additional capability wiring, not project-access wiring

### Response semantics
- `joined_at` usually represents assignment time for membership records
- some statistics fields in group details are partially derived and not always complete for every conceptual count

---

## Related Documentation

- **[Groups Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: April 2026  
**Document Version**: 3.0
