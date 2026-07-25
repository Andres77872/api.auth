# Groups Troubleshooting, Caveats, and Best Practices

Things that commonly confuse operators working with the groups system in `api.auth`.

---

## Troubleshooting

### User cannot access a project

Check the full chain, not just one piece.

1. Is the user in the expected user group?
   ```bash
   curl -X GET "http://localhost:8000/admin/user-groups/users/$USER_HASH/groups" \
     -H "Authorization: Bearer $TOKEN"
   ```
2. Does that user group have a project-group link?
   ```bash
   curl -X GET "http://localhost:8000/admin/user-groups/$GROUP_HASH/project-groups" \
     -H "Authorization: Bearer $TOKEN"
   ```
3. Does the project group actually contain the project?
   ```bash
   curl -X GET "http://localhost:8000/admin/project-groups/$PROJECT_GROUP_HASH" \
     -H "Authorization: Bearer $TOKEN"
   ```

If any link in that chain is missing, access resolution breaks.

---

### Changes do not show up immediately

Common causes:

- the user's current session still contains old group context
- the user needs to log in again or switch project context
- cached access or permission data has not been refreshed yet

Practical fix order:

1. verify the DB-facing API calls succeeded
2. re-login or switch project
3. if needed, clear/invalidate cache through admin/system endpoints

---

### Bulk membership assignment only partially succeeds

The bulk endpoint reports successes and failures individually. Read the response body, don't just look at HTTP 200.

Typical causes:

- one or more `user_hash` values are invalid
- some users are already assigned
- some previously inactive assignments were reactivated

---

### A group delete removed more access than expected

This is the expected cascade.

Deleting a user group soft-deactivates:

- the group itself
- member rows in `user_group_members`
- access links in `user_group_project_groups`

It also **revokes the affected members' live project sessions** (`reason="user_group_deleted"`), so those users are kicked out and must re-authenticate. The same active session revocation fires when you revoke a user-group → project-group link (`user_group_project_group_access_revoked`), delete a project group (`project_group_deleted`), or remove a project from a project group (`project_removed_from_group`).

So if you only wanted to remove one project's reach, revoke the project-group link first instead of deleting the entire user group — and expect affected users to be logged out of the impacted projects either way.

---

## Current Caveats

### Hierarchical group columns are not public CRUD features

`parent_group_id` exists in schema tables, and SQL includes hierarchy views, cycle-prevention triggers, and recursive permission logic. The active group-management route layer, however, does not expose `parent_group_id` as a create/update field and the DB helper paths pass `NULL`.

So: do not operate hierarchy through the public group CRUD API. If you rely on SQL-layer hierarchy behavior, verify it directly at the database/procedure level.

### Dedicated test coverage now exists

Group behavior is covered by focused integration suites, including `test_slice11_admin_project_groups.py` (project-group CRUD + non-admin 403), `test_slice19_ug_pg_link_orchestration.py` (UG→PG grant/revoke wiring), `test_groups_of_groups_contract.py` (groups-of-groups endpoint contracts and 404/403 paths), `test_auth_group_project_flows.py`, and the default-group orchestration slices (`test_slice18_project_default_groups_orchestration.py`, `test_slice24_real_default_groups.py`). These run against the real app with middleware active. Still verify environment-specific edge cases before high-risk admin changes, but the "no focused coverage" caveat is no longer accurate.

---

## Best Practices

### 1. Treat user groups as global organizational units

Don't create one user group per tiny action. Use them for stable team or access buckets.

### 2. Treat project groups as reusable access containers

If the same set of projects is granted repeatedly, create or reuse a project group instead of wiring access project by project in your mental model.

### 3. Separate access from capability

- project groups = where a team can go
- permission groups = what a team can do there

Mixing those concepts is how people create a quilombo in access control.

### 4. Use explicit names for temporary groups

Examples:
- `contractors_q2_2026`
- `migration_team_april_2026`
- `readonly_support_weekend`

### 5. Review deletes before executing them

Before deleting a user group, inspect:
- members
- project-group links
- any permission-group assignments tied to the team

### 6. Expect session refresh after material group changes

If group changes affect login context, accessible projects, or cached group names, plan for re-login, refresh, or project switching.

---

## Related Documentation

- **[Groups Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**

---

**Document Version**: 3.1
