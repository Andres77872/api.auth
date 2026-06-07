# Projects Scenarios and Examples

Concrete examples for operating projects in this repository.

---

## Scenario 1: Setting Up a New Project

Goal: create a project and make it reachable by the right team.

```bash
# 1. Create the project
curl -X POST "http://localhost:8000/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_name=Customer API v2&project_description=Customer platform backend"

# 2. Inspect the generated groups before inventing new ones
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

# 3. If needed, add the project to a broader project group
curl -X POST "http://localhost:8000/admin/project-groups/$PLATFORM_GROUP_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$PROJECT_HASH"

# 4. Grant a team access through that project group
curl -X POST "http://localhost:8000/admin/user-groups/$BACKEND_TEAM_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$PLATFORM_GROUP_HASH"
```

Why this works:

- project creation already bootstraps default groups
- broader team access is layered through project groups, not direct project assignment

---

## Scenario 2: Adding a Team to an Existing Project

Goal: grant one existing team access to one existing project without touching every user individually.

```bash
# 1. Put the project in the right project group
curl -X POST "http://localhost:8000/admin/project-groups/$QA_PROJECTS_HASH/projects" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=$PROJECT_HASH"

# 2. Grant the team's user group access to that project group
curl -X POST "http://localhost:8000/admin/user-groups/$QA_TEAM_HASH/project-groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=$QA_PROJECTS_HASH"

# 3. Verify the result from the project side
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

This is the right abstraction when the same team should reach multiple projects over time.

---

## Scenario 3: Multi-Project Platform Team

This scenario is about group wiring (one user group linked to multiple project groups). The canonical documentation lives in the groups suite:

- **[Groups → Scenario 3: Platform Team With Access to Multiple Domains](../groups/scenarios.md#scenario-3-platform-team-with-access-to-multiple-domains)**

From the project side, the outcome is: every project contained in those project groups becomes accessible to all members of the linked user group.

---

## Scenario 4: Onboarding New Employees

Goal: add a new user to an existing project access model with minimal churn.

```bash
# 1. Register the user into the team group that already has project-group access
curl -X POST "http://localhost:8000/auth/register" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=emma.johnson&email=emma.johnson@company.com&password=TempPass123!&user_group_hash=$BACKEND_TEAM_HASH"

# 2. Have the user log in and verify accessible projects
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=emma.johnson&password=TempPass123!"
```

Why this pattern matters:

- onboarding stays team-centric
- project access is inherited from existing group wiring
- `/auth/register` requires `user_group_hash`; there is no `POST /admin/users` creation route or `user_type=consumer` create field
- no per-user project exceptions are needed

---

## Scenario 5: Managing Contractor Access

This scenario is about group wiring (isolated temporary user group with limited project-group access). The canonical documentation lives in the groups suite:

- **[Groups → Scenario 2: Give Temporary Contractor Access](../groups/scenarios.md#scenario-2-give-temporary-contractor-access)**

From the project side, the outcome is: contractors gain access only to projects within the linked project group, and revocation is a single group-link deletion.

---

## Scenario 6: Project Reorganization

Goal: move access from old team structure to new team structure without breaking project reach.

Recommended order:

1. create the new combined user group
2. add the new group's project-group links first
3. migrate members
4. verify `GET /projects/{hash}/members`
5. only then retire old user groups

Useful commands:

```bash
curl -X GET "http://localhost:8000/projects/$PROJECT_HASH/members?limit=100" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X GET "http://localhost:8000/projects/$PROJECT_HASH/groups" \
  -H "Authorization: Bearer $ADMIN_TOKEN"

curl -X DELETE "http://localhost:8000/admin/user-groups/$OLD_TEAM_HASH" \
  -H "Authorization: Bearer $ADMIN_TOKEN"
```

Do the verification before deleting old groups, otherwise you create your own outage like an animal.

---

## Related Documentation

- **[Projects Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
