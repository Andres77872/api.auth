# User Management Usage Cases (Legacy)

> **This document has been reorganized into a dedicated suite.**
>
> Start here: **[Users Documentation Suite](users/README.md)**

The former monolith has been split into focused documents:

- [usage.md](users/usage.md) — profile, access summary, user detail, update, status, reset, delete, list, search
- [user-types.md](users/user-types.md) — root/admin creation, type lifecycle, admin project assignment
- [bulk-operations.md](users/bulk-operations.md) — bulk update and bulk delete for users
- [architecture.md](users/architecture.md) — 3-tier model, group/project relationships, sessions, cache invalidation
- [request-flow.md](users/request-flow.md) — registration, login, list/detail scoping, type-change, deactivation, delete flows
- [scenarios.md](users/scenarios.md) — onboarding, offboarding, support, admin promotion workflows
- [reference.md](users/reference.md) — complete endpoint and query parameter reference
- [troubleshooting.md](users/troubleshooting.md) — common failures, caveats, and best practices

## Email Management Quick Reference

Email is optional. Current-user email lifecycle endpoints are:

- `GET /users/me/emails`
- `POST /users/me/emails`
- `POST /users/me/emails/{email_id}/resend`
- `DELETE /users/me/emails/{email_id}`
- `POST /users/me/emails/{email_id}/primary`

Add/resend responses are generic `202`; `429 + Retry-After` means the client must back off. Removing or changing primary email revokes other sessions while preserving the current authenticated session when possible.

Admin/root email endpoints are:

- `GET /users/{user_hash}/emails`
- `POST /users/{user_hash}/emails/{email_id}/resend`
- `POST /users/{user_hash}/reset-password`

Admin views expose masked/hash email fields only, never full recipient, token, activation/reset URL, body, or provider payload.

Admin password reset no longer returns or generates a visible temporary password. It queues a reset-link email for the target's primary activated email when possible, returns a generic accepted posture, and exposes no reset token/link/full email in the response. If the target has no deliverable activated email, the route remains non-enumerating and records only safe audit metadata.

Password-management compatibility rules:

- Use `POST /auth/password/change` for authenticated self-service password changes; `PUT /users/profile` rejects password-equivalent fields with sanitized guidance.
- Do not send `force_password_reset`; bulk/admin compatibility paths reject that retired field because there is no forced login-gated workflow.
- No `must_change_on_login` workflow exists in this change; admin reset remains reset-link based.

Session side effects:

- Authenticated current-user email removal/primary changes revoke other sessions while preserving the current session when possible.
- Public activation/reset consumes create no session and revoke the target user's existing sessions only after an actual state change.

---

**Document Version**: 2.0
