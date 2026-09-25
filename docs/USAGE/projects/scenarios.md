# Projects scenarios

End-to-end workflows around a project. Endpoint details are in [reference.md](reference.md);
group operations are explained in the [groups suite](../groups/usage.md).

## Set up a new project

Goal: a new project with an administrator and its first users.

```bash
# 1. Create the project (root)
curl -X POST "http://localhost:8000/projects" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  --data-urlencode "project_name=Customer API v2"
# -> project.project_hash = $PROJECT_HASH

# 2. Read the default groups. Their names carry the internal project ID:
#    admin_proj-<uuid>, user_proj-<uuid>, readonly_proj-<uuid>
curl "http://localhost:8000/projects/$PROJECT_HASH/groups" \
  -H "Authorization: Bearer $ROOT_TOKEN"
# -> $PROJECT_ID = proj-<uuid>; $USER_GROUP = group_hash of user_<project_id>

# 3. Make an existing admin user administrator of the project (root)
curl -X POST "http://localhost:8000/user-types/admin/$ADMIN_USER_HASH/projects/add" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -d "project_id=$PROJECT_ID"

# 4. Add consumers to the project's user group
curl -X POST "http://localhost:8000/admin/user-groups/$USER_GROUP/members" \
  -H "Authorization: Bearer $ROOT_TOKEN" \
  -d "user_hash=$CONSUMER_HASH"
```

Outcome: the admin user can log in to the project and administer it (update, members, groups,
delete); the consumer can log in with `project_hash=$PROJECT_HASH`. Step 3 adds the admin to
`admin_<project_id>`, which only root may change. Admin-user creation and the other assignment
routes are in [user types](../users/user-types.md).

## Let consumers register themselves into a project

Goal: consumers sign up without an administrator adding them one by one.

`POST /auth/register` is public and places the new consumer in the user group whose hash it
receives. Hand out the hash of a group that reaches the project, such as `user_<project_id>`:

```bash
curl -X POST "http://localhost:8000/auth/register" \
  --data-urlencode "username=emma.johnson" \
  --data-urlencode "email=emma.johnson@example.com" \
  --data-urlencode "password=$NEW_PASSWORD" \
  -d "user_group_hash=$USER_GROUP"
```

When the group reaches an active project, the response signs the user in to the first such project
by name and sets the session cookies. Later logins name the project explicitly:

```bash
curl -X POST "http://localhost:8000/auth/login" \
  --data-urlencode "username=emma.johnson" \
  --data-urlencode "password=$NEW_PASSWORD" \
  -d "project_hash=$PROJECT_HASH"
```

> [!CAUTION]
> Anyone holding the group hash can register into that group. Never share the hash of an
> `admin_` group or of a group that reaches projects the public should not see.

## Add a project to an existing team's reach

Goal: a team that already has a project group gets one more project.

```bash
curl -X POST "http://localhost:8000/admin/project-groups/$TEAM_PROJECT_GROUP/projects" \
  -H "Authorization: Bearer $TOKEN" \
  -d "project_hash=$PROJECT_HASH"

curl "http://localhost:8000/projects/$PROJECT_HASH/groups" \
  -H "Authorization: Bearer $TOKEN"
```

Every user group granted `$TEAM_PROJECT_GROUP` now reaches the project, which the second call
confirms. Building a team from scratch, contractor access and multi-domain teams are covered in
[groups scenarios](../groups/scenarios.md).

## Audit who can reach a project

Goal: explain every user who can access a project.

```bash
# 1. Every user with access (root users included)
curl "http://localhost:8000/projects/$PROJECT_HASH/members?limit=100" \
  -H "Authorization: Bearer $TOKEN"

# 2. The user groups that provide it
curl "http://localhost:8000/projects/$PROJECT_HASH/groups" \
  -H "Authorization: Bearer $TOKEN"

# 3. For a suspicious group, its members and all its grants
curl "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH" \
  -H "Authorization: Bearer $TOKEN"
```

To narrow access, revoke the group's grant if the whole team should lose the project, or remove
individual members otherwise ([groups usage](../groups/usage.md#revoke-a-grant)). Step 3 needs a
session with `admin` or `manage_users`; steps 1 and 2 need admin scope over the project.

## Reorganize teams without an outage

Goal: move a project's users from old groups to a new group.

1. Create the new user group and grant it the project groups the old groups had.
2. Add the members to the new group (bulk add).
3. Check `GET /projects/{project_hash}/members`: `pagination.total` should not have dropped.
4. Delete the old user groups.

Order matters: session revocation in step 4 keeps the sessions of users who still reach the project
through the new group, so nobody is logged out. Deleting first would revoke them.

## Retire a project

Goal: stop all use of a project.

```bash
curl -X DELETE "http://localhost:8000/projects/$PROJECT_HASH" \
  -H "Authorization: Bearer $ROOT_TOKEN"
```

After the delete the project returns `404`, no group reaches it, and access tokens scoped to it
fail on their next use. API keys for it stop validating once their cached validation result
expires (at most `60` seconds). Archiving would keep the record visible to root, but no API route
sets the archive flag (`PATCH /projects/{project_hash}/archive` returns `501`).

The default groups stay behind. Remove them if they have no further use: the project group and the
`user_` / `readonly_` groups through the groups routes, and `admin_<project_id>` as root.
