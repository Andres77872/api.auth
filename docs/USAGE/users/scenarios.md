# Users Scenarios and Examples

Concrete, repo-specific examples for operating the users system in this repository.

---

## Scenario 1: User Self-Service Profile Review

Goal: confirm personal profile data and current access.

```bash
# 1. Inspect current profile
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $TOKEN"

# 2. Inspect access summary
curl -X GET "http://localhost:8000/users/access-summary" \
  -H "Authorization: Bearer $TOKEN"

# 3. Update own email
curl -X PUT "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=new@example.com"
```

Use this flow before escalating an access complaint. Many issues are visible already in `access-summary`.

---

## Scenario 2: Self-Register a New Consumer User

Goal: onboard a user into an existing user group that already has project reach.

```bash
# 1. Check username/email availability
curl -X POST "http://localhost:8000/auth/check-availability" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_employee&email=new@company.com"

# 2. Register into a known user group
curl -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=new_employee&password=SecurePassword123!&email=new@company.com&user_group_hash=$USER_GROUP_HASH"
```

Important prerequisite:

- the referenced user group must already be linked to at least one project, otherwise registration is rejected

---

## Scenario 3: Root Creates a Multi-Project Admin

Goal: create a real admin operator who can manage more than one project.

```bash
# 1. Create the admin user with two project assignments
curl -X POST "http://localhost:8000/user-types/admin" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=ops_admin&password=SecurePassword123!&email=ops@example.com&assigned_project_ids=1&assigned_project_ids=2"

# 2. Verify the resulting assignment set
curl -X GET "http://localhost:8000/user-types/admin/$ADMIN_HASH/projects" \
  -H "Authorization: Bearer $ROOT_TOKEN"

# 3. Inspect type metadata
curl -X GET "http://localhost:8000/user-types/$ADMIN_HASH/info" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

Why this path matters:

- it creates the admin and wires admin-group membership in one workflow

---

## Scenario 4: Admin Reviews a User in Their Own Scope

Goal: inspect a user before changing status or details.

```bash
# 1. Narrow candidates with list
curl -X GET "http://localhost:8000/users/list?project_filter=$PROJECT_HASH&search=jane" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2. Get the detailed record
curl -X GET "http://localhost:8000/users/$USER_HASH?include_group_hierarchy=true&include_permission_details=true" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 3. Update email if needed
curl -X PUT "http://localhost:8000/users/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "email=jane.updated@example.com"
```

If step 2 returns "User not in your projects", the admin lacks overlapping project reach with that user.

---

## Scenario 5: Offboard a Departing User Safely

Goal: remove live access immediately, then decide whether soft delete is needed.

```bash
# 1. Inspect current access first
curl -X GET "http://localhost:8000/users/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 2. Deactivate immediately
curl -X PUT "http://localhost:8000/users/$USER_HASH/status?is_active=false" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 3. Optionally soft-delete later
curl -X DELETE "http://localhost:8000/users/$USER_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Operational reasoning:

- deactivation is the fastest lockout path because it invalidates sessions and user cache
- delete is still soft-delete, but it also deactivates group memberships

---

## Scenario 6: Promote a Consumer to Admin Without Creating a Broken Admin

Goal: avoid creating an admin who has the type flag but no assigned project.

```bash
# Preferred path: stricter user-types route
curl -X PUT "http://localhost:8000/user-types/$USER_HASH/type" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_type=admin&assigned_project_id=3"

# Then add more projects if needed
curl -X POST "http://localhost:8000/user-types/admin/$USER_HASH/projects/add" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_id=5"
```

Avoid this unless you know why:

```bash
curl -X PATCH "http://localhost:8000/users/$USER_HASH/type" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_type=admin"
```

That second path changes the enum but does not require initial project assignment.

---

## Scenario 7: Reset a Password During Support Handling

Goal: request a secure reset link for a non-root user without exposing password or token material to support staff.

```bash
curl -X POST "http://localhost:8000/users/$USER_HASH/reset-password" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Remember:

- the API response returns accepted reset-link metadata only
- no temporary password, reset token, reset URL, full email, or provider payload is returned
- the user must consume `/auth/password/reset` and then login again; the link does not create a session

---

## Related Documentation

- **[Users Overview](README.md)**
- **[Usage](usage.md)**
- **[Email Management](email-management.md)**
- **[User Types](user-types.md)**
- **[Bulk Operations](bulk-operations.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Document Version**: 1.0
