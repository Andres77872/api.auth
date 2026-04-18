# 🔐 Group-Based Multi-Project Authentication System

A comprehensive authentication system with **hierarchical group-based access control** and **complete RBAC** capabilities for enterprise-grade access control.

## 🏗️ Groups-of-Groups Architecture

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

## 🌟 User Types

| Type | Description | Access Level |
|------|-------------|--------------|
| 🔴 `root` | System administrators | Full global access |
| 🟡 `admin` | Project administrators | Manage users in their projects |
| 🟢 `consumer` | Regular users | Self-service + project access via groups |

## ✨ Features

### 🔐 Authentication & Sessions
- JWT-based session management with HTTP-only cookies
- Multi-project login and project switching
- Session validation and token refresh
- Username/email availability checking

### 👥 Hierarchical Group Management
- **User Groups**: Organize users globally
- **Project Groups**: Container for related projects
- **Permission Groups**: Reusable permission templates
- Groups-of-groups architecture for scalable access control

### 🎭 Complete RBAC Management
- **Global Roles**: Job function-based permission assignment
- **Permission Groups**: Create reusable permission templates
- **Permissions**: Granular individual permissions
- Real-time permission validation

### 📁 Project Management
- Project CRUD with group-based access
- Project members and statistics
- Activity tracking and audit logs
- Archive functionality

### 🛡️ Enterprise Security
- Multi-layer security (transport, auth, authorization, data isolation)
- UUID-based identification (`usr-{UUID4}`, `proj-{UUID4}`)
- Comprehensive audit trails
- Redis-based session caching

### 🔧 Admin Features
- Dashboard statistics and monitoring
- Activity feed with filtering
- System health checks
- Cache management
- Bulk operations (update, delete, assign)

## 🚀 Quick Start

```bash
# 1. Clone and install
git clone <repository-url>
cd api.auth
pip install -r requirements.txt

# 2. Set environment variables
export DB_MYSQL_PASSWORD=your_mysql_password
export DB_REDIS_PASSWORD=your_redis_password

# 3. Initialize database
python scripts/recreate_database.py

# 4. Start the server
python -m uvicorn src.main:app --reload

# 5. Test the system
curl http://localhost:8000/system/ping
```

## 📡 Complete API Reference

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
| `/users/list` | GET | List users with filters (admin) |
| `/users/search/query` | GET | Search users (admin) |
| `/users/{user_hash}` | GET | Get user details |
| `/users/{user_hash}/status` | PUT | Update user status |
| `/users/{user_hash}/reset-password` | POST | Reset password (admin) |
| `/users/{user_hash}` | DELETE | Delete user (admin) |

### Projects (`/projects`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/projects` | POST | Create project |
| `/projects` | GET | List projects |
| `/projects/{hash}` | GET | Get project details |
| `/projects/{hash}` | PUT | Update project |
| `/projects/{hash}` | DELETE | Delete project |
| `/projects/{hash}/members` | GET | Get project members |
| `/projects/{hash}/groups` | GET | Get project groups |
| `/projects/{hash}/activity` | GET | Get project activity |
| `/projects/{hash}/stats` | GET | Get project statistics |
| `/projects/{hash}/owner` | PATCH | Change project owner (**currently 501**) |
| `/projects/{hash}/archive` | PATCH | Archive/unarchive project (**currently 501**) |

### User Groups (`/admin/user-groups`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/user-groups` | POST | Create user group |
| `/admin/user-groups` | GET | List user groups |
| `/admin/user-groups/{hash}` | GET | Get group details |
| `/admin/user-groups/{hash}` | PUT | Update group |
| `/admin/user-groups/{hash}` | DELETE | Delete group |
| `/admin/user-groups/{hash}/members` | GET | Get members |
| `/admin/user-groups/{hash}/members` | POST | Add member |
| `/admin/user-groups/{hash}/members/bulk` | POST | Bulk add members |
| `/admin/user-groups/{hash}/members/{user}` | DELETE | Remove member |
| `/admin/user-groups/{hash}/project-groups` | GET | Get project group access |
| `/admin/user-groups/{hash}/project-groups` | POST | Grant project group access |
| `/admin/user-groups/{hash}/project-groups/{pg}` | DELETE | Revoke access |

### Project Groups (`/admin/project-groups`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/admin/project-groups` | POST | Create project group |
| `/admin/project-groups` | GET | List project groups |
| `/admin/project-groups/{hash}` | GET | Get group details |
| `/admin/project-groups/{hash}` | PUT | Update group |
| `/admin/project-groups/{hash}` | DELETE | Delete group |
| `/admin/project-groups/{hash}/projects` | GET | Get projects in group |
| `/admin/project-groups/{hash}/projects` | POST | Add project |
| `/admin/project-groups/{hash}/projects/{proj}` | DELETE | Remove project |

### Roles (`/roles`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/roles/roles` | POST | Create role |
| `/roles/roles` | GET | List roles |
| `/roles/roles/{hash}` | GET | Get role details |
| `/roles/roles/{hash}` | PUT | Update role |
| `/roles/roles/{hash}` | DELETE | Delete role |
| `/roles/roles/{hash}/permission-groups/{pg}` | POST | Add permission group |
| `/roles/roles/{hash}/permission-groups/{pg}` | DELETE | Remove permission group |
| `/roles/users/{user_hash}/role` | GET | Get user's role |
| `/roles/users/{user_hash}/role` | POST | Assign role |
| `/roles/users/me/role` | GET | Get my role |

### Permission Groups (`/roles/permission-groups`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/roles/permission-groups` | POST | Create permission group |
| `/roles/permission-groups` | GET | List permission groups |
| `/roles/permission-groups/{hash}` | GET | Get group details |
| `/roles/permission-groups/{hash}` | PUT | Update group |
| `/roles/permission-groups/{hash}` | DELETE | Delete group |
| `/roles/permission-groups/{hash}/permissions` | GET | Get permissions |
| `/roles/permission-groups/{hash}/permissions` | POST | Add permission |
| `/roles/permission-groups/{hash}/permissions/{p}` | DELETE | Remove permission |

### Permissions (`/permissions`)
| Endpoint | Method | Description |
|----------|--------|-------------|
| `/roles/permissions` | GET | List all permissions |
| `/permissions/users/me/permissions` | GET | Get my permissions |
| `/permissions/users/me/permissions/check` | POST | Check specific permission |
| `/permissions/users/me/permission-groups` | GET | Get my direct permission groups |
| `/permissions/users/me/sources` | GET | Get permission sources |
| `/permissions/admin/user-groups/{hash}/permission-groups` | POST | Assign to user group |
| `/permissions/users/{user}/permission-groups` | POST | Assign to user |

### System (`/system`)
| Endpoint | Method | Auth | Description |
|----------|--------|------|-------------|
| `/system/info` | GET | No | System information |
| `/system/health` | GET | No | Health check |
| `/system/ping` | GET | No | Simple ping |
| `/system/cache/stats` | GET | Yes | Cache statistics |
| `/system/cache/clear` | POST | Admin | Clear all cache |
| `/system/cache/invalidate/user/{hash}` | POST | Admin | Invalidate user cache |
| `/system/cache/invalidate/project/{id}` | POST | Admin | Invalidate project cache |

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

## 💡 API Usage

### Authentication
```bash
# Login
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john_doe&password=SecurePass123!"

# Use token for authenticated requests
curl -X GET "http://localhost:8000/users/profile" \
  -H "Authorization: Bearer YOUR_TOKEN"
```

### Request Format
- Most endpoints use **Form data** (`application/x-www-form-urlencoded`)
- Bulk operations use **JSON** (`application/json`)

### Response Format
```json
{
  "success": true,
  "message": "Operation completed successfully",
  "data": { ... }
}
```

## 📚 Documentation

### Usage Guides
| Document | Description |
|----------|-------------|
| [Authentication](docs/USAGE/authentication-usage-cases.md) | Login, sessions, project switching |
| [Users](docs/USAGE/users-usage-cases.md) | Profile, admin operations |
| [Groups](docs/USAGE/groups/README.md) | User groups, project groups, flows, troubleshooting |
| [Projects](docs/USAGE/projects/README.md) | Project management suite |
| [Permissions](docs/USAGE/permissions-usage-cases.md) | Roles, permissions |
| [Admin](docs/USAGE/admin-usage-cases.md) | Dashboard, bulk ops, cache |

### Architecture
- [Architecture Overview](docs/ARCHITECTURE/README.md)
- [Database Schema](schemas/README.md)

## 🐳 Docker Deployment

```bash
docker-compose up -d
```

```yaml
services:
  api-auth:
    environment:
      - DB_MYSQL_PASSWORD=secure_password
      - DB_REDIS_PASSWORD=secure_password
      - JWT_SECRET_KEY=your_jwt_secret
```

## 🔧 Configuration

```bash
# Database
DB_MYSQL_PASSWORD=your_mysql_password
DB_HOST=192.168.1.90
DB_NAME=magic-auth

# JWT
JWT_SECRET_KEY=your_secure_jwt_secret_key
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_HOURS=72

# Redis
DB_REDIS_PASSWORD=your_redis_password
REDIS_HOST=192.168.1.90
REDIS_PORT=6379
```

## 📊 Performance

- **Concurrent Users**: 1000+ simultaneous sessions
- **Response Time**: <50ms for authentication operations
- **Cache Hit Rate**: >95% with Redis optimization
- **Projects**: Unlimited with group-based access

## 🆘 Troubleshooting

| Problem | Solution |
|---------|----------|
| Session expired | Re-authenticate via `/auth/login` |
| Access denied | Check user group membership and project group access |
| Permission denied | Verify permission groups assigned to user/group |
| Database errors | Verify MySQL connection and schema |
| Cache issues | Use `/system/cache/clear` to reset |

### Quick Diagnostics
```bash
# Test system
curl http://localhost:8000/system/health

# Test database
python -c "from src.Util.db import get_connection; print('✓ DB Connected')"

# Test Redis
python -c "from src.Util.db_config import redis_client; redis_client.ping(); print('✓ Redis OK')"
```

## 👨‍💻 Author

**Andrés**
- Website: https://arizmendi.io
- Email: andres@arz.ai

---

**🚀 Ready to start?** Check the [Usage Documentation](docs/USAGE/README.md) for complete guides and examples.
