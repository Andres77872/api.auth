# Groups Usage

Practical usage guide for operating the groups system in `api.auth`.

---

## 📖 Table of Contents

- [Authentication and Route Ownership](#authentication-and-route-ownership)
- [Creating User Groups](#creating-user-groups)
- [Managing Membership](#managing-membership)
- [Granting Project Access Through Project Groups](#granting-project-access-through-project-groups)
- [Managing Project Groups](#managing-project-groups)
- [Assigning Permission Groups](#assigning-permission-groups)
- [Updating and Removing Access](#updating-and-removing-access)

---

## Authentication and Route Ownership

The groups feature is split across multiple route families:

| Concern | Route Family | Notes |
|--------|--------------|-------|
| User group CRUD and membership | `/admin/user-groups` | Requires `admin` or `manage_users` |
| Project group CRUD and project assignment | `/admin/project-groups` | Requires `admin` or `manage_roles` |
| Permission group CRUD | `/roles/permission-groups` | Separate permission-group management |
| Attach permission groups to user groups | `/permissions/admin/user-groups/.../permission-groups` | Controls capabilities, not project reach |

**Important:** most endpoints use `application/x-www-form-urlencoded`. The bulk member assignment endpoint uses JSON.

---

## Creating User Groups

User groups represent teams, departments, contractors, or any reusable user bucket.

```bash
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=platform_team&description=Platform engineering team"
```

**What this does in the repo:**
- Creates a global record in `user_groups`
- Does **not** give project access by itself
- Does **not** give permissions by itself

Typical response shape:

```json
{
  "success": true,
  "message": "User group \"platform_team\" created successfully",
  "user_group": {
    "group_hash": "UG-...",
    "group_name": "platform_team",
    "description": "Platform engineering team",
    "created_at": "2026-04-16T10:30:00Z"
  }
}
```

---

## Managing Membership

### Add one user

```bash
curl -X POST "http://localhost:8000/admin/user-groups/UG-PLATFORM123/members" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "user_hash=usr-abc123"
```

### Bulk add users

```bash
curl -X POST "http://localhost:8000/admin/user-groups/UG-PLATFORM123/members/bulk" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{
    "user_hashes": ["usr-abc123", "usr-def456", "usr-ghi789"]
  }'
```

Operational notes:

- Bulk assignment reports per-user success and failure
- Membership timestamps are exposed as `joined_at`
- Existing inactive memberships may be reactivated instead of creating a brand-new logical assignment

### Inspect membership

```bash
curl -X GET "http://localhost:8000/admin/user-groups/UG-PLATFORM123/members?limit=50&offset=0" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

This members endpoint caps `limit` at 100 and returns each member with `user_hash`, `username`, `email`, `user_type`, `is_active`, and `joined_at`, plus a `statistics` block and a `generated_at` timestamp. Use it when you need the operational list. Use `GET /admin/user-groups/{hash}` when you need the broader group view, including linked project groups.

### Reverse lookup: which groups does a user belong to?

```bash
curl -X GET "http://localhost:8000/admin/user-groups/users/usr-abc123/groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

Returns the user-groups a given user is a member of, each with `joined_at`, plus `statistics.total_groups`. Handy when debugging "why can this user reach this project?" from the user side instead of the group side.

---

## Granting Project Access Through Project Groups

This is the critical part that many people get wrong.

User groups do **not** point directly to projects in the active architecture. They point to **project groups**, and project groups contain projects.

```bash
curl -X POST "http://localhost:8000/admin/user-groups/UG-PLATFORM123/project-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_group_hash=PG-BACKEND456"
```

That creates the access link through `user_group_project_groups`.

After this link exists:
- every member of the user group can inherit access to every active project in that project group
- login and project-switch flows can resolve those projects as accessible
- project access still remains separate from permission-group assignment

---

## Managing Project Groups

Project groups are reusable access containers.

### Create a project group

```bash
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "group_name=backend_services&description=Backend APIs and internal services"
```

### Add a project to a project group

```bash
curl -X POST "http://localhost:8000/admin/project-groups/PG-BACKEND456/projects" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=proj-auth-api-123"
```

### Inspect a project group

```bash
curl -X GET "http://localhost:8000/admin/project-groups/PG-BACKEND456" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

Use project groups when multiple teams need the same set of projects, or when a single team needs all projects in a functional area.

---

## Assigning Permission Groups

Permission groups are managed separately because they solve a different problem.

- **Project groups** answer: which projects can this team reach?
- **Permission groups** answer: what can this team do once it gets there?

### Assign an existing permission group to a user group

```bash
curl -X POST "http://localhost:8000/permissions/admin/user-groups/UG-PLATFORM123/permission-groups" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "permission_group_hash=PG-CONTENT789"
```

This is the clean way to give a team reusable capabilities without attaching permissions user by user.

---

## Updating and Removing Access

### Update group metadata

```bash
curl -X PUT "http://localhost:8000/admin/user-groups/UG-PLATFORM123" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "description=Platform engineering and shared services"
```

### Remove a member

```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/UG-PLATFORM123/members/usr-abc123" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

### Revoke user-group access to a project group

```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/UG-PLATFORM123/project-groups/PG-BACKEND456" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

> **Revoke also kills live sessions.** This is not just a row deactivation. The route calls `revoke_project_sessions_losing_access(...)`, so every affected member's active session for the impacted projects is terminated immediately. Those users must re-authenticate.

### Delete a user group

```bash
curl -X DELETE "http://localhost:8000/admin/user-groups/UG-PLATFORM123" \
  -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

Deletion is a **soft delete**. In current stored-procedure behavior, it also deactivates:

- the `user_groups` row
- linked `user_group_members` rows
- linked `user_group_project_groups` rows

The route also calls `revoke_project_sessions_losing_access(..., reason="user_group_deleted")`, so the **live project sessions** of all affected members are revoked. Deleting a group removes live memberships, access links, and active sessions in one operation; affected users must re-authenticate.

The same active session-revocation applies to deleting a project group (`reason="project_group_deleted"`) and removing a project from a project group (`reason="project_removed_from_group"`).

---

## Related Documentation

- **[Groups Overview](README.md)**
- **[Architecture](architecture.md)**
- **[Request & Data Flow](request-flow.md)**
- **[Scenarios](scenarios.md)**
- **[Operational Reference](reference.md)**
- **[Troubleshooting](troubleshooting.md)**

---

**Document Version**: 3.1
