# Database Schema - Magic Auth System

**Enhanced 3-Tier User Type Multi-Project Authentication System**

---

## 📁 Folder Structure

```
schemas/
├── tables/              # All table definitions and initialization
│   ├── 01_create_database.sql
│   ├── 02_create_tables.sql
│   ├── 03_create_indexes.sql
│   ├── 04_add_constraints.sql
│   ├── 05_initialize_data.sql
│   └── 06_create_views.sql
│
├── stored_procedures/   # All stored procedures organized by domain
│   ├── 01_user_management.sql
│   ├── 02_user_groups.sql
│   ├── 03_projects.sql
│   ├── 04_project_groups.sql
│   ├── 05_global_roles.sql
│   ├── 06_permission_assignments.sql
│   ├── 07_sessions_analytics.sql
│   ├── 08_admin_operations.sql
│   └── 09_system_maintenance.sql
│
└── README.md           # This file
```

---

## 🚀 Quick Start

### Using Python Scripts (Recommended)

```bash
# Create database from scratch
python scripts/create_database.py

# Recreate database (drops and recreates everything)
python scripts/recreate_database.py
```

### Manual Setup (Execute in Order)

```bash
# 1. TABLES - Create database structure
mysql -u root -p < schemas/tables/01_create_database.sql
mysql -u root -p < schemas/tables/02_create_tables.sql
mysql -u root -p < schemas/tables/03_create_indexes.sql
mysql -u root -p < schemas/tables/04_add_constraints.sql
mysql -u root -p < schemas/tables/05_initialize_data.sql
mysql -u root -p < schemas/tables/06_create_views.sql

# 2. STORED PROCEDURES - Create all procedures
mysql -u root -p < schemas/stored_procedures/01_user_management.sql
mysql -u root -p < schemas/stored_procedures/02_user_groups.sql
mysql -u root -p < schemas/stored_procedures/03_projects.sql
mysql -u root -p < schemas/stored_procedures/04_project_groups.sql
mysql -u root -p < schemas/stored_procedures/05_global_roles.sql
mysql -u root -p < schemas/stored_procedures/06_permission_assignments.sql
mysql -u root -p < schemas/stored_procedures/07_sessions_analytics.sql
mysql -u root -p < schemas/stored_procedures/08_admin_operations.sql
mysql -u root -p < schemas/stored_procedures/09_system_maintenance.sql
```

---

## 📚 Tables Folder (`tables/`)

Contains all table definitions, indexes, constraints, and initialization data.

| File | Description | Details |
|------|-------------|---------|
| `01_create_database.sql` | Creates `magic_auth` database | Database setup with UTF-8 collation |
| `02_create_tables.sql` | All table definitions | 39 tables (users, projects, groups, roles, permissions, etc.) |
| `03_create_indexes.sql` | Performance indexes | 80+ performance indexes |
| `04_add_constraints.sql` | Foreign keys and triggers | 30+ constraints, 12 triggers |
| `05_initialize_data.sql` | Initial data | Root user + 40 activity types |
| `06_create_views.sql` | Performance views | 6 optimization views |

### Key Tables Overview

#### Core Tables
- **users** - User accounts (root, admin, consumer)
- **projects** - Applications/systems in multi-project architecture
- **user_groups** - Global user groups spanning projects
- **user_group_members** - User-to-group assignments
- **user_group_projects** - Group-to-project access grants

#### Global Role System
- **roles** - Global roles (one per user)
- **global_permissions** - Permission definitions
- **global_permission_groups** - Reusable permission containers
- **role_permission_groups** - Role-to-permission-group links
- **global_permission_group_permissions** - Permission-group contents

#### Permission Assignment System
- **user_group_permission_groups** - Assign permission groups to user groups
- **user_permission_groups** - Direct permission group assignments to users

#### Session & Activity
- **user_sessions** - Session management
- **activity_catalog** - Activity type definitions
- **activity_logs** - User and system activity tracking
- **permission_audit_log** - Audit trail for permission changes

#### Supporting Tables
- **project_groups** - Permission group sets for projects
- **project_group_members** - Project-to-group memberships
- **permission_cache** - Performance caching
- **bulk_operations_log** - Bulk operation tracking

---

## 🔧 Stored Procedures Folder (`stored_procedures/`)

Contains 112+ stored procedures organized by functional domain.

| File | Procedures | Description |
|------|-----------|-------------|
| `01_user_management.sql` | 21 | User auth, CRUD, type management, admin access |
| `02_user_groups.sql` | 26 | Group CRUD, membership, project access |
| `03_projects.sql` | 12 | Project CRUD, stats, member management |
| `04_project_groups.sql` | 12 | Project group CRUD and membership |
| `05_global_roles.sql` | 19 | Role, permission, and permission group management |
| `06_permission_assignments.sql` | 11 | User/group permission assignments |
| `07_sessions_analytics.sql` | 5 | Activity logging and statistics |
| `08_admin_operations.sql` | 1 | Admin operations and audit logs |
| `09_system_maintenance.sql` | 5 | Cleanup, health checks |

### Procedure Categories

#### User Management (01)
- **Authentication**: `sp_user_login`
- **CRUD**: `sp_get_user_by_*`, `sp_create_*_user`, `sp_update_user`, `sp_delete_user`
- **Listing**: `sp_list_users`, `sp_count_users`, `sp_search_users`
- **Status**: `sp_get_user_status`, `sp_set_user_status`
- **Admin**: `sp_get_admin_assigned_projects`, `sp_check_admin_multi_project_access`

#### User Groups (02)
- **Group Management**: `sp_create_user_group`, `sp_get_user_group_by_*`, `sp_update_user_group`
- **Membership**: `sp_assign_user_to_group`, `sp_remove_user_from_group`, `sp_get_users_in_group`
- **Project Access**: `sp_grant_group_project_access`, `sp_revoke_group_project_access`
- **Utilities**: `sp_find_default_user_group_for_project`, `sp_find_admin_group_for_project`

#### Projects (03)
- **CRUD**: `sp_create_project`, `sp_get_project_by_*`, `sp_update_project`, `sp_delete_project`
- **Listing**: `sp_list_all_projects`, `sp_search_projects`, `sp_count_projects`
- **Stats**: `sp_get_project_stats`, `sp_get_project_statistics`, `sp_get_project_members`

#### Global Roles (05)
- **Roles**: `sp_global_create_role`, `sp_global_get_role_by_hash`, `sp_global_list_roles`
- **Permission Groups**: `sp_global_create_permission_group`, `sp_global_list_permission_groups`
- **Permissions**: `sp_global_create_permission`, `sp_global_list_permissions`
- **Assignments**: `sp_global_assign_permission_group_to_role`, `sp_global_assign_role_to_user`
- **Checking**: `sp_global_check_user_has_permission`, `sp_global_get_user_permissions`

#### Permission Assignments (06)
- **User Group Assignments**: `sp_assign_permission_group_to_user_group`, `sp_get_user_group_permission_groups`
- **Direct User Assignments**: `sp_assign_permission_group_to_user`, `sp_get_user_permission_groups`
- **Resolution**: `sp_get_user_all_permissions`, `sp_check_user_has_permission_extended`

#### System Maintenance (09)
- **Cleanup**: `sp_cleanup_expired_sessions`, `sp_cleanup_permission_cache`, `sp_cleanup_orphaned_records`
- **Health**: `sp_system_health_check`, `sp_check_database_health`

---

## 📊 Performance Views

Created by `tables/06_create_views.sql`:

| View | Purpose |
|------|---------|
| `v_user_project_access` | User project access through groups (includes root access) |
| `v_user_project_access_summary` | User access summary with group counts |
| `v_active_user_sessions` | Active sessions with group context |
| `user_summary_view` | Enhanced user summary for dashboards |
| `project_health_view` | Project monitoring and activity levels |
| `v_user_group_hierarchy` | Recursive hierarchical group structure |

---

## 🏗️ Database Architecture

### User Type System (3-Tier)
1. **Root** - Super admin, access to everything
2. **Admin** - Project administrators, group-based access
3. **Consumer** - Regular users, group-based access

### Access Control Model
- **NO direct project assignments** - All access through groups
- Users → User Groups → Projects
- Users get permissions through:
  1. Global Role (one per user)
  2. User Group Permission Groups
  3. Direct Permission Group Assignments

### Permission Flow
```
User → Role → Permission Groups → Permissions
User → User Groups → Permission Groups → Permissions
User → Direct Permission Groups → Permissions
```

---

## 🔑 Initial Credentials

After running `05_initialize_data.sql`:

```
Username: root
Password: admin123
Email: root@system.local
Type: root
```

**⚠️ Change this password immediately in production!**

---

## 📈 Performance Tips

1. **Indexes**: All critical indexes are created by `03_create_indexes.sql`
2. **Views**: Use performance views for complex queries
3. **Caching**: `permission_cache` table for expensive permission checks
4. **Maintenance**: Run `sp_cleanup_*` procedures regularly
5. **Health Checks**: Use `sp_system_health_check()` to monitor issues

---

## 🧪 Testing

### Check Database Setup
```sql
-- Check tables
SELECT COUNT(*) FROM information_schema.tables 
WHERE table_schema = 'magic_auth';

-- Check stored procedures
SELECT COUNT(*) FROM information_schema.routines 
WHERE routine_schema = 'magic_auth' AND routine_type = 'PROCEDURE';

-- Check views
SELECT COUNT(*) FROM information_schema.views 
WHERE table_schema = 'magic_auth';

-- System health check
CALL sp_system_health_check();
```

---

## 🛠️ Maintenance

### Regular Tasks
- **Daily**: Check `sp_system_health_check()`
- **Weekly**: Run `sp_cleanup_expired_sessions()`, `sp_cleanup_permission_cache()`
- **Monthly**: Run `sp_cleanup_orphaned_records()`, review audit logs
- **Quarterly**: Review and optimize indexes, update statistics

### Monitoring
```sql
-- Check system health
CALL sp_system_health_check();

-- Check recent activity
CALL sp_get_activity_logs(100, 0, NULL, NULL, NULL, 7);

-- Check session count
SELECT COUNT(*) FROM user_sessions WHERE is_active = 1 AND expires_at > NOW();

-- Check user statistics
SELECT user_type, COUNT(*) as count FROM users WHERE is_active = 1 GROUP BY user_type;
```

---

## 📝 Additional Documentation

- **Architecture**: See `docs/ARCHITECTURE/` folder
- **API Endpoints**: See `docs/api/` folder
- **Error Handling**: See `docs/ERROR_HANDLER/` folder
- **Usage Examples**: See `docs/USAGE/` folder

---

## 📞 Support

For issues, questions, or contributions:
- Check the documentation in `docs/` folder
- Contact the development team

---

**Last Updated**: October 26, 2025  
**Version**: 3.0 (Clean Structure)  
**Database**: MySQL 8.0+
