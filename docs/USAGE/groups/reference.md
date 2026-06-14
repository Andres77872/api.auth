# Groups Endpoint and Operational Reference

Reference for the groups-related API surface used in this repository.

---

## User Groups

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/admin/user-groups` | POST | `admin` or `manage_users` | Form | Create user group |
| `/admin/user-groups` | GET | `admin` or `manage_users` | Query params | List user groups |
| `/admin/user-groups/{hash}` | GET | `admin` or `manage_users` | - | Group details, members, legacy `accessible_projects`, linked `accessible_project_groups`, and `statistics` |
| `/admin/user-groups/{hash}` | PUT | `admin` or `manage_users` | Form | Update group metadata |
| `/admin/user-groups/{hash}` | DELETE | `admin` or `manage_users` | - | Soft-delete group and linked active access; revokes affected users' live project sessions |
| `/admin/user-groups/{hash}/members` | GET | `admin` or `manage_users` | Query params | Paginated members (`limit` capped at 100); response includes `user_type`, `is_active`, `joined_at`, `statistics`, `generated_at` |
| `/admin/user-groups/{hash}/members` | POST | `admin` or `manage_users` | Form | Add one member |
| `/admin/user-groups/{hash}/members/bulk` | POST | `admin` or `manage_users` | JSON | Bulk add members |
| `/admin/user-groups/{hash}/members/{user_hash}` | DELETE | `admin` or `manage_users` | - | Remove one member |
| `/admin/user-groups/{hash}/project-groups` | GET | `admin` or `manage_users` | - | List project-group access links |
| `/admin/user-groups/{hash}/project-groups` | POST | `admin` or `manage_users` | Form | Grant project-group access |
| `/admin/user-groups/{hash}/project-groups/{project_group_hash}` | DELETE | `admin` or `manage_users` | - | Revoke project-group access; revokes affected users' live project sessions |
| `/admin/user-groups/users/{user_hash}/groups` | GET | `admin` or `manage_users` | - | List a user's current user-group memberships (with `joined_at`) |

---

## Project Groups

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/admin/project-groups` | POST | `admin` or `manage_roles` | Form | Create project group |
| `/admin/project-groups` | GET | `admin` or `manage_roles` | Query params | List project groups |
| `/admin/project-groups/{hash}` | GET | `admin` or `manage_roles` | - | Project-group details |
| `/admin/project-groups/{hash}` | PUT | `admin` or `manage_roles` | Form | Update project-group metadata |
| `/admin/project-groups/{hash}` | DELETE | `admin` or `manage_roles` | - | Soft-delete project group; revokes affected users' live project sessions |
| `/admin/project-groups/{hash}/projects` | POST | `admin` or `manage_roles` | Form | Add project to group |
| `/admin/project-groups/{hash}/projects/{project_hash}` | DELETE | `admin` or `manage_roles` | - | Remove project from group; revokes affected users' live sessions for that project |

> There is **no** `GET /admin/project-groups/{hash}/projects` endpoint. To list the projects assigned to a project group, call `GET /admin/project-groups/{hash}` (details) and read its `assigned_projects` field.

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
- Bulk member assignment (`POST /admin/user-groups/{hash}/members/bulk`) uses JSON: `{"user_hashes": ["...", "..."]}`
- List endpoints use standard `limit` / `offset` query parameters where available
- `GET /admin/user-groups` and `GET /admin/project-groups` cap `limit` at `1000` (`le=1000`)
- `GET /admin/user-groups/{hash}/members` caps `limit` at `100` (`le=100`) — this sub-resource is deliberately tighter than the list endpoints

### Access semantics
- User-group membership alone does not grant project access
- Project-group membership alone does not grant user access
- The effective bridge is `user_group_project_groups`
- Permission groups are additional capability wiring, not project-access wiring

### Session revocation side effects
Several destructive operations do more than deactivate rows — they actively terminate the live project sessions of affected users by calling `auth_lifecycle.revoke_project_sessions_losing_access(...)`. Affected users are forced to re-authenticate for the impacted projects.

| Operation | Reason recorded |
|-----------|-----------------|
| `DELETE /admin/user-groups/{hash}` | `user_group_deleted` |
| `DELETE /admin/user-groups/{hash}/project-groups/{project_group_hash}` | `user_group_project_group_access_revoked` |
| `DELETE /admin/project-groups/{hash}` | `project_group_deleted` |
| `DELETE /admin/project-groups/{hash}/projects/{project_hash}` | `project_removed_from_group` |

Adding members, granting access, and metadata updates do **not** trigger session revocation.

### Response semantics
- `joined_at` represents assignment time for membership records (`assigned_at` on the underlying row)
- `GET /admin/user-groups/{hash}` returns both a legacy `accessible_projects` field (direct project access) **and** `accessible_project_groups` (the groups-of-groups links), plus a `statistics` block. Note `statistics.total_derived_projects` is currently fixed at `0` (it would require a separate query to compute) and `derived_projects` is returned as an empty list.
- `GET /admin/user-groups/{hash}/members` returns each member with `user_hash`, `username`, `email`, `user_type`, `is_active`, and `joined_at`, plus a `statistics` block and a `generated_at` timestamp
- `GET /admin/user-groups/users/{user_hash}/groups` (reverse lookup) returns the groups a user belongs to, each with `joined_at`, plus `statistics.total_groups` and `generated_at`

---

## Related Documentation

- **[Groups Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: June 2026  
**Document Version**: 3.1
