# Permission resolution

A user's permissions are resolved in two different ways, and the two do not agree:

- The **auth-time set** is the `permissions` list attached to a validated access token or API key.
  Route guards act on it. For consumers it comes only from the global role; `root` and `admin`
  sessions carry fixed built-in lists.
- The **inspection view** is what the `/permissions/users/me/...` endpoints report. It is the union
  of the role, user-group, and direct permission-group assignments.

This page is the single authoritative description of both. Other pages in the
[roles](../roles/README.md) and [permissions](README.md) suites link here instead of repeating it.

## At a glance

| Source | Auth-time set (session and API-key guards) | Inspection endpoints | `/roles` admin guard | `/permissions` admin guard |
| --- | --- | --- | --- | --- |
| Built-in list of a `root` or `admin` session | Yes, instead of the role | No | Passes by user type | Passes by user type |
| Global role → permission groups → permissions | Yes, consumers only | Yes | Yes (`manage_roles`) | Yes (`manage_roles`) |
| User group → permission groups (direct members) | No | Yes | No | Yes (`manage_roles`) |
| Direct user → permission groups | No | Yes | No | Yes (`manage_roles`) |
| Project role catalog, permission-group catalog | No | No | No | No |
| Project-scoped role and permission tables | No | No | No | No |

A permission granted only through a user group or a direct assignment is therefore visible in
`GET /permissions/users/me/permissions` but is honored by exactly one guard: the `manage_roles`
fallback of the `/permissions` admin routes. For that reason a permission group containing a
[reserved name](../roles/reference.md#reserved-permission-names) such as `manage_roles` can be
assigned or removed through `/permissions` by root only.

## Building blocks

All of these are global. None of them has a project dimension.

| Concept | Table | Notes |
| --- | --- | --- |
| Permission | `global_permissions` | A name (`permission_name`) that guards match on. Unique, compared case-, accent- and width-insensitively (`utf8mb4_unicode_ci`). |
| Permission group | `global_permission_groups` | Bundles permissions through `global_permission_group_permissions`. |
| Role | `roles` | Bundles permission groups through `role_permission_groups`. A user holds at most one, in `users.role_id`. |
| User-group assignment | `user_group_permission_groups` | Gives a permission group to the members of a user group. |
| Direct assignment | `user_permission_groups` | Gives a permission group to one user, with optional `notes`. |

```text
users.role_id ─► roles ─► role_permission_groups ───────┐     (auth-time and inspection)
user_group_members ─► user_group_permission_groups ─────┼─► global_permission_groups
user_permission_groups ─────────────────────────────────┘     ─► global_permission_group_permissions
                                                                ─► global_permissions
                                                  (user-group and direct rows: inspection only)
```

Every link row has its own `is_active` flag, and so does every role, user group, permission group,
and permission. Every resolver checks the flag of each hop it walks, so switching off any one of them
drops what it granted; see [Soft-delete effects](#soft-delete-effects).

## Auth-time permission set

### What each caller gets

| Caller | `permissions` on the validated session or key | Changes when |
| --- | --- | --- |
| `root`, project login (`POST /auth/login`) | `admin`, `global_admin`, `unrestricted_access` | Fixed for the session |
| `admin`, project login | `admin`, `project_admin`, `manage_users`, `manage_groups`, `manage_permissions` | Fixed for the session |
| `root`, platform login (`POST /auth/platform/login`) | `admin`, `global_admin`, `manage_users`, `manage_roles`, `unrestricted_access` | Fixed for the session |
| `admin`, platform login | `admin`, `project_admin`, `manage_users`, `manage_roles`, `manage_permissions` | Fixed for the session |
| `consumer` | Role-derived: `sp_global_get_user_permissions` | Recomputed on every validation |
| API key owned by `root` | `admin`, `global_admin` | Per key validation |
| API key owned by `admin` (with access to the key's project) | `admin`, `project_admin` | Per key validation |
| API key owned by a `consumer` | Role-derived: `sp_global_get_user_permissions` | Per key validation |

A global role assigned to a `root` or `admin` user changes nothing about their session
permissions.

### Consumer resolution

A consumer session does not keep a permission list: whatever was stored at issue time is ignored.
Every access-token validation (`validate_session` → `validate_access_session` →
`reconstruct_auth_context`) calls `db_global_roles.get_user_permissions`, which runs
`sp_global_get_user_permissions`:

```text
users (is_active)
  └─ roles (is_active)                                   via users.role_id
       └─ role_permission_groups (is_active)
            └─ global_permission_groups (is_active)
                 └─ global_permission_group_permissions (is_active)
                      └─ global_permissions (is_active)  → DISTINCT permission_name
```

These are the rows, with the same flags, that the reserved-name check reads
(`sp_global_get_user_role`, `sp_global_get_role_permission_groups`,
`sp_global_get_permission_group_permissions`), so a role cannot grant a reserved name that the check
does not see. If the lookup fails, the consumer gets an empty list rather than an error.

API-key requests resolve the owner the same way (`verify_api_key` in
`src/middleware/authentication.py`).

### When changes take effect

- **Access tokens.** `validate_access_session` recomputes the context on every request but returns
  the derived `session_full:{access_jti}` Redis entry when one exists. That entry lives
  `VALIDATE_CACHE_TTL` seconds (default `30`). Role, link, and permission changes therefore reach
  existing access tokens within about 30 seconds. No refresh or re-login is needed; `POST /auth/refresh`
  or `POST /auth/switch-project` mints a new `access_jti` and so sees the change immediately.
- **API keys.** A validated key is cached for `60` seconds (`APIKEY_TTL`), including the owner's
  permissions.
- **No other permission cache.** `cache_manager` defines a `permission:` key family
  (`PERMISSION_CHECK_TTL`, 1800 seconds) and the schema has a `permission_cache` table, but no
  resolver reads or writes either.

### Where the auth-time set is visible

- `GET /auth/validate` does **not** return permissions (only user, project, `user_groups`,
  session expiry and `plan`).
- `POST /auth/validate-api-key` returns `permissions` for the key owner.
- No endpoint returns a consumer's role-derived list directly. Reconstruct it from the role:
  `GET /roles/users/me/role`, then `GET /roles/roles/{role_hash}/permission-groups`, then
  `GET /roles/permission-groups/{group_hash}/permissions`, or read the `from_role` section of
  `GET /permissions/users/me/permission-sources`.

## Inspection-time resolution

These endpoints resolve all three assignment sources, always for the caller, straight from the
database (no cache):

| Endpoint | Resolver | Returns |
| --- | --- | --- |
| `GET /permissions/users/me/permissions` | `sp_get_user_all_permissions` | Distinct permission names from role, user groups, and direct assignments |
| `GET /permissions/users/me/permissions/check/{permission_name}` | `sp_check_user_has_permission_extended` | `has_permission` for one name, same three sources |
| `GET /permissions/users/me/permission-sources` | `sp_get_user_permission_sources` | Permission **groups** per source (`from_role`, `from_user_groups`, `from_direct_assignment`) |
| `GET /permissions/users/me/permission-groups` | `sp_get_user_permission_groups` | Direct assignments only |
| `GET /roles/users/me/role` | `sp_global_get_user_role` | The active role, or `null` |

The three sources as the procedures read them:

```text
role        users (is_active).role_id ─► roles (is_active) ─► role_permission_groups (is_active)
user group  user_group_members (is_active, direct membership only) ─► user_groups (is_active)
            ─► user_group_permission_groups (is_active)
direct      user_permission_groups (is_active)
            └─ union of permission groups ─► global_permission_groups (is_active)
                                             ─► global_permission_group_permissions (is_active)
                                             ─► global_permissions (is_active)
```

Rules that follow from the procedures:

- Only **direct** user-group membership counts. Parent groups (`user_groups.parent_group_id`) are not
  walked, although `sp_get_user_all_groups_with_inheritance` exists.
- There is no `root`/`admin` bypass. A root caller gets `has_permission: false` for any name its role
  does not grant, and the built-in session lists never appear.
- All three procedures resolve the same permission groups with the same flags, so
  `/permission-sources` lists exactly the groups behind `/permissions` and `/check`.
- A permission reached through several sources is listed once (`DISTINCT`). There is no deny rule
  and no precedence between sources.

## Guards on the role and permission APIs

| Guard | Routes | Passes when |
| --- | --- | --- |
| `require_admin` in `src/routes/global_roles.py` | `/roles` writes and catalog writes | Caller's user type is `root` or `admin`, or a live `sp_global_check_user_has_permission(user, 'manage_roles')` is true (role only, same flags as the auth-time resolver) |
| `require_admin` in `src/routes/permission_assignments.py` | `/permissions` admin routes | Caller's user type is `root` or `admin`, or `sp_check_user_has_permission_extended(user, 'manage_roles')` is true (role, user groups, direct; every hop active) |
| `require_valid_session` (both files) | Every `GET` route except the four `/permissions` admin reads | Any valid access token |

Both `require_admin` guards read the database live, so they are not delayed by the 30-second
session cache, and both deny when the permission lookup itself fails. Past the guard, non-root callers
are held to the reserved-name rule: the `/roles` routes stop them from creating, moving, or assigning
reserved permission names (bulk role assignment included), and the `/permissions` routes stop them from
assigning or removing a permission group that contains one; see
[Roles reference](../roles/reference.md#reserved-permission-names).

Guards elsewhere read the **auth-time set** as their first check, for example:

| Guard | Needs in session permissions |
| --- | --- |
| `/admin/user-groups` router, `/admin/users/bulk-update`, `/admin/users/bulk-delete` | `admin` or `manage_users` |
| `/admin/project-groups` router | `admin` or `manage_roles` |
| `/admin/projects/{project_hash}/bulk-assign-roles`, `/admin/user-groups/bulk-assign` | `admin` |
| `/admin/billing` router | `admin` or `manage_billing` |
| `/api-keys` router (`verify_admin_access`) | user type `root`/`admin`, or `admin`/`global_admin` |

For a consumer these are satisfied only through the global role. A user-group or direct assignment
of `manage_users` unlocks none of them. Some routes add further checks after this one; in particular
`resolve_admin_scope` (`src/Util/admin_scope.py`) reads the user type live and gives administrative
scope only to `root` and `admin` users, whatever the session permissions say. Those rules are
documented with each route's suite.

## Auth-time versus inspection-time

| Aspect | Auth-time set | Inspection endpoints |
| --- | --- | --- |
| Sources | Role only (consumers); fixed list (`root`/`admin`) | Role, direct user-group membership, direct assignment |
| `root`/`admin` built-ins | Included | Not shown; no bypass |
| Soft-deleted role still in `users.role_id` | Ignored | Ignored |
| Soft-deleted permission group still linked | Ignored | Ignored |
| Soft-deleted user group, memberships still active | Not a source | Ignored |
| Soft-deleted permission | Ignored | Ignored |
| Freshness | Up to `VALIDATE_CACHE_TTL` (30 seconds) for tokens, 60 seconds for API keys | Live |
| Exposed by | `POST /auth/validate-api-key` only | `/permissions/users/me/*` |

## Soft-delete effects

Nothing in these suites is hard-deleted. What each change does to the two views:

| Change | Auth-time set (consumers) | `/me/permissions`, `/check`, `/permissions` admin guard | `/me/permission-sources` |
| --- | --- | --- | --- |
| `DELETE /roles/roles/{role_hash}` | Role's permissions dropped | Role source dropped (`users.role_id` and links stay, ignored) | Role rows dropped |
| `DELETE /roles/permission-groups/{group_hash}` | Dropped unless another linked group grants it (links stay, ignored) | Dropped unless another source grants it | Group rows dropped |
| `DELETE /roles/permissions/{permission_hash}` | Dropped | Dropped | Unchanged (lists groups) |
| `DELETE /roles/roles/{role_hash}/permission-groups/{group_hash}` | Dropped unless another linked group grants it | Dropped for the role source | Dropped |
| `DELETE /roles/permission-groups/{group_hash}/permissions/{permission_hash}` | Dropped | Dropped | Unchanged |
| `DELETE /roles/users/{user_hash}/role` | Emptied | Role source dropped | Role rows dropped |
| Remove a user-group or direct assignment | No effect (never counted) | Dropped | Dropped |
| Delete a user group (`/admin/user-groups`) | No effect on permissions | Dropped (the deletion also ends memberships) | Dropped |

A deleted role, group, or permission cannot be restored through the API, and the links to it can no
longer be removed through the API either, because lookups by hash see active rows only. The links
stay as history and grant nothing.

> [!NOTE]
> Databases created from older schema files keep the old resolver procedures until they are
> re-applied: `python scripts/schema_sync.py --apply` re-creates them from
> `schemas/stored_procedures/05_global_roles.sql` and `06_permission_assignments.sql`. Those files
> only drop and re-create procedures; no data changes.

## What does not affect resolution

- **`role_priority`** only orders role listings and the project role catalog.
- **Catalogs.** `role_project_catalog` and `permission_group_project_catalog` are metadata for UIs.
  They neither grant nor restrict anything; `permission_project_catalog` has no routes at all.
- **Project-scoped tables and procedures.** `user_group_project_group_roles`,
  `user_group_project_group_permissions` (grant/deny with priority), the views
  `v_user_scoped_permissions` and `v_user_project_scoped_roles`, and the procedures
  `sp_check_user_permission_for_project_with_deny`, `sp_get_user_role_for_project`, and
  `sp_get_user_scoped_roles` exist in `schemas/` but no Python code calls them. There is no active
  deny rule anywhere.
- **`require_permission()`** in `src/middleware/authentication.py` is defined but no route uses it.
- **Legacy models.** `Permission`, `PermissionGroup`, and `UserProjectPermissionGroup` in
  `src/Util/Models.py` still carry `project_id`; the routes do not use them.

## Worked examples

Consumer `bob` holds role `viewer` (group `read_only` → `read_data`). His user group `developers`
has group `api_access` (→ `call_api`), and root gave him a direct assignment of `reporting`
(→ `manage_roles`, a reserved name).

| Question | Answer |
| --- | --- |
| Session `permissions` | `read_data` |
| `GET /permissions/users/me/permissions` | `call_api`, `manage_roles`, `read_data` |
| `GET /permissions/users/me/permissions/check/manage_roles` | `true` |
| `POST /permissions/users/{user_hash}/permission-groups` as bob | Allowed for a group without reserved names (extended `manage_roles`); `403` for `reporting` |
| `POST /roles/roles` as bob | `403` (role-only check finds no `manage_roles`) |
| `/admin/project-groups` as bob | `403` (session permissions lack `admin` and `manage_roles`) |

If an admin now links `api_access` to role `viewer`, bob's session gains `call_api` within 30
seconds, without a new login. If the admin instead deletes group `read_only`, bob loses `read_data`
from his session within 30 seconds and from the inspection endpoints at once, although the role link
stays in place. If root deletes `reporting`, bob loses `manage_roles` and the `/permissions` admin
routes answer him `403` on the next request.

## Related

- [Permissions](README.md) and [Roles](../roles/README.md) — the assignment and definition APIs
- [Permissions troubleshooting](troubleshooting.md) — symptom-first diagnosis
- [Groups](../groups/README.md) — user groups and the project access chain (which projects a user can enter)
- [Error reference](../errors.md)
