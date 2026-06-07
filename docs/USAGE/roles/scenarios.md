# Roles Scenarios

Concrete admin and user workflows for the global roles system in `api.auth`.

---

## Admin Scenarios

### Scenario 1: Create a New Role from Scratch

You need a new "Content Editor" role with read and write data permissions.

```bash
# Step 1: Create the permissions
curl -X POST "http://localhost:8000/roles/permissions" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_name=read_data&permission_display_name=Read Data&permission_description=Read project data&permission_category=data"

curl -X POST "http://localhost:8000/roles/permissions" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_name=write_data&permission_display_name=Write Data&permission_description=Write project data&permission_category=data"

# Step 2: Create a permission group
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=content_editors&group_display_name=Content Editors&group_category=general"

# Step 3: Add permissions to the group (use the hashes from steps 1 and 2)
curl -X POST "http://localhost:8000/roles/permission-groups/PG_CONTENT_EDITORS/permissions/PERM_READ_DATA" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X POST "http://localhost:8000/roles/permission-groups/PG_CONTENT_EDITORS/permissions/PERM_WRITE_DATA" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Step 4: Create the role
curl -X POST "http://localhost:8000/roles/roles" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_name=content_editor&role_display_name=Content Editor&role_priority=60"

# Step 5: Attach the permission group to the role
curl -X POST "http://localhost:8000/roles/roles/ROLE_CONTENT_EDITOR/permission-groups/PG_CONTENT_EDITORS" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

This is the standard 4-step build process: **permission → group → add to group → attach group to role**.

---

### Scenario 2: Assign a Role to a User

```bash
# Check the user's current role (may be null)
curl -X GET "http://localhost:8000/roles/users/usr-abc123/role" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Assign the new role
curl -X PUT "http://localhost:8000/roles/users/usr-abc123/role" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_hash=ROLE_CONTENT_EDITOR"

# Verify the assignment
curl -X GET "http://localhost:8000/roles/users/usr-abc123/role" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Note:** the user must be active. If they are inactive, you get 403 `ACCOUNT_INACTIVE`.

---

### Scenario 3: Change a User's Role

```bash
# Assign a different role (replaces the existing one)
curl -X PUT "http://localhost:8000/roles/users/usr-abc123/role" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_hash=ROLE_VIEWER"
```

The user's session still contains permissions from their previous role until they re-login or refresh.

The API takes the public `role_hash` form value, resolves it to the internal numeric role id, and stores that id in `users.role_id`.

---

### Scenario 4: Remove a User's Role

```bash
# Remove the role entirely
curl -X DELETE "http://localhost:8000/roles/users/usr-abc123/role" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Verify — should return null role
curl -X GET "http://localhost:8000/roles/users/usr-abc123/role" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

---

### Scenario 5: Audit What Permissions a Role Grants

```bash
# Get the role with its permission groups
curl -X GET "http://localhost:8000/roles/roles/ROLE_CONTENT_EDITOR" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# For each permission group in the response, get its permissions
curl -X GET "http://localhost:8000/roles/permission-groups/PG_CONTENT_EDITORS" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

This is a two-step lookup: role → permission groups → permissions.

---

### Scenario 6: Soft-Delete a Role

```bash
# Attempt to delete a system role (will fail)
curl -X DELETE "http://localhost:8000/roles/roles/ROLE_ADMIN" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# → currently 500 INTERNAL_ERROR because ErrorCode.OPERATION_NOT_ALLOWED is missing
#   (the intended behavior is a clean 403 block)

# Delete a user-created role (succeeds)
curl -X DELETE "http://localhost:8000/roles/roles/ROLE_CONTENT_EDITOR" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# The role disappears from list queries
curl -X GET "http://localhost:8000/roles/roles" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# But users who had this role still reference it (orphaned FK)
# Their role query returns null because the SP checks is_active
curl -X GET "http://localhost:8000/roles/users/usr-abc123/role" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
# → role: null
```

---

### Scenario 7: Catalog Roles for a Project

```bash
# Add a role to the project's catalog (metadata only)
curl -X POST "http://localhost:8000/roles/projects/proj-api-v2/catalog/roles/ROLE_CONTENT_EDITOR" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "catalog_purpose=Recommended editor role&notes=Metadata only"

# List all cataloged roles for the project
curl -X GET "http://localhost:8000/roles/projects/proj-api-v2/catalog/roles" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# Remove from catalog
curl -X DELETE "http://localhost:8000/roles/projects/proj-api-v2/catalog/roles/ROLE_CONTENT_EDITOR" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

**Reminder:** this is metadata only. It does not restrict which roles can be assigned to users of this project.

---

## User Scenarios

### Scenario 8: Check My Role

```bash
curl -X GET "http://localhost:8000/roles/users/me/role" \
  -H "Authorization: Bearer $USER_TOKEN"
```

Returns `null` if no role is assigned or if the assigned role is soft-deleted.

---

### Scenario 9: Check My Effective Permissions

```bash
# Get all permissions from all three sources
curl -X GET "http://localhost:8000/permissions/users/me/permissions" \
  -H "Authorization: Bearer $USER_TOKEN"

# Check a specific permission
curl -X GET "http://localhost:8000/permissions/users/me/permissions/check/read_data" \
  -H "Authorization: Bearer $USER_TOKEN"

# See where my permissions come from
curl -X GET "http://localhost:8000/permissions/users/me/permission-sources" \
  -H "Authorization: Bearer $USER_TOKEN"
```

**Important:** these endpoints use the **comprehensive** resolution (role + user-group + direct). The auth/session flow only uses the role path. See [../permissions/resolution.md](../permissions/resolution.md).

---

### Scenario 10: Role Changed but Permissions Don't Seem Updated

```bash
# The access context may still have old permissions. Refresh with the refresh token:
curl -X POST "http://localhost:8000/auth/refresh" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "refresh_token=$REFRESH_TOKEN"

# Or re-login entirely:
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -H "User-Agent: my-client/1.0" \
  -d "username=myuser&password=mypass&project_hash=$PROJECT_HASH"
```

---

## Related Documentation

- **[Roles Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**
- **[Permission Resolution](../permissions/resolution.md)** — Auth vs inspection gap

---

**Last Updated**: April 2026  
**Document Version**: 1.0
