# Users Documentation

Detailed, repo-specific documentation for the user-management system implemented in `api.auth`.

---

## 📖 Overview

The users domain in this repository is a **3-tier model** layered on top of the groups-of-groups access architecture:

```text
ROOT      → global administrative scope
ADMIN     → assigned projects via admin user-group membership
CONSUMER  → USER → USER_GROUP → PROJECT_GROUP → PROJECT
```

What matters operationally:

- **`root` users** are global operators — they bypass group-membership validation on `/auth/login` but **still require `project_hash`** to log in. Root/admin can use `/auth/platform/login` if they need login without project binding (consumer users are rejected from platform login)
- **`admin` users** are still normal `users` rows, but their reach comes from assignment to project-specific admin groups
- **`consumer` users** get project reach through user groups and project groups, not direct user-to-project links
- **`/users/*`** (18 endpoints) covers profile, access summary, list/search, detail, status, reset, delete, one type-change endpoint, and per-user email management (multi-email, primary email, activation resend)
- **`/user-types/*`** covers root/admin creation, type inspection, admin-project assignment, and the stricter type-management path
- **`/admin/users/bulk-*`** covers bulk update/delete for users only

---

## 🗂️ Documents in This Suite

| Document | Focus |
|----------|-------|
| [usage.md](usage.md) | Day-to-day profile, access summary, listing, detail, status, reset, delete, and update flows |
| [email-management.md](email-management.md) | Per-user email lifecycle (multi-email, primary, activation resend) and admin/root email inspection/resend |
| [user-types.md](user-types.md) | Root/admin creation, type lifecycle, admin project assignment, and type-management caveats |
| [bulk-operations.md](bulk-operations.md) | Bulk update and bulk delete behavior, limits, error handling, and implementation caveats |
| [architecture.md](architecture.md) | 3-tier model, tables, route split, group/project relationships, sessions, and cache invalidation |
| [request-flow.md](request-flow.md) | End-to-end runtime flow for registration, login, listing, scoping, type changes, deactivation, and deletion |
| [scenarios.md](scenarios.md) | Concrete curl-based workflows for onboarding, offboarding, access review, and admin lifecycle tasks |
| [reference.md](reference.md) | Endpoint reference for `/users/*`, `/user-types/*`, and `/admin/users/bulk-*` |
| [troubleshooting.md](troubleshooting.md) | Common failure modes, stale-session behavior, scoping confusion, and operator best practices |

---

## 🧠 Core User Model in This Repo

### User entity

- Stored in `users`
- `user_type` is an enum: `root`, `admin`, `consumer`
- `role_id` exists as the global role attachment point
- `is_active = 0` is the soft-delete/deactivation mechanism

### Access model

- **Consumers** reach projects through `user_group_members` → `user_group_project_groups` → `project_group_members`
- **Admins** also reach projects through group membership, but typically through project admin groups discovered with `sp_find_admin_group_for_project`
- **Roots** bypass **group-membership validation** on `/auth/login` (can access any project without group membership) — but they still require `project_hash` to specify the target project. Use `/auth/platform/login` for root/admin login without `project_hash`.

### What `/users/*` does NOT manage directly

- user-group membership
- project-group wiring
- role assignment
- permission-group assignment

Those live in the groups, roles, and permissions suites.

---

## 🚦 Recommended Reading Order

1. Start with [usage.md](usage.md)
2. Then read [architecture.md](architecture.md)
3. Use [request-flow.md](request-flow.md) for runtime behavior
4. Read [user-types.md](user-types.md) before changing user types or creating admins
5. Read [bulk-operations.md](bulk-operations.md) before mass changes
6. Keep [reference.md](reference.md) open while operating the API
7. Use [scenarios.md](scenarios.md) and [troubleshooting.md](troubleshooting.md) for real workflows and failure handling

---

## ⚠️ Scope and Caveats

- This suite documents the active route layer in `src/routes/users.py` (18 endpoints, including the per-user email-management group — see [email-management.md](email-management.md)), `src/routes/user_types_auth.py` (10 endpoints), and `src/routes/bulk_operations.py`
- There are **two type-change routes**: `/users/{hash}/type` and `/user-types/{hash}/type`. They overlap, but they do **not** enforce the same constraints
- Admin scoping is **not perfectly uniform** across list, search, and some user-type endpoints; caveats are called out where the code diverges
- Admin password reset queues a secure reset link when the target has a primary activated email; it does not return a temporary password, reset token, reset link, full email, or provider payload
- `PUT /users/profile` rejects password-equivalent fields; use `POST /auth/password/change` for self-service password changes
- Role/group assignment is intentionally managed outside the `/users/*` routes

---

## 🔗 Related Documentation

- **[Usage Documentation Home](../README.md)** - Complete usage index
- **[Email Management](email-management.md)** - Per-user email lifecycle endpoints and admin/root email inspection/resend
- **[Email Activation Runbook](../../RUNBOOKS/email-activation.md)** - Tokens, durable outbox, worker, webhooks, suppression, retention, rollback
- **[Authentication Usage Cases](../authentication-usage-cases.md)** - Login, registration, refresh, logout, project switching
- **[Groups Documentation Suite](../groups/README.md)** - User groups, project groups, and the access bridge
- **[Projects Documentation Suite](../projects/README.md)** - Project reach and project-scoped context
- **[Permissions Documentation Suite](../permissions/README.md)** - Permission sources, direct assignments, and authorization caveats
- **[Roles Documentation Suite](../roles/README.md)** - Global role CRUD and user role assignment
- **[Admin Usage Cases](../admin-usage-cases.md)** - Dashboard, health, cache management, and admin operations outside the users domain
- **[Database Schema](../../../schemas/)** - SQL tables and stored procedures

---

**Last Updated**: June 2026
**Document Version**: 1.1
