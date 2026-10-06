# Permissions scenarios

End-to-end workflows that chain several calls. Each step links the fields it needs to
[Permissions reference](reference.md); the rules behind the outcomes are in
[Permission resolution](resolution.md). Examples use `http://localhost:8000`, `$ROOT_TOKEN` for a
root session, `$TOKEN` for an admin session, and `$USER_TOKEN` for the affected user.

## Make a permission effective for a consumer

**Goal:** a consumer must pass a guard that checks a permission, for example `manage_users` on
`/admin/user-groups`.

Guards read the auth-time set, which for consumers comes only from the global role. Assigning the
permission group to the user's user group or directly to the user will not work.

1. Find the user's role and its groups:

   ```bash
   curl "http://localhost:8000/roles/users/$USER_HASH/role" -H "Authorization: Bearer $TOKEN"
   curl "http://localhost:8000/roles/$ROLE_HASH/permission-groups" -H "Authorization: Bearer $TOKEN"
   ```

2. Link a group containing the permission to that role, or assign the user a role that has it
   (both in [Roles usage](../roles/usage.md)). `manage_users` is a reserved name, so only root can link
   a group containing it or assign a role that grants it:

   ```bash
   curl -X POST "http://localhost:8000/roles/$ROLE_HASH/permission-groups/$PG_HASH" \
     -H "Authorization: Bearer $ROOT_TOKEN"
   ```

3. Verify as the user. The group must appear under `sources.from_role`:

   ```bash
   curl "http://localhost:8000/permissions/users/me/permission-sources" \
     -H "Authorization: Bearer $USER_TOKEN"
   ```

4. The user's existing access token picks up the change within `VALIDATE_CACHE_TTL` seconds
   (default `30`); a refresh picks it up at once. No re-login is needed.

## Delegate the `/permissions` admin routes to a team

**Goal:** let a support team manage user-group and direct assignments without giving it `/roles`
write access.

The `/permissions` admin guard accepts `manage_roles` from any source, while the `/roles` guard and
session-based guards accept it only from the role.

1. As root, create a group holding `manage_roles` (a reserved name, so root only):

   ```bash
   curl -X POST "http://localhost:8000/roles/permission-groups" \
     -H "Authorization: Bearer $ROOT_TOKEN" \
     -d "group_name=assignment_admins" -d "group_display_name=Assignment admins"
   curl -X POST "http://localhost:8000/roles/permission-groups/$PG_HASH/permissions/$MANAGE_ROLES_PERMISSION_HASH" \
     -H "Authorization: Bearer $ROOT_TOKEN"
   ```

2. As root, assign the group to the team's user group (it contains a reserved name):

   ```bash
   curl -X POST "http://localhost:8000/permissions/admin/user-groups/$SUPPORT_GROUP_HASH/permission-groups" \
     -H "Authorization: Bearer $ROOT_TOKEN" \
     -d "permission_group_hash=$PG_HASH"
   ```

3. A team member checks the result; `has_permission` is `true` right away (no cache):

   ```bash
   curl "http://localhost:8000/permissions/users/me/permissions/check/manage_roles" \
     -H "Authorization: Bearer $USER_TOKEN"
   ```

The member can now call every `/permissions` admin route. `POST /roles` and
`/admin/project-groups` still return `403`.

Team members cannot widen or narrow the delegation themselves: assigning or removing
`assignment_admins` is root-only because it contains `manage_roles`. Audit who holds it with
`GET /permissions/permissions/groups/{pg_hash}/users` and `.../user-groups`.

## Grant and later remove a temporary direct assignment

**Goal:** record an exception for one user, with a reason, and remove it when it ends.

```bash
# 1. Assign with a reason
curl -X POST "http://localhost:8000/permissions/users/$USER_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "permission_group_hash=$REPORTING_PG_HASH" \
  --data-urlencode "notes=Q3 audit, remove after close"

# 2. Confirm it and read the notes back
curl "http://localhost:8000/permissions/users/$USER_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"

# 3. Remove it
curl -X DELETE "http://localhost:8000/permissions/users/$USER_HASH/permission-groups/$REPORTING_PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

A direct assignment does not change the user's auth-time permissions. Use it for records that
clients read through the inspection endpoints, or for `manage_roles` delegation as above. If the
exception must pass a guard, change the role instead.

## Audit why a user has a permission

**Goal:** explain a permission name the user sees.

1. As the user, list permissions and group sources:

   ```bash
   curl "http://localhost:8000/permissions/users/me/permissions" -H "Authorization: Bearer $USER_TOKEN"
   curl "http://localhost:8000/permissions/users/me/permission-sources" -H "Authorization: Bearer $USER_TOKEN"
   ```

2. For each group in `sources`, list its permissions:

   ```bash
   curl "http://localhost:8000/roles/permission-groups/$PG_HASH/permissions" -H "Authorization: Bearer $USER_TOKEN"
   ```

3. If a name is in `permissions` but no source group contains it, it comes through a soft-deleted
   role or permission group. `/permission-sources` hides inactive roles and groups;
   `/permissions` does not. See [Soft-delete effects](resolution.md#soft-delete-effects).

Without the user's token, an admin can assemble the same picture from
`GET /roles/users/{user_hash}/role`, `GET /permissions/users/{user_hash}/permission-groups`, and the
permission groups of each user group the user belongs to
(`GET /permissions/admin/user-groups/{group_hash}/permission-groups`).

## Retire a permission group cleanly

**Goal:** stop a permission group from granting anything.

Deleting the group (`DELETE /roles/permission-groups/{group_hash}`) is enough to revoke it
everywhere: every resolver ignores a deleted group, even while role links and assignments to it
remain. Unlinking first is still worth it when you want the links gone rather than kept as history,
because a deleted group no longer resolves by hash and its links can then no longer be removed
through the API.

```bash
# 1. Where is it assigned?
curl "http://localhost:8000/permissions/permissions/groups/$PG_HASH/user-groups" -H "Authorization: Bearer $TOKEN"
curl "http://localhost:8000/permissions/permissions/groups/$PG_HASH/users" -H "Authorization: Bearer $TOKEN"
curl "http://localhost:8000/roles?limit=100" -H "Authorization: Bearer $TOKEN"
#    then GET /roles/{role_hash}/permission-groups for each role

# 2. Remove every link
curl -X DELETE "http://localhost:8000/roles/$ROLE_HASH/permission-groups/$PG_HASH" -H "Authorization: Bearer $TOKEN"
curl -X DELETE "http://localhost:8000/permissions/admin/user-groups/$USER_GROUP_HASH/permission-groups/$PG_HASH" -H "Authorization: Bearer $TOKEN"
curl -X DELETE "http://localhost:8000/permissions/users/$USER_HASH/permission-groups/$PG_HASH" -H "Authorization: Bearer $TOKEN"

# 3. Delete the group
curl -X DELETE "http://localhost:8000/roles/permission-groups/$PG_HASH" -H "Authorization: Bearer $TOKEN"
```

If the group contains a reserved name, steps 2 and 3 need a root token: role unlinks, user-group and
direct removals, and the delete are all root-only for such a group.

## Diagnose a 403 after a permission change

**Goal:** find out why a consumer still gets `403` after being given a permission.

1. Look up which set the target route checks in
   [Guards on the role and permission APIs](resolution.md#guards-on-the-role-and-permission-apis).
2. If it reads the auth-time set or is a `/roles` write, only the role counts. Confirm the group is
   under `from_role`:

   ```bash
   curl "http://localhost:8000/permissions/users/me/permission-sources" -H "Authorization: Bearer $USER_TOKEN"
   ```

3. If it is there, wait `VALIDATE_CACHE_TTL` seconds (default `30`) or refresh the token:

   ```bash
   curl -X POST "http://localhost:8000/auth/refresh" -d "refresh_token=$REFRESH_TOKEN"
   ```

4. If it is still denied, the route has another condition (for example project access, admin
   scope, or root only). Check that route's suite.

## Publish recommended groups for a project UI

**Goal:** show operators which permission groups usually go with a project.

```bash
curl -X POST "http://localhost:8000/permissions/projects/$PROJECT_HASH/permission-group-catalog/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "catalog_purpose=Editorial baseline"
curl "http://localhost:8000/permissions/projects/$PROJECT_HASH/permission-group-catalog" \
  -H "Authorization: Bearer $USER_TOKEN"
```

The role equivalent is the [project role catalog](../roles/usage.md#manage-a-project-role-catalog).
Neither catalog changes access; assign through the role or the routes above.
