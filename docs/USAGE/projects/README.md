# Projects Documentation

Detailed, repo-specific documentation for project management and project access in `api.auth`.

---

## 📖 Overview

Projects are the leaf nodes of the runtime access model implemented in this repository:

```
USER → USER_GROUP → PROJECT_GROUP → PROJECT
```

This projects suite focuses on what happens at the project layer:

- project CRUD under `/projects`
- project-group assignment under `/admin/project-groups`
- user-group-to-project-group access wiring under `/admin/user-groups/{hash}/project-groups`
- login and project switching with project-scoped session context
- default access scaffolding created automatically by `create_default_groups()`

If you need the full group model first, read the [groups documentation suite](../groups/README.md).

---

## 🗂️ Documents in This Suite

| Document | Focus |
|----------|-------|
| [usage.md](usage.md) | Day-to-day project operations: create, inspect, update, delete, and manage access through groups |
| [architecture.md](architecture.md) | Runtime model, route files, DB modules, stored procedures, and important caveats |
| [request-flow.md](request-flow.md) | End-to-end flows for listing, creating, deleting, logging in, and switching projects |
| [scenarios.md](scenarios.md) | Concrete repo-specific examples for setup, onboarding, contractors, and reorganizations |
| [reference.md](reference.md) | Endpoint and operational reference for `/projects`, project groups, and access bridge routes |
| [troubleshooting.md](troubleshooting.md) | Common failures, caveats, diagnostics, and best practices |

---

## 🧠 Core Project Model in This Repo

- **Projects** live in `projects`
- **Project groups** live in `project_groups` and contain projects through `project_group_members`
- **User groups** gain project access through `user_group_project_groups`
- **Accessible projects** are resolved through `sp_get_user_accessible_projects` and `v_user_project_access`
- **Sessions** embed the current project context during login and `/auth/switch-project`
- **New projects auto-bootstrap access scaffolding** through `create_default_groups()`

---

## 🚦 Recommended Reading Order

1. Start with [usage.md](usage.md)
2. Then read [architecture.md](architecture.md)
3. Use [request-flow.md](request-flow.md) for runtime behavior
4. Keep [reference.md](reference.md) open while operating the API
5. Use [scenarios.md](scenarios.md) and [troubleshooting.md](troubleshooting.md) for real workflows and failure cases

---

## 🔗 Related Documentation

- **[Usage Documentation Home](../README.md)** - Complete usage index
- **[Groups Documentation Suite](../groups/README.md)** - Access model and group operations
- **[Authentication Usage Cases](../authentication-usage-cases.md)** - Login, refresh, and project switching
- **[Permissions Documentation Suite](../permissions/README.md)** - Capability management separate from project reach
- **[Database Schema](../../../schemas/)** - SQL schema, views, and stored procedures

---

**Last Updated**: April 2026  
**Document Version**: 1.0
