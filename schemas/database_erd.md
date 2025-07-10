# Database Entity Relationship Diagram

## Overview

This document provides a visual representation of the database schema relationships.

## Complete ERD

```mermaid
erDiagram
    %% Core User and Project Tables
    users {
        int id PK
        varchar user_hash UK
        varchar username UK
        varchar email
        varchar password_hash
        enum user_type
        int assigned_project_id FK
        datetime created_at
        datetime updated_at
        int created_by FK
        boolean is_active
    }
    
    projects {
        int id PK
        varchar project_hash UK
        varchar project_name
        text project_description
        datetime project_created
        datetime updated_at
        int created_by FK
        boolean is_active
    }
    
    user_projects {
        int id PK
        int user_id FK
        int project_id FK
        varchar user_project_hash UK
        datetime granted_at
        int granted_by FK
        datetime revoked_at
        int revoked_by FK
        boolean is_active
    }
    
    admin_project_assignments {
        int id PK
        int user_id FK
        int project_id FK
        datetime assigned_at
        int assigned_by FK
        datetime removed_at
        int removed_by FK
        boolean is_active
    }
    
    %% Group Management Tables
    user_groups {
        int id PK
        varchar group_hash UK
        varchar group_name
        text group_description
        int project_id FK
        json permissions
        datetime created_at
        datetime updated_at
        boolean is_active
    }
    
    user_group_members {
        int id PK
        int user_id FK
        int user_group_id FK
        datetime assigned_at
        int assigned_by FK
        datetime removed_at
        int removed_by FK
        boolean is_active
    }
    
    user_group_projects {
        int id PK
        int user_group_id FK
        int project_id FK
        datetime granted_at
        int granted_by FK
        datetime revoked_at
        int revoked_by FK
        boolean is_active
    }
    
    project_groups {
        int id PK
        varchar group_hash UK
        varchar group_name
        text group_description
        json permissions
        datetime created_at
        datetime updated_at
        boolean is_active
    }
    
    project_group_members {
        int id PK
        int project_id FK
        int project_group_id FK
        datetime assigned_at
        int assigned_by FK
        datetime removed_at
        int removed_by FK
        boolean is_active
    }
    
    %% RBAC Permission Tables
    permissions {
        int id PK
        varchar permission_hash UK
        int project_id FK
        varchar permission_name
        varchar permission_display_name
        text permission_description
        varchar permission_category
        boolean is_system_permission
        datetime created_at
        datetime updated_at
        int created_by FK
        boolean is_active
    }
    
    permission_groups {
        int id PK
        varchar group_hash UK
        int project_id FK
        varchar group_name
        varchar group_display_name
        text group_description
        int group_priority
        boolean is_system_role
        datetime created_at
        datetime updated_at
        int created_by FK
        boolean is_active
    }
    
    permission_group_permissions {
        int id PK
        int permission_group_id FK
        int permission_id FK
        datetime granted_at
        int granted_by FK
        datetime revoked_at
        int revoked_by FK
        boolean is_active
    }
    
    user_project_permission_groups {
        int id PK
        int user_id FK
        int project_id FK
        int permission_group_id FK
        datetime assigned_at
        int assigned_by FK
        datetime removed_at
        int removed_by FK
        boolean is_active
    }
    
    %% Support Tables
    user_sessions {
        int id PK
        int user_project_id FK
        varchar session_token UK
        datetime expires_at
        datetime created_at
        boolean is_active
    }
    
    user_project_groups {
        int id PK
        int user_project_id FK
        int group_id FK
        datetime assigned_at
        int assigned_by FK
        datetime removed_at
        int removed_by FK
        boolean is_active
    }
    
    permission_audit_log {
        int id PK
        varchar action_type
        int project_id FK
        int target_user_id FK
        int permission_id FK
        int permission_group_id FK
        int performed_by FK
        json old_values
        json new_values
        datetime action_timestamp
        varchar ip_address
        text user_agent
        varchar table_name
        int record_id
    }
    
    %% Relationships
    users ||--o{ users : "created_by"
    users ||--o{ projects : "creates"
    users ||--o{ user_projects : "has access to"
    users ||--o{ admin_project_assignments : "admin for"
    users ||--o{ user_group_members : "belongs to"
    users ||--o{ user_project_permission_groups : "has roles"
    
    projects ||--o{ user_projects : "accessed by"
    projects ||--o{ admin_project_assignments : "has admins"
    projects ||--o{ user_groups : "legacy groups"
    projects ||--o{ user_group_projects : "accessible by groups"
    projects ||--o{ project_group_members : "belongs to groups"
    projects ||--o{ permissions : "has permissions"
    projects ||--o{ permission_groups : "has roles"
    
    user_groups ||--o{ user_group_members : "has members"
    user_groups ||--o{ user_group_projects : "can access"
    user_groups ||--o{ user_project_groups : "legacy assignments"
    
    project_groups ||--o{ project_group_members : "has projects"
    
    permissions ||--o{ permission_group_permissions : "assigned to"
    permission_groups ||--o{ permission_group_permissions : "has permissions"
    permission_groups ||--o{ user_project_permission_groups : "assigned to users"
    
    user_projects ||--o{ user_sessions : "has sessions"
    user_projects ||--o{ user_project_groups : "legacy groups"
```

## Key Relationships Explained

### User Type Hierarchy

1. **Root Users**: Have `user_type = 'root'` and no `assigned_project_id`
2. **Admin Users**: Have `user_type = 'admin'` with entries in `admin_project_assignments`
3. **Consumer Users**: Have `user_type = 'consumer'` and access projects through `user_projects`

### Permission Flow

```
User → User Groups → Projects (via user_group_projects)
User → Projects (via user_projects) → Permission Groups → Permissions
Admin User → Projects (via admin_project_assignments) → Full Admin Access
Root User → All Projects → Full Global Access
```

### RBAC Implementation

1. **Permissions** are defined per project
2. **Permission Groups** (roles) collect permissions
3. **Users** are assigned to permission groups within projects
4. All changes are tracked in **permission_audit_log**

## Table Categories

### Core Tables
- `users`: All user accounts
- `projects`: All applications/systems
- `user_projects`: Consumer user access to projects
- `admin_project_assignments`: Admin user project assignments

### Group Management
- `user_groups`: Global user organization
- `project_groups`: Project-level permission groups
- Various linking tables for memberships

### RBAC System
- `permissions`: Available permissions
- `permission_groups`: Role definitions
- `permission_group_permissions`: Role-permission mappings
- `user_project_permission_groups`: User-role assignments

### Support Tables
- `user_sessions`: Active sessions
- `permission_audit_log`: Complete audit trail
- `user_project_groups`: Legacy compatibility 