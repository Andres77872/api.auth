# Roles scenarios

End-to-end workflows that chain several `/roles` calls. Field rules are in
[Roles reference](reference.md); why each result looks the way it does is in
[Permission resolution](../permissions/resolution.md). Examples use `http://localhost:8000`,
`$ROOT_TOKEN` for a root session, `$TOKEN` for an admin session, and `$USER_TOKEN` for the affected
user.

## Build a role and give it to a user

**Goal:** a `content_editor` role that grants `read_data` and `write_data`, assigned to one consumer.

```bash
# 1. Permissions (keep each permission_hash)
curl -X POST "http://localhost:8000/roles/permissions" -H "Authorization: Bearer $TOKEN" \
  -d "permission_name=read_data" -d "permission_display_name=Read data" -d "permission_category=data"
curl -X POST "http://localhost:8000/roles/permissions" -H "Authorization: Bearer $TOKEN" \
  -d "permission_name=write_data" -d "permission_display_name=Write data" -d "permission_category=data"

# 2. A group holding both (keep group_hash)
curl -X POST "http://localhost:8000/roles/permission-groups" -H "Authorization: Bearer $TOKEN" \
  -d "group_name=content_editing" -d "group_display_name=Content editing"
curl -X POST "http://localhost:8000/roles/permission-groups/$GROUP_HASH/permissions/$READ_HASH" -H "Authorization: Bearer $TOKEN"
curl -X POST "http://localhost:8000/roles/permission-groups/$GROUP_HASH/permissions/$WRITE_HASH" -H "Authorization: Bearer $TOKEN"

# 3. The role, linked to the group (keep role_hash)
curl -X POST "http://localhost:8000/roles" -H "Authorization: Bearer $TOKEN" \
  -d "role_name=content_editor" -d "role_display_name=Content editor" -d "role_priority=60"
curl -X POST "http://localhost:8000/roles/$ROLE_HASH/permission-groups/$GROUP_HASH" -H "Authorization: Bearer $TOKEN"

# 4. Assign it
curl -X PUT "http://localhost:8000/roles/users/$USER_HASH/role" -H "Authorization: Bearer $TOKEN" \
  -d "role_hash=$ROLE_HASH"

# 5. The user confirms: content_editing is listed under sources.from_role
curl "http://localhost:8000/permissions/users/me/permission-sources" -H "Authorization: Bearer $USER_TOKEN"
```

The user's session permissions include `read_data` and `write_data` within about 30 seconds, without
a new login. If the user is `root` or `admin`, the role has no effect on their session.

## Delegate role management to a consumer

**Goal:** a consumer can maintain ordinary roles and assignments without being an `admin` user.

The `/roles` guard accepts `manage_roles` only from the caller's role, and `manage_roles` is a
reserved name, so root sets this up.

```bash
# 1. Root puts manage_roles into a group and the group into a role
curl -X POST "http://localhost:8000/roles/permission-groups" -H "Authorization: Bearer $ROOT_TOKEN" \
  -d "group_name=role_admin" -d "group_display_name=Role administration"
curl -X POST "http://localhost:8000/roles/permission-groups/$PG_ROLE_ADMIN/permissions/$MANAGE_ROLES_HASH" \
  -H "Authorization: Bearer $ROOT_TOKEN"
curl -X POST "http://localhost:8000/roles" -H "Authorization: Bearer $ROOT_TOKEN" \
  -d "role_name=role_manager" -d "role_display_name=Role manager"
curl -X POST "http://localhost:8000/roles/$ROLE_MANAGER_HASH/permission-groups/$PG_ROLE_ADMIN" \
  -H "Authorization: Bearer $ROOT_TOKEN"

# 2. Root assigns the role (it grants a reserved name)
curl -X PUT "http://localhost:8000/roles/users/$DELEGATE_HASH/role" -H "Authorization: Bearer $ROOT_TOKEN" \
  -d "role_hash=$ROLE_MANAGER_HASH"
```

The delegate can now create and edit roles, groups, and permissions, link them, and assign roles to
other users. It still gets `403` for anything involving a reserved name and for its own role.
Role-derived `manage_roles` also opens the `/permissions` admin routes and the first check of
`/admin/project-groups`, so plan the delegation with the full
[guard list](../permissions/resolution.md#guards-on-the-role-and-permission-apis) in mind.

## Change a user's role

**Goal:** move a user from `content_editor` to `viewer`.

```bash
curl "http://localhost:8000/roles/users/$USER_HASH/role" -H "Authorization: Bearer $TOKEN"
curl -X PUT "http://localhost:8000/roles/users/$USER_HASH/role" -H "Authorization: Bearer $TOKEN" \
  -d "role_hash=$VIEWER_HASH"
```

The `PUT` replaces the old role in one step; there is nothing to remove first. If either role grants
a reserved name, only root can make the change. The user's existing tokens switch to the new
permissions within about 30 seconds; `POST /auth/refresh` applies it at once.

## Rename a role

**Goal:** `role_name` is immutable, so replace `editor` with `content_editor`.

1. Create `content_editor` and read the old role's groups:

   ```bash
   curl "http://localhost:8000/roles/$OLD_ROLE_HASH/permission-groups" -H "Authorization: Bearer $TOKEN"
   ```

2. Link each of those groups to the new role
   (`POST /roles/{role_hash}/permission-groups/{group_hash}`).
3. Reassign every holder with `PUT /roles/users/{user_hash}/role`. No endpoint lists a role's
   holders, so work from your own user list; bulk assignment takes the role **name**:

   ```bash
   curl -X POST "http://localhost:8000/admin/projects/$PROJECT_HASH/bulk-assign-roles" \
     -H "Authorization: Bearer $TOKEN" \
     -d "user_hashes=$USER_A" -d "user_hashes=$USER_B" -d "role_names=content_editor"
   ```

4. Delete the old role. Its name stays taken.

A display-name change alone does not need any of this: `PUT /roles/{role_hash}` with
`role_display_name`.

## Retire a role

**Goal:** stop using a role without leaving users on a dead reference.

1. Reassign or clear every holder (`PUT` or `DELETE /roles/users/{user_hash}/role`). After the role is
   deleted, holders keep it in `users.role_id`: it grants nothing at auth time, but the inspection
   endpoints still count its permissions.
2. Optionally remove it from project catalogs
   (`DELETE /roles/projects/{project_hash}/catalog/roles/{role_hash}`). Catalog listings hide deleted
   roles anyway, but the catalog rows stay active and cannot be removed once the role is deleted.
3. Delete it:

   ```bash
   curl -X DELETE "http://localhost:8000/roles/$ROLE_HASH" -H "Authorization: Bearer $TOKEN"
   ```

System roles (`is_system_role = 1`) cannot be deleted (`403` `AUTHZ_2009`).

## Audit what a role grants

```bash
curl "http://localhost:8000/roles/$ROLE_HASH" -H "Authorization: Bearer $TOKEN"
# for each group in permission_groups:
curl "http://localhost:8000/roles/permission-groups/$GROUP_HASH/permissions" -H "Authorization: Bearer $TOKEN"
```

Both reads show only active groups and permissions, which is exactly what the role grants: a
soft-deleted group that is still linked grants nothing and does not appear here either. See
[Soft-delete effects](../permissions/resolution.md#soft-delete-effects).

## Suggest roles for a project

```bash
curl -X POST "http://localhost:8000/roles/projects/$PROJECT_HASH/catalog/roles/$ROLE_HASH" \
  -H "Authorization: Bearer $TOKEN" --data-urlencode "catalog_purpose=Default for editors"
curl "http://localhost:8000/roles/projects/$PROJECT_HASH/catalog/roles" -H "Authorization: Bearer $USER_TOKEN"
```

The catalog is for UIs. It does not limit which roles can be assigned to the project's users, and
removing an entry changes no assignment.
