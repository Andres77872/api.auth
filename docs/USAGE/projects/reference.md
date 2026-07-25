# Projects Endpoint and Operational Reference

Reference for the project-related API surface used in this repository.

---

## Projects

All 11 endpoints live in `src/routes/projects.py`.

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/projects` | POST | `admin` | Form | Create project and trigger default group bootstrap |
| `/projects` | GET | Valid session | Query params | List visible projects |
| `/projects/{hash}` | GET | Valid session; `admin` or group access | - | Get project details |
| `/projects/{hash}` | PUT | `admin` | Form | Update project metadata |
| `/projects/{hash}` | DELETE | `admin` | - | Soft-delete project and invalidate project sessions |
| `/projects/{hash}/members` | GET | `admin` or `manage_users` | Query params | List effective project members |
| `/projects/{hash}/groups` | GET | `admin` or `manage_users` | Query params | List user groups with access to the project |
| `/projects/{hash}/activity` | GET | Valid session; `admin` or group access | Query params | Get project activity feed |
| `/projects/{hash}/stats` | GET | Valid session; `admin` or group access | - | Get project statistics |
| `/projects/{hash}/owner` | PATCH | `admin` | Form (`new_owner_hash`) | Planned ownership transfer endpoint (**currently 501**) |
| `/projects/{hash}/archive` | PATCH | `admin` | Form (`archived`) | Planned archive/unarchive endpoint (**currently 501**) |

> "Group access" means the requesting non-admin user reaches the project through `get_user_accessible_projects()` (the groups-of-groups chain). There is no named per-project permission gate; the handlers require a valid session and then allow `admin` to bypass, otherwise verify membership in the accessible-projects list.

---

## Query Parameters

| Endpoint | Parameter | Type | Default | Range | Notes |
|----------|-----------|------|---------|-------|-------|
| `GET /projects` | `limit` | int | `10` | 1–500 | Page size |
| `GET /projects` | `offset` | int | `0` | ≥ 0 | Skip count |
| `GET /projects` | `search` | str | (none) | — | Admin path only; routes to `search_projects()` |
| `GET /projects/{hash}/members` | `limit` | int | `50` | 1–100 | Page size |
| `GET /projects/{hash}/members` | `offset` | int | `0` | ≥ 0 | Skip count |
| `GET /projects/{hash}/members` | `user_type` | str | (none) | — | Filter (e.g. `admin`, `consumer`) |
| `GET /projects/{hash}/activity` | `limit` | int | `50` | 1–100 | Page size |
| `GET /projects/{hash}/activity` | `offset` | int | `0` | ≥ 0 | Skip count |
| `GET /projects/{hash}/activity` | `activity_type` | str | (none) | — | Filter by activity type |
| `GET /projects/{hash}/activity` | `days` | int | `30` | 1–365 | Look-back window |
| `GET /projects/{hash}/groups` | `limit` | int | `100` | 1–500 | Page size |
| `GET /projects/{hash}/groups` | `offset` | int | `0` | ≥ 0 | Skip count |

`GET /projects/{hash}` and `GET /projects/{hash}/stats` take no query parameters (only the path hash).

---

## Project Groups

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/admin/project-groups` | POST | `admin` or `manage_roles` | Form | Create project group |
| `/admin/project-groups` | GET | `admin` or `manage_roles` | Query params | List project groups |
| `/admin/project-groups/{hash}` | GET | `admin` or `manage_roles` | - | Get project-group details |
| `/admin/project-groups/{hash}` | PUT | `admin` or `manage_roles` | Form | Update project-group metadata |
| `/admin/project-groups/{hash}` | DELETE | `admin` or `manage_roles` | - | Soft-delete project group and active links |
| `/admin/project-groups/{hash}/projects` | POST | `admin` or `manage_roles` | Form | Add project to group |
| `/admin/project-groups/{hash}/projects/{project_hash}` | DELETE | `admin` or `manage_roles` | - | Remove project from group |

There is no separate `GET /admin/project-groups/{hash}/projects` route. Read
`assigned_projects` from `GET /admin/project-groups/{hash}`.

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
- create and update project routes use `multipart/form-data` (the `User-Agent` header is required on every request; a missing one yields `422`)
- most list routes use `limit` / `offset`
- `PATCH /projects/{hash}/owner` expects the required form field `new_owner_hash`, but still returns `501`
- `PATCH /projects/{hash}/archive` expects the required form field `archived` (bool), but still returns `501`

### Access semantics
- project reach is resolved through `user_group_project_groups` and `project_group_members`
- root access is modeled separately in `v_user_project_access`
- project access and permissions are not the same concern

### Response semantics
- project member and project list access levels are path labels (`group_access` / `admin_access`), not global-permission-derived labels
- `GET /projects/{hash}` returns a `project_groups` array (each item: `group_hash`, `group_name`, `description`) — the project-group memberships of the project under the groups-of-groups model, sourced from `get_permission_groups_for_project()`
- some older docs or responses may still use legacy naming like `accessible_projects`

### Error codes
This surface returns the following error codes (see [errors.md](../errors.md) for the full envelope):

| Error code | HTTP | When |
|-----------|------|------|
| `SESSION_INVALID` | 401 | Missing or expired session token |
| `USER_NOT_FOUND` | 404 | Resolved user (or `new_owner_hash`) does not exist |
| `PROJECT_NOT_FOUND` | 404 | `project_hash` does not resolve to an active project |
| `INSUFFICIENT_PERMISSIONS` | 403 | Caller lacks `admin` (or `manage_users` on member/group listings) |
| `PROJECT_ACCESS_DENIED` | 403 | Non-admin lacks group access to the project (details/activity/stats) |
| `MISSING_REQUIRED_FIELD` | 400 | `project_name` omitted on `POST /projects` |
| `FEATURE_NOT_IMPLEMENTED` | 501 | `PATCH /projects/{hash}/owner` and `PATCH /projects/{hash}/archive` stubs |
| `INTERNAL_ERROR` | 500 | DB-layer create/update/delete returned no result |

---

## Related Documentation

- **[Projects Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Document Version**: 1.1
