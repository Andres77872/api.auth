# Users scenarios

End-to-end workflows that chain several user-management calls. Background is linked from each
scenario; field tables are in the [reference](reference.md).

## Onboard a self-registered consumer

Goal: a new person joins an existing user group, signs in, and gets a usable email address.

```bash
# 1. Optional: check the username is free
curl -X POST "http://localhost:8000/auth/check-availability" \
  -d "username=new_employee"

# 2. Register into a user group that already reaches a project
curl -X POST "http://localhost:8000/auth/register" \
  --data-urlencode "username=new_employee" \
  --data-urlencode "password=$NEW_PASSWORD" \
  -d "user_group_hash=$USER_GROUP_HASH"

# 3. Add a sign-in and recovery address (the user opens the emailed link next)
curl -X POST "http://localhost:8000/users/me/emails" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "email=new.employee@example.com"

# 4. After activating the address, sign in again and confirm reach
curl "http://localhost:8000/users/access-summary" \
  -H "Authorization: Bearer $TOKEN"
```

- Registration always creates a `consumer`. If the group reaches no active project, the account is
  still created but no tokens are issued; add the user to a group with project reach before they
  sign in.
- An `email` sent to `/auth/register` only fills the legacy `users.email` column. Step 3 is what makes
  email sign-in and password recovery work ([User email management](email-management.md)).
- Activating the address revokes every session of the user, so step 4 needs a fresh sign-in.

## Create a multi-project admin

Goal: a root creates an operator who administers two projects.

```bash
# 1. Create the admin with both internal project IDs
curl -X POST "http://localhost:8000/user-types/admin" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  --data-urlencode "username=ops_admin" \
  --data-urlencode "password=$INITIAL_PASSWORD" \
  -d "assigned_project_ids=$PROJECT_ID_1&assigned_project_ids=$PROJECT_ID_2"

# 2. Confirm the assignments really exist
curl "http://localhost:8000/user-types/admin/$ADMIN_HASH/projects" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

- A project without an admin group is not assigned: the creation response lists it under
  `skipped_projects`, and `assigned_projects` holds only the real assignments. Step 2 confirms them
  ([User types](user-types.md#create-an-admin-user)).
- The admin signs in with `POST /auth/login` and one of the assigned `project_hash` values, or with
  `POST /auth/platform/login` for dashboard work without a project.
- Hand over the initial password out of band and have the admin change it with
  `POST /auth/password/change`, then add an email address for recovery.

## Promote a consumer to admin

```bash
# 1. Promote with the first project
curl -X PUT "http://localhost:8000/user-types/$USER_HASH/type" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -d "user_type=admin&assigned_project_id=$PROJECT_ID"

# 2. Add more projects
curl -X POST "http://localhost:8000/user-types/admin/$USER_HASH/projects/add" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -d "project_id=$OTHER_PROJECT_ID"

# 3. Check the result
curl "http://localhost:8000/user-types/admin/$USER_HASH/projects" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

- Step 1 returns `404` (`NF_4003`) and changes nothing if the project has no admin group.
- The promotion signs the user out everywhere; they sign in again to get an admin session.
- Do not promote with `PATCH /users/{user_hash}/type`: it leaves the admin with no project. To
  reverse a promotion, follow [Demote an admin](user-types.md#demote-an-admin); the order of steps
  matters.

## Review who can reach a project

Goal: an admin audits the users of one of their projects before a change.

```bash
# 1. Users who reach the project through their groups
curl "http://localhost:8000/users/list?project_filter=$PROJECT_HASH&include_inactive=false&limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2. Why a given user reaches it, and with which permissions
curl "http://localhost:8000/users/$USER_HASH?include_permission_details=true" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Keep paging with `offset` until it reaches `pagination.total`; admin pages can be short. A `403` in
step 2 means the user shares no project with you or is a root user.

## Offboard a departing user

Goal: cut access now, keep the record.

```bash
# 1. Record the current state (groups, projects, permissions)
curl "http://localhost:8000/users/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2a. Deactivate the account only; group memberships are kept
curl -X PUT "http://localhost:8000/users/$USER_HASH/status?is_active=false" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2b. Or soft-delete: deactivates the account and its group memberships
curl -X DELETE "http://localhost:8000/users/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

- Pick one of 2a or 2b. Both revoke sessions and refresh tokens, and after either one the user is
  inactive, so the other call no longer finds them.
- Both are one-way through the API: no route reactivates an account.
- Keep the account unless something requires permanent removal
  ([Permanently delete a user](usage.md#permanently-delete-a-user)).

## Respond to a suspected account takeover

Choose by whether the user keeps the account.

```bash
# 1. Check the user's addresses first (masked)
curl "http://localhost:8000/users/$USER_HASH/emails" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2a. Stop the account now (one-way): all sessions are revoked immediately
curl -X PUT "http://localhost:8000/users/$USER_HASH/status?is_active=false" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2b. Or keep the account: send a reset link; completing it revokes every session
curl -X POST "http://localhost:8000/users/$USER_HASH/reset-password" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

- The reset link goes to the primary activated address, else the earliest-activated one. If the user
  does not recognize that address, a link would go to whoever controls it; deactivate instead.
- Existing sessions stay valid until the reset is completed, so prefer deactivation while the
  attacker may still be signed in.

## Help a user who receives no reset link

```bash
# 1. Queue a link and read has_delivery_target
curl -X POST "http://localhost:8000/users/$USER_HASH/reset-password" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2. Inspect the user's addresses (masked)
curl "http://localhost:8000/users/$USER_HASH/emails" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 3. If an address is still pending, re-send its activation link
curl -X POST "http://localhost:8000/users/$USER_HASH/emails/$EMAIL_ID/resend" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

- `has_delivery_target: false` means the user has no activated address; nothing was sent.
- A `suppressed` address bounced or complained at the provider and receives nothing; the user should
  remove it and add a working one.
- If the address is activated and the link still does not arrive, follow the delivery checks in the
  [email suite](../email/README.md).

## Free an address held by a deleted account

Goal: a new account cannot activate an address because a soft-deleted account still holds it.

Soft delete keeps the old account's `user_emails` rows, and an activated address can belong to only
one account, so the new account's activation link is consumed without effect.

```bash
# 1. Find the old account; its legacy email field holds its primary address
curl "http://localhost:8000/users/list?include_inactive=true&search=old.address@example.com" \
  -H "Authorization: Bearer $ROOT_TOKEN"

# 2. Permanently delete it (hard delete also finds inactive users)
curl -X DELETE "http://localhost:8000/users/$OLD_USER_HASH/hard" \
  -H "Authorization: Bearer $ROOT_TOKEN"

# 3. The new account's address is still pending: request a fresh activation link
curl -X POST "http://localhost:8000/users/me/emails/$EMAIL_ID/resend" \
  -H "Authorization: Bearer $TOKEN"
```

Hard delete is irreversible and removes everything the old account owned; read
[Permanently delete a user](usage.md#permanently-delete-a-user) first.

## Deactivate many accounts at once

```bash
# 1. Collect the hashes (for example, everyone in a user group)
curl "http://localhost:8000/users/list?group_filter=$USER_GROUP_HASH&include_group_info=false&include_project_access=false&limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2. Deactivate up to 100 per request
curl -X POST "http://localhost:8000/admin/users/bulk-update" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -d "user_hashes=$USER_A&user_hashes=$USER_B&is_active=false"
```

Read `summary` and `results` in the `200` response, fix the causes, and resend only the failed hashes.
Your own account, and for an admin root users and users outside the projects you administer, fail
individually and are left unchanged ([Bulk user operations](bulk-operations.md)).
