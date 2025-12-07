# Usage Documentation

This directory contains **practical usage guides** and **real-world scenarios** for working with the authentication system. Unlike the API documentation which focuses on endpoints, these guides focus on **how to accomplish common tasks** and solve real business problems.

---

## 🏗️ System Architecture

The authentication system uses a **Groups-of-Groups Architecture**:

```
USER → USER_GROUP → PROJECT_GROUP → PROJECTS
                 ↘
                   PERMISSION_GROUP → PERMISSIONS
```

**Key Concepts:**
- **Users** belong to **User Groups** (organizational teams)
- **User Groups** have access to **Project Groups** (project containers)
- **Project Groups** contain related **Projects**
- **User Groups** also have **Permission Groups** assigned
- **Permission Groups** contain individual **Permissions**

---

## 📚 Available Guides

### Authentication & Sessions
- **[Authentication Usage Cases](authentication-usage-cases.md)** - Complete guide for:
  - Login (basic, with project, with email)
  - User registration and availability checks
  - Session management (validate, refresh, logout)
  - Project switching
  - Multi-project workflows

### User Management
- **[Users Usage Cases](users-usage-cases.md)** - Complete guide for:
  - User profile (view and update)
  - Access summary (hierarchical view)
  - Admin operations (status, password reset, delete)
  - User search and listing with filters

### Groups Management
- **[Groups Usage Cases](groups-usage-cases.md)** - Complete guide for:
  - User Groups (organizing users and controlling project access)
  - Project Groups (grouping related projects together)
  - Permission Groups (defining reusable permission sets)
  - Groups-of-Groups Architecture (how they all work together)

### Project Management
- **[Project Usage Cases](projects-usage-cases.md)** - Complete guide for:
  - Creating and managing projects
  - Setting up team access through the groups architecture
  - Onboarding/offboarding workflows
  - Multi-project team scenarios
  - Troubleshooting access issues

### Permission Management
- **[Permissions Usage Cases](permissions-usage-cases.md)** - Complete guide for:
  - Permission Groups (creating and managing permission templates)
  - Permissions (individual permission management)
  - Roles (job function-based permission assignment)
  - User Group assignments (team-wide permissions)
  - Direct User assignments (individual overrides)
  - Current User queries (checking your own permissions)

### Admin & System Operations
- **[Admin Usage Cases](admin-usage-cases.md)** - Complete guide for:
  - Dashboard statistics and system overview
  - Activity monitoring and filtering
  - System health checks and metrics
  - Cache management (stats, clear, invalidate)
  - Bulk operations (update, delete, assign)

---

## 🗂️ Complete API Endpoint Reference

### Authentication (`/auth`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/auth/login` | POST | User login |
| `/auth/register` | POST | New user registration |
| `/auth/validate` | GET | Validate current session |
| `/auth/logout` | POST | End session |
| `/auth/refresh` | POST | Refresh token |
| `/auth/switch-project` | POST | Switch project context |
| `/auth/check-availability` | POST | Check username/email availability |

### Users (`/users`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/users/profile` | GET | Get current user profile |
| `/users/profile` | PUT | Update current user profile |
| `/users/access-summary` | GET | Get hierarchical access summary |
| `/users/list` | GET | List users (admin) |
| `/users/search/query` | GET | Search users (admin) |
| `/users/{user_hash}` | GET | Get user details |
| `/users/{user_hash}` | PUT | Update user details (admin) |
| `/users/{user_hash}/type` | PATCH | Change user type (root only) |
| `/users/{user_hash}/status` | PUT | Update user status |
| `/users/{user_hash}/reset-password` | POST | Reset user password (admin) |
| `/users/{user_hash}` | DELETE | Delete user (admin) |

### User Types (`/user-types`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/user-types/root` | POST | Create ROOT user (root only) |
| `/user-types/admin` | POST | Create ADMIN user (root only) |
| `/user-types/{user_hash}/info` | GET | Get user type info |
| `/user-types/{user_hash}/type` | PUT | Update user type (root only) |
| `/user-types/users/{type}` | GET | List users by type |
| `/user-types/stats` | GET | User type statistics |
| `/user-types/admin/{user_hash}/projects` | GET | Get admin user's projects |
| `/user-types/admin/{user_hash}/projects` | PUT | Update admin's projects |
| `/user-types/admin/{user_hash}/projects/add` | POST | Add admin to project |
| `/user-types/admin/{user_hash}/projects/{project_id}` | DELETE | Remove admin from project |

### Projects (`/projects`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/projects` | POST | Create project |
| `/projects` | GET | List projects |
| `/projects/{hash}` | GET | Get project details |
| `/projects/{hash}` | PUT | Update project |
| `/projects/{hash}` | DELETE | Delete project |
| `/projects/{hash}/members` | GET | Get project members |
| `/projects/{hash}/groups` | GET | Get user groups with access (via project groups) |
| `/projects/{hash}/activity` | GET | Get project activity |
| `/projects/{hash}/stats` | GET | Get project statistics |
| `/projects/{hash}/owner` | PUT | Change project owner |
| `/projects/{hash}/archive` | POST | Archive project |

### User Groups (`/admin/user-groups`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/user-groups` | POST | Create user group |
| `/admin/user-groups` | GET | List user groups |
| `/admin/user-groups/{hash}` | GET | Get user group details |
| `/admin/user-groups/{hash}` | PUT | Update user group |
| `/admin/user-groups/{hash}` | DELETE | Delete user group |
| `/admin/user-groups/{hash}/members` | GET | Get group members |
| `/admin/user-groups/{hash}/members` | POST | Add member |
| `/admin/user-groups/{hash}/members/bulk` | POST | Bulk add members |
| `/admin/user-groups/{hash}/members/{user_hash}` | DELETE | Remove member |
| `/admin/user-groups/{hash}/project-groups` | GET | Get assigned project groups |
| `/admin/user-groups/{hash}/project-groups` | POST | Assign project group access |
| `/admin/user-groups/{hash}/project-groups/{pg_hash}` | DELETE | Remove project group access |

### Project Groups (`/admin/project-groups`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/project-groups` | POST | Create project group |
| `/admin/project-groups` | GET | List project groups |
| `/admin/project-groups/{hash}` | GET | Get project group details |
| `/admin/project-groups/{hash}` | PUT | Update project group |
| `/admin/project-groups/{hash}` | DELETE | Delete project group |
| `/admin/project-groups/{hash}/projects` | GET | Get projects in group |
| `/admin/project-groups/{hash}/projects` | POST | Add project to group |
| `/admin/project-groups/{hash}/projects/{proj_hash}` | DELETE | Remove project from group |

### Roles (`/roles`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/roles/roles` | POST | Create role |
| `/roles/roles` | GET | List roles |
| `/roles/roles/{hash}` | GET | Get role details |
| `/roles/roles/{hash}` | PUT | Update role |
| `/roles/roles/{hash}` | DELETE | Delete role |
| `/roles/roles/{hash}/permission-groups/{pg_hash}` | POST | Assign permission group |
| `/roles/roles/{hash}/permission-groups/{pg_hash}` | DELETE | Remove permission group |
| `/roles/users/{user_hash}/role` | GET | Get user's role |
| `/roles/users/{user_hash}/role` | PUT | Assign role to user |
| `/roles/users/{user_hash}/role` | DELETE | Remove role from user |
| `/roles/users/me/role` | GET | Get my role |

### Permission Groups (`/roles/permission-groups`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/roles/permission-groups` | POST | Create permission group |
| `/roles/permission-groups` | GET | List permission groups |
| `/roles/permission-groups/{hash}` | GET | Get permission group details |
| `/roles/permission-groups/{hash}` | PUT | Update permission group |
| `/roles/permission-groups/{hash}` | DELETE | Delete permission group |
| `/roles/permission-groups/{hash}/permissions` | GET | Get permissions in group |
| `/roles/permission-groups/{hash}/permissions/{perm_hash}` | POST | Add permission |
| `/roles/permission-groups/{hash}/permissions/{perm_hash}` | DELETE | Remove permission |

### Permissions (`/roles/permissions`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/roles/permissions` | POST | Create permission |
| `/roles/permissions` | GET | List permissions |
| `/roles/permissions/{hash}` | GET | Get permission details |
| `/roles/permissions/{hash}` | PUT | Update permission |
| `/roles/permissions/{hash}` | DELETE | Delete permission |

### Permissions (`/roles/permissions` & `/permissions`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/roles/permissions` | GET | List all permissions |
| `/roles/permissions/{hash}` | GET | Get permission details |
| `/permissions/users/me/permissions` | GET | Get my permissions |
| `/permissions/users/me/permissions/check/{permission}` | GET | Check specific permission |
| `/permissions/users/me/permission-groups` | GET | Get my direct permission groups |
| `/permissions/users/me/permission-sources` | GET | Get permission sources |
| `/permissions/admin/user-groups/{hash}/permission-groups` | POST | Assign to user group |
| `/permissions/admin/user-groups/{hash}/permission-groups/{pg_hash}` | DELETE | Remove from user group |
| `/permissions/admin/user-groups/{hash}/permission-groups` | GET | List user group's permission groups |
| `/permissions/admin/user-groups/{hash}/permission-groups/bulk` | POST | Bulk assign to user group |
| `/permissions/users/{user_hash}/permission-groups` | POST | Assign to user directly |
| `/permissions/users/{user_hash}/permission-groups/{pg_hash}` | DELETE | Remove from user |
| `/permissions/users/{user_hash}/permission-groups` | GET | List user's permission groups |

### Permission Group Catalog & Queries (`/permissions`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/permissions/projects/{hash}/permission-group-catalog/{pg_hash}` | POST | Add to project catalog |
| `/permissions/projects/{hash}/permission-group-catalog/{pg_hash}` | DELETE | Remove from project catalog |
| `/permissions/projects/{hash}/permission-group-catalog` | GET | Get project's cataloged groups |
| `/permissions/permissions/groups/{pg_hash}/project-catalog` | GET | Get group's cataloged projects |
| `/permissions/permissions/groups/{pg_hash}/user-groups` | GET | Get user groups with permission group |
| `/permissions/permissions/groups/{pg_hash}/users` | GET | Get users with permission group (direct) |

### Role Catalog (`/roles`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/roles/projects/{hash}/catalog/roles/{role_hash}` | POST | Add role to project catalog |
| `/roles/projects/{hash}/catalog/roles/{role_hash}` | DELETE | Remove role from project catalog |
| `/roles/projects/{hash}/catalog/roles` | GET | Get project's cataloged roles |

### System (`/system`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/system/info` | GET | System information (public) |
| `/system/health` | GET | Health check (public) |
| `/system/ping` | GET | Simple ping (public) |
| `/system/cache/stats` | GET | Cache statistics |
| `/system/cache/clear` | POST | Clear all cache (admin) |
| `/system/cache/invalidate/user/{hash}` | POST | Invalidate user cache |
| `/system/cache/invalidate/project/{id}` | POST | Invalidate project cache |

### Admin Dashboard (`/admin`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/dashboard/stats` | GET | Dashboard statistics |
| `/admin/activity` | GET | Activity feed |
| `/admin/activity/types` | GET | Activity type list |
| `/admin/health` | GET | Detailed health check |
| `/admin/users/statistics` | GET | User statistics |
| `/admin/projects/statistics` | GET | Project statistics |
| `/admin/system/overview` | GET | System overview |

### Bulk Operations (`/admin`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/users/bulk-update` | POST | Bulk update users |
| `/admin/users/bulk-delete` | POST | Bulk delete users |
| `/admin/projects/{hash}/bulk-assign-roles` | POST | Bulk assign roles |
| `/admin/user-groups/bulk-assign` | POST | Bulk assign to groups |

---

## 🎯 What You'll Find Here

### ✅ Focus On
- **Real-world scenarios** - "How do I add contractors to a project?"
- **Step-by-step workflows** - Complete procedures from start to finish
- **Common patterns** - Proven approaches for typical situations
- **Troubleshooting** - Solutions to frequent problems
- **Best practices** - Recommended ways to accomplish tasks
- **Complete examples** - Full end-to-end scenarios with commands

### ❌ Not Covered Here
- API endpoint specifications (see `/docs/api/`)
- Architecture details (see `/docs/ARCHITECTURE/`)
- Database schema (see `/schemas/`)
- Technical implementation details

---

## 🚀 Quick Start

### New to the System?

1. **Start with Authentication** - [Authentication Usage Cases](authentication-usage-cases.md)
   - Learn login, registration, and session management

2. **Then Users** - [Users Usage Cases](users-usage-cases.md)
   - Manage profiles and understand user operations

3. **Understand Groups** - [Groups Usage Cases](groups-usage-cases.md)
   - Learn User Groups, Project Groups, and Permission Groups

4. **Then Projects** - [Project Usage Cases](projects-usage-cases.md)
   - Learn how to create projects and manage access

5. **Finally Permissions** - [Permissions Usage Cases](permissions-usage-cases.md)
   - Configure fine-grained permission control

6. **For Admins** - [Admin Usage Cases](admin-usage-cases.md)
   - Dashboard, monitoring, bulk operations

### Common Tasks Quick Links

| Task | Guide |
|------|-------|
| Login/Logout | [Authentication - Login](authentication-usage-cases.md#login) |
| Register new user | [Authentication - Registration](authentication-usage-cases.md#registration) |
| Update my profile | [Users - Profile Operations](users-usage-cases.md#user-profile-operations) |
| View my access | [Users - Access Summary](users-usage-cases.md#access-summary) |
| Change user type | [Users - User Type Management](users-usage-cases.md#user-type-management) |
| Update user details | [Users - Update User Details](users-usage-cases.md#update-user-details-admin) |
| Add user to a project | [Projects - Scenario 1](projects-usage-cases.md#scenario-1-setting-up-a-new-project) |
| Create a new team | [Groups - Creating User Groups](groups-usage-cases.md#creating-a-user-group) |
| Grant team access to projects | [Groups - Groups-of-Groups](groups-usage-cases.md#groups-of-groups-architecture) |
| Set up permissions for a team | [Permissions - User Group Assignments](permissions-usage-cases.md#user-group-assignments) |
| Onboard new employee | [Projects - Scenario 4](projects-usage-cases.md#scenario-4-onboarding-new-employees) |
| Manage contractors | [Projects - Scenario 5](projects-usage-cases.md#scenario-5-managing-contractor-access) |
| Create ROOT/ADMIN users | [Admin - User Type Management](admin-usage-cases.md#user-type-management) |
| Manage admin projects | [Admin - Admin Project Management](admin-usage-cases.md#admin-project-management) |
| Check my permissions | [Permissions - Current User Queries](permissions-usage-cases.md#current-user-queries) |
| View dashboard stats | [Admin - Dashboard](admin-usage-cases.md#admin-dashboard) |
| Bulk update users | [Admin - Bulk Operations](admin-usage-cases.md#bulk-operations) |
| Clear cache | [Admin - Cache Management](admin-usage-cases.md#cache-management) |
| Check system health | [Admin - System Health](admin-usage-cases.md#system-health--metrics) |

---

## 📖 How to Use These Guides

1. **Find your scenario** - Look for a guide that matches your use case
2. **Follow step-by-step** - Each guide provides complete workflows
3. **Adapt to your needs** - Use examples as templates for your situation
4. **Combine patterns** - Mix and match approaches for complex scenarios

---

## 🔗 Related Documentation

- **[API Documentation](/docs/api/)** - Detailed endpoint specifications
- **[Architecture Guides](/docs/ARCHITECTURE/)** - System design and concepts
- **[Database Schema](/schemas/)** - Database structure and relationships

---

## 💡 Tips

### Authentication
All API calls require authentication via Bearer token:
```bash
curl -X GET "http://localhost:8000/endpoint" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Form Data vs JSON
- Most endpoints use **Form data** (`application/x-www-form-urlencoded`)
- Bulk operations use **JSON** (`application/json`)

### Response Format
All responses follow this structure:
```json
{
  "success": true,
  "message": "Operation completed successfully",
  "data": { ... }
}
```

### User Types & Permissions

| User Type | Description | Access Level |
|-----------|-------------|--------------|
| `root` | System administrator | Full system access |
| `admin` | Project administrator | Manage users in their projects |
| `consumer` | Regular user | Self-service profile, project access |

---

## 📋 Document Index

| Document | Description | Key Topics |
|----------|-------------|------------|
| [authentication-usage-cases.md](authentication-usage-cases.md) | Auth & sessions | Login, register, refresh, switch project |
| [users-usage-cases.md](users-usage-cases.md) | User management | Profile, status, search, admin operations |
| [groups-usage-cases.md](groups-usage-cases.md) | Group management | User groups, project groups, permission groups |
| [projects-usage-cases.md](projects-usage-cases.md) | Project management | Create, access, teams, troubleshooting |
| [permissions-usage-cases.md](permissions-usage-cases.md) | Permissions | Roles, permission groups, assignments |
| [admin-usage-cases.md](admin-usage-cases.md) | Admin operations | Dashboard, activity, cache, bulk ops |

---

**Last Updated**: December 2024
**API Version**: 1.0.0
