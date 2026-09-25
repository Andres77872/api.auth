# Groups scenarios

End-to-end workflows. Each step's fields and responses are in [reference.md](reference.md); the
individual requests are explained in [usage.md](usage.md). `$TOKEN` belongs to a root user or to a
session that carries `admin` (both prefixes), or `manage_users` plus `manage_roles`.

## Onboard a team

Goal: a new team can sign in to a set of projects.

```bash
# 1. Create the team
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "group_name=qa_team" \
  --data-urlencode "description=Quality assurance"
# -> user_group.group_hash = $QA_TEAM

# 2. Create the project container
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "group_name=qa_projects"
# -> project_group.group_hash = $QA_PROJECTS

# 3. Put the projects in it (repeat per project)
curl -X POST "http://localhost:8000/admin/project-groups/$QA_PROJECTS/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$TEST_PROJECT"

# 4. Grant the team the container
curl -X POST "http://localhost:8000/admin/user-groups/$QA_TEAM/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_group_hash=$QA_PROJECTS"

# 5. Add the people
curl -X POST "http://localhost:8000/admin/user-groups/$QA_TEAM/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_hashes": ["'"$QA_1"'", "'"$QA_2"'", "'"$QA_3"'"]}'

# 6. Verify
curl "http://localhost:8000/admin/user-groups/$QA_TEAM" \
  -H "Authorization: Bearer $TOKEN"
```

Outcome: `accessible_projects` in step 6 lists every active, non-archived project in
`qa_projects`, and each consumer member can log in with any of those `project_hash` values. Steps
3 to 5 can run in any order; access exists once all three links are in place. Admin users log in
only to projects they are assigned to administer, so group membership alone does not let them in.

What users may do inside a project comes from their global role, not from this wiring. See the
[permissions suite](../permissions/README.md).

## Give temporary contractor access

Goal: time-boxed access that is removed in one call.

```bash
# 1. A dedicated, clearly named group
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer $TOKEN" \
  --data-urlencode "group_name=contractors_2026_q4" \
  --data-urlencode "description=Contractors through December 2026"

# 2. Grant only the limited project group
curl -X POST "http://localhost:8000/admin/user-groups/$CONTRACTORS/project-groups" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_group_hash=$LIMITED_PROJECTS"

# 3. Add the contractors
curl -X POST "http://localhost:8000/admin/user-groups/$CONTRACTORS/members/bulk" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"user_hashes": ["'"$CONTRACTOR_1"'", "'"$CONTRACTOR_2"'"]}'

# 4. At the end of the engagement, revoke the grant
curl -X DELETE "http://localhost:8000/admin/user-groups/$CONTRACTORS/project-groups/$LIMITED_PROJECTS" \
  -H "Authorization: Bearer $TOKEN"
```

Step 4 revokes the contractors' sessions and refresh-token families for the lost projects at once
(reason `user_group_project_group_access_revoked`); they do not keep access until token expiry.
A contractor who also belongs to another group that reaches the same project keeps that session.

API keys the contractors own may keep validating for up to `60` seconds, the API-key validation
cache lifetime. To cut them off immediately, revoke the keys as well
([API keys usage](../api-keys/usage.md)).

## One team across several project domains

Goal: one user group reaches the projects of several project groups.

```bash
for PG in "$AUTH_SERVICES" "$DATA_SERVICES" "$ADMIN_PORTALS"; do
  curl -X POST "http://localhost:8000/admin/user-groups/$PLATFORM_TEAM/project-groups" \
    -H "Authorization: Bearer $TOKEN" \
    -d "project_group_hash=$PG"
done

curl "http://localhost:8000/admin/user-groups/$PLATFORM_TEAM/project-groups" \
  -H "Authorization: Bearer $TOKEN"
```

Outcome: members reach the union of the three groups' projects. Removing one domain later is a
single revoke; the other grants are unaffected.

## Use a project's default groups

Goal: add users to a project without building new groups.

Every project is created with `user_<project_id>`, `readonly_<project_id>` and
`admin_<project_id>` user groups already granted its `default_<project_id>` project group
([Projects](../projects/README.md#key-concepts)). They start empty.

```bash
# 1. Find the default group hashes (root, or an admin assigned to the project)
curl "http://localhost:8000/projects/$PROJECT_HASH/groups" \
  -H "Authorization: Bearer $TOKEN"

# 2. Add a consumer to user_<project_id>
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP_OF_PROJECT/members" \
  -H "Authorization: Bearer $TOKEN" \
  -d "user_hash=$USER_HASH"
```

The `admin_<project_id>` group is root-only through these routes. Assign admin users with
`PUT /user-types/admin/{user_hash}/projects` instead ([user types](../users/user-types.md)).
`user_` and `readonly_` grant the same project reach; the names carry no permission difference.

## Deprovision a team

Goal: retire a team without leaving access behind.

```bash
# 1. Review what the team reaches and who is in it
curl "http://localhost:8000/admin/user-groups/$TEAM" \
  -H "Authorization: Bearer $TOKEN"

# 2. Optional staged rollback: revoke grants one at a time
curl -X DELETE "http://localhost:8000/admin/user-groups/$TEAM/project-groups/$PROJECT_GROUP" \
  -H "Authorization: Bearer $TOKEN"

# 3. Retire the group
curl -X DELETE "http://localhost:8000/admin/user-groups/$TEAM" \
  -H "Authorization: Bearer $TOKEN"
```

Step 3 deactivates every membership and grant of the group and revokes the members' sessions for
projects they no longer reach (reason `user_group_deleted`). A deleted group cannot be restored
through the API and its name stays reserved, so a later team needs a new name.
