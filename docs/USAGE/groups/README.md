# Groups Documentation

Detailed, repo-specific documentation for the groups system used by `api.auth`.

---

## 📖 Overview

This documentation set covers the real groups model implemented in this repository:

```
USER → USER_GROUP → PROJECT_GROUP → PROJECT
                 ↘
                   PERMISSION_GROUP → PERMISSIONS
```

The groups system is not just a generic RBAC concept. In this codebase:

- **User Groups** are global organizational buckets for users
- **Project Groups** are containers that group projects together
- **Permission Groups** are reusable permission templates attached separately to user groups or users
- **Project access** is granted through `user_group_project_groups`
- **Project switching and login sessions** embed user-group context into the session payload
- **Deletes are soft deletes** (`is_active = 0`), not hard removals

---

## 🗂️ Documents in This Suite

| Document | Focus |
|----------|-------|
| [usage.md](usage.md) | Day-to-day group operations: create, assign, grant access, revoke, delete |
| [architecture.md](architecture.md) | The actual model, tables, route split, and implementation boundaries |
| [request-flow.md](request-flow.md) | End-to-end runtime flows: CRUD, login/session embedding, project switching, deletion |
| [scenarios.md](scenarios.md) | Concrete repo-specific examples for onboarding, contractor access, and team setup |
| [reference.md](reference.md) | Endpoint and operational reference for user groups, project groups, and related permission-group operations |
| [troubleshooting.md](troubleshooting.md) | Common failure modes, caveats, and best practices |

---

## 🧠 Core Model in This Repo

### User Groups
- Managed under `/admin/user-groups`
- Global scope, not tied to a single project
- Hold memberships in `user_group_members`
- Gain project access by linking to project groups through `user_group_project_groups`

### Project Groups
- Managed under `/admin/project-groups`
- Hold projects in `project_group_members`
- Act as access containers, not permission containers

### Permission Groups
- Managed under `/roles/permission-groups` and `/permissions/...`
- Attached separately to user groups through `user_group_permission_groups`
- Affect **what users can do**, not **which projects they can access**

---

## 🚦 Recommended Reading Order

1. Start with [usage.md](usage.md)
2. Then read [architecture.md](architecture.md)
3. Use [request-flow.md](request-flow.md) for runtime behavior
4. Keep [reference.md](reference.md) open while operating the API
5. Use [scenarios.md](scenarios.md) and [troubleshooting.md](troubleshooting.md) when applying it to real workflows

---

## 🔗 Related Documentation

- **[Usage Documentation Home](../README.md)** - Complete usage index
- **[Authentication Usage Cases](../authentication-usage-cases.md)** - Login, refresh, project switching
- **[Users Documentation Suite](../users/README.md)** - User profile, access summary, user types, and lifecycle operations
- **[Projects Documentation Suite](../projects/README.md)** - Project creation, access flows, and operational caveats
- **[Permissions Documentation Suite](../permissions/README.md)** - Permission groups, roles, assignments, and authorization caveats
- **[Database Schema](../../../schemas/)** - SQL schema and stored procedures

---

**Document Version**: 3.1

> **Why version 3.1?** The groups suite was refactored across three major passes (initial docs → architecture corrections → scenario deduplication), then revised again to remove a non-existent project-list endpoint and document live session-revocation side effects. The version number reflects iteration count, not API versioning.
