# Migration Guide

Complete guide for migrating from legacy authentication systems to the Enhanced Multi-Project Authentication API.

## 📋 Overview

This guide covers:
- **Legacy System Assessment**: Understanding your current setup
- **Migration Planning**: Step-by-step migration strategy
- **Data Migration**: Moving users, projects, and permissions
- **System Migration**: Updating application code
- **Testing & Validation**: Ensuring migration success
- **Rollback Procedures**: Safety measures and contingency plans

## 🎯 Migration Scenarios

### Scenario 1: From Single-Project Auth System
- Migrate from single project to multi-project architecture
- Preserve existing users and their permissions
- Add project structure and group-based permissions

### Scenario 2: From Collection-Based System  
- Migrate from `tb_collection` and `tb_collection_user` tables
- Convert collections to projects
- Map collection users to project users

### Scenario 3: From Multiple Independent Systems
- Consolidate multiple authentication systems
- Merge user bases with conflict resolution
- Unify permission structures

## 🔄 Migration Process Overview

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ 1. Assessment   │───►│ 2. Planning     │───►│ 3. Preparation  │
│                 │    │                 │    │                 │
│ • Analyze       │    │ • Map data      │    │ • Backup data   │
│   current system│    │ • Design        │    │   setup test    │
│ • Identify      │    │   migration     │    │   environment   │
│   dependencies  │    │   strategy      │    │ • Create        │
│ • Plan timeline │    │ • Risk analysis │    │   migration     │
│                 │    │                 │    │   scripts       │
└─────────────────┘    └─────────────────┘    └─────────────────┘
           │                       │                       │
           ▼                       ▼                       ▼
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│ 4. Data         │───►│ 5. System       │───►│ 6. Validation   │
│    Migration    │    │    Migration    │    │    & Testing    │
│                 │    │                 │    │                 │
│ • Run migration │    │ • Update APIs   │    │ • Test all      │
│   scripts       │    │ • Deploy new    │    │   functions     │
│ • Validate data │    │   system        │    │ • Performance   │
│ • Handle        │    │ • Update        │    │   testing       │
│   conflicts     │    │   integrations  │    │ • User          │
│                 │    │                 │    │   acceptance    │
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

-- Check for data relationships
SELECT 
    table_name,
    column_name,
    constraint_name,
    referenced_table_name,
    referenced_column_name
FROM information_schema.key_column_usage
WHERE table_schema = 'your_database'
AND referenced_table_name IS NOT NULL;
```

#### 2. Data Volume Assessment

```sql
-- Get data volume statistics
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
FROM projects;
```

#### 3. Integration Analysis

Create an inventory of all systems that integrate with your current authentication:

```markdown
## Integration Inventory

### Web Applications
- [ ] Main web application (URL: _______)
- [ ] Admin panel (URL: _______)
- [ ] API dashboard (URL: _______)

### Mobile Applications  
- [ ] iOS app (Version: _______)
- [ ] Android app (Version: _______)

### Third-Party Integrations
- [ ] Single Sign-On (SSO) systems
- [ ] External APIs using authentication
- [ ] Webhook endpoints

### Dependencies
- [ ] Database connections
- [ ] Cache systems (Redis, Memcached)
- [ ] Session storage systems
```

## 🗺️ Migration Planning

### Migration Strategy Options

#### Option 1: Big Bang Migration
- **Timeline**: 1-2 days downtime
- **Pros**: Clean cut, no dual system complexity
- **Cons**: High risk, longer downtime
- **Best for**: Small systems with flexible downtime requirements

#### Option 2: Phased Migration
- **Timeline**: 2-4 weeks gradual transition  
- **Pros**: Lower risk, minimal downtime
- **Cons**: More complex, dual system maintenance
- **Best for**: Production systems with high availability needs

#### Option 3: Blue-Green Deployment
- **Timeline**: 1 week preparation + instant switch
- **Pros**: Zero downtime, easy rollback
- **Cons**: Requires infrastructure duplication
- **Best for**: Critical systems with zero-downtime requirements

### Data Mapping Strategy

#### Legacy Collection System → Enhanced System

```python
# Data mapping example
LEGACY_TO_ENHANCED_MAPPING = {
    'tb_collection': 'projects',
    'tb_collection_user': 'users + user_projects',
    'collection_hash': 'project_hash',
    'user_name': 'username',
    'user_email': 'email',
    'user_password': 'password_hash'
}
```

## 💾 Data Migration

### Step 1: Database Setup

```bash
# 1. Create new enhanced database
mysql -u root -p -e "CREATE DATABASE magic_auth_enhanced CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;"

# 2. Initialize enhanced schema
python setup_enhanced_auth.py

# 3. Verify schema creation
mysql -u root -p magic_auth_enhanced -e "SHOW TABLES;"
```

### Step 2: Data Backup

```bash
# Backup current system
mysqldump -u root -p your_current_database > backup_legacy_$(date +%Y%m%d_%H%M%S).sql

# Backup specific tables
mysqldump -u root -p your_current_database tb_collection tb_collection_user > legacy_auth_backup.sql
```

### Step 3: Migration Scripts

#### Collection-Based System Migration

```python
# migrate_legacy_to_enhanced.py
import pymysql
import hashlib
import secrets
from datetime import datetime

def migrate_collections_to_projects():
    """Migrate tb_collection to projects table"""
    
    # Connection to legacy database
    legacy_conn = pymysql.connect(
        host='localhost',
        user='root',
        password='password',
        database='legacy_database'
    )
    
    # Connection to enhanced database
    enhanced_conn = pymysql.connect(
        host='localhost',
        user='root',
        password='password', 
        database='magic_auth_enhanced'
    )
    
    try:
        legacy_cursor = legacy_conn.cursor()
        enhanced_cursor = enhanced_conn.cursor()
        
        # Get all collections
        legacy_cursor.execute("""
            SELECT id_collection, collection_hash, collection_name, 
                   collection_description, collection_created
            FROM tb_collection
            WHERE collection_active = 1
        """)
        
        collections = legacy_cursor.fetchall()
        
        for collection in collections:
            collection_id, collection_hash, name, description, created = collection
            
            # Insert into projects table
            enhanced_cursor.execute("""
                INSERT INTO projects (project_hash, project_name, project_description, project_created)
                VALUES (%s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE 
                project_name = VALUES(project_name),
                project_description = VALUES(project_description)
            """, (collection_hash, name or f"Legacy Project {collection_id}", description, created))
            
            print(f"Migrated collection: {name} ({collection_hash})")
        
        enhanced_conn.commit()
        print(f"Successfully migrated {len(collections)} collections to projects")
        
    except Exception as e:
        enhanced_conn.rollback()
        print(f"Error migrating collections: {e}")
        raise
    
    finally:
        legacy_conn.close()
        enhanced_conn.close()

def migrate_users_and_relationships():
    """Migrate users and their project relationships"""
    
    legacy_conn = pymysql.connect(
        host='localhost',
        user='root', 
        password='password',
        database='legacy_database'
    )
    
    enhanced_conn = pymysql.connect(
        host='localhost',
        user='root',
        password='password',
        database='magic_auth_enhanced'
    )
    
    try:
        legacy_cursor = legacy_conn.cursor()
        enhanced_cursor = enhanced_conn.cursor()
        
        # Get unique users across all collections
        legacy_cursor.execute("""
            SELECT DISTINCT user_name, user_email, user_password, user_hash, 
                   MIN(user_creation) as first_created
            FROM tb_collection_user
            GROUP BY user_name, user_email, user_password, user_hash
        """)
        
        users = legacy_cursor.fetchall()
        
        for user in users:
            username, email, password_hash, user_hash, created = user
            
            # Insert into users table
            enhanced_cursor.execute("""
                INSERT INTO users (username, email, password_hash, user_hash, created_at)
                VALUES (%s, %s, %s, %s, %s)
                ON DUPLICATE KEY UPDATE
                email = VALUES(email),
                updated_at = NOW()
            """, (username, email, password_hash, user_hash, created))
            
            print(f"Migrated user: {username}")
        
        enhanced_conn.commit()
        
        # Now migrate user-project relationships
        legacy_cursor.execute("""
            SELECT tcu.user_hash, tc.collection_hash, tcu.user_creation,
                   tcu.id_collection_user
            FROM tb_collection_user tcu
            JOIN tb_collection tc ON tc.id_collection = tcu.id_collection
            WHERE tc.collection_active = 1
        """)
        
        relationships = legacy_cursor.fetchall()
        
        for relationship in relationships:
            user_hash, project_hash, granted_at, legacy_id = relationship
            
            # Generate unique user_project_hash
            user_project_hash = hashlib.sha256(f"{user_hash}_{project_hash}_{legacy_id}".encode()).hexdigest()
            
            # Insert user-project relationship
            enhanced_cursor.execute("""
                INSERT INTO user_projects (user_id, project_id, user_project_hash, granted_at)
                SELECT u.id, p.id, %s, %s
                FROM users u, projects p
                WHERE u.user_hash = %s AND p.project_hash = %s
                ON DUPLICATE KEY UPDATE granted_at = VALUES(granted_at)
            """, (user_project_hash, granted_at, user_hash, project_hash))
            
            # Get the user_project_id for group assignment
            enhanced_cursor.execute("""
                SELECT up.id, ug.id as admin_group_id
                FROM user_projects up
                JOIN users u ON u.id = up.user_id  
                JOIN projects p ON p.id = up.project_id
                JOIN user_groups ug ON ug.project_id = p.id AND ug.group_name = 'user'
                WHERE u.user_hash = %s AND p.project_hash = %s
            """, (user_hash, project_hash))
            
            result = enhanced_cursor.fetchone()
            if result:
                user_project_id, user_group_id = result
                
                # Assign to default 'user' group
                enhanced_cursor.execute("""
                    INSERT INTO user_project_groups (user_project_id, group_id, assigned_at)
                    VALUES (%s, %s, %s)
                    ON DUPLICATE KEY UPDATE assigned_at = VALUES(assigned_at)
                """, (user_project_id, user_group_id, granted_at))
        
        enhanced_conn.commit()
        print(f"Successfully migrated {len(relationships)} user-project relationships")
        
    except Exception as e:
        enhanced_conn.rollback()
        print(f"Error migrating users and relationships: {e}")
        raise
        
    finally:
        legacy_conn.close()
        enhanced_conn.close()

if __name__ == "__main__":
    print("Starting legacy to enhanced migration...")
    
    # Step 1: Migrate collections to projects
    migrate_collections_to_projects()
    
    # Step 2: Migrate users and relationships
    migrate_users_and_relationships()
    
    print("Migration completed successfully!")
```

### Step 4: Data Validation

```python
# validate_migration.py
def validate_migration():
    """Validate that migration completed successfully"""
    
    enhanced_conn = pymysql.connect(
        host='localhost',
        user='root',
        password='password',
        database='magic_auth_enhanced'
    )
    
    try:
        cursor = enhanced_conn.cursor()
        
        # Check user count
        cursor.execute("SELECT COUNT(*) FROM users")
        user_count = cursor.fetchone()[0]
        print(f"Total users migrated: {user_count}")
        
        # Check project count
        cursor.execute("SELECT COUNT(*) FROM projects") 
        project_count = cursor.fetchone()[0]
        print(f"Total projects migrated: {project_count}")
        
        # Check user-project relationships
        cursor.execute("SELECT COUNT(*) FROM user_projects WHERE is_active = 1")
        relationship_count = cursor.fetchone()[0]
        print(f"Total user-project relationships: {relationship_count}")
        
        # Check default groups were created
        cursor.execute("""
            SELECT p.project_name, COUNT(ug.id) as group_count
            FROM projects p
            LEFT JOIN user_groups ug ON p.id = ug.project_id
            GROUP BY p.id, p.project_name
        """)
        
        project_groups = cursor.fetchall()
        for project_name, group_count in project_groups:
            print(f"Project '{project_name}' has {group_count} groups")
            if group_count < 3:
                print(f"WARNING: Project '{project_name}' missing default groups")
        
        # Test sample login
        from src.Util.db import enhanced_login
        
        # Try to login with a migrated user
        cursor.execute("""
            SELECT u.username, p.project_hash
            FROM users u
            JOIN user_projects up ON u.id = up.user_id
            JOIN projects p ON p.id = up.project_id
            WHERE up.is_active = 1
            LIMIT 1
        """)
        
        sample_user = cursor.fetchone()
        if sample_user:
            username, project_hash = sample_user
            print(f"Testing login for user: {username} in project: {project_hash}")
            
            # Note: You'll need to know a test password or reset one for testing
            # login_result = enhanced_login(username, "test_password", project_hash)
            # if login_result:
            #     print("✓ Sample login test successful")
            # else:
            #     print("✗ Sample login test failed")
        
        print("Migration validation completed!")
        
    finally:
        enhanced_conn.close()

if __name__ == "__main__":
    validate_migration()
```

## 🔄 System Migration

### Step 1: Update Application Code

#### Legacy API Calls → Enhanced API Calls

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

# After (Enhanced)
def enhanced_login(username, password, project_hash):
    response = requests.post("http://api/user/login", data={
        "username": username,
        "password": password,
        "project_hash": project_hash  # Note: same parameter, renamed
    })
    return response.json()
```

#### Update Session Handling

```python
# Before (Legacy)
def check_session(user_hash, session_key):
    return legacy_db.validate_session(user_hash, session_key)

# After (Enhanced)  
def check_session(session_token):
    from src.Util.db import validate_session
    return validate_session(session_token)
```

### Step 2: Update Database Connections

```python
# Update database configuration
# config.py

# Legacy database config (keep for migration period)
LEGACY_DB_CONFIG = {
    "host": "localhost",
    "user": "root", 
    "password": "legacy_password",
    "database": "legacy_auth_system"
}

# Enhanced database config  
ENHANCED_DB_CONFIG = {
    "host": "localhost",
    "user": "root",
    "password": "enhanced_password", 
    "database": "magic_auth_enhanced"
}
```

### Step 3: Update Environment Variables

```bash
# .env file updates

# Legacy system (comment out after migration)
# DB_DATABASE=legacy_auth_system
# DB_TABLE_PREFIX=tb_

# Enhanced system (new configuration)
DB_DATABASE=magic_auth_enhanced
DB_HOST=192.168.1.90
DB_USER=root
DB_MYSQL_PASSWORD=your_mysql_password
DB_REDIS_PASSWORD=your_redis_password

# Migration settings (temporary)
MIGRATION_MODE=true
LEGACY_DB_DATABASE=legacy_auth_system
```

## 🧪 Testing & Validation

### Migration Testing Checklist

#### 1. Data Integrity Tests

```sql
-- Test 1: User count validation
SELECT 
    (SELECT COUNT(*) FROM legacy_db.tb_collection_user) as legacy_users,
    (SELECT COUNT(*) FROM magic_auth_enhanced.users) as enhanced_users;

-- Test 2: Project count validation  
SELECT
    (SELECT COUNT(*) FROM legacy_db.tb_collection) as legacy_collections,
    (SELECT COUNT(*) FROM magic_auth_enhanced.projects) as enhanced_projects;

-- Test 3: Relationship validation
SELECT
    (SELECT COUNT(*) FROM legacy_db.tb_collection_user) as legacy_relationships,
    (SELECT COUNT(*) FROM magic_auth_enhanced.user_projects WHERE is_active = 1) as enhanced_relationships;
```

#### 2. Functional Tests

```python
# test_migration.py
import pytest
from src.Util.db import enhanced_login, enhanced_register, validate_session

class TestMigration:
    
    def test_migrated_user_login(self):
        """Test that migrated users can login"""
        # Use known migrated user credentials
        result = enhanced_login("migrated_user", "password", "project_hash")
        assert result is not None
        assert result.user_hash is not None
        assert result.session_token is not None
    
    def test_migrated_project_access(self):
        """Test that users have correct project access"""
        result = enhanced_login("migrated_user", "password", "project_hash")
        assert len(result.available_projects) > 0
    
    def test_session_validation(self):
        """Test that session validation works"""
        login_result = enhanced_login("migrated_user", "password", "project_hash")
        session_result = validate_session(login_result.session_token)
        assert session_result is not None
        assert session_result.user_hash == login_result.user_hash
    
    def test_permissions(self):
        """Test that permissions were migrated correctly"""
        login_result = enhanced_login("migrated_user", "password", "project_hash")
        assert "read" in login_result.permissions
        assert "write" in login_result.permissions
```

#### 3. Performance Tests

```python
# performance_test.py
import time
import concurrent.futures
from src.Util.db import enhanced_login

def test_login_performance():
    """Test login performance under load"""
    
    def single_login():
        start = time.time()
        result = enhanced_login("test_user", "password", "project_hash")
        end = time.time()
        return end - start, result is not None
    
    # Test concurrent logins
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        futures = [executor.submit(single_login) for _ in range(100)]
        results = [future.result() for future in futures]
    
    times = [r[0] for r in results]
    successes = [r[1] for r in results]
    
    print(f"Average login time: {sum(times)/len(times):.3f}s")
    print(f"Success rate: {sum(successes)/len(successes)*100:.1f}%")
    print(f"Max login time: {max(times):.3f}s")
    
    assert sum(successes)/len(successes) > 0.95  # 95% success rate
    assert max(times) < 2.0  # No login should take more than 2 seconds
```

### Load Testing

```bash
# Install load testing tools
pip install locust

# Create load test script
# locustfile.py
from locust import HttpUser, task, between

class AuthUser(HttpUser):
    wait_time = between(1, 3)
    
    def on_start(self):
        # Login on start
        response = self.client.post("/user/login", data={
            "username": "test_user",
            "password": "password",
            "project_hash": "test_project_hash"
        })
        
        if response.status_code == 200:
            data = response.json()
            self.session_token = data.get("session_token")
        
    @task(3)
    def get_profile(self):
        if hasattr(self, 'session_token'):
            self.client.get("/user/profile", headers={
                "Authorization": f"Bearer {self.session_token}"
            })
    
    @task(1) 
    def validate_session(self):
        if hasattr(self, 'session_token'):
            self.client.get("/user/validate", headers={
                "Authorization": f"Bearer {self.session_token}"
            })

# Run load test
locust -f locustfile.py --host=http://localhost:8000
```

## 🚨 Rollback Procedures

### Rollback Strategy

#### 1. Immediate Rollback (Emergency)

```bash
#!/bin/bash
# emergency_rollback.sh

echo "EMERGENCY ROLLBACK STARTED"

# 1. Stop enhanced API
docker-compose -f docker-compose.enhanced.yml down

# 2. Start legacy API  
docker-compose -f docker-compose.legacy.yml up -d

# 3. Restore legacy database from backup
mysql -u root -p legacy_auth_system < backup_legacy_$(date +%Y%m%d)_*.sql

# 4. Update load balancer to point to legacy system
# (Implementation depends on your load balancer)

# 5. Clear enhanced system caches
redis-cli -h redis-server FLUSHDB

echo "EMERGENCY ROLLBACK COMPLETED"
echo "Legacy system is now active"
```

#### 2. Planned Rollback

```python
# planned_rollback.py
def rollback_migration():
    """Planned rollback with data preservation"""
    
    print("Starting planned rollback...")
    
    # 1. Export any new data created in enhanced system
    export_new_enhanced_data()
    
    # 2. Restore legacy database
    restore_legacy_database()
    
    # 3. Import compatible new data to legacy system
    import_compatible_data_to_legacy()
    
    # 4. Update application configuration
    update_config_to_legacy()
    
    print("Planned rollback completed")

def export_new_enhanced_data():
    """Export data created after migration"""
    enhanced_conn = get_enhanced_connection()
    cursor = enhanced_conn.cursor()
    
    # Export users created after migration
    cursor.execute("""
        SELECT * FROM users 
        WHERE created_at > %s
    """, (MIGRATION_DATE,))
    
    new_users = cursor.fetchall()
    
    # Save to file for manual review
    with open('new_users_export.json', 'w') as f:
        json.dump(new_users, f, default=str)
    
    print(f"Exported {len(new_users)} new users")
```

### Data Consistency Checks

```python
# rollback_validation.py
def validate_rollback():
    """Ensure rollback was successful"""
    
    # Test legacy system connectivity
    try:
        legacy_conn = get_legacy_connection()
        cursor = legacy_conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM tb_collection_user")
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
    
    return True
```

## 📋 Migration Checklist

### Pre-Migration Checklist

- [ ] **Assessment Complete**
  - [ ] Current system analysis documented
  - [ ] Data volume and complexity assessed  
  - [ ] Integration dependencies identified
  - [ ] Migration timeline approved

- [ ] **Backups Created**
  - [ ] Full database backup created
  - [ ] Application code backed up
  - [ ] Configuration files backed up
  - [ ] Recovery procedures tested

- [ ] **Test Environment Ready**
  - [ ] Enhanced system deployed in test
  - [ ] Migration scripts tested
  - [ ] Sample data migration completed
  - [ ] Integration tests passing

### Migration Day Checklist

- [ ] **Pre-Migration Tasks**
  - [ ] Final backup completed
  - [ ] Maintenance mode enabled
  - [ ] Team notifications sent
  - [ ] Rollback procedures ready

- [ ] **Migration Execution**
  - [ ] Database migration completed
  - [ ] Data validation passed
  - [ ] Application deployment completed
  - [ ] Configuration updated

- [ ] **Post-Migration Tasks**
  - [ ] Functional tests completed
  - [ ] Performance tests passed
  - [ ] User acceptance testing completed
  - [ ] Monitoring enabled

### Post-Migration Checklist

- [ ] **System Validation**
  - [ ] All critical functions working
  - [ ] Performance meets requirements
  - [ ] No data integrity issues
  - [ ] Security controls active

- [ ] **Documentation Updated**
  - [ ] API documentation updated
  - [ ] User guides updated
  - [ ] Operational procedures updated
  - [ ] Migration completed documented

- [ ] **Cleanup Tasks**
  - [ ] Legacy system archived
  - [ ] Temporary migration tools removed
  - [ ] Test data cleaned up
  - [ ] Success metrics reported

## 🆘 Troubleshooting Common Issues

### Issue 1: Duplicate Key Errors During Migration

```sql
-- Problem: Duplicate users or projects during migration
-- Solution: Handle duplicates gracefully

INSERT INTO users (username, email, password_hash, user_hash, created_at)
VALUES (%s, %s, %s, %s, %s)
ON DUPLICATE KEY UPDATE
    email = COALESCE(VALUES(email), email),
    updated_at = NOW();
```

### Issue 2: Missing Foreign Key Relationships

```python
# Problem: User-project relationships not created
# Solution: Ensure proper relationship creation

def fix_missing_relationships():
    cursor.execute("""
        SELECT u.id as user_id, p.id as project_id, 
               CONCAT('fix_', u.user_hash, '_', p.project_hash) as user_project_hash
        FROM users u
        CROSS JOIN projects p
        WHERE NOT EXISTS (
            SELECT 1 FROM user_projects up 
            WHERE up.user_id = u.id AND up.project_id = p.id
        )
        AND u.user_hash IN (
            -- Only for users that should have access
            SELECT DISTINCT user_hash FROM legacy_user_collection_mapping
        )
    """)
```

### Issue 3: Performance Degradation After Migration

```python
# Problem: Slow queries after migration
# Solution: Optimize indexes and queries

def optimize_post_migration():
    cursor.execute("ANALYZE TABLE users, projects, user_projects, user_groups")
    
    # Add missing indexes if needed
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_user_projects_composite 
        ON user_projects(user_id, project_id, is_active)
    """)
    
    cursor.execute("""
        CREATE INDEX IF NOT EXISTS idx_sessions_active 
        ON user_sessions(expires_at, is_active)
    """)
```

### Issue 4: Session Token Conflicts

```python
# Problem: Session tokens from legacy system conflict
# Solution: Invalidate all legacy sessions and force re-login

def handle_session_conflicts():
    # Clear all Redis sessions
    redis_client.flushdb()
    
    # Mark all database sessions as expired
    cursor.execute("""
        UPDATE user_sessions 
        SET is_active = 0, 
            expires_at = NOW()
        WHERE expires_at > NOW()
    """)
    
    print("All sessions invalidated - users will need to re-login")
```

## 📞 Support and Resources

### Migration Support

- **Documentation**: Complete docs in `/docs` folder
- **Test Scripts**: Migration validation scripts included
- **Rollback Procedures**: Detailed rollback instructions provided
- **Performance Monitoring**: Built-in metrics and logging

### Getting Help

1. **Check Documentation**: Review all docs in `/docs` folder
2. **Run Test Scripts**: Use provided validation scripts
3. **Check Logs**: Review application and database logs
4. **Test Rollback**: Ensure rollback procedures work before migration

---

**This migration guide provides a comprehensive approach to safely migrating from legacy authentication systems to the Enhanced Multi-Project Authentication API. Follow the steps carefully and always test thoroughly before production migration.** 