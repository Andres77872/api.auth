# Users troubleshooting

Symptom, cause and fix for the `/users`, `/user-types` and bulk user routes. Error codes are in the
[reference](reference.md#errors).

## Access and scoping

### Admin gets 403 "User not in your projects"

**Cause:** list, detail, update, status and soft delete let an admin act only on users who share at
least one project with the admin's reachable projects.

**Fix:** compare `GET /users/access-summary` for the admin with `GET /users/{user_hash}` as root. Give
the admin reach to one of the user's projects, or have root do the change.

### Admin can read a user but gets 403 on reset, email or type-info routes

**Cause:** these routes use the stricter *assigned* scope: the admin must be assigned to one of the
user's projects (member of its `admin_<project_id>` group). Reach through ordinary user groups does
not count. See [Caller rules](reference.md#caller-rules).

**Fix:** assign the admin to the project with `POST /user-types/admin/{user_hash}/projects/add`, or have
root perform the action.

### Admin gets 403 on a root user, or root users are missing from lists

**Cause:** by design. Root users reach every project, but they are outside every admin's scope:
admins cannot read, update, deactivate, delete, reset, list or search them, and bulk requests report
them as failed entries.

**Fix:** have a root user act on other root users.

### List or search returns fewer users than `limit`, or `total` looks wrong

**Cause:** `pagination.total` on `GET /users/list` ignores `search`, group and project filters and
admin scoping. Admin scoping is applied after the page (or search `limit`) is read.

**Fix:** treat `total` as an upper bound and page with `offset` until it reaches `total`. Narrow the
search term instead of raising the search `limit`, which is capped at `100`.

### User is signed out after a type change

**Cause:** by design. Changing a user's type (any type-change route or bulk update) revokes all of
their access sessions and refresh tokens, because a session carries the type it was issued for.
Username, legacy email and password changes do not sign the user out (a password change revokes only
the user's other sessions).

**Fix:** the user signs in again.

### `/auth/validate` still shows the old username

**Cause:** a session keeps the username it was issued with; a rename leaves existing sessions valid
and does not rewrite them.

**Fix:** the new name appears after the user's next sign-in. Read `GET /users/profile` for the
current value.

### Access changes do not show in the client

**Cause:** each request re-checks that the user is active, their type, admin assignments and project
reach, but the `accessible_projects` and `user_groups` returned at sign-in are snapshots.

**Fix:** read `GET /users/access-summary` for the current state. A client whose session project was
removed from the user's reach is signed out on its next request and must sign in to another project.

## Lifecycle

### Reactivating a user returns 404

**Cause:** routes look users up among active accounts only. `PUT /users/{user_hash}/status?is_active=true`
and bulk update with `is_active=true` cannot find a deactivated or soft-deleted user.

**Fix:** there is no reactivation route. Treat deactivation as one-way through the API.

### Soft delete returns 500 but the user is gone

**Cause:** the database still runs an old `sp_delete_user`, which reported the number of group
memberships it deactivated instead of whether the account changed. For a user without active
memberships the route then answers `500` (`INT_7001`), and bulk delete reports `Delete failed`, even
though the account was deactivated.

**Fix:** re-apply the procedures with `python scripts/schema_sync.py --env-file .env --apply`. The
affected user already shows `is_active: false` in
`GET /users/list?include_inactive=true&search=<username>`; do not retry.

### Status change or soft delete returns 400

**Cause:** you targeted your own account. Nobody can deactivate or delete themselves.

**Fix:** have another root or admin do it.

### Hard delete returns 403 or 400

**Cause:** `403`: the caller is not root. `400`: a root tried to delete their own account.

**Fix:** use a different root account. Check that permanent removal is really required first
([Permanently delete a user](usage.md#permanently-delete-a-user)).

## User types

### New admin cannot sign in to any project

**Cause:** the admin has no assigned project. Either the type was set with `PATCH /users/{user_hash}/type`,
`PUT /users/{user_hash}` or bulk update, or every project given at creation had no admin group and was
skipped (listed in the creation response's `skipped_projects`).

**Fix:** check `GET /user-types/admin/{user_hash}/projects`, then add a project with
`POST /user-types/admin/{user_hash}/projects/add`. A `404` (`NF_4003`) there means the project has no
`admin_<project_id>` group. The admin can use `POST /auth/platform/login` in the meantime.

### Create-admin response has `skipped_projects`

**Cause:** those projects have no admin group: an active `admin_<project_id>` user group granted a
project group that contains the project (archived or inactive projects never qualify). The admin was
not assigned to them; `assigned_projects` lists only the real assignments.

**Fix:** give the project an admin group ([How admin assignment works](user-types.md#how-admin-assignment-works);
`POST /projects` creates one), then add the project with
`POST /user-types/admin/{user_hash}/projects/add`.

### Promotion to admin returns 404 `NF_4003`

**Cause:** `PUT /user-types/{user_hash}/type` with `user_type=admin` names a project that has no admin
group. The check runs before anything changes, so the user keeps their old type.

**Fix:** choose a project with an admin group, or give the project one first (see
[Create-admin response has `skipped_projects`](#create-admin-response-has-skipped_projects)).

### Statistics show system-wide counts to an admin

**Cause:** `GET /user-types/stats` always counts every active user; only the `scope` block differs
for admins.

**Fix:** none; for project-level numbers use `GET /users/list?project_filter=<project_hash>`.

### Demoted admin still reaches the old projects

**Cause:** changing the type does not remove `admin_<project_id>` memberships, and those groups grant
their projects to any member.

**Fix:** remove the memberships with `DELETE /admin/user-groups/{group_hash}/members/{user_hash}`. Next
time, remove the projects before demoting ([Demote an admin](user-types.md#demote-an-admin)).

### Admin project routes return 400 "User is not an admin user"

**Cause:** the four `/user-types/admin/{user_hash}/projects` routes only accept users whose current
type is `admin`.

**Fix:** check the type with `GET /user-types/{user_hash}/info`.

### Removing an admin from a project returns 404

**Cause:** the admin is not assigned to that project (`NF_4003`), or the user or project is unknown.

**Fix:** read `GET /user-types/admin/{user_hash}/projects` first and only remove listed projects,
using their `project_id`.

## Password reset and email

### Reset-password returns `has_delivery_target: false`

**Cause:** the user has no `activated` address. Pending, removed and suppressed addresses do not
count, and neither does the legacy `users.email` field.

**Fix:** the user adds and activates an address ([User email management](email-management.md)); an
operator can re-send a pending activation with `POST /users/{user_hash}/emails/{email_id}/resend`.

### Adding an address returns 202 but no email arrives

**Cause:** the `202` is identical for every outcome. Nothing is sent when the address is already
activated or suppressed on the account, or the account already has 5 pending or activated
addresses. A queued email can also still be waiting in the outbox.

**Fix:** check `GET /users/me/emails` (or the admin view). Remove unused pending addresses to get under
the limit, then check delivery in the [email suite](../email/README.md).

### Activation link opened but the address stays `pending`

**Cause:** another account already holds the address as activated, the link expired
(`EMAIL_ACTIVATION_TOKEN_TTL_SECONDS`, default `86400`), or a newer link replaced it.

**Fix:** request a new link with the resend route. If another account holds the address, the user
needs a different address, or root frees it
([Free an address held by a deleted account](scenarios.md#free-an-address-held-by-a-deleted-account)).

### Email routes return 429

**Cause:** a send bucket (per recipient, caller or IP) is full, the resend cooldown
(`EMAIL_RESEND_COOLDOWN_SECONDS`, default `60`) is active, or Redis is unavailable (the limiter fails
closed). Retries with the same `Idempotency-Key` still count.

**Fix:** wait for `Retry-After`. Check Redis health if every send is refused.

### Setting the primary address returns 409

**Cause:** the address is not one of the caller's own `activated`, non-removed addresses.

**Fix:** activate it first, or pick an `id` from `GET /users/me/emails` with `status: "activated"`.

### Users are signed out after email changes

**Cause:** by design. Activating an address signs the user out everywhere; removing an address or
changing the primary signs out every session except the one that made the change.

**Fix:** sign in again on the other devices.

## Bulk operations

### Bulk update or delete reports "User not found" for a known user

**Cause:** the user is inactive; bulk routes look up active users only.

**Fix:** nothing to do for deletes or deactivations. Reactivation is not possible through the API.

### Bulk routes return 403 for a valid token

**Cause:** the caller is not a root or admin user (a consumer is refused even with `admin` or
`manage_users` from a global role), the session's permissions lack both names, or a non-root caller
sent `user_type`.

**Fix:** use a root or admin session; only root may change types in bulk.

### Bulk results fail some users with a scope or self error

**Cause:** each target is checked like the single-user routes: nobody may deactivate or delete their
own account, and an admin may only touch non-root users who reach a project the admin is assigned to.
Refused users are left unchanged; the rest of the batch still runs.

**Fix:** remove those hashes, or have root act on them.
