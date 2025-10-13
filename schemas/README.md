# Enhanced 3-Tier User Type Multi-Project Authentication Database Schema

This folder contains the MySQL database schema for the enhanced authentication system with 3-tier user types:

- **ROOT USERS**: Super administrators with unrestricted global access
- **ADMIN USERS**: Project-specific administrators limited to assigned projects
- **CONSUMER USERS**: End users with RBAC-based permissions through groups

## Files Overview

### Core Schema Files (Execute in Order)

1. **01_create_database.sql** - Creates the database and sets proper character encoding
2. **02_create_tables.sql** - Creates all tables (Rev1 + Rev2 permission assignment tables)
3. **03_create_index.sql** - Creates performance indexes for all tables
4. **04_add_constraints.sql** - Adds foreign key constraints, relationships, and triggers
5. **05_initialize_data.sql** - Inserts initial data including default users and permissions
6. **06_performance_optimization.sql** - Additional performance optimizations
7. **07_stored_procedures.sql** - Core stored procedures for application logic
8. **08_permission_assignment_procedures.sql** - Rev2 permission assignment stored procedures

### Deprecated Files (Do Not Use)

- ~~**08_permission_assignments.sql**~~ - DEPRECATED: Content moved to 02, 03, 04
- ~~**09_permission_assignment_procedures.sql**~~ - DEPRECATED: Renamed to 08_permission_assignment_procedures.sql

## Installation Instructions

### Method 1: Sequential Execution (Recommended)

Execute each SQL file in order:

```bash
# Create database
mysql -u root -p < 01_create_database.sql

# Create tables (includes Rev2 permission assignment tables)
mysql -u root -p magic_auth < 02_create_tables.sql

# Create indexes
mysql -u root -p magic_auth < 03_create_index.sql

# Add constraints and triggers
mysql -u root -p magic_auth < 04_add_constraints.sql

# Initialize data (optional but recommended)
mysql -u root -p magic_auth < 05_initialize_data.sql

# Add performance optimizations (recommended)
mysql -u root -p magic_auth < 06_performance_optimization.sql

# Add core stored procedures
mysql -u root -p magic_auth < 07_stored_procedures.sql

# Add Rev2 permission assignment procedures
mysql -u root -p magic_auth < 08_permission_assignment_procedures.sql
```

### Method 2: Single Command

Execute all files at once:

```bash
# Concatenate and execute all files
cat 01_create_database.sql \
    02_create_tables.sql \
    03_create_index.sql \
    04_add_constraints.sql \
    05_initialize_data.sql \
    06_performance_optimization.sql \
    07_stored_procedures.sql \
    08_permission_assignment_procedures.sql \
    | mysql -u root -p
```

### Method 3: Using MySQL Workbench or phpMyAdmin

1. Open your MySQL client
2. Execute each SQL file in numerical order
3. Verify successful execution after each step

## Default Users

After running the initialization script, you'll have these users:

| Username | Password | User Type | Description |
|----------|----------|-----------|-------------|
| root | admin123 | Root | Super administrator with global access |
| admin | admin123 | Admin | Project administrator for Default Project |
| user | user123 | Consumer | Regular user with Contributor role |

## Database Tables

### Core Tables

1. **users** - User accounts with 3-tier user types
2. **projects** - Applications/systems in the multi-project architecture
3. **user_projects** - Links consumer users to projects
4. **admin_project_assignments** - Multi-project assignments for admin users

### Permission System Tables

1. **permissions** - Project-specific permission definitions
2. **permission_groups** - Role definitions (collections of permissions)
3. **permission_group_permissions** - Links permissions to roles
4. **user_project_permission_groups** - User role assignments per project

### Group Management Tables

1. **user_groups** - Global user groups for organizing users
2. **user_group_members** - User membership in groups
3. **user_group_projects** - Project access for user groups
4. **project_groups** - Permission groups at project level
5. **project_group_members** - Project membership in groups

### Support Tables

1. **user_sessions** - Session management
2. **permission_audit_log** - Audit trail for all permission changes
3. **user_project_groups** - Legacy table for backward compatibility

## Key Features

### User Type Hierarchy

1. **Root Users**
   - Unrestricted access to all projects and features
   - Can create other root, admin, and consumer users
   - No project assignment needed

2. **Admin Users**
   - Limited to assigned projects only
   - Can manage users, roles, and permissions within their projects
   - Support for multi-project assignments

3. **Consumer Users**
   - Access controlled through RBAC permissions
   - Must be granted project access explicitly
   - Permissions assigned through roles

### RBAC Implementation

- Each project has its own permission catalog
- Roles are project-specific
- Users are assigned roles within projects
- Complete audit trail for all permission changes

### Multi-Project Architecture

- Projects are isolated from each other
- Users can have different roles in different projects
- Admin users can be assigned to multiple projects
- Consumer users access projects through group memberships

### Rev2: Permission Assignment System (NEW)

The Rev2 system adds flexible permission group assignments:

1. **User Group Assignments (Primary)**
   - Assign permission groups to entire user groups
   - All group members inherit the permissions
   - Scalable for organizational management

2. **Direct User Assignments (Secondary)**
   - Assign permission groups directly to individual users
   - For special cases and overrides
   - Documented with notes field

3. **Permission Group Project Catalog (Metadata)**
   - Optional metadata for UI organization
   - Suggests which permission groups are relevant per project
   - NOT used in authorization logic

**Tables Added:**
- `user_group_permission_groups` - Links user groups to permission groups
- `user_permission_groups` - Links users directly to permission groups
- `permission_group_project_catalog` - Organizational metadata (UI only)

**See:** `/docs/rev2/` for complete Rev2 documentation

## Troubleshooting

### Common Issues

1. **Foreign key constraint errors**
   - Ensure you're running the scripts in the correct order
   - Check that referenced tables exist before adding constraints

2. **Duplicate key errors**
   - The database may already exist with data
   - Drop the database first: `DROP DATABASE IF EXISTS magic_auth;`

3. **Character set issues**
   - Ensure your MySQL server supports utf8mb4
   - Check server configuration if you get charset errors

### Verification Queries

Check if installation was successful:

```sql
-- Check user types
SELECT user_type, COUNT(*) FROM users GROUP BY user_type;

-- Check projects
SELECT * FROM projects;

-- Check permissions
SELECT COUNT(*) as permission_count FROM permissions;

-- Check roles
SELECT * FROM permission_groups ORDER BY group_priority DESC;
```

## Customization

### Adding New Permissions

```sql
INSERT INTO permissions (permission_hash, project_id, permission_name, permission_display_name, 
                        permission_description, permission_category, created_by)
VALUES (CONCAT('PERM-', UUID()), @project_id, 'custom_permission', 'Custom Permission', 
        'Description of the permission', 'custom', @user_id);
```

### Creating New Roles

```sql
INSERT INTO permission_groups (group_hash, project_id, group_name, group_display_name, 
                              group_description, group_priority, created_by)
VALUES (CONCAT('ROLE-', UUID()), @project_id, 'custom_role', 'Custom Role', 
        'Description of the role', 50, @user_id);
```

### Password Hashing

The system uses SHA256 for password hashing. To generate a password hash:

```sql
SELECT UPPER(SHA2('your_password', 256));
```

## Security Notes

1. Change default passwords immediately after installation
2. Use strong passwords for all accounts
3. Regularly audit permission assignments
4. Enable MySQL query logging for security monitoring
5. Implement proper backup procedures

## Support

For issues or questions about the schema:
1. Check the SQL comments for detailed explanations
2. Review the Models.py file for data structure definitions
3. Examine the db module files for usage examples 