# Bulk user operations

`POST /admin/users/bulk-update` and `POST /admin/users/bulk-delete` apply one change to many users in
a single request. This page is their detailed contract. The other bulk routes,
`POST /admin/projects/{project_hash}/bulk-assign-roles` and `POST /admin/user-groups/bulk-assign`,
change roles and group membership and are covered in
[Admin usage cases](../admin-usage-cases.md).

## Authorization

Both routes take an access token of a **root or admin user** whose session permissions include
`admin` or `manage_users`; otherwise they return `403` (`AUTHZ_2002`). Root and admin sessions carry
these permissions. A consumer is refused even when their global role carries one of these names.

Each target is then checked on its own, and a refused target fails in `results` without being
changed:

- Nobody may deactivate or delete their own account (`Cannot deactivate your own account`,
  `Cannot delete your own account`).
- Admins may only touch non-root users who reach one of the projects they are assigned to
  administer (`Root users are outside your administrative scope`,
  `User not in your administrative scope`). This is the same assigned-scope model as search and
  reset-password ([Caller rules](reference.md#caller-rules)).
- Root may change any other user, including other root users, in bulk update.

Changing `user_type` in bulk additionally requires a root caller (`403`, `AUTHZ_2002`).

## Request format

Form fields (`application/x-www-form-urlencoded` or `multipart/form-data`). Send list fields by
repeating them: `user_hashes=usr-a&user_hashes=usr-b`.

## Bulk update

`POST /admin/users/bulk-update`

```bash
curl -X POST "http://localhost:8000/admin/users/bulk-update" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hashes=$USER_A&user_hashes=$USER_B&is_active=false"
```

| Field | Required | Notes |
| --- | --- | --- |
| `user_hashes` | Yes | 1 to 100 user hashes; repeat the field |
| `is_active` | One of the two | `false` deactivates. `true` cannot reactivate anyone (see below) |
| `user_type` | One of the two | `root`, `admin` or `consumer`; root callers only. No admin project is assigned |
| `force_password_reset` | No | Not supported: any value returns `400`. Use `POST /users/{user_hash}/reset-password` or `POST /auth/password/change` |

Per-user behavior:

- Targets are looked up among **active** users only. An unknown or inactive hash is reported as
  `User not found`, so `is_active=true` cannot reactivate a deactivated account.
- A user deactivated here has their sessions and refresh tokens revoked. Group memberships are left
  as they are.
- `user_type` changes only the type, like `PATCH /users/{user_hash}/type`: a new admin gets no
  project assignment. A user whose type actually changes is signed out everywhere (sessions and
  refresh tokens). Use
  [`PUT /user-types/{user_hash}/type`](user-types.md#change-a-users-type) for admin promotions.
- Each user writes a `user_update` activity record (`action: bulk_update_user`), and the request writes
  one `bulk_user_update` record.

## Bulk delete

`POST /admin/users/bulk-delete`

```bash
curl -X POST "http://localhost:8000/admin/users/bulk-delete" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hashes=$USER_A&user_hashes=$USER_B&confirm_deletion=true"
```

| Field | Required | Notes |
| --- | --- | --- |
| `user_hashes` | Yes | 1 to 50 user hashes; repeat the field |
| `confirm_deletion` | Yes | Must be `true`; it defaults to `false`, which returns `400` |

Per-user behavior:

- This is the same soft delete as `DELETE /users/{user_hash}`: the account and its active group
  memberships are deactivated; nothing is removed.
- Targets are looked up among active users only (`User not found` otherwise).
- Root users are never deleted, whoever calls. Each one is reported as a failure
  (`Cannot bulk delete root users`) and counted in both `error_count` and `protected_count`.
- A user without active group memberships is deleted like any other.
- Each deleted user has their sessions and refresh tokens revoked. If that revocation fails, the user
  is still reported as deleted and a `warnings[]` entry names them; their tokens are refused anyway
  because every request re-checks that the user is active.
- Each user writes a `user_status_change` activity record (`action: bulk_delete_user`), and the
  request writes one `bulk_user_delete` record.

## Responses

Both routes return `200` with `success: true` whenever the request itself was valid, even if every
user failed. Read `summary` and `results`.

```json
{
  "success": true,
  "message": "Bulk update completed: 1 succeeded, 1 failed",
  "summary": {
    "total_requested": 2,
    "success_count": 1,
    "error_count": 1,
    "skipped_count": 0
  },
  "updates_applied": {"is_active": false},
  "results": [
    {"user_hash": "usr-a1b2c3", "success": true, "user_id": "usr-6f1e2d3c-4b5a-4968-8776-5a4b3c2d1e0f"},
    {"user_hash": "usr-d4e5f6", "success": false, "error": "User not found"}
  ],
  "errors": [
    {"user": "usr-d4e5f6", "error": "User not found"}
  ],
  "performed_by": "ops_admin",
  "performed_at": "2026-09-24T09:30:00.000000Z"
}
```

| Field | Update | Delete | Notes |
| --- | --- | --- | --- |
| `summary.total_requested` | Yes | Yes | Number of hashes sent |
| `summary.success_count`, `summary.error_count` | Yes | Yes | Per-user outcomes |
| `summary.skipped_count` | Yes | - | Always `0` today |
| `summary.protected_count` | - | Yes | Root users refused |
| `updates_applied` | Yes | - | The fields applied to every user |
| `results[]` | Yes | Yes | `user_hash`, `success`, `error` on failure; update adds `user_id` for users it changed |
| `errors[]` | Yes | Yes | `{"user", "error"}` per failure, or `{"operation", "error"}` if the whole batch failed |
| `warnings[]` | - | Yes | `{"user", "warning"}` for a user deleted whose session revocation failed; usually empty |
| `performed_by`, `performed_at` | Yes | Yes | Caller username and UTC time |

## Errors

| Status | Code | When |
| --- | --- | --- |
| `400` | `VAL_3010` | More than 100 (update) or 50 (delete) hashes |
| `400` | `VAL_3012` | Invalid `user_type` |
| `400` | `VAL_3002` | Update with neither `is_active` nor `user_type` |
| `400` | `VAL_3001` | Delete without `confirm_deletion=true`; update with `force_password_reset` (field not supported) |
| `401` | `AUTH_1003` | Missing, invalid or expired access token |
| `403` | `AUTHZ_2002` | Caller is not a root or admin user, session lacks `admin`/`manage_users`, or a non-root caller sent `user_type` |
| `422` | `VAL_3001` | `user_hashes` missing |

## Bulk versus single-user routes

| Check | Single-user routes | Bulk routes |
| --- | --- | --- |
| Admin project scoping | Overlap (projects the admin reaches) | Assigned scope (projects the admin administers) |
| Refuses the caller's own account | Yes (status, delete) | Yes (deactivation, delete) |
| Protects root users from admins | Yes | Yes |
| Protects root users from root | No | Delete only |
| Revokes sessions | Immediately | Immediately |
| Can reactivate | No | No |

A refused target makes a single-user route answer `400` or `403`; in bulk it is one failed entry in
`results` while the rest of the batch proceeds.

## Operating guidance

- Use bulk update for emergency deactivation waves and bulk delete for reviewed cleanup of known
  non-root accounts.
- Keep batches small for risky changes and keep the list of hashes you sent.
- After each call, rerun only the failed hashes once you understand each `error`.
- For group membership or role changes at scale, use the group and role bulk routes, not these.
