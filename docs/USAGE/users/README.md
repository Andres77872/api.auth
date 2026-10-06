# Users

The users domain manages accounts: each user's profile, type (`root`, `admin` or `consumer`), email
addresses and lifecycle from creation to deletion. End users call it to read their own access and
manage their addresses; root and admin operators call it to find, update, deactivate and delete
users, create operators and assign admins to projects. Group membership, roles and permissions are
managed by other suites.

## Key concepts

- **User types.** `root` operates everything; `admin` administers the projects they are assigned
  to; `consumer` is an end user. See [User types](user-types.md).
- **Reach comes from groups.** Users reach projects through user group, project group and project
  links; root reaches every active project. There is no direct user-to-project link.
- **Admin assignment is group membership.** An admin is assigned to a project by joining its
  `admin_<project_id>` user group.
- **Email addresses are separate identities.** `user_emails` holds up to 5 pending or activated
  addresses per user; only activated ones sign in or receive reset links. The email in user summaries comes from the activated primary address.
- **Soft delete by default.** Deactivation and soft delete keep the row; hard delete removes it and
  everything the user owns. No route reactivates an account.

## Route families

| Family | Routes | Caller | Details |
| --- | --- | --- | --- |
| Self-service | `GET`/`PUT /users/profile`, `GET /users/access-summary`, `/users/me/emails*` | Any signed-in user | [Usage](usage.md), [email management](email-management.md) |
| User administration | `/users/list`, `/users/search/query`, `/users/{user_hash}` (read, update, status, reset-password, soft and hard delete, type), `/users/{user_hash}/emails*` | Root or admin; hard delete and type change root only | [Usage](usage.md) |
| User types | `/user-types/*` (10 routes) | Root; type info, list by type and stats also admin | [User types](user-types.md) |
| Bulk | `POST /admin/users/bulk-update`, `POST /admin/users/bulk-delete` | Root or admin with session permission `admin` or `manage_users` | [Bulk user operations](bulk-operations.md) |

`src/routes/users.py` registers 19 routes, `src/routes/user_types_auth.py` 10, and
`src/routes/bulk_operations.py` 4 (2 of them documented here). The full inventory is in the
[reference](reference.md#endpoints).

## Rules and caveats

- Write routes take form fields; `POST /users/me/emails` also accepts JSON.
- Admins are scoped two ways: by projects they *reach* (list, detail, update, status, soft delete)
  and by projects they are *assigned* to (search, reset-password, email and type-info routes). See
  [Caller rules](reference.md#caller-rules).
- Root users reach every project but are outside every admin's scope: admins cannot read, update,
  deactivate, delete, reset or list them, singly or in bulk.
- Inactive users return `404` on every route except hard delete, and cannot be reactivated through
  the API.
- Updating a profile, username keeps the user's sessions. Changing a user's type
  signs them out everywhere (access sessions and refresh families).
- Only `PUT /user-types/{user_hash}/type` assigns a project when promoting to `admin`.
- Hard delete is root-only and irreversible; use it only when permanent removal is required.
- Email send routes answer a generic `202`; `429` with `Retry-After` is the only detailed reply.
- Passwords are changed in the auth routes. `POST /users/{user_hash}/reset-password` queues a link
  and never returns a password or token.

## In this suite

| Document | Purpose |
| --- | --- |
| [usage.md](usage.md) | Tasks: own profile and access, finding users, updating, deactivating, reset links, deleting |
| [user-types.md](user-types.md) | Creating root and admin users, changing types, admin project assignment |
| [email-management.md](email-management.md) | Adding, activating, removing and choosing email addresses; admin views |
| [bulk-operations.md](bulk-operations.md) | Contract for bulk update and bulk delete |
| [scenarios.md](scenarios.md) | End-to-end workflows: onboarding, admin setup, offboarding, incidents |
| [reference.md](reference.md) | Endpoints, caller rules, fields, responses, errors, settings |
| [request-flow.md](request-flow.md) | What each request does from authentication to stored procedures and Redis |
| [architecture.md](architecture.md) | Model, tables, scoping design, revocation and lifecycle decisions |
| [troubleshooting.md](troubleshooting.md) | Symptoms, causes and fixes |

## Related

- [Usage documentation home](../README.md)
- [Authentication usage](../authentication-usage-cases.md): sign-in, refresh, password change and reset
- [Groups](../groups/README.md), [Projects](../projects/README.md), [Roles](../roles/README.md) and
  [Permissions](../permissions/README.md) suites
- [Email suite](../email/README.md): outbox, worker, templates and provider webhooks
- [Admin usage cases](../admin-usage-cases.md): dashboard, cache, and the role and group bulk routes
- [Error reference](../errors.md)
