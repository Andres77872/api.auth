# Permissions Endpoint and Operational Reference

Reference for the permissions-related API surface used in this repository.

---

## Roles

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/roles/roles` | POST | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | Form | Create role |
| `/roles/roles` | GET | Valid session | Query params | List roles |
| `/roles/roles/{hash}` | GET | Valid session | - | Get role details and linked permission groups |
| `/roles/roles/{hash}` | PUT | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | Form | Update role metadata |
| `/roles/roles/{hash}` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | - | Soft-delete role |
| `/roles/roles/{hash}/permission-groups/{pg_hash}` | POST | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | - | Attach permission group to role |
| `/roles/roles/{hash}/permission-groups` | GET | Valid session | - | List role permission groups |
| `/roles/roles/{hash}/permission-groups/{pg_hash}` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | - | Remove permission group from role |

---

## Role Assignment

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/roles/users/me/role` | GET | Valid session | - | Get current user's role |
| `/roles/users/{user_hash}/role` | PUT | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | Form | Assign role to user |
| `/roles/users/{user_hash}/role` | GET | Valid session | - | Inspect a user's role |
| `/roles/users/{user_hash}/role` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | - | Remove role from user |

---

## Permission Groups

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/roles/permission-groups` | POST | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | Form | Create permission group |
| `/roles/permission-groups` | GET | Valid session | Query params | List permission groups |
| `/roles/permission-groups/{hash}` | GET | Valid session | - | Get permission group details |
| `/roles/permission-groups/{hash}` | PUT | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | Form | Update permission group |
| `/roles/permission-groups/{hash}` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | - | Soft-delete permission group |
| `/roles/permission-groups/{hash}/permissions/{perm_hash}` | POST | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | - | Add permission to permission group |
| `/roles/permission-groups/{hash}/permissions` | GET | Valid session | - | List permissions in group |
| `/roles/permission-groups/{hash}/permissions/{perm_hash}` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | - | Remove permission from permission group |

---

## Permissions

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/roles/permissions` | POST | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | Form | Create permission |
| `/roles/permissions` | GET | Valid session | Query params | List permissions |
| `/roles/permissions/{hash}` | GET | Valid session | - | Get permission details |
| `/roles/permissions/{hash}` | PUT | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | Form | Update permission |
| `/roles/permissions/{hash}` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | - | Soft-delete permission |

---

## User-Group Permission Assignments

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/permissions/admin/user-groups/{hash}/permission-groups` | POST | `root` / `admin`; declared consumer `manage_roles` fallback currently fails closed | Form | Assign permission group to user group |
| `/permissions/admin/user-groups/{hash}/permission-groups/{pg_hash}` | DELETE | `root` / `admin`; declared consumer `manage_roles` fallback currently fails closed | - | Remove permission group from user group |
| `/permissions/admin/user-groups/{hash}/permission-groups` | GET | `root` / `admin`; declared consumer `manage_roles` fallback currently fails closed | - | List permission groups on a user group |
| `/permissions/admin/user-groups/{hash}/permission-groups/bulk` | POST | `root` / `admin`; declared consumer `manage_roles` fallback currently fails closed | Form | Bulk-assign permission groups to user group |

---

## Direct User Permission Assignments

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/permissions/users/{user_hash}/permission-groups` | POST | `root` / `admin`; declared consumer `manage_roles` fallback currently fails closed | Form | Directly assign permission group to user (required `permission_group_hash`; optional `notes` for the assignment reason) |
| `/permissions/users/{user_hash}/permission-groups/{pg_hash}` | DELETE | `root` / `admin`; declared consumer `manage_roles` fallback currently fails closed | - | Remove direct assignment |
| `/permissions/users/{user_hash}/permission-groups` | GET | `root` / `admin`; declared consumer `manage_roles` fallback currently fails closed | - | List direct permission groups for user |

---

## Current-User Permission Queries

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/permissions/users/me/permissions` | GET | Valid session | - | Get effective permissions from all three sources |
| `/permissions/users/me/permissions/check/{permission}` | GET | Valid session | - | Check one permission via extended resolver |
| `/permissions/users/me/permission-groups` | GET | Valid session | - | Get direct permission groups only |
| `/permissions/users/me/permission-sources` | GET | Valid session | - | Break down permission sources |

---

## Catalog Endpoints (Metadata Only)

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/permissions/projects/{hash}/permission-group-catalog/{pg_hash}` | POST | `root` / `admin`; declared consumer `manage_roles` fallback currently fails closed | Form | Add permission group to project catalog (both Form fields `catalog_purpose` and `notes` are optional; the request body may be empty) |
| `/permissions/projects/{hash}/permission-group-catalog/{pg_hash}` | DELETE | `root` / `admin`; declared consumer `manage_roles` fallback currently fails closed | - | Remove permission group from project catalog |
| `/permissions/projects/{hash}/permission-group-catalog` | GET | Valid session | - | List a project's cataloged permission groups |
| `/permissions/permissions/groups/{pg_hash}/project-catalog` | GET | Valid session | - | List projects cataloging a permission group |
| `/roles/projects/{hash}/catalog/roles/{role_hash}` | POST | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | Form | Add role to project role catalog |
| `/roles/projects/{hash}/catalog/roles/{role_hash}` | DELETE | `root` / `admin`, otherwise consumer with `manage_roles` via role-only check | - | Remove role from project role catalog |
| `/roles/projects/{hash}/catalog/roles` | GET | Valid session | - | List a project's cataloged roles |

---

## Permission-Group Usage Queries

| Endpoint | Method | Auth / Permission | Content Type | Purpose |
|----------|--------|-------------------|--------------|---------|
| `/permissions/permissions/groups/{pg_hash}/user-groups` | GET | `root` / `admin`; declared consumer `manage_roles` fallback currently fails closed | - | List user groups using a permission group |
| `/permissions/permissions/groups/{pg_hash}/users` | GET | `root` / `admin`; declared consumer `manage_roles` fallback currently fails closed | - | List users with direct assignment of a permission group |

---

## Operational Notes

### Request shapes

- most write operations use **form data**
- bulk user-group permission assignment also uses **form data** with repeated field names
- read operations mostly use plain query params or path params

### Guard differences

- `/roles` write routes use a **role-only** `manage_roles` fallback
- `/permissions` admin routes declare an **extended** `manage_roles` fallback,
  but the helper/procedure name mismatch makes it fail closed in a canonical
  deployment
- `/admin/user-groups` and `/admin/project-groups` are separate suites with separate session-based guards

### Path oddities

- the routes under `/permissions/permissions/groups/...` are real, not a typo in this doc
- they are produced by router prefix + route path concatenation in `permission_assignments.py`

### Metadata semantics

- catalog endpoints do not grant or deny authorization
- they are safe for organization, not for enforcement

---

## AUTHZ Error Reference

| Code | Typical meaning in this area |
|------|------------------------------|
| `AUTHZ_2001` | Access denied |
| `AUTHZ_2002` | Insufficient permissions |
| `AUTHZ_2003` | Project access denied |
| `AUTHZ_2004` | Group-level access denied |
| `AUTHZ_2005` | Specific resource access denied |
| `AUTHZ_2006` | Role assignment denied |
| `AUTHZ_2007` | Permission denied |
| `AUTHZ_2008` | API key has no access to the requested project |

---

## Related Documentation

- **[Permissions Overview](README.md)**
- **[Usage](usage.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Document Version**: 1.0
