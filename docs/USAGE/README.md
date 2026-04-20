# Usage Documentation

Practical usage guides and real-world scenarios for the `api.auth` authentication and authorization system.

---

## System Architecture

The system uses a **Groups-of-Groups** access model:

```
USER → USER_GROUP → PROJECT_GROUP → PROJECTS
                  ↘
                    PERMISSION_GROUP → PERMISSIONS
```

- **Users** belong to **User Groups** (organizational teams)
- **User Groups** link to **Project Groups** (project containers)
- **Project Groups** contain related **Projects**
- **User Groups** also have **Permission Groups** assigned
- **Permission Groups** contain individual **Permissions**

---

## Documentation Suites

### Getting Started
- **[Getting Started](getting-started.md)** — First-time setup, bootstrap, env config, registration/login, gotchas

### Authentication & Sessions
- **[Authentication Usage Cases](authentication-usage-cases.md)** — Login, registration, session management, project switching, multi-project workflows
- **[Client Authentication Guide](client-authentication-guide.md)** — Frontend/mobile integration with JS, Python, and React examples

### Domain Suites

| Domain | Entry Point | Covers |
|--------|-------------|--------|
| Users | [users/README.md](users/README.md) | Profile, user types, bulk ops, lifecycle |
| Groups | [groups/README.md](groups/README.md) | User groups, project groups, CRUD workflows |
| Projects | [projects/README.md](projects/README.md) | Project CRUD, access control, member management |
| Permissions | [permissions/README.md](permissions/README.md) | Dual-path auth, permission groups, assignments |
| Roles | [roles/README.md](roles/README.md) | Global role CRUD, permission-group linking, user assignment |
| Audit Logs | [audit_logs/README.md](audit_logs/README.md) | Activity feed, API audit logs (`/admin/audit/*`), security events, export |

### Admin & System
- **[Admin Usage Cases](admin-usage-cases.md)** — Dashboard stats, system health, cache management, cross-domain bulk operations

### Reference
- **[Error Reference](errors.md)** — Error codes, response shapes, status codes, UUID masking, troubleshooting

---

## API Surface Overview

### Route Families

| Prefix | Area | Auth | Key Endpoints |
|--------|------|------|---------------|
| `/auth` | Authentication | Mixed | login, register, validate, refresh, logout, switch-project, check-availability |
| `/users` | User Management | Yes | profile, access-summary, list, search, detail, update, status, reset, delete |
| `/user-types` | User Types | Root/Admin | create root/admin, type info, type change, list by type, stats, admin project assignment |
| `/projects` | Projects | Mixed | CRUD, members, groups, activity, stats |
| `/admin/user-groups` | User Groups | Admin/manage_users | CRUD, members (single/bulk), project-group links |
| `/admin/project-groups` | Project Groups | Admin/manage_roles | CRUD, project links |
| `/roles` | Global Roles | Mixed | Role/permission-group/permission CRUD, user role assignment, project catalog |
| `/permissions` | Permission Assignments | Mixed | Assign permission groups to user-groups/users, self-service queries, catalogs |
| `/admin/audit/*` | API Audit Logs | Admin/Root | logs, security-events, statistics, export |
| `/admin/users/{id}/activity` | User Activity | Admin/Root | Per-user combined activity timeline |
| `/admin` | Admin Dashboard | Admin/Root | dashboard/stats, activity, activity/{id}, activity/types, health, user/project statistics, system/overview |
| `/system` | System | Mixed | info, health, ping, cache stats/clear/invalidate |
| `/admin` (bulk) | Bulk Operations | Admin | users/bulk-update, users/bulk-delete, projects/{hash}/bulk-assign-roles, user-groups/bulk-assign |

**API Version**: 2.2.0 (see `src/main.py`)

**Content-Type**: Almost all POST/PUT/PATCH endpoints use `multipart/form-data`. Exceptions: `POST /admin/user-groups/{hash}/members/bulk` and `POST /admin/audit/export` use JSON.

**User-Agent**: Required on every request. Missing it returns 422.

For detailed endpoint tables, see each suite's `reference.md`.

---

## Quick Start

1. **[Getting Started](getting-started.md)** — Deploy, bootstrap root, create first admin/project/group
2. **[Error Reference](errors.md)** — Understand error responses before integrating
3. **[Authentication Usage Cases](authentication-usage-cases.md)** — Login, register, session lifecycle
4. **[Users Suite](users/README.md)** — User management and lifecycle
5. **[Groups Suite](groups/README.md)** — Understand the access bridge
6. **[Projects Suite](projects/README.md)** — Project CRUD and access
7. **[Permissions Suite](permissions/README.md)** — How permissions resolve (critical: read [resolution.md](permissions/resolution.md))
8. **[Roles Suite](roles/README.md)** — Global role management
9. **[Admin Usage Cases](admin-usage-cases.md)** — Dashboard, monitoring, bulk ops
10. **[Audit Logs Suite](audit_logs/README.md)** — Activity feed, API audit logs, compliance

### Common Tasks

| Task | Guide |
|------|-------|
| Login/Logout | [Authentication - Login](authentication-usage-cases.md#login) |
| Register new user | [Authentication - Registration](authentication-usage-cases.md#registration) |
| Update my profile | [Users - Profile](users/usage.md#profile-operations) |
| View my access | [Users - Access Summary](users/usage.md#access-summary) |
| Change user type | [Users - User Types](users/user-types.md#change-user-type-with-assignment-rules) |
| Add user to a project | [Projects - Scenario 1](projects/scenarios.md#scenario-1-setting-up-a-new-project) |
| Create a new team | [Groups - Usage](groups/usage.md#creating-user-groups) |
| Grant team access to projects | [Groups - Architecture](groups/architecture.md#core-access-model) |
| Set up permissions for a team | [Permissions - Usage](permissions/usage.md#user-group-permission-assignments) |
| Create ROOT/ADMIN users | [Users - User Types](users/user-types.md#create-a-root-user) |
| Check my permissions | [Permissions - Usage](permissions/usage.md#current-user-queries) |
| Create a new role | [Roles - Usage](roles/usage.md#creating-roles) |
| View dashboard stats | [Admin - Dashboard](admin-usage-cases.md#admin-dashboard) |
| Bulk update users | [Users - Bulk Operations](users/bulk-operations.md#bulk-update-users) |
| View activity logs | [Audit Logs - Activity Feed](audit_logs/usage.md#activity-feed-dashboard) |
| View API audit logs | [Audit Logs - API Audit Logs](audit_logs/usage.md#api-audit-logs) |
| Export audit data | [Audit Logs - Export](audit_logs/usage.md#export) |

---

## Platform Constraints

| Constraint | Detail |
|------------|--------|
| **Content-Type** | Almost all POST/PUT/PATCH use `multipart/form-data`. Exceptions: `POST /admin/user-groups/{hash}/members/bulk` and `POST /admin/audit/export` use JSON. |
| **User-Agent** | Required on **every** request. Missing it returns 422. |
| **POST body limit** | 8MB maximum. Exceeding it returns 413. |
| **501 stubs** | `PATCH /projects/{hash}/owner` and `PATCH /projects/{hash}/archive` are not implemented. |
| **No rate limiting** | No endpoint has rate limiting. Protect at the infrastructure level. |
| **JWT_SECRET_KEY** | Must be set in production. If omitted, each restart generates a new key and invalidates all sessions. |
| **CORS** | Defaults to `http://localhost:3000,http://localhost:5173,http://localhost:4173`. Set `ALLOWED_ORIGINS` in production. |
| **Password validation** | No server-side enforcement. Clients must validate. |
| **First root user** | Must be created directly in the database. No API bootstrap exists. |

---

## Related Documentation

- **[Database Schema](../../schemas/)** — Database structure, relationships, and stored procedures

---

**Last Updated**: April 2026
**API Version**: 2.2.0
