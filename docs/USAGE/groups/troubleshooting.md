# Groups troubleshooting

Symptom, cause and fix. Error codes are explained in [errors.md](../errors.md); route contracts
are in [reference.md](reference.md).

## Access problems

### A user cannot reach a project

Cause: one link of the chain is missing or inactive, the project is archived, or the user is an
admin user (admins log in only to projects they are assigned to administer).

Fix: walk the chain from the user side.

1. Which groups is the user in?

   ```bash
   curl "http://localhost:8000/admin/user-groups/users/$USER_HASH/groups" \
     -H "Authorization: Bearer $TOKEN"
   ```

2. Which project groups does each group reach, and which projects are behind them?

   ```bash
   curl "http://localhost:8000/admin/user-groups/$USER_GROUP_HASH" \
     -H "Authorization: Bearer $TOKEN"
   ```

   `accessible_project_groups` lists the grants; `accessible_projects` lists the reachable
   projects. A project missing from `accessible_projects` while its project group is listed is
   either not in that project group or archived.

3. Is the project in the project group?

   ```bash
   curl "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH" \
     -H "Authorization: Bearer $TOKEN"
   ```

   `assigned_projects` omits archived projects. No endpoint shows the archive flag; check
   `projects.archived` in the database.

Login answers `403` `AUTHZ_2003` when the requested project is not reachable, and `403`
`AUTHZ_2001` when the consumer reaches no project at all.

### A user keeps access right after a revoke or delete

Cause: one of these:

- another user group still grants the same project. Revocation keeps sessions that another
  chain still covers;
- the request uses an API key. Validation results are cached for `60` seconds and group changes
  do not clear them;
- the user is root, who reaches every active, non-archived project without groups.

Fix: check the user's other groups (first step above). For immediate API-key cut-off, revoke the
key ([API keys](../api-keys/usage.md)).

### A user was logged out after a group change

Cause: expected. Deleting a user group or project group, revoking a grant and removing a project
from a project group revoke the project sessions and refresh-token families of users who lost the
project. A removed member's token is refused on its next request.

Fix: the user logs in again with a project they still reach.

### A newly granted project does not appear in the current session

Cause: a session is bound to one project. The grant is effective, but the existing session does
not move.

Fix: log in with the new `project_hash`, or call `POST /auth/switch-project`, which requires
recent authentication ([authentication](../authentication-usage-cases.md)). Group names reported
for a session can lag by up to `30` seconds (`VALIDATE_CACHE_TTL`).

### A permission group is attached but the user still gets 403

Cause: permission groups attached to a user group show up in the permission inspection endpoints
but are not used for authorization, which reads global-role permissions.

Fix: grant the permission through the user's global role. See
[permission resolution](../permissions/resolution.md).

## Errors from group routes

### 403 on every user-group route

Cause: the session carries neither `admin` nor `manage_users`. A consumer whose role has
`manage_roles` can use project-group routes but not user-group routes.

Fix: use a root or admin session, or have root grant `manage_users` through the consumer's
global role.

### 403 on project-group routes

Cause: the session carries neither `admin` nor `manage_roles`.

Fix: as above, with `manage_roles`.

### 403 changing an `admin_` group

Cause: only root may create, rename, delete, or change members or grants of such a group. The
message is "Only root users may change project admin groups". Case and accents are ignored, so
`Admin_x` counts too.

Fix: call as root. To make someone a project administrator, use
`PUT /user-types/admin/{user_hash}/projects` ([user types](../users/user-types.md)). To name an
ordinary group, pick a name that does not start with `admin_`.

### 409 creating or renaming a group

Cause: the name is used by another group of the same kind, including deleted groups. Comparison
ignores case.

Fix: choose another name. Deleted groups cannot be restored through the API.

### Updating a project group returns 500

Cause: the request had neither `group_name` nor `description` (or both were empty, which counts as
omitted). Unlike the user-group route, which answers `400`, the project-group route answers `500`
`INT_7001` ("Update failed").

Fix: send at least one non-empty field. A description cannot be cleared.

### Revoking a grant returns 500

Cause: there is no active grant between the two groups (already revoked, never granted, or removed
by a group delete).

Fix: list the grants first with `GET /admin/user-groups/{group_hash}/project-groups`.

### Bulk add returns 200 but some users were not added

Cause: the bulk route answers `200` once the group exists. Unknown or inactive users are listed in
`errors[]`; other failures appear in `results[]` with `status: "error"`.

Fix: read `summary.error_count`, then retry the failed hashes with the single-add route to get a
specific `404`.

### 404 for a group hash that used to work

Cause: the group was deleted. Lookups return active groups only, and a deleted group keeps its
hash but cannot be reactivated through the API.

Fix: list groups with `GET /admin/user-groups` or `GET /admin/project-groups` to find the
replacement.

## Things that do not work as they look

- **`parent_group_id` has no effect.** Hierarchy exists in the schema, but no route sets it and the
  access chain never follows it.
- **`derived_projects` and `total_derived_projects` are always empty or `0`.** Read
  `accessible_projects` instead.
- **`user_` and `readonly_` default groups grant the same reach.** The names carry no permission
  difference; capabilities come from global roles.
