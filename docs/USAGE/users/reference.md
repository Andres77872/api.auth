# Users Endpoint and Operational Reference

Reference for the user-management API surface used in this repository.

---

## `/users` Endpoints

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/users/profile` | GET | Any authenticated user | - | Get current user profile with groups and projects |
| `/users/profile` | PUT | Any authenticated user | Form | Update own username/email; password fields are rejected |
| `/users/access-summary` | GET | Any authenticated user | - | Get hierarchical access summary |
| `/users/list` | GET | Root or admin | Query params | List users with filters and optional group/project data |
| `/users/me/emails` | GET | Any authenticated user | - | List the caller's own email rows (owner view) |
| `/users/me/emails` | POST | Any authenticated user | Form or JSON | Add/reuse a pending email and enqueue an activation link; generic `202` |
| `/users/me/emails/{email_id}/resend` | POST | Any authenticated user | - | Resend activation for an owned pending email; generic `202` |
| `/users/me/emails/{email_id}` | DELETE | Any authenticated user | - | Soft-remove an owned email; revokes other sessions |
| `/users/me/emails/{email_id}/primary` | POST | Any authenticated user | - | Set an owned activated email as primary; revokes other sessions |
| `/users/{user_hash}/emails` | GET | Root or admin | - | List a target user's emails (masked/hash-only view) |
| `/users/{user_hash}/emails/{email_id}/resend` | POST | Root or admin | - | Re-trigger activation for a target user's email; generic `202` |
| `/users/search/query` | GET | Root or admin | Query params | Quick user search by username/email |
| `/users/{user_hash}` | GET | Self, root, or scoped admin | Query params | Get detailed user information |
| `/users/{user_hash}` | PUT | Root or scoped admin | Form | Update username/email; root may also send `user_type` |
| `/users/{user_hash}/status` | PUT | Root or scoped admin | Query param `is_active` | Activate or deactivate a user |
| `/users/{user_hash}/reset-password` | POST | Root or admin | - | Queue a hash-only admin password-reset link email (no temp password/token/URL returned); body-less POST |
| `/users/{user_hash}` | DELETE | Root or scoped admin | - | Soft-delete a user and invalidate sessions/cache |
| `/users/{user_hash}/hard` | DELETE | Root only | - | Permanently delete the user/owned identity content, release email rows, preserve shared resources with ownership cleared |
| `/users/{user_hash}/type` | PATCH | Root only | Form | Change user type through the legacy/simple path |

> The `/users/*` route file (`src/routes/users.py`) exposes **19 endpoints**,
> including the per-user email-management group above. Full lifecycle behavior
> for those email routes (generic `202`, `429 + Retry-After`, resend cooldown,
> idempotency, session revocation, owner vs admin field views) is in
> [email-management.md](email-management.md).

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

## Email Management Request Fields

### `POST /users/me/emails`

| Field / Header | Type | Notes |
|----------------|------|-------|
| `email` | string (Form or JSON body) | Required; address to add and send an activation link to. Invalid shape is rejected before enqueue |
| `Idempotency-Key` | header | Optional; replays a prior generic `202` instead of enqueuing twice |

### `POST /users/me/emails/{email_id}/resend`

| Field / Header | Type | Notes |
|----------------|------|-------|
| `email_id` | path | The owned, pending email row to resend |
| `Idempotency-Key` | header | Optional; replays the prior generic `202` |

Send-side email contracts (apply to `POST /users/me/emails`, both resend
routes):

- **Generic `202 Accepted`** is returned for any processable request regardless
  of whether a row actually changed; enqueue failures are swallowed and still
  return `202`, so the body never confirms existence or delivery.
- **`429 + Retry-After`** is the only detailed public response, returned by the
  rate limiter (and by the resend cooldown). The body carries
  `details.retry_after_seconds`.
- **Resend cooldown** uses `EMAIL_RESEND_COOLDOWN_SECONDS` (default **60s**).
- The admin resend (`POST /users/{user_hash}/emails/{email_id}/resend`) does
  **not** read an `Idempotency-Key`.

See [email-management.md](email-management.md) for full request/response
examples and the owner vs admin field views.

---

## Bulk Request Fields

### `POST /admin/users/bulk-update`

| Field | Type | Notes |
|-------|------|-------|
| `user_hashes` | repeated string | Required; max 100 |
| `is_active` | bool | Optional |
| `user_type` | string | Optional; must be `root`, `admin`, or `consumer` |
| `force_password_reset` | bool | Not supported; route rejects it with reset-link or `/auth/password/change` guidance |

### `POST /admin/users/bulk-delete`

| Field | Type | Notes |
|-------|------|-------|
| `user_hashes` | repeated string | Required; max 50 |
| `confirm_deletion` | bool | Required and must be `true` |

---

## Operational Notes

- `PUT /users/{hash}/status` and `DELETE /users/{hash}` are the documented user-lifecycle paths that explicitly invalidate sessions and cache
- `DELETE /users/{hash}/hard` is ROOT-only and permanent. It can purge an already inactive user, cannot target the caller, releases the target's email rows for re-registration, and relies on foreign-key cascade for owned/identity content. Shared projects/user groups are preserved with ownership cleared. Prefer soft delete for routine offboarding
- `DELETE /users/me/emails/{email_id}` and `POST /users/me/emails/{email_id}/primary` also revoke the caller's other sessions (reasons `email_removed` / `email_primary_changed`) while preserving the current session when possible
- `/users/search/query` is not a full substitute for `/users/list` because the scoping logic is simpler
- `/users/{hash}/type` and `/user-types/{hash}/type` are not interchangeable in admin-promotion workflows
- `POST /users/{hash}/reset-password` is a body-less POST that queues a hash-only reset link when possible and does not expose password/token/link/full-email/provider payload by design

---

## Related Documentation

- **[Users Overview](README.md)**
- **[Usage](usage.md)**
- **[Email Management](email-management.md)**
- **[User Types](user-types.md)**
- **[Bulk Operations](bulk-operations.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Document Version**: 1.1
