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

Route-level limits and validation:

- at least one `user_hashes` value is required
- maximum **100** users per request
- `user_type` must be `root`, `admin`, or `consumer` if provided
- at least one update field must be present
- `force_password_reset` is not supported; the route rejects it with guidance to reset-link recovery or `/auth/password/change`

Rejected password-control compatibility fields:

- Do not send `force_password_reset`; there is no forced login-gated password-change workflow in this change.
- Do not send `must_change_on_login` through direct utility callers; stale callers receive per-user errors instead of silent success.

### Result shape

The endpoint returns:

- `summary.total_requested`
- `summary.success_count`
- `summary.error_count`
- `summary.skipped_count`
- `updates_applied`
- `results`
- `errors`

### Current implementation contract

Bulk update is callable as documented. The route builds the utility contract directly:

- `user_updates` is a list of dictionaries shaped like `{"user_hash": "...", "updates": {...}}`
- the utility accepts that list-of-dicts shape and applies the requested fields per user

No boludez: still inspect the partial-success response, but do not treat this endpoint as broken because of the old 3-argument mismatch. That mismatch is gone.

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
- per-user validation or update failures reported in the partial-success payload

---

## Recommended Operational Use

### Use bulk update for:

- emergency deactivation of many accounts
- simple mass flag changes where the same update fields apply to many users

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
- **[Email Management](email-management.md)**
- **[User Types](user-types.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: June 2026
**Document Version**: 1.0
