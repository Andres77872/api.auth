# Users Endpoint and Operational Reference

Reference for the user-management API surface used in this repository.

---

## `/users` Endpoints

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/users/profile` | GET | Any authenticated user | - | Get current user profile with groups and projects |
| `/users/profile` | PUT | Any authenticated user | Form | Update own username, email, or password |
| `/users/access-summary` | GET | Any authenticated user | - | Get hierarchical access summary |
| `/users/list` | GET | Root or admin | Query params | List users with filters and optional group/project data |
| `/users/search/query` | GET | Root or admin | Query params | Quick user search by username/email |
| `/users/{user_hash}` | GET | Self, root, or scoped admin | Query params | Get detailed user information |
| `/users/{user_hash}` | PUT | Root or scoped admin | Form | Update username/email; root may also send `user_type` |
| `/users/{user_hash}/status` | PUT | Root or scoped admin | Query param `is_active` | Activate or deactivate a user |
| `/users/{user_hash}/reset-password` | POST | Root or admin | - | Reset a non-root user's password |
| `/users/{user_hash}` | DELETE | Root or scoped admin | - | Soft-delete a user and invalidate sessions/cache |
| `/users/{user_hash}/type` | PATCH | Root only | Form | Change user type through the legacy/simple path |

---

## `/user-types` Endpoints

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/user-types/root` | POST | Root only | Form | Create a root user |
| `/user-types/admin` | POST | Root only | Form | Create an admin user with one or more project assignments |
| `/user-types/{user_hash}/info` | GET | Root or admin | - | Get user-type capabilities and assignment metadata |
| `/user-types/{user_hash}/type` | PUT | Root only | Form | Change user type through the stricter assignment-aware path |
| `/user-types/users/{user_type}` | GET | Root or admin | Query params | List users by type |
| `/user-types/stats` | GET | Root or admin | - | Get user-type distribution statistics |
| `/user-types/admin/{user_hash}/projects` | GET | Root only | - | List all projects assigned to an admin |
| `/user-types/admin/{user_hash}/projects` | PUT | Root only | Form | Replace an admin's full project assignment set |
| `/user-types/admin/{user_hash}/projects/add` | POST | Root only | Form | Add an admin to one additional project |
| `/user-types/admin/{user_hash}/projects/{project_id}` | DELETE | Root only | - | Remove an admin from one project |

---

## `/admin/users` Bulk Endpoints

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/admin/users/bulk-update` | POST | Session permissions `admin` or `manage_users` | Form | Bulk update selected user fields |
| `/admin/users/bulk-delete` | POST | Session permissions `admin` or `manage_users` | Form | Bulk soft-delete users with explicit confirmation |

---

## List and Detail Query Parameters

### `GET /users/list`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `limit` | int | Max rows to return | `100` |
| `offset` | int | Pagination offset | `0` |
| `sort_by` | string | Sort field (`username`, `email`, `user_type`, `created_at`, `last_login`) | `username` |
| `sort_order` | string | `asc` or `desc` | `asc` |
| `search` | string | Username/email contains filter | `null` |
| `user_type_filter` | string | `root`, `admin`, `consumer` | `null` |
| `group_filter` | string | User-group hash or name | `null` |
| `project_filter` | string | Project hash or name | `null` |
| `include_inactive` | bool | Include inactive users | `false` |
| `include_group_info` | bool | Include parsed group memberships | `true` |
| `include_project_access` | bool | Include parsed project access details | `true` |

### `GET /users/{user_hash}`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `include_group_hierarchy` | bool | Include group/project count enrichment | `true` |
| `include_permission_details` | bool | Include effective permissions and access groups | `true` |

### `GET /users/search/query`

| Parameter | Type | Description | Default |
|-----------|------|-------------|---------|
| `q` | string | Search term for username/email | required |
| `user_type_filter` | string | `root`, `admin`, `consumer` | `null` |
| `limit` | int | Max results; route caps at 100 | `50` |

---

## Bulk Request Fields

### `POST /admin/users/bulk-update`

| Field | Type | Notes |
|-------|------|-------|
| `user_hashes` | repeated string | Required; max 100 |
| `is_active` | bool | Optional |
| `user_type` | string | Optional; must be `root`, `admin`, or `consumer` |
| `force_password_reset` | bool | Optional route field; verify runtime behavior in staging |

### `POST /admin/users/bulk-delete`

| Field | Type | Notes |
|-------|------|-------|
| `user_hashes` | repeated string | Required; max 50 |
| `confirm_deletion` | bool | Required and must be `true` |

---

## Operational Notes

- `PUT /users/{hash}/status` and `DELETE /users/{hash}` are the documented user-lifecycle paths that explicitly invalidate sessions and cache
- `/users/search/query` is not a full substitute for `/users/list` because the scoping logic is simpler
- `/users/{hash}/type` and `/user-types/{hash}/type` are not interchangeable in admin-promotion workflows
- password reset response omits the generated temporary password by design

---

## Related Documentation

- **[Users Overview](README.md)**
- **[Usage](usage.md)**
- **[User Types](user-types.md)**
- **[Bulk Operations](bulk-operations.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
