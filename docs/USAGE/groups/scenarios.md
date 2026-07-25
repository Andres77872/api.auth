# Groups Scenarios and Examples

Concrete examples for operating the groups system in this repository.

---

## Scenario 1: Onboard a New Team

Goal: create a team, grant it project access, and give it reusable permissions.

```bash
# 1. Create the team bucket
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=qa_team&description=Quality assurance team"

# 2. Create the project container
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=qa_projects&description=QA and test environments"

# 3. Add projects to the container
curl -X POST "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$TEST_PROJECT_HASH"

# 4. Grant team access to that project container
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$PROJECT_GROUP_HASH"

# 5. Assign reusable permissions to the team
curl -X POST "http://localhost:8000/permissions/admin/user-groups/$USER_GROUP_HASH/permission-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=$PERMISSION_GROUP_HASH"

# 6. Add people
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_hashes": ["usr-qa1", "usr-qa2", "usr-qa3"]}'
```

Outcome:
- users inherit access to all projects in the QA project group
- users inherit team-level permissions through the permission group

---

## Scenario 2: Give Temporary Contractor Access

Goal: isolate temporary access so cleanup is easy.

```bash
# 1. Create a clearly time-bounded user group
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=contractors_q2_2026&description=Contractors through June 2026"

# 2. Grant only the limited project group they need
curl -X POST "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$LIMITED_PROJECT_GROUP_HASH"

# 3. Add the contractors
curl -X POST "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_hashes": ["usr-contractor1", "usr-contractor2"]}'

# 4. Revoke access at the end of the engagement
curl -X DELETE "http://localhost:8000/admin/user-groups/$CONTRACTOR_GROUP_HASH/project-groups/$LIMITED_PROJECT_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Why this pattern works:
- cleanup happens in one place
- naming communicates expiration intent
- contractors never need to share a permanent internal group
- the revoke in step 4 also terminates the contractors' live sessions for those projects (`reason="user_group_project_group_access_revoked"`), so they are logged out immediately rather than retaining access until their tokens expire

---

## Scenario 3: Platform Team With Access to Multiple Domains

Goal: one team, multiple project containers.

```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=platform_team&description=Platform engineering"

curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$AUTH_SERVICES_GROUP"

curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$DATA_SERVICES_GROUP"

curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$ADMIN_PORTALS_GROUP"
```

Outcome: all members of one user group inherit access to all projects across all three containers.

---

## Scenario 4: Understand Project Creation Defaults

Goal: avoid recreating access scaffolding manually when the system already does part of it.

When a new project is created, `create_default_groups()` automatically creates:

- one default project group for that project
- three default user groups tied to the project id:
  - `admin_{project_id}`
  - `user_{project_id}`
  - `readonly_{project_id}`
- links between those user groups and the default project group

Use this when:
- you want a quick project bootstrap
- your operational model maps well to the default admin/user/readonly split

Do **not** immediately duplicate those groups unless you have a reason. First verify whether the generated defaults already match the use case.

---

## Scenario 5: Deprovision a Team Safely

Goal: remove access without accidentally leaving stale memberships behind.

Recommended order:

1. List members and project-group links
2. Confirm the team is no longer needed
3. Revoke project-group links if you want a staged rollback
4. Soft-delete the user group only when the team should be fully retired

Useful commands:

```bash
curl -X GET "http://localhost:8000/admin/user-groups/$GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"

curl -X GET "http://localhost:8000/admin/user-groups/$GROUP_HASH/project-groups" \
  -H "Authorization: Bearer $TOKEN"

curl -X DELETE "http://localhost:8000/admin/user-groups/$GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

Remember: delete is a soft-delete, but it still deactivates memberships and user-group-to-project-group links — and it actively revokes affected members' live project sessions (`reason="user_group_deleted"`), so they will be logged out and must re-authenticate.

---

## Related Documentation

- **[Groups Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Document Version**: 3.1
