# Projects troubleshooting

Symptom, cause and fix. Error codes are explained in [errors.md](../errors.md); route contracts
and the authorization matrix are in [reference.md](reference.md).

## Authorization errors

### 403 creating a project

Cause: `POST /projects` is root-only. Admin users and consumers get `403` `AUTHZ_2002` whatever
permissions their session carries.

Fix: create the project with a root session, then assign an admin user to it
([set up a new project](scenarios.md#set-up-a-new-project)).

### 403 on update, delete, members or groups with an admin-looking session

Cause: these routes need admin scope. A consumer whose global role grants `admin` or
`manage_users` still has none (`403` `AUTHZ_2002`). An admin user acting on a project they are not
assigned to gets `403` `AUTHZ_2003`.

Fix: use root, or assign the admin user to the project through
`/user-types/admin/{user_hash}/projects` ([user types](../users/user-types.md)). An admin user's
assignments can be checked with `GET /user-types/admin/{user_hash}/projects`.

### 403 `AUTHZ_2003` reading a project

Cause: without admin scope, `GET /projects/{project_hash}`, `/activity` and `/stats` need group
reach, and archived projects are never reachable through groups.

Fix: check the access chain as described in
[groups troubleshooting](../groups/troubleshooting.md#a-user-cannot-reach-a-project).

## Visibility problems

### A project is missing from `GET /projects`

Cause, by caller:

- consumer: no active chain reaches it, or it is archived;
- admin user: not assigned to it, or it is archived;
- root: it is archived, or it is on a later page. Root pagination reports `total` as the page size
  and `has_more: false`.

Fix: for root, keep paging until a page has fewer than `limit` rows, or use `search`. For the
others, check the chain or the assignment. An archived project is still readable by root with
`GET /projects/{project_hash}`.

### 404 for a project that used to work

Cause: the project was deleted (`is_active = 0`). Deleted projects return `404` on every route and
cannot be restored through the API.

Fix: none through the API. Sessions and API keys scoped to it no longer validate.

### A project is denied everywhere, but root can still open it

Cause: the project is archived in the database. Login and switch-project return `403`, sessions
scoped to it get `401`, it disappears from listings and group reach, and its member list is empty.
No route shows or changes the flag.

Fix: inspect `projects.archived` in the database. `PATCH /projects/{project_hash}/archive` cannot
help; it returns `501`.

### Nobody can log in to a new project

Cause: the default user groups start empty and no admin user is assigned. Only root reaches it.

Fix: assign an admin user and add users to `user_<project_id>`
([set up a new project](scenarios.md#set-up-a-new-project)).

### A user cannot reach a project

The access chain is the groups suite's concern:
[groups troubleshooting](../groups/troubleshooting.md#a-user-cannot-reach-a-project).

## Unexpected responses

### 501 from owner or archive

Cause: `PATCH /projects/{project_hash}/owner` and `PATCH /projects/{project_hash}/archive` are
stubs. They return `501` `INT_7006` after the request passes validation, authorization and project
lookup. Nothing is changed.

Fix: none through the API. An earlier `400`, `403` or `404` from these routes means the request
failed before reaching the stub.

### Statistics differ from the member list

Cause: `statistics.total_users` counts only users reached through groups, so root users are
missing unless they are group members, while the member list includes every active root user.
`active_sessions` is always `null` because the statistics procedure does not measure sessions
([project statistics](reference.md#project-statistics)).

Fix: use `GET /projects/{project_hash}/members` (`pagination.total`) for the complete count.

### Member list counts do not add up

Cause: `statistics.total_members` covers all members, but `root_users`, `admin_users`,
`consumer_users` and `active_members` count only the current page. Every active root user is
listed as a member of every non-archived project.

Fix: page through the whole list, or filter with `user_type`.

### `user_access.user_groups` lists groups unrelated to the project

Cause: `GET /projects/{project_hash}` returns all of the caller's user groups, not only those that
reach the project. The same is true of `groups` in the member list.

Fix: to see which groups lead to the project, use `GET /projects/{project_hash}/groups` and
compare.

### 400 on `PUT` with nothing changed

Cause: both fields were omitted or empty. Empty form values count as omitted, so a description
cannot be cleared.

Fix: send at least one non-empty field.
