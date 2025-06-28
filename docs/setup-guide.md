# Setup Guide

This guide walks you through setting up the Enhanced Multi-Project Authentication API from scratch to production-ready deployment.

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
DB_DATABASE=magic_auth_enhanced

# Redis Configuration
DB_REDIS_PASSWORD=your_redis_password

# Optional: Custom Redis settings
REDIS_HOST=192.168.1.90
REDIS_PORT=6379
REDIS_DB=0

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
    "database": os.environ.get("DB_DATABASE", "magic_auth_enhanced"),
    "charset": "utf8mb4",
    "autocommit": True
}
```

### 3. Redis Configuration

Redis is used for session caching. Configuration is in `src/Util/db/db_enhanced.py`:

```python
client = redis.StrictRedis(
    host=os.environ.get("REDIS_HOST", "192.168.1.90"),
    port=int(os.environ.get("REDIS_PORT", "6379")),
    db=int(os.environ.get("REDIS_DB", "0")),
    password=os.environ.get("DB_REDIS_PASSWORD"),
    decode_responses=True
)
```

## 🗄️ Database Setup

### 1. Create Database

```sql
-- Connect to MySQL as root
mysql -u root -p

-- Create database
CREATE DATABASE magic_auth_enhanced CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Create user (optional, for security)
CREATE USER 'auth_user'@'localhost' IDENTIFIED BY 'secure_password';
GRANT ALL PRIVILEGES ON magic_auth_enhanced.* TO 'auth_user'@'localhost';
FLUSH PRIVILEGES;
```

### 2. Initialize Schema

#### Option 1: Using the Setup Script (Recommended)

```bash
# Create schema with sample data
python setup_enhanced_auth.py --with-sample-data

# Or create schema only
python setup_enhanced_auth.py
```

#### Option 2: Manual Schema Creation

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
```

## 🚀 Running the Application

### 1. Development Mode

```bash
# Start with auto-reload
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
docker build -t auth-api .

# Run container
docker run -d -p 8000:8000 --name auth-api \
  -e DB_MYSQL_PASSWORD=your_password \
  -e DB_REDIS_PASSWORD=your_redis_password \
  auth-api
```

### 4. Docker Compose (Full Stack)

Create `docker-compose.yml`:

```yaml
version: '3.8'

services:
  auth-api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DB_HOST=mysql
      - DB_MYSQL_PASSWORD=rootpassword
      - DB_REDIS_PASSWORD=redispassword
    depends_on:
      - mysql
      - redis

  mysql:
    image: mysql:8.0
    environment:
      - MYSQL_ROOT_PASSWORD=rootpassword
      - MYSQL_DATABASE=magic_auth_enhanced
    ports:
      - "3306:3306"
    volumes:
      - mysql_data:/var/lib/mysql

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
```

### 2. Sample Data Testing

If you used `--with-sample-data`:

```bash
# Test admin login
curl -X POST "http://localhost:8000/user/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=YOUR_PROJECT_HASH"

# Test user login
curl -X POST "http://localhost:8000/user/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john_doe&password=password123&project_hash=YOUR_PROJECT_HASH"
```

### 3. Module Structure Test

```bash
# Verify modular database structure
python test_modular_structure.py

# Run API tests
python -m pytest tests/ -v  # if you have tests
```

## 🔒 Security Configuration

### 1. Password Security

The system uses SHA256 hashing for password storage. For production, consider:

```python
# In db_users.py, you can customize password hashing
import hashlib
import secrets

def hash_password(password: str, salt: str = None) -> tuple[str, str]:
    if not salt:
        salt = secrets.token_hex(16)
    
    password_hash = hashlib.sha256((password + salt).encode()).hexdigest()
    return password_hash, salt
```

### 2. Session Security

Configure session settings:

```python
# Session expiration (default: 3 days)
SESSION_EXPIRE_SECONDS = 3 * 24 * 60 * 60

# Token length (default: 32 bytes)
TOKEN_LENGTH = 32
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

### 1. Application Logs

Logs are handled by `src/Util/logger_ws.py`. Configure log levels:

```python
import logging

# Set log level
logging.basicConfig(level=logging.INFO)

# For debug mode
logging.basicConfig(level=logging.DEBUG)
```

### 2. Database Monitoring

Monitor database performance:

```sql
-- Check connection count
SHOW STATUS LIKE 'Threads_connected';

-- Check query performance
SHOW PROCESSLIST;

-- Check table sizes
SELECT 
    table_name,
    round(((data_length + index_length) / 1024 / 1024), 2) as 'Size (MB)'
FROM information_schema.tables 
WHERE table_schema = 'magic_auth_enhanced';
```

### 3. Redis Monitoring

```bash
# Redis CLI monitoring
redis-cli monitor

# Check memory usage
redis-cli info memory

# Check connected clients
redis-cli info clients
```

## 🔄 Backup & Maintenance

### 1. Database Backup

```bash
# Create backup
mysqldump -u root -p magic_auth_enhanced > backup_$(date +%Y%m%d_%H%M%S).sql

# Restore backup
mysql -u root -p magic_auth_enhanced < backup_file.sql
```

### 2. Redis Backup

```bash
# Create Redis backup
redis-cli save
cp /var/lib/redis/dump.rdb backup_redis_$(date +%Y%m%d_%H%M%S).rdb
```

### 3. Cleanup Tasks

```sql
-- Clean expired sessions (run daily)
DELETE FROM user_sessions 
WHERE expires_at < NOW() OR is_active = 0;

-- Archive old audit logs (run monthly)
DELETE FROM user_sessions 
WHERE created_at < DATE_SUB(NOW(), INTERVAL 6 MONTH);
```

## 🛠️ Troubleshooting

### Common Issues

1. **Module Import Errors**
   ```bash
   # Ensure you're in the correct directory and virtual environment
   pwd  # Should be in the api.auth directory
   which python  # Should point to .venv/bin/python
   ```

2. **Database Connection Errors**
   ```bash
   # Check MySQL service
   sudo systemctl status mysql
   
   # Test connection manually
   mysql -h 192.168.1.90 -u root -p
   ```

3. **Redis Connection Errors**
   ```bash
   # Check Redis service
   sudo systemctl status redis
   
   # Test connection
   redis-cli -h 192.168.1.90 -a your_password ping
   ```

4. **Permission Errors**
   ```bash
   # Check file permissions
   ls -la src/
   
   # Fix permissions if needed
   chmod +x setup_enhanced_auth.py
   ```

### Debug Mode

Enable debug mode for troubleshooting:

```bash
# Set environment variable
export DEBUG=true

# Or run with debug logging
python -m uvicorn src.main:app --reload --log-level debug
```

## 📚 Next Steps

After successful installation:

1. **Read the [API Reference](api-reference.md)** for detailed endpoint documentation
2. **Review the [Database Schema](database-schema.md)** to understand the data structure
3. **Check the [Architecture Guide](architecture.md)** for system design details
4. **Set up your first project** and users through the API

## 🆘 Getting Help

If you encounter issues:

1. Check the troubleshooting section above
2. Review the logs in debug mode
3. Test individual components (database, Redis, modules)
4. Refer to the detailed documentation in the `docs/` folder

---

**🎉 You're ready to use the Enhanced Multi-Project Authentication API!** 