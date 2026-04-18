# Permissions Usage

Day-to-day operational guide for the permissions system used in `api.auth`.

---

## Before You Start

Use this decision rule:

- **Role assignment** → standard baseline for a job function
- **User-group permission-group assignment** → preferred team-scale capability model
- **Direct user permission-group assignment** → exceptions, temporary access, or overrides

If you need project reach, that is a **groups/projects problem**, not a permissions problem. Permissions control **what a user can do**, not **which projects they can enter**.

---

## Permission Groups

Permission groups are reusable bundles of individual permissions.

### Create a permission group

```bash
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=content_management&group_display_name=Content Management&group_description=Create and edit content&group_category=content"
```

### List permission groups

```bash
curl -X GET "http://localhost:8000/roles/permission-groups?category=content&limit=50&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

### Inspect one permission group and its permissions

```bash
curl -X GET "http://localhost:8000/roles/permission-groups/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### Update a permission group

```bash
curl -X PUT "http://localhost:8000/roles/permission-groups/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_display_name=Content Management Pro&group_description=Editorial and publishing operations&group_category=content"
```

### Delete a permission group

```bash
curl -X DELETE "http://localhost:8000/roles/permission-groups/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### Add a permission to a permission group

```bash
curl -X POST "http://localhost:8000/roles/permission-groups/$PG_HASH/permissions/$PERMISSION_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### List permissions inside a permission group

```bash
curl -X GET "http://localhost:8000/roles/permission-groups/$PG_HASH/permissions" \
  -H "Authorization: Bearer $TOKEN"
```

### Remove a permission from a permission group

```bash
curl -X DELETE "http://localhost:8000/roles/permission-groups/$PG_HASH/permissions/$PERMISSION_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Permissions

Individual permissions are the atomic capability names checked by the RBAC layer.

### Create a permission

```bash
curl -X POST "http://localhost:8000/roles/permissions" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_name=publish_content&permission_display_name=Publish Content&permission_description=Allows publishing workflow&permission_category=content"
```

### List permissions

```bash
curl -X GET "http://localhost:8000/roles/permissions?category=content&limit=50&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

### Inspect one permission

```bash
curl -X GET "http://localhost:8000/roles/permissions/$PERMISSION_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### Update a permission

```bash
curl -X PUT "http://localhost:8000/roles/permissions/$PERMISSION_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_display_name=Publish Content Pro&permission_description=Allows publish and release operations&permission_category=content"
```

### Delete a permission

```bash
curl -X DELETE "http://localhost:8000/roles/permissions/$PERMISSION_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Roles

Roles are the global baseline path. Each user has one role at most.

### Create a role

```bash
curl -X POST "http://localhost:8000/roles/roles" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_name=content_editor&role_display_name=Content Editor&role_description=Default editorial role&role_priority=40"
```

### List roles

```bash
curl -X GET "http://localhost:8000/roles/roles?limit=50&offset=0" \
  -H "Authorization: Bearer $TOKEN"
```

### Inspect one role

```bash
curl -X GET "http://localhost:8000/roles/roles/$ROLE_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### Update a role

```bash
curl -X PUT "http://localhost:8000/roles/roles/$ROLE_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_display_name=Senior Content Editor&role_description=Editorial baseline with review duties&role_priority=60"
```

### Delete a role

```bash
curl -X DELETE "http://localhost:8000/roles/roles/$ROLE_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### Attach a permission group to a role

```bash
curl -X POST "http://localhost:8000/roles/roles/$ROLE_HASH/permission-groups/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### List a role's permission groups

```bash
curl -X GET "http://localhost:8000/roles/roles/$ROLE_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

### Remove a permission group from a role

```bash
curl -X DELETE "http://localhost:8000/roles/roles/$ROLE_HASH/permission-groups/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### Assign a role to a user

```bash
curl -X PUT "http://localhost:8000/roles/users/$USER_HASH/role" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_hash=$ROLE_HASH"
```

### Inspect a user's role

```bash
curl -X GET "http://localhost:8000/roles/users/$USER_HASH/role" \
  -H "Authorization: Bearer $TOKEN"
```

### Remove a user's role

```bash
curl -X DELETE "http://localhost:8000/roles/users/$USER_HASH/role" \
  -H "Authorization: Bearer $TOKEN"
```

---

## User-Group Permission Assignments

This is the preferred organizational model.

### Assign a permission group to a user group

```bash
curl -X POST "http://localhost:8000/permissions/admin/user-groups/$GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=$PG_HASH"
```

### Bulk-assign multiple permission groups to a user group

```bash
curl -X POST "http://localhost:8000/permissions/admin/user-groups/$GROUP_HASH/permission-groups/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hashes=$PG_A" \
  -d "permission_group_hashes=$PG_B" \
  -d "permission_group_hashes=$PG_C"
```

Read the response body carefully. This endpoint reports partial success per permission group.

### List permission groups attached to a user group

```bash
curl -X GET "http://localhost:8000/permissions/admin/user-groups/$GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

### Remove a permission group from a user group

```bash
curl -X DELETE "http://localhost:8000/permissions/admin/user-groups/$GROUP_HASH/permission-groups/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Direct User Permission Assignments

Use this path for exceptions, temporary access, or one-off overrides.

### Assign a permission group directly to a user

```bash
curl -X POST "http://localhost:8000/permissions/users/$USER_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=$PG_HASH&notes=Temporary migration access"
```

### List direct permission groups for a user

```bash
curl -X GET "http://localhost:8000/permissions/users/$USER_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

### Remove a direct permission-group assignment

```bash
curl -X DELETE "http://localhost:8000/permissions/users/$USER_HASH/permission-groups/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Current-User Queries

These endpoints are the safest operator-facing way to verify what the API currently resolves for a user.

### Get my role

```bash
curl -X GET "http://localhost:8000/roles/users/me/role" \
  -H "Authorization: Bearer $TOKEN"
```

### Get my effective permissions from all sources

```bash
curl -X GET "http://localhost:8000/permissions/users/me/permissions" \
  -H "Authorization: Bearer $TOKEN"
```

### Check one permission name

```bash
curl -X GET "http://localhost:8000/permissions/users/me/permissions/check/manage_roles" \
  -H "Authorization: Bearer $TOKEN"
```

### List my direct permission groups only

```bash
curl -X GET "http://localhost:8000/permissions/users/me/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

### Break down my permission sources

```bash
curl -X GET "http://localhost:8000/permissions/users/me/permission-sources" \
  -H "Authorization: Bearer $TOKEN"
```

Important caveat: `permission-groups` for `me` returns **direct assignments only**, not the role and user-group paths. Use `permissions` or `permission-sources` if you need the full picture.

---

## Catalog Operations (Metadata Only)

These routes help operators organize recommended permission groups and roles per project. They do **not** change authorization behavior.

### Add a permission group to a project's catalog

```bash
curl -X POST "http://localhost:8000/permissions/projects/$PROJECT_HASH/permission-group-catalog/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "catalog_purpose=Standard editorial permissions&notes=UI suggestion only"
```

### List permission groups cataloged for a project

```bash
curl -X GET "http://localhost:8000/permissions/projects/$PROJECT_HASH/permission-group-catalog" \
  -H "Authorization: Bearer $TOKEN"
```

### Remove a permission group from a project's catalog

```bash
curl -X DELETE "http://localhost:8000/permissions/projects/$PROJECT_HASH/permission-group-catalog/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

### See which projects catalog a permission group

```bash
curl -X GET "http://localhost:8000/permissions/permissions/groups/$PG_HASH/project-catalog" \
  -H "Authorization: Bearer $TOKEN"
```

Yes, the route really is `/permissions/permissions/groups/...` because the router prefix is `/permissions` and the route path also begins with `/permissions/groups/...`.

### Add a role to a project's role catalog

```bash
curl -X POST "http://localhost:8000/roles/projects/$PROJECT_HASH/catalog/roles/$ROLE_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "catalog_purpose=Standard engineering role&notes=Recommendation only"
```

### List cataloged roles for a project

```bash
curl -X GET "http://localhost:8000/roles/projects/$PROJECT_HASH/catalog/roles" \
  -H "Authorization: Bearer $TOKEN"
```

### Remove a role from the project catalog

```bash
curl -X DELETE "http://localhost:8000/roles/projects/$PROJECT_HASH/catalog/roles/$ROLE_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

---

## Permission-Group Usage Queries

Use these when you need to audit where a permission group is in use.

### Which user groups have this permission group?

```bash
curl -X GET "http://localhost:8000/permissions/permissions/groups/$PG_HASH/user-groups" \
  -H "Authorization: Bearer $TOKEN"
```

### Which users have this permission group directly?

```bash
curl -X GET "http://localhost:8000/permissions/permissions/groups/$PG_HASH/users" \
  -H "Authorization: Bearer $TOKEN"
```

The second route reports **direct assignments only**. It does not enumerate users who inherit that same permission group through roles or user groups.

---

## Related Documentation

- **[Permissions Overview](README.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
