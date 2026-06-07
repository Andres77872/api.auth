# Permissions Request and Data Flow

End-to-end runtime flows for how the permissions system behaves in `api.auth`.

---

## Flow 1: Session Validation Before Authorization

```
CLIENT REQUEST
  └─► Authorization header or `session_token` cookie
        └─► HTTPBearerOrCookie
              └─► validate_session(access_token)
                    ├─► access JWT signature/exp/type/claim checks
                    ├─► Redis `session:{access_jti}` + `refresh_family:{family_id}` checks
                    ├─► derived `session_full:{access_jti}` cache only after lifecycle checks
                    └─► user-type-specific reconstruction
```

### What happens next

- **root**: global access session
- **admin**: project assignment validated for current project context
- **consumer**: current project membership is rechecked and role-derived permissions are rebuilt

If validation fails, the route usually returns an auth error before any permission logic even starts.

---

## Flow 2: Extended Permission Check (`/permissions/users/me/permissions/check/{name}`)

This is the clearest expression of the active three-source resolver.

```
GET /permissions/users/me/permissions/check/{permission_name}
  └─► permission_assignments.require_valid_session
        └─► check_user_has_permission_extended(user_id, permission_name)
              └─► extended permission-check stored procedure
                    ├─► role permission groups
                    ├─► user-group permission groups
                    └─► direct user permission groups
```

### Why this matters

- this route checks the **full union**
- this is more complete than route guards that rely only on session permissions
- when you need to prove what the DB currently resolves, use this path

Procedure-name caveat: the Python helper currently calls `sp_check_user_has_permission`, while the schema file defines `sp_check_user_has_permission_extended`. The route intent is clearly the extended three-source check, but the exact procedure wiring may depend on your deployed DB state.

---

## Flow 3: Writing Through the `/roles` API

Example: create a role or permission group.

```
POST /roles/roles
  └─► global_roles.require_admin
        ├─► valid session required
        ├─► allow if user_type in {root, admin}
        └─► otherwise check `manage_roles` through role-only resolver
              └─► db_global_roles.check_user_has_permission
                    └─► sp_global_check_user_has_permission
```

After the guard passes:

- route resolves referenced user/role/group records
- DB layer calls stored procedures in `05_global_roles.sql`
- write succeeds or raises conflict/not-found/internal errors

### Caveat

This flow does **not** use the extended permission union for consumer admin access. It is narrower.

---

## Flow 4: Writing Through the `/permissions` Admin API

Example: assign a permission group to a user group.

```
POST /permissions/admin/user-groups/{group_hash}/permission-groups
  └─► permission_assignments.require_admin
        ├─► valid session required
        ├─► allow if user_type in {root, admin}
        └─► otherwise check `manage_roles` through extended resolver
              └─► extended permission-check helper in `db_permission_assignments.py`
```

After the guard passes:

1. resolve user group by hash
2. resolve permission group by hash
3. call `assign_permission_group_to_user_group(...)`
4. stored procedure writes to `user_group_permission_groups`

This is the main team-scale assignment path.

---

## Flow 5: Current-User Effective Permission Listing

```
GET /permissions/users/me/permissions
  └─► require_valid_session
        └─► get_user_all_permissions(user_id)
              └─► sp_get_user_all_permissions
                    ├─► permissions from role-linked groups
                    ├─► permissions from user-group-linked groups
                    └─► permissions from direct-user-linked groups
```

The output is a deduplicated list of permission names.

Use this flow when you want the operational answer to: _what can this user actually do right now according to the DB?_ 

---

## Flow 6: Permission Source Breakdown

```
GET /permissions/users/me/permission-sources
  └─► get_user_permission_sources(user_id)
        └─► sp_get_user_permission_sources
              ├─► role source rows
              ├─► user-group source rows
              └─► direct source rows
```

The route groups the result into:

- `from_role`
- `from_user_groups`
- `from_direct_assignment`

This is your best audit endpoint when an operator says, “why does this user have that permission?”

---

## Flow 7: Session Refresh / Re-login After Changes

```
permission or group assignment changes
  └─► DB state updated
        ├─► some request paths see fresh state immediately
        └─► some access-token/session-derived views still reflect prior login context
              ├─► POST /auth/refresh with refresh_token cookie/body
              ├─► POST /auth/switch-project with access token + current refresh token
              └─► POST /auth/login again
```

### Practical meaning

- self-query endpoints under `/permissions/users/me/...` are the best live verification paths
- `/auth/validate` reflects the validated access session payload such as cached `user_group_names`
- after major RBAC or group changes, refresh with the refresh token or re-login is the safe operator move

---

## Flow 8: Catalog Metadata Flow

Example: add a permission group to a project catalog.

```
POST /permissions/projects/{project_hash}/permission-group-catalog/{pg_hash}
  └─► admin guard
        └─► resolve project + permission group
              └─► write metadata row in permission_group_project_catalog
```

That flow does **not** touch:

- `user_group_permission_groups`
- `user_permission_groups`
- `role_permission_groups`
- `global_permission_group_permissions`

So it changes **documentation metadata**, not authorization.

---

## Related Documentation

- **[Permissions Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Last Updated**: April 2026  
**Document Version**: 1.0
