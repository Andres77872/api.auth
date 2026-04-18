# Users Bulk Operations

Operational guide for the user-focused bulk endpoints under `/admin/users/*`.

---

## Scope

This document covers:

- `POST /admin/users/bulk-update`
- `POST /admin/users/bulk-delete`

It does **not** cover:

- `/admin/projects/{hash}/bulk-assign-roles`
- `/admin/user-groups/bulk-assign`

Those are adjacent admin tools, but they are not user-entity lifecycle operations.

---

## Authentication and Input Shape

Both endpoints:

- validate the session token directly
- require session permissions containing `admin` or `manage_users`
- use `application/x-www-form-urlencoded`
- expect repeated `user_hashes=...` fields

---

## Bulk Update Users

### Route contract

```bash
curl -X POST "http://localhost:8000/admin/users/bulk-update" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-a&user_hashes=usr-b&is_active=false"
```

Accepted update fields at the route layer:

- `is_active`
- `user_type`
- `force_password_reset`

Route-level limits and validation:

- at least one `user_hashes` value is required
- maximum **100** users per request
- `user_type` must be `root`, `admin`, or `consumer` if provided
- at least one update field must be present

### Result shape

The endpoint returns:

- `summary.total_requested`
- `summary.success_count`
- `summary.error_count`
- `summary.skipped_count`
- `updates_applied`
- `results`
- `errors`

### Important implementation caveat

There is a repo-level mismatch here:

- the route calls `bulk_update_users(user_hashes, updates, current_user.id)`
- the imported utility function signature expects a list of per-user update dictionaries, not that 3-argument shape

So the **intended** public contract is clear from the route, but the current implementation should be verified in staging before you rely on it for production bulk updates. No boludez: do not discover this during an incident.

---

## Bulk Delete Users

### Route contract

```bash
curl -X POST "http://localhost:8000/admin/users/bulk-delete" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hashes=usr-a&user_hashes=usr-b&confirm_deletion=true"
```

Safety checks enforced by the route:

- `confirm_deletion=true` is required
- at least one `user_hashes` value is required
- maximum **50** users per request

Behavior from the utility layer:

- users not found are reported individually
- `root` users are protected from bulk delete
- delete is soft-delete via `delete_user()`
- the utility aggregates per-user failures instead of failing the whole request immediately

Response fields include:

- `summary.success_count`
- `summary.error_count`
- `summary.protected_count`
- `results`
- `errors`
- `warnings`

---

## Failure Handling and Operator Guidance

These endpoints are designed around **partial success** reporting.

That means:

- HTTP success does **not** mean every target user succeeded
- always inspect `errors`, `warnings`, and per-user `results`
- rerun only the failed subset after you understand the cause

Typical failure causes:

- invalid `user_hash`
- protected `root` target
- invalid `user_type`
- missing confirmation for bulk delete
- implementation mismatch on bulk update

---

## Recommended Operational Use

### Use bulk update for:

- emergency deactivation of many accounts
- simple mass flag changes after validating behavior in staging

### Use bulk delete for:

- controlled cleanup of known non-root accounts
- post-review retirement waves where audit preservation via soft delete is acceptable

### Do NOT use user bulk endpoints for:

- changing group membership at scale
- changing project reach at scale
- assigning roles

Those belong to the groups/roles admin endpoints.

---

## Related Documentation

- **[Users Overview](README.md)**
- **[Usage](usage.md)**
- **[User Types](user-types.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
