# Permissions Documentation

Detailed, repo-specific documentation for the permissions and authorization system implemented in `api.auth`.

---

## 📖 Overview

The permissions system in this repository is not a single RBAC layer. It is a **dual-path authorization model**:

```
REQUEST
  └─► session validation
        ├─► user-type checks (`root`, `admin`, `consumer`)
        └─► global permission resolution
              ├─► role → permission groups → permissions
              ├─► user group → permission groups → permissions
              └─► direct user → permission groups → permissions
```

What matters operationally:

- **User type** still matters for high-level access gates
- **Permissions are global**, not tied to one project in the active route layer
- Effective permissions can come from **three sources at once**
- **Catalog endpoints are metadata only** and do not grant access
- Some admin routes do **not** evaluate permissions the same way, so you need to know the guard differences before operating this API in production

---

## 🗂️ Documents in This Suite

| Document | Focus |
|----------|-------|
| [usage.md](usage.md) | Day-to-day CRUD and assignment workflows for permission groups, permissions, roles, catalogs, and self-service queries |
| [architecture.md](architecture.md) | Dual-path auth model, permission sources, route guard matrix, session/cache behavior, and legacy-vs-current model caveats |
| [resolution.md](resolution.md) | Permission resolution mechanics: three user types, permission chain, two resolution paths (auth vs inspection), project-scoped deny, and known gaps |
| [request-flow.md](request-flow.md) | End-to-end runtime flows for permission checks, role assignment, group assignment, session validation, and metadata catalogs |
| [scenarios.md](scenarios.md) | Concrete repo-specific curl workflows for team setup, direct overrides, role onboarding, audits, and troubleshooting |
| [reference.md](reference.md) | Endpoint and operational reference for `/roles` and `/permissions` |
| [troubleshooting.md](troubleshooting.md) | Common failures, AUTHZ error context, stale-session caveats, and operator best practices |

---

## 🧠 Core Model in This Repo

### Permission sources

The active permission resolution model combines these sources:

1. **Global role assignment** — one role per user
2. **User-group permission-group assignment** — team-scale capability wiring
3. **Direct user permission-group assignment** — individual override path

### What permission groups are

- Managed under `/roles/permission-groups`
- Stored in `global_permission_groups`
- Filled with permissions through `global_permission_group_permissions`
- Reused by roles, user groups, and direct user assignments

### What roles are

- Managed under `/roles/roles`
- Stored in `roles`
- Linked to permission groups through `role_permission_groups`
- Assigned directly to users as a single global baseline

### What catalogs are

- Permission-group catalog endpoints live under `/permissions/projects/.../permission-group-catalog/...`
- Role catalog endpoints live under `/roles/projects/.../catalog/roles/...`
- Both are explicitly documented in code as **metadata only**

If you treat catalogs as authorization, you are going to create a quilombo. They are organizational hints, not enforcement.

---

## 🚦 Recommended Reading Order

1. Start with [usage.md](usage.md)
2. Then read [architecture.md](architecture.md)
3. Read [resolution.md](resolution.md) for permission resolution mechanics and the auth-vs-inspection gap
4. Use [request-flow.md](request-flow.md) for runtime behavior
5. Keep [reference.md](reference.md) open while operating the API
6. Use [scenarios.md](scenarios.md) and [troubleshooting.md](troubleshooting.md) for real workflows and failure cases

---

## ⚠️ Scope and Caveats

- This suite documents the **active public route layer** under `src/routes/global_roles.py` and `src/routes/permission_assignments.py`
- The repo still contains **legacy/project-scoped permission artifacts** in models, schema, and views; those are covered as caveats in [architecture.md](architecture.md)
- Guard behavior differs across `/roles`, `/permissions`, `/admin/user-groups`, and `/admin/project-groups`; do not assume one permission unlocks all of them
- Session-related views such as `/auth/validate` can reflect login-time context rather than the latest admin changes; see [troubleshooting.md](troubleshooting.md)

---

## 🔗 Related Documentation

- **[Usage Documentation Home](../README.md)** - Complete usage index
- **[Authentication Usage Cases](../authentication-usage-cases.md)** - Login, refresh, logout, project switching
- **[Groups Documentation Suite](../groups/README.md)** - User groups, project groups, and the access bridge used by group-based permissions
- **[Roles Documentation Suite](../roles/README.md)** - Global role CRUD, permission-group linking, user assignment, and role-specific caveats
- **[Projects Documentation Suite](../projects/README.md)** - Project access model separate from capability management
- **[Users Documentation Suite](../users/README.md)** - Profile, access summary, user types, and lifecycle operations
- **[Database Schema](../../../schemas/)** - SQL tables, views, and stored procedures

---

**Last Updated**: April 2026  
**Document Version**: 1.0
