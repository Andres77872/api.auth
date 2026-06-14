# Groups Request and Data Flow

How group-related requests move through the API, DB layer, stored procedures, and session lifecycle.

---

## 1. Create a User Group

Flow for `POST /admin/user-groups`:

1. `src/routes/admin_user_groups.py:create_user_group_endpoint()` receives form fields
2. `require_admin()` validates the session and checks `admin` or `manage_users`
3. The route resolves the acting user for audit context
4. `src/Util/db/db_user_groups.py:create_user_group()` runs
5. Stored procedure `sp_create_user_group` persists the record
6. The API returns `CreateUserGroupResponse`

Result: a global user group exists, but it still has no members, no project reach, and no permissions until further links are added.

---

## 2. Add Members to a User Group

Flow for `POST /admin/user-groups/{hash}/members` and `/members/bulk`:

1. Route validates the acting session
2. The user group is looked up by hash
3. The user or users are resolved by hash
4. Membership rows are written to `user_group_members`
5. Bulk responses aggregate successes and failures per input user

Important runtime detail:

- a membership may be reactivated instead of inserted fresh if it already existed but was inactive

---

## 3. Grant User Group Access to a Project Group

Flow for `POST /admin/user-groups/{hash}/project-groups`:

1. The route validates the session
2. It resolves the user group and project group
3. `db_user_groups.py:grant_user_group_project_group_access()` runs
4. Stored procedure `sp_grant_user_group_project_group_access` writes into `user_group_project_groups`

This is the main access bridge in the application.

Without this row, user-group membership alone does not give project access.

---

## 4. Login and Session Embedding

Flow for `POST /auth/login`:

1. `src/routes/auth.py:login()` verifies credentials
2. The code resolves accessible projects through the groups-of-groups chain
3. `auth_lifecycle.py:_issue_token_pair()` builds the session payload with active user-group context
4. The session payload stores:
   - `user_group_ids`
   - `user_group_names`
   - current project context if one is selected
5. The token/session is stored and returned

This is why a user can log in and immediately see group context reflected in auth responses.

---

## 5. Project Switching

Flow for `POST /auth/switch-project`:

1. The current session is validated
2. The API checks whether the user can access the requested project through the resolved group chain
3. A new session is generated with the new project context
4. Group information relevant to that project context is returned

Operationally, this is one of the moments where group-based access becomes visible to the client without a full fresh login.

---

## 6. Default Group Creation During Project Creation

Flow inside `src/Util/db/db_projects.py:create_default_groups()`:

1. Create a default project group for the new project
2. Insert the new project into `project_group_members`
3. Create default user groups (`admin_*`, `user_*`, `readonly_*`)
4. Link each default user group to the default project group through `user_group_project_groups`

This means project onboarding already assumes the group bridge architecture.

---

## 7. Soft Delete Behavior

Flow for `DELETE /admin/user-groups/{hash}`:

1. The route resolves the group
2. It snapshots the impacted users (`get_users_in_group`) and projects (`get_projects_for_user_group`) **before** deletion
3. `db_user_groups.py:delete_user_group()` executes
4. Stored procedure `sp_delete_user_group` deactivates:
   - the user group
   - its memberships
   - its project-group access links
5. On success, `auth_lifecycle.py:revoke_project_sessions_losing_access(..., reason="user_group_deleted")` revokes the snapshotted users' live sessions for the impacted projects

So deleting a user group is effectively a membership, access, **and live-session** teardown, not just a name cleanup. The revoke / project-group delete / project-removal routes follow the same snapshot-then-revoke pattern with reasons `user_group_project_group_access_revoked`, `project_group_deleted`, and `project_removed_from_group` respectively.

---

## 8. Access Resolution Query Shape

The core accessible-project resolution uses joins equivalent to:

```text
user_group_members
  → user_groups
  → user_group_project_groups
  → project_groups
  → project_group_members
  → projects
```

That is the real runtime data flow behind “user can access this project”.

---

## Related Documentation

- **[Groups Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: June 2026  
**Document Version**: 3.1
