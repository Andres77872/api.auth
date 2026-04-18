# Permissions Scenarios

Concrete, repo-specific scenarios for operating the permissions system in `api.auth`.

---

## Scenario 1: Set Up a New Team Permission Baseline

**Goal**: create a reusable QA permission group, attach it to a QA user group, and verify the result.

```bash
# 1) Create the permission group
curl -X POST "http://localhost:8000/roles/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=qa_testing&group_display_name=QA Testing&group_description=QA team baseline&group_category=testing"

# 2) Add permissions to that group
curl -X POST "http://localhost:8000/roles/permission-groups/$QA_PG_HASH/permissions/$READ_PERMISSION_HASH" \
  -H "Authorization: Bearer $TOKEN"

curl -X POST "http://localhost:8000/roles/permission-groups/$QA_PG_HASH/permissions/$WRITE_PERMISSION_HASH" \
  -H "Authorization: Bearer $TOKEN"

# 3) Attach the permission group to the QA user group
curl -X POST "http://localhost:8000/permissions/admin/user-groups/$QA_GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=$QA_PG_HASH"

# 4) Verify which permission groups are attached to the team
curl -X GET "http://localhost:8000/permissions/admin/user-groups/$QA_GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"
```

**Why this pattern is preferred**:

- one assignment covers the whole team
- onboarding/offboarding happens through user-group membership
- the permission model stays consistent across the team

---

## Scenario 2: Grant Temporary Exception Access to One User

**Goal**: give one operator extra reporting capability without changing the whole team.

```bash
# 1) Assign a direct permission group with notes
curl -X POST "http://localhost:8000/permissions/users/$USER_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=$REPORTING_PG_HASH&notes=Temporary Q2 reporting access"

# 2) Verify direct assignments for that user
curl -X GET "http://localhost:8000/permissions/users/$USER_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN"

# 3) Ask the user to verify effective permissions from their own session
curl -X GET "http://localhost:8000/permissions/users/me/permission-sources" \
  -H "Authorization: Bearer $USER_TOKEN"

# 4) Remove the exception when the work is done
curl -X DELETE "http://localhost:8000/permissions/users/$USER_HASH/permission-groups/$REPORTING_PG_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Use this for exceptions. If you do this for half the company, your permission model is already broken.

---

## Scenario 3: Standardize Access with a Global Role

**Goal**: create a standard `content_editor` role and assign it to multiple users.

```bash
# 1) Create the role
curl -X POST "http://localhost:8000/roles/roles" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_name=content_editor&role_display_name=Content Editor&role_description=Editorial baseline&role_priority=40"

# 2) Link required permission groups to the role
curl -X POST "http://localhost:8000/roles/roles/$ROLE_HASH/permission-groups/$EDITORIAL_PG_HASH" \
  -H "Authorization: Bearer $TOKEN"

curl -X POST "http://localhost:8000/roles/roles/$ROLE_HASH/permission-groups/$PUBLISHING_PG_HASH" \
  -H "Authorization: Bearer $TOKEN"

# 3) Assign the role to a user
curl -X PUT "http://localhost:8000/roles/users/$USER_HASH/role" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "role_hash=$ROLE_HASH"

# 4) Verify the user's role
curl -X GET "http://localhost:8000/roles/users/$USER_HASH/role" \
  -H "Authorization: Bearer $TOKEN"
```

This is the clean baseline path for job-function defaults. Then layer team or direct assignments only where justified.

---

## Scenario 4: Audit Why a User Has a Permission

**Goal**: determine whether a permission comes from the user's role, user group, or a direct assignment.

```bash
# 1) Check the effective permission directly
curl -X GET "http://localhost:8000/permissions/users/me/permissions/check/manage_roles" \
  -H "Authorization: Bearer $USER_TOKEN"

# 2) Pull the full effective permission list
curl -X GET "http://localhost:8000/permissions/users/me/permissions" \
  -H "Authorization: Bearer $USER_TOKEN"

# 3) Pull the source breakdown
curl -X GET "http://localhost:8000/permissions/users/me/permission-sources" \
  -H "Authorization: Bearer $USER_TOKEN"
```

If the user has the permission in step 1 but cannot access a route guarded elsewhere, compare that route against the guard matrix in [architecture.md](architecture.md#admin-guard-matrix).

---

## Scenario 5: Organize Recommended Permission Sets Per Project Without Changing Auth

**Goal**: attach metadata so operators or UIs know which permission groups and roles are commonly used with a project.

```bash
# 1) Add a permission group to the project's metadata catalog
curl -X POST "http://localhost:8000/permissions/projects/$PROJECT_HASH/permission-group-catalog/$PG_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "catalog_purpose=Recommended for editorial teams&notes=Metadata only"

# 2) Add a role to the project's role catalog
curl -X POST "http://localhost:8000/roles/projects/$PROJECT_HASH/catalog/roles/$ROLE_HASH" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "catalog_purpose=Typical editor baseline&notes=Suggestion only"

# 3) Read the project's catalog views
curl -X GET "http://localhost:8000/permissions/projects/$PROJECT_HASH/permission-group-catalog" \
  -H "Authorization: Bearer $TOKEN"

curl -X GET "http://localhost:8000/roles/projects/$PROJECT_HASH/catalog/roles" \
  -H "Authorization: Bearer $TOKEN"
```

This helps operations, but it does NOT grant access. If you skip the real assignment routes, nothing changes for the user.

---

## Scenario 6: User Still Gets 403 After a Permission Change

**Goal**: prove whether the issue is missing assignment, wrong guard path, or stale session context.

```bash
# 1) Check the user's effective permissions
curl -X GET "http://localhost:8000/permissions/users/me/permissions" \
  -H "Authorization: Bearer $USER_TOKEN"

# 2) Check the user's permission sources
curl -X GET "http://localhost:8000/permissions/users/me/permission-sources" \
  -H "Authorization: Bearer $USER_TOKEN"

# 3) Refresh the user's session
curl -X POST "http://localhost:8000/auth/refresh" \
  -H "Authorization: Bearer $USER_TOKEN"

# 4) If the route is project-sensitive, switch project context explicitly
curl -X POST "http://localhost:8000/auth/switch-project" \
  -H "Authorization: Bearer $USER_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$PROJECT_HASH"
```

If the self-query endpoints say the permission exists, but the target route still denies access, the most likely next step is to check whether that route uses:

- role-only permission guard
- session permission snapshot
- project access check

---

## Related Documentation

- **[Permissions Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
