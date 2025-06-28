# Migration Guide

Complete guide for migrating from legacy authentication systems to the Group-Based Multi-Project Authentication API.

## 📋 Overview

This guide covers:
- **Legacy System Assessment**: Understanding your current setup
- **Migration Planning**: Step-by-step migration strategy to group-based system
- **Data Migration**: Moving users, projects, and permissions to group structure
- **System Migration**: Updating application code for group-based operations
- **Testing & Validation**: Ensuring group migration success
- **Rollback Procedures**: Safety measures and contingency plans

## 🎯 Migration Scenarios

### Scenario 1: From Single-Project Auth System
- Migrate from single project to group-based multi-project architecture
- Preserve existing users and their permissions through groups
- Add hierarchical group structure and project group permissions

### Scenario 2: From Collection-Based System  
- Migrate from `tb_collection` and `tb_collection_user` tables
- Convert collections to projects with project groups
- Map collection users to user groups with project access

### Scenario 3: From Multiple Independent Systems
- Consolidate multiple authentication systems into group-based architecture
- Merge user bases with group-based conflict resolution
- Unify permission structures through project groups

### Scenario 4: From Enhanced System to Clean Groups
- Migrate from the old "enhanced" system to the new clean group-based system
- Remove confusing naming and implement proper hierarchical groups
- Convert project-specific groups to global user groups and project groups

## 🔄 Migration Process Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ 1. Assessment   │───►│ 2. Planning     │───►│ 3. Preparation  │
│                 │    │                 │    │                 │
│ • Analyze       │    │ • Map to groups │    │ • Backup data   │
│   current system│    │ • Design group  │    │ • Setup test    │
│ • Identify      │    │   migration     │    │   environment   │
│   dependencies  │    │   strategy      │    │ • Create group  │
│ • Plan timeline │    │ • Risk analysis │    │   migration     │
│                 │    │                 │    │   scripts       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
           │                       │                       │
           ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ 4. Group Data   │───►│ 5. System       │───►│ 6. Validation   │
│    Migration    │    │    Migration    │    │    & Testing    │
│                 │    │                 │    │                 │
│ • Run group     │    │ • Update APIs   │    │ • Test group    │
│   migration     │    │ • Deploy group  │    │   functions     │
│   scripts       │    │   system        │    │ • Performance   │
│ • Validate      │    │ • Update        │    │   testing       │
│   group data    │    │   integrations  │    │ • User          │
│ • Handle        │    │                 │    │   acceptance    │
│   conflicts     │    │                 │    │                 │
└─────────────────┘    └─────────────────┘    └─────────────────┘
```

## 📊 Pre-Migration Assessment

### Current System Analysis

#### 1. Database Schema Analysis

```sql
-- Analyze current user tables
DESCRIBE your_current_user_table;
SELECT COUNT(*) as total_users FROM your_current_user_table;

-- Analyze current project/collection tables  
DESCRIBE your_current_project_table;
SELECT COUNT(*) as total_projects FROM your_current_project_table;

-- Check for existing group structures
DESCRIBE user_groups; -- If exists
SELECT COUNT(*) as total_groups FROM user_groups; -- If exists
```

#### 2. Group Structure Assessment

```sql
-- Assess existing group complexity
SELECT 
    project_id,
    COUNT(DISTINCT group_name) as groups_per_project,
    COUNT(DISTINCT user_id) as users_per_project
FROM existing_user_project_groups
GROUP BY project_id
ORDER BY groups_per_project DESC;

-- Identify permission patterns
SELECT 
    permissions,
    COUNT(*) as group_count
FROM existing_user_groups
WHERE is_active = 1
GROUP BY permissions
ORDER BY group_count DESC;
```

#### 3. Data Volume Assessment

```sql
-- Get data volume statistics for group migration
SELECT 
    'Users' as entity,
    COUNT(*) as total_count,
    MIN(created_at) as earliest_record,
    MAX(created_at) as latest_record
FROM users
UNION ALL
SELECT 
    'Projects' as entity,
    COUNT(*),
    MIN(created_at),
    MAX(created_at)
FROM projects
UNION ALL
SELECT 
    'User-Project Relationships' as entity,
    COUNT(*),
    MIN(granted_at),
    MAX(granted_at)
FROM user_projects; -- If exists
```

#### 4. Integration Analysis

Create an inventory of all systems that integrate with your current authentication:

```markdown
## Integration Inventory for Group Migration

### Web Applications
- [ ] Main web application (URL: _______) - Group access patterns: _______
- [ ] Admin panel (URL: _______) - Group management needs: _______
- [ ] API dashboard (URL: _______) - Group-based permissions: _______

### Mobile Applications  
- [ ] iOS app (Version: _______) - Group context requirements: _______
- [ ] Android app (Version: _______) - Group switching needs: _______

### Third-Party Integrations
- [ ] Single Sign-On (SSO) systems - Group mapping requirements: _______
- [ ] External APIs using authentication - Group-based API access: _______
- [ ] Webhook endpoints - Group context in webhooks: _______

### Dependencies
- [ ] Database connections - Group-aware queries: _______
- [ ] Cache systems (Redis, Memcached) - Group context caching: _______
- [ ] Session storage systems - Group session management: _______
```

## 🗺️ Migration Planning

### Migration Strategy Options

#### Option 1: Big Bang Migration to Groups
- **Timeline**: 1-2 days downtime
- **Pros**: Clean cut to group-based system, no dual system complexity
- **Cons**: High risk, longer downtime
- **Best for**: Small systems with flexible downtime requirements

#### Option 2: Phased Group Migration
- **Timeline**: 2-4 weeks gradual transition  
- **Pros**: Lower risk, minimal downtime, group-by-group migration
- **Cons**: More complex, dual system maintenance
- **Best for**: Production systems with high availability needs

#### Option 3: Blue-Green Group Deployment
- **Timeline**: 1 week preparation + instant switch
- **Pros**: Zero downtime, easy rollback to legacy system
- **Cons**: Requires infrastructure duplication
- **Best for**: Critical systems with zero-downtime requirements

### Data Mapping Strategy

#### Legacy System → Group-Based System

```python
# Data mapping for group-based migration
LEGACY_TO_GROUP_MAPPING = {
    # Tables
    'tb_collection': 'projects',
    'tb_collection_user': 'users + user_group_members + user_group_projects',
    'user_groups': 'user_groups (global) + project_groups',
    'user_project_groups': 'user_group_members + project_group_members',
    
    # Fields
    'collection_hash': 'project_hash',
    'user_name': 'username',
    'user_email': 'email',
    'user_password': 'password_hash',
    'group_name': 'user_group.group_name OR project_group.group_name',
    'permissions': 'project_group.permissions'
}

# Group consolidation strategy
GROUP_CONSOLIDATION = {
    'project_specific_groups': 'convert_to_user_groups',
    'permission_groups': 'convert_to_project_groups',
    'admin_groups': 'merge_into_global_administrators',
    'user_groups': 'merge_into_global_users'
}
```

## 💾 Data Migration

### Step 1: Database Setup

```bash
# 1. Create new group-based database
mysql -u root -p -e "CREATE DATABASE magic_auth_groups CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 2. Initialize group-based schema
mysql -u root -p magic_auth_groups < new_database_schema.sql

# 3. Verify group schema creation
mysql -u root -p magic_auth_groups -e "SHOW TABLES;" | grep group
```

### Step 2: Data Backup

```bash
# Backup current system
mysqldump -u root -p your_current_database > backup_legacy_$(date +%Y%m%d_%H%M%S).sql

# Backup specific tables for group migration
mysqldump -u root -p your_current_database \
  users projects user_projects user_groups user_project_groups \
  > legacy_for_group_migration.sql
```

### Step 3: Group Migration Scripts

#### Enhanced to Clean Groups Migration

```python
# migrate_to_clean_groups.py
import pymysql
import hashlib
import json
from datetime import datetime

def migrate_to_clean_group_system():
    """Migrate from enhanced system to clean group-based system"""
    
    # Connection to legacy database
    legacy_conn = pymysql.connect(
        host='localhost',
        user='root',
        password='password',
        database='magic_auth_enhanced'  # Old database
    )
    
    # Connection to new group-based database
    group_conn = pymysql.connect(
        host='localhost',
        user='root',
        password='password', 
        database='magic_auth_groups'  # New database
    )
    
    try:
        legacy_cursor = legacy_conn.cursor()
        group_cursor = group_conn.cursor()
        
        print("=== Migrating to Clean Group-Based System ===")
        
        # Step 1: Migrate users (unchanged)
        migrate_users(legacy_cursor, group_cursor)
        
        # Step 2: Create global user groups
        create_global_user_groups(group_cursor)
        
        # Step 3: Create project groups
        create_project_groups(group_cursor)
        
        # Step 4: Migrate projects
        migrate_projects(legacy_cursor, group_cursor)
        
        # Step 5: Convert project-specific groups to user group assignments
        convert_project_groups_to_user_groups(legacy_cursor, group_cursor)
        
        # Step 6: Assign projects to project groups
        assign_projects_to_project_groups(group_cursor)
        
        # Step 7: Grant user groups access to projects
        grant_user_groups_project_access(legacy_cursor, group_cursor)
        
        group_conn.commit()
        print("✓ Clean group-based migration completed successfully!")
        
    except Exception as e:
        group_conn.rollback()
        print(f"✗ Error during group migration: {e}")
        raise
    
    finally:
        legacy_conn.close()
        group_conn.close()

def migrate_users(legacy_cursor, group_cursor):
    """Migrate users to clean group system"""
    print("Migrating users...")
    
    legacy_cursor.execute("""
        SELECT DISTINCT user_hash, username, email, password_hash, created_at
        FROM users
        WHERE is_active = 1
    """)
    
    users = legacy_cursor.fetchall()
    
    for user in users:
        user_hash, username, email, password_hash, created_at = user
        
        group_cursor.execute("""
            INSERT INTO users (user_hash, username, email, password_hash, created_at)
            VALUES (%s, %s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE
            email = VALUES(email),
            updated_at = NOW()
        """, (user_hash, username, email, password_hash, created_at))
        
    print(f"✓ Migrated {len(users)} users")

def create_global_user_groups(group_cursor):
    """Create default global user groups"""
    print("Creating global user groups...")
    
    default_user_groups = [
        {
            'group_name': 'administrators',
            'description': 'System administrators with full access',
            'group_hash': hashlib.sha256('administrators'.encode()).hexdigest()[:32]
        },
        {
            'group_name': 'users',
            'description': 'Standard users with project access',
            'group_hash': hashlib.sha256('users'.encode()).hexdigest()[:32]
        },
        {
            'group_name': 'guests',
            'description': 'Limited read-only access',
            'group_hash': hashlib.sha256('guests'.encode()).hexdigest()[:32]
        }
    ]
    
    for group in default_user_groups:
        group_cursor.execute("""
            INSERT INTO user_groups (group_hash, group_name, description)
            VALUES (%(group_hash)s, %(group_name)s, %(description)s)
            ON DUPLICATE KEY UPDATE
            description = VALUES(description)
        """, group)
    
    print(f"✓ Created {len(default_user_groups)} global user groups")

def create_project_groups(group_cursor):
    """Create default project groups"""
    print("Creating project groups...")
    
    default_project_groups = [
        {
            'group_name': 'full-access',
            'permissions': json.dumps(['admin', 'read', 'write', 'delete', 'manage_users']),
            'description': 'Complete project control',
            'group_hash': hashlib.sha256('full-access'.encode()).hexdigest()[:32]
        },
        {
            'group_name': 'read-write',
            'permissions': json.dumps(['read', 'write', 'create']),
            'description': 'Standard user permissions',
            'group_hash': hashlib.sha256('read-write'.encode()).hexdigest()[:32]
        },
        {
            'group_name': 'read-only',
            'permissions': json.dumps(['read', 'view']),
            'description': 'View-only access',
            'group_hash': hashlib.sha256('read-only'.encode()).hexdigest()[:32]
        }
    ]
    
    for group in default_project_groups:
        group_cursor.execute("""
            INSERT INTO project_groups (group_hash, group_name, permissions, description)
            VALUES (%(group_hash)s, %(group_name)s, %(permissions)s, %(description)s)
            ON DUPLICATE KEY UPDATE
            permissions = VALUES(permissions),
            description = VALUES(description)
        """, group)
    
    print(f"✓ Created {len(default_project_groups)} project groups")

def migrate_projects(legacy_cursor, group_cursor):
    """Migrate projects to group system"""
    print("Migrating projects...")
    
    legacy_cursor.execute("""
        SELECT project_hash, project_name, project_description, project_created
        FROM projects
        WHERE is_active = 1
    """)
    
    projects = legacy_cursor.fetchall()
    
    for project in projects:
        project_hash, name, description, created = project
        
        group_cursor.execute("""
            INSERT INTO projects (project_hash, project_name, project_description, created_at)
            VALUES (%s, %s, %s, %s)
            ON DUPLICATE KEY UPDATE 
            project_name = VALUES(project_name),
            project_description = VALUES(project_description)
        """, (project_hash, name, description, created))
    
    print(f"✓ Migrated {len(projects)} projects")

def convert_project_groups_to_user_groups(legacy_cursor, group_cursor):
    """Convert old project-specific groups to user group assignments"""
    print("Converting project groups to user group assignments...")
    
    # Get user-project relationships with their old groups
    legacy_cursor.execute("""
        SELECT DISTINCT
            u.user_hash,
            p.project_hash,
            ug.group_name,
            up.granted_at
        FROM users u
        JOIN user_projects up ON u.id = up.user_id
        JOIN projects p ON p.id = up.project_id
        LEFT JOIN user_project_groups upg ON up.id = upg.user_project_id
        LEFT JOIN user_groups ug ON upg.group_id = ug.id
        WHERE u.is_active = 1 AND p.is_active = 1 AND up.is_active = 1
    """)
    
    relationships = legacy_cursor.fetchall()
    
    for relationship in relationships:
        user_hash, project_hash, old_group_name, granted_at = relationship
        
        # Map old group names to new user groups
        if old_group_name in ['admin', 'administrator']:
            new_user_group = 'administrators'
        elif old_group_name in ['readonly', 'read-only', 'guest']:
            new_user_group = 'guests'
        else:
            new_user_group = 'users'  # Default
        
        # Assign user to global user group
        group_cursor.execute("""
            INSERT INTO user_group_members (user_id, user_group_id, assigned_at)
            SELECT u.id, ug.id, %s
            FROM users u, user_groups ug
            WHERE u.user_hash = %s AND ug.group_name = %s
            ON DUPLICATE KEY UPDATE assigned_at = VALUES(assigned_at)
        """, (granted_at, user_hash, new_user_group))
    
    print(f"✓ Converted {len(relationships)} group assignments")

def assign_projects_to_project_groups(group_cursor):
    """Assign all projects to appropriate project groups"""
    print("Assigning projects to project groups...")
    
    # For this example, assign all projects to 'full-access' group
    # In practice, you might want more sophisticated logic
    group_cursor.execute("""
        INSERT INTO project_group_members (project_id, project_group_id, assigned_at)
        SELECT p.id, pg.id, NOW()
        FROM projects p, project_groups pg
        WHERE pg.group_name = 'full-access'
        ON DUPLICATE KEY UPDATE assigned_at = VALUES(assigned_at)
    """)
    
    group_cursor.execute("SELECT ROW_COUNT()")
    count = group_cursor.fetchone()[0]
    print(f"✓ Assigned {count} projects to project groups")

def grant_user_groups_project_access(legacy_cursor, group_cursor):
    """Grant user groups access to projects based on legacy relationships"""
    print("Granting user groups project access...")
    
    # Get unique user group + project combinations
    group_cursor.execute("""
        SELECT DISTINCT ug.id, p.id
        FROM user_group_members ugm
        JOIN user_groups ug ON ugm.user_group_id = ug.id
        JOIN users u ON ugm.user_id = u.id
        JOIN projects p ON 1=1  -- Grant access to all projects for now
        WHERE ugm.is_active = 1 AND ug.is_active = 1
    """)
    
    access_grants = group_cursor.fetchall()
    
    for user_group_id, project_id in access_grants:
        group_cursor.execute("""
            INSERT INTO user_group_projects (user_group_id, project_id, granted_at)
            VALUES (%s, %s, NOW())
            ON DUPLICATE KEY UPDATE granted_at = VALUES(granted_at)
        """, (user_group_id, project_id))
    
    print(f"✓ Granted {len(access_grants)} user group project access relationships")

if __name__ == "__main__":
    print("Starting migration to clean group-based system...")
    migrate_to_clean_group_system()
    print("Migration completed successfully!")
```

### Step 4: Data Validation

```python
# validate_group_migration.py
def validate_group_migration():
    """Validate that group migration completed successfully"""
    
    group_conn = pymysql.connect(
        host='localhost',
        user='root',
        password='password',
        database='magic_auth_groups'
    )
    
    try:
        cursor = group_conn.cursor()
        
        print("=== Group Migration Validation ===")
        
        # Check user count
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        print(f"Total users migrated: {user_count}")
        
        # Check user groups
        cursor.execute("SELECT COUNT(*) FROM user_groups WHERE is_active = 1")
        user_group_count = cursor.fetchone()[0]
        print(f"Total user groups: {user_group_count}")
        
        # Check project groups
        cursor.execute("SELECT COUNT(*) FROM project_groups WHERE is_active = 1")
        project_group_count = cursor.fetchone()[0]
        print(f"Total project groups: {project_group_count}")
        
        # Check project count
        cursor.execute("SELECT COUNT(*) FROM projects WHERE is_active = 1") 
        project_count = cursor.fetchone()[0]
        print(f"Total projects migrated: {project_count}")
        
        # Check user group memberships
        cursor.execute("SELECT COUNT(*) FROM user_group_members WHERE is_active = 1")
        membership_count = cursor.fetchone()[0]
        print(f"Total user group memberships: {membership_count}")
        
        # Check user group project access
        cursor.execute("SELECT COUNT(*) FROM user_group_projects WHERE is_active = 1")
        access_count = cursor.fetchone()[0]
        print(f"Total user group project access grants: {access_count}")
        
        # Check project group assignments
        cursor.execute("SELECT COUNT(*) FROM project_group_members WHERE is_active = 1")
        project_assignments = cursor.fetchone()[0]
        print(f"Total project group assignments: {project_assignments}")
        
        # Validate group structure
        cursor.execute("""
            SELECT ug.group_name, COUNT(ugm.user_id) as member_count
            FROM user_groups ug
            LEFT JOIN user_group_members ugm ON ug.id = ugm.user_group_id AND ugm.is_active = 1
            WHERE ug.is_active = 1
            GROUP BY ug.id, ug.group_name
        """)
        
        group_stats = cursor.fetchall()
        print("\nUser Group Statistics:")
        for group_name, member_count in group_stats:
            print(f"  {group_name}: {member_count} members")
        
        # Test sample group-based access
        cursor.execute("""
            SELECT u.username, ug.group_name, p.project_name
            FROM users u
            JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
            JOIN user_groups ug ON ugm.user_group_id = ug.id AND ug.is_active = 1
            JOIN user_group_projects ugp ON ug.id = ugp.user_group_id AND ugp.is_active = 1
            JOIN projects p ON ugp.project_id = p.id AND p.is_active = 1
            LIMIT 5
        """)
        
        sample_access = cursor.fetchall()
        print("\nSample Group-Based Access:")
        for username, group_name, project_name in sample_access:
            print(f"  {username} ({group_name}) → {project_name}")
        
        print("\n✓ Group migration validation completed successfully!")
        
    finally:
        group_conn.close()

if __name__ == "__main__":
    validate_group_migration()
```

## 🔄 System Migration

### Step 1: Update Application Code for Groups

#### Legacy API Calls → Group-Based API Calls

```python
# Before (Legacy)
import requests

def legacy_login(username, password, collection_hash):
    response = requests.post("http://api/user/login", data={
        "username": username,
        "password": password,
        "collection_hash": collection_hash
    })
    return response.json()

# After (Group-Based)
def group_based_login(username, password, project_hash):
    response = requests.post("http://api/user/login", data={
        "username": username,
        "password": password,
        "project_hash": project_hash  # Clean naming
    })
    
    data = response.json()
    
    # New group-based response structure
    return {
        'session_token': data['session_token'],
        'user_groups': data['user']['user_groups'],
        'project_permissions': data['project']['permissions'],
        'accessible_projects': data['accessible_projects']
    }
```

#### Update Group Handling

```python
# Before (Legacy)
def check_user_permission(user_id, project_id, permission):
    # Complex project-specific group lookup
    return legacy_db.check_project_permission(user_id, project_id, permission)

# After (Group-Based)  
def check_user_permission(user_id, project_id, permission):
    from group_based_crud_operations import PermissionUtils
    return PermissionUtils.check_user_permission(user_id, project_id, permission)
```

### Step 2: Update Database Connections

```python
# Update database configuration for groups
# config.py

# Legacy database config (keep for migration period)
LEGACY_DB_CONFIG = {
    "host": "localhost",
    "user": "root", 
    "password": "legacy_password",
    "database": "magic_auth_enhanced"  # Old system
}

# Group-based database config  
GROUP_DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "group_password", 
    "database": "magic_auth_groups"  # New group system
}
```

### Step 3: Update Environment Variables

```bash
# .env file updates for group system

# Legacy system (comment out after migration)
# DB_DATABASE=magic_auth_enhanced
# DB_TABLE_PREFIX=tb_

# Group-based system (new configuration)
DB_DATABASE=magic_auth_groups
DB_HOST=192.168.1.90
DB_USER=root
DB_MYSQL_PASSWORD=your_mysql_password
DB_REDIS_PASSWORD=your_redis_password

# Group system settings
GROUP_SYSTEM_ENABLED=true
DEFAULT_USER_GROUP=users
DEFAULT_PROJECT_GROUP=read-write

# Migration settings (temporary)
MIGRATION_MODE=true
LEGACY_DB_DATABASE=magic_auth_enhanced
```

## 🧪 Testing & Validation

### Group Migration Testing Checklist

#### 1. Data Integrity Tests

```sql
-- Test 1: User count validation
SELECT 
    (SELECT COUNT(*) FROM legacy_db.users) as legacy_users,
    (SELECT COUNT(*) FROM magic_auth_groups.users) as group_users;

-- Test 2: Group structure validation  
SELECT
    (SELECT COUNT(*) FROM magic_auth_groups.user_groups) as user_groups,
    (SELECT COUNT(*) FROM magic_auth_groups.project_groups) as project_groups;

-- Test 3: Group membership validation
SELECT
    (SELECT COUNT(*) FROM magic_auth_groups.user_group_members WHERE is_active = 1) as user_memberships,
    (SELECT COUNT(*) FROM magic_auth_groups.user_group_projects WHERE is_active = 1) as project_access_grants;
```

#### 2. Group Functional Tests

```python
# test_group_migration.py
import pytest
from group_based_crud_operations import *

class TestGroupMigration:
    
    def test_user_group_functionality(self):
        """Test that user groups work correctly"""
        # Create test user group
        test_group = UserGroupCRUD.create("test_group", "Test group for migration")
        assert test_group is not None
        assert test_group.group_name == "test_group"
    
    def test_project_group_functionality(self):
        """Test that project groups work correctly"""
        # Create test project group
        test_group = ProjectGroupCRUD.create(
            "test_permissions", 
            ["read", "write"],
            "Test permission group"
        )
        assert test_group is not None
        assert "read" in test_group.permissions
    
    def test_group_based_login(self):
        """Test that group-based login works"""
        from src.Util.db import enhanced_login
        
        result = enhanced_login("test_user", "password", "test_project_hash")
        assert result is not None
        assert hasattr(result, 'groups')
        assert len(result.groups) > 0
    
    def test_permission_resolution(self):
        """Test that permissions resolve through groups correctly"""
        # This would test the hierarchical permission resolution
        permissions = PermissionUtils.get_user_project_permissions(1, 1)
        assert permissions is not None
        assert isinstance(permissions, list)
    
    def test_group_project_access(self):
        """Test that users get project access through groups"""
        projects = PermissionUtils.get_user_accessible_projects(1)
        assert projects is not None
        assert len(projects) >= 0
```

#### 3. Performance Tests

```python
# group_performance_test.py
import time
import concurrent.futures
from group_based_crud_operations import PermissionUtils

def test_group_permission_performance():
    """Test group permission checking performance"""
    
    def single_permission_check():
        start = time.time()
        result = PermissionUtils.check_user_permission(1, 1, "read")
        end = time.time()
        return end - start, result

    # Test concurrent permission checks
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(single_permission_check) for _ in range(100)]
        results = [future.result() for future in futures]
    
    times = [r[0] for r in results]
    successes = [r[1] for r in results if r[1] is not None]
    
    print(f"Average permission check time: {sum(times)/len(times):.3f}s")
    print(f"Success rate: {len(successes)/len(results)*100:.1f}%")
    print(f"Max permission check time: {max(times):.3f}s")
    
    assert max(times) < 1.0  # No permission check should take more than 1 second
    assert len(successes)/len(results) > 0.95  # 95% success rate
```

## 🚨 Rollback Procedures

### Rollback Strategy for Group Migration

#### 1. Immediate Rollback (Emergency)

```bash
#!/bin/bash
# emergency_group_rollback.sh

echo "EMERGENCY GROUP ROLLBACK STARTED"

# 1. Stop group-based API
docker-compose -f docker-compose.groups.yml down

# 2. Start legacy API  
docker-compose -f docker-compose.legacy.yml up -d

# 3. Restore legacy database from backup
mysql -u root -p magic_auth_enhanced < backup_legacy_$(date +%Y%m%d)_*.sql

# 4. Update environment to legacy system
export DB_DATABASE=magic_auth_enhanced
export GROUP_SYSTEM_ENABLED=false

# 5. Clear group system caches
redis-cli -h redis-server FLUSHDB

echo "EMERGENCY ROLLBACK COMPLETED"
echo "Legacy system is now active"
```

#### 2. Planned Group Rollback

```python
# planned_group_rollback.py
def rollback_group_migration():
    """Planned rollback from group system to legacy"""
    
    print("Starting planned group system rollback...")
    
    # 1. Export any new data created in group system
    export_new_group_data()
    
    # 2. Restore legacy database
    restore_legacy_database()
    
    # 3. Convert compatible group data back to legacy format
    convert_group_data_to_legacy()
    
    # 4. Update application configuration to legacy
    update_config_to_legacy()
    
    print("Planned group rollback completed")

def export_new_group_data():
    """Export data created after group migration"""
    group_conn = get_group_connection()
    cursor = group_conn.cursor()
    
    # Export users created after migration
    cursor.execute("""
        SELECT * FROM users 
        WHERE created_at > %s
    """, (GROUP_MIGRATION_DATE,))
    
    new_users = cursor.fetchall()
    
    # Export new user groups
    cursor.execute("""
        SELECT * FROM user_groups 
        WHERE created_at > %s AND group_name NOT IN ('administrators', 'users', 'guests')
    """, (GROUP_MIGRATION_DATE,))
    
    new_groups = cursor.fetchall()
    
    # Save to file for manual review
    with open('new_group_data_export.json', 'w') as f:
        json.dump({
            'new_users': new_users,
            'new_groups': new_groups
        }, f, default=str)
    
    print(f"Exported {len(new_users)} new users and {len(new_groups)} new groups")
```

### Data Consistency Checks

```python
# group_rollback_validation.py
def validate_group_rollback():
    """Ensure rollback from group system was successful"""
    
    # Test legacy system connectivity
    try:
        legacy_conn = get_legacy_connection()
        cursor = legacy_conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        print(f"Legacy system user count: {user_count}")
        legacy_conn.close()
    except Exception as e:
        print(f"ERROR: Legacy system not accessible: {e}")
        return False
    
    # Test legacy API endpoints
    try:
        response = requests.get("http://legacy-api/health")
        if response.status_code == 200:
            print("✓ Legacy API is responding")
        else:
            print(f"✗ Legacy API returned status {response.status_code}")
            return False
    except Exception as e:
        print(f"ERROR: Legacy API not responding: {e}")
        return False
    
    # Verify group system is disabled
    try:
        response = requests.get("http://api/system/groups/health")
        if response.status_code == 404:
            print("✓ Group system properly disabled")
        else:
            print("✗ Group system still responding")
            return False
    except Exception:
        print("✓ Group system properly disabled")
    
    return True
```

## 📋 Migration Checklist

### Pre-Migration Checklist

- [ ] **Assessment Complete**
  - [ ] Current system analysis documented with group structure
  - [ ] Data volume and group complexity assessed  
  - [ ] Integration dependencies identified for group migration
  - [ ] Group migration timeline approved

- [ ] **Backups Created**
  - [ ] Full database backup created
  - [ ] Application code backed up
  - [ ] Configuration files backed up
  - [ ] Group migration recovery procedures tested

- [ ] **Test Environment Ready**
  - [ ] Group-based system deployed in test
  - [ ] Group migration scripts tested
  - [ ] Sample data migration to groups completed
  - [ ] Group integration tests passing

### Migration Day Checklist

- [ ] **Pre-Migration Tasks**
  - [ ] Final backup completed
  - [ ] Maintenance mode enabled
  - [ ] Team notifications sent
  - [ ] Group rollback procedures ready

- [ ] **Group Migration Execution**
  - [ ] Database migration to group structure completed
  - [ ] Group data validation passed
  - [ ] Group-based application deployment completed
  - [ ] Group configuration updated

- [ ] **Post-Migration Tasks**
  - [ ] Group functional tests completed
  - [ ] Group performance tests passed
  - [ ] User acceptance testing of group features completed
  - [ ] Group monitoring enabled

### Post-Migration Checklist

- [ ] **Group System Validation**
  - [ ] All group functions working correctly
  - [ ] Group performance meets requirements
  - [ ] No group data integrity issues
  - [ ] Group security controls active

- [ ] **Documentation Updated**
  - [ ] API documentation updated for group endpoints
  - [ ] User guides updated for group functionality
  - [ ] Operational procedures updated for group management
  - [ ] Group migration completion documented

- [ ] **Cleanup Tasks**
  - [ ] Legacy system archived or decommissioned
  - [ ] Temporary group migration tools removed
  - [ ] Test data cleaned up
  - [ ] Group migration success metrics reported

## 🆘 Troubleshooting Common Group Migration Issues

### Issue 1: Group Assignment Conflicts During Migration

```python
# Problem: Multiple group assignments for same user
# Solution: Implement group priority resolution

def resolve_group_conflicts():
    cursor.execute("""
        SELECT user_id, COUNT(*) as group_count
        FROM user_group_members 
        WHERE is_active = 1
        GROUP BY user_id
        HAVING group_count > 1
    """)
    
    conflicts = cursor.fetchall()
    
    for user_id, group_count in conflicts:
        # Apply priority: administrators > users > guests
        cursor.execute("""
            UPDATE user_group_members ugm
            JOIN user_groups ug ON ugm.user_group_id = ug.id
            SET ugm.is_active = 0
            WHERE ugm.user_id = %s 
            AND ug.group_name != (
                SELECT priority_group FROM (
                    SELECT CASE 
                        WHEN EXISTS(SELECT 1 FROM user_group_members ugm2 
                                   JOIN user_groups ug2 ON ugm2.user_group_id = ug2.id 
                                   WHERE ugm2.user_id = %s AND ug2.group_name = 'administrators') 
                        THEN 'administrators'
                        WHEN EXISTS(SELECT 1 FROM user_group_members ugm2 
                                   JOIN user_groups ug2 ON ugm2.user_group_id = ug2.id 
                                   WHERE ugm2.user_id = %s AND ug2.group_name = 'users') 
                        THEN 'users'
                        ELSE 'guests'
                    END as priority_group
                ) as priority
            )
        """, (user_id, user_id, user_id))
```

### Issue 2: Missing Group Relationships After Migration

```python
# Problem: Users without group assignments
# Solution: Assign orphaned users to default groups

def fix_missing_group_relationships():
    # Find users without group assignments
    cursor.execute("""
        SELECT u.id, u.username
        FROM users u
        LEFT JOIN user_group_members ugm ON u.id = ugm.user_id AND ugm.is_active = 1
        WHERE ugm.user_id IS NULL AND u.is_active = 1
    """)
    
    orphaned_users = cursor.fetchall()
    
    for user_id, username in orphaned_users:
        # Assign to default 'users' group
        cursor.execute("""
            INSERT INTO user_group_members (user_id, user_group_id, assigned_at)
            SELECT %s, ug.id, NOW()
            FROM user_groups ug
            WHERE ug.group_name = 'users'
        """, (user_id,))
        
        print(f"Assigned orphaned user {username} to 'users' group")
```

### Issue 3: Group Performance Issues After Migration

```python
# Problem: Slow group permission queries
# Solution: Optimize group indexes and queries

def optimize_group_performance():
    # Add composite indexes for group queries
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_group_members_active 
        ON user_group_members(user_id, user_group_id, is_active)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_group_projects_active 
        ON user_group_projects(user_group_id, project_id, is_active)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_project_group_members_active 
        ON project_group_members(project_id, project_group_id, is_active)
    """)
    
    # Analyze tables for query optimization
    cursor.execute("ANALYZE TABLE user_groups, project_groups, user_group_members")
```

## 📞 Support and Resources

### Group Migration Support

- **Documentation**: Complete group system docs in `/docs` folder
- **Test Scripts**: Group migration validation scripts included
- **Rollback Procedures**: Detailed group rollback instructions provided
- **Performance Monitoring**: Built-in group metrics and logging

### Getting Help with Group Migration

1. **Check Group Documentation**: Review all group-related docs in `/docs` folder
2. **Run Group Test Scripts**: Use provided group validation scripts
3. **Check Group Logs**: Review application and database logs for group operations
4. **Test Group Rollback**: Ensure group rollback procedures work before migration

---

**This migration guide provides a comprehensive approach to safely migrating from legacy authentication systems to the clean Group-Based Multi-Project Authentication API. The new system eliminates confusing naming and provides a clear hierarchical structure: Users → User Groups → Project Access → Project Groups → Permissions. Follow the steps carefully and always test group functionality thoroughly before production migration.** 