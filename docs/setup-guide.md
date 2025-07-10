# Setup Guide

This guide walks you through setting up the Group-Based Multi-Project Authentication API from scratch to production-ready deployment.

## 📋 Prerequisites

- **Python 3.11+**
- **MySQL 8.0+**
- **Redis 6.0+**
- **pip** and **venv** (recommended)

## 🛠️ Installation

### 1. Clone Repository

```bash
git clone <repository-url>
cd api.auth
```

### 2. Create Virtual Environment

```bash
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
# or
.venv\Scripts\activate     # Windows
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

## 🔧 Configuration

### 1. Environment Variables

Create a `.env` file in the root directory:

```bash
# Database Configuration
DB_HOST=192.168.1.90
DB_USER=root
DB_MYSQL_PASSWORD=your_mysql_password
DB_DATABASE=magic_auth_groups

# Redis Configuration
DB_REDIS_PASSWORD=your_redis_password

# Optional: Custom Redis settings
REDIS_HOST=192.168.1.90
REDIS_PORT=6379
REDIS_DB=0

# Group System Configuration
GROUP_SYSTEM_ENABLED=true

# Optional: Application settings
APP_HOST=0.0.0.0
APP_PORT=8000
DEBUG=false
```

### 2. Database Configuration

The system uses MySQL for persistent storage. Update connection settings in `src/Util/db/db_enhanced.py` if needed:

```python
connectionDB = {
    "host": os.environ.get("DB_HOST", "192.168.1.90"),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_MYSQL_PASSWORD"),
    "database": os.environ.get("DB_DATABASE", "magic_auth_groups"),
    "charset": "utf8mb4",
    "autocommit": True
}
```

### 3. Redis Configuration

Redis is used for advanced cache management including sessions, access checks, and RBAC. Configuration is in `src/Util/db_config.py`:

```python
redis_client = redis.StrictRedis(
    host=os.environ.get("REDIS_HOST", "192.168.1.90"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    db=int(os.environ.get("REDIS_DB", "0")),
    password=os.environ.get("DB_REDIS_PASSWORD"),
    decode_responses=True
)
```

### 4. Cache Configuration

The comprehensive cache system can be configured with environment variables:

```bash
# Cache Configuration
CACHE_ENABLED=true
SESSION_TTL=3600          # 1 hour for sessions
ACCESS_CHECK_TTL=1800     # 30 minutes for access checks
RBAC_CHECK_TTL=1800       # 30 minutes for RBAC checks
USER_TYPE_TTL=3600        # 1 hour for user type info

# Cache Size Limits (optional)
MAX_CACHE_SIZE_MB=50
CACHE_CLEANUP_INTERVAL=3600  # 1 hour
```

## 🗄️ Database Setup

### 1. Create Database

```sql
-- Connect to MySQL as root
mysql -u root -p

-- Create database for group-based system
CREATE DATABASE magic_auth_groups CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Create user (optional, for security)
CREATE USER 'auth_user'@'localhost' IDENTIFIED BY 'secure_password';
GRANT ALL PRIVILEGES ON magic_auth_groups.* TO 'auth_user'@'localhost';
FLUSH PRIVILEGES;
```

### 2. Initialize Group-Based Schema

#### Option 1: Using the New Schema Script (Recommended)

```bash
# Create group-based schema with default groups
mysql -u root -p magic_auth_groups < new_database_schema.sql

# Verify the tables were created
mysql -u root -p magic_auth_groups -e "SHOW TABLES;"
```

#### Option 2: Using Python Initialization Script

```bash
# Initialize with default user and project groups
python group_based_crud_operations.py --init-defaults

# Or create custom initial setup
python group_based_crud_operations.py --create-admin-user admin admin123
```

#### Option 3: Manual Schema Creation

If you prefer to create the schema manually, use the SQL from `docs/database-schema.md`.

### 3. Verify Installation

```bash
# Test database connection
python -c "
from src.Util.db import get_connection
try:
    con = get_connection()
    print('✓ Database connection successful')
    con.close()
except Exception as e:
    print(f'✗ Database connection failed: {e}')
"

# Test Redis connection
python -c "
from src.Util.db import client
try:
    client.ping()
    print('✓ Redis connection successful')
except Exception as e:
    print(f'✗ Redis connection failed: {e}')
"

# Test group-based CRUD operations
python -c "
from group_based_crud_operations import UserGroupCRUD
try:
    groups = UserGroupCRUD.read_all()
    print(f'✓ Group system operational - {len(groups)} user groups found')
except Exception as e:
    print(f'✗ Group system failed: {e}')
"
```

## 🚀 Running the Application

### 1. Development Mode

```bash
# Start with auto-reload and group system enabled
python -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000

# With debug logging
python -m uvicorn src.main:app --reload --log-level debug
```

### 2. Production Mode

```bash
# Basic production setup
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000 --workers 4

# With Gunicorn (recommended)
pip install gunicorn
gunicorn src.main:app -w 4 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:8000
```

### 3. Docker Deployment

```bash
# Build image
docker build -t group-auth-api .

# Run container with group system enabled
docker run -d -p 8000:8000 --name group-auth-api \
  -e DB_MYSQL_PASSWORD=your_password \
  -e DB_REDIS_PASSWORD=your_redis_password \
  -e GROUP_SYSTEM_ENABLED=true \
  group-auth-api
```

### 4. Docker Compose (Full Stack)

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  group-auth-api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DB_HOST=mysql
      - DB_MYSQL_PASSWORD=rootpassword
      - DB_REDIS_PASSWORD=redispassword
      - DB_DATABASE=magic_auth_groups
      - GROUP_SYSTEM_ENABLED=true
    depends_on:
      - mysql
      - redis

  mysql:
    image: mysql:8.0
    environment:
      - MYSQL_ROOT_PASSWORD=rootpassword
      - MYSQL_DATABASE=magic_auth_groups
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql
      - ./new_database_schema.sql:/docker-entrypoint-initdb.d/init.sql

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass redispassword
    ports:
      - "6379:6379"

volumes:
  mysql_data:
```

## 🧪 Testing Installation

### 1. API Health Check

```bash
# Test basic connectivity
curl http://localhost:8000/ping

# Get system information
curl http://localhost:8000/system/info

# Check group system health
curl http://localhost:8000/system/groups/health
```

### 2. Group System Testing

If you initialized with default data:

```bash
# Test admin login (if default admin was created)
curl -X POST "http://localhost:8000/user/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=YOUR_PROJECT_HASH"

# Test user group functionality
curl -X GET "http://localhost:8000/user/access-summary" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

### 3. Group-Based Operations Test

```bash
# Run the test script
python test_modular_structure.py

# Test group-based CRUD operations
python -c "
from group_based_crud_operations import *

# Test user group creation
admin_group = UserGroupCRUD.create('test_admins', 'Test administrators')
print(f'Created user group: {admin_group.group_name}')

# Test project group creation
full_access = ProjectGroupCRUD.create('test_full_access', ['admin', 'read', 'write'])
print(f'Created project group: {full_access.group_name}')

print('✓ Group-based CRUD operations working correctly')
"

# Test cache system
python -c "
from src.Util.cache_manager import cache_manager

# Test cache connectivity
try:
    cache_manager.redis_client.ping()
    print('✓ Cache system operational')
    
    # Test cache operations
    cache_manager.set_session('test_token', {'user_id': 1, 'test': True})
    cached_session = cache_manager.get_session('test_token')
    
    if cached_session and cached_session.get('test'):
        print('✓ Cache read/write operations working')
    else:
        print('✗ Cache operations failed')
        
    # Clean up test data
    cache_manager.invalidate_user_cache(1)
    print('✓ Cache invalidation working')
    
except Exception as e:
    print(f'✗ Cache system failed: {e}')
"

# Test RBAC initialization (requires admin token and project hash)
echo "NOTE: The following RBAC test requires a valid admin session token and project hash."
# curl -X POST "http://localhost:8000/rbac/projects/YOUR_PROJECT_HASH/initialize" -H "Authorization: Bearer YOUR_ADMIN_TOKEN"
```

## 🔒 Security Configuration

### 1. Group-Based Security

The system implements hierarchical group-based security:

```python
# Configure default user groups in group_based_crud_operations.py
DEFAULT_USER_GROUPS = {
    "administrators": {
        "description": "System administrators with full access",
        "default_permissions": ["admin", "create_projects", "manage_groups"]
    },
    "users": {
        "description": "Standard users with project access",
        "default_permissions": ["read", "write"]
    },
    "guests": {
        "description": "Limited read-only access",
        "default_permissions": ["read"]
    }
}
```

### 2. Session Security

Configure group-aware session settings:

```python
# Session expiration (default: 3 days)
SESSION_EXPIRE_SECONDS = 3 * 24 * 60 * 60

# Token length (default: 32 bytes)
TOKEN_LENGTH = 32

# Group context in sessions
INCLUDE_GROUP_CONTEXT = True
```

### 3. CORS Configuration

Update CORS settings in `src/main.py`:

```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Replace with your domain
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"]
)
```

## 📊 Monitoring & Logging

### 1. Group-Aware Application Logs

Logs are handled by `src/Util/logger_ws.py` with group context. Configure log levels:

```python
import logging

# Set log level
logging.basicConfig(level=logging.INFO)

# For debug mode with group information
logging.basicConfig(level=logging.DEBUG)
```

### 2. Database Monitoring

Monitor group-based database performance:

```sql
-- Check group relationships
SELECT 
    'User Groups' as entity,
    COUNT(*) as total,
    SUM(is_active) as active
FROM user_groups
UNION ALL
SELECT 
    'Project Groups' as entity,
    COUNT(*) as total,
    SUM(is_active) as active
FROM project_groups;

-- Check group membership counts
SELECT 
    ug.group_name,
    COUNT(ugm.user_id) as member_count
FROM user_groups ug
LEFT JOIN user_group_members ugm ON ug.id = ugm.user_group_id AND ugm.is_active = 1
WHERE ug.is_active = 1
GROUP BY ug.id, ug.group_name;
```

### 3. Redis & Cache Monitoring

```bash
# Redis CLI monitoring with cache context
redis-cli monitor | grep -E "(session|access|rbac|user_type)"

# Check cache-related data
redis-cli --scan --pattern "session:*" | head -10
redis-cli --scan --pattern "access_check:*" | head -10
redis-cli --scan --pattern "rbac:*" | head -10
redis-cli --scan --pattern "user_type:*" | head -10

# Check memory usage and cache statistics
redis-cli info memory
redis-cli info stats

# Monitor cache hit rates (if available)
redis-cli --latency -i 1
```

### 4. Cache Performance Monitoring

```bash
# Test cache performance via API
curl -X GET "http://localhost:8000/system/cache/stats" \
  -H "Authorization: Bearer ADMIN_TOKEN"

# Monitor cache invalidation events
tail -f logs/cache.log | grep -E "(invalidat|clear|flush)"

# Check cache health in system monitoring
curl -X GET "http://localhost:8000/system/health" | jq '.components.cache'
```

## 🔄 Backup & Maintenance

### 1. Database Backup

```bash
# Create backup of group-based system
mysqldump -u root -p magic_auth_groups > backup_groups_$(date +%Y%m%d_%H%M%S).sql

# Backup only group-related tables
mysqldump -u root -p magic_auth_groups \
  users user_groups user_group_members \
  projects project_groups project_group_members \
  user_group_projects user_sessions \
  > group_backup.sql

# Restore backup
mysql -u root -p magic_auth_groups < backup_file.sql
```

### 2. Redis Backup

```bash
# Create Redis backup
redis-cli save
cp /var/lib/redis/dump.rdb backup_redis_groups_$(date +%Y%m%d_%H%M%S).rdb
```

### 3. Group System Maintenance

```sql
-- Clean expired sessions (run daily)
DELETE FROM user_sessions 
WHERE expires_at < NOW() OR is_active = 0;

-- Archive old group assignments (run monthly)
UPDATE user_group_members 
SET is_active = 0 
WHERE removed_at < DATE_SUB(NOW(), INTERVAL 6 MONTH);

-- Update group statistics
UPDATE user_groups ug
SET updated_at = NOW()
WHERE EXISTS (
    SELECT 1 FROM user_group_members ugm 
    WHERE ugm.user_group_id = ug.id AND ugm.assigned_at > DATE_SUB(NOW(), INTERVAL 1 DAY)
);
```

## 🛠️ Troubleshooting

### Common Issues

1. **Group System Import Errors**
   ```bash
   # Ensure you're in the correct directory and virtual environment
   pwd  # Should be in the api.auth directory
   which python  # Should point to .venv/bin/python
   
   # Test group module imports
   python -c "from group_based_crud_operations import UserGroupCRUD; print('✓ Group imports working')"
   ```

2. **Database Connection Errors**
   ```bash
   # Check MySQL service
   sudo systemctl status mysql
   
   # Test connection manually
   mysql -h 192.168.1.90 -u root -p -D magic_auth_groups
   
   # Verify tables exist
   mysql -u root -p magic_auth_groups -e "SHOW TABLES LIKE '%group%';"
   ```

3. **Group System Not Working**
   ```bash
   # Check if group tables exist
   mysql -u root -p magic_auth_groups -e "
   SELECT TABLE_NAME FROM information_schema.TABLES 
   WHERE TABLE_SCHEMA = 'magic_auth_groups' 
   AND TABLE_NAME LIKE '%group%';
   "
   
   # Initialize default groups if missing
   python group_based_crud_operations.py --init-defaults
   ```

4. **Redis Connection Errors**
   ```bash
   # Check Redis service
   sudo systemctl status redis
   
   # Test connection with group context
   redis-cli -h 192.168.1.90 -a your_password ping
   ```

### Debug Mode

Enable debug mode for troubleshooting:

```bash
# Set environment variable
export DEBUG=true
export GROUP_SYSTEM_ENABLED=true

# Or run with debug logging
python -m uvicorn src.main:app --reload --log-level debug
```

### Group System Diagnostics

```bash
# Run group system diagnostics
python -c "
from group_based_crud_operations import *

print('=== Group System Diagnostics ===')

# Check user groups
user_groups = UserGroupCRUD.read_all()
print(f'User Groups: {len(user_groups)}')
for group in user_groups:
    print(f'  - {group.group_name}: {group.description}')

# Check project groups
project_groups = ProjectGroupCRUD.read_all()
print(f'Project Groups: {len(project_groups)}')
for group in project_groups:
    print(f'  - {group.group_name}: {group.permissions}')

print('✓ Group system operational')
"
```

## 📚 Next Steps

After successful installation:

1. **Read the [API Reference](api-reference.md)** for detailed endpoint documentation
2. **Review the [Database Schema](database-schema.md)** to understand the group structure
3. **Check the [Architecture Guide](architecture.md)** for system design details
4. **Set up your first user groups** and assign users
5. **Create project groups** and assign projects
6. **Test the group-based access control** through the API

## 🆘 Getting Help

If you encounter issues:

1. Check the troubleshooting section above
2. Review the logs in debug mode
3. Test individual components (database, Redis, groups)
4. Verify group system is properly initialized
5. Refer to the detailed documentation in the `docs/` folder

## 🎯 Group System Quick Start

Once installed, quickly test the group system:

```bash
# 1. Create a user group
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -d '{"group_name": "developers", "description": "Development team"}'

# 2. Create a project group
curl -X POST "http://localhost:8000/admin/project-groups" \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -d '{"group_name": "api-access", "permissions": ["read", "write", "api"]}'

# 3. Test user group assignment
curl -X POST "http://localhost:8000/admin/assign-user-to-group" \
  -H "Authorization: Bearer ADMIN_TOKEN" \
  -d '{"username": "john_doe", "group_name": "developers"}'
```

---

**🎉 You're ready to use the Group-Based Multi-Project Authentication API!** 